"""
Base SQLite independiente para autenticacion, usuarios y accesos de VigIA.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from db.paths import ROOT_DIR, resolve_db_path
from db.schema import DB_PATH as LEGACY_DB_PATH


AUTH_DB_PATH = resolve_db_path("VIGIA_AUTH_DB_PATH", "vigia_auth.db", ROOT_DIR)

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS auth_devices (
    device_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    user_agent TEXT,
    ip_address TEXT,
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    approved_at DATETIME,
    approved_by TEXT,
    rejected_at DATETIME,
    rejected_by TEXT,
    revoked_at DATETIME,
    revoked_by TEXT
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    session_token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_user_module_scopes (
    scope_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    module TEXT NOT NULL DEFAULT 'novedades_cd',
    scope TEXT NOT NULL DEFAULT 'operativo',
    sector TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS auth_user_app_access (
    access_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    module TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    profile TEXT,
    scope TEXT,
    sector TEXT,
    email TEXT,
    metadata_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(username, module)
);
CREATE INDEX IF NOT EXISTS idx_auth_devices_username ON auth_devices(username, status);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_username ON auth_sessions(username, expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_scopes_username_module ON auth_user_module_scopes(username, module, active);
CREATE INDEX IF NOT EXISTS idx_auth_app_access_user_module ON auth_user_app_access(username, module, enabled);
"""

AUTH_TABLES = [
    "auth_users",
    "auth_devices",
    "auth_sessions",
    "auth_user_module_scopes",
    "auth_user_app_access",
]


async def _attach_operational(db: aiosqlite.Connection) -> None:
    if AUTH_DB_PATH.resolve() == LEGACY_DB_PATH.resolve():
        raise RuntimeError("VIGIA_AUTH_DB_PATH debe ser distinto de VIGIA_OPERATIVA_DB_PATH.")
    await db.execute("ATTACH DATABASE ? AS operational", (str(LEGACY_DB_PATH),))


async def _legacy_has_table(db: aiosqlite.Connection, table: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM operational.sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ) as cur:
        return await cur.fetchone() is not None


async def _migrate_legacy_auth_if_empty(db: aiosqlite.Connection) -> None:
    async with db.execute("SELECT COUNT(*) FROM auth_users") as cur:
        if int((await cur.fetchone())[0]) > 0:
            return
    for table in AUTH_TABLES:
        if await _legacy_has_table(db, table):
            async with db.execute(f"PRAGMA main.table_info({table})") as cur:
                target_columns = {row[1] for row in await cur.fetchall()}
            async with db.execute(f"PRAGMA operational.table_info({table})") as cur:
                source_columns = {row[1] for row in await cur.fetchall()}
            columns = sorted(target_columns & source_columns)
            if not columns:
                continue
            names = ", ".join(f'"{column}"' for column in columns)
            await db.execute(
                f"INSERT OR IGNORE INTO main.{table} ({names}) "
                f"SELECT {names} FROM operational.{table}"
            )


async def init_auth_db() -> None:
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(AUTH_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.executescript(AUTH_SCHEMA)
        await _attach_operational(db)
        await _migrate_legacy_auth_if_empty(db)
        await db.commit()


@asynccontextmanager
async def auth_db(*, attach_operational: bool = False) -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(AUTH_DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA busy_timeout = 10000")
    if attach_operational:
        await _attach_operational(db)
    try:
        yield db
    finally:
        await db.close()


async def attach_auth_db(db: aiosqlite.Connection) -> None:
    async with db.execute("PRAGMA database_list") as cur:
        if any(row[1] == "authdb" for row in await cur.fetchall()):
            return
    await db.execute("ATTACH DATABASE ? AS authdb", (str(AUTH_DB_PATH),))
