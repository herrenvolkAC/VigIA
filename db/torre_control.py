"""Persistencia local de snapshots para la Torre de Control OpEx."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from db.paths import resolve_db_path


ROOT_DIR = Path(__file__).resolve().parent.parent
TORRE_CONTROL_DB_PATH = resolve_db_path(
    "TORRE_CONTROL_DB_PATH",
    "torre_control.db",
    ROOT_DIR,
)

DIVISION_LABELS = {
    "1": "SECOS",
    "2": "REFRIGERADOS",
    "3": "SECOS",
    "4": "REFRIGERADOS",
    "6": "NOA",
}


def division_label(value: Any) -> str:
    text = "" if value is None else str(value).strip().upper()
    return DIVISION_LABELS.get(text, text or "SIN DIVISIÓN")


async def init_torre_control_db() -> None:
    TORRE_CONTROL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(TORRE_CONTROL_DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ubicaciones_division (
                codigo_ubicacion TEXT PRIMARY KEY,
                pasillo TEXT NOT NULL,
                hueco TEXT NOT NULL,
                zona_almacen TEXT NOT NULL,
                division TEXT NOT NULL,
                actualizado_en TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS torre_control_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT NOT NULL UNIQUE,
                fecha_desde TEXT NOT NULL,
                fecha_hasta TEXT NOT NULL,
                refreshed_at TEXT NOT NULL,
                oracle_now TEXT,
                row_count INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_torre_control_range "
            "ON torre_control_snapshots(fecha_desde, fecha_hasta)"
        )
        await db.commit()


async def get_ubicaciones_division() -> dict[str, str]:
    await init_torre_control_db()
    async with aiosqlite.connect(TORRE_CONTROL_DB_PATH) as db:
        async with db.execute(
            "SELECT codigo_ubicacion, division FROM ubicaciones_division"
        ) as cur:
            return {str(row[0]): division_label(row[1]) for row in await cur.fetchall()}


async def save_ubicaciones_division(rows: list[dict[str, Any]], actualizado_en: str) -> int:
    await init_torre_control_db()
    async with aiosqlite.connect(TORRE_CONTROL_DB_PATH) as db:
        await db.executemany(
            """
            INSERT INTO ubicaciones_division (
                codigo_ubicacion, pasillo, hueco, zona_almacen, division, actualizado_en
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(codigo_ubicacion) DO UPDATE SET
                pasillo = excluded.pasillo,
                hueco = excluded.hueco,
                zona_almacen = excluded.zona_almacen,
                division = excluded.division,
                actualizado_en = excluded.actualizado_en
            """,
            [
                (
                    row["codigo_ubicacion"],
                    row["pasillo"],
                    row["hueco"],
                    row["zona_almacen"],
                    division_label(row["division"]),
                    actualizado_en,
                )
                for row in rows
            ],
        )
        await db.commit()
    return len(rows)


async def get_snapshot(cache_key: str) -> dict[str, Any] | None:
    await init_torre_control_db()
    async with aiosqlite.connect(TORRE_CONTROL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM torre_control_snapshots WHERE cache_key = ?",
            (cache_key,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["payload"] = json.loads(result.pop("payload_json"))
        except (TypeError, json.JSONDecodeError):
            return None
        return result


async def save_snapshot(
    *,
    cache_key: str,
    fecha_desde: str,
    fecha_hasta: str,
    refreshed_at: str,
    oracle_now: str | None,
    row_count: int,
    payload: dict[str, Any],
) -> None:
    await init_torre_control_db()
    async with aiosqlite.connect(TORRE_CONTROL_DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO torre_control_snapshots (
                cache_key, fecha_desde, fecha_hasta, refreshed_at,
                oracle_now, row_count, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(cache_key) DO UPDATE SET
                fecha_desde = excluded.fecha_desde,
                fecha_hasta = excluded.fecha_hasta,
                refreshed_at = excluded.refreshed_at,
                oracle_now = excluded.oracle_now,
                row_count = excluded.row_count,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                cache_key,
                fecha_desde,
                fecha_hasta,
                refreshed_at,
                oracle_now,
                row_count,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        await db.commit()
