"""Cache local para calculos automaticos de Daily.

Esta base es independiente de vigia.db y de daily_operativa.db. El objetivo es
que la UI lea resultados precalculados sin consultar Oracle en el flujo
interactivo.
"""
from __future__ import annotations

import json
import hashlib
from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from db.daily_operativa import LOCAL_TZ
from db.paths import resolve_db_path


DAILY_AUTO_DB_PATH = resolve_db_path(
    "DAILY_AUTO_DB_PATH",
    "daily_auto.db",
    Path(__file__).resolve().parent,
)


CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS daily_auto_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_key       TEXT NOT NULL,
    daily_label     TEXT NOT NULL,
    fecha_inicio    TEXT NOT NULL,
    fecha_fin       TEXT NOT NULL,
    fecha_carga     TEXT NOT NULL,
    process         TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    duration_ms     REAL,
    row_count       INTEGER DEFAULT 0,
    error           TEXT,
    timings_json    TEXT,
    run_trigger     TEXT DEFAULT 'scheduler',
    usuario         TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(daily_key, process)
);
"""


CREATE_RESULTADOS = """
CREATE TABLE IF NOT EXISTS daily_auto_resultados (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES daily_auto_runs(id) ON DELETE CASCADE,
    daily_key       TEXT NOT NULL,
    process         TEXT NOT NULL,
    sector          TEXT NOT NULL,
    sector_oracle   TEXT NOT NULL,
    id_parametro    TEXT NOT NULL,
    valor           REAL,
    cantidad        REAL,
    legajos         REAL,
    details_count   INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(daily_key, process, sector, id_parametro)
);
"""


CREATE_CLARK_DETALLE = """
CREATE TABLE IF NOT EXISTS daily_auto_clark_detalle (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES daily_auto_runs(id) ON DELETE CASCADE,
    daily_key       TEXT NOT NULL,
    sector          TEXT NOT NULL,
    sector_oracle   TEXT NOT NULL,
    almacen         TEXT,
    legajo          TEXT,
    nombre          TEXT,
    fecha           TEXT,
    pallet          TEXT,
    operacion       TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RAW_PRODUCTIVIDAD = """
CREATE TABLE IF NOT EXISTS daily_auto_productividad_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_key       TEXT NOT NULL,
    fecha_inicio    TEXT NOT NULL,
    fecha_fin       TEXT NOT NULL,
    row_index       INTEGER NOT NULL,
    row_hash        TEXT NOT NULL,
    legajo          TEXT,
    fecha           TEXT,
    operacion       TEXT,
    almacen         TEXT,
    zona_origen     TEXT,
    ubicacion       TEXT,
    pallet          TEXT,
    referencia      TEXT,
    cantidad        REAL,
    raw_json        TEXT NOT NULL,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(daily_key, row_index)
);
"""

CREATE_RAW_DESPACHO = """
CREATE TABLE IF NOT EXISTS daily_auto_despacho_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_key       TEXT NOT NULL,
    fecha_inicio    TEXT NOT NULL,
    fecha_fin       TEXT NOT NULL,
    row_index       INTEGER NOT NULL,
    row_hash        TEXT NOT NULL,
    almacen         TEXT,
    viaje           TEXT,
    cargador        TEXT,
    fecha_cierre    TEXT,
    division        TEXT,
    raw_json        TEXT NOT NULL,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(daily_key, row_index)
);
"""

CREATE_MANUAL_COMPARACION = """
CREATE TABLE IF NOT EXISTS daily_manual_comparacion (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file     TEXT NOT NULL,
    source_row      INTEGER NOT NULL,
    concepto        TEXT NOT NULL,
    fecha_daily     TEXT NOT NULL,
    daily_key       TEXT NOT NULL,
    sector          TEXT NOT NULL,
    up              TEXT NOT NULL,
    metrica         TEXT NOT NULL,
    operacion       TEXT NOT NULL,
    id_parametro    TEXT NOT NULL,
    valor_manual    REAL,
    imported_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_file, source_row, concepto)
);
"""

CREATE_AUTO_MANUAL_COMPARACION = """
CREATE TABLE IF NOT EXISTS daily_auto_manual_comparacion (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_key               TEXT NOT NULL,
    fecha_daily             TEXT NOT NULL,
    sector                  TEXT NOT NULL,
    up                      TEXT NOT NULL,
    metrica                 TEXT NOT NULL,
    operacion               TEXT NOT NULL,
    concepto                TEXT NOT NULL,
    id_parametro            TEXT NOT NULL,
    valor_manual            REAL,
    valor_automatico        REAL,
    diferencia              REAL,
    diferencia_abs          REAL,
    diferencia_pct          REAL,
    estado                  TEXT NOT NULL,
    source_file             TEXT,
    source_row              INTEGER,
    compared_at             TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(daily_key, sector, up, metrica, concepto, id_parametro)
);
"""


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_runs_lookup ON daily_auto_runs(daily_key, process, status)",
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_resultados_lookup ON daily_auto_resultados(daily_key, process, sector)",
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_clark_lookup ON daily_auto_clark_detalle(daily_key, sector)",
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_prod_raw_key ON daily_auto_productividad_raw(daily_key, fecha, operacion)",
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_prod_raw_lookup ON daily_auto_productividad_raw(daily_key, almacen, legajo)",
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_despacho_raw_key ON daily_auto_despacho_raw(daily_key, fecha_cierre, almacen)",
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_despacho_raw_lookup ON daily_auto_despacho_raw(daily_key, almacen, cargador)",
    "CREATE INDEX IF NOT EXISTS idx_daily_manual_comp_key ON daily_manual_comparacion(fecha_daily, daily_key, sector, id_parametro)",
    "CREATE INDEX IF NOT EXISTS idx_daily_auto_manual_comp_lookup ON daily_auto_manual_comparacion(fecha_daily, sector, operacion, metrica)",
]


