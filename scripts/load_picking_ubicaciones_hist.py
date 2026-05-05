"""
Carga el mapa empirico de ubicaciones usadas en Picking desde Oracle hacia vigia.db.

Uso:
  python scripts/load_picking_ubicaciones_hist.py

La tabla resultante ordena la ubicacion completa por codigo Oracle. Es una base
teorica inicial para medir saltos; no representa metros fisicos.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aiosqlite
from dotenv import load_dotenv

from db.schema import DB_PATH, init_db
from routers.productividad_analisis import query_productive_db_picking_ubicaciones_hist

load_dotenv(ROOT / ".env", override=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Carga ubicaciones historicas de Picking en vigia.db")
    parser.add_argument("--source", default="oracle_productiva:F132HIST_HIST", help="Nombre de fuente a guardar")
    return parser.parse_args()


async def _store(rows: list[dict], source_name: str) -> int:
    payload = []
    for idx, row in enumerate(rows, start=1):
        codigo = str(row.get("UBICACION_CODIGO") or row.get("ubicacion_codigo") or "").strip()
        if not codigo:
            continue
        payload.append(
            (
                codigo,
                idx,
                "",
                "",
                0,
                source_name,
            )
        )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM picking_ubicaciones_hist")
        await db.executemany(
            """
            INSERT INTO picking_ubicaciones_hist (
                ubicacion_codigo, orden_teorico, first_seen, last_seen, pick_count, source_name,
                snapshot_loaded_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            payload,
        )
        await db.commit()
    return len(payload)


async def main() -> None:
    args = _parse_args()
    await init_db()
    rows = await asyncio.to_thread(
        query_productive_db_picking_ubicaciones_hist,
        "1900-01-01 00:00:00",
        "2999-12-31 23:59:59",
    )
    stored = await _store(rows, args.source)
    print(f"Ubicaciones picking cargadas: {stored}")


if __name__ == "__main__":
    asyncio.run(main())
