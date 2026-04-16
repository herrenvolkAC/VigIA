"""
VigIA · db/schema.py
Definición de tablas SQLite y conexión con aiosqlite.
"""
import aiosqlite
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "vigia.db"

CREATE_TURNOS = """
CREATE TABLE IF NOT EXISTS turnos (
    turno_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha        DATE,
    turno        TEXT,
    programa_num TEXT,
    objetivo_total INTEGER,
    dotacion_real  INTEGER,
    total_real     INTEGER,
    cerrado        BOOLEAN DEFAULT 0,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_MOVIMIENTOS = """
CREATE TABLE IF NOT EXISTS movimientos (
    mov_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    turno_id          INTEGER REFERENCES turnos(turno_id),
    hora              TIME,
    sector            TEXT,
    bultos_programados INTEGER,
    bultos_ejecutados  INTEGER,
    dotacion_prog      INTEGER,
    dotacion_ejec      INTEGER,
    prod_prog          REAL,
    prod_ejec          REAL,
    observaciones      TEXT,
    ola_num            INTEGER
);
"""

CREATE_PREDICCIONES = """
CREATE TABLE IF NOT EXISTS predicciones (
    pred_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    turno_id    INTEGER REFERENCES turnos(turno_id),
    hora_pred   TIME,
    valor_pred  INTEGER,
    ic_bajo     INTEGER,
    ic_alto     INTEGER,
    confianza   REAL,
    factor_top  TEXT,
    modelo_ver  TEXT,
    proveedor_ia TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_MODELOS = """
CREATE TABLE IF NOT EXISTS modelos (
    modelo_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    version        TEXT,
    fecha_entreno  DATETIME,
    turnos_usados  INTEGER,
    mae            REAL,
    activo         BOOLEAN DEFAULT 0,
    archivo        TEXT,
    notas          TEXT
);
"""


async def init_db():
    """Crea las tablas si no existen."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TURNOS)
        await db.execute(CREATE_MOVIMIENTOS)
        await db.execute(CREATE_PREDICCIONES)
        await db.execute(CREATE_MODELOS)
        await db.commit()
    print(f"[DB] Base de datos inicializada: {DB_PATH}")


async def get_db():
    """Context manager para obtener una conexión."""
    return aiosqlite.connect(DB_PATH)
