"""Exportación Parquet del resumen de Picking de las últimas 24 horas."""
from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from routers.productividad_analisis import _query_productive_db_sql


router = APIRouter(prefix="/api/picking", tags=["picking"])
logger = logging.getLogger("vigia.picking_parquet")

QUERY_PICKING_SUMMARY_24H = """
SELECT
    A.CDESCRIP AS OPERACION,
    COUNT(DISTINCT A.CNUPALET) AS PALET,
    SUM(A.QCANTIDA) AS BULTOS,
    A.CZONAORI AS ZONA
FROM F132HIST A
WHERE A.FCREAREG >= SYSDATE - INTERVAL '24' HOUR
  AND A.FCREAREG < SYSDATE
  AND A.CDESCRIP IN (
      'Picking',
      'S. P. COMPLETOS',
      'SURTIDO P.COMPLETOS'
  )
  AND A.QCANTIDA > 0
GROUP BY A.CDESCRIP, A.CZONAORI
ORDER BY OPERACION, ZONA
"""


def _number(value: Any) -> int | float:
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _parquet_bytes(rows: list[dict[str, Any]]) -> io.BytesIO:
    table = pa.table({
        "OPERACION": [str(row.get("OPERACION") or "") for row in rows],
        "PALET": [_number(row.get("PALET")) for row in rows],
        "BULTOS": [_number(row.get("BULTOS")) for row in rows],
        "ZONA": [str(row.get("ZONA") or "") for row in rows],
    })
    output = io.BytesIO()
    pq.write_table(table, output, compression="snappy")
    output.seek(0)
    return output


@router.get("/productividad.parquet", response_class=StreamingResponse)
async def export_picking_summary_24h() -> StreamingResponse:
    """Devuelve el resumen agrupado de Picking de las últimas 24 horas."""
    try:
        rows = await asyncio.to_thread(
            _query_productive_db_sql,
            QUERY_PICKING_SUMMARY_24H,
            fecha_desde="",
            fecha_hasta="",
        )
        output = _parquet_bytes(rows)
    except Exception as exc:
        logger.exception("No se pudo generar el resumen Parquet de Picking")
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar Oracle o generar el archivo Parquet.",
        ) from exc

    return StreamingResponse(
        output,
        media_type="application/vnd.apache.parquet",
        headers={
            "Content-Disposition": 'attachment; filename="produccion_resumen.parquet"',
        },
    )
