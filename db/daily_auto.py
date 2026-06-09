"""Cache local para calculos automaticos de Daily.

Esta base es independiente de vigia.db y de daily_operativa.db. El objetivo es
que la UI lea resultados precalculados sin consultar Oracle en el flujo
interactivo.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from db.daily_operativa import LOCAL_TZ
from db.paths import resolve_db_path


DAILY_AUTO_DB_PATH = resolve_db_path(
    "DAILY_AUTO_DB_PATH",
    "daily_auto.db",
    Path(__file__).resolve().parent,
)


CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS daily_auto_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_key       TEXT NOT NULL,
    daily_label     TEXT NOT NULL,
    fecha_inicio    TEXT NOT NULL,
    fecha_fin       TEXT NOT NULL,
    fecha_carga     TEXT NOT NULL,
    process         TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    duration_ms     REAL,
    row_count       INTEGER DEFAULT 0,
    error           TEXT,
    timings_json    TEXT,
    run_trigger     TEXT DEFAULT 'scheduler',
    usuario         TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(daily_key, process)
);
"""


CREATE_RESULTADOS = """
CREATE TABLE IF NOT EXISTS daily_auto_resultados (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES daily_auto_runs(id) ON DELETE CASCADE,
    daily_key       TEXT NOT NULL,
    process         TEXT NOT NULL,
    sector          TEXT NOT NULL,
    sector_oracle   TEXT NOT NULL,
    id_parametro    TEXT NOT NULL,
    valor           REAL,
    cantidad        REAL,
    legajos         REAL,
    details_count   INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(daily_key, process, sector, id_parametro)
);
"""


