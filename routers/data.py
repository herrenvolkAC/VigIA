"""
VigIA v2.0 · routers/data.py
Endpoints de datos: /api/snapshot, /api/turno/activo
"""
import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, date, time, timedelta
from typing import Optional, Any

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.schema import DB_PATH
from routers.ai import _call_ai, _extract_json
from routers.productividad_analisis import _query_productive_db

logger = logging.getLogger("vigia.data")
router = APIRouter()

TURN_STARTS = {
    "tarde": time(14, 0),
    "noche": time(22, 0),
    "manana": time(6, 0),
}
TURN_LABELS = {
    "tarde": "Tarde",
    "noche": "Noche",
    "manana": "Manana",
}
ONLINE_AI_PROMPT_VERSION = "cumplimiento-online-v1"
ONLINE_AI_SYSTEM = (
    "Sos un supervisor operativo senior de un centro de distribucion.\n"
    "Recibis un resumen interno de productividad online de picking por turno.\n"
    "Tu objetivo es proponer UNA sola accion concreta y una consecuencia esperada simple.\n"
    "La accion debe estar escrita como orden operativa breve.\n"
    "La consecuencia debe decir que pasaria si se ejecuta esa accion, en lenguaje simple.\n"
    "No hables de cumplimiento, plan, brecha esperada ni justificaciones analiticas largas.\n"
    "No expliques el modelo. No agregues contexto extra.\n"
    "Responde SOLO con JSON valido, sin markdown ni texto extra:\n"
    '{"accion":"una accion concreta y breve, maximo 18 palabras",'
    '"impacto":"si haces esto, deberia pasar esto, en maximo 22 palabras"}'
)


# ── Schemas ───────────────────────────────────────────────────────────────────
class OlaData(BaseModel):
    ola_num: int
    sector: str
    hora_ini: str
    hora_fin: str
    bultos_prog: int
    bultos_ejec: int
    dot_prog: int
    dot_ejec: int
    prod_prog: float
    prod_ejec: float
    obs: Optional[str] = ""


class SnapshotRequest(BaseModel):
    programa: str
    fecha: str
    turno: str
    olas: list[OlaData]


class CumplimientoOnlineRequest(BaseModel):
    turno: str
    ola_num: Optional[int] = None


def _normalize_turno(turno: str) -> str:
    raw = (turno or "").strip().lower()
    raw = (
        raw.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    if "tard" in raw:
        return "tarde"
    if "noch" in raw:
        return "noche"
    if "man" in raw:
        return "manana"
    raise HTTPException(status_code=400, detail=f"Turno no reconocido: {turno}")


def _turno_label(turno_key: str) -> str:
    return TURN_LABELS.get(turno_key, turno_key.title())


def _most_recent_turn_start(turno_key: str, now: datetime) -> datetime:
    hhmm = TURN_STARTS[turno_key]
    candidate = datetime.combine(now.date(), hhmm)
    if candidate > now:
        candidate -= timedelta(days=1)
    return candidate


def _floor_to_quarter(dt: datetime) -> datetime:
    minute = dt.minute - (dt.minute % 15)
    return dt.replace(minute=minute, second=0, microsecond=0)


def _format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_row_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _classify_sector(zona: str) -> str:
    text = (zona or "").strip().upper()
    return "NOA" if "NOA" in text else "Secos"


def _build_ola_datetimes(turno_start: datetime, hora_ini: str, hora_fin: str) -> tuple[datetime, datetime]:
    start_hour, start_min = [int(part) for part in str(hora_ini).split(":")[:2]]
    end_hour, end_min = [int(part) for part in str(hora_fin).split(":")[:2]]
    start_dt = turno_start.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
    end_dt = turno_start.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)
    if start_dt < turno_start:
        start_dt += timedelta(days=1)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _serialize_rows(rows: list[dict[str, Any]]) -> str:
    serializable = []
    for row in rows:
        serializable.append({
            "FHMOVIMIENTO": _parse_row_datetime(row.get("FHMOVIMIENTO")).isoformat(sep=" ") if _parse_row_datetime(row.get("FHMOVIMIENTO")) else "",
            "OPERARIO": row.get("OPERARIO") or "",
            "ZONAORIGEN": row.get("ZONAORIGEN") or "",
            "CANTIDAD": _safe_float(row.get("CANTIDAD")),
            "PESOREGISTRADO": _safe_float(row.get("PESOREGISTRADO")),
            "NROPALLET": row.get("NROPALLET") or "",
        })
    return json.dumps(serializable, ensure_ascii=False)


