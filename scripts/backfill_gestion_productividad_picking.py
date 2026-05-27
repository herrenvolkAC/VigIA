"""
Backfill de Gestion Operativa - Productividad Picking.

Carga en vigia.db los eventos y segmentos de productividad por turnos.

Ejemplos:
    python scripts/backfill_gestion_productividad_picking.py
    python scripts/backfill_gestion_productividad_picking.py --from-date 2026-01-01 --to-date 2026-05-22
    python scripts/backfill_gestion_productividad_picking.py --coverage-mode exact
"""
import argparse
import asyncio
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.schema import DB_PATH, init_db  # noqa: E402
from routers.gestion_operativa import (  # noqa: E402
    _build_segments,
    _normalize_productividad_rows,
    _store_productividad_run,
)
from routers.productividad_analisis import (  # noqa: E402
    _turn_label,
    _turn_range_for_date,
    query_productive_db_gestion_productividad_picking,
)


TURNOS = ("manana", "tarde", "noche")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill gestion productividad picking")
    parser.add_argument("--from-date", default="2026-01-01", help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--to-date", default=date.today().isoformat(), help="Fecha fin YYYY-MM-DD")
    parser.add_argument(
        "--coverage-mode",
        choices=("covered", "exact"),
        default="covered",
        help="covered salta turnos ya contenidos en un rango local; exact solo salta rangos exactos",
    )
    parser.add_argument("--sleep", type=float, default=1.0, help="Pausa entre consultas Oracle, en segundos")
    parser.add_argument("--max-turns", type=int, default=0, help="Limite de turnos a cargar en esta ejecucion")
    parser.add_argument("--stop-on-error", action="store_true", help="Detiene el proceso ante el primer error")
    return parser.parse_args()


def _date_range(start: date, end: date) -> list[str]:
    if end < start:
        raise ValueError("--to-date debe ser mayor o igual a --from-date")
    out = []
    cursor = start
    while cursor <= end:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


async def _range_is_cached(fecha_desde: str, fecha_hasta: str, coverage_mode: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        if coverage_mode == "exact":
            query = """
                SELECT 1
                FROM gestion_productividad_picking_runs
                WHERE fecha_desde = ?
                  AND fecha_hasta = ?
                LIMIT 1
            """
            params = (fecha_desde, fecha_hasta)
        else:
            query = """
                SELECT 1
                FROM gestion_productividad_picking_runs
                WHERE fecha_desde <= ?
                  AND fecha_hasta >= ?
                LIMIT 1
            """
            params = (fecha_desde, fecha_hasta)
        async with db.execute(query, params) as cur:
            return await cur.fetchone() is not None


async def _load_turn(fecha: str, turno: str, coverage_mode: str) -> dict[str, object]:
    turno_key, fecha_desde, fecha_hasta = _turn_range_for_date(fecha, turno)
    label = _turn_label(turno_key)
    if await _range_is_cached(fecha_desde, fecha_hasta, coverage_mode):
        return {
            "status": "skip",
            "fecha": fecha,
            "turno": label,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "rows": 0,
            "segments": 0,
        }

    started = time.perf_counter()
    raw_rows = await asyncio.to_thread(
        query_productive_db_gestion_productividad_picking,
        fecha_desde,
        fecha_hasta,
    )
    events = _normalize_productividad_rows(raw_rows)
    segments = _build_segments(events)
    run_id = await _store_productividad_run(fecha_desde, fecha_hasta, events, segments, len(raw_rows))
    return {
        "status": "ok",
        "run_id": run_id,
        "fecha": fecha,
        "turno": label,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "rows": len(raw_rows),
        "events": len(events),
        "segments": len(segments),
        "seconds": round(time.perf_counter() - started, 2),
    }


async def main() -> int:
    load_dotenv(dotenv_path=ROOT_DIR / ".env", override=True)
    os.environ.setdefault("PRODUCTIVE_DB_LOCAL_ONLY", "0")
    args = _parse_args()
    await init_db()

    start = datetime.strptime(args.from_date, "%Y-%m-%d").date()
    end = datetime.strptime(args.to_date, "%Y-%m-%d").date()
    dates = _date_range(start, end)
    planned = len(dates) * len(TURNOS)
    done = 0
    loaded = 0
    skipped = 0
    errors = 0

    print(
        f"[START] Backfill gestion productividad picking {dates[0]}..{dates[-1]} "
        f"turnos={planned} coverage={args.coverage_mode}",
        flush=True,
    )

    for fecha in dates:
        for turno in TURNOS:
            if args.max_turns and done >= args.max_turns:
                print("[STOP] Limite --max-turns alcanzado", flush=True)
                print(f"[DONE] loaded={loaded} skipped={skipped} errors={errors}", flush=True)
                return 0 if errors == 0 else 1
            done += 1
            try:
                result = await _load_turn(fecha, turno, args.coverage_mode)
                if result["status"] == "skip":
                    skipped += 1
                    print(
                        f"[SKIP] {fecha} {result['turno']} cubierto localmente "
                        f"{result['fecha_desde']}..{result['fecha_hasta']}",
                        flush=True,
                    )
                else:
                    loaded += 1
                    print(
                        f"[OK] {fecha} {result['turno']} run={result['run_id']} "
                        f"rows={result['rows']} events={result['events']} "
                        f"segments={result['segments']} seconds={result['seconds']}",
                        flush=True,
                    )
                    if args.sleep > 0:
                        await asyncio.sleep(args.sleep)
            except Exception as exc:
                errors += 1
                print(f"[ERROR] {fecha} {turno}: {exc}", flush=True)
                if args.stop_on_error:
                    print(f"[DONE] loaded={loaded} skipped={skipped} errors={errors}", flush=True)
                    return 1
                await asyncio.sleep(max(args.sleep, 2))

    print(f"[DONE] loaded={loaded} skipped={skipped} errors={errors}", flush=True)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
