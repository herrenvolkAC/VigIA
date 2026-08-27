"""Carga mensual, reanudable y controlada de indicadores desde Oracle a SQLite."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from calendar import monthrange
from datetime import date
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.analisis_productividad import (
    ANALISIS_PRODUCTIVIDAD_DB_PATH,
    init_analisis_productividad_db,
    now_iso,
    tendencia_row_payload,
)
from routers.analisis_premio_productividad import tendencia_operativa


def month_windows(start: date, end: date):
    current = date(start.year, start.month, 1)
    while current <= end:
        month_end = date(current.year, current.month, monthrange(current.year, current.month)[1])
        yield current, min(month_end, end)
        current = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)


async def load_scope(operation: str, group: int, start: date, end: date) -> None:
    async with aiosqlite.connect(ANALISIS_PRODUCTIVIDAD_DB_PATH) as db:
        errors = 0
        for month_start, month_end in month_windows(start, end):
            month_key = int(month_start.strftime("%Y%m"))
            batch_id = f"{month_key}-{operation}-{group}-{uuid.uuid4().hex[:8]}"
            await db.execute(
                "INSERT INTO ap_carga_lote(batch_id,fecha_desde,fecha_hasta,operacion,grupo_productivo,estado,creado_en) VALUES(?,?,?,?,?,?,?)",
                (batch_id, month_start.isoformat(), month_end.isoformat(), operation, group, "RUNNING", now_iso()),
            )
            await db.commit()
            try:
                result = await tendencia_operativa(month_start.isoformat(), month_end.isoformat(), operation, group)
                rows = result.get("rows", [])
                await db.execute("DELETE FROM ap_tendencia_mensual WHERE operacion=? AND grupo_productivo=? AND mes=?", (operation, group, month_key))
                for row in rows:
                    await db.execute(
                        "INSERT INTO ap_tendencia_mensual(batch_id,operacion,grupo_productivo,mes,payload_json,cargado_en) VALUES(?,?,?,?,?,?)",
                        (batch_id, operation, group, int(row["mes"]), tendencia_row_payload(row), now_iso()),
                    )
                await db.execute("UPDATE ap_carga_lote SET estado=?,filas=?,finalizado_en=? WHERE batch_id=?", ("DONE", len(rows), now_iso(), batch_id))
                await db.commit()
                print(f"OK {operation} grupo={group} mes={month_key} filas={len(rows)}")
            except Exception as exc:
                await db.execute("UPDATE ap_carga_lote SET estado=?,error=?,finalizado_en=? WHERE batch_id=?", ("ERROR", str(exc)[:2000], now_iso(), batch_id))
                await db.commit()
                print(f"ERROR {operation} grupo={group} mes={month_key}: {exc}")
                errors += 1
        print(f"RESUMEN {operation} grupo={group}: errores={errors}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desde", default="2024-01-01")
    parser.add_argument("--hasta", default=date.today().isoformat())
    parser.add_argument("--operaciones", nargs="+", default=["CARGA", "CARRETEO"])
    parser.add_argument("--grupos", nargs="+", type=int, default=[0])
    args = parser.parse_args()
    load_dotenv(".env", override=True)
    os.environ["ANALISIS_PRODUCTIVIDAD_OMITIR_LOCAL"] = "1"
    start, end = date.fromisoformat(args.desde), date.fromisoformat(args.hasta)
    await init_analisis_productividad_db()
    print(f"Base local: {ANALISIS_PRODUCTIVIDAD_DB_PATH}")
    for operation in args.operaciones:
        for group in args.grupos:
            await load_scope(operation.upper(), group, start, end)


if __name__ == "__main__":
    asyncio.run(main())
