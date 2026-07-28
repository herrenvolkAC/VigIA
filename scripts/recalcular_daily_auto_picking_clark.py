from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from routers.gestion_operativa import (
    _daily_window_for_fecha_carga,
    run_daily_auto_clark_precache,
    run_daily_auto_picking_precache,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recalcula solo los automaticos de Picking y Clark para una fecha de carga Daily."
    )
    parser.add_argument(
        "--fecha-carga",
        required=True,
        help="Fecha de carga Daily en formato YYYY-MM-DD. Ejemplo: 2026-07-28",
    )
    parser.add_argument(
        "--usuario",
        default="recalculo_produccion",
        help="Usuario/etiqueta para auditar el run.",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    fecha = datetime.strptime(args.fecha_carga[:10], "%Y-%m-%d")
    daily = _daily_window_for_fecha_carga(fecha)
    print(f"Daily: {daily['daily_key']} | {daily['daily_label']} | fecha_carga={daily['fecha_carga']}")

    picking = await run_daily_auto_picking_precache(
        force=True,
        trigger="manual_fix_refri_totales",
        usuario=args.usuario,
        daily_override=daily,
    )
    print("PICKING:", picking)

    clark = await run_daily_auto_clark_precache(
        force=True,
        trigger="manual_fix_refri_totales",
        usuario=args.usuario,
        daily_override=daily,
    )
    print("CLARK:", clark)

    if picking.get("status") != "success" or clark.get("status") != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(_main())