SECTOR_MAP = {
    "NOA": "Noa",
    "SECOS": "Secos",
    "REFRIGERADOS": "Refrigerados",
    "OC": "OC",
    "CONGELADOS": "Congelados",
}


CLARK_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_PROD_CLARK_NOA_6A6",
    "Secos": "OP_PROD_CLARK_SECOS_6A6",
    "Refrigerados": "OP_PROD_CLARK_REFRI_6A6",
    "OC": "OP_PROD_CLARK_OC_6A6",
    "Congelados": "OP_PROD_CLARK_CONGELADOS_6A6",
}

PICKING_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_PROD_PICKING_NOA_6A6",
    "Secos": "OP_PROD_PICKING_SECOS_6A6",
    "Refrigerados": "OP_PROD_PICKING_REFRI_6A6",
    "OC": "OP_PROD_PICKING_OC_6A6",
    "Congelados": "OP_PROD_PICKING_CONGELADOS_6A6",
}

PICKING_REAL_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_PICKING_REAL_6A6",
    "Secos": "OP_CUMP_PICKING_REAL_6A6",
    "Refrigerados": "OP_CUMP_PICKING_REAL_6A6",
}

PICKING_DOTACION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_DOT_PICKING_LEGAJOS_6A8",
    "Secos": "OP_DOT_PICKING_LEGAJOS_6A8",
    "Refrigerados": "OP_DOT_PICKING_LEGAJOS_6A8",
}

CLARK_DOTACION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_DOT_SPC_LEGAJOS_6A8",
    "Secos": "OP_DOT_SPC_LEGAJOS_6A8",
    "Refrigerados": "OP_DOT_SPC_LEGAJOS_6A8",
}

SPC_REAL_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_SPC_REAL_6A6",
    "Secos": "OP_CUMP_SPC_REAL_6A6",
    "Refrigerados": "OP_CUMP_SPC_REAL_6A6",
}

RECEPCION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_PROD_RECEPCION_NOA_6A6",
    "Secos": "OP_PROD_RECEPCION_SECOS_6A6",
    "Refrigerados": "OP_PROD_RECEPCION_REFRI_6A6",
}

RECEPCION_REAL_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_RECEPCION_REAL_6A6",
    "Secos": "OP_CUMP_RECEPCION_REAL_6A6",
    "Refrigerados": "OP_CUMP_RECEPCION_REAL_6A6",
}

RECEPCION_DOTACION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_DOT_RECEPCION_LEGAJOS_6A8",
    "Secos": "OP_DOT_RECEPCION_LEGAJOS_6A8",
    "Refrigerados": "OP_DOT_RECEPCION_LEGAJOS_6A8",
}

DESPACHO_PARAM_IDS_BY_SECTOR = {
    "Secos": "OP_PROD_DESPACHO_SECOS_6A6",
    "Refrigerados": "OP_PROD_DESPACHO_REFRI_6A6",
}

DESPACHO_REAL_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_DESPACHO_REAL_6A6",
    "Secos": "OP_CUMP_DESPACHO_REAL_6A6",
    "Refrigerados": "OP_CUMP_DESPACHO_REAL_6A6",
}

DESPACHO_DOTACION_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_DOT_DESPACHO_LEGAJOS_6A8",
    "Secos": "OP_DOT_DESPACHO_LEGAJOS_6A8",
    "Refrigerados": "OP_DOT_DESPACHO_LEGAJOS_6A8",
}

PICKING_PLAN_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_PICKING_PLAN_6A6",
    "Secos": "OP_CUMP_PICKING_PLAN_6A6",
    "Refrigerados": "OP_CUMP_PICKING_PLAN_6A6",
}

SPC_PLAN_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_SPC_PLAN_6A6",
    "Secos": "OP_CUMP_SPC_PLAN_6A6",
    "Refrigerados": "OP_CUMP_SPC_PLAN_6A6",
}

DESPACHO_PLAN_PARAM_IDS_BY_SECTOR = {
    "Noa": "OP_CUMP_DESPACHO_PLAN_6A6",
    "Secos": "OP_CUMP_DESPACHO_PLAN_6A6",
    "Refrigerados": "OP_CUMP_DESPACHO_PLAN_6A6",
}

PRODUCTIVIDAD_JORNADA_BY_SECTOR = {
    "Congelados": 6.0,
}

REFRIGERADOS_SPLIT_SECTORS = {"OC", "Congelados"}


def _productividad_jornada(sector: str) -> float:
    return PRODUCTIVIDAD_JORNADA_BY_SECTOR.get(sector, 6.5)


