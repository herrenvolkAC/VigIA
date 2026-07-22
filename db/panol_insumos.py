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
    uso TEXT,
    stock_minimo REAL DEFAULT 0,
    activo INTEGER DEFAULT 1,
    creado_en TEXT,
    actualizado_en TEXT
);
"""

CREATE_ARTICULOS_COSTOS = """
CREATE TABLE IF NOT EXISTS articulos_costos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    articulo_id INTEGER NOT NULL,
    costo_unitario REAL NOT NULL,
    moneda TEXT DEFAULT 'ARS',
    fecha_desde TEXT NOT NULL,
    fecha_hasta TEXT,
    fuente TEXT,
    usuario TEXT,
    fecha_hora TEXT,
    FOREIGN KEY (articulo_id) REFERENCES articulos(id)
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

CREATE_PRODUCCION_MOVIMIENTOS = """
CREATE TABLE IF NOT EXISTS produccion_movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    articulo_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    ubicacion_destino_id INTEGER,
    cantidad REAL NOT NULL,
    turno TEXT NOT NULL,
    observacion TEXT,
    usuario TEXT,
    fecha_hora TEXT,
    FOREIGN KEY (articulo_id) REFERENCES articulos(id),
    FOREIGN KEY (ubicacion_destino_id) REFERENCES ubicaciones(id)
);
"""

CREATE_PEDIDOS_INSUMOS = """
CREATE TABLE IF NOT EXISTS pedidos_insumos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_id INTEGER NOT NULL,
    estado TEXT NOT NULL,
    usuario_solicita TEXT,
    fecha_solicitud TEXT,
    observacion_solicitud TEXT,
    usuario_confirma TEXT,
    fecha_confirmacion TEXT,
    observacion_confirmacion TEXT,
    FOREIGN KEY (sector_id) REFERENCES ubicaciones(id)
);
"""

CREATE_PEDIDOS_INSUMOS_ITEMS = """
CREATE TABLE IF NOT EXISTS pedidos_insumos_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL,
    articulo_id INTEGER NOT NULL,
    cantidad_insumo_solicitada REAL DEFAULT 0,
    cantidad_produccion_solicitada REAL DEFAULT 0,
    cantidad_insumo_confirmada REAL DEFAULT 0,
    cantidad_produccion_confirmada REAL DEFAULT 0,
    ubicacion_origen_insumo_id INTEGER,
    uso_entrega TEXT,
    FOREIGN KEY (pedido_id) REFERENCES pedidos_insumos(id),
    FOREIGN KEY (articulo_id) REFERENCES articulos(id),
    FOREIGN KEY (ubicacion_origen_insumo_id) REFERENCES ubicaciones(id)
);
"""

CREATE_MERMAS_INSUMOS = """
CREATE TABLE IF NOT EXISTS mermas_insumos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_id INTEGER NOT NULL,
    pedido_id INTEGER,
    articulo_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    cantidad REAL NOT NULL,
    motivo TEXT NOT NULL,
    observacion TEXT NOT NULL,
    usuario TEXT,
    fecha_hora TEXT,
    FOREIGN KEY (sector_id) REFERENCES ubicaciones(id),
    FOREIGN KEY (pedido_id) REFERENCES pedidos_insumos(id),
    FOREIGN KEY (articulo_id) REFERENCES articulos(id)
);
"""

