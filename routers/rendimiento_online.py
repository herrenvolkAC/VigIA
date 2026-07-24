"""Tablero online de rendimiento de picking por division, sector y legajo."""
from __future__ import annotations

import io
import json
import math
import asyncio
import logging
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel

from db.rendimiento_historico import (
    get_analysis as get_historic_analysis,
    get_run as get_historic_run,
    init_rendimiento_historico_db,
    save_day_cache,
)
from routers.productividad_analisis import _query_productive_db_sql


router = APIRouter(prefix="/api/rendimiento-online", tags=["rendimiento-online"])
BASE_DIR = Path(__file__).resolve().parent.parent
STANDARD_PATH = BASE_DIR / "datos" / "productividad_estandar_sector.json"
logger = logging.getLogger("vigia.rendimiento_online")
HISTORICO_QUERY_VERSION = "rend_online_picking_legajo_sector_v2"
HISTORICO_SCHEDULE_TIME = time(6, 30)
HISTORICO_BACKFILL_DAYS = 62
_historico_scheduler_task: asyncio.Task | None = None
_historico_scheduler_stop: asyncio.Event | None = None


QUERY_RENDIMIENTO_ONLINE = """
WITH HIST_SOURCE AS (
    SELECT
        FCREAREG, CDESCRIP, CNUPALET, QCANTIDA, CREFEREN, CNPEDIDO,
        COPECREA, CZONADES, CZONAORI, CALMACEN
    FROM F132HIST
    WHERE FCREAREG >= TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
      AND FCREAREG <= TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
      AND CDESCRIP IN ('Picking', 'TRANSPORTE DE PALETS')
    UNION ALL
    SELECT
        FCREAREG, CDESCRIP, CNUPALET, QCANTIDA, CREFEREN, CNPEDIDO,
        COPECREA, CZONADES, CZONAORI, CALMACEN
    FROM F132HIST_HIST
    WHERE FCREAREG >= TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
      AND FCREAREG <= TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
      AND CDESCRIP IN ('Picking', 'TRANSPORTE DE PALETS')
)
SELECT
    B.CNSECTOR,
    A.FCREAREG,
    A.CDESCRIP,
    A.CNUPALET,
    A.QCANTIDA,
    A.CREFEREN,
    A.CNPEDIDO,
    A.COPECREA AS LEGAJO,
    C.NOMBRE,
    D.DARTICUL AS DARTICUL,
    A.CZONADES AS DESTINO,
    SUB1.DESCDIVI AS DIVISION,
    SYSDATE AS ORACLE_NOW
FROM HIST_SOURCE A
JOIN F602ASEC B
  ON A.CREFEREN = B.CREFEREN
 AND A.CALMACEN = B.CALMACEN
LEFT JOIN PV_LEGAJO C
  ON A.COPECREA = C.LEGAJO
LEFT JOIN F002ARTI D
  ON A.CREFEREN = D.CREFEREN
LEFT JOIN (
    SELECT DISTINCT CZONALMA, DESCDIVI
    FROM VW_UBICACIONES_DIVISION
) SUB1
  ON SUB1.CZONALMA = A.CZONAORI
ORDER BY A.COPECREA, A.FCREAREG
"""

QUERY_PREMIO_DIAS_PAGO = """
SELECT FECHA, LEGAJO
FROM PV_DIA_LABORAL
WHERE FECHA >= :fecha_desde
  AND FECHA <= :fecha_hasta
ORDER BY FECHA, LEGAJO
"""

QUERY_PREMIO_ESCALAS = """
SELECT
    B.descripcion AS operacion,
    C.descripcion AS division,
    A.nivel,
    A.desde,
    A.hasta,
    A.premio
FROM PV_ESCALA_DE_PREMIOS A
JOIN PV_GRUPO_DE_FUNCIONES_CAB B ON A.ID_DE_GRUPO_DE_FUNCIONES = B.ID
JOIN PV_GRUPO_PRODUCTIVO_CAB C ON A.ID_DE_GRUPO_PRODUCTIVO = C.ID
WHERE B.descripcion = 'PICKING'
ORDER BY C.descripcion, A.nivel
"""

TURNOS = {
    "manana": ("Manana", time(6, 0), time(14, 0)),
    "tarde": ("Tarde", time(14, 0), time(22, 0)),
    "noche": ("Noche", time(22, 0), time(6, 0)),
    "noche_anterior": ("Noche anterior", time(22, 0), time(6, 0)),
}

INITIAL_STANDARDS = [
    ("NOA", "AM", 174), ("NOA", "B5", 339), ("NOA", "CU", 57),
    ("NOA", "EC", 166), ("NOA", "EP", 211), ("NOA", "JC", 173),
    ("NOA", "LB", 10), ("NOA", "MU", 56), ("NOA", "NS", 145),
    ("NOA", "NT", 92), ("NOA", "N1", 204), ("NOA", "N2", 208),
    ("NOA", "PI", 139), ("NOA", "PT", 258), ("NOA", "TV", 14),
    ("NOA", "VA", 90), ("NOA", "VT", 137), ("REFRIGERADOS", "BA", 297),
    ("REFRIGERADOS", "CF", 245), ("REFRIGERADOS", "CO", 179),
    ("REFRIGERADOS", "FB", 145), ("REFRIGERADOS", "FQ", 189),
    ("REFRIGERADOS", "F1", 124), ("REFRIGERADOS", "F2", 136),
    ("REFRIGERADOS", "F4", 157), ("REFRIGERADOS", "HE", 148),
    ("REFRIGERADOS", "HU", 146), ("REFRIGERADOS", "MO", 57),
    ("REFRIGERADOS", "PA", 186), ("REFRIGERADOS", "P4", 34),
    ("REFRIGERADOS", "VE", 128), ("SECOS", "A3", 101), ("SECOS", "B1", 173),
    ("SECOS", "B3", 253), ("SECOS", "CA", 218), ("SECOS", "CH", 137),
    ("SECOS", "IN", 151), ("SECOS", "NP", 66), ("SECOS", "OF", 113),
    ("SECOS", "PE", 154), ("SECOS", "P1", 162), ("SECOS", "P3", 225),
    ("SECOS", "SF", 101),
]


