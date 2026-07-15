"""Tablero online de rendimiento de picking por division, sector y legajo."""
from __future__ import annotations

import io
import json
import math
import asyncio
from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel

from routers.productividad_analisis import _query_productive_db_sql


router = APIRouter(prefix="/api/rendimiento-online", tags=["rendimiento-online"])
BASE_DIR = Path(__file__).resolve().parent.parent
STANDARD_PATH = BASE_DIR / "datos" / "productividad_estandar_sector.json"


QUERY_RENDIMIENTO_ONLINE = """
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
FROM F132HIST A
JOIN F602ASEC B
  ON A.CREFEREN = B.CREFEREN
 AND A.CALMACEN = B.CALMACEN
JOIN PV_LEGAJO C
  ON A.COPECREA = C.LEGAJO
LEFT JOIN F002ARTI D
  ON A.CREFEREN = D.CREFEREN
LEFT JOIN (
    SELECT DISTINCT CZONALMA, DESCDIVI
    FROM VW_UBICACIONES_DIVISION
) SUB1
  ON SUB1.CZONALMA = A.CZONAORI
WHERE A.FCREAREG >= TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
  AND A.FCREAREG <= TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
  AND A.CDESCRIP IN ('Picking', 'TRANSPORTE DE PALETS')
ORDER BY A.COPECREA, A.FCREAREG
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

    for division, sector in standard_keys:
        by_sector[(division, sector)]["en_maestro"] = True
        by_division[division]["sectores"].add(sector)

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
        "sectores": sorted(sectores, key=lambda r: (r["division"], not r["en_maestro"], r["estado"], r["sector"])),
        "legajos": sorted(legajos, key=lambda r: (r["division"], r["sector"], r["estado"], -r["productividad_actual"])),
    }


def _query_rows(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return _query_productive_db_sql(
        QUERY_RENDIMIENTO_ONLINE,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


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
    operations = _build_operations(rows, min(oracle_now, rango["fecha_hasta"]), sector_divisions)
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
