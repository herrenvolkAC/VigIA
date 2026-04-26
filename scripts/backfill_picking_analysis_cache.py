"""
Backfill del cache local de picking para desarrollo.

Ejemplos:
    python scripts/backfill_picking_analysis_cache.py
    python scripts/backfill_picking_analysis_cache.py --days 3
    python scripts/backfill_picking_analysis_cache.py --from-date 2026-04-23 --to-date 2026-04-25
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.schema import init_db  # noqa: E402
from routers.productividad_analisis import (  # noqa: E402
    _turn_label,
    _turn_range_for_date,
    _store_cached_picking_analysis_rows,
    query_productive_db_picking_analysis_detail,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill del cache local de picking")
    parser.add_argument("--days", type=int, default=3, help="Cantidad de dias hacia atras incluyendo hoy")
    parser.add_argument("--from-date", dest="from_date", help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--to-date", dest="to_date", help="Fecha fin YYYY-MM-DD")
    return parser.parse_args()


def _date_list(args: argparse.Namespace) -> list[str]:
    if args.from_date:
        start = datetime.strptime(args.from_date, "%Y-%m-%d").date()
    else:
        start = (datetime.now().date() - timedelta(days=max(int(args.days) - 1, 0)))
    if args.to_date:
        end = datetime.strptime(args.to_date, "%Y-%m-%d").date()
    else:
        end = datetime.now().date()
    if end < start:
        raise ValueError("to-date debe ser mayor o igual a from-date")
    dates = []
    cursor = start
    while cursor <= end:
        dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return dates


async def main() -> int:
    load_dotenv(dotenv_path=ROOT_DIR / ".env", override=True)
    args = _parse_args()
    await init_db()

    turns = ["Mañana", "Tarde", "Noche"]
    total_rows = 0
    dates = _date_list(args)
    print(f"[INFO] Backfill picking cache para {len(dates)} dias: {dates[0]} .. {dates[-1]}")

    for fecha in dates:
        for turno in turns:
            turno_key, fecha_desde, fecha_hasta = _turn_range_for_date(fecha, turno)
            print(f"[RUN] {fecha} {turno} -> {fecha_desde} .. {fecha_hasta}")
            rows = await asyncio.to_thread(
                query_productive_db_picking_analysis_detail,
                fecha_desde,
                fecha_hasta,
            )
            inserted = await _store_cached_picking_analysis_rows(
                fecha=fecha,
                turno_key=turno_key,
                turno_label=_turn_label(turno_key),
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                rows=rows,
                source_name="oracle_productiva",
            )
            total_rows += inserted
            print(f"[OK] {fecha} {turno}: {inserted} filas cacheadas")

    print(f"[DONE] Total filas cacheadas: {total_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