class StandardItem(BaseModel):
    division: str
    sector: str
    productividad_x_hora: float
    activo: bool = True


class StandardsRequest(BaseModel):
    estandares: list[StandardItem]


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_sector(value: Any) -> str:
    text = _norm(value)
    return "".join(ch for ch in text if ch.isalnum())


def _division_by_sector(standards: dict[tuple[str, str], dict[str, Any]]) -> dict[str, str]:
    sector_map: dict[str, set[str]] = defaultdict(set)
    for division, sector in standards:
        sector_norm = _normalize_sector(sector)
        if sector_norm:
            sector_map[sector_norm].add(division)
    return {sector: next(iter(divisions)) for sector, divisions in sector_map.items() if len(divisions) == 1}


def _normalize_division(
    value: Any,
    sector: str = "",
    sector_divisions: dict[str, str] | None = None,
) -> str:
    sector_norm = _normalize_sector(sector)
    if sector_divisions and sector_norm:
        mapped = sector_divisions.get(sector_norm)
        if mapped:
            return mapped
    text = _norm(value)
    if not text:
        return "SIN MAPEAR"
    if "VARIOS NO ALIMENTOS" in text or text == "NOA":
        return "NOA"
    if "SECTOR SECOS" in text or text == "SECOS" or text == "SECOS + NOA":
        return "SECOS"
    if (
        text.startswith("CAMARA")
        or "REFRIG" in text
        or text == "OTRAS CAMARAS"
        or "F&Q" in text
        or "CONGEL" in text
        or "FRUTA" in text
        or "VERDURA" in text
    ):
        return "REFRIGERADOS"
    return text


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            pass
    return None


