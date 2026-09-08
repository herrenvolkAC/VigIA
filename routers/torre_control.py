"""Torre de Control OpEx: primera vista de Picking."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from db.torre_control import division_label, get_snapshot, get_ubicaciones_division, save_snapshot, save_ubicaciones_division
from routers.productividad_analisis import _query_productive_db_sql


router = APIRouter(prefix="/api/opex/torre-control", tags=["torre-control"])
logger = logging.getLogger("vigia.torre_control")
REFRESH_MINUTES = 15
ORACLE_TIMEOUT_SECONDS = 60
_refresh_lock: asyncio.Lock | None = None


QUERY_PICKING_ACTIVITY = """
SELECT
    A.FCREAREG,
    A.CDESCRIP,
    A.CNPEDIDO,
    A.CNUPALET,
    A.QCANTIDA,
    A.CREFEREN,
    A.COPECREA,
    A.CUBIORIG,
    A.CZONAORI,
    SYSDATE AS ORACLE_NOW
FROM F132HIST A
WHERE A.FCREAREG > TO_DATE(:fecha_desde, 'YYYY-MM-DD HH24:MI:SS')
  AND A.FCREAREG < TO_DATE(:fecha_hasta, 'YYYY-MM-DD HH24:MI:SS')
  AND A.CDESCRIP IN (
      'Picking',
      'SURTIDO P.COMPLETOS',
      'S. P. COMPLETOS',
      'EXTRACCION DE REAPROS',
      'EXTRACCION TRASPASOS',
      'GUARADO PALETS ENTRADA'
  )
"""

QUERY_UBICACIONES_DIVISION = """
SELECT DISTINCT
    TRIM(CPASILLO) AS PASILLO,
    TRIM(CHUECOPA) AS HUECO,
    TRIM(CZONALMA) AS ZONA_ALMACEN,
    TRIM(CDIVISIO) AS DIVISION
FROM VW_UBICACIONES_DIVISION
WHERE CPASILLO IS NOT NULL
  AND CHUECOPA IS NOT NULL
  AND CZONALMA IS NOT NULL
  AND CDIVISIO IS NOT NULL
