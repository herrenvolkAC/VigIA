"""
Backfill historico de productividad picking sobre vigia.db.

Uso recomendado:
    python scripts/backfill_productividad_history.py --days 30

Opcionalmente se puede generar IA solo para las ultimas N ventanas:
    python scripts/backfill_productividad_history.py --days 30 --with-ia --ia-last 3
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

from db.schema import init_db
from routers.productividad_analisis import (
    build_or_get_ai_analysis,
    build_or_get_internal_analysis,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill historico de productividad picking")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Cantidad de ventanas diarias a cargar hacia atras. Default: 30",
    )
    parser.add_argument(
        "--from-date",
        dest="from_date",
        help="Fecha inicio base en formato YYYY-MM-DD. Si se informa, pisa --days.",
    )
    parser.add_argument(
        "--to-date",
        dest="to_date",
        help="Fecha fin base en formato YYYY-MM-DD. Default: hoy.",
    )
    parser.add_argument(
        "--cutoff-hour",
        type=int,
        default=14,
        help="Hora de corte diaria para armar las ventanas. Default: 14",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Reconsulta Oracle aunque ya exista cache local.",
    )
    parser.add_argument(
        "--with-ia",
        action="store_true",
        help="Genera tambien analisis IA para algunas ventanas.",
    )
    parser.add_argument(
        "--ia-provider",
        default=None,
        help="Proveedor IA a usar. Default: el configurado en .env",
    )
    parser.add_argument(
        "--ia-last",
        type=int,
        default=1,
        help="Cantidad de ventanas mas recientes a las que se les genera IA cuando se usa --with-ia. Default: 1",
    )
    return parser.parse_args()


def _window_bounds(args: argparse.Namespace) -> list[tuple[str, str]]:
    cutoff = int(args.cutoff_hour)
    today = datetime.now().replace(hour=cutoff, minute=0, second=0, microsecond=0)

    if args.to_date:
        end_base = datetime.strptime(args.to_date, "%Y-%m-%d").replace(
            hour=cutoff, minute=0, second=0, microsecond=0
        )
    else:
        end_base = today

    if args.from_date:
        start_base = datetime.strptime(args.from_date, "%Y-%m-%d").replace(
            hour=cutoff, minute=0, second=0, microsecond=0
        )
    else:
        start_base = end_base - timedelta(days=int(args.days))

    windows = []
    cursor = start_base
    while cursor < end_base:
        next_cursor = cursor + timedelta(days=1)
        windows.append((
            cursor.strftime("%Y-%m-%d %H:%M:%S"),
            next_cursor.strftime("%Y-%m-%d %H:%M:%S"),
        ))
        cursor = next_cursor
    return windows


async def _run() -> None:
    args = _parse_args()
    load_dotenv(override=True)
    await init_db()

    windows = _window_bounds(args)
    if not windows:
        print("[BACKFILL] No hay ventanas a procesar.")
        return

    print(f"[BACKFILL] Ventanas a procesar: {len(windows)}")
    ia_start_index = max(len(windows) - max(args.ia_last, 0), 0)

    for index, (fecha_desde, fecha_hasta) in enumerate(windows, start=1):
        print(f"[{index}/{len(windows)}] Interno {fecha_desde} -> {fecha_hasta}")
        try:
            resumen = await build_or_get_internal_analysis(
                fecha_desde,
                fecha_hasta,
                force_refresh=args.force_refresh,
            )
            cache = resumen.get("cache", {})
            print(
                f"    OK interno | cache_hit={cache.get('interno_cache_hit')} | "
                f"ops={resumen.get('resumen', {}).get('operarios_total', 0)} | "
                f"mov={resumen.get('resumen', {}).get('movimientos_total', 0)}"
            )
        except Exception as exc:
            print(f"    ERROR interno: {exc}")
            continue

        if args.with_ia and index - 1 >= ia_start_index:
            print(f"    IA {fecha_desde} -> {fecha_hasta}")
            try:
                ia = await build_or_get_ai_analysis(
                    resumen,
                    provider=(args.ia_provider or ""),
                    force_refresh=args.force_refresh,
                )
                print(
                    f"    OK IA | cache_hit={ia.get('cache', {}).get('ia_cache_hit')} | "
                    f"provider={ia.get('provider')} | model={ia.get('model_used')}"
                )
            except Exception as exc:
                print(f"    ERROR IA: {exc}")


if __name__ == "__main__":
    asyncio.run(_run())
