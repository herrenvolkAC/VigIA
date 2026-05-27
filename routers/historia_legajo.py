"""
VigIA - Historia de legajo.

Vista transversal de datos locales de RRHH, TNC y productividad.
"""
from __future__ import annotations

import asyncio
import os
import logging
from contextlib import suppress
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

import aiosqlite
from fastapi import APIRouter, HTTPException, Query

from db.schema import DB_PATH
from routers.productividad_analisis import (
    query_productive_db_historia_actividad_operaciones_bulk,
    query_productive_db_historia_actividad_operaciones,
    query_productive_db_historia_productividad_legajo,
    query_productive_db_historia_tnc_legajo,
)

router = APIRouter(prefix="/api/historia-legajo", tags=["historia-legajo"])
logger = logging.getLogger("vigia.historia_legajo")
MAX_ACTIVIDAD_OPERACIONES_ORACLE_DAYS = 15
ACTIVIDAD_SYNC_LOCK_NAME = "historia_actividad_operaciones"
_actividad_scheduler_task: asyncio.Task | None = None
_actividad_scheduler_stop: asyncio.Event | None = None
REAL_SANCIONES = (
    "Amonestación",
    "AmonestaciÃ³n",
    "Anotaciones Especiales",
    "Llamada de Atención Escrita",
    "Llamada de AtenciÃ³n Escrita",
    "Suspensión",
    "SuspensiÃ³n",
)
REAL_SANCION_CODES = ("03", "97", "98", "99")


def _norm_legajo(value: Any) -> str:
    text = str(value or "").strip()
    return text.lstrip("0") or text


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _net_minutes(row: dict[str, Any]) -> float:
    return max(
        0.0,
        _to_float(row.get("minutos_productivos"))
        - _to_float(row.get("minutos_entrega_primer"))
        - _to_float(row.get("minutos_ultimo_devol")),
    )


def _today() -> str:
    return date.today().isoformat()


def _date_to_str(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "").strip()


def _date_to_oracle_key(value: str) -> str:
    return value.replace("-", "")[:8]


def _oracle_date_to_iso(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _iter_date_strings(fecha_desde: str, fecha_hasta: str) -> list[str]:
    start = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
    end = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
    total = (end - start).days
    return [(start + timedelta(days=offset)).isoformat() for offset in range(total + 1)]


def _date_ranges(days: list[str], max_days: int = 180) -> list[tuple[str, str]]:
    if not days:
        return []
    ordered = sorted(days)
    ranges = []
    start = prev = datetime.strptime(ordered[0], "%Y-%m-%d").date()
    for value in ordered[1:]:
        current = datetime.strptime(value, "%Y-%m-%d").date()
        if current == prev + timedelta(days=1) and (current - start).days < max_days:
            prev = current
            continue
        ranges.append((start.isoformat(), prev.isoformat()))
        start = prev = current
    ranges.append((start.isoformat(), prev.isoformat()))
    return ranges


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "on"}


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _parse_hhmm(value: str) -> time:
    hour, minute = value.strip().split(":", 1)
    return time(int(hour), int(minute))


def _parse_sync_windows() -> list[tuple[time, time, str]]:
    raw = os.getenv("HISTORIA_ACTIVIDAD_SYNC_WINDOWS", "21:00-22:00,05:00-06:00")
    windows = []
    for item in raw.split(","):
        if "-" not in item:
            continue
        start_raw, end_raw = item.split("-", 1)
        try:
            start = _parse_hhmm(start_raw)
            end = _parse_hhmm(end_raw)
        except Exception:
            continue
        windows.append((start, end, f"{start_raw.strip()}-{end_raw.strip()}"))
    return windows