AVANCE_PARAM_IDS = {
    ("RECEPCION", "PLAN"): "OP_AVANCE_RECEPCION_PLAN_6A8",
    ("RECEPCION", "REAL"): "OP_AVANCE_RECEPCION_REAL_6A8",
    ("PICKING", "PLAN"): "OP_AVANCE_PICKING_PLAN_6A8",
    ("PICKING", "REAL"): "OP_AVANCE_PICKING_REAL_6A8",
    ("SPC", "PLAN"): "OP_AVANCE_SPC_PLAN_6A8",
    ("SPC", "REAL"): "OP_AVANCE_SPC_REAL_6A8",
    ("DESPACHO", "PLAN"): "OP_AVANCE_DESPACHO_PLAN_6A8",
    ("DESPACHO", "REAL"): "OP_AVANCE_DESPACHO_REAL_6A8",
}


def _now_text() -> str:
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def _norm_legajo(value: Any) -> str:
    text = str(value or "").strip()
    return text.lstrip("0") or text


def _row_value(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if value is None:
        value = row.get(key.lower())
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def _row_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = _row_value(row, key)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _row_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(row, default=_json_default, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _day_name(value: datetime) -> str:
    labels = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
    return labels[value.weekday()]


def scheduled_daily_window(now: datetime | None = None) -> dict[str, Any]:
    """Calcula la ventana que debe precargarse, sin exigir el cutoff 06:30."""
    current = now.astimezone(LOCAL_TZ) if now else datetime.now(LOCAL_TZ)
    weekday = current.weekday()
    if weekday == 6:
        return {
            "can_run": False,
            "reason": "La Daily de fin de semana se precarga el lunes.",
            "now": current.isoformat(timespec="seconds"),
        }
    if weekday == 0:
        start_date = current.date() - timedelta(days=2)
    else:
        start_date = current.date() - timedelta(days=1)
    end_date = current.date()
    start = datetime.combine(start_date, time(6, 0), tzinfo=LOCAL_TZ)
    end = datetime.combine(end_date, time(6, 0), tzinfo=LOCAL_TZ)
    return {
        "can_run": True,
        "daily_key": f"{start:%Y%m%d0600}_{end:%Y%m%d0600}",
        "daily_label": f"{_day_name(start)} 06:00 / {_day_name(end)} 06:00",
        "fecha_inicio": start.isoformat(timespec="seconds"),
        "fecha_fin": end.isoformat(timespec="seconds"),
        "fecha_carga": current.date().isoformat(),
        "now": current.isoformat(timespec="seconds"),
    }


async def init_daily_auto_db() -> None:
    DAILY_AUTO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(CREATE_RUNS)
        await db.execute(CREATE_RESULTADOS)
        await db.execute(CREATE_CLARK_DETALLE)
        await db.execute(CREATE_RAW_PRODUCTIVIDAD)
        await db.execute(CREATE_RAW_DESPACHO)
        await db.execute(CREATE_MANUAL_COMPARACION)
        await db.execute(CREATE_AUTO_MANUAL_COMPARACION)
        async with db.execute("PRAGMA table_info(daily_auto_runs)") as cur:
            run_columns = {str(row[1]) for row in await cur.fetchall()}
        if "run_trigger" not in run_columns:
            await db.execute("ALTER TABLE daily_auto_runs ADD COLUMN run_trigger TEXT DEFAULT 'scheduler'")
        if "usuario" not in run_columns:
            await db.execute("ALTER TABLE daily_auto_runs ADD COLUMN usuario TEXT")
        for sql in INDEXES:
            await db.execute(sql)
        await db.commit()


async def purge_daily_productividad_raw_cache(retention_days: int = 5) -> int:
    await init_daily_auto_db()
    cutoff = (datetime.now(LOCAL_TZ) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        cur = await db.execute(
            "DELETE FROM daily_auto_productividad_raw WHERE fecha_inicio < ?",
            (cutoff,),
        )
        await db.commit()
        return int(cur.rowcount or 0)


async def save_productividad_raw_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    fecha_fin_raw: str,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
    retention_days: int = 5,
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    fecha_inicio = str(daily["fecha_inicio"])
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'PRODUCTIVIDAD_RAW', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], fecha_inicio, fecha_fin_raw,
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        await db.execute("DELETE FROM daily_auto_productividad_raw WHERE daily_key = ?", (daily["daily_key"],))
        for idx, row in enumerate(rows):
            raw_json = json.dumps(row, default=_json_default, ensure_ascii=False, sort_keys=True)
            await db.execute(
                """
                INSERT INTO daily_auto_productividad_raw (
                    daily_key, fecha_inicio, fecha_fin, row_index, row_hash,
                    legajo, fecha, operacion, almacen, zona_origen, ubicacion,
                    pallet, referencia, cantidad, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    daily["daily_key"], fecha_inicio, fecha_fin_raw, idx, _row_hash(row),
                    _row_value(row, "COPECREA") or _row_value(row, "LEGAJO"),
                    str(_row_value(row, "FCREAREG") or ""),
                    _row_value(row, "CDESCRIP") or _row_value(row, "OPERACION"),
                    _row_value(row, "ALMACEN"),
                    _row_value(row, "CZONAORI"),
                    _row_value(row, "CUBIORIG"),
                    _row_value(row, "CNUPALET"),
                    _row_value(row, "CREFEREN"),
                    _row_float(row, "QCANTIDA"),
                    raw_json,
                ),
            )
        purged_cur = await db.execute(
            "DELETE FROM daily_auto_productividad_raw WHERE fecha_inicio < ?",
            ((datetime.now(LOCAL_TZ) - timedelta(days=retention_days)).isoformat(timespec="seconds"),),
        )
        await db.commit()
        return {
            "rows": len(rows),
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin_raw,
            "purged_rows": int(purged_cur.rowcount or 0),
        }


async def get_productividad_raw_cache_rows(daily_key: str) -> list[dict[str, Any]]:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT row_index, legajo, fecha, operacion, almacen, cantidad, raw_json
            FROM daily_auto_productividad_raw
            WHERE daily_key = ?
            ORDER BY legajo, fecha, row_index
            """,
            (daily_key,),
        ) as cur:
            rows = []
            for row in await cur.fetchall():
                item = dict(row)
                try:
                    raw = json.loads(item.get("raw_json") or "{}")
                except json.JSONDecodeError:
                    raw = {}
                rows.append({**raw, "_row_index": item.get("row_index")})
            return rows


async def save_despacho_raw_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
    retention_days: int = 5,
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    fecha_inicio = str(daily["fecha_inicio"])
    fecha_fin = str(daily["fecha_fin"])
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'DESPACHO_RAW', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], fecha_inicio, fecha_fin,
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        await db.execute("DELETE FROM daily_auto_despacho_raw WHERE daily_key = ?", (daily["daily_key"],))
        for idx, row in enumerate(rows):
            raw_json = json.dumps(row, default=_json_default, ensure_ascii=False, sort_keys=True)
            await db.execute(
                """
                INSERT INTO daily_auto_despacho_raw (
                    daily_key, fecha_inicio, fecha_fin, row_index, row_hash,
                    almacen, viaje, cargador, fecha_cierre, division, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    daily["daily_key"], fecha_inicio, fecha_fin, idx, _row_hash(row),
                    _row_value(row, "ALMACEN"),
                    _row_value(row, "HOJARUTA") or _row_value(row, "CNUVIAJE") or _row_value(row, "VIAJE"),
                    _row_value(row, "CARGADOR"),
                    str(_row_value(row, "FECIERRE") or _row_value(row, "FECHA_CIERRE") or ""),
                    _row_value(row, "CDIVISIO"),
                    raw_json,
                ),
            )
        purged_cur = await db.execute(
            "DELETE FROM daily_auto_despacho_raw WHERE fecha_inicio < ?",
            ((datetime.now(LOCAL_TZ) - timedelta(days=retention_days)).isoformat(timespec="seconds"),),
        )
        await db.commit()
        return {
            "rows": len(rows),
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "purged_rows": int(purged_cur.rowcount or 0),
        }


async def get_despacho_raw_cache_rows(daily_key: str) -> list[dict[str, Any]]:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT row_index, raw_json
            FROM daily_auto_despacho_raw
            WHERE daily_key = ?
            ORDER BY almacen, cargador, fecha_cierre, row_index
            """,
            (daily_key,),
        ) as cur:
            rows = []
            for row in await cur.fetchall():
                item = dict(row)
                try:
                    raw = json.loads(item.get("raw_json") or "{}")
                except json.JSONDecodeError:
                    raw = {}
                rows.append({**raw, "_row_index": item.get("row_index")})
            return rows


async def has_successful_run(daily_key: str, process: str) -> bool:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        async with db.execute(
            """
            SELECT 1
            FROM daily_auto_runs
            WHERE daily_key = ? AND process = ? AND status = 'success'
            LIMIT 1
            """,
            (daily_key, process),
        ) as cur:
            return await cur.fetchone() is not None


async def mark_run_error(
    daily: dict[str, Any],
    process: str,
    error: str,
    started_at: str,
    *,
    trigger: str = "scheduler",
    usuario: str = "",
) -> None:
    await init_daily_auto_db()
    now = _now_text()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'error', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                status = 'error',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                error = excluded.error,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], process, started_at, now, str(error)[:2000],
                trigger, usuario, now,
            ),
        )
        await db.commit()