def _fmt_dt(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _ensure_standards_file() -> None:
    if STANDARD_PATH.exists():
        return
    STANDARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {"division": division, "sector": sector, "productividad_x_hora": prod, "activo": True}
        for division, sector, prod in INITIAL_STANDARDS
    ]
    STANDARD_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_standards() -> list[dict[str, Any]]:
    _ensure_standards_file()
    try:
        raw = json.loads(STANDARD_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo leer el JSON de estandares: {exc}") from exc
    result = []
    for item in raw if isinstance(raw, list) else []:
        division = _normalize_division(item.get("division"))
        sector = _normalize_sector(item.get("sector"))
        if not division or not sector:
            continue
        result.append({
            "division": division,
            "sector": sector,
            "productividad_x_hora": float(item.get("productividad_x_hora") or 0),
            "activo": bool(item.get("activo", True)),
        })
    return sorted(result, key=lambda r: (r["division"], r["sector"]))


def _save_standards(items: list[StandardItem]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    cleaned = []
    for item in items:
        division = _normalize_division(item.division)
        sector = _normalize_sector(item.sector)
        if not division or not sector:
            continue
        key = (division, sector)
        if key in seen:
            raise HTTPException(status_code=400, detail=f"Estandar duplicado: {division} / {sector}")
        seen.add(key)
        cleaned.append({
            "division": division,
            "sector": sector,
            "productividad_x_hora": max(float(item.productividad_x_hora), 0.0),
            "activo": bool(item.activo),
        })
    STANDARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    STANDARD_PATH.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    return sorted(cleaned, key=lambda r: (r["division"], r["sector"]))


def _standard_map() -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (row["division"], row["sector"]): row
        for row in _load_standards()
        if row.get("activo", True)
    }


def _logistic_date(now: datetime) -> datetime:
    base = now.date()
    if now.time() < time(6, 0):
        base = base - timedelta(days=1)
    return datetime.combine(base, time.min)


def _turno_range(turno: str, now: datetime) -> dict[str, Any]:
    key = _norm(turno).lower().replace("ñ", "n")
    if key not in TURNOS:
        key = "manana"
    label, start_t, end_t = TURNOS[key]
    base = _logistic_date(now)
    if key == "noche_anterior":
        base = base - timedelta(days=1)
    start = datetime.combine(base.date(), start_t)
    end_date = base.date() + (timedelta(days=1) if key in {"noche", "noche_anterior"} else timedelta())
    end = datetime.combine(end_date, end_t)
    effective_end = min(now, end) if now >= start else start
    return {
        "turno_key": key,
        "turno_label": label,
        "fecha_desde": start,
        "fecha_hasta": effective_end,
        "fecha_fin_turno": end,
        "dia_logistico": base.strftime("%Y-%m-%d"),
        "en_curso": start <= now <= end,
        "futuro": now < start,
    }


def _status(actual: float, esperado: float) -> tuple[str, float | None]:
    if esperado <= 0:
        return "none", None
    pct = actual / esperado * 100
    if pct >= 95:
        return "ok", pct
    if pct >= 85:
        return "warn", pct
    return "bad", pct


def _new_bucket() -> dict[str, Any]:
    return {
        "bultos": 0.0,
        "segundos": 0.0,
        "operaciones": 0,
        "operaciones_abiertas": 0,
        "operaciones_transporte": 0,
        "operaciones_cambio_sector": 0,
        "primer_movimiento": None,
        "ultimo_movimiento": None,
        "legajos": set(),
        "sectores": set(),
        "sectores_con_actividad": set(),
        "legajos_bad": set(),
        "legajos_warn": set(),
    }


def _add_dt(bucket: dict[str, Any], start: datetime | None, end: datetime | None) -> None:
    if start and (bucket["primer_movimiento"] is None or start < bucket["primer_movimiento"]):
        bucket["primer_movimiento"] = start
    if end and (bucket["ultimo_movimiento"] is None or end > bucket["ultimo_movimiento"]):
        bucket["ultimo_movimiento"] = end


def _build_operations(
    rows: list[dict[str, Any]],
    now: datetime,
    sector_divisions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows_sorted = sorted(
        rows,
        key=lambda r: (_norm(r.get("LEGAJO")), _parse_dt(r.get("FCREAREG")) or datetime.min),
    )
    operations: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    last_pick_time: datetime | None = None

    def close_current(end_dt: datetime, cierre: str) -> None:
        nonlocal current, last_pick_time
        if not current:
            return
        seconds = max((end_dt - current["inicio"]).total_seconds(), 0.0)
        current.update({
            "fin": end_dt,
            "segundos": seconds,
            "cierre": cierre,
        })
        operations.append(current)
        current = None
        last_pick_time = None

    for row in rows_sorted:
        mov_dt = _parse_dt(row.get("FCREAREG"))
        if not mov_dt:
            continue
        operacion = _norm(row.get("CDESCRIP"))
        legajo = _norm(row.get("LEGAJO"))
        sector = _normalize_sector(row.get("CNSECTOR")) or "SIN SECTOR"
        division = _normalize_division(row.get("DIVISION"), sector, sector_divisions)
        nombre = str(row.get("NOMBRE") or "").strip()
        cantidad = float(row.get("QCANTIDA") or 0)

        if current and current["legajo"] != legajo:
            close_current(last_pick_time or current["inicio"], "CAMBIO_LEGAJO")

        if operacion == "PICKING":
            if current and current["sector"] != sector:
                close_current(last_pick_time or mov_dt, "CAMBIO_SECTOR")
            if not current:
                current = {
                    "division": division,
                    "sector": sector,
                    "legajo": legajo,
                    "nombre": nombre,
                    "inicio": mov_dt,
                    "bultos": 0.0,
                    "pallets": set(),
                    "pedidos": set(),
                }
            current["bultos"] += cantidad
            if row.get("CNUPALET"):
                current["pallets"].add(str(row.get("CNUPALET")))
            if row.get("CNPEDIDO"):
                current["pedidos"].add(str(row.get("CNPEDIDO")))
            last_pick_time = mov_dt
        elif operacion == "TRANSPORTE DE PALETS" and current:
            close_current(mov_dt, "TRANSPORTE")

    if current:
        close_current(now, "ABIERTA")
    for op in operations:
        op["pallets"] = len(op.get("pallets") or [])
        op["pedidos"] = len(op.get("pedidos") or [])
    return operations


def _decorate_row(row: dict[str, Any], expected: float) -> dict[str, Any]:
    horas = row["segundos"] / 3600 if row["segundos"] else 0.0
    actual = row["bultos"] / horas if horas > 0 else 0.0
    estado, cumplimiento = _status(actual, expected)
    expected_bultos = expected * horas if expected > 0 else 0.0
    row.update({
        "horas": round(horas, 4),
        "productividad_actual": round(actual, 2),
        "productividad_esperada": round(expected, 2),
        "productividad_esperada_turno": round(expected * 6.5, 2),
        "bultos_esperados": round(expected_bultos, 2),
        "cumplimiento_pct": round(cumplimiento, 1) if cumplimiento is not None and math.isfinite(cumplimiento) else None,
        "estado": estado,
        "primer_movimiento": _fmt_dt(row.get("primer_movimiento")),
        "ultimo_movimiento": _fmt_dt(row.get("ultimo_movimiento")),
    })
    return row


def _normalize_records(rows: list[dict[str, Any]], sector_divisions: dict[str, str] | None = None) -> list[dict[str, Any]]:
    raw_records = []
    for row in rows:
        mov_dt = _parse_dt(row.get("FCREAREG"))
        if not mov_dt:
            continue
        sector = _normalize_sector(row.get("CNSECTOR")) or "SIN SECTOR"
        division = _normalize_division(row.get("DIVISION"), sector, sector_divisions)
        operacion = str(row.get("CDESCRIP") or "").strip()
        raw_records.append({
            "division": division,
            "sector": sector,
            "legajo": _norm(row.get("LEGAJO")),
            "nombre": str(row.get("NOMBRE") or "").strip(),
            "fecha_dt": mov_dt,
            "operacion": operacion,
            "pallet": str(row.get("CNUPALET") or "").strip(),
            "cantidad": float(row.get("QCANTIDA") or 0),
            "referencia": str(row.get("CREFEREN") or "").strip(),
            "articulo_descripcion": str(row.get("DARTICUL") or "").strip(),
            "pedido": str(row.get("CNPEDIDO") or "").strip(),
            "destino": str(row.get("DESTINO") or "").strip(),
        })
    raw_records.sort(key=lambda r: (r["legajo"], r["fecha_dt"], r["sector"], r["operacion"]))

    records = []
    transport_group: dict[str, Any] | None = None
    last_event_by_legajo: dict[str, datetime] = {}

    def append_event(event: dict[str, Any]) -> None:
        legajo = event["legajo"]
        event_dt = event.pop("fecha_dt")
        prev_dt = last_event_by_legajo.get(legajo)
        minutes = (event_dt - prev_dt).total_seconds() / 60 if prev_dt else None
        last_event_by_legajo[legajo] = event_dt
        event["fecha"] = _fmt_dt(event_dt)
        event["minutos"] = round(minutes, 1) if minutes is not None and minutes >= 0 else None
        records.append(event)

    def flush_transport() -> None:
        nonlocal transport_group
        if not transport_group:
            return
        append_event(transport_group)
        transport_group = None

    for record in raw_records:
        if _norm(record["operacion"]) == "TRANSPORTE DE PALETS":
            group_key = (record["legajo"], record["division"], record["sector"], record["pallet"])
            current_key = transport_group.get("group_key") if transport_group else None
            if transport_group and current_key != group_key:
                flush_transport()
            if not transport_group:
                transport_group = {
                    "group_key": group_key,
                    "division": record["division"],
                    "sector": record["sector"],
                    "legajo": record["legajo"],
                    "nombre": record["nombre"],
                    "fecha_dt": record["fecha_dt"],
                    "operacion": "TRANSPORTE DE PALETS",
                    "pallet": record["pallet"],
                    "cantidad": 0.0,
                    "referencia": "",
                    "articulo_descripcion": "",
                    "pedido": "",
                    "destino": record["destino"],
                    "movimientos_agrupados": 0,
                }
            transport_group["fecha_dt"] = max(transport_group["fecha_dt"], record["fecha_dt"])
            if record["destino"]:
                transport_group["destino"] = record["destino"]
            transport_group["movimientos_agrupados"] += 1
            continue
        flush_transport()
        record["movimientos_agrupados"] = 1
        append_event(record)
    flush_transport()

    for record in records:
        record.pop("group_key", None)
    return sorted(records, key=lambda r: (r["division"], r["sector"], r["legajo"], r["fecha"] or ""))


def _summarize(operations: list[dict[str, Any]], standards: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    by_legajo: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(_new_bucket)
    by_sector: dict[tuple[str, str], dict[str, Any]] = defaultdict(_new_bucket)
    by_division: dict[str, dict[str, Any]] = defaultdict(_new_bucket)
    standard_keys = set(standards.keys())

    for op in operations:
        division = op["division"]
        sector = op["sector"]
        legajo = op["legajo"]
        seconds = float(op["segundos"] or 0)
        bultos = float(op["bultos"] or 0)
        for bucket in (by_legajo[(division, sector, legajo)], by_sector[(division, sector)], by_division[division]):
            bucket["bultos"] += bultos
            bucket["segundos"] += seconds
            bucket["operaciones"] += 1
            bucket["legajos"].add(legajo)
            bucket["sectores"].add(sector)
            bucket["sectores_con_actividad"].add(sector)
            if op["cierre"] == "ABIERTA":
                bucket["operaciones_abiertas"] += 1
            elif op["cierre"] == "TRANSPORTE":
                bucket["operaciones_transporte"] += 1
            elif op["cierre"] == "CAMBIO_SECTOR":
                bucket["operaciones_cambio_sector"] += 1
            _add_dt(bucket, op.get("inicio"), op.get("fin"))
        leg = by_legajo[(division, sector, legajo)]
        leg["division"] = division
        leg["sector"] = sector
        leg["legajo"] = legajo
        leg["nombre"] = op.get("nombre") or leg.get("nombre") or ""

    legajos = []
    for (division, sector, _legajo), row in by_legajo.items():
        expected = float(standards.get((division, sector), {}).get("productividad_x_hora") or 0)
        en_maestro = (division, sector) in standard_keys
        clean = {
            "division": division,
            "sector": sector,
            "legajo": row["legajo"],
            "nombre": row.get("nombre") or "",
            "en_maestro": en_maestro,
            "requiere_maestro": not en_maestro,
            "bultos": round(row["bultos"], 2),
            "segundos": round(row["segundos"], 1),
            "operaciones": row["operaciones"],
            "operaciones_abiertas": row["operaciones_abiertas"],
            "primer_movimiento": row["primer_movimiento"],
            "ultimo_movimiento": row["ultimo_movimiento"],
        }
        legajos.append(_decorate_row(clean, expected))

    legajo_status = {(r["division"], r["sector"], r["legajo"]): r["estado"] for r in legajos}
    for row in legajos:
        sector_bucket = by_sector[(row["division"], row["sector"])]
        division_bucket = by_division[row["division"]]
        if row["estado"] == "bad":
            sector_bucket["legajos_bad"].add(row["legajo"])
            division_bucket["legajos_bad"].add(row["legajo"])
        elif row["estado"] == "warn":
            sector_bucket["legajos_warn"].add(row["legajo"])
            division_bucket["legajos_warn"].add(row["legajo"])

    sectores = []
    sectores_bad_by_division: dict[str, set[str]] = defaultdict(set)
    sectores_warn_by_division: dict[str, set[str]] = defaultdict(set)
    for (division, sector), row in by_sector.items():
        expected = float(standards.get((division, sector), {}).get("productividad_x_hora") or 0)
        en_maestro = (division, sector) in standard_keys
        clean = {
            "division": division,
            "sector": sector,
            "en_maestro": en_maestro,
            "requiere_maestro": not en_maestro,
            "bultos": round(row["bultos"], 2),
            "segundos": round(row["segundos"], 1),
            "operaciones": row["operaciones"],
            "operaciones_abiertas": row["operaciones_abiertas"],
            "legajos_activos": len(row["legajos"]),
            "legajos_rojo": len(row["legajos_bad"]),
            "legajos_amarillo": len(row["legajos_warn"]),
            "primer_movimiento": row["primer_movimiento"],
            "ultimo_movimiento": row["ultimo_movimiento"],
        }
        item = _decorate_row(clean, expected)
        if item["estado"] == "bad":
            sectores_bad_by_division[division].add(sector)
        elif item["estado"] == "warn":
            sectores_warn_by_division[division].add(sector)
        sectores.append(item)

    divisiones = []
    for division, row in by_division.items():
        expected_bultos = 0.0
        for sector in row["sectores"]:
            sec = by_sector[(division, sector)]
            expected = float(standards.get((division, sector), {}).get("productividad_x_hora") or 0)
            expected_bultos += expected * (sec["segundos"] / 3600)
        horas = row["segundos"] / 3600 if row["segundos"] else 0
        expected_hour = expected_bultos / horas if horas > 0 else 0.0
        clean = {
            "division": division,
            "bultos": round(row["bultos"], 2),
            "segundos": round(row["segundos"], 1),
            "operaciones": row["operaciones"],
            "operaciones_abiertas": row["operaciones_abiertas"],
            "sectores_activos": len(row["sectores_con_actividad"]),
            "sectores_total": len(row["sectores"]),
            "sectores_maestro": sum(1 for sector in row["sectores"] if (division, sector) in standard_keys),
            "sectores_fuera_maestro": sum(1 for sector in row["sectores"] if (division, sector) not in standard_keys),
            "legajos_activos": len(row["legajos"]),
            "sectores_rojo": len(sectores_bad_by_division[division]),
            "sectores_amarillo": len(sectores_warn_by_division[division]),
            "legajos_rojo": len(row["legajos_bad"]),
            "legajos_amarillo": len(row["legajos_warn"]),
            "primer_movimiento": row["primer_movimiento"],
            "ultimo_movimiento": row["ultimo_movimiento"],
        }
        item = _decorate_row(clean, expected_hour)
        item["bultos_esperados"] = round(expected_bultos, 2)
        divisiones.append(item)

    return {
        "divisiones": sorted(divisiones, key=lambda r: r["division"]),
        "sectores": sorted(sectores, key=lambda r: (r["division"], r["en_maestro"], r["estado"], r["sector"])),
        "legajos": sorted(legajos, key=lambda r: (r["division"], r["sector"], r["estado"], -r["productividad_actual"])),
    }


def query_rendimiento_online_rows(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return _query_productive_db_sql(
        QUERY_RENDIMIENTO_ONLINE,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


def build_rendimiento_online_operations(rows: list[dict[str, Any]], cutoff: datetime) -> list[dict[str, Any]]:
    standards = _standard_map()
    return _build_operations(rows, cutoff, _division_by_sector(standards))


def _query_rows(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return query_rendimiento_online_rows(fecha_desde, fecha_hasta)


def _standards_diagnostics(summary: dict[str, Any], standards: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    fuera_maestro = [
        {
            "division": row.get("division"),
            "sector": row.get("sector"),
            "bultos": row.get("bultos"),
            "legajos_activos": row.get("legajos_activos"),
            "ultimo_movimiento": row.get("ultimo_movimiento"),
        }
        for row in summary.get("sectores", [])
        if row.get("requiere_maestro") and (row.get("operaciones") or 0) > 0
    ]
    by_division: dict[str, int] = defaultdict(int)
    for division, _sector in standards:
        by_division[division] += 1
    return {
        "standard_path": str(STANDARD_PATH),
        "estandares_activos": len(standards),
        "estandares_por_division": dict(sorted(by_division.items())),
        "sectores_fuera_maestro_activos": sorted(
            fuera_maestro,
            key=lambda r: (str(r.get("division") or ""), str(r.get("sector") or "")),
        ),
    }


async def _build_payload(turno: str) -> dict[str, Any]:
    now = datetime.now()
    rango = _turno_range(turno, now)
    fecha_desde = _fmt_dt(rango["fecha_desde"])
    fecha_hasta = _fmt_dt(rango["fecha_hasta"])
    if not fecha_desde or not fecha_hasta:
        raise HTTPException(status_code=400, detail="Rango de turno invalido.")
    rows = await asyncio.to_thread(_query_rows, fecha_desde, fecha_hasta)
    oracle_now = next((_parse_dt(row.get("ORACLE_NOW")) for row in rows if row.get("ORACLE_NOW")), None) or now
    standards = _standard_map()
    sector_divisions = _division_by_sector(standards)
    operations = build_rendimiento_online_operations(rows, min(oracle_now, rango["fecha_hasta"]))
    summary = _summarize(operations, standards)
    diagnostics = _standards_diagnostics(summary, standards)
    return {
        "rango": {
            **{k: v for k, v in rango.items() if k not in {"fecha_desde", "fecha_hasta", "fecha_fin_turno"}},
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "fecha_fin_turno": _fmt_dt(rango["fecha_fin_turno"]),
            "server_now": _fmt_dt(now),
            "oracle_now": _fmt_dt(oracle_now),
        },
        "summary": {
            "movimientos": len(rows),
            "operaciones": len(operations),
            "source_name": "oracle_productiva",
        },
        "diagnostico_estandares": diagnostics,
        "registros": _normalize_records(rows, sector_divisions),
        **summary,
    }


def _closed_logistic_days(now: datetime, days: int = HISTORICO_BACKFILL_DAYS) -> list[dict[str, Any]]:
    last_closed = _logistic_date(now)
    if now.time() < time(6, 0):
        last_closed = last_closed - timedelta(days=1)
    result = []
    for offset in range(days):
        start = last_closed - timedelta(days=offset + 1)
        end = start + timedelta(days=1)
        result.append({
            "dia_logistico": start.strftime("%Y-%m-%d"),
            "fecha_desde": start.replace(hour=6).strftime("%Y-%m-%d %H:%M:%S"),
            "fecha_hasta": end.replace(hour=6).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return result


async def _cache_closed_day(day: dict[str, Any], *, force: bool = False, trigger: str = "manual") -> dict[str, Any]:
    operacion = "PICKING"
    existing = await get_historic_run(operacion, day["dia_logistico"])
    if (
        existing
        and existing.get("status") == "success"
        and existing.get("query_version") == HISTORICO_QUERY_VERSION
        and not force
    ):
        return {"dia_logistico": day["dia_logistico"], "status": "skipped"}
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        rows = await asyncio.to_thread(query_rendimiento_online_rows, day["fecha_desde"], day["fecha_hasta"])
        standards = _standard_map()
        operations = _build_operations(rows, _parse_dt(day["fecha_hasta"]) or datetime.now(), _division_by_sector(standards))
        summary = _summarize(operations, standards)
        saved = await save_day_cache(
            operacion=operacion,
            dia_logistico=day["dia_logistico"],
            fecha_desde=day["fecha_desde"],
            fecha_hasta=day["fecha_hasta"],
            movimientos=len(rows),
            operaciones=len(operations),
            query_version=HISTORICO_QUERY_VERSION,
            legajos=summary["legajos"],
            started_at=started,
        )
        logger.info(
            "[rendimiento-historico] Cache %s dia=%s movimientos=%s operaciones=%s trigger=%s",
            operacion, day["dia_logistico"], len(rows), len(operations), trigger,
        )
        return saved
    except Exception as exc:
        await save_day_cache(
            operacion=operacion,
            dia_logistico=day["dia_logistico"],
            fecha_desde=day["fecha_desde"],
            fecha_hasta=day["fecha_hasta"],
            movimientos=0,
            operaciones=0,
            query_version=HISTORICO_QUERY_VERSION,
            legajos=[],
            status="error",
            error=str(exc),
            started_at=started,
        )
        logger.exception("[rendimiento-historico] Error cacheando dia %s", day["dia_logistico"])
        return {"dia_logistico": day["dia_logistico"], "status": "error", "error": str(exc)}


async def run_rendimiento_historico_backfill(
    *, force: bool = False, trigger: str = "manual", days: int = HISTORICO_BACKFILL_DAYS
) -> dict[str, Any]:
    await init_rendimiento_historico_db()
    closed_days = _closed_logistic_days(datetime.now(), days)
    results = []
    for day in closed_days:
        results.append(await _cache_closed_day(day, force=force, trigger=trigger))
    return {
        "ok": True,
        "operacion": "PICKING",
        "days_checked": len(closed_days),
        "cached": sum(1 for row in results if row.get("status") == "success"),
        "skipped": sum(1 for row in results if row.get("status") == "skipped"),
        "errors": [row for row in results if row.get("status") == "error"],
        "results": results,
    }


def _next_historico_run_after(now: datetime) -> datetime:
    candidate = datetime.combine(now.date(), HISTORICO_SCHEDULE_TIME)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


async def _historico_scheduler_loop() -> None:
    assert _historico_scheduler_stop is not None
    await init_rendimiento_historico_db()
    logger.info("[rendimiento-historico] Scheduler iniciado. Hora diaria: %s.", HISTORICO_SCHEDULE_TIME.strftime("%H:%M"))
    while not _historico_scheduler_stop.is_set():
        now = datetime.now()
        run_time = datetime.combine(now.date(), HISTORICO_SCHEDULE_TIME)
        if run_time <= now < run_time + timedelta(minutes=10):
            await run_rendimiento_historico_backfill(trigger="scheduler")
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(_historico_scheduler_stop.wait(), timeout=600)
            continue
        next_run = _next_historico_run_after(now)
        sleep_seconds = max(30.0, min((next_run - now).total_seconds(), 1800.0))
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(_historico_scheduler_stop.wait(), timeout=sleep_seconds)


def start_rendimiento_historico_scheduler() -> None:
    global _historico_scheduler_task, _historico_scheduler_stop
    if _historico_scheduler_task and not _historico_scheduler_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _historico_scheduler_stop = asyncio.Event()
    _historico_scheduler_task = loop.create_task(_historico_scheduler_loop())


async def stop_rendimiento_historico_scheduler() -> None:
    global _historico_scheduler_task, _historico_scheduler_stop
    if _historico_scheduler_stop:
        _historico_scheduler_stop.set()
    if _historico_scheduler_task:
        _historico_scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await _historico_scheduler_task
    _historico_scheduler_task = None
    _historico_scheduler_stop = None


def _premium_group_for_row(row: dict[str, Any]) -> tuple[str, str]:
    division = _normalize_division(row.get("division"))
    if division in {"SECOS", "NOA"}:
        return "SECOS + NOA", "SECOS/NOA agrupado por escala"
    if division == "REFRIGERADOS":
        return "OTRAS CAMARAS", "REFRIGERADOS estimado como OTRAS CAMARAS"
    return division or "SIN ESCALA", "division directa"


def _scale_match(scales: list[dict[str, Any]], bultos: float) -> dict[str, Any] | None:
    for scale in sorted(scales, key=lambda r: (float(r.get("DESDE") or 0), float(r.get("NIVEL") or 0))):
        desde = float(scale.get("DESDE") or 0)
        hasta = float(scale.get("HASTA") or 0)
        if bultos >= desde and (hasta <= 0 or bultos <= hasta):
            return scale
    return None


def _yyyymmdd(day: str) -> int:
    return int(str(day or "").replace("-", "")[:8] or 0)


async def _build_premios_no_incluidos(
    *,
    operacion: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> dict[str, Any]:
    historic = await get_historic_analysis(
        operacion=operacion,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    pagos_rows, escala_rows = await asyncio.gather(
        asyncio.to_thread(_query_productive_db_sql, QUERY_PREMIO_DIAS_PAGO, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta),
        asyncio.to_thread(_query_productive_db_sql, QUERY_PREMIO_ESCALAS, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta),
    )
    pagos = {
        (int(row.get("FECHA") or 0), str(row.get("LEGAJO") or "").strip())
        for row in pagos_rows
        if row.get("FECHA") is not None and str(row.get("LEGAJO") or "").strip()
    }
    escalas: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in escala_rows:
        grupo = _norm(row.get("DIVISION"))
        if grupo:
            escalas[grupo].append(row)

    by_day_group: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in historic.get("diario", []):
        legajo = str(row.get("legajo") or "").strip()
        day = str(row.get("dia_logistico") or "")
        if not legajo or not day:
            continue
        fecha_num = _yyyymmdd(day)
        if (fecha_num, legajo) in pagos:
            continue
        grupo, criterio = _premium_group_for_row(row)
        key = (legajo, day, grupo)
        item = by_day_group.setdefault(key, {
            "legajo": legajo,
            "nombre": row.get("nombre") or "",
            "dia_logistico": day,
            "fecha_pago": fecha_num,
            "grupo_premio": grupo,
            "criterio_grupo": criterio,
            "sector_rrhh": row.get("sector_rrhh") or "",
            "funcion": row.get("funcion") or "",
            "area_personal": row.get("area_personal") or "",
            "fecha_ingreso": row.get("fecha_ingreso"),
            "antiguedad_dias_calc": row.get("antiguedad_dias_calc"),
            "estrato": row.get("estrato"),
            "bultos": 0.0,
            "segundos": 0.0,
            "divisiones": set(),
            "sectores": set(),
            "ultimo_movimiento": row.get("ultimo_movimiento"),
        })
        item["bultos"] += float(row.get("bultos") or 0)
        item["segundos"] += float(row.get("segundos") or 0)
        item["divisiones"].add(row.get("division"))
        item["sectores"].add(row.get("sector"))
        if row.get("ultimo_movimiento") and (not item.get("ultimo_movimiento") or row["ultimo_movimiento"] > item["ultimo_movimiento"]):
            item["ultimo_movimiento"] = row["ultimo_movimiento"]

    detalle = []
    for item in by_day_group.values():
        bultos = float(item.get("bultos") or 0)
        scales = escalas.get(_norm(item.get("grupo_premio")), [])
        match = _scale_match(scales, bultos)
        divisiones = sorted(str(v) for v in item.pop("divisiones") if v)
        sectores = sorted(str(v) for v in item.pop("sectores") if v)
        item.update({
            "bultos": round(bultos, 2),
            "minutos": round(float(item.get("segundos") or 0) / 60, 1),
            "divisiones_count": len(divisiones),
            "divisiones_lista": ", ".join(divisiones),
            "sectores_count": len(sectores),
            "sectores_lista": ", ".join(sectores),
            "nivel": int(match.get("NIVEL")) if match else None,
            "desde": float(match.get("DESDE") or 0) if match else None,
            "hasta": float(match.get("HASTA") or 0) if match else None,
            "premio": round(float(match.get("PREMIO") or 0), 2) if match else 0.0,
            "estado_premio": "estimado" if match else "sin_escala",
        })
        detalle.append(item)

    by_legajo: dict[str, dict[str, Any]] = {}
    for row in detalle:
        legajo = row["legajo"]
        leg = by_legajo.setdefault(legajo, {
            "legajo": legajo,
            "nombre": row.get("nombre") or "",
            "sector_rrhh": row.get("sector_rrhh") or "",
            "funcion": row.get("funcion") or "",
            "area_personal": row.get("area_personal") or "",
            "fecha_ingreso": row.get("fecha_ingreso"),
            "antiguedad_dias_calc": row.get("antiguedad_dias_calc"),
            "estrato": row.get("estrato"),
            "dias": set(),
            "grupos": set(),
            "divisiones": set(),
            "sectores": set(),
            "bultos": 0.0,
            "minutos": 0.0,
            "premio_estimado": 0.0,
            "dias_sin_escala": 0,
            "mejor_nivel": None,
            "ultimo_movimiento": row.get("ultimo_movimiento"),
        })
        leg["dias"].add(row.get("dia_logistico"))
        leg["grupos"].add(row.get("grupo_premio"))
        for value in str(row.get("divisiones_lista") or "").split(","):
            if value.strip():
                leg["divisiones"].add(value.strip())
        for value in str(row.get("sectores_lista") or "").split(","):
            if value.strip():
                leg["sectores"].add(value.strip())
        leg["bultos"] += float(row.get("bultos") or 0)
        leg["minutos"] += float(row.get("minutos") or 0)
        leg["premio_estimado"] += float(row.get("premio") or 0)
        if row.get("estado_premio") == "sin_escala":
            leg["dias_sin_escala"] += 1
        nivel = row.get("nivel")
        if nivel is not None and (leg["mejor_nivel"] is None or int(nivel) > int(leg["mejor_nivel"])):
            leg["mejor_nivel"] = int(nivel)
        if row.get("ultimo_movimiento") and (not leg.get("ultimo_movimiento") or row["ultimo_movimiento"] > leg["ultimo_movimiento"]):
            leg["ultimo_movimiento"] = row["ultimo_movimiento"]

    legajos = []
    for item in by_legajo.values():
        for key in ("dias", "grupos", "divisiones", "sectores"):
            values = sorted(str(v) for v in item[key] if v)
            item[f"{key}_count"] = len(values)
            item[f"{key}_lista"] = ", ".join(values)
            item.pop(key, None)
        item["bultos"] = round(float(item.get("bultos") or 0), 2)
        item["minutos"] = round(float(item.get("minutos") or 0), 1)
        item["premio_estimado"] = round(float(item.get("premio_estimado") or 0), 2)
        legajos.append(item)

    legajos.sort(key=lambda r: (-float(r.get("premio_estimado") or 0), str(r.get("legajo") or "")))
    detalle.sort(key=lambda r: (str(r.get("legajo") or ""), str(r.get("dia_logistico") or ""), str(r.get("grupo_premio") or "")))
    resumen = {
        "legajos": len(legajos),
        "dias_no_incluidos": len({(row.get("legajo"), row.get("dia_logistico")) for row in detalle}),
        "filas_estimadas": len(detalle),
        "bultos": round(sum(float(row.get("bultos") or 0) for row in detalle), 2),
        "premio_estimado": round(sum(float(row.get("premio") or 0) for row in detalle), 2),
        "sin_escala": sum(1 for row in detalle if row.get("estado_premio") == "sin_escala"),
        "pagos_oracle": len(pagos_rows),
        "escalas": len(escala_rows),
    }
    return {
        "source": "rendimiento_historico_cache + oracle_productiva",
        "operacion": operacion,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "resumen": resumen,
        "legajos": legajos,
        "detalle": detalle,
        "escalas": escala_rows,
    }


@router.get("/estandares")
async def get_estandares():
    return {"estandares": _load_standards()}


@router.put("/estandares")
async def put_estandares(req: StandardsRequest):
    return {"estandares": _save_standards(req.estandares)}


@router.get("/tablero")
async def get_tablero(turno: str = Query("manana")):
    try:
        return await _build_payload(turno)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo calcular rendimiento online: {exc}") from exc


@router.get("/historico/analisis")
async def get_historico_analisis(
    operacion: str = Query("PICKING"),
    fecha_desde: str = Query(""),
    fecha_hasta: str = Query(""),
):
    op = _norm(operacion)
    if op != "PICKING":
        raise HTTPException(status_code=400, detail="Por ahora solo esta disponible la operacion Picking.")
    today = _logistic_date(datetime.now()).date()
    default_to = (today - timedelta(days=1)).isoformat()
    default_from = (today - timedelta(days=62)).isoformat()
    return await get_historic_analysis(
        operacion=op,
        fecha_desde=fecha_desde or default_from,
        fecha_hasta=fecha_hasta or default_to,
    )


@router.get("/historico/premios-no-incluidos")
async def get_historico_premios_no_incluidos(
    operacion: str = Query("PICKING"),
    fecha_desde: str = Query(""),
    fecha_hasta: str = Query(""),
):
    op = _norm(operacion)
    if op != "PICKING":
        raise HTTPException(status_code=400, detail="Por ahora solo esta disponible la operacion Picking.")
    today = _logistic_date(datetime.now()).date()
    default_to = (today - timedelta(days=1)).isoformat()
    default_from = (today - timedelta(days=62)).isoformat()
    try:
        return await _build_premios_no_incluidos(
            operacion=op,
            fecha_desde=fecha_desde or default_from,
            fecha_hasta=fecha_hasta or default_to,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo estimar premios no incluidos: {exc}") from exc


@router.get("/export/legajos.xlsx")
async def export_legajos(turno: str = Query("manana"), division: str = Query(""), sector: str = Query("")):
    payload = await _build_payload(turno)
    div_filter = _normalize_division(division) if division else ""
    sec_filter = _normalize_sector(sector)
    rows = [
        row for row in payload["legajos"]
        if (not div_filter or row["division"] == div_filter)
        and (not sec_filter or row["sector"] == sec_filter)
    ]

    wb = Workbook()
    ws = wb.active
    ws.title = "Legajos"
    headers = [
        "Division", "Sector", "Legajo", "Nombre", "Bultos", "Segundos", "Horas",
        "Productividad actual", "Productividad esperada", "Cumplimiento %",
        "Estado", "Operaciones", "Operaciones abiertas", "Primer movimiento", "Ultimo movimiento",
    ]
    ws.append(headers)
    for row in rows:
        ws.append([
            row.get("division"), row.get("sector"), row.get("legajo"), row.get("nombre"),
            row.get("bultos"), row.get("segundos"), row.get("horas"),
            row.get("productividad_actual"), row.get("productividad_esperada"),
            row.get("cumplimiento_pct"), row.get("estado"), row.get("operaciones"),
            row.get("operaciones_abiertas"), row.get("primer_movimiento"), row.get("ultimo_movimiento"),
        ])
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 10), 34)
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = f"rendimiento_legajos_{payload['rango']['turno_key']}.xlsx"
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
