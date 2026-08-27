"""Base local de staging para el estudio histórico de productividad."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from db.paths import ROOT_DIR, resolve_db_path


ANALISIS_PRODUCTIVIDAD_DB_PATH = resolve_db_path(
    "ANALISIS_PRODUCTIVIDAD_DB_PATH", "analisis_productividad.db", ROOT_DIR
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_carga_lote (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL UNIQUE,
    fecha_desde TEXT NOT NULL,
    fecha_hasta TEXT NOT NULL,
    operacion TEXT NOT NULL,
    grupo_productivo INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL,
    filas INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL,
    finalizado_en TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS ap_tendencia_mensual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    operacion TEXT NOT NULL,
    grupo_productivo INTEGER NOT NULL DEFAULT 0,
    mes INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    cargado_en TEXT NOT NULL,
    UNIQUE(operacion, grupo_productivo, mes)
);
CREATE INDEX IF NOT EXISTS ix_ap_tendencia_scope
    ON ap_tendencia_mensual(operacion, grupo_productivo, mes);
CREATE TABLE IF NOT EXISTS ap_fuente_catalogo (
    tabla TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL,
    alcance TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);
"""


async def init_analisis_productividad_db() -> None:
    ANALISIS_PRODUCTIVIDAD_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(ANALISIS_PRODUCTIVIDAD_DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


def tendencia_row_payload(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, default=str)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
