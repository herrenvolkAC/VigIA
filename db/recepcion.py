"""Base SQLite independiente del modulo Recepcion."""
from __future__ import annotations

import aiosqlite

from db.paths import ROOT_DIR, resolve_db_path


RECEPCION_DB_PATH = resolve_db_path("VIGIA_RECEPCION_DB_PATH", "recepcion.db", ROOT_DIR)

CREATE_RECEPCIONES = """
CREATE TABLE IF NOT EXISTS recepciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_descarga TEXT NOT NULL,
    proveedor_codigo TEXT NOT NULL,
    proveedor_nombre TEXT NOT NULL,
    recepcionista_legajo TEXT NOT NULL,
    recepcionista_nombre TEXT NOT NULL,
    pallets_recibidos INTEGER NOT NULL,
    pallets_auditados INTEGER NOT NULL,
    cuenta_con_novedad INTEGER NOT NULL DEFAULT 0,
    observacion TEXT,
    creado_por TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RECEPCION_PLUS = """
CREATE TABLE IF NOT EXISTS recepcion_plus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recepcion_id INTEGER NOT NULL REFERENCES recepciones(id) ON DELETE CASCADE,
    plu_codigo TEXT NOT NULL,
    plu_articulo TEXT NOT NULL,
    afectacion REAL,
    observacion TEXT
);
"""

CREATE_RECEPCION_FOTOS = """
CREATE TABLE IF NOT EXISTS recepcion_fotos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recepcion_id INTEGER NOT NULL REFERENCES recepciones(id) ON DELETE CASCADE,
    nombre_original TEXT NOT NULL,
    nombre_archivo TEXT NOT NULL,
    ruta_archivo TEXT NOT NULL,
    tipo_mime TEXT,
    tamano_bytes INTEGER NOT NULL DEFAULT 0,
    creado_por TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RECEPCION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_recepciones_fecha ON recepciones(fecha_descarga)",
    "CREATE INDEX IF NOT EXISTS idx_recepciones_proveedor ON recepciones(proveedor_codigo)",
    "CREATE INDEX IF NOT EXISTS idx_recepciones_recepcionista ON recepciones(recepcionista_legajo)",
    "CREATE INDEX IF NOT EXISTS idx_recepcion_plus_recepcion ON recepcion_plus(recepcion_id)",
    "CREATE INDEX IF NOT EXISTS idx_recepcion_plus_plu ON recepcion_plus(plu_codigo)",
    "CREATE INDEX IF NOT EXISTS idx_recepcion_fotos_recepcion ON recepcion_fotos(recepcion_id)",
]


async def init_recepcion_db() -> None:
    RECEPCION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(RECEPCION_DB_PATH) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 60000")
        await db.execute(CREATE_RECEPCIONES)
        await db.execute(CREATE_RECEPCION_PLUS)
        await db.execute(CREATE_RECEPCION_FOTOS)
        for statement in CREATE_RECEPCION_INDEXES:
            await db.execute(statement)
        await db.commit()


async def migrate_legacy_recepcion_db(legacy_db_path) -> int:
    """Copia una vez los registros creados en la base operativa anterior."""
    if str(legacy_db_path) == str(RECEPCION_DB_PATH) or not legacy_db_path.exists():
        return 0
    await init_recepcion_db()
    async with aiosqlite.connect(legacy_db_path) as legacy, aiosqlite.connect(RECEPCION_DB_PATH) as target:
        legacy.row_factory = aiosqlite.Row
        target.row_factory = aiosqlite.Row
        try:
            async with legacy.execute("SELECT * FROM recepciones ORDER BY id") as cur:
                rows = await cur.fetchall()
        except Exception:
            return 0
        migrated = 0
        for row in rows:
            async with target.execute("SELECT 1 FROM recepciones WHERE id=?", (row["id"],)) as cur:
                if await cur.fetchone():
                    continue
            await target.execute("""INSERT INTO recepciones
                (id,fecha_descarga,proveedor_codigo,proveedor_nombre,recepcionista_legajo,recepcionista_nombre,
                 pallets_recibidos,pallets_auditados,cuenta_con_novedad,observacion,creado_por,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", tuple(row))
            async with legacy.execute("SELECT * FROM recepcion_plus WHERE recepcion_id=?", (row["id"],)) as cur:
                for item in await cur.fetchall():
                    await target.execute("INSERT INTO recepcion_plus (id,recepcion_id,plu_codigo,plu_articulo,afectacion,observacion) VALUES (?,?,?,?,?,?)", tuple(item))
            async with legacy.execute("SELECT * FROM recepcion_fotos WHERE recepcion_id=?", (row["id"],)) as cur:
                for item in await cur.fetchall():
                    await target.execute("""INSERT INTO recepcion_fotos
                        (id,recepcion_id,nombre_original,nombre_archivo,ruta_archivo,tipo_mime,tamano_bytes,creado_por,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?)""", tuple(item))
            migrated += 1
        await target.commit()
        return migrated