async def save_clark_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
        if sector_oracle in SECTOR_MAP:
            grouped[sector_oracle].append(row)

    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'CLARK', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'CLARK'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'CLARK'", (daily["daily_key"],))
        await db.execute("DELETE FROM daily_auto_clark_detalle WHERE daily_key = ?", (daily["daily_key"],))

        result_count = 0
        for sector_oracle, sector_rows in grouped.items():
            sector = SECTOR_MAP[sector_oracle]
            legajos = {
                _norm_legajo(_row_value(row, "LEGAJO"))
                for row in sector_rows
                if _norm_legajo(_row_value(row, "LEGAJO"))
            }
            pallets = [row for row in sector_rows if str(_row_value(row, "PALLET") or "").strip()]
            valor = round(len(pallets) / len(legajos), 2) if legajos else 0.0
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'CLARK', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, CLARK_PARAM_IDS_BY_SECTOR[sector],
                    valor, len(pallets), len(legajos), len(sector_rows),
                ),
            )
            result_count += 1
            for row in sector_rows:
                await db.execute(
                    """
                    INSERT INTO daily_auto_clark_detalle (
                        run_id, daily_key, sector, sector_oracle, almacen,
                        legajo, nombre, fecha, pallet, operacion
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, _row_value(row, "ALMACEN"),
                        _row_value(row, "LEGAJO"), _row_value(row, "NOMBRE"),
                        str(_row_value(row, "FCREAREG") or ""), _row_value(row, "PALLET"),
                        _row_value(row, "OPERACION"),
                    ),
                )
        await db.commit()
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_clark_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'CLARK', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'CLARK'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'CLARK'", (daily["daily_key"],))
        await db.execute("DELETE FROM daily_auto_clark_detalle WHERE daily_key = ?", (daily["daily_key"],))

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            if sector_oracle not in SECTOR_MAP:
                continue
            legajo = str(_row_value(row, "COPECREA") or _row_value(row, "LEGAJO") or "").strip()
            bucket = grouped.setdefault(
                sector_oracle,
                {"pallets": 0.0, "hs_clark": 0.0, "pallets_surtido": 0.0, "legajos": set()},
            )
            bucket["pallets"] += _row_float(row, "PALLETS_TOTALES", _row_float(row, "PALLETS"))
            bucket["hs_clark"] += _row_float(row, "HS_CLARK_TOTAL")
            bucket["pallets_surtido"] += _row_float(row, "PALLETS_TOT_SURTIDO")
            if legajo:
                bucket["legajos"].add(legajo)

        result_count = 0
        for sector_oracle, values in grouped.items():
            sector = SECTOR_MAP[sector_oracle]
            pallets = values["pallets"]
            legajos = float(len(values["legajos"]))
            valor = round(pallets / values["hs_clark"] * _productividad_jornada(sector), 2) if values["hs_clark"] else 0.0
            pallets_surtido = values["pallets_surtido"]
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'CLARK', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, CLARK_PARAM_IDS_BY_SECTOR[sector],
                    valor, pallets, legajos,
                ),
            )
            result_count += 1
            for param_map, item_value, item_cantidad, item_legajos in (
                (SPC_REAL_PARAM_IDS_BY_SECTOR, pallets_surtido, pallets_surtido, legajos),
                (CLARK_DOTACION_PARAM_IDS_BY_SECTOR, legajos, legajos, legajos),
            ):
                id_parametro = param_map.get(sector)
                if not id_parametro:
                    continue
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'CLARK', ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                        item_value, item_cantidad, item_legajos,
                    ),
                )
                result_count += 1
        refri_values = [values for sector_oracle, values in grouped.items() if SECTOR_MAP.get(sector_oracle) in REFRIGERADOS_SPLIT_SECTORS]
        if refri_values:
            pallets_surtido = sum(float(values["pallets_surtido"] or 0) for values in refri_values)
            legajos_refri: set[str] = set()
            for values in refri_values:
                legajos_refri.update(values["legajos"])
            legajos = float(len(legajos_refri))
            for id_parametro, valor, cantidad, item_legajos in (
                (SPC_REAL_PARAM_IDS_BY_SECTOR["Refrigerados"], pallets_surtido, pallets_surtido, legajos),
                (CLARK_DOTACION_PARAM_IDS_BY_SECTOR["Refrigerados"], legajos, legajos, legajos),
            ):
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'CLARK', 'Refrigerados', 'REFRIGERADOS', ?, ?, ?, ?, 0)
                    """,
                    (run_id, daily["daily_key"], id_parametro, valor, cantidad, item_legajos),
                )
                result_count += 1
        await db.commit()
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_clark_raw_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'CLARK', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'CLARK'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'CLARK'", (daily["daily_key"],))
        await db.execute("DELETE FROM daily_auto_clark_detalle WHERE daily_key = ?", (daily["daily_key"],))

        result_count = 0
        refri_spc_pallets = 0.0
        refri_spc_legajos_count = 0.0
        refri_spc_legajos_ids: set[str] = set()
        for row in rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            pallets = _row_float(row, "PALLETS_DISTINTOS")
            hs_clark = _row_float(row, "HS_CLARK_TOTAL")
            legajos_clark = _row_float(row, "LEGAJOS_CLARK")
            pallets_spc = _row_float(row, "PALLETS_SPC_DISTINTOS")
            legajos_spc = _row_float(row, "LEGAJOS_SPC")
            productividad = round(pallets / hs_clark * _productividad_jornada(sector), 2) if hs_clark else 0.0
            if sector in REFRIGERADOS_SPLIT_SECTORS:
                refri_spc_pallets += pallets_spc
                ids = _row_value(row, "LEGAJOS_SPC_IDS") or []
                if isinstance(ids, (list, tuple, set)):
                    refri_spc_legajos_ids.update(str(item).strip() for item in ids if str(item).strip())
                else:
                    refri_spc_legajos_count += legajos_spc
            items = [(CLARK_PARAM_IDS_BY_SECTOR[sector], productividad, pallets, legajos_clark)]
            if sector in SPC_REAL_PARAM_IDS_BY_SECTOR:
                items.append((SPC_REAL_PARAM_IDS_BY_SECTOR[sector], pallets_spc, pallets_spc, legajos_spc))
            if sector in CLARK_DOTACION_PARAM_IDS_BY_SECTOR:
                items.append((CLARK_DOTACION_PARAM_IDS_BY_SECTOR[sector], legajos_spc, legajos_spc, legajos_spc))
            for id_parametro, valor, cantidad, legajos in items:
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'CLARK', ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos,
                    ),
                )
                result_count += 1
        if refri_spc_pallets or refri_spc_legajos_ids or refri_spc_legajos_count:
            legajos_spc = float(len(refri_spc_legajos_ids)) if refri_spc_legajos_ids else refri_spc_legajos_count
            for id_parametro, valor, cantidad, legajos in (
                (SPC_REAL_PARAM_IDS_BY_SECTOR["Refrigerados"], refri_spc_pallets, refri_spc_pallets, legajos_spc),
                (CLARK_DOTACION_PARAM_IDS_BY_SECTOR["Refrigerados"], legajos_spc, legajos_spc, legajos_spc),
            ):
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'CLARK', 'Refrigerados', 'REFRIGERADOS', ?, ?, ?, ?, 0)
                    """,
                    (run_id, daily["daily_key"], id_parametro, valor, cantidad, legajos),
                )
                result_count += 1
        await db.commit()
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_picking_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
        if sector_oracle not in SECTOR_MAP:
            continue
        bultos = _row_float(row, "BULTOS_PICKING", _row_float(row, "BULTOS"))
        hs_picking = _row_float(row, "HS_PICKING")
        legajo = str(_row_value(row, "COPECREA") or _row_value(row, "LEGAJO") or "").strip()
        bucket = grouped.setdefault(
            sector_oracle,
            {"bultos": 0.0, "hs_picking": 0.0, "legajos": set()},
        )
        bucket["bultos"] += bultos
        bucket["hs_picking"] += hs_picking
        if legajo:
            bucket["legajos"].add(legajo)
    valid_rows = [
        {
            "ALMACEN": sector_oracle,
            "BULTOS": values["bultos"],
            "LEGAJOS": len(values["legajos"]),
            "PRODUCCION": round(
                values["bultos"] / values["hs_picking"] * _productividad_jornada(SECTOR_MAP.get(sector_oracle, "")),
                2,
            ) if values["hs_picking"] else 0.0,
        }
        for sector_oracle, values in grouped.items()
    ]
    if rows and not valid_rows:
        raise ValueError("La consulta Picking no devolvio filas esperadas con ALMACEN/BULTOS_PICKING/COPECREA.")
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'PICKING', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'PICKING'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'PICKING'", (daily["daily_key"],))

        result_count = 0
        for row in valid_rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            bultos = _row_float(row, "BULTOS")
            legajos = _row_float(row, "LEGAJOS")
            valor = _row_float(row, "PRODUCCION")
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'PICKING', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, PICKING_PARAM_IDS_BY_SECTOR[sector],
                    valor, bultos, legajos,
                ),
            )
            result_count += 1
            for param_map, item_value, item_cantidad, item_legajos in (
                (PICKING_REAL_PARAM_IDS_BY_SECTOR, bultos, bultos, legajos),
                (PICKING_DOTACION_PARAM_IDS_BY_SECTOR, legajos, legajos, legajos),
            ):
                id_parametro = param_map.get(sector)
                if not id_parametro:
                    continue
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'PICKING', ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                        item_value, item_cantidad, item_legajos,
                    ),
                )
                result_count += 1
        refri_values = [values for sector_oracle, values in grouped.items() if SECTOR_MAP.get(sector_oracle) in REFRIGERADOS_SPLIT_SECTORS]
        if refri_values:
            bultos = sum(float(values["bultos"] or 0) for values in refri_values)
            legajos_refri: set[str] = set()
            for values in refri_values:
                legajos_refri.update(values["legajos"])
            legajos = float(len(legajos_refri))
            for id_parametro, valor, cantidad, item_legajos in (
                (PICKING_REAL_PARAM_IDS_BY_SECTOR["Refrigerados"], bultos, bultos, legajos),
                (PICKING_DOTACION_PARAM_IDS_BY_SECTOR["Refrigerados"], legajos, legajos, legajos),
            ):
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'PICKING', 'Refrigerados', 'REFRIGERADOS', ?, ?, ?, ?, 0)
                    """,
                    (run_id, daily["daily_key"], id_parametro, valor, cantidad, item_legajos),
                )
                result_count += 1
        await db.commit()
    if rows and result_count == 0:
        raise ValueError("La consulta Picking no genero resultados para sectores habilitados.")
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_recepcion_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    valid_rows = []
    for row in rows:
        if _row_value(row, "ALMACEN") is not None and _row_value(row, "PALLETS") is not None:
            valid_rows.append(row)
    if rows and not valid_rows:
        raise ValueError("La consulta Recepcion no devolvio filas agregadas esperadas (ALMACEN/PALLETS).")
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'RECEPCION', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'RECEPCION'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'RECEPCION'", (daily["daily_key"],))

        result_count = 0
        for row in valid_rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            pallets = float(_row_value(row, "PALLETS") or 0)
            legajos = float(_row_value(row, "LEGAJOS") or 0)
            valor = float(_row_value(row, "PRODUCCION") or 0)
            for id_parametro, item_value in (
                (RECEPCION_PARAM_IDS_BY_SECTOR[sector], valor),
                (RECEPCION_REAL_PARAM_IDS_BY_SECTOR[sector], pallets),
                (RECEPCION_DOTACION_PARAM_IDS_BY_SECTOR[sector], legajos),
            ):
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'RECEPCION', ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                        item_value, pallets, legajos,
                    ),
                )
                result_count += 1
        await db.commit()
    if rows and result_count == 0:
        raise ValueError("La consulta Recepcion no genero resultados para sectores habilitados.")
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_despacho_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    valid_rows = []
    for row in rows:
        if _row_value(row, "ALMACEN") is not None and _row_value(row, "VIAJES") is not None:
            valid_rows.append(row)
    if rows and not valid_rows:
        raise ValueError("La consulta Despacho no devolvio filas agregadas esperadas (ALMACEN/VIAJES).")
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'DESPACHO', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'DESPACHO'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'DESPACHO'", (daily["daily_key"],))

        result_count = 0
        for row in valid_rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            viajes = float(_row_value(row, "VIAJES") or 0)
            cargadores = float(_row_value(row, "CARGADORES") or _row_value(row, "LEGAJOS") or 0)
            valor = float(_row_value(row, "PRODUCCION") or 0)
            items: list[tuple[str, float]] = [
                (DESPACHO_REAL_PARAM_IDS_BY_SECTOR[sector], viajes),
                (DESPACHO_DOTACION_PARAM_IDS_BY_SECTOR[sector], cargadores),
            ]
            if sector in DESPACHO_PARAM_IDS_BY_SECTOR:
                items.insert(0, (DESPACHO_PARAM_IDS_BY_SECTOR[sector], valor))
            for id_parametro, item_value in items:
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'DESPACHO', ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                        item_value, viajes, cargadores,
                    ),
                )
                result_count += 1
        await db.commit()
    if rows and result_count == 0:
        raise ValueError("La consulta Despacho no genero resultados para sectores habilitados.")
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_planificacion_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    valid_rows = []
    for row in rows:
        if _row_value(row, "ALMACEN") is not None and _row_value(row, "VIAJES_PLANIFICADOS") is not None:
            valid_rows.append(row)
    if rows and not valid_rows:
        raise ValueError("La consulta Planificacion no devolvio filas agregadas esperadas (ALMACEN/VIAJES_PLANIFICADOS).")
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'PLANIFICACION', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], daily["fecha_inicio"], daily["fecha_fin"],
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'PLANIFICACION'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'PLANIFICACION'", (daily["daily_key"],))

        result_count = 0
        for row in valid_rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            if not sector:
                continue
            viajes = float(_row_value(row, "VIAJES_PLANIFICADOS") or 0)
            bultos_picking = float(_row_value(row, "BULTOS_PICKING_PLANIFICADOS") or 0)
            pallets_picking = float(_row_value(row, "PALLETS_PICKING_PLANIFICADOS") or 0)
            pallets_spc = float(_row_value(row, "PALLETS_SPC_PLANIFICADOS") or 0)
            bultos_spc = float(_row_value(row, "BULTOS_SPC_PLANIFICADOS") or 0)
            items = [
                (PICKING_PLAN_PARAM_IDS_BY_SECTOR[sector], bultos_picking, bultos_picking, pallets_picking),
                (SPC_PLAN_PARAM_IDS_BY_SECTOR[sector], pallets_spc, pallets_spc, bultos_spc),
                (DESPACHO_PLAN_PARAM_IDS_BY_SECTOR[sector], viajes, viajes, 0),
            ]
            for id_parametro, valor, cantidad, details_count in items:
                await db.execute(
                    """
                    INSERT INTO daily_auto_resultados (
                        run_id, daily_key, process, sector, sector_oracle, id_parametro,
                        valor, cantidad, legajos, details_count
                    ) VALUES (?, ?, 'PLANIFICACION', ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                        valor, cantidad, int(details_count or 0),
                    ),
                )
                result_count += 1
        await db.commit()
    if rows and result_count == 0:
        raise ValueError("La consulta Planificacion no genero resultados para sectores habilitados.")
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def save_avance_summary_cache(
    daily: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    avance_inicio: str,
    avance_fin: str,
    started_at: str,
    duration_ms: float,
    timings: dict[str, Any] | None = None,
    trigger: str = "scheduler",
    usuario: str = "",
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")
        await db.execute(
            """
            INSERT INTO daily_auto_runs (
                daily_key, daily_label, fecha_inicio, fecha_fin, fecha_carga,
                process, status, started_at, finished_at, duration_ms,
                row_count, timings_json, error, run_trigger, usuario, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'AVANCE', 'success', ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(daily_key, process) DO UPDATE SET
                daily_label = excluded.daily_label,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                fecha_carga = excluded.fecha_carga,
                status = 'success',
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                row_count = excluded.row_count,
                timings_json = excluded.timings_json,
                error = NULL,
                run_trigger = excluded.run_trigger,
                usuario = excluded.usuario,
                updated_at = excluded.updated_at
            """,
            (
                daily["daily_key"], daily["daily_label"], avance_inicio, avance_fin,
                daily["fecha_carga"], started_at, now, duration_ms, len(rows),
                json.dumps(timings or {}, ensure_ascii=False), trigger, usuario, now,
            ),
        )
        async with db.execute(
            "SELECT id FROM daily_auto_runs WHERE daily_key = ? AND process = 'AVANCE'",
            (daily["daily_key"],),
        ) as cur:
            run_row = await cur.fetchone()
        run_id = int(run_row[0])
        await db.execute("DELETE FROM daily_auto_resultados WHERE daily_key = ? AND process = 'AVANCE'", (daily["daily_key"],))

        result_count = 0
        for row in rows:
            sector_oracle = str(_row_value(row, "ALMACEN") or "").strip().upper()
            sector = SECTOR_MAP.get(sector_oracle)
            proceso = str(_row_value(row, "PROCESO") or "").strip().upper()
            tipo = str(_row_value(row, "TIPO") or "").strip().upper()
            id_parametro = AVANCE_PARAM_IDS.get((proceso, tipo))
            if not sector or not id_parametro:
                continue
            valor = _row_float(row, "VALOR")
            await db.execute(
                """
                INSERT INTO daily_auto_resultados (
                    run_id, daily_key, process, sector, sector_oracle, id_parametro,
                    valor, cantidad, legajos, details_count
                ) VALUES (?, ?, 'AVANCE', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id, daily["daily_key"], sector, sector_oracle, id_parametro,
                    valor, valor, _row_float(row, "LEGAJOS"),
                ),
            )
            result_count += 1
        await db.commit()
    return {"run_id": run_id, "rows": len(rows), "resultados": result_count}


async def get_latest_run(daily_key: str, process: str = "CLARK") -> dict[str, Any] | None:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT *
            FROM daily_auto_runs
            WHERE daily_key = ? AND process = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (daily_key, process),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_cached_results(daily_key: str) -> list[dict[str, Any]]:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT r.*, run.status, run.finished_at, run.duration_ms
            FROM daily_auto_resultados r
            JOIN daily_auto_runs run ON run.id = r.run_id
            WHERE r.daily_key = ? AND r.process IN ('CLARK', 'PICKING', 'RECEPCION', 'DESPACHO', 'PLANIFICACION', 'AVANCE') AND run.status = 'success'
            ORDER BY r.sector, r.process
            """,
            (daily_key,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def replace_daily_manual_comparacion_rows(
    rows: list[dict[str, Any]],
    *,
    source_file: str,
    fecha_desde: str,
    fecha_hasta: str,
) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute(
            """
            DELETE FROM daily_manual_comparacion
            WHERE source_file = ?
              AND fecha_daily >= ?
              AND fecha_daily <= ?
            """,
            (source_file, fecha_desde, fecha_hasta),
        )
        for row in rows:
            await db.execute(
                """
                INSERT OR REPLACE INTO daily_manual_comparacion (
                    source_file, source_row, concepto, fecha_daily, daily_key,
                    sector, up, metrica, operacion, id_parametro, valor_manual,
                    imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_file,
                    int(row["source_row"]),
                    row["concepto"],
                    row["fecha_daily"],
                    row["daily_key"],
                    row["sector"],
                    row["up"],
                    row["metrica"],
                    row["operacion"],
                    row["id_parametro"],
                    row.get("valor_manual"),
                    now,
                ),
            )
        await db.commit()
    return {"rows": len(rows), "source_file": source_file, "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta}


async def rebuild_daily_auto_manual_comparacion(fecha_desde: str, fecha_hasta: str) -> dict[str, Any]:
    await init_daily_auto_db()
    now = _now_text()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute(
            "DELETE FROM daily_auto_manual_comparacion WHERE fecha_daily >= ? AND fecha_daily <= ?",
            (fecha_desde, fecha_hasta),
        )
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                m.*,
                a.valor AS valor_automatico
            FROM daily_manual_comparacion m
            LEFT JOIN daily_auto_resultados a
              ON a.daily_key = m.daily_key
             AND a.sector = m.sector
             AND a.id_parametro = m.id_parametro
            WHERE m.fecha_daily >= ?
              AND m.fecha_daily <= ?
            """,
            (fecha_desde, fecha_hasta),
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
        inserted = 0
        for row in rows:
            manual = _row_float(row, "valor_manual", None) if row.get("valor_manual") is not None else None
            automatico = _row_float(row, "valor_automatico", None) if row.get("valor_automatico") is not None else None
            if manual is None and automatico is None:
                diferencia = diferencia_abs = diferencia_pct = None
                estado = "sin_datos"
            elif manual is None:
                diferencia = diferencia_abs = diferencia_pct = None
                estado = "sin_manual"
            elif automatico is None:
                diferencia = diferencia_abs = diferencia_pct = None
                estado = "sin_automatico"
            else:
                diferencia = automatico - manual
                diferencia_abs = abs(diferencia)
                diferencia_pct = (diferencia / manual) if manual else None
                if diferencia_abs <= 0.01:
                    estado = "coincide"
                elif diferencia_pct is not None and abs(diferencia_pct) >= 0.2:
                    estado = "critica"
                elif diferencia_pct is not None and abs(diferencia_pct) >= 0.05:
                    estado = "relevante"
                else:
                    estado = "menor"
            await db.execute(
                """
                INSERT OR REPLACE INTO daily_auto_manual_comparacion (
                    daily_key, fecha_daily, sector, up, metrica, operacion,
                    concepto, id_parametro, valor_manual, valor_automatico,
                    diferencia, diferencia_abs, diferencia_pct, estado,
                    source_file, source_row, compared_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["daily_key"], row["fecha_daily"], row["sector"], row["up"], row["metrica"], row["operacion"],
                    row["concepto"], row["id_parametro"], manual, automatico,
                    diferencia, diferencia_abs, diferencia_pct, estado,
                    row["source_file"], row["source_row"], now,
                ),
            )
            inserted += 1
        await db.commit()
    return {"rows": inserted, "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta}


async def get_daily_auto_manual_comparacion(fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT *
            FROM daily_auto_manual_comparacion
            WHERE fecha_daily >= ?
              AND fecha_daily <= ?
            ORDER BY diferencia_abs DESC, fecha_daily DESC, sector, operacion, metrica
            """,
            (fecha_desde, fecha_hasta),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_cached_clark_detail(daily_key: str, sector: str) -> list[dict[str, Any]]:
    await init_daily_auto_db()
    async with aiosqlite.connect(DAILY_AUTO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT almacen, legajo, nombre, fecha, pallet, operacion
            FROM daily_auto_clark_detalle
            WHERE daily_key = ? AND sector = ?
            ORDER BY legajo, fecha, pallet
            """,
            (daily_key, sector),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]
