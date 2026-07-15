from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db.auth import auth_db
from db.plantel_optimo import plantel_optimo_db
from routers.auth_local import current_auth
from routers.productividad_analisis import _query_productive_db_sql


router = APIRouter(prefix="/api/plantel-optimo", tags=["plantel-optimo"])


QUERY_PLANTEL_OPTIMO_DEMANDA = """
SELECT
    CASE p.codigodedivision
        WHEN 1 THEN 'SECOS'
        WHEN 2 THEN 'REFRIGERADOS'
        WHEN 4 THEN 'REFRIGERADOS'
        WHEN 6 THEN 'NOA'
        ELSE 'OTROS'
    END AS almacen,
    CODIGODESECTOR AS sector,
    CASE WHEN p.TIPO LIKE '%PICKING%' THEN 'PICKING' END AS tipo,
    COUNT(DISTINCT P.NUMERO) AS cantidad_pallet,
    SUM(d.cantidad) AS bultos_pallet,
    TO_NUMBER(TO_CHAR(v.FECHAYHORADEINICIO, 'HH24')) AS hora
FROM TR_VIAJE v
JOIN TR_CARGAS c
  ON v.CODIGO = c.CODIGODEVIAJE
JOIN TR_PALLET p
  ON c.NUMERODEPALLET = p.NUMERO
JOIN TR_DETALLE_DE_PALLET_NEW d
  ON d.pallet_id = p.NUMERO
WHERE v.FECHAYHORADEINICIO >= TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
  AND v.FECHAYHORADEINICIO <  TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
  AND p.TIPO LIKE '%PICKIN%'
GROUP BY
    CODIGODESECTOR,
    TO_NUMBER(TO_CHAR(v.FECHAYHORADEINICIO, 'HH24')),
    CASE p.codigodedivision
        WHEN 1 THEN 'SECOS'
        WHEN 2 THEN 'REFRIGERADOS'
        WHEN 4 THEN 'REFRIGERADOS'
        WHEN 6 THEN 'NOA'
        ELSE 'OTROS'
    END,
    CASE WHEN p.TIPO LIKE '%PICKING%' THEN 'PICKING' END
ORDER BY almacen, sector, hora
"""


PRODUCTIVIDAD_SECTOR_ESTANDAR = [
    {"almacen": "NOA", "sector": "AM", "productividad_hora": 160},
    {"almacen": "SECOS", "sector": "A3", "productividad_hora": 82},
    {"almacen": "REFRIGERADOS", "sector": "BA", "productividad_hora": 387},
    {"almacen": "SECOS", "sector": "B1", "productividad_hora": 174},
    {"almacen": "SECOS", "sector": "B3", "productividad_hora": 276},
    {"almacen": "NOA", "sector": "B5", "productividad_hora": 87},
    {"almacen": "REFRIGERADOS", "sector": "CO", "productividad_hora": 140},
    {"almacen": "NOA", "sector": "EC", "productividad_hora": 141},
    {"almacen": "NOA", "sector": "EP", "productividad_hora": 180},
    {"almacen": "REFRIGERADOS", "sector": "FB", "productividad_hora": 158},
    {"almacen": "REFRIGERADOS", "sector": "FQ", "productividad_hora": 197},
    {"almacen": "REFRIGERADOS", "sector": "F1", "productividad_hora": 130},
    {"almacen": "REFRIGERADOS", "sector": "F4", "productividad_hora": 148},
    {"almacen": "REFRIGERADOS", "sector": "HU", "productividad_hora": 156},
    {"almacen": "NOA", "sector": "JC", "productividad_hora": 163},
    {"almacen": "REFRIGERADOS", "sector": "MO", "productividad_hora": 0},
    {"almacen": "NOA", "sector": "MU", "productividad_hora": 55},
    {"almacen": "NOA", "sector": "NS", "productividad_hora": 160},
    {"almacen": "NOA", "sector": "NT", "productividad_hora": 90},
    {"almacen": "NOA", "sector": "N1", "productividad_hora": 191},
    {"almacen": "SECOS", "sector": "OF", "productividad_hora": 107},
    {"almacen": "REFRIGERADOS", "sector": "PA", "productividad_hora": 183},
    {"almacen": "SECOS", "sector": "PE", "productividad_hora": 154},
    {"almacen": "NOA", "sector": "PI", "productividad_hora": 134},
    {"almacen": "SECOS", "sector": "P1", "productividad_hora": 152},
    {"almacen": "SECOS", "sector": "P3", "productividad_hora": 193},
    {"almacen": "NOA", "sector": "TV", "productividad_hora": 13},
    {"almacen": "NOA", "sector": "VA", "productividad_hora": 81},
    {"almacen": "REFRIGERADOS", "sector": "VE", "productividad_hora": 151},
    {"almacen": "NOA", "sector": "VT", "productividad_hora": 112},
]


