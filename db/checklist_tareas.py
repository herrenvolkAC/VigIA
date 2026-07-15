"""Base SQLite independiente para el modulo CheckList Tareas."""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import AsyncIterator, Any

import aiosqlite

from db.auth import auth_db
from db.paths import ROOT_DIR, resolve_db_path


CHECKLIST_DB_PATH = resolve_db_path(
    "CHECKLIST_TAREAS_DB_PATH", "checklist_tareas.db", ROOT_DIR
)
SEED_PATH = ROOT_DIR / "resources" / "checklist_tareas_seed_v1.json"
logger = logging.getLogger("vigia.checklist_tareas")


SCHEMA = """
CREATE TABLE IF NOT EXISTS checklist_sector (
    sector_id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checklist_task (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    duration_minutes INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checklist_assignment (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed_key TEXT UNIQUE,
    legacy_id INTEGER,
    task_id INTEGER NOT NULL REFERENCES checklist_task(task_id),
    sector_id INTEGER NOT NULL REFERENCES checklist_sector(sector_id),
    username TEXT NOT NULL,
    shift TEXT,
    duration_minutes INTEGER,
    allow_delay INTEGER NOT NULL DEFAULT 0,
    instructions_override TEXT,
    starts_on TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checklist_schedule (
    schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL UNIQUE REFERENCES checklist_assignment(assignment_id) ON DELETE CASCADE,
    schedule_type TEXT NOT NULL,
    weekdays_json TEXT,
    specific_date TEXT,
    monthly_day INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checklist_occurrence (
    occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER REFERENCES checklist_assignment(assignment_id),
    sector_id INTEGER NOT NULL REFERENCES checklist_sector(sector_id),
    scheduled_date TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT,
    completed_by TEXT,
    completed_at TEXT,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    eventual_title TEXT,
    responsible_username TEXT,
    shift TEXT,
    duration_minutes INTEGER,
    allow_delay INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(assignment_id, scheduled_date)
);

CREATE TABLE IF NOT EXISTS checklist_delegation (
    delegation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_id INTEGER NOT NULL REFERENCES checklist_sector(sector_id),
    from_username TEXT NOT NULL,
    to_username TEXT NOT NULL,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklist_delegation_assignment (
    delegation_id INTEGER NOT NULL REFERENCES checklist_delegation(delegation_id) ON DELETE CASCADE,
    assignment_id INTEGER NOT NULL REFERENCES checklist_assignment(assignment_id) ON DELETE CASCADE,
    PRIMARY KEY (delegation_id, assignment_id)
);

CREATE TABLE IF NOT EXISTS checklist_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_id INTEGER,
    actor_username TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklist_seed_migration (
    seed_version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_checklist_assignment_sector_active
    ON checklist_assignment(sector_id, active, username);
CREATE INDEX IF NOT EXISTS idx_checklist_occurrence_effective
    ON checklist_occurrence(sector_id, effective_date, status);
CREATE INDEX IF NOT EXISTS idx_checklist_occurrence_assignment
    ON checklist_occurrence(assignment_id, scheduled_date);
CREATE INDEX IF NOT EXISTS idx_checklist_delegation_dates
    ON checklist_delegation(sector_id, active, date_from, date_to);
CREATE INDEX IF NOT EXISTS idx_checklist_delegation_assignment_assignment
    ON checklist_delegation_assignment(assignment_id, delegation_id);
CREATE INDEX IF NOT EXISTS idx_checklist_audit_entity
    ON checklist_audit(entity_type, entity_id, created_at);
"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def date_today() -> str:
    return date.today().isoformat()


def _load_seed() -> dict[str, Any] | None:
    if not SEED_PATH.exists():
        return None
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _auto_init_enabled() -> bool:
    return os.getenv("CHECKLIST_TAREAS_AUTO_INIT", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


async def _missing_seed_operators(seed: dict[str, Any]) -> list[str]:
    operators = list(seed["operators"])
    async with auth_db() as db:
        placeholders = ",".join("?" for _ in operators)
        async with db.execute(
            f"SELECT username FROM auth_users WHERE active = 1 AND username IN ({placeholders})",
            tuple(operators),
        ) as cur:
            existing = {row[0] for row in await cur.fetchall()}
    return sorted(set(operators) - existing)


async def _has_seed(db: aiosqlite.Connection, version: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM checklist_seed_migration WHERE seed_version = ?", (version,)
    ) as cur:
        return await cur.fetchone() is not None


async def _seed_operational_data(db: aiosqlite.Connection, seed: dict[str, Any]) -> None:
    version = str(seed["seed_version"])
    if await _has_seed(db, version):
        return

    sector = seed["sector"]
    await db.execute(
        """
        INSERT INTO checklist_sector (code, name, active, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET name=excluded.name, active=excluded.active, updated_at=excluded.updated_at
        """,
        (sector["code"], sector["name"], int(sector.get("active", True)), now_iso()),
    )
    async with db.execute(
        "SELECT sector_id FROM checklist_sector WHERE code = ?", (sector["code"],)
    ) as cur:
        sector_id = int((await cur.fetchone())[0])

    for task in seed["tasks"]:
        await db.execute(
            """
            INSERT INTO checklist_task (code, title, duration_minutes, active, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                title=excluded.title, duration_minutes=excluded.duration_minutes,
                active=excluded.active, updated_at=excluded.updated_at
            """,
            (
                task["code"], task["title"], task.get("duration_minutes"),
                int(task.get("active", True)), now_iso(),
            ),
        )

    async with db.execute("SELECT task_id, code FROM checklist_task") as cur:
        task_ids = {row[1]: int(row[0]) for row in await cur.fetchall()}

    for item in seed["assignments"]:
        await db.execute(
            """
            INSERT INTO checklist_assignment
                (seed_key, legacy_id, task_id, sector_id, username, shift, duration_minutes,
                 allow_delay, instructions_override, starts_on, active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(seed_key) DO UPDATE SET
                task_id=excluded.task_id, sector_id=excluded.sector_id, username=excluded.username,
                shift=excluded.shift, duration_minutes=excluded.duration_minutes,
                allow_delay=excluded.allow_delay, instructions_override=excluded.instructions_override,
                starts_on=COALESCE(checklist_assignment.starts_on, excluded.starts_on),
                active=excluded.active, updated_at=excluded.updated_at
            """,
            (
                item["seed_key"], item["legacy_id"], task_ids[item["task_code"]], sector_id,
                item["username"], None, None,
                int(item.get("allow_delay", False)), item.get("instructions_override"),
                date_today(), int(item.get("active", True)), now_iso(),
            ),
        )
        async with db.execute(
            "SELECT assignment_id FROM checklist_assignment WHERE seed_key = ?", (item["seed_key"],)
        ) as cur:
            assignment_id = int((await cur.fetchone())[0])
        schedule = item.get("schedule")
        if schedule:
            await db.execute(
                """
                INSERT INTO checklist_schedule
                    (assignment_id, schedule_type, weekdays_json, specific_date, monthly_day, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(assignment_id) DO UPDATE SET
                    schedule_type=excluded.schedule_type, weekdays_json=excluded.weekdays_json,
                    specific_date=excluded.specific_date, monthly_day=excluded.monthly_day,
                    updated_at=excluded.updated_at
                """,
                (
                    assignment_id, schedule["type"],
                    json.dumps(schedule.get("weekdays"), ensure_ascii=False) if schedule.get("weekdays") is not None else None,
                    schedule.get("date"), schedule.get("day"), now_iso(),
                ),
            )

    await db.execute(
        """
        INSERT INTO checklist_seed_migration (seed_version, applied_at, details_json)
        VALUES (?, ?, ?)
        """,
        (
            version,
            now_iso(),
            json.dumps(
                {"tasks": len(seed["tasks"]), "assignments": len(seed["assignments"])},
                ensure_ascii=False,
            ),
        ),
    )


async def _seed_auth_access(db: aiosqlite.Connection, seed: dict[str, Any]) -> None:
    version = f"{seed['seed_version']}:auth_access"
    operators = list(seed["operators"])
    if not await _has_seed(db, version):
        async with auth_db() as adb:
            timestamp = now_iso()
            await adb.executemany(
                """
                INSERT INTO auth_user_app_access
                    (username, module, enabled, profile, scope, sector, metadata_json, updated_at)
                VALUES (?, 'checklist_tareas', 1, 'OPERADOR', 'sector', ?, ?, ?)
                ON CONFLICT(username, module) DO UPDATE SET
                    enabled=1, profile='OPERADOR', scope='sector', sector=excluded.sector,
                    metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
                """,
                [
                    (
                        username,
                        seed["sector"]["name"],
                        json.dumps(
                            {
                                "sectors": [seed["sector"]["code"]],
                                "shift": (seed.get("operator_shifts") or {}).get(username),
                            },
                            ensure_ascii=False,
                        ),
                        timestamp,
                    )
                    for username in operators
                ],
            )
            await adb.commit()
        await db.execute(
            "INSERT INTO checklist_seed_migration (seed_version, applied_at, details_json) VALUES (?, ?, ?)",
            (version, now_iso(), json.dumps({"operators": len(operators)})),
        )

    shift_version = f"{seed['seed_version']}:auth_shift_v2"
    if await _has_seed(db, shift_version):
        return
    async with auth_db() as adb:
        for username in operators:
            async with adb.execute(
                "SELECT metadata_json FROM auth_user_app_access WHERE username=? AND module='checklist_tareas'",
                (username,),
            ) as cur:
                row = await cur.fetchone()
            metadata: dict[str, Any] = {}
            if row:
                try:
                    metadata = json.loads(row[0] or "{}")
                except json.JSONDecodeError:
                    metadata = {}
                metadata["sectors"] = metadata.get("sectors") or [seed["sector"]["code"]]
                metadata["shift"] = (seed.get("operator_shifts") or {}).get(username)
                await adb.execute(
                    """
                    UPDATE auth_user_app_access SET metadata_json=?, updated_at=?
                    WHERE username=? AND module='checklist_tareas'
                    """,
                    (json.dumps(metadata, ensure_ascii=False), now_iso(), username),
                )
            else:
                await adb.execute(
                    """
                    INSERT INTO auth_user_app_access
                        (username, module, enabled, profile, scope, sector, metadata_json, updated_at)
                    VALUES (?, 'checklist_tareas', 1, 'OPERADOR', 'sector', ?, ?, ?)
                    """,
                    (
                        username, seed["sector"]["name"],
                        json.dumps(
                            {"sectors": [seed["sector"]["code"]], "shift": (seed.get("operator_shifts") or {}).get(username)},
                            ensure_ascii=False,
                        ),
                        now_iso(),
                    ),
                )
        await adb.commit()
    await db.execute(
        "INSERT INTO checklist_seed_migration (seed_version, applied_at, details_json) VALUES (?, ?, ?)",
        (shift_version, now_iso(), json.dumps({"operators": len(operators)})),
    )


async def _sync_seed_task_defaults(db: aiosqlite.Connection, seed: dict[str, Any]) -> None:
    for task in seed["tasks"]:
        await db.execute(
            """
            UPDATE checklist_task
            SET duration_minutes = COALESCE(duration_minutes, ?)
            WHERE code = ?
            """,
            (task.get("duration_minutes"), task["code"]),
        )


async def init_checklist_tareas_db(*, force_seed: bool = False) -> dict[str, Any]:
    CHECKLIST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(CHECKLIST_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.executescript(SCHEMA)
        async with db.execute("PRAGMA table_info(checklist_assignment)") as cur:
            assignment_columns = {row[1] for row in await cur.fetchall()}
        if "starts_on" not in assignment_columns:
            await db.execute("ALTER TABLE checklist_assignment ADD COLUMN starts_on TEXT")
        async with db.execute("PRAGMA table_info(checklist_task)") as cur:
            task_columns = {row[1] for row in await cur.fetchall()}
        if "duration_minutes" not in task_columns:
            await db.execute("ALTER TABLE checklist_task ADD COLUMN duration_minutes INTEGER")
        await db.execute(
            "UPDATE checklist_assignment SET starts_on = ? WHERE starts_on IS NULL",
            (date_today(),),
        )
        await db.execute(
            "UPDATE checklist_assignment SET shift = NULL, duration_minutes = NULL "
            "WHERE shift IS NOT NULL OR duration_minutes IS NOT NULL"
        )
        await db.commit()

        if not force_seed and not _auto_init_enabled():
            existing_seed = _load_seed()
            if existing_seed is not None and await _has_seed(db, str(existing_seed["seed_version"])):
                await _sync_seed_task_defaults(db, existing_seed)
                await db.commit()
                await _seed_auth_access(db, existing_seed)
                await db.commit()
                return {
                    "status": "already_initialized",
                    "db_path": str(CHECKLIST_DB_PATH),
                    "tasks": len(existing_seed["tasks"]),
                    "assignments": len(existing_seed["assignments"]),
                    "operators": len(existing_seed["operators"]),
                }
            logger.warning(
                "CheckList Tareas: inicializacion automatica deshabilitada; esquema disponible sin seed."
            )
            return {"status": "disabled", "db_path": str(CHECKLIST_DB_PATH)}

        seed = _load_seed()
        if seed is None:
            logger.warning(
                "CheckList Tareas: no se encontro %s; VigIA inicia sin cargar tareas.", SEED_PATH
            )
            return {
                "status": "waiting_seed",
                "db_path": str(CHECKLIST_DB_PATH),
                "seed_path": str(SEED_PATH),
            }

        missing = await _missing_seed_operators(seed)
        if missing:
            logger.warning(
                "CheckList Tareas: seed pendiente; faltan usuarios activos: %s",
                ", ".join(missing),
            )
            return {
                "status": "waiting_users",
                "db_path": str(CHECKLIST_DB_PATH),
                "missing_users": missing,
            }

        already_loaded = await _has_seed(db, str(seed["seed_version"]))
        await _seed_operational_data(db, seed)
        await _sync_seed_task_defaults(db, seed)
        await db.commit()
        await _seed_auth_access(db, seed)
        await db.commit()
        return {
            "status": "already_initialized" if already_loaded else "initialized",
            "db_path": str(CHECKLIST_DB_PATH),
            "tasks": len(seed["tasks"]),
            "assignments": len(seed["assignments"]),
            "operators": len(seed["operators"]),
        }


@asynccontextmanager
async def checklist_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(CHECKLIST_DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA busy_timeout = 10000")
    await db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
    finally:
        await db.close()
