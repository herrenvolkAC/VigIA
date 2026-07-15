"""
Base SQLite independiente para el modulo Plantel Optimo.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from db.paths import ROOT_DIR, resolve_db_path


PLANTEL_OPTIMO_DB_PATH = resolve_db_path("PLANTEL_OPTIMO_DB_PATH", "plantel_optimo.db", ROOT_DIR)


CREATE_PRODUCTIVIDAD_SECTOR = """
CREATE TABLE IF NOT EXISTS productividad_sector (
    sector TEXT PRIMARY KEY,
    almacen TEXT NOT NULL,
    productividad_hora REAL NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    updated_by TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


CREATE_DEMANDA_CACHE = """
CREATE TABLE IF NOT EXISTS demanda_cache (
    cache_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    synced_by TEXT,
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
    rows_json TEXT NOT NULL,
    rows_count INTEGER NOT NULL DEFAULT 0
);
"""


CREATE_ESCENARIOS = """
CREATE TABLE IF NOT EXISTS escenarios (
    scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT,
    source_name TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    demanda_json TEXT NOT NULL,
    productividad_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
"""


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_plantel_optimo_productividad_almacen ON productividad_sector(almacen, activo)",
    "CREATE INDEX IF NOT EXISTS idx_plantel_optimo_demanda_cache_sync ON demanda_cache(synced_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_plantel_optimo_escenarios_created ON escenarios(created_at DESC)",
]


async def init_plantel_optimo_db() -> None:
    PLANTEL_OPTIMO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(PLANTEL_OPTIMO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        for stmt in (CREATE_PRODUCTIVIDAD_SECTOR, CREATE_DEMANDA_CACHE, CREATE_ESCENARIOS):
            await db.execute(stmt)
        for stmt in INDEXES:
            await db.execute(stmt)
        await db.commit()


async def connect_plantel_optimo_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(PLANTEL_OPTIMO_DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA busy_timeout = 10000")
    return db


@asynccontextmanager
async def plantel_optimo_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await connect_plantel_optimo_db()
    try:
        yield db
    finally:
        await db.close()