class AnalizarFechaRequest(BaseModel):
    fecha: str
    nombre: str | None = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _norm(value: Any) -> str:
    return _clean(value).upper()


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _row_dict(row: Any | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


async def _fetch_rows(db, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    async with db.execute(sql, args) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def _fetch_one(db, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    async with db.execute(sql, args) as cur:
        return _row_dict(await cur.fetchone())


async def _require_plantel_optimo_access(request: Request) -> dict[str, Any]:
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    if auth.get("role") == "admin":
        return auth
    async with auth_db() as db:
        try:
            row = await _fetch_one(
                db,
                """
                SELECT enabled
                FROM auth_user_app_access
                WHERE username = ? AND module = 'plantel_optimo'
                """,
                (auth["username"],),
            )
        except sqlite3.OperationalError:
            row = None
    if not row or not row.get("enabled"):
        raise HTTPException(status_code=403, detail="Sin acceso al modulo Plantel Optimo.")
    return auth


def _parse_fecha_operativa(value: str) -> date:
    text = _clean(value)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Fecha invalida. Usa formato YYYY-MM-DD.") from exc


def _fecha_operativa_window(value: str) -> dict[str, str]:
    day = _parse_fecha_operativa(value)
    start = datetime.combine(day, time(6, 0))
    end = start + timedelta(days=1)
    return {
        "fecha": day.isoformat(),
        "fecha_desde": start.strftime("%Y-%m-%d %H:%M:%S"),
        "fecha_hasta": end.strftime("%Y-%m-%d %H:%M:%S"),
        "label": f"{start:%Y-%m-%d %H:%M} / {end:%Y-%m-%d %H:%M}",
    }


def _hour_value(value: Any) -> int:
    try:
        hour = int(float(value))
    except (TypeError, ValueError):
        hour = 0
    return max(0, min(hour, 23))


def _bucket_label_from_hour(hour: int) -> str:
    start = (hour // 2) * 2
    end = (start + 2) % 24
    return f"{start}-{end}"


def _bucket_sort_value(label: str) -> int:
    try:
        start = int(str(label).split("-", 1)[0])
    except (TypeError, ValueError):
        return 99
    return start if start >= 6 else start + 24


def _productividad_map() -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (_norm(row["almacen"]), _norm(row["sector"])): {
            "almacen": _norm(row["almacen"]),
            "sector": _norm(row["sector"]),
            "productividad_hora": float(row["productividad_hora"] or 0),
        }
        for row in PRODUCTIVIDAD_SECTOR_ESTANDAR
    }


def _query_oracle_demanda(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return _query_productive_db_sql(
        QUERY_PLANTEL_OPTIMO_DEMANDA,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


def _normalize_oracle_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        almacen = _norm(row.get("ALMACEN") or row.get("almacen"))
        sector = _norm(row.get("SECTOR") or row.get("sector"))
        hour = _hour_value(row.get("HORA") or row.get("hora"))
        bultos = _safe_float(row.get("BULTOS_PALLET") or row.get("bultos_pallet"))
        pallets = _safe_float(row.get("CANTIDAD_PALLET") or row.get("cantidad_pallet"))
        if not almacen or not sector:
            continue
        normalized.append(
            {
                "almacen": almacen,
                "sector": sector,
                "tipo": _norm(row.get("TIPO") or row.get("tipo") or "PICKING"),
                "hora": hour,
                "rango": _bucket_label_from_hour(hour),
                "cantidad_pallet": pallets,
                "bultos_pallet": bultos,
            }
        )
    return normalized


def _calcular_sugerencia(demanda_rows: list[dict[str, Any]]) -> dict[str, Any]:
    prod = _productividad_map()
    bucket_sector: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"bultos_pallet": 0.0, "cantidad_pallet": 0.0}
    )
    missing: set[str] = set()
    zero_capacity: set[str] = set()

    for row in demanda_rows:
        almacen = _norm(row.get("almacen"))
        sector = _norm(row.get("sector"))
        rango = _clean(row.get("rango"))
        key = (almacen, sector)
        if key not in prod:
            missing.add(f"{almacen}/{sector}")
            continue
        if prod[key]["productividad_hora"] <= 0:
            zero_capacity.add(f"{almacen}/{sector}")
            continue
        item = bucket_sector[(rango, almacen, sector)]
        item["bultos_pallet"] += _safe_float(row.get("bultos_pallet"))
        item["cantidad_pallet"] += _safe_float(row.get("cantidad_pallet"))

    sectores_result = []
    bucket_almacen: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"bultos_pallet": 0.0, "cantidad_pallet": 0.0, "operarios": 0}
    )
    for (rango, almacen, sector), values in bucket_sector.items():
        productividad_hora = prod[(almacen, sector)]["productividad_hora"]
        capacidad_rango = productividad_hora * 2
        bultos = values["bultos_pallet"]
        operarios = math.ceil(bultos / capacidad_rango) if bultos > 0 else 0
        bucket_almacen[(rango, almacen)]["bultos_pallet"] += bultos
        bucket_almacen[(rango, almacen)]["cantidad_pallet"] += values["cantidad_pallet"]
        bucket_almacen[(rango, almacen)]["operarios"] += operarios
        sectores_result.append(
            {
                "rango": rango,
                "almacen": almacen,
                "sector": sector,
                "cantidad_pallet": round(values["cantidad_pallet"], 2),
                "bultos_pallet": round(bultos, 2),
                "productividad_hora": round(productividad_hora, 2),
                "capacidad_operario_rango": round(capacidad_rango, 2),
                "operarios_sugeridos": operarios,
            }
        )

    almacenes_rango = [
        {
            "rango": rango,
            "almacen": almacen,
            "cantidad_pallet": round(values["cantidad_pallet"], 2),
            "bultos_pallet": round(values["bultos_pallet"], 2),
            "operarios_sugeridos": int(values["operarios"]),
        }
        for (rango, almacen), values in bucket_almacen.items()
    ]

    peak_by_almacen: dict[str, dict[str, Any]] = {}
    for item in almacenes_rango:
        current = peak_by_almacen.get(item["almacen"])
        if not current or item["operarios_sugeridos"] > current["operarios_sugeridos"]:
            peak_by_almacen[item["almacen"]] = {
                "almacen": item["almacen"],
                "rango_pico": item["rango"],
                "bultos_pico": item["bultos_pallet"],
                "pallets_pico": item["cantidad_pallet"],
                "operarios_sugeridos": item["operarios_sugeridos"],
            }

    sectores_result.sort(key=lambda item: (_bucket_sort_value(item["rango"]), item["almacen"], item["sector"]))
    almacenes_rango.sort(key=lambda item: (_bucket_sort_value(item["rango"]), item["almacen"]))
    almacenes = sorted(peak_by_almacen.values(), key=lambda item: item["almacen"])
    return {
        "summary": {
            "generated_at": _now(),
            "rangos": len({row["rango"] for row in demanda_rows}),
            "sectores_demanda": len({f"{row['almacen']}/{row['sector']}" for row in demanda_rows}),
            "sectores_sin_estandar": sorted(missing),
            "sectores_productividad_cero": sorted(zero_capacity),
            "bultos_total": round(sum(row["bultos_pallet"] for row in demanda_rows), 2),
            "pallets_total": round(sum(row["cantidad_pallet"] for row in demanda_rows), 2),
            "dotacion_pico_total": sum(item["operarios_sugeridos"] for item in almacenes),
        },
        "almacenes": almacenes,
        "almacenes_por_rango": almacenes_rango,
        "sectores_por_rango": sectores_result,
        "raw_rows": demanda_rows,
    }


@router.get("/config")
async def config(request: Request):
    await _require_plantel_optimo_access(request)
    today = date.today().isoformat()
    return {
        "fecha_default": today,
        "window_default": _fecha_operativa_window(today),
        "productividades": PRODUCTIVIDAD_SECTOR_ESTANDAR,
    }


@router.post("/analizar")
async def analizar(req: AnalizarFechaRequest, request: Request):
    auth = await _require_plantel_optimo_access(request)
    window = _fecha_operativa_window(req.fecha)
    try:
        raw_rows = await asyncio.to_thread(
            _query_oracle_demanda,
            window["fecha_desde"],
            window["fecha_hasta"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo consultar Oracle: {exc}") from exc
    demanda_rows = _normalize_oracle_rows(raw_rows)
    result = _calcular_sugerencia(demanda_rows)
    result["summary"]["fecha"] = window["fecha"]
    result["summary"]["fecha_desde"] = window["fecha_desde"]
    result["summary"]["fecha_hasta"] = window["fecha_hasta"]
    result["summary"]["source_name"] = "oracle"

    async with plantel_optimo_db() as db:
        await db.execute("DELETE FROM demanda_cache")
        await db.execute("DELETE FROM escenarios")
        await db.execute("DELETE FROM sqlite_sequence WHERE name IN ('demanda_cache', 'escenarios')")
        await db.execute(
            """
            INSERT INTO demanda_cache (source_name, synced_by, synced_at, rows_json, rows_count)
            VALUES ('oracle', ?, ?, ?, ?)
            """,
            (auth["username"], _now(), _safe_json(demanda_rows), len(demanda_rows)),
        )
        cursor = await db.execute(
            """
            INSERT INTO escenarios
                (nombre, source_name, created_by, created_at, demanda_json, productividad_json, result_json)
            VALUES (?, 'oracle', ?, ?, ?, ?, ?)
            """,
            (
                req.nombre or f"Plantel Optimo {window['fecha']}",
                auth["username"],
                _now(),
                _safe_json(demanda_rows),
                _safe_json(PRODUCTIVIDAD_SECTOR_ESTANDAR),
                _safe_json(result),
            ),
        )
        await db.commit()
        result["summary"]["scenario_id"] = cursor.lastrowid
    return result


@router.get("/escenarios")
async def escenarios(request: Request, limit: int = 10):
    await _require_plantel_optimo_access(request)
    limit = max(1, min(int(limit), 50))
    async with plantel_optimo_db() as db:
        rows = await _fetch_rows(
            db,
            """
            SELECT scenario_id, nombre, source_name, created_by, created_at, result_json
            FROM escenarios
            ORDER BY scenario_id DESC
            LIMIT ?
            """,
            (limit,),
        )
    for row in rows:
        try:
            row["summary"] = json.loads(row.pop("result_json") or "{}").get("summary", {})
        except json.JSONDecodeError:
            row["summary"] = {}
    return {"escenarios": rows}
