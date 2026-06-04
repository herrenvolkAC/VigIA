"""
Base SQLite independiente para el modulo Panol Insumos.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from db.paths import ROOT_DIR, resolve_db_path


PANOL_DB_PATH = resolve_db_path("PANOL_INSUMOS_DB_PATH", "panol_insumos.db", ROOT_DIR)


CREATE_ARTICULOS = """
CREATE TABLE IF NOT EXISTS articulos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE NOT NULL,
    descripcion TEXT NOT NULL,
    categoria TEXT,
    unidad TEXT DEFAULT 'UN',
    stock_minimo REAL DEFAULT 0,
    activo INTEGER DEFAULT 1,
    creado_en TEXT,
    actualizado_en TEXT
);
"""

CREATE_UBICACIONES = """
CREATE TABLE IF NOT EXISTS ubicaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE,
    descripcion TEXT,
    activo INTEGER DEFAULT 1
);
"""

CREATE_TURNOS = """
CREATE TABLE IF NOT EXISTS turnos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE NOT NULL,
    descripcion TEXT,
    activo INTEGER DEFAULT 1
);
"""

CREATE_MOVIMIENTOS = """
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    articulo_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    ubicacion_origen_id INTEGER,
    ubicacion_destino_id INTEGER,
    cantidad REAL NOT NULL,
    motivo TEXT,
    observacion TEXT,
    usuario TEXT,
    fecha_hora TEXT,
    FOREIGN KEY (articulo_id) REFERENCES articulos(id),
    FOREIGN KEY (ubicacion_origen_id) REFERENCES ubicaciones(id),
    FOREIGN KEY (ubicacion_destino_id) REFERENCES ubicaciones(id)
);
"""

CREATE_STOCK_CD = """
CREATE TABLE IF NOT EXISTS stock_cd_importado (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    articulo_id INTEGER NOT NULL,
    stock_cd REAL NOT NULL,
    fecha_reporte TEXT,
    archivo_origen TEXT,
    usuario_importacion TEXT,
    fecha_importacion TEXT,
    FOREIGN KEY (articulo_id) REFERENCES articulos(id)
);
"""

CREATE_INVENTARIO = """
CREATE TABLE IF NOT EXISTS inventario_turno (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    articulo_id INTEGER NOT NULL,
    ubicacion_id INTEGER,
    turno TEXT NOT NULL,
    fecha TEXT NOT NULL,
    stock_fisico REAL NOT NULL,
    usuario TEXT,
    fecha_hora TEXT,
    observacion TEXT,
    FOREIGN KEY (articulo_id) REFERENCES articulos(id),
    FOREIGN KEY (ubicacion_id) REFERENCES ubicaciones(id)
);
"""

CREATE_CONSUMOS = """
CREATE TABLE IF NOT EXISTS consumos_calculados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    articulo_id INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    turno TEXT NOT NULL,
    stock_inicial REAL NOT NULL,
    ingresos_turno REAL NOT NULL,
    stock_final REAL NOT NULL,
    consumo_calculado REAL NOT NULL,
    usuario TEXT,
    fecha_hora TEXT,
    inventario_id INTEGER,
    FOREIGN KEY (articulo_id) REFERENCES articulos(id),
    FOREIGN KEY (inventario_id) REFERENCES inventario_turno(id)
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_articulos_codigo ON articulos(codigo)",
    "CREATE INDEX IF NOT EXISTS idx_movimientos_articulo_fecha ON movimientos(articulo_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_movimientos_origen ON movimientos(ubicacion_origen_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_movimientos_destino ON movimientos(ubicacion_destino_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_stock_cd_articulo_fecha ON stock_cd_importado(articulo_id, fecha_importacion)",
    "CREATE INDEX IF NOT EXISTS idx_inventario_articulo_fecha ON inventario_turno(articulo_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_consumos_articulo_fecha ON consumos_calculados(articulo_id, fecha_hora)",
]


async def init_panol_db() -> None:
    PANOL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(PANOL_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        for stmt in (
            CREATE_ARTICULOS,
            CREATE_UBICACIONES,
            CREATE_TURNOS,
            CREATE_MOVIMIENTOS,
            CREATE_STOCK_CD,
            CREATE_INVENTARIO,
            CREATE_CONSUMOS,
        ):
            await db.execute(stmt)
        for stmt in INDEXES:
            await db.execute(stmt)
        await _ensure_column(db, "inventario_turno", "ubicacion_id", "INTEGER")
        await db.executemany(
            """
            INSERT OR IGNORE INTO ubicaciones (codigo, descripcion, activo)
            VALUES (?, ?, 1)
            """,
            [
                ("JAULA", "Jaula",),
                ("OFICINA_ADO", "Oficina ADO",),
            ],
        )
        await db.executemany(
            """
            INSERT OR IGNORE INTO turnos (codigo, descripcion, activo)
            VALUES (?, ?, 1)
            """,
            [
                ("MANANA", "Manana",),
                ("TARDE", "Tarde",),
                ("NOCHE", "Noche",),
            ],
        )
        await db.execute(
            """
            UPDATE inventario_turno
            SET ubicacion_id = (SELECT id FROM ubicaciones WHERE codigo = 'OFICINA_ADO')
            WHERE ubicacion_id IS NULL
            """
        )
        await db.commit()


async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, definition: str) -> None:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        columns = {row[1] for row in await cur.fetchall()}
    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def connect_panol_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(PANOL_DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA busy_timeout = 10000")
    await db.execute("PRAGMA foreign_keys = ON")
    return db


@asynccontextmanager
async def panol_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await connect_panol_db()
    try:
        yield db
    finally:
        await db.close()
