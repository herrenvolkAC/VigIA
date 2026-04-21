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

# ============================================================================
# FASE 1: ALARMAS + PRODUCTIVIDAD (20-30 abril)
# ============================================================================

CREATE_OLAS = """
CREATE TABLE IF NOT EXISTS olas (
    ola_id                VARCHAR(50) PRIMARY KEY,
    turno_id              INTEGER REFERENCES turnos(turno_id),
    numero_ola            INTEGER,
    zona                  VARCHAR(20),
    hora_inicio           TIME,
    hora_fin              TIME,
    bultos_programados    INTEGER,
    bultos_ejecutados     INTEGER DEFAULT 0,
    estado                VARCHAR(20),
    operarios_asignados   INTEGER,
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_OPERARIOS = """
CREATE TABLE IF NOT EXISTS operarios (
    operario_id      VARCHAR(20) PRIMARY KEY,
    nombre           VARCHAR(100),
    zona_principal   VARCHAR(20),
    fecha_union      DATE,
    estado           VARCHAR(20),
    especialidad     VARCHAR(50),
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_ASIGNACIONES_OLA = """
CREATE TABLE IF NOT EXISTS asignaciones_ola (
    asignacion_id       VARCHAR(50) PRIMARY KEY,
    ola_id              VARCHAR(50) REFERENCES olas(ola_id),
    operario_id         VARCHAR(20) REFERENCES operarios(operario_id),
    zona                VARCHAR(20),
    bultos_programados  INTEGER,
    bultos_reales       INTEGER DEFAULT 0,
    tiempo_minutos      INTEGER,
    productividad       FLOAT,
    estado              VARCHAR(20),
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_ESTANDARES_SECTOR = """
CREATE TABLE IF NOT EXISTS estandares_sector (
    estandar_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sector                 VARCHAR(20),
    bultos_por_hora        INTEGER,
    bultos_turno_total     INTEGER,
    efectivo_desde         DATE,
    actualizado_por        VARCHAR(50),
    actualizado_en         DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_HISTORICO_OLAS = """
CREATE TABLE IF NOT EXISTS historico_olas (
    historico_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha                 DATE,
    ola_numero            INTEGER,
    turno                 VARCHAR(20),
    zona                  VARCHAR(20),
    productividad_promedio FLOAT,
    bultos_ejecutados     INTEGER,
    operarios_count       INTEGER,
    dia_semana            INTEGER,
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_db():
    """Crea las tablas si no existen."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Tablas existentes
        await db.execute(CREATE_TURNOS)
        await db.execute(CREATE_MOVIMIENTOS)
        await db.execute(CREATE_PREDICCIONES)
        await db.execute(CREATE_MODELOS)

        # Tablas FASE 1: Alarmas + Productividad
        await db.execute(CREATE_OLAS)
        await db.execute(CREATE_OPERARIOS)
        await db.execute(CREATE_ASIGNACIONES_OLA)
        await db.execute(CREATE_ESTANDARES_SECTOR)
        await db.execute(CREATE_HISTORICO_OLAS)

        await db.commit()
    print(f"[DB] Base de datos inicializada: {DB_PATH}")
    print(f"[DB] OK - Tablas FASE 1 creadas: olas, operarios, asignaciones_ola, estandares_sector, historico_olas")


async def get_db():
    """Context manager para obtener una conexión."""
    return aiosqlite.connect(DB_PATH)