def _deserialize_rows(payload: str | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    try:
        data = json.loads(payload)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _deserialize_json_object(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _load_turn_plan(db: aiosqlite.Connection, turno_key: str) -> list[dict[str, Any]]:
    turno_label = _turno_label(turno_key)
    cursor = await db.execute("SELECT MAX(fecha) AS fecha FROM historico_olas")
    row = await cursor.fetchone()
    latest_fecha = row["fecha"] if row else None
    if not latest_fecha:
        raise HTTPException(status_code=400, detail="No hay plan historico disponible en historico_olas.")

    cursor = await db.execute(
        """
        SELECT fecha, ola_num, ola_label, hora_ini, hora_fin, turno,
               prog_secos, prog_noa, prog_total, dot_prog, prod_prog
        FROM historico_olas
        WHERE fecha = ? AND LOWER(REPLACE(turno, 'ñ', 'n')) = LOWER(REPLACE(?, 'ñ', 'n'))
        ORDER BY ola_num
        """,
        (latest_fecha, turno_label),
    )
    rows = await cursor.fetchall()
    if not rows:
        raise HTTPException(status_code=400, detail=f"No hay olas planificadas para el turno {turno_label}.")

    plan = []
    for row in rows:
        start_dt, end_dt = _build_ola_datetimes(
            datetime.combine(date.today(), TURN_STARTS[turno_key]),
            row["hora_ini"],
            row["hora_fin"],
        )
        plan.append({
            "num": row["ola_num"],
            "label": row["ola_label"] or f"OLA {row['ola_num']}",
            "turno": turno_label,
            "hora_ini": row["hora_ini"],
            "hora_fin": row["hora_fin"],
            "ini": start_dt.time().hour,
            "fin": end_dt.time().hour if end_dt.time().hour != 0 or end_dt.date() == start_dt.date() else 24,
            "progSecos": round(_safe_float(row["prog_secos"])),
            "progNOA": round(_safe_float(row["prog_noa"])),
            "progTotal": round(_safe_float(row["prog_total"])),
            "dotProg": int(round(_safe_float(row["dot_prog"]))),
            "prodProg": round(_safe_float(row["prod_prog"]), 2),
        })
    return plan


async def _load_existing_snapshot_map(db: aiosqlite.Connection, turno_key: str, turno_inicio: str) -> dict[str, aiosqlite.Row]:
    cursor = await db.execute(
        """
        SELECT *
        FROM cumplimiento_online_snapshots
        WHERE turno_key = ? AND turno_inicio = ?
        """,
        (turno_key, turno_inicio),
    )
    rows = await cursor.fetchall()
    return {row["bloque_hasta"]: row for row in rows}


def _build_cut_blocks(turno_start: datetime, cut_end: datetime) -> list[tuple[datetime, datetime]]:
    blocks = []
    block_start = turno_start
    while block_start < cut_end:
        block_end = min(block_start + timedelta(minutes=15), cut_end)
        blocks.append((block_start, block_end))
        block_start = block_end
    return blocks


async def _store_snapshot(
    db: aiosqlite.Connection,
    turno_key: str,
    turno_label: str,
    turno_inicio: str,
    bloque_desde: str,
    bloque_hasta: str,
    rows: list[dict[str, Any]],
) -> None:
    resumen = {
        "cantidad_total": round(sum(_safe_float(row.get("CANTIDAD")) for row in rows), 2),
        "movimientos": len(rows),
        "operarios": len({str(row.get("OPERARIO") or "").strip() for row in rows if str(row.get("OPERARIO") or "").strip()}),
    }
    await db.execute(
        """
        INSERT INTO cumplimiento_online_snapshots
        (turno_key, turno_label, turno_inicio, bloque_desde, bloque_hasta,
         oracle_rows_count, rows_json, resumen_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(turno_key, turno_inicio, bloque_hasta) DO UPDATE SET
            bloque_desde = excluded.bloque_desde,
            oracle_rows_count = excluded.oracle_rows_count,
            rows_json = excluded.rows_json,
            resumen_json = excluded.resumen_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            turno_key,
            turno_label,
            turno_inicio,
            bloque_desde,
            bloque_hasta,
            len(rows),
            _serialize_rows(rows),
            json.dumps(resumen, ensure_ascii=False),
        ),
    )


def _aggregate_turn_rows(
    rows: list[dict[str, Any]],
    plan_olas: list[dict[str, Any]],
    turno_start: datetime,
    cut_end: datetime,
) -> dict[str, Any]:
    ola_boundaries = []
    for ola in plan_olas:
        start_dt, end_dt = _build_ola_datetimes(turno_start, ola["hora_ini"], ola["hora_fin"])
        ola_boundaries.append((ola["num"], start_dt, end_dt))

    per_ola: dict[int, dict[str, Any]] = {}
    for ola in plan_olas:
        per_ola[ola["num"]] = {
            **ola,
            "ejecSecos": 0,
            "ejecNOA": 0,
            "ejecTotal": 0,
            "dotEjec": 0,
            "prodEjec": 0.0,
            "obs": "",
            "_operarios": set(),
        }

    turn_operarios = set()
    zone_totals: dict[str, float] = defaultdict(float)
    block_totals: dict[str, float] = defaultdict(float)
    total_cantidad = 0.0
    total_movimientos = 0

    for row in rows:
        fh = _parse_row_datetime(row.get("FHMOVIMIENTO"))
        if not fh or fh < turno_start or fh > cut_end:
            continue
        cantidad = _safe_float(row.get("CANTIDAD"))
        operario = str(row.get("OPERARIO") or "").strip()
        zona = str(row.get("ZONAORIGEN") or "").strip() or "Sin zona"
        total_cantidad += cantidad
        total_movimientos += 1
        if operario:
            turn_operarios.add(operario)
        zone_totals[zona] += cantidad
        block_totals[fh.strftime("%Y-%m-%d %H:%M:%S")] += cantidad

        matched_ola_num = None
        for ola_num, start_dt, end_dt in ola_boundaries:
            if start_dt <= fh < end_dt:
                matched_ola_num = ola_num
                break
        if matched_ola_num is None:
            continue

        target = per_ola[matched_ola_num]
        if _classify_sector(zona) == "NOA":
            target["ejecNOA"] += cantidad
        else:
            target["ejecSecos"] += cantidad
        target["ejecTotal"] += cantidad
        if operario:
            target["_operarios"].add(operario)

    current_block_end = cut_end.strftime("%Y-%m-%d %H:%M:%S")
    quantities_by_snapshot: list[dict[str, Any]] = []
    snapshot_totals: dict[str, float] = defaultdict(float)
    for row in rows:
        fh = _parse_row_datetime(row.get("FHMOVIMIENTO"))
        if not fh or fh > cut_end:
            continue
        block_end = _floor_to_quarter(fh + timedelta(minutes=14, seconds=59))
        if block_end > cut_end:
            block_end = cut_end
        snapshot_totals[block_end.strftime("%Y-%m-%d %H:%M:%S")] += _safe_float(row.get("CANTIDAD"))
    for block_key in sorted(snapshot_totals):
        quantities_by_snapshot.append({"bloque_hasta": block_key, "cantidad": round(snapshot_totals[block_key], 2)})

    for ola in per_ola.values():
        operarios = len(ola["_operarios"])
        ola["dotEjec"] = operarios
        ola["prodEjec"] = round((ola["ejecTotal"] / operarios), 2) if operarios else 0.0
        ola.pop("_operarios", None)
        ola["ejecSecos"] = round(ola["ejecSecos"])
        ola["ejecNOA"] = round(ola["ejecNOA"])
        ola["ejecTotal"] = round(ola["ejecTotal"])

    turn_duration_hours = max((cut_end - turno_start).total_seconds() / 3600, 0.01)
    total_operarios = len(turn_operarios)
    return {
        "olas": [per_ola[ola["num"]] for ola in plan_olas],
        "resumen": {
            "cantidad_total": round(total_cantidad),
            "movimientos_total": total_movimientos,
            "operarios_activos": total_operarios,
            "productividad_operario": round((total_cantidad / total_operarios), 2) if total_operarios else 0.0,
            "ritmo_turno_hora": round(total_cantidad / turn_duration_hours, 2),
            "corte_hasta": current_block_end,
        },
        "zonas": [
            {"zona": zona, "cantidad_total": round(total, 2)}
            for zona, total in sorted(zone_totals.items(), key=lambda item: item[1], reverse=True)
        ],
        "bloques": quantities_by_snapshot,
    }


def _expected_progress(plan_olas: list[dict[str, Any]], turno_start: datetime, cut_end: datetime) -> dict[str, Any]:
    expected_total = 0.0
    per_ola = {}
    for ola in plan_olas:
        start_dt, end_dt = _build_ola_datetimes(turno_start, ola["hora_ini"], ola["hora_fin"])
        duration = max((end_dt - start_dt).total_seconds(), 1)
        elapsed = max(min((cut_end - start_dt).total_seconds(), duration), 0)
        ratio = elapsed / duration
        expected_total += ola["progTotal"] * ratio
        per_ola[ola["num"]] = round(ola["progTotal"] * ratio, 2)
    return {"esperado_total": round(expected_total, 2), "esperado_por_ola": per_ola}


def _build_online_context(
    turno_label: str,
    turno_start: datetime,
    cut_end: datetime,
    aggregated: dict[str, Any],
) -> tuple[str, str]:
    resumen = aggregated["resumen"]
    actual_total = resumen["cantidad_total"]
    bloque_actual = aggregated["bloques"][-1]["cantidad"] if aggregated["bloques"] else 0
    bloque_prev = aggregated["bloques"][-2]["cantidad"] if len(aggregated["bloques"]) > 1 else 0
    trend = round(bloque_actual - bloque_prev, 2)
    zonas = aggregated["zonas"][:3]
    zonas_text = ", ".join(f"{z['zona']}={round(z['cantidad_total'])}" for z in zonas) or "sin zonas destacadas"
    ritmo_hora = resumen["ritmo_turno_hora"]
    prod_operario = resumen["productividad_operario"]

    internal_summary = (
        f"Turno {turno_label} al corte {cut_end.strftime('%H:%M')}: "
        f"{actual_total:,.0f} bultos acumulados, {resumen['movimientos_total']:,.0f} movimientos, "
        f"{resumen['operarios_activos']} operarios activos, {prod_operario:.1f} bultos/op acumulado, "
        f"{ritmo_hora:.1f} bultos/op/hora. "
        f"Ultimo bloque 15m {bloque_actual:,.0f} ({trend:+,.0f} vs bloque previo). "
        f"Zonas: {zonas_text}."
    )

    ia_context = (
        f"Turno: {turno_label}\n"
        f"Inicio turno: {turno_start.strftime('%Y-%m-%d %H:%M')}\n"
        f"Corte: {cut_end.strftime('%Y-%m-%d %H:%M')}\n"
        f"Bultos acumulados: {actual_total:.0f}\n"
        f"Movimientos acumulados: {resumen['movimientos_total']:.0f}\n"
        f"Operarios activos: {resumen['operarios_activos']}\n"
        f"Bultos por operario acumulado: {prod_operario:.1f}\n"
        f"Bultos por operario por hora: {ritmo_hora:.1f}\n"
        f"Ritmo del ultimo bloque de 15 minutos: {bloque_actual:.0f}\n"
        f"Variacion vs bloque previo: {trend:+.0f}\n"
        f"Top zonas: {zonas_text}\n"
        "Da una sola accion concreta para mejorar productividad y una consecuencia esperada simple."
    )
    return internal_summary, ia_context


async def _generate_online_suggestion(context: str) -> tuple[str, str, str, str]:
    provider = os.getenv("AI_PROVIDER", "claude").lower()
    try:
        raw_text, model_used = await _call_ai(provider, ONLINE_AI_SYSTEM, [{"role": "user", "content": context}])
        clean = _extract_json(raw_text)
        parsed = json.loads(clean)
        action = str(parsed.get("accion") or "").strip()
        impact = str(parsed.get("impacto") or "").strip()
        if not action:
            raise ValueError("La IA no devolvio sugerencia.")
        if not impact:
            impact = "Si hacés esto ahora, deberías sostener mejor el ritmo del turno en el próximo bloque."
        return action, impact, provider, model_used
    except Exception as exc:
        logger.warning(f"[cumplimiento-online] IA no disponible: {exc}")
        return (
            "Mover apoyo al sector con menor ritmo del turno.",
            "Si hacés esto ahora, deberías sostener mejor la productividad en el próximo bloque.",
            provider,
            "—",
        )


def _detect_focus_ola(
    olas: list[dict[str, Any]],
    turno_start: datetime,
    cut_end: datetime,
    requested_ola_num: int | None,
) -> dict[str, Any]:
    current_ola = None
    previous_ola = None
    future_ola = None

    for ola in olas:
        ola_start, ola_end = _build_ola_datetimes(turno_start, ola["hora_ini"], ola["hora_fin"])
        if ola_start <= cut_end < ola_end:
            current_ola = ola
            break
        if ola_end <= cut_end:
            previous_ola = ola
        elif future_ola is None and ola_start > cut_end:
            future_ola = ola

    requested = next((ola for ola in olas if ola["num"] == requested_ola_num), None) if requested_ola_num is not None else None
    if current_ola:
        return current_ola
    if requested:
        return requested
    if previous_ola:
        return previous_ola
    if future_ola:
        return future_ola
    return olas[0]


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post("/snapshot")
async def save_snapshot(req: SnapshotRequest):
    """
    Recibe el snapshot parseado del xlsx y lo persiste en la BD.
    Crea o reutiliza el turno del día/programa.
    """
    logger.info(f"[/api/snapshot] programa={req.programa}, turno={req.turno}, olas={len(req.olas)}")

    objetivo_total = sum(o.bultos_prog for o in req.olas)
    dotacion = max((o.dot_ejec for o in req.olas if o.dot_ejec > 0), default=0)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Buscar turno existente para el mismo día/programa/turno
        cursor = await db.execute(
            "SELECT turno_id FROM turnos WHERE fecha=? AND programa_num=? AND turno=? AND cerrado=0",
            (req.fecha, req.programa, req.turno),
        )
        row = await cursor.fetchone()

        if row:
            turno_id = row["turno_id"]
            # Actualizar objetivo y dotación
            await db.execute(
                "UPDATE turnos SET objetivo_total=?, dotacion_real=? WHERE turno_id=?",
                (objetivo_total, dotacion, turno_id),
            )
            logger.info(f"[snapshot] Turno existente actualizado: id={turno_id}")
        else:
            cursor = await db.execute(
                """INSERT INTO turnos (fecha, turno, programa_num, objetivo_total, dotacion_real)
                   VALUES (?, ?, ?, ?, ?)""",
                (req.fecha, req.turno, req.programa, objetivo_total, dotacion),
            )
            turno_id = cursor.lastrowid
            logger.info(f"[snapshot] Nuevo turno creado: id={turno_id}")

        # Eliminar movimientos previos del turno y reinsertar (fresh snapshot)
        await db.execute("DELETE FROM movimientos WHERE turno_id=?", (turno_id,))

        for ola in req.olas:
            await db.execute(
                """INSERT INTO movimientos
                   (turno_id, hora, sector, bultos_programados, bultos_ejecutados,
                    dotacion_prog, dotacion_ejec, prod_prog, prod_ejec, observaciones, ola_num)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    turno_id,
                    ola.hora_ini,
                    ola.sector,
                    ola.bultos_prog,
                    ola.bultos_ejec,
                    ola.dot_prog,
                    ola.dot_ejec,
                    ola.prod_prog,
                    ola.prod_ejec,
                    ola.obs or "",
                    ola.ola_num,
                ),
            )

        await db.commit()

    return {
        "ok": True,
        "turno_id": turno_id,
        "olas_guardadas": len(req.olas),
        "objetivo_total": objetivo_total,
    }


@router.get("/turno/activo")
async def turno_activo():
    """
    Devuelve el turno abierto más reciente con sus movimientos.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """SELECT * FROM turnos WHERE cerrado=0
               ORDER BY created_at DESC LIMIT 1"""
        )
        turno = await cursor.fetchone()

        if not turno:
            return {"turno": None, "movimientos": []}

        turno_dict = dict(turno)

        cursor = await db.execute(
            "SELECT * FROM movimientos WHERE turno_id=? ORDER BY ola_num",
            (turno_dict["turno_id"],),
        )
        movs = await cursor.fetchall()

    movimientos = [dict(m) for m in movs]
    total_ejecutado = sum((m.get("bultos_ejecutados") or 0) for m in movimientos)
    objetivo_total = turno_dict.get("objetivo_total") or 0
    turno_dict["total_ejecutado"] = total_ejecutado
    turno_dict["pct_avance"] = round(total_ejecutado / objetivo_total * 100, 1) if objetivo_total else None
    turno_dict["proceso"] = "picking"

    return {
        "turno": turno_dict,
        "movimientos": movimientos,
    }


@router.get("/turnos")
async def listar_turnos(limit: int = 20):
    """Lista los últimos N turnos (abiertos y cerrados)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM turnos ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
    return {"turnos": [dict(r) for r in rows]}


@router.post("/cumplimiento/online-turno")
async def cumplimiento_online_turno(req: CumplimientoOnlineRequest):
    """
    Reconstruye el avance online del turno seleccionado con snapshots locales
    por bloques de 15 minutos y backfill incremental desde Oracle.
    """
    turno_key = _normalize_turno(req.turno)
    turno_label = _turno_label(turno_key)
    now = datetime.now()
    turno_start = _most_recent_turn_start(turno_key, now)
    cut_end = _floor_to_quarter(now)

    if cut_end <= turno_start:
        raise HTTPException(
            status_code=400,
            detail=f"Aun no hay un corte cerrado de 15 minutos para el turno {turno_label}.",
        )

    turno_inicio_str = _format_dt(turno_start)
    cut_end_str = _format_dt(cut_end)
    fetched_blocks = 0

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        plan_olas = await _load_turn_plan(db, turno_key)
        snapshot_map = await _load_existing_snapshot_map(db, turno_key, turno_inicio_str)

        for block_start, block_end in _build_cut_blocks(turno_start, cut_end):
            block_end_str = _format_dt(block_end)
            if block_end_str in snapshot_map:
                continue

            oracle_from = block_start if block_start == turno_start else block_start + timedelta(seconds=1)
            rows = await asyncio.to_thread(_query_productive_db, _format_dt(oracle_from), block_end_str)
            await _store_snapshot(
                db=db,
                turno_key=turno_key,
                turno_label=turno_label,
                turno_inicio=turno_inicio_str,
                bloque_desde=_format_dt(block_start),
                bloque_hasta=block_end_str,
                rows=rows,
            )
            fetched_blocks += 1

        await db.commit()
        snapshot_map = await _load_existing_snapshot_map(db, turno_key, turno_inicio_str)
        latest_snapshot = snapshot_map.get(cut_end_str)
        if latest_snapshot is None:
            raise HTTPException(status_code=500, detail="No se encontro el snapshot local del corte solicitado.")

        all_rows: list[dict[str, Any]] = []
        for key in sorted(key for key in snapshot_map.keys() if key <= cut_end_str):
            all_rows.extend(_deserialize_rows(snapshot_map[key]["rows_json"]))

        aggregated = _aggregate_turn_rows(all_rows, plan_olas, turno_start, cut_end)
        internal_summary, ia_context = _build_online_context(
            turno_label=turno_label,
            turno_start=turno_start,
            cut_end=cut_end,
            aggregated=aggregated,
        )

        suggestion = latest_snapshot["ia_sugerencia"] or ""
        ia_provider = latest_snapshot["ia_provider"] or os.getenv("AI_PROVIDER", "claude").lower()
        ia_model = latest_snapshot["ia_model"] or "—"
        ia_generated_at = latest_snapshot["ia_generated_at"]
        reused_suggestion = True
        stored_resumen = _deserialize_json_object(latest_snapshot["resumen_json"])
        stored_internal_summary = str(stored_resumen.get("internal_summary") or "").strip()
        stored_impact = str(stored_resumen.get("ia_impact") or "").strip()
        summary_changed = stored_internal_summary != internal_summary.strip()

        if fetched_blocks > 0 or not suggestion or summary_changed:
            suggestion, impact_detail, ia_provider, ia_model = await _generate_online_suggestion(ia_context)
            ia_generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            reused_suggestion = False
            await db.execute(
                """
                UPDATE cumplimiento_online_snapshots
                SET resumen_json = ?,
                    ia_provider = ?,
                    ia_model = ?,
                    ia_prompt_version = ?,
                    ia_sugerencia = ?,
                    ia_generated_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE turno_key = ? AND turno_inicio = ? AND bloque_hasta = ?
                """,
                (
                    json.dumps(
                        {
                            "internal_summary": internal_summary,
                            "resumen": aggregated["resumen"],
                            "ia_impact": impact_detail,
                        },
                        ensure_ascii=False,
                    ),
                    ia_provider,
                    ia_model,
                    ONLINE_AI_PROMPT_VERSION,
                    suggestion,
                    ia_generated_at,
                    turno_key,
                    turno_inicio_str,
                    cut_end_str,
                ),
            )
            await db.commit()
        else:
            impact_detail = stored_impact or "Si hacés esto ahora, deberías sostener mejor la productividad del turno en el próximo bloque."

        turno_totales = {
            turno_label: {
                "prog": round(sum(ola["progTotal"] for ola in aggregated["olas"])),
                "ejec": round(sum(ola["ejecTotal"] for ola in aggregated["olas"])),
            }
        }

    return {
        "turno": turno_label,
        "turno_key": turno_key,
        "turno_inicio": turno_inicio_str,
        "corte_hasta": cut_end_str,
        "oracle_usado": fetched_blocks > 0,
        "bloques_nuevos": fetched_blocks,
        "sin_actualizacion_productiva": fetched_blocks == 0,
        "internal_summary": internal_summary,
        "sugerencia_ia": suggestion,
        "sugerencia_reutilizada": reused_suggestion,
        "ia_provider": ia_provider,
        "ia_model": ia_model,
        "ia_generated_at": ia_generated_at,
        "sugerencia_detalle": impact_detail,
        "olas": aggregated["olas"],
        "bloques": aggregated["bloques"],
        "turnoTotales": turno_totales,
        "resumen": aggregated["resumen"],
        "zonas": aggregated["zonas"],
    }


@router.get("/cumplimiento/ultimo")
async def get_cumplimiento_ultimo():
    """
    Devuelve la ultima foto disponible de cumplimiento por ola usando historico_olas.
    La respuesta esta pensada para hidratar picking.html.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("SELECT MAX(fecha) as fecha FROM historico_olas")
        row = await cursor.fetchone()
        fecha = row["fecha"] if row else None

        if not fecha:
            return {"fecha": None, "programa": None, "olas": [], "turnoTotales": {}}

        cursor = await db.execute(
            """
            SELECT
                ola_num,
                ola_label,
                turno,
                hora_ini,
                hora_fin,
                prog_secos,
                prog_noa,
                ejec_secos,
                ejec_noa,
                dot_prog,
                dot_ejec,
                prod_prog,
                prod_ejec
            FROM historico_olas
            WHERE fecha = ?
            ORDER BY ola_num
            """,
            (fecha,),
        )
        rows = await cursor.fetchall()

    olas = []
    turno_totales = {}
    for r in rows:
        turno = r["turno"]
        prog_total = round((r["prog_secos"] or 0) + (r["prog_noa"] or 0))
        ejec_total = round((r["ejec_secos"] or 0) + (r["ejec_noa"] or 0))
        ini = int(str(r["hora_ini"]).split(":")[0])
        fin = int(str(r["hora_fin"]).split(":")[0])

        olas.append({
            "num": r["ola_num"],
            "label": r["ola_label"] or f"OLA {r['ola_num']}",
            "turno": turno,
            "ini": ini,
            "fin": fin,
            "progSecos": round(r["prog_secos"] or 0),
            "progNOA": round(r["prog_noa"] or 0),
            "progTotal": prog_total,
            "ejecSecos": round(r["ejec_secos"] or 0),
            "ejecNOA": round(r["ejec_noa"] or 0),
            "ejecTotal": ejec_total,
            "dotProg": r["dot_prog"] or 0,
            "dotEjec": r["dot_ejec"] or 0,
            "prodProg": round(r["prod_prog"] or 0, 2),
            "prodEjec": round(r["prod_ejec"] or 0, 2),
            "obs": "",
        })

        turno_totales.setdefault(turno, {"prog": 0, "ejec": 0})
        turno_totales[turno]["prog"] += prog_total
        turno_totales[turno]["ejec"] += ejec_total

    return {
        "fecha": fecha,
        "programa": f"Historico {fecha}",
        "olas": olas,
        "turnoTotales": turno_totales,
    }
