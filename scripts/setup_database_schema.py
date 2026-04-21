"""
VigIA - Database Schema Setup
Crea las 6 nuevas tablas para SESIÓN 1.1
Ejecutar: python scripts/setup_database_schema.py
"""
import asyncio
import aiosqlite
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path(__file__).parent.parent / "vigia.db"

# ============================================================================
# SCHEMA SQL - 6 NUEVAS TABLAS
# ============================================================================

SQL_SCHEMA = """
-- 1. ARTICULOS_MAESTRO - Catálogo de SKUs
CREATE TABLE IF NOT EXISTS articulos_maestro (
    sku TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL,
    peso_kg REAL,
    dimensiones TEXT,                    -- JSON: {ancho_cm, alto_cm, profundidad_cm}
    tipo TEXT,                           -- 'secas', 'congelado', 'fresco', 'bebidas'
    tiempo_picking_promedio_seg INT,     -- Tiempo promedio para hacer pick de este SKU
    complejidad TEXT,                    -- 'baja', 'media', 'alta'
    activo BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. PICKS_OPERARIO - TABLA CRÍTICA (1.460.000 registros en producción)
CREATE TABLE IF NOT EXISTS picks_operario (
    pick_id TEXT PRIMARY KEY,
    fecha DATE NOT NULL,
    timestamp DATETIME NOT NULL,
    turno_id TEXT NOT NULL,
    ola_id TEXT NOT NULL,
    operario_id TEXT NOT NULL,
    sector TEXT NOT NULL,
    sku TEXT NOT NULL,
    cantidad_bultos INT DEFAULT 1,
    peso_kg REAL,
    tiempo_segundos INT,
    estado TEXT DEFAULT 'completado',    -- 'completado', 'error', 'cancelado'
    FOREIGN KEY (operario_id) REFERENCES operarios(operario_id),
    FOREIGN KEY (ola_id) REFERENCES olas(ola_id),
    FOREIGN KEY (sku) REFERENCES articulos_maestro(sku)
);

-- Índices para picks_operario (CRÍTICOS para performance)
CREATE INDEX IF NOT EXISTS idx_picks_operario_timestamp ON picks_operario(timestamp);
CREATE INDEX IF NOT EXISTS idx_picks_ola ON picks_operario(ola_id);
CREATE INDEX IF NOT EXISTS idx_picks_sku ON picks_operario(sku);
CREATE INDEX IF NOT EXISTS idx_picks_fecha ON picks_operario(fecha);

-- 3. PAUSAS_OPERARIO - Registro de pausas
CREATE TABLE IF NOT EXISTS pausas_operario (
    pausa_id TEXT PRIMARY KEY,
    fecha DATE NOT NULL,
    operario_id TEXT NOT NULL,
    timestamp_inicio DATETIME NOT NULL,
    timestamp_fin DATETIME,
    tipo TEXT NOT NULL,                  -- 'almuerzo', 'descanso', 'baño', 'capacitacion', 'cambio_zona'
    duracion_minutos INT,
    notas TEXT,
    FOREIGN KEY (operario_id) REFERENCES operarios(operario_id)
);

-- 4. AUSENTISMO_OPERARIO - Registración de ausencias
CREATE TABLE IF NOT EXISTS ausentismo_operario (
    ausencia_id TEXT PRIMARY KEY,
    fecha DATE NOT NULL,
    operario_id TEXT NOT NULL,
    tipo TEXT NOT NULL,                  -- 'enfermedad', 'licencia', 'inasistencia', 'retardo', 'suspensión'
    duracion_minutos INT,
    justificado BOOLEAN,
    notas TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (operario_id) REFERENCES operarios(operario_id)
);

-- 5. ERRORES_OPERARIO - Registro de errores en picking
CREATE TABLE IF NOT EXISTS errores_operario (
    error_id TEXT PRIMARY KEY,
    fecha DATE NOT NULL,
    timestamp DATETIME NOT NULL,
    operario_id TEXT NOT NULL,
    sku TEXT,
    tipo_error TEXT NOT NULL,            -- 'sku_incorrecto', 'cantidad_incorrecta', 'codigo_barras', 'ubicacion_mal', 'bulto_dañado'
    cantidad INT,
    descripcion TEXT,
    severidad TEXT DEFAULT 'media',      -- 'baja', 'media', 'alta'
    corregido BOOLEAN DEFAULT 0,
    FOREIGN KEY (operario_id) REFERENCES operarios(operario_id),
    FOREIGN KEY (sku) REFERENCES articulos_maestro(sku)
);

-- Índices para errores_operario
CREATE INDEX IF NOT EXISTS idx_errores_operario ON errores_operario(operario_id);
CREATE INDEX IF NOT EXISTS idx_errores_fecha ON errores_operario(fecha);

-- 6. CACHE_ANALISIS - Cache de análisis inteligentes
CREATE TABLE IF NOT EXISTS cache_analisis (
    analisis_id TEXT PRIMARY KEY,
    operario_id TEXT NOT NULL,
    fecha DATE NOT NULL,
    tipo_analisis TEXT NOT NULL,         -- 'caida_progresiva', 'correlacion_sku', 'patron_semanal', 'recuperacion_pausa', 'anomalia_zscore'
    resultado_json TEXT NOT NULL,        -- JSON con resultado del análisis
    cached_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    duracion_ms INT,                     -- Cuánto tardó el análisis
    confianza REAL,                      -- 0-100, confianza del resultado
    ttl_minutos INT DEFAULT 60,          -- Time to live del cache
    FOREIGN KEY (operario_id) REFERENCES operarios(operario_id)
);
"""

async def setup_database():
    """Ejecuta el schema de creación de tablas"""
    print("\n" + "="*70)
    print("VIGIA DATABASE SCHEMA SETUP")
    print("="*70 + "\n")

    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            print(f"[DB] Base de datos: {DB_PATH}")
            print(f"[SQL] Ejecutando schema SQL...\n")

            # Ejecutar cada statement del schema
            for statement in SQL_SCHEMA.split(';'):
                statement = statement.strip()
                if statement:
                    await db.execute(statement)
                    print(f"[OK] Ejecutado: {statement[:60]}...")

            await db.commit()
            print("\n[SUCCESS] Schema ejecutado exitosamente\n")

            # Validar tablas creadas
            print("[VALIDATE] Tablas creadas:\n")

            cursor = await db.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table'
                ORDER BY name
            """)
            tables = await cursor.fetchall()

            for table in tables:
                table_name = table[0]
                cursor = await db.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = await cursor.fetchone()
                print(f"  [{table_name}] - {count[0]} registros")

            print("\n" + "="*70)
            print("[COMPLETE] SCHEMA SETUP COMPLETADO")
            print("="*70 + "\n")

            return True

    except Exception as e:
        print(f"\n[ERROR] {e}\n")
        return False

if __name__ == "__main__":
    success = asyncio.run(setup_database())
    sys.exit(0 if success else 1)