"""


def _lock() -> asyncio.Lock:
    global _refresh_lock
    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()
    return _refresh_lock


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Fecha/hora inválida.") from exc


def _fmt_datetime(value: datetime) -> str:
    return value.replace(second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _location_code(cubiorig: Any, zona_almacen: Any) -> str:
    cubiorig_text = _text(cubiorig)
    return "|".join((cubiorig_text[:3], cubiorig_text[3:6], _text(zona_almacen))).upper()


def _operation_label(value: Any) -> str:
    operation = _text(value).upper()
    if operation in {"SURTIDO P.COMPLETOS", "S. P. COMPLETOS"}:
        return "S. P. COMPLETOS"
    return operation or "SIN OPERACIÓN"


def _normalize_row(row: dict[str, Any], ubicaciones: dict[str, str]) -> dict[str, Any]:
    code = _location_code(row.get("CUBIORIG"), row.get("CZONAORI"))
    return {
        "fecha": _text(row.get("FCREAREG")),
        "descripcion": _text(row.get("CDESCRIP")),
        "operacion": _operation_label(row.get("CDESCRIP")),
        "pedido": _text(row.get("CNPEDIDO")),
        "pallet": _text(row.get("CNUPALET")),
        "bultos": _number(row.get("QCANTIDA")),
        "articulo": _text(row.get("CREFEREN")),
        "operario": _text(row.get("COPECREA")),
        "division": ubicaciones.get(code, "SIN DIVISIÓN"),
        "oracle_now": _text(row.get("ORACLE_NOW")),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_division: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_division[row["division"]].append(row)

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        operators: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            if item["operario"]:
                operators[item["operario"]].append(item)

        total_hours = 0.0
        for operator_rows in operators.values():
            dates = []
            for item in operator_rows:
                try:
                    dates.append(datetime.fromisoformat(item["fecha"].replace(" ", "T")))
                except ValueError:
                    continue
            if len(dates) >= 2:
                total_hours += max((max(dates) - min(dates)).total_seconds() / 3600, 1 / 60)

        bultos = sum(item["bultos"] for item in items)
        return {
            "bultos": round(bultos, 2),
            "operarios": len({item["operario"] for item in items if item["operario"]}),
            "productividad_promedio": round(bultos / total_hours, 2) if total_hours else None,
            "articulos": len({item["articulo"] for item in items if item["articulo"]}),
            "movimientos": len(items),
        }

    return {
        "total": summarize(rows),
        "divisiones": [
            {"division": division, **summarize(items)}
            for division, items in sorted(by_division.items())
        ],
    }


def _build_payload(raw_rows: list[dict[str, Any]], fecha_desde: str, fecha_hasta: str, ubicaciones: dict[str, str]) -> dict[str, Any]:
    rows = [_normalize_row(row, ubicaciones) for row in raw_rows]
    oracle_now = next((row["oracle_now"] for row in rows if row["oracle_now"]), "")
    return {
        "operaciones": sorted({row["operacion"] for row in rows}),
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "rows": rows,
        "summary": _summary(rows),
        "oracle_now": oracle_now,
    }


async def _load_or_refresh(fecha_desde: str, fecha_hasta: str) -> dict[str, Any]:
    start = _parse_datetime(fecha_desde).replace(second=0, microsecond=0)
    end = start + timedelta(hours=24)
    start_fmt, end_fmt = _fmt_datetime(start), _fmt_datetime(end)
    # Versionar la clave obliga a descartar snapshots generados antes de sumar operaciones.
    cache_key = f"picking-v3|{start_fmt}|{end_fmt}"
    cached = await get_snapshot(cache_key)
    now = datetime.now()
    if cached:
        try:
            age_minutes = (now - datetime.fromisoformat(cached["refreshed_at"])).total_seconds() / 60
        except (KeyError, TypeError, ValueError):
            age_minutes = REFRESH_MINUTES
        if age_minutes < REFRESH_MINUTES:
            payload = cached["payload"]
            payload["cache"] = {"source": "sqlite", "refreshed_at": cached["refreshed_at"], "stale": False}
            return payload

    async with _lock():
        cached = await get_snapshot(cache_key)
        if cached:
            try:
                age_minutes = (now - datetime.fromisoformat(cached["refreshed_at"])).total_seconds() / 60
            except (KeyError, TypeError, ValueError):
                age_minutes = REFRESH_MINUTES
            if age_minutes < REFRESH_MINUTES:
                payload = cached["payload"]
                payload["cache"] = {"source": "sqlite", "refreshed_at": cached["refreshed_at"], "stale": False}
                return payload

        try:
            ubicaciones = await get_ubicaciones_division()
            if not ubicaciones:
                mapping_rows = await asyncio.wait_for(
                    asyncio.to_thread(
                        _query_productive_db_sql,
                        QUERY_UBICACIONES_DIVISION,
                        fecha_desde="",
                        fecha_hasta="",
                    ),
                    timeout=ORACLE_TIMEOUT_SECONDS,
                )
                normalized_mapping = []
                for row in mapping_rows:
                    pasillo = _text(row.get("PASILLO")).upper()
                    hueco = _text(row.get("HUECO")).upper()
                    zona = _text(row.get("ZONA_ALMACEN")).upper()
                    division = division_label(row.get("DIVISION"))
                    normalized_mapping.append({
                        "codigo_ubicacion": "|".join((pasillo, hueco, zona)),
                        "pasillo": pasillo,
                        "hueco": hueco,
                        "zona_almacen": zona,
                        "division": division,
                    })
                await save_ubicaciones_division(
                    normalized_mapping,
                    datetime.now().isoformat(timespec="seconds"),
                )
                ubicaciones = await get_ubicaciones_division()

            raw_rows = await asyncio.wait_for(
                asyncio.to_thread(
                    _query_productive_db_sql,
                    QUERY_PICKING_ACTIVITY,
                    fecha_desde=start_fmt,
                    fecha_hasta=end_fmt,
                ),
                timeout=ORACLE_TIMEOUT_SECONDS,
            )
            payload = _build_payload(raw_rows, start_fmt, end_fmt, ubicaciones)
            refreshed_at = datetime.now().isoformat(timespec="seconds")
            payload["cache"] = {"source": "oracle", "refreshed_at": refreshed_at, "stale": False}
            await save_snapshot(
                cache_key=cache_key,
                fecha_desde=start_fmt,
                fecha_hasta=end_fmt,
                refreshed_at=refreshed_at,
                oracle_now=payload.get("oracle_now"),
                row_count=len(raw_rows),
                payload=payload,
            )
            return payload
        except Exception as exc:
            if cached:
                payload = cached["payload"]
                payload["cache"] = {
                    "source": "sqlite",
                    "refreshed_at": cached.get("refreshed_at"),
                    "stale": True,
                    "warning": "No se pudo actualizar Oracle; se muestra el último snapshot disponible.",
                }
                return payload
            logger.exception("No se pudo actualizar la Torre de Control de Picking")
            raise HTTPException(status_code=502, detail="No se pudo consultar Oracle para Picking.") from exc


@router.get("/picking")
async def torre_control_picking(
    fecha_desde: str = Query(..., description="Fecha/hora inicial en formato YYYY-MM-DDTHH:MM"),
) -> dict[str, Any]:
    start = _parse_datetime(fecha_desde)
    return await _load_or_refresh(_fmt_datetime(start), _fmt_datetime(start + timedelta(hours=24)))
