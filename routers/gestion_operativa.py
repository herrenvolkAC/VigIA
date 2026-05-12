"""
VigIA · Gestion operativa.

Endpoints para herramientas de apoyo directo a la operacion.
"""
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from routers.productividad_analisis import (
    _build_picking_idle_analysis,
    _turn_label,
    _turn_range_for_date,
    query_productive_db_picking_tiempos_muertos,
)

logger = logging.getLogger("vigia.gestion_operativa")
router = APIRouter(prefix="/api/gestion-operativa", tags=["gestion-operativa"])


@router.get("/cambios-almacen")
async def get_cambios_almacen(
    fecha: str = Query(..., description="YYYY-MM-DD"),
    turno: str = Query(..., description="Mañana, Tarde o Noche"),
) -> dict[str, Any]:
    turno_key, fecha_desde, fecha_hasta = _turn_range_for_date(fecha, turno)
    logger.info(
        "[gestion-operativa:cambios-almacen] Consultando Oracle turno=%s rango=%s..%s",
        _turn_label(turno_key),
        fecha_desde,
        fecha_hasta,
    )
    try:
        detail_rows = await asyncio.to_thread(
            query_productive_db_picking_tiempos_muertos,
            fecha_desde,
            fecha_hasta,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("Error consultando cambios de almacen")
        raise HTTPException(status_code=500, detail=f"No se pudo consultar Oracle: {exc}")

    base = _build_picking_idle_analysis(
        detail_rows,
        [],
        fecha,
        turno_key,
        fecha_desde,
        fecha_hasta,
    )
    crossings = base.get("almacen_crossings", {})
    return {
        "fecha": fecha,
        "turno": _turn_label(turno_key),
        "turno_key": turno_key,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "summary": {
            "movimientos_total": base.get("summary", {}).get("movimientos_total", 0),
            "pickings_total": base.get("summary", {}).get("pickings_total", 0),
            **crossings.get("summary", {}),
        },
        "transferencias": crossings.get("transferencias", []),
        "cruces": crossings.get("cruces", []),
        "source_name": "oracle_productiva",
    }