def _time_in_window(current: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def _current_sync_window(now: datetime | None = None) -> str | None:
    current = (now or datetime.now()).time()
    for start, end, label in _parse_sync_windows():
        if _time_in_window(current, start, end):
            return label
    return None


def _sync_fecha_desde() -> str:
    configured = os.getenv("HISTORIA_ACTIVIDAD_SYNC_START_DATE", "").strip()
    if configured:
        return configured
    return date(date.today().year, 1, 1).isoformat()


def _sync_fecha_hasta() -> str:
    offset = _env_int("HISTORIA_ACTIVIDAD_SYNC_END_OFFSET_DAYS", 1, minimum=0, maximum=30)
    return (date.today() - timedelta(days=offset)).isoformat()


async def _latest_batch_id(db: aiosqlite.Connection) -> int | None:
    async with db.execute(
        """
        SELECT batch_id
        FROM rrhh_import_batches
        WHERE status = 'complete'
        ORDER BY imported_at DESC, batch_id DESC
        LIMIT 1
        """
    ) as cur:
        row = await cur.fetchone()
    return int(row["batch_id"]) if row else None


async def _legajo_profile(db: aiosqlite.Connection, legajo: str, batch_id: int | None) -> dict[str, Any] | None:
    if not batch_id:
        return None
    async with db.execute(
        """
        SELECT legajo, nombre, empresa, proveedor, razon_social,
               desc_sector_generico, desc_funcion, desc_posicion,
               desc_grupo_personal, desc_area_personal, desc_unidad_organizativa,
               fecha_ingreso, fecha_baja
        FROM rrhh_legajero
        WHERE batch_id = ?
          AND legajo = ?
        LIMIT 1
        """,
        (batch_id, _norm_legajo(legajo)),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    data = dict(row)
    return {
        "legajo": data.get("legajo"),
        "nombre": data.get("nombre"),
        "empresa": data.get("empresa"),
        "proveedor": data.get("proveedor"),
        "razon_social": data.get("razon_social"),
        "sector": data.get("desc_sector_generico"),
        "cargo": data.get("desc_funcion"),
        "posicion": data.get("desc_posicion"),
        "grupo_personal": data.get("desc_grupo_personal"),
        "area_personal": data.get("desc_area_personal"),
        "unidad": data.get("desc_unidad_organizativa"),
        "fecha_ingreso": data.get("fecha_ingreso"),
        "fecha_baja": data.get("fecha_baja"),
    }


def _timeline_item(fecha: str, tipo: str, titulo: str, detalle: str = "", meta: str = "") -> dict[str, str]:
    return {"fecha": fecha or "", "tipo": tipo, "titulo": titulo or "-", "detalle": detalle or "", "meta": meta or ""}


async def _fetch_productividad_rows(
    db: aiosqlite.Connection,
    legajo: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> list[dict[str, Any]]:
    """Fuente local actual. Punto de reemplazo para Oracle en la proxima etapa."""
    async with db.execute(
        """
        SELECT fecha_operativa, turno_label, almacen, primer_traspaso,
               minutos_productivos, minutos_entrega_primer, minutos_ultimo_devol,
               traspasos, bultos, sesion_incompleta, excede_turno
        FROM gestion_productividad_picking_segments
        WHERE copecrea = ?
          AND fecha_operativa >= ?
          AND fecha_operativa <= ?
        ORDER BY fecha_operativa DESC, primer_traspaso DESC
        """,
        (legajo, fecha_desde, fecha_hasta),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def _fetch_productividad_real_rows(
    legajo: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> tuple[list[dict[str, Any]], str, str | None]:
    try:
        raw_rows = await asyncio.to_thread(
            query_productive_db_historia_productividad_legajo,
            _date_to_oracle_key(fecha_desde),
            _date_to_oracle_key(fecha_hasta),
            legajo,
        )
    except Exception as exc:
        logger.warning("No se pudo consultar productividad real Oracle para legajo=%s: %s", legajo, exc)
        return [], "oracle_error", str(exc)

    rows = []
    for row in raw_rows:
        data = {str(key).lower(): value for key, value in row.items()}
        rows.append(
            {
                "fecha": _oracle_date_to_iso(data.get("fecha")),
                "funcion": data.get("funcion") or "",
                "prod_real": round(_to_float(data.get("prod_real")), 2),
                "prod_equivalente": round(_to_float(data.get("prod_equival_por_sector")), 2),
            }
        )
    return rows, "oracle", None


async def _query_actividad_operaciones_oracle(
    legajo: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> list[dict[str, Any]]:
    raw_rows = await asyncio.to_thread(
        query_productive_db_historia_actividad_operaciones,
        fecha_desde,
        fecha_hasta,
        legajo,
    )
    rows = []
    grouped: dict[str, set[str]] = {}
    for row in raw_rows:
        data = {str(key).lower(): value for key, value in row.items()}
        fecha = _oracle_date_to_iso(data.get("fecha"))
        operacion = str(data.get("operacion") or data.get("cdescrip") or "").strip()
        if fecha and operacion:
            grouped.setdefault(fecha, set()).add(operacion)
    for fecha, operaciones in grouped.items():
        ordered = sorted(operaciones)
        rows.append(
            {
                "fecha": fecha,
                "operaciones": "; ".join(ordered),
                "source_rows_count": len(ordered),
                "source_name": "oracle_productiva",
            }
        )
    rows.sort(key=lambda item: item["fecha"])
    return rows


async def _query_actividad_operaciones_oracle_bulk(
    fecha_desde: str,
    fecha_hasta: str,
) -> list[dict[str, Any]]:
    raw_rows = await asyncio.to_thread(
        query_productive_db_historia_actividad_operaciones_bulk,
        fecha_desde,
        fecha_hasta,
    )
    rows = []
    for row in raw_rows:
        data = {str(key).lower(): value for key, value in row.items()}
        legajo = _norm_legajo(data.get("legajo") or data.get("copecrea"))
        fecha = _oracle_date_to_iso(data.get("fecha"))
        operacion = str(data.get("operacion") or data.get("cdescrip") or "").strip()
        if legajo and fecha and operacion:
            rows.append({"legajo": legajo, "fecha": fecha, "operacion": operacion})
    return rows


async def _load_cached_actividad_operaciones(
    db: aiosqlite.Connection,
    legajo: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT legajo, fecha, operaciones, source_rows_count, source_name, synced_at
        FROM historia_legajo_actividad_operaciones
        WHERE legajo = ?
          AND fecha >= ?
          AND fecha <= ?
        ORDER BY fecha
        """,
        (legajo, fecha_desde, fecha_hasta),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def _store_actividad_operaciones(
    db: aiosqlite.Connection,
    legajo: str,
    rows_by_date: dict[str, dict[str, Any]],
    days: list[str],
) -> None:
    for day in days:
        row = rows_by_date.get(day, {})
        await db.execute(
            """
            INSERT INTO historia_legajo_actividad_operaciones
                (legajo, fecha, operaciones, source_rows_count, source_name, synced_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(legajo, fecha) DO UPDATE SET
                operaciones = excluded.operaciones,
                source_rows_count = excluded.source_rows_count,
                source_name = excluded.source_name,
                synced_at = CURRENT_TIMESTAMP
            """,
            (
                legajo,
                day,
                row.get("operaciones") or "",
                int(row.get("source_rows_count") or 0),
                row.get("source_name") or "oracle_productiva",
            ),
        )


async def _latest_active_legajos(db: aiosqlite.Connection) -> list[str]:
    batch_id = await _latest_batch_id(db)
    if not batch_id:
        return []
    today = _today()
    async with db.execute(
        """
        SELECT DISTINCT legajo
        FROM rrhh_legajero
        WHERE batch_id = ?
          AND TRIM(COALESCE(legajo, '')) <> ''
          AND (
              COALESCE(fecha_baja, '') = ''
              OR fecha_baja = '9999-12-31'
              OR fecha_baja > ?
          )
        ORDER BY legajo
        """,
        (batch_id, today),
    ) as cur:
        return [_norm_legajo(row["legajo"]) for row in await cur.fetchall()]


async def _missing_actividad_days(
    db: aiosqlite.Connection,
    legajos: list[str],
    fecha_desde: str,
    fecha_hasta: str,
) -> list[dict[str, Any]]:
    if not legajos:
        return []
    all_days = _iter_date_strings(fecha_desde, fecha_hasta)
    active_legajos = set(legajos)
    cached_by_day: dict[str, set[str]] = {day: set() for day in all_days}
    async with db.execute(
        """
        SELECT fecha, legajo
        FROM historia_legajo_actividad_operaciones
        WHERE fecha >= ?
          AND fecha <= ?
        """,
        (fecha_desde, fecha_hasta),
    ) as cur:
        async for row in cur:
            fecha = str(row["fecha"])
            legajo = _norm_legajo(row["legajo"])
            if fecha in cached_by_day and legajo in active_legajos:
                cached_by_day[fecha].add(legajo)
    expected = len(active_legajos)
    return [
        {"fecha": day, "missing": max(0, expected - len(cached_by_day.get(day, set()))), "cached": len(cached_by_day.get(day, set()))}
        for day in all_days
        if len(cached_by_day.get(day, set())) < expected
    ]


async def _create_sync_run(db: aiosqlite.Connection, *, trigger: str, window_label: str | None) -> int:
    cur = await db.execute(
        """
        INSERT INTO historia_legajo_actividad_sync_runs
            (trigger, status, window_label, started_at, heartbeat_at)
        VALUES (?, 'running', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (trigger, window_label),
    )
    await db.commit()
    return int(cur.lastrowid)


async def _try_acquire_actividad_sync_lock(
    db: aiosqlite.Connection,
    *,
    owner: str,
    run_id: int,
) -> bool:
    stale_minutes = _env_int("HISTORIA_ACTIVIDAD_SYNC_STALE_MINUTES", 15, minimum=2, maximum=180)
    await db.execute("BEGIN IMMEDIATE")
    async with db.execute(
        """
        SELECT status, heartbeat_at
        FROM historia_legajo_actividad_sync_lock
        WHERE lock_name = ?
        """,
        (ACTIVIDAD_SYNC_LOCK_NAME,),
    ) as cur:
        row = await cur.fetchone()
    if row and row["status"] == "running" and row["heartbeat_at"]:
        try:
            heartbeat = datetime.fromisoformat(str(row["heartbeat_at"]).replace(" ", "T"))
        except ValueError:
            heartbeat = datetime.min
        if datetime.now() - heartbeat < timedelta(minutes=stale_minutes):
            await db.rollback()
            return False
    await db.execute(
        """
        INSERT INTO historia_legajo_actividad_sync_lock
            (lock_name, status, owner, run_id, started_at, heartbeat_at, updated_at, error)
        VALUES (?, 'running', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)
        ON CONFLICT(lock_name) DO UPDATE SET
            status = 'running',
            owner = excluded.owner,
            run_id = excluded.run_id,
            started_at = CURRENT_TIMESTAMP,
            heartbeat_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP,
            error = NULL
        """,
        (ACTIVIDAD_SYNC_LOCK_NAME, owner, run_id),
    )
    await db.commit()
    return True


async def _sync_heartbeat(db: aiosqlite.Connection, run_id: int) -> None:
    await db.execute(
        """
        UPDATE historia_legajo_actividad_sync_runs
        SET heartbeat_at = CURRENT_TIMESTAMP
        WHERE run_id = ?
        """,
        (run_id,),
    )
    await db.execute(
        """
        UPDATE historia_legajo_actividad_sync_lock
        SET heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE lock_name = ?
        """,
        (ACTIVIDAD_SYNC_LOCK_NAME,),
    )
    await db.commit()


async def _finish_sync_run(
    db: aiosqlite.Connection,
    run_id: int,
    *,
    status: str,
    error: str | None = None,
    metrics: dict[str, Any] | None = None,
    release_lock: bool = True,
) -> None:
    metrics = metrics or {}
    await db.execute(
        """
        UPDATE historia_legajo_actividad_sync_runs
        SET status = ?,
            fecha_desde = COALESCE(?, fecha_desde),
            fecha_hasta = COALESCE(?, fecha_hasta),
            days_attempted = COALESCE(?, days_attempted),
            legajos_scope_count = COALESCE(?, legajos_scope_count),
            cache_rows_written = COALESCE(?, cache_rows_written),
            active_rows_written = COALESCE(?, active_rows_written),
            oracle_rows_count = COALESCE(?, oracle_rows_count),
            finished_at = CURRENT_TIMESTAMP,
            heartbeat_at = CURRENT_TIMESTAMP,
            duration_seconds = ROUND((JULIANDAY(CURRENT_TIMESTAMP) - JULIANDAY(started_at)) * 86400, 2),
            error = ?
        WHERE run_id = ?
        """,
        (
            status,
            metrics.get("fecha_desde"),
            metrics.get("fecha_hasta"),
            metrics.get("days_attempted"),
            metrics.get("legajos_scope_count"),
            metrics.get("cache_rows_written"),
            metrics.get("active_rows_written"),
            metrics.get("oracle_rows_count"),
            error,
            run_id,
        ),
    )
    if release_lock:
        await db.execute(
            """
            UPDATE historia_legajo_actividad_sync_lock
            SET status = ?,
                owner = NULL,
                run_id = NULL,
                heartbeat_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                error = ?
            WHERE lock_name = ?
            """,
            ("idle" if status == "ok" else status, error, ACTIVIDAD_SYNC_LOCK_NAME),
        )
    await db.commit()


async def _store_actividad_operaciones_bulk(
    db: aiosqlite.Connection,
    *,
    legajos: list[str],
    days: list[str],
    oracle_rows: list[dict[str, Any]],
) -> dict[str, int]:
    active_legajos = set(legajos)
    grouped: dict[tuple[str, str], set[str]] = {}
    for row in oracle_rows:
        legajo = _norm_legajo(row.get("legajo"))
        fecha = str(row.get("fecha") or "")
        operacion = str(row.get("operacion") or "").strip()
        if legajo in active_legajos and fecha in days and operacion:
            grouped.setdefault((legajo, fecha), set()).add(operacion)

    written = 0
    active_written = 0
    for day in days:
        for legajo in legajos:
            operaciones = sorted(grouped.get((legajo, day), set()))
            if operaciones:
                active_written += 1
            await db.execute(
                """
                INSERT INTO historia_legajo_actividad_operaciones
                    (legajo, fecha, operaciones, source_rows_count, source_name, synced_at)
                VALUES (?, ?, ?, ?, 'oracle_productiva_bulk', CURRENT_TIMESTAMP)
                ON CONFLICT(legajo, fecha) DO UPDATE SET
                    operaciones = excluded.operaciones,
                    source_rows_count = excluded.source_rows_count,
                    source_name = excluded.source_name,
                    synced_at = CURRENT_TIMESTAMP
                """,
                (legajo, day, "; ".join(operaciones), len(operaciones)),
            )
            written += 1
    await db.commit()
    return {"cache_rows_written": written, "active_rows_written": active_written}


async def run_actividad_operaciones_sync_once(*, trigger: str = "manual", force_window: bool = False) -> dict[str, Any]:
    if not _env_bool("HISTORIA_ACTIVIDAD_SYNC_ENABLED", True):
        return {"status": "disabled", "detail": "HISTORIA_ACTIVIDAD_SYNC_ENABLED=0"}

    window_label = _current_sync_window()
    if not force_window and not window_label:
        return {"status": "outside_window", "detail": "Fuera de ventana configurada."}

    owner = f"{os.getpid()}-{uuid4().hex[:8]}"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        db.row_factory = aiosqlite.Row
        run_id = await _create_sync_run(db, trigger=trigger, window_label=window_label)
        acquired = await _try_acquire_actividad_sync_lock(db, owner=owner, run_id=run_id)
        if not acquired:
            await _finish_sync_run(db, run_id, status="skipped", error="Ya hay una sincronizacion activa.", release_lock=False)
            return {"status": "skipped", "run_id": run_id, "detail": "Ya hay una sincronizacion activa."}

        metrics: dict[str, Any] = {}
        try:
            fecha_desde = _sync_fecha_desde()
            fecha_hasta = _sync_fecha_hasta()
            if fecha_desde > fecha_hasta:
                metrics.update({"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta})
                await _finish_sync_run(db, run_id, status="ok", metrics=metrics)
                return {"status": "ok", "run_id": run_id, "detail": "No hay rango para sincronizar."}

            legajos = await _latest_active_legajos(db)
            max_legajos = _env_int("HISTORIA_ACTIVIDAD_SYNC_MAX_LEGAJOS", 0, minimum=0)
            if max_legajos:
                legajos = legajos[:max_legajos]
            missing = await _missing_actividad_days(db, legajos, fecha_desde, fecha_hasta)
            max_days = _env_int("HISTORIA_ACTIVIDAD_SYNC_DAYS_PER_RUN", 1, minimum=1, maximum=15)
            days = [item["fecha"] for item in missing[:max_days]]
            metrics.update(
                {
                    "fecha_desde": days[0] if days else fecha_desde,
                    "fecha_hasta": days[-1] if days else fecha_hasta,
                    "days_attempted": len(days),
                    "legajos_scope_count": len(legajos),
                    "cache_rows_written": 0,
                    "active_rows_written": 0,
                    "oracle_rows_count": 0,
                }
            )
            if not legajos or not days:
                await _finish_sync_run(db, run_id, status="ok", metrics=metrics)
                return {"status": "ok", "run_id": run_id, "detail": "No hay dias faltantes."}

            max_seconds = _env_int("HISTORIA_ACTIVIDAD_SYNC_MAX_SECONDS", 240, minimum=30, maximum=1800)
            started = datetime.now()
            oracle_rows_count = 0
            cache_rows_written = 0
            active_rows_written = 0
            for desde, hasta in _date_ranges(days, max_days=max_days):
                if (datetime.now() - started).total_seconds() > max_seconds:
                    raise TimeoutError(f"La tanda supero el limite de {max_seconds} segundos.")
                await _sync_heartbeat(db, run_id)
                oracle_rows = await _query_actividad_operaciones_oracle_bulk(desde, hasta)
                range_days = [day for day in days if desde <= day <= hasta]
                store_metrics = await _store_actividad_operaciones_bulk(
                    db,
                    legajos=legajos,
                    days=range_days,
                    oracle_rows=oracle_rows,
                )
                oracle_rows_count += len(oracle_rows)
                cache_rows_written += store_metrics["cache_rows_written"]
                active_rows_written += store_metrics["active_rows_written"]

            metrics.update(
                {
                    "oracle_rows_count": oracle_rows_count,
                    "cache_rows_written": cache_rows_written,
                    "active_rows_written": active_rows_written,
                }
            )
            await _finish_sync_run(db, run_id, status="ok", metrics=metrics)
            return {"status": "ok", "run_id": run_id, **metrics}
        except Exception as exc:
            logger.exception("Fallo sync actividad diaria run_id=%s", run_id)
            await _finish_sync_run(db, run_id, status="failed", error=str(exc), metrics=metrics)
            return {"status": "failed", "run_id": run_id, "error": str(exc), **metrics}


async def _actividad_scheduler_loop() -> None:
    logger.info("Scheduler Historia actividad diaria iniciado.")
    interval = _env_int("HISTORIA_ACTIVIDAD_SYNC_POLL_SECONDS", 300, minimum=30, maximum=3600)
    while _actividad_scheduler_stop is not None and not _actividad_scheduler_stop.is_set():
        try:
            if _env_bool("HISTORIA_ACTIVIDAD_SYNC_ENABLED", True) and _current_sync_window():
                result = await run_actividad_operaciones_sync_once(trigger="scheduler", force_window=False)
                if result.get("status") in {"ok", "failed"}:
                    logger.info("Sync actividad diaria: %s", result)
            await asyncio.wait_for(_actividad_scheduler_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Scheduler Historia actividad diaria continuo tras error: %s", exc)
            await asyncio.sleep(interval)
    logger.info("Scheduler Historia actividad diaria detenido.")


def start_historia_actividad_scheduler() -> None:
    global _actividad_scheduler_task, _actividad_scheduler_stop
    if _actividad_scheduler_task and not _actividad_scheduler_task.done():
        return
    _actividad_scheduler_stop = asyncio.Event()
    _actividad_scheduler_task = asyncio.create_task(_actividad_scheduler_loop())


async def stop_historia_actividad_scheduler() -> None:
    global _actividad_scheduler_task, _actividad_scheduler_stop
    if _actividad_scheduler_stop:
        _actividad_scheduler_stop.set()
    if _actividad_scheduler_task:
        _actividad_scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await _actividad_scheduler_task
    _actividad_scheduler_task = None
    _actividad_scheduler_stop = None


async def _fetch_actividad_operaciones_rows(
    db: aiosqlite.Connection,
    legajo: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> tuple[list[dict[str, Any]], str, str | None]:
    cached = await _load_cached_actividad_operaciones(db, legajo, fecha_desde, fecha_hasta)
    cached_dates = {row["fecha"] for row in cached}
    all_days = _iter_date_strings(fecha_desde, fecha_hasta)
    missing_days = [day for day in all_days if day not in cached_dates]

    warning = None
    if missing_days:
        if len(missing_days) > MAX_ACTIVIDAD_OPERACIONES_ORACLE_DAYS:
            warning = (
                f"Actividad diaria: hay {len(missing_days)} dias no cacheados. "
                f"Para proteger Oracle, acota el rango a {MAX_ACTIVIDAD_OPERACIONES_ORACLE_DAYS} dias para completar esos datos."
            )
            rows = [row for row in cached if str(row.get("operaciones") or "").strip()]
            return rows, "local_cache_partial", warning
        try:
            for desde, hasta in _date_ranges(missing_days):
                oracle_rows = await _query_actividad_operaciones_oracle(legajo, desde, hasta)
                rows_by_date = {row["fecha"]: row for row in oracle_rows}
                days = [day for day in missing_days if desde <= day <= hasta]
                await _store_actividad_operaciones(db, legajo, rows_by_date, days)
            await db.commit()
            cached = await _load_cached_actividad_operaciones(db, legajo, fecha_desde, fecha_hasta)
        except Exception as exc:
            logger.warning("No se pudo consultar actividad diaria Oracle para legajo=%s: %s", legajo, exc)
            warning = str(exc)

    rows = [row for row in cached if str(row.get("operaciones") or "").strip()]
    return rows, "local_oracle_cache", warning


async def _fetch_actividad_rows(
    db: aiosqlite.Connection,
    batch_id: int,
    legajo: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT fecha, horario, aus_pres_codigo, motivo, hs_trab,
               hs_ext_realiz, hs_50_autorizadas, hs_100, tarde,
               ausentismo_clasificacion, ausentismo_contabiliza
        FROM rrhh_actividad_diaria
        WHERE batch_id = ?
          AND legajo = ?
          AND fecha >= ?
          AND fecha <= ?
        ORDER BY fecha DESC
        """,
        (batch_id, legajo, fecha_desde, fecha_hasta),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def _fetch_sanciones_rows(
    db: aiosqlite.Connection,
    batch_id: int,
    legajo: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> list[dict[str, Any]]:
    placeholders = ", ".join("?" for _ in REAL_SANCIONES)
    code_placeholders = ", ".join("?" for _ in REAL_SANCION_CODES)
    async with db.execute(
        f"""
        WITH sanciones_consolidadas AS (
            SELECT *
            FROM (
                SELECT s.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY s.legajo, COALESCE(s.inicio,''), COALESCE(s.fin,''), COALESCE(s.cod,''), COALESCE(s.creacion,''), COALESCE(s.descripcion,''), COALESCE(s.causa_sancion,''), COALESCE(s.descripcion_causa,'')
                           ORDER BY b.imported_at DESC, s.batch_id DESC, s.id DESC
                       ) rn
                FROM rrhh_sanciones s
                JOIN rrhh_import_batches b ON b.batch_id = s.batch_id
                WHERE b.status = 'complete'
            )
            WHERE rn = 1
        )
        SELECT inicio, fin, cod, creacion, descripcion, detalle,
               desc_ausentismo, causa_sancion, descripcion_causa
        FROM sanciones_consolidadas
        WHERE legajo = ?
          AND COALESCE(creacion, inicio, '') >= ?
          AND COALESCE(creacion, inicio, '') <= ?
          AND (
              TRIM(COALESCE(descripcion, '')) IN ({placeholders})
              OR TRIM(COALESCE(cod, '')) IN ({code_placeholders})
          )
        ORDER BY COALESCE(creacion, inicio) DESC, legajo
        """,
        (legajo, fecha_desde, fecha_hasta, *REAL_SANCIONES, *REAL_SANCION_CODES),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def _fetch_tnc_rows(
    legajo: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> tuple[list[dict[str, Any]], str, str | None]:
    try:
        raw_rows = await asyncio.to_thread(
            query_productive_db_historia_tnc_legajo,
            _date_to_oracle_key(fecha_desde),
            _date_to_oracle_key(fecha_hasta),
            legajo,
        )
    except Exception as exc:
        logger.warning("No se pudo consultar TNC Oracle para legajo=%s: %s", legajo, exc)
        return [], "oracle_error", str(exc)

    rows = []
    for row in raw_rows:
        data = {str(key).lower(): value for key, value in row.items()}
        rows.append(
            {
                "fecha": _oracle_date_to_iso(data.get("fecha")),
                "funcion": data.get("descrip_de_funcion") or "",
                "cantidad_excedida": round(_to_float(data.get("cantidad_de_cortes_hechos")), 2),
                "tiempo_excedido_segundos": int(_to_float(data.get("tiempo_excedido_en_segundos"))),
            }
        )
    return rows, "oracle", None


async def _fetch_latest_photo(db: aiosqlite.Connection, legajo: str) -> str:
    async with db.execute(
        """
        SELECT foto
        FROM tnc_eventos_cache
        WHERE legajo = ?
          AND NULLIF(TRIM(foto), '') IS NOT NULL
        ORDER BY dia_tnc DESC
        LIMIT 1
        """,
        (legajo,),
    ) as cur:
        row = await cur.fetchone()
    return str(row["foto"]) if row else ""


async def _fetch_fichadas_rows(
    db: aiosqlite.Connection,
    batch_id: int,
    legajo: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT fecha_fichada, fecha, hora, sentido, ubicacion, origen, destino
        FROM rrhh_fichadas
        WHERE batch_id = ?
          AND legajo = ?
          AND fecha >= ?
          AND fecha <= ?
        ORDER BY fecha_fichada DESC
        LIMIT 400
        """,
        (batch_id, legajo, fecha_desde, fecha_hasta),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


@router.get("/buscar")
async def buscar_legajos(q: str = Query("", min_length=1), limit: int = Query(12, ge=1, le=30)) -> dict[str, Any]:
    query = f"%{q.strip()}%"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        db.row_factory = aiosqlite.Row
        batch_id = await _latest_batch_id(db)
        if not batch_id:
            return {"items": []}
        async with db.execute(
            """
            SELECT legajo, nombre, desc_sector_generico, desc_funcion, desc_posicion
            FROM rrhh_legajero
            WHERE batch_id = ?
              AND (legajo LIKE ? OR nombre LIKE ?)
            ORDER BY nombre COLLATE NOCASE, legajo
            LIMIT ?
            """,
            (batch_id, query, query, limit),
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    return {
        "items": [
            {
                "legajo": row.get("legajo"),
                "nombre": row.get("nombre"),
                "sector": row.get("desc_sector_generico"),
                "cargo": row.get("desc_funcion"),
                "posicion": row.get("desc_posicion"),
            }
            for row in rows
        ]
    }


@router.get("/actividad-sync/status")
async def actividad_sync_status() -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT *
            FROM historia_legajo_actividad_sync_lock
            WHERE lock_name = ?
            """,
            (ACTIVIDAD_SYNC_LOCK_NAME,),
        ) as cur:
            lock_row = await cur.fetchone()
        async with db.execute(
            """
            SELECT *
            FROM historia_legajo_actividad_sync_runs
            ORDER BY started_at DESC, run_id DESC
            LIMIT 10
            """
        ) as cur:
            runs = [dict(row) for row in await cur.fetchall()]
        async with db.execute(
            """
            SELECT COUNT(*) total,
                   SUM(CASE WHEN NULLIF(TRIM(operaciones), '') IS NOT NULL THEN 1 ELSE 0 END) con_actividad,
                   MIN(fecha) fecha_min,
                   MAX(fecha) fecha_max
            FROM historia_legajo_actividad_operaciones
            """
        ) as cur:
            cache_row = await cur.fetchone()
    return {
        "enabled": _env_bool("HISTORIA_ACTIVIDAD_SYNC_ENABLED", True),
        "current_window": _current_sync_window(),
        "configured_windows": os.getenv("HISTORIA_ACTIVIDAD_SYNC_WINDOWS", "21:00-22:00,05:00-06:00"),
        "poll_seconds": _env_int("HISTORIA_ACTIVIDAD_SYNC_POLL_SECONDS", 300, minimum=30, maximum=3600),
        "days_per_run": _env_int("HISTORIA_ACTIVIDAD_SYNC_DAYS_PER_RUN", 1, minimum=1, maximum=15),
        "sync_range": {"fecha_desde": _sync_fecha_desde(), "fecha_hasta": _sync_fecha_hasta()},
        "lock": dict(lock_row) if lock_row else None,
        "cache": dict(cache_row) if cache_row else {},
        "runs": runs,
    }


@router.post("/actividad-sync/run")
async def actividad_sync_run(force_window: bool = Query(False)) -> dict[str, Any]:
    return await run_actividad_operaciones_sync_once(trigger="manual", force_window=force_window)


@router.get("/{legajo}")
async def historia_legajo(
    legajo: str,
    fecha_desde: date = Query(date(2026, 1, 1)),
    fecha_hasta: date = Query(default_factory=date.today),
) -> dict[str, Any]:
    legajo_norm = _norm_legajo(legajo)
    if fecha_desde > fecha_hasta:
        raise HTTPException(status_code=400, detail="El rango de fechas es invalido: desde no puede ser mayor que hasta.")
    fecha_desde_str = _date_to_str(fecha_desde)
    fecha_hasta_str = _date_to_str(fecha_hasta)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        db.row_factory = aiosqlite.Row
        batch_id = await _latest_batch_id(db)
        profile = await _legajo_profile(db, legajo_norm, batch_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Legajo no encontrado en el ultimo maestro.")

        prod_rows = await _fetch_productividad_rows(db, legajo_norm, fecha_desde_str, fecha_hasta_str)
        prod_real_rows, productividad_source, productividad_warning = await _fetch_productividad_real_rows(
            legajo_norm,
            fecha_desde_str,
            fecha_hasta_str,
        )
        actividad_rows = await _fetch_actividad_rows(db, batch_id, legajo_norm, fecha_desde_str, fecha_hasta_str)
        actividad_operaciones_rows, actividad_operaciones_source, actividad_operaciones_warning = await _fetch_actividad_operaciones_rows(
            db,
            legajo_norm,
            fecha_desde_str,
            fecha_hasta_str,
        )
        sanciones_rows = await _fetch_sanciones_rows(db, batch_id, legajo_norm, fecha_desde_str, fecha_hasta_str)
        tnc_rows, tnc_source, tnc_warning = await _fetch_tnc_rows(legajo_norm, fecha_desde_str, fecha_hasta_str)
        fichadas_rows = await _fetch_fichadas_rows(db, batch_id, legajo_norm, fecha_desde_str, fecha_hasta_str)
        foto = await _fetch_latest_photo(db, legajo_norm)

    total_bultos = sum(_to_float(row.get("bultos")) for row in prod_rows)
    total_lineas = sum(int(row.get("traspasos") or 0) for row in prod_rows)
    total_min = sum(_to_float(row.get("minutos_productivos")) for row in prod_rows)
    total_net = sum(_net_minutes(row) for row in prod_rows)
    horas_extra = sum(_to_float(row.get("hs_ext_realiz")) + _to_float(row.get("hs_50_autorizadas")) + _to_float(row.get("hs_100")) for row in actividad_rows)
    horas_trab = sum(_to_float(row.get("hs_trab")) for row in actividad_rows)
    ausencias = sum(1 for row in actividad_rows if int(row.get("ausentismo_contabiliza") or 0))
    tardes = sum(_to_float(row.get("tarde")) for row in actividad_rows)
    tnc_segundos = sum(int(row.get("tiempo_excedido_segundos") or 0) for row in tnc_rows)
    almacenes = sorted({str(row.get("almacen") or "SIN MAPEAR") for row in prod_rows})

    by_day: dict[str, dict[str, Any]] = {}
    for row in prod_rows:
        dia = row.get("fecha_operativa") or ""
        item = by_day.setdefault(dia, {"fecha": dia, "bultos": 0.0, "lineas": 0, "minutos": 0.0, "minutos_netos": 0.0})
        item["bultos"] += _to_float(row.get("bultos"))
        item["lineas"] += int(row.get("traspasos") or 0)
        item["minutos"] += _to_float(row.get("minutos_productivos"))
        item["minutos_netos"] += _net_minutes(row)
    productividad_diaria = []
    for item in by_day.values():
        item["productividad_bruta"] = round(item["bultos"] / (item["minutos"] / 60), 2) if item["minutos"] else 0
        item["productividad_neta"] = round(item["bultos"] / (item["minutos_netos"] / 60), 2) if item["minutos_netos"] else 0
        item["bultos"] = round(item["bultos"], 2)
        productividad_diaria.append(item)
    productividad_diaria.sort(key=lambda item: item["fecha"])

    prod_real_by_day: dict[str, dict[str, Any]] = {}
    for row in prod_real_rows:
        dia = row.get("fecha") or ""
        if not dia:
            continue
        item = prod_real_by_day.setdefault(dia, {"fecha": dia, "prod_real_values": [], "prod_equiv_values": [], "funciones": set()})
        if _to_float(row.get("prod_real")) > 0:
            item["prod_real_values"].append(_to_float(row.get("prod_real")))
        if _to_float(row.get("prod_equivalente")) > 0:
            item["prod_equiv_values"].append(_to_float(row.get("prod_equivalente")))
        if row.get("funcion"):
            item["funciones"].add(str(row.get("funcion")))

    productividad_real_diaria = []
    for item in prod_real_by_day.values():
        real_values = item.pop("prod_real_values")
        equiv_values = item.pop("prod_equiv_values")
        funciones = sorted(item.pop("funciones"))
        item["productividad_real"] = round(sum(real_values) / len(real_values), 2) if real_values else 0
        item["productividad_equivalente"] = round(sum(equiv_values) / len(equiv_values), 2) if equiv_values else 0
        item["funciones"] = funciones
        productividad_real_diaria.append(item)
    productividad_real_diaria.sort(key=lambda item: item["fecha"])

    prod_real_values = [_to_float(row.get("prod_real")) for row in prod_real_rows if _to_float(row.get("prod_real")) > 0]
    prod_equiv_values = [_to_float(row.get("prod_equivalente")) for row in prod_real_rows if _to_float(row.get("prod_equivalente")) > 0]

    timeline = []
    for row in prod_rows[:120]:
        timeline.append(_timeline_item(row.get("fecha_operativa"), "productividad", f"Picking {row.get('almacen')}", f"{row.get('bultos') or 0:g} bultos - {row.get('traspasos') or 0} lineas", row.get("turno_label") or ""))
    for row in actividad_rows[:120]:
        if row.get("motivo") or int(row.get("ausentismo_contabiliza") or 0) or _to_float(row.get("hs_ext_realiz")) or _to_float(row.get("hs_50_autorizadas")) or _to_float(row.get("hs_100")):
            extra = _to_float(row.get("hs_ext_realiz")) + _to_float(row.get("hs_50_autorizadas")) + _to_float(row.get("hs_100"))
            timeline.append(_timeline_item(row.get("fecha"), "novedad", row.get("motivo") or row.get("aus_pres_codigo") or "Actividad RRHH", f"Hs trab {row.get('hs_trab') or 0:g} - Hs extra {extra:g}", row.get("horario") or ""))
    for row in tnc_rows[:120]:
        timeline.append(_timeline_item(row.get("fecha"), "tnc", row.get("funcion") or "TNC", f"{row.get('cantidad_excedida') or 0:g} excedidos", f"{row.get('tiempo_excedido_segundos') or 0} seg"))
    for row in sanciones_rows[:80]:
        timeline.append(_timeline_item(row.get("inicio") or row.get("creacion"), "sancion", row.get("descripcion") or row.get("cod") or "Sancion", row.get("detalle") or row.get("descripcion_causa") or "", row.get("desc_ausentismo") or ""))
    timeline.sort(key=lambda item: item["fecha"], reverse=True)

    return {
        "legajo": profile,
        "foto": foto,
        "rango": {"fecha_desde": fecha_desde_str, "fecha_hasta": fecha_hasta_str},
        "sources": {
            "rrhh": "local",
            "productividad": productividad_source,
            "tnc": tnc_source,
            "actividad_operaciones": actividad_operaciones_source,
        },
        "warnings": {
            "productividad": productividad_warning,
            "tnc": tnc_warning,
            "actividad_operaciones": actividad_operaciones_warning,
        },
        "summary": {
            "horas_extra": round(horas_extra, 1),
            "horas_trabajadas": round(horas_trab, 1),
            "ausencias": ausencias,
            "llegadas_tarde": round(tardes, 1),
            "dias_con_actividad": len(actividad_operaciones_rows),
            "tnc_eventos": len(tnc_rows),
            "tnc_horas": round(tnc_segundos / 3600, 1),
            "sanciones": len(sanciones_rows),
            "bultos": round(total_bultos, 1),
            "lineas": total_lineas,
            "dias_productivos": len(by_day),
            "productividad_bruta": round(total_bultos / (total_min / 60), 2) if total_min else 0,
            "productividad_neta": round(total_bultos / (total_net / 60), 2) if total_net else 0,
            "productividad_real": round(sum(prod_real_values) / len(prod_real_values), 2) if prod_real_values else 0,
            "productividad_equivalente": round(sum(prod_equiv_values) / len(prod_equiv_values), 2) if prod_equiv_values else 0,
            "sesiones_incompletas": sum(int(row.get("sesion_incompleta") or 0) for row in prod_rows),
            "excede_turno": sum(int(row.get("excede_turno") or 0) for row in prod_rows),
            "almacenes": almacenes,
        },
        "productividad": {
            "diaria": productividad_real_diaria,
            "rows": prod_real_rows[:300],
            "picking_diaria": productividad_diaria,
            "picking_rows": prod_rows[:300],
        },
        "novedades": actividad_rows[:300],
        "actividad_operaciones": actividad_operaciones_rows[:400],
        "sanciones": sanciones_rows[:120],
        "tnc": tnc_rows[:300],
        "fichadas": fichadas_rows,
        "timeline": timeline[:300],
    }