CREATE_USUARIOS_SECTORES = """
CREATE TABLE IF NOT EXISTS usuarios_sectores_panol (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    sector_id INTEGER NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_por TEXT,
    fecha_hora TEXT,
    actualizado_por TEXT,
    actualizado_en TEXT,
    FOREIGN KEY (sector_id) REFERENCES ubicaciones(id)
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_articulos_codigo ON articulos(codigo)",
    "CREATE INDEX IF NOT EXISTS idx_articulos_costos_articulo_fecha ON articulos_costos(articulo_id, fecha_desde, fecha_hasta)",
    "CREATE INDEX IF NOT EXISTS idx_movimientos_articulo_fecha ON movimientos(articulo_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_movimientos_origen ON movimientos(ubicacion_origen_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_movimientos_destino ON movimientos(ubicacion_destino_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_stock_cd_articulo_fecha ON stock_cd_importado(articulo_id, fecha_importacion)",
    "CREATE INDEX IF NOT EXISTS idx_inventario_articulo_fecha ON inventario_turno(articulo_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_consumos_articulo_fecha ON consumos_calculados(articulo_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_produccion_articulo_fecha ON produccion_movimientos(articulo_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_produccion_destino_fecha ON produccion_movimientos(ubicacion_destino_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_produccion_turno_fecha ON produccion_movimientos(turno, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_pedidos_estado_fecha ON pedidos_insumos(estado, fecha_solicitud)",
    "CREATE INDEX IF NOT EXISTS idx_pedidos_usuario_fecha ON pedidos_insumos(usuario_solicita, fecha_solicitud)",
    "CREATE INDEX IF NOT EXISTS idx_pedidos_items_pedido ON pedidos_insumos_items(pedido_id)",
    "CREATE INDEX IF NOT EXISTS idx_pedidos_items_articulo ON pedidos_insumos_items(articulo_id)",
    "CREATE INDEX IF NOT EXISTS idx_mermas_sector_fecha ON mermas_insumos(sector_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_mermas_articulo_fecha ON mermas_insumos(articulo_id, fecha_hora)",
    "CREATE INDEX IF NOT EXISTS idx_mermas_pedido ON mermas_insumos(pedido_id)",
    "CREATE INDEX IF NOT EXISTS idx_usuarios_sectores_panol_user ON usuarios_sectores_panol(username, activo)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_usuarios_sectores_panol_user_activo ON usuarios_sectores_panol(username) WHERE activo = 1",
]


async def init_panol_db() -> None:
    PANOL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(PANOL_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")
        for stmt in (
            CREATE_ARTICULOS,
            CREATE_ARTICULOS_COSTOS,
            CREATE_UBICACIONES,
            CREATE_TURNOS,
            CREATE_MOVIMIENTOS,
            CREATE_STOCK_CD,
            CREATE_INVENTARIO,
            CREATE_CONSUMOS,
            CREATE_PRODUCCION_MOVIMIENTOS,
            CREATE_PEDIDOS_INSUMOS,
            CREATE_PEDIDOS_INSUMOS_ITEMS,
            CREATE_MERMAS_INSUMOS,
            CREATE_USUARIOS_SECTORES,
        ):
            await db.execute(stmt)
        for stmt in INDEXES:
            await db.execute(stmt)
        await _ensure_column(db, "inventario_turno", "ubicacion_id", "INTEGER")
        await _ensure_column(db, "articulos", "uso", "TEXT")
        await _ensure_column(db, "pedidos_insumos_items", "uso_entrega", "TEXT")
        await db.executemany(
            """
            INSERT OR IGNORE INTO ubicaciones (codigo, descripcion, activo)
            VALUES (?, ?, 1)
            """,
            [
                ("JAULA", "Jaula",),
                ("Envíos a Domicilio", "Envíos a Domicilio",),
                ("Noa", "Noa",),
                ("OFICINA_ADO", "Oficina ADO",),
                ("Refrigerados", "Refrigerados",),
                ("Secos", "Secos",),
                ("Sector 126", "Sector 126",),
                ("Sucursales", "Sucursales",),
            ],
        )
        envios = "Env\u00edos a Domicilio"
        await db.execute(
            """
            INSERT OR IGNORE INTO ubicaciones (codigo, descripcion, activo)
            VALUES (?, ?, 1)
            """,
            (envios, envios),
        )
        await db.execute(
            """
            UPDATE ubicaciones
            SET activo = 0
            WHERE codigo LIKE 'Env%os a Domicilio'
              AND codigo <> ?
            """,
            (envios,),
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
