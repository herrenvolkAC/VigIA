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

CREATE_PRODUCTIVIDAD_ANALISIS_RUNS = """
CREATE TABLE IF NOT EXISTS productividad_analisis_runs (
    run_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    rango_key             TEXT NOT NULL UNIQUE,
    fecha_desde           TEXT NOT NULL,
    fecha_hasta           TEXT NOT NULL,
    source_name           TEXT DEFAULT 'oracle_productiva',
    source_rows_count     INTEGER DEFAULT 0,
    resumen_hash          TEXT,
    resumen_json          TEXT,
    ia_provider           TEXT,
    ia_model              TEXT,
    ia_prompt_version     TEXT,
    ia_summary_hash       TEXT,
    ia_json               TEXT,
    oracle_cached_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    ia_generated_at       DATETIME,
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PRODUCTIVIDAD_ANALISIS_OPERARIO = """
CREATE TABLE IF NOT EXISTS productividad_analisis_operario (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                INTEGER NOT NULL REFERENCES productividad_analisis_runs(run_id) ON DELETE CASCADE,
    operario              TEXT NOT NULL,
    movimientos           INTEGER DEFAULT 0,
    cantidad_total        REAL DEFAULT 0,
    peso_total            REAL DEFAULT 0,
    pallets_unicos        INTEGER DEFAULT 0,
    horas_activas         REAL DEFAULT 0,
    productividad_general REAL DEFAULT 0,
    movimientos_por_hora  REAL DEFAULT 0,
    desvio_vs_promedio_pct REAL DEFAULT 0,
    estado                TEXT
);
"""

CREATE_PRODUCTIVIDAD_ANALISIS_OPERARIO_ZONA = """
CREATE TABLE IF NOT EXISTS productividad_analisis_operario_zona (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                INTEGER NOT NULL REFERENCES productividad_analisis_runs(run_id) ON DELETE CASCADE,
    operario              TEXT NOT NULL,
    zona                  TEXT NOT NULL,
    movimientos           INTEGER DEFAULT 0,
    cantidad_total        REAL DEFAULT 0,
    peso_total            REAL DEFAULT 0,
    horas_activas         REAL DEFAULT 0,
    productividad         REAL DEFAULT 0
);
"""

CREATE_PRODUCTIVIDAD_ANALISIS_ZONA = """
CREATE TABLE IF NOT EXISTS productividad_analisis_zona (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                INTEGER NOT NULL REFERENCES productividad_analisis_runs(run_id) ON DELETE CASCADE,
    zona                  TEXT NOT NULL,
    movimientos           INTEGER DEFAULT 0,
    cantidad_total        REAL DEFAULT 0,
    peso_total            REAL DEFAULT 0,
    operarios             INTEGER DEFAULT 0,
    horas_activas         REAL DEFAULT 0,
    productividad         REAL DEFAULT 0
);
"""

CREATE_PRODUCTIVIDAD_ANALISIS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_productividad_runs_fechas ON productividad_analisis_runs(fecha_desde, fecha_hasta)",
    "CREATE INDEX IF NOT EXISTS idx_productividad_operario_run ON productividad_analisis_operario(run_id, operario)",
    "CREATE INDEX IF NOT EXISTS idx_productividad_operario_hist ON productividad_analisis_operario(operario, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_productividad_operario_zona_hist ON productividad_analisis_operario_zona(operario, zona, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_productividad_zona_hist ON productividad_analisis_zona(zona, run_id)",
]


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
        await db.execute(CREATE_PRODUCTIVIDAD_ANALISIS_RUNS)
        await db.execute(CREATE_PRODUCTIVIDAD_ANALISIS_OPERARIO)
        await db.execute(CREATE_PRODUCTIVIDAD_ANALISIS_OPERARIO_ZONA)
        await db.execute(CREATE_PRODUCTIVIDAD_ANALISIS_ZONA)
        for statement in CREATE_PRODUCTIVIDAD_ANALISIS_INDEXES:
            await db.execute(statement)

        await db.commit()
    print(f"[DB] Base de datos inicializada: {DB_PATH}")
    print(
        "[DB] OK - Tablas creadas: olas, operarios, asignaciones_ola, "
        "estandares_sector, historico_olas, productividad_analisis_*"
    )


async def get_db():
    """Context manager para obtener una conexión."""
    return aiosqlite.connect(DB_PATH)
