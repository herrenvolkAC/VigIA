"""
Backfill batch del historico de plantel operativo hacia vigia.db.

Uso recomendado:
    python scripts/backfill_plantel_history.py --days 30

Opcional:
    python scripts/backfill_plantel_history.py --from-date 2026-04-01 --to-date 2026-04-23
    python scripts/backfill_plantel_history.py --days 30 --batch-days 1 --force-refresh
"""
import argparse
import asyncio
import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db.schema import init_db, DB_PATH  # noqa: E402
from routers.plantel_operativo import _infer_turno_key_from_dt  # noqa: E402
from routers.productividad_analisis import query_productive_db_plantel  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill historico de plantel operativo")
    parser.add_argument("--days", type=int, default=30, help="Dias hacia atras. Default: 30")
    parser.add_argument("--from-date", dest="from_date", help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--to-date", dest="to_date", help="Fecha fin YYYY-MM-DD. Default: hoy")
    parser.add_argument("--batch-days", type=int, default=1, help="Dias por batch Oracle. Default: 1")
    parser.add_argument("--force-refresh", action="store_true", help="Borra e inserta nuevamente el rango consultado")
    return parser.parse_args()


def _date_range(args: argparse.Namespace) -> tuple[datetime, datetime]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_base = datetime.strptime(args.to_date, "%Y-%m-%d") if args.to_date else today
    end_base = end_base.replace(hour=0, minute=0, second=0, microsecond=0)
    if args.from_date:
        start_base = datetime.strptime(args.from_date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start_base = end_base - timedelta(days=int(args.days))
    if end_base < start_base:
        raise ValueError("to-date debe ser mayor o igual a from-date")
    return start_base, end_base + timedelta(days=1)


def _batch_windows(start_dt: datetime, end_dt: datetime, batch_days: int) -> list[tuple[datetime, datetime]]:
    windows = []
    cursor = start_dt
    step = max(1, int(batch_days))
    while cursor < end_dt:
        next_cursor = min(cursor + timedelta(days=step), end_dt)
        windows.append((cursor, next_cursor))
        cursor = next_cursor
    return windows


def _row_uid(fh_mov: str, operario: str, zona: str, cantidad: float, pallet: str, almacen: str) -> str:
    raw = "|".join([
        fh_mov or "",
        operario or "",
        zona or "",
        f"{cantidad:.4f}",
        pallet or "",
        almacen or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _delete_range(start_dt: datetime, end_dt: datetime) -> None:
    import aiosqlite

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            DELETE FROM plantel_movimientos_hist
            WHERE fecha >= ? AND fecha < ?
            """,
            (start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")),
        )
        await db.commit()


async def _store_rows(rows: list[dict], source_name: str) -> int:
    import aiosqlite

    payload = []
    for row in rows:
        fh = str(row.get("FHMOVIMIENTO") or "").strip()
        if not fh:
            continue
        fh_dt = datetime.fromisoformat(fh.replace("T", " ")[:19])
        operario = str(row.get("OPERARIO") or "").strip()
        zona = str(row.get("ZONAORIGEN") or "").strip()
        almacen = str(row.get("ALMACEN") or "").strip()
        cantidad = float(row.get("CANTIDAD") or 0)
        pallet = str(row.get("NROPALLET") or "").strip()
        payload.append(
            (
                _row_uid(fh, operario, zona, cantidad, pallet, almacen),
                fh_dt.date().isoformat(),
                fh_dt.strftime("%Y-%m-%d %H:%M:%S"),
                _infer_turno_key_from_dt(fh_dt),
                operario,
                operario,
                zona,
                almacen,
                cantidad,
                float(row.get("PESOREGISTRADO") or 0),
                pallet,
                source_name,
            )
        )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """
            INSERT OR REPLACE INTO plantel_movimientos_hist (
                row_uid, fecha, fh_movimiento, turno_key, operario_id, operario_nombre,
                zona_origen, almacen, cantidad, peso_registrado, nro_pallet, source_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        await db.commit()
    return len(payload)


async def _run() -> None:
    args = _parse_args()
    load_dotenv(override=True)
    await init_db()

    start_dt, end_dt = _date_range(args)
    windows = _batch_windows(start_dt, end_dt, args.batch_days)

    print(f"[PLANTEL BACKFILL] Rango {start_dt:%Y-%m-%d} -> {(end_dt - timedelta(days=1)):%Y-%m-%d}")
    print(f"[PLANTEL BACKFILL] Batches: {len(windows)} de {args.batch_days} día(s)")

    if args.force_refresh:
        print("[PLANTEL BACKFILL] Limpiando rango previo en plantel_movimientos_hist...")
        await _delete_range(start_dt, end_dt)

    total_rows = 0
    for index, (batch_start, batch_end) in enumerate(windows, start=1):
        desde = batch_start.strftime("%Y-%m-%d %H:%M:%S")
        hasta = (batch_end - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{index}/{len(windows)}] Oracle {desde} -> {hasta}")
        rows = await asyncio.to_thread(query_productive_db_plantel, desde, hasta)
        inserted = await _store_rows(rows, "oracle_productiva")
        total_rows += inserted
        print(f"    filas Oracle={len(rows)} | upsert local={inserted}")

    print(f"[PLANTEL BACKFILL] Completo. Filas procesadas: {total_rows}")


if __name__ == "__main__":
    asyncio.run(_run())