CREATE_CLARK_DETALLE = """
CREATE TABLE IF NOT EXISTS daily_auto_clark_detalle (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES daily_auto_runs(id) ON DELETE CASCADE,
    daily_key       TEXT NOT NULL,
    sector          TEXT NOT NULL,
    sector_oracle   TEXT NOT NULL,
    almacen         TEXT,
    legajo          TEXT,
    nombre          TEXT,
    fecha           TEXT,
    pallet          TEXT,
    operacion       TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_runs_lookup ON daily_auto_runs(daily_key, process, status)",
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_resultados_lookup ON daily_auto_resultados(daily_key, process, sector)",
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_clark_lookup ON daily_auto_clark_detalle(daily_key, sector)",
]


SECTOR_MAP = {
    "NOA": "Noa",
    "SECOS": "Secos",
    "REFRIGERADOS": "Refrigerados",
}


CLARK_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_PROD_CLARK_NOA_6A6",
    "Secos": "OP_PROD_CLARK_SECOS_6A6",
    "Refrigerados": "OP_PROD_CLARK_REFRI_6A6",
}

PICKING_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_PROD_PICKING_NOA_6A6",
    "Secos": "OP_PROD_PICKING_SECOS_6A6",
    "Refrigerados": "OP_PROD_PICKING_REFRI_6A6",
}

PICKING_REAL_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_PICKING_REAL_6A6",
    "Secos": "OP_CUMP_PICKING_REAL_6A6",
    "Refrigerados": "OP_CUMP_PICKING_REAL_6A6",
}

PICKING_DOTACION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_DOT_PICKING_LEGAJOS_6A8",
    "Secos": "OP_DOT_PICKING_LEGAJOS_6A8",
    "Refrigerados": "OP_DOT_PICKING_LEGAJOS_6A8",
}

CLARK_DOTACION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_DOT_SPC_LEGAJOS_6A8",
    "Secos": "OP_DOT_SPC_LEGAJOS_6A8",
    "Refrigerados": "OP_DOT_SPC_LEGAJOS_6A8",
}

RECEPCION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_PROD_RECEPCION_NOA_6A6",
    "Secos": "OP_PROD_RECEPCION_SECOS_6A6",
    "Refrigerados": "OP_PROD_RECEPCION_REFRI_6A6",
}

RECEPCION_REAL_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_RECEPCION_REAL_6A6",
    "Secos": "OP_CUMP_RECEPCION_REAL_6A6",
    "Refrigerados": "OP_CUMP_RECEPCION_REAL_6A6",
}

RECEPCION_DOTACION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_DOT_RECEPCION_LEGAJOS_6A8",
    "Secos": "OP_DOT_RECEPCION_LEGAJOS_6A8",
    "Refrigerados": "OP_DOT_RECEPCION_LEGAJOS_6A8",
}

DESPACHO_PARAM_IDS_BY_SECTOR = {
    "Secos": "OP_PROD_DESPACHO_SECOS_6A6",
    "Refrigerados": "OP_PROD_DESPACHO_REFRI_6A6",
}

DESPACHO_REAL_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_DESPACHO_REAL_6A6",
    "Secos": "OP_CUMP_DESPACHO_REAL_6A6",
    "Refrigerados": "OP_CUMP_DESPACHO_REAL_6A6",
}

DESPACHO_DOTACION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_DOT_DESPACHO_LEGAJOS_6A8",
    "Secos": "OP_DOT_DESPACHO_LEGAJOS_6A8",
    "Refrigerados": "OP_DOT_DESPACHO_LEGAJOS_6A8",
}

PICKING_PLAN_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_PICKING_PLAN_6A6",
    "Secos": "OP_CUMP_PICKING_PLAN_6A6",
    "Refrigerados": "OP_CUMP_PICKING_PLAN_6A6",
}

SPC_PLAN_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_SPC_PLAN_6A6",
    "Secos": "OP_CUMP_SPC_PLAN_6A6",
    "Refrigerados": "OP_CUMP_SPC_PLAN_6A6",
}

DESPACHO_PLAN_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_DESPACHO_PLAN_6A6",
    "Secos": "OP_CUMP_DESPACHO_PLAN_6A6",
    "Refrigerados": "OP_CUMP_DESPACHO_PLAN_6A6",
}


def _now_text() -> str:
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def _norm_legajo(value: Any) -> str:
    text = str(value or "").strip()
    return text.lstrip("0") or text


def _row_value(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if value is None:
        value = row.get(key.lower())
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def _day_name(value: datetime) -> str:
    labels = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
    return labels[value.weekday()]


def scheduled_daily_window(now: datetime | None = None) -> dict[str, Any]:
    """Calcula la ventana que debe precargarse, sin exigir el cutoff 06:30."""
    current = now.astimezone(LOCAL_TZ) if now else datetime.now(LOCAL_TZ)
    weekday = current.weekday()
    if weekday == 6:
        return {
            "can_run": False,
            "reason": "La Daily de fin de semana se precarga el lunes.",
            "now": current.isoformat(timespec="seconds"),
        }
    if weekday == 0:
        start_date = current.date() - timedelta(days=2)
    else:
        start_date = current.date() - timedelta(days=1)
    end_date = current.date()
    start = datetime.combine(start_date, time(6, 0), tzinfo=LOCAL_TZ)
    end = datetime.combine(end_date, time(6, 0), tzinfo=LOCAL_TZ)
    return {
        "can_run": True,
        "daily_key": f"{start:%Y%m%d0600}_{end:%Y%m%d0600}",
        "daily_label": f"{_day_name(start)} 06:00 / {_day_name(end)} 06:00",
        "fecha_inicio": start.isoformat(timespec="seconds"),
        "fecha_fin": end.isoformat(timespec="seconds"),
        "fecha_carga": current.date().isoformat(),
        "now": current.isoformat(timespec="seconds"),
    }


async def init_daily_auto_db() -> None:
    DAILY_AUTO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(CREATE_RUNS)
        await db.execute(CREATE_RESULTADOS)
        await db.execute(CREATE_CLARK_DETALLE)
        async with db.execute("PRAGMA table_info(daily_auto_runs)") as cur:
            run_columns = {str(row[1]) for row in await cur.fetchall()}
        if "run_trigger" not in run_columns:
            await db.execute("ALTER TABLE daily_auto_runs ADD COLUMN run_trigger TEXT DEFAULT 'scheduler'")
        if "usuario" not in run_columns:
            await db.execute("ALTER TABLE daily_auto_runs ADD COLUMN usuario TEXT")
        for sql in INDEXES:
            await db.execute(sql)
        await db.commit()


async def has_successful_run(daily_key: str, process: str) -> bool:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        async with db.execute(
            """
            SELECT 1
            FROM daily_auto_runs
            WHERE daily_key = ? AND process = ? AND status = 'success'
            LIMIT 1
            """,
            (daily_key, process),
        ) as cur:
            return await cur.fetchone() is not None


async def mark_run_error(
    daily: dict[str, Any],
    process: str,
    error: str,
    started_at: str,
    *,
    trigger: str = "scheduler",
    usuario: str = "",
) -> None:
    await init_daily_auto_db()
    now = _now_text()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'error', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                status = 'error',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                error = excluded.error,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], process, started_at, now, str(error)[:2000],
                trigger, usuario, now,
            ),
        )
        await db.commit()


async def save_clark_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
        if sector_oracle in SECTOR_MAP:
            grouped[sector_oracle].append(row)

    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'CLARK', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'CLARK'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'CLARK'", (daily["daily_key"],))
        await db.execute("DELETE FROM daily_auto_clark_detalle WHERE daily_key = ?", (daily["daily_key"],))

        result_count = 0
        for sector_oracle, sector_rows in grouped.items():
            sector = SECTOR_MAP[sector_oracle]
            legajos = {
                _norm_legajo(_row_value(row, "LEGAJO"))
                for row in sector_rows
                if _norm_legajo(_row_value(row, "LEGAJO"))
            }
            pallets = [row for row in sector_rows if str(_row_value(row, "PALLET") or "").strip()]
            valor = round(len(pallets) / len(legajos), 2) if legajos else 0.0
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'CLARK', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, CLARK_PARAM_IDS_BY_SECTOR[sector],
                    valor, len(pallets), len(legajos), len(sector_rows),
                ),
            )
            result_count += 1
            for row in sector_rows:
                await db.execute(
                    """
                    INSERT INTO daily_auto_clark_detalle (
                        run_id, daily_key, sector, sector_oracle, almacen,
                        legajo, nombre, fecha, pallet, operacion
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, _row_value(row, "ALMACEN"),
                        _row_value(row, "LEGAJO"), _row_value(row, "NOMBRE"),
                        str(_row_value(row, "FCREAREG") or ""), _row_value(row, "PALLET"),
                        _row_value(row, "OPERACION"),
                    ),
                )
        await db.commit()
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_clark_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'CLARK', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'CLARK'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'CLARK'", (daily["daily_key"],))
        await db.execute("DELETE FROM daily_auto_clark_detalle WHERE daily_key = ?", (daily["daily_key"],))

        result_count = 0
        for row in rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            pallets = float(_row_value(row, "PALLETS") or 0)
            legajos = float(_row_value(row, "LEGAJOS") or 0)
            valor = float(_row_value(row, "PRODUCCION") or 0)
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'CLARK', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, CLARK_PARAM_IDS_BY_SECTOR[sector],
                    valor, pallets, legajos,
                ),
            )
            result_count += 1
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'CLARK', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, CLARK_DOTACION_PARAM_IDS_BY_SECTOR[sector],
                    legajos, legajos, legajos,
                ),
            )
            result_count += 1
        await db.commit()
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_picking_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    valid_rows = []
    for row in rows:
        if _row_value(row, "ALMACEN") is not None and _row_value(row, "BULTOS") is not None:
            valid_rows.append(row)
    if rows and not valid_rows:
        raise ValueError("La consulta Picking no devolvio filas agregadas esperadas (ALMACEN/BULTOS).")
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'PICKING', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'PICKING'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'PICKING'", (daily["daily_key"],))

        result_count = 0
        for row in valid_rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            bultos = float(_row_value(row, "BULTOS") or 0)
            legajos = float(_row_value(row, "LEGAJOS") or 0)
            valor = float(_row_value(row, "PRODUCCION") or 0)
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'PICKING', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, PICKING_PARAM_IDS_BY_SECTOR[sector],
                    valor, bultos, legajos,
                ),
            )
            result_count += 1
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'PICKING', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, PICKING_REAL_PARAM_IDS_BY_SECTOR[sector],
                    bultos, bultos, legajos,
                ),
            )
            result_count += 1
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'PICKING', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, PICKING_DOTACION_PARAM_IDS_BY_SECTOR[sector],
                    legajos, legajos, legajos,
                ),
            )
            result_count += 1
        await db.commit()
    if rows and result_count == 0:
        raise ValueError("La consulta Picking no genero resultados para sectores habilitados.")
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_recepcion_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    valid_rows = []
    for row in rows:
        if _row_value(row, "ALMACEN") is not None and _row_value(row, "PALLETS") is not None:
            valid_rows.append(row)
    if rows and not valid_rows:
        raise ValueError("La consulta Recepcion no devolvio filas agregadas esperadas (ALMACEN/PALLETS).")
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'RECEPCION', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'RECEPCION'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'RECEPCION'", (daily["daily_key"],))

        result_count = 0
        for row in valid_rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            pallets = float(_row_value(row, "PALLETS") or 0)
            legajos = float(_row_value(row, "LEGAJOS") or 0)
            valor = float(_row_value(row, "PRODUCCION") or 0)
            for id_parametro, item_value in (
                (RECEPCION_PARAM_IDS_BY_SECTOR[sector], valor),
                (RECEPCION_REAL_PARAM_IDS_BY_SECTOR[sector], pallets),
                (RECEPCION_DOTACION_PARAM_IDS_BY_SECTOR[sector], legajos),
            ):
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'RECEPCION', ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                        item_value, pallets, legajos,
                    ),
                )
                result_count += 1
        await db.commit()
    if rows and result_count == 0:
        raise ValueError("La consulta Recepcion no genero resultados para sectores habilitados.")
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_despacho_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    valid_rows = []
    for row in rows:
        if _row_value(row, "ALMACEN") is not None and _row_value(row, "VIAJES") is not None:
            valid_rows.append(row)
    if rows and not valid_rows:
        raise ValueError("La consulta Despacho no devolvio filas agregadas esperadas (ALMACEN/VIAJES).")
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'DESPACHO', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'DESPACHO'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'DESPACHO'", (daily["daily_key"],))

        result_count = 0
        for row in valid_rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            viajes = float(_row_value(row, "VIAJES") or 0)
            cargadores = float(_row_value(row, "CARGADORES") or _row_value(row, "LEGAJOS") or 0)
            valor = float(_row_value(row, "PRODUCCION") or 0)
            items: list[tuple[str, float]] = [
                (DESPACHO_REAL_PARAM_IDS_BY_SECTOR[sector], viajes),
                (DESPACHO_DOTACION_PARAM_IDS_BY_SECTOR[sector], cargadores),
            ]
            if sector in DESPACHO_PARAM_IDS_BY_SECTOR:
                items.insert(0, (DESPACHO_PARAM_IDS_BY_SECTOR[sector], valor))
            for id_parametro, item_value in items:
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'DESPACHO', ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                        item_value, viajes, cargadores,
                    ),
                )
                result_count += 1
        await db.commit()
    if rows and result_count == 0:
        raise ValueError("La consulta Despacho no genero resultados para sectores habilitados.")
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_planificacion_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    valid_rows = []
    for row in rows:
        if _row_value(row, "ALMACEN") is not None and _row_value(row, "VIAJES_PLANIFICADOS") is not None:
            valid_rows.append(row)
    if rows and not valid_rows:
        raise ValueError("La consulta Planificacion no devolvio filas agregadas esperadas (ALMACEN/VIAJES_PLANIFICADOS).")
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'PLANIFICACION', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'PLANIFICACION'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'PLANIFICACION'", (daily["daily_key"],))

        result_count = 0
        for row in valid_rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            viajes = float(_row_value(row, "VIAJES_PLANIFICADOS") or 0)
            bultos_picking = float(_row_value(row, "BULTOS_PICKING_PLANIFICADOS") or 0)
            pallets_picking = float(_row_value(row, "PALLETS_PICKING_PLANIFICADOS") or 0)
            pallets_spc = float(_row_value(row, "PALLETS_SPC_PLANIFICADOS") or 0)
            bultos_spc = float(_row_value(row, "BULTOS_SPC_PLANIFICADOS") or 0)
            items = [
                (PICKING_PLAN_PARAM_IDS_BY_SECTOR[sector], bultos_picking, bultos_picking, pallets_picking),
                (SPC_PLAN_PARAM_IDS_BY_SECTOR[sector], pallets_spc, pallets_spc, bultos_spc),
                (DESPACHO_PLAN_PARAM_IDS_BY_SECTOR[sector], viajes, viajes, 0),
            ]
            for id_parametro, valor, cantidad, details_count in items:
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'PLANIFICACION', ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                        valor, cantidad, int(details_count or 0),
                    ),
                )
                result_count += 1
        await db.commit()
    if rows and result_count == 0:
        raise ValueError("La consulta Planificacion no genero resultados para sectores habilitados.")
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def get_latest_run(daily_key: str, process: str = "CLARK") -> dict[str, Any] | None:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT *
            FROM daily_auto_runs
            WHERE daily_key = ? AND process = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (daily_key, process),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_cached_results(daily_key: str) -> list[dict[str, Any]]:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT r.*, run.status, run.finished_at, run.duration_ms
            FROM daily_auto_resultados r
            JOIN daily_auto_runs run ON run.id = r.run_id
            WHERE r.daily_key = ? AND r.process IN ('CLARK', 'PICKING', 'RECEPCION', 'DESPACHO', 'PLANIFICACION') AND run.status = 'success'
            ORDER BY r.sector, r.process
            """,
            (daily_key,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_cached_clark_detail(daily_key: str, sector: str) -> list[dict[str, Any]]:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT almacen, legajo, nombre, fecha, pallet, operacion
            FROM daily_auto_clark_detalle
            WHERE daily_key = ? AND sector = ?
            ORDER BY legajo, fecha, pallet
            """,
            (daily_key, sector),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]
