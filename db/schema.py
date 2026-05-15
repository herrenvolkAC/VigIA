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

CREATE_CUMPLIMIENTO_ONLINE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS cumplimiento_online_snapshots (
    snapshot_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    turno_key            TEXT NOT NULL,
    turno_label          TEXT NOT NULL,
    turno_inicio         TEXT NOT NULL,
    bloque_desde         TEXT NOT NULL,
    bloque_hasta         TEXT NOT NULL,
    oracle_rows_count    INTEGER DEFAULT 0,
    rows_json            TEXT,
    resumen_json         TEXT,
    ia_provider          TEXT,
    ia_model             TEXT,
    ia_prompt_version    TEXT,
    ia_sugerencia        TEXT,
    ia_generated_at      TEXT,
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(turno_key, turno_inicio, bloque_hasta)
);
"""

CREATE_PLANTEL_SCENARIOS = """
CREATE TABLE IF NOT EXISTS plantel_scenarios (
    scenario_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre                 TEXT NOT NULL,
    turno_key              TEXT NOT NULL,
    turno_label            TEXT NOT NULL,
    hora_inicio            TEXT NOT NULL,
    hora_fin               TEXT NOT NULL,
    dotacion_total         INTEGER DEFAULT 0,
    estado                 TEXT DEFAULT 'generado',
    source_name            TEXT DEFAULT 'oracle_productiva',
    request_json           TEXT,
    result_json            TEXT,
    ia_provider            TEXT,
    ia_model               TEXT,
    ia_prompt_version      TEXT,
    ia_json                TEXT,
    created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PLANTEL_SCENARIO_ALMACEN = """
CREATE TABLE IF NOT EXISTS plantel_scenario_almacen (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id            INTEGER NOT NULL REFERENCES plantel_scenarios(scenario_id) ON DELETE CASCADE,
    almacen                TEXT NOT NULL,
    bultos_turno           REAL DEFAULT 0,
    lineas_turno           REAL DEFAULT 0,
    dotacion_sugerida      INTEGER DEFAULT 0,
    capacidad_equipo       REAL DEFAULT 0,
    productividad_grupal   REAL DEFAULT 0,
    hora_fin_estimada      TEXT,
    cobertura_pct          REAL DEFAULT 0,
    riesgo                 TEXT,
    baseline_dotacion      INTEGER DEFAULT 0,
    baseline_capacidad     REAL DEFAULT 0,
    baseline_hora_fin      TEXT,
    baseline_cobertura_pct REAL DEFAULT 0,
    created_at             DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PLANTEL_SCENARIO_ASIGNACION = """
CREATE TABLE IF NOT EXISTS plantel_scenario_asignacion (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id            INTEGER NOT NULL REFERENCES plantel_scenarios(scenario_id) ON DELETE CASCADE,
    operario_id            TEXT NOT NULL,
    operario_nombre        TEXT,
    tipo_asignacion        TEXT NOT NULL,
    almacen                TEXT NOT NULL,
    score_total            REAL DEFAULT 0,
    capacidad_estimada     REAL DEFAULT 0,
    penalizacion           REAL DEFAULT 0,
    motivo_principal       TEXT,
    detalle_json           TEXT,
    created_at             DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PLANTEL_SCENARIO_METRICA = """
CREATE TABLE IF NOT EXISTS plantel_scenario_metrica (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id            INTEGER NOT NULL REFERENCES plantel_scenarios(scenario_id) ON DELETE CASCADE,
    metrica_key            TEXT NOT NULL,
    metrica_valor          REAL,
    detalle                TEXT,
    created_at             DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PLANTEL_HISTORY_CACHE = """
CREATE TABLE IF NOT EXISTS plantel_history_cache (
    cache_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    turno_key               TEXT NOT NULL,
    history_days            INTEGER NOT NULL,
    source_name             TEXT NOT NULL,
    payload_json            TEXT NOT NULL,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(turno_key, history_days, source_name)
);
"""

CREATE_PLANTEL_MOVIMIENTOS_HIST = """
CREATE TABLE IF NOT EXISTS plantel_movimientos_hist (
    row_uid                 TEXT PRIMARY KEY,
    fecha                   DATE NOT NULL,
    fh_movimiento           TEXT NOT NULL,
    turno_key               TEXT NOT NULL,
    operario_id             TEXT NOT NULL,
    operario_nombre         TEXT,
    zona_origen             TEXT,
    almacen                 TEXT NOT NULL,
    cantidad                REAL DEFAULT 0,
    peso_registrado         REAL DEFAULT 0,
    nro_pallet              TEXT,
    source_name             TEXT DEFAULT 'oracle_productiva',
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_UBICACIONES_ORACLE = """
CREATE TABLE IF NOT EXISTS ubicaciones_oracle (
    ubicacion_id            TEXT PRIMARY KEY,
    snapshot_source         TEXT,
    snapshot_loaded_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    cempresa                TEXT,
    calmacen                TEXT,
    czonalma                TEXT NOT NULL,
    cpasillo                TEXT NOT NULL,
    chuecopa                INTEGER NOT NULL,
    cdigcont                TEXT,
    nnivelal                INTEGER,
    nposlarg                INTEGER,
    cumdimen                TEXT,
    qaltubic                REAL,
    qancubic                REAL,
    qlarubic                REAL,
    cunmpeso                TEXT,
    qpmaxubi                REAL,
    cumvolum                TEXT,
    qvmaxubi                REAL,
    xpropubi                TEXT,
    xtipsubi                TEXT,
    xubilimi                TEXT,
    fultrecu                TEXT,
    copultre                TEXT,
    xsitubic                TEXT,
    xblqrecu                TEXT,
    cconsign                TEXT,
    qpalaltu                REAL,
    qpalprof                REAL,
    crotacio                TEXT,
    qpesoact                REAL,
    qvoluact                REAL,
    qpalactu                REAL,
    xsetrasp                TEXT,
    xserotos                TEXT,
    fcreareg                TEXT,
    fmodireg                TEXT,
    copecrea                TEXT,
    codinuti                TEXT,
    pasifisi                TEXT,
    ggercome                TEXT,
    qpemaxpa                REAL,
    qaltubpi                REAL,
    ubicacion_codigo        TEXT NOT NULL
);
"""

CREATE_PICKING_UBICACIONES_HIST = """
CREATE TABLE IF NOT EXISTS picking_ubicaciones_hist (
    ubicacion_codigo        TEXT PRIMARY KEY,
    orden_teorico          INTEGER NOT NULL,
    first_seen             TEXT,
    last_seen              TEXT,
    pick_count             INTEGER DEFAULT 0,
    source_name            TEXT DEFAULT 'oracle_productiva',
    snapshot_loaded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PICKING_ANALYSIS_CACHE_RUNS = """
CREATE TABLE IF NOT EXISTS picking_analysis_cache_runs (
    cache_run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha                   DATE NOT NULL,
    turno_key               TEXT NOT NULL,
    turno_label             TEXT NOT NULL,
    fecha_desde             TEXT NOT NULL,
    fecha_hasta             TEXT NOT NULL,
    source_name             TEXT DEFAULT 'oracle_productiva',
    source_rows_count       INTEGER DEFAULT 0,
    resumen_hash            TEXT,
    ia_provider             TEXT,
    ia_model                TEXT,
    ia_prompt_version       TEXT,
    ia_summary_hash         TEXT,
    ia_json                 TEXT,
    ia_generated_at         DATETIME,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(fecha, turno_key)
);
"""

CREATE_PICKING_ANALYSIS_CACHE_ROWS = """
CREATE TABLE IF NOT EXISTS picking_analysis_cache_rows (
    row_uid                  TEXT PRIMARY KEY,
    cache_run_id             INTEGER NOT NULL REFERENCES picking_analysis_cache_runs(cache_run_id) ON DELETE CASCADE,
    fecha                    DATE NOT NULL,
    turno_key                TEXT NOT NULL,
    fh_movimiento            TEXT NOT NULL,
    copecrea                 TEXT NOT NULL,
    operario                 TEXT,
    almacen                  TEXT,
    zona_origen              TEXT,
    ubic_origen              TEXT,
    nro_pallet               TEXT,
    cantidad                 REAL DEFAULT 0,
    peso                     REAL DEFAULT 0,
    referencia               TEXT,
    created_at               DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PRODUCTIVIDAD_ONLINE_CACHE_RUNS = """
CREATE TABLE IF NOT EXISTS productividad_online_cache_runs (
    cache_run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha                   DATE NOT NULL,
    turno_key               TEXT NOT NULL,
    turno_label             TEXT NOT NULL,
    fecha_desde             TEXT NOT NULL,
    fecha_hasta             TEXT NOT NULL,
    source_rows_count       INTEGER DEFAULT 0,
    evaluacion_json         TEXT,
    evaluacion_hash         TEXT,
    ia_provider             TEXT,
    ia_model                TEXT,
    ia_prompt_version       TEXT,
    ia_summary_hash         TEXT,
    ia_json                 TEXT,
    ia_generated_at         DATETIME,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(fecha, turno_key)
);
"""

CREATE_PRODUCTIVIDAD_ONLINE_CACHE_ROWS = """
CREATE TABLE IF NOT EXISTS productividad_online_cache_rows (
    row_uid                  TEXT PRIMARY KEY,
    cache_run_id             INTEGER NOT NULL REFERENCES productividad_online_cache_runs(cache_run_id) ON DELETE CASCADE,
    fecha                    DATE NOT NULL,
    turno_key                TEXT NOT NULL,
    fh_movimiento            TEXT NOT NULL,
    copecrea                 TEXT NOT NULL,
    operario                 TEXT,
    operacion                TEXT,
    almacen                  TEXT,
    zona_origen              TEXT,
    ubic_origen              TEXT,
    nro_pallet               TEXT,
    cantidad                 REAL DEFAULT 0,
    peso                     REAL DEFAULT 0,
    created_at               DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PRODUCTIVIDAD_HOURLY_IA_CACHE = """
CREATE TABLE IF NOT EXISTS productividad_hourly_ia_cache (
    cache_key               TEXT PRIMARY KEY,
    provider                TEXT NOT NULL,
    model_used              TEXT,
    prompt_version          TEXT NOT NULL,
    summary_hash            TEXT NOT NULL,
    request_json            TEXT NOT NULL,
    ia_json                 TEXT NOT NULL,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TNC_EVENTOS_CACHE = """
CREATE TABLE IF NOT EXISTS tnc_eventos_cache (
    row_uid                 TEXT PRIMARY KEY,
    empresa                 TEXT,
    almacen                 TEXT,
    legajo                  TEXT NOT NULL,
    operario                TEXT,
    area                    TEXT,
    puesto                  TEXT,
    foto                    TEXT,
    codigo_tnc              TEXT NOT NULL,
    descripcion_tnc         TEXT,
    dia_tnc                 DATE NOT NULL,
    turno_key               TEXT NOT NULL,
    turno_label             TEXT NOT NULL,
    loteinformacion         TEXT NOT NULL,
    ultimamodificacion     TEXT,
    inicio                  TEXT,
    fin                     TEXT,
    estado                  TEXT,
    minutos                 INTEGER DEFAULT 0,
    tope                    INTEGER DEFAULT 0,
    diferencia              INTEGER DEFAULT 0,
    estado_tiempo           TEXT,
    source_name             TEXT DEFAULT 'oracle_productiva',
    synced_at               DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TNC_CACHE_SYNC = """
CREATE TABLE IF NOT EXISTS tnc_cache_sync (
    dia_tnc                 DATE PRIMARY KEY,
    synced_at               DATETIME DEFAULT CURRENT_TIMESTAMP,
    registros               INTEGER DEFAULT 0,
    estado                  TEXT DEFAULT 'complete',
    error                   TEXT
);
"""

CREATE_RRHH_IMPORT_BATCHES = """
CREATE TABLE IF NOT EXISTS rrhh_import_batches (
    batch_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_key               TEXT NOT NULL UNIQUE,
    source_dir              TEXT NOT NULL,
    imported_by             TEXT,
    imported_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
    status                  TEXT NOT NULL DEFAULT 'complete',
    files_json              TEXT,
    summary_json            TEXT,
    error                   TEXT
);
"""

CREATE_RRHH_LEGAJERO = """
CREATE TABLE IF NOT EXISTS rrhh_legajero (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                INTEGER NOT NULL REFERENCES rrhh_import_batches(batch_id) ON DELETE CASCADE,
    legajo                  TEXT NOT NULL,
    nombre                  TEXT,
    empresa                 TEXT,
    division_personal       TEXT,
    sucursal                TEXT,
    unidad_organizativa     TEXT,
    desc_unidad_organizativa TEXT,
    sector_generico         TEXT,
    desc_sector_generico    TEXT,
    clave_funcion           TEXT,
    desc_funcion            TEXT,
    posicion                TEXT,
    desc_posicion           TEXT,
    grupo_personal          TEXT,
    desc_grupo_personal     TEXT,
    area_personal           TEXT,
    desc_area_personal      TEXT,
    fecha_ingreso           DATE,
    fecha_baja              DATE,
    proveedor               TEXT,
    razon_social            TEXT,
    es_gerencia             INTEGER DEFAULT 0,
    raw_json                TEXT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, legajo)
);
"""

CREATE_RRHH_PERSONAS = """
CREATE TABLE IF NOT EXISTS rrhh_personas (
    legajo                  TEXT PRIMARY KEY,
    nombre                  TEXT,
    empresa                 TEXT,
    division_personal       TEXT,
    sucursal                TEXT,
    unidad_organizativa     TEXT,
    desc_unidad_organizativa TEXT,
    sector_generico         TEXT,
    desc_sector_generico    TEXT,
    clave_funcion           TEXT,
    desc_funcion            TEXT,
    posicion                TEXT,
    desc_posicion           TEXT,
    grupo_personal          TEXT,
    desc_grupo_personal     TEXT,
    area_personal           TEXT,
    desc_area_personal      TEXT,
    area_nomina             TEXT,
    clase_contrato          TEXT,
    desc_tipo_contrato      TEXT,
    regla_plan_horario      TEXT,
    jubilado                TEXT,
    centro_coste            TEXT,
    fecha_ingreso           DATE,
    fecha_baja              DATE,
    antiguedad_anios        REAL DEFAULT 0,
    antiguedad_meses        REAL DEFAULT 0,
    antiguedad_dias         REAL DEFAULT 0,
    proveedor               TEXT,
    razon_social            TEXT,
    es_gerencia             INTEGER DEFAULT 0,
    active                  INTEGER NOT NULL DEFAULT 1,
    first_seen_batch_id     INTEGER REFERENCES rrhh_import_batches(batch_id),
    last_seen_batch_id      INTEGER REFERENCES rrhh_import_batches(batch_id),
    last_changed_batch_id   INTEGER REFERENCES rrhh_import_batches(batch_id),
    first_seen_at           DATETIME,
    last_seen_at            DATETIME,
    deactivated_at          DATETIME,
    data_hash               TEXT,
    change_count            INTEGER NOT NULL DEFAULT 0,
    raw_json                TEXT,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RRHH_PERSONAS_CHANGES = """
CREATE TABLE IF NOT EXISTS rrhh_personas_changes (
    change_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                INTEGER NOT NULL REFERENCES rrhh_import_batches(batch_id) ON DELETE CASCADE,
    legajo                  TEXT NOT NULL,
    change_type             TEXT NOT NULL,
    old_json                TEXT,
    new_json                TEXT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RRHH_ACTIVIDAD = """
CREATE TABLE IF NOT EXISTS rrhh_actividad_diaria (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                INTEGER NOT NULL REFERENCES rrhh_import_batches(batch_id) ON DELETE CASCADE,
    legajo                  TEXT NOT NULL,
    empleado                TEXT,
    fecha                   DATE NOT NULL,
    division                TEXT,
    subdivision             TEXT,
    sector                  TEXT,
    grupo_profesional       TEXT,
    area_personal           TEXT,
    dia                     TEXT,
    pausa                   TEXT,
    horario                 TEXT,
    aus_pres_codigo         TEXT,
    aus_pres_codigo_norm    TEXT,
    ausentismo_tratamiento  TEXT,
    ausentismo_tipo         TEXT,
    ausentismo_clasificacion TEXT,
    ausentismo_contabiliza  INTEGER DEFAULT 0,
    ausentismo_regla        TEXT,
    motivo                  TEXT,
    comida                  TEXT,
    entrada                 TEXT,
    p1_ini                  TEXT,
    p1_fin                  TEXT,
    mas                     TEXT,
    salida                  TEXT,
    hs_trab                 REAL DEFAULT 0,
    hs_ext_realiz           REAL DEFAULT 0,
    hs_50_autorizadas       REAL DEFAULT 0,
    hs_100                  REAL DEFAULT 0,
    recargo_50              REAL DEFAULT 0,
    recargo_100             REAL DEFAULT 0,
    rec_noct                REAL DEFAULT 0,
    hs_fer                  REAL DEFAULT 0,
    tarde                   REAL DEFAULT 0,
    viajes_equiv            REAL DEFAULT 0,
    es_gerencia             INTEGER DEFAULT 0,
    raw_json                TEXT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RRHH_FICHADAS = """
CREATE TABLE IF NOT EXISTS rrhh_fichadas (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                INTEGER NOT NULL REFERENCES rrhh_import_batches(batch_id) ON DELETE CASCADE,
    legajo                  TEXT NOT NULL,
    empleado                TEXT,
    fecha_fichada           DATETIME NOT NULL,
    fecha                   DATE NOT NULL,
    hora                    TEXT,
    sentido                 TEXT,
    ubicacion               TEXT,
    origen                  TEXT,
    destino                 TEXT,
    tipo_lectura            TEXT,
    es_gerencia             INTEGER DEFAULT 0,
    raw_json                TEXT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RRHH_SANCIONES = """
CREATE TABLE IF NOT EXISTS rrhh_sanciones (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                INTEGER NOT NULL REFERENCES rrhh_import_batches(batch_id) ON DELETE CASCADE,
    legajo                  TEXT NOT NULL,
    nombre                  TEXT,
    inicio                  DATE,
    fin                     DATE,
    cod                     TEXT,
    creacion                DATE,
    descripcion             TEXT,
    detalle                 TEXT,
    ausentismo              TEXT,
    desc_ausentismo         TEXT,
    causa_sancion           TEXT,
    descripcion_causa       TEXT,
    unidad_organizativa     TEXT,
    desc_unidad_organizativa TEXT,
    es_gerencia             INTEGER DEFAULT 0,
    raw_json                TEXT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RRHH_CODIGOS_AUSENTISMO = """
CREATE TABLE IF NOT EXISTS rrhh_codigos_ausentismo (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                INTEGER NOT NULL REFERENCES rrhh_import_batches(batch_id) ON DELETE CASCADE,
    codigo                  TEXT NOT NULL,
    codigo_normalizado      TEXT,
    descripcion             TEXT,
    tratamiento             TEXT,
    tipo_ausentismo         TEXT,
    source_sheet            TEXT,
    raw_json                TEXT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, codigo, tipo_ausentismo)
);
"""

CREATE_RRHH_CODIGOS_AUSENTISMO_MAESTRO = """
CREATE TABLE IF NOT EXISTS rrhh_codigos_ausentismo_maestro (
    codigo_normalizado      TEXT PRIMARY KEY,
    codigo_original         TEXT,
    descripcion             TEXT,
    tratamiento             TEXT,
    tipo_ausentismo         TEXT,
    source_sheet            TEXT,
    active                  INTEGER NOT NULL DEFAULT 1,
    first_seen_batch_id     INTEGER REFERENCES rrhh_import_batches(batch_id),
    last_seen_batch_id      INTEGER REFERENCES rrhh_import_batches(batch_id),
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    raw_json                TEXT
);
"""

CREATE_RRHH_AUSENTISMO_REGLAS = """
CREATE TABLE IF NOT EXISTS rrhh_ausentismo_reglas (
    regla_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                INTEGER REFERENCES rrhh_import_batches(batch_id) ON DELETE CASCADE,
    regla_tipo              TEXT NOT NULL,
    patron                  TEXT NOT NULL,
    clasificacion           TEXT NOT NULL,
    contabiliza             INTEGER NOT NULL DEFAULT 0,
    source_sheet            TEXT,
    active                  INTEGER NOT NULL DEFAULT 1,
    raw_json                TEXT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, regla_tipo, patron, clasificacion)
);
"""

CREATE_CUMPLIMIENTO_ONLINE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_cumpl_online_turno_inicio ON cumplimiento_online_snapshots(turno_key, turno_inicio, bloque_hasta)",
]

CREATE_PRODUCTIVIDAD_ANALISIS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_productividad_runs_fechas ON productividad_analisis_runs(fecha_desde, fecha_hasta)",
    "CREATE INDEX IF NOT EXISTS idx_productividad_operario_run ON productividad_analisis_operario(run_id, operario)",
    "CREATE INDEX IF NOT EXISTS idx_productividad_operario_hist ON productividad_analisis_operario(operario, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_productividad_operario_zona_hist ON productividad_analisis_operario_zona(operario, zona, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_productividad_zona_hist ON productividad_analisis_zona(zona, run_id)",
]

CREATE_PLANTEL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_plantel_scenarios_turno_created ON plantel_scenarios(turno_key, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_plantel_almacen_scenario ON plantel_scenario_almacen(scenario_id, almacen)",
    "CREATE INDEX IF NOT EXISTS idx_plantel_asignacion_scenario_tipo ON plantel_scenario_asignacion(scenario_id, tipo_asignacion)",
    "CREATE INDEX IF NOT EXISTS idx_plantel_metrica_scenario_key ON plantel_scenario_metrica(scenario_id, metrica_key)",
    "CREATE INDEX IF NOT EXISTS idx_plantel_history_cache_lookup ON plantel_history_cache(turno_key, history_days, source_name, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_plantel_mov_hist_turno_fecha ON plantel_movimientos_hist(turno_key, fecha, fh_movimiento)",
    "CREATE INDEX IF NOT EXISTS idx_plantel_mov_hist_almacen ON plantel_movimientos_hist(almacen, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_plantel_mov_hist_operario ON plantel_movimientos_hist(operario_id, fecha)",
]

CREATE_UBICACIONES_ORACLE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ubicaciones_oracle_zona_pasillo_hueco_pos ON ubicaciones_oracle(czonalma, cpasillo, chuecopa, nposlarg)",
    "CREATE INDEX IF NOT EXISTS idx_ubicaciones_oracle_codigo ON ubicaciones_oracle(ubicacion_codigo)",
    "CREATE INDEX IF NOT EXISTS idx_ubicaciones_oracle_tipo_nivel ON ubicaciones_oracle(xtipsubi, nnivelal)",
]

CREATE_PICKING_UBICACIONES_HIST_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_picking_ubic_hist_orden ON picking_ubicaciones_hist(orden_teorico)",
    "CREATE INDEX IF NOT EXISTS idx_picking_ubic_hist_count ON picking_ubicaciones_hist(pick_count DESC)",
]

CREATE_PICKING_ANALYSIS_CACHE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_picking_cache_runs_fecha_turno ON picking_analysis_cache_runs(fecha, turno_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_picking_cache_rows_lookup ON picking_analysis_cache_rows(fecha, turno_key, fh_movimiento)",
    "CREATE INDEX IF NOT EXISTS idx_picking_cache_rows_operario ON picking_analysis_cache_rows(copecrea, fecha, turno_key)",
]

CREATE_PRODUCTIVIDAD_ONLINE_CACHE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_prod_online_cache_runs_fecha_turno ON productividad_online_cache_runs(fecha, turno_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_prod_online_cache_rows_lookup ON productividad_online_cache_rows(fecha, turno_key, fh_movimiento)",
    "CREATE INDEX IF NOT EXISTS idx_prod_online_cache_rows_operario ON productividad_online_cache_rows(copecrea, fecha, turno_key)",
]

CREATE_PRODUCTIVIDAD_HOURLY_IA_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_prod_hourly_ia_lookup ON productividad_hourly_ia_cache(provider, prompt_version, summary_hash, updated_at)",
]

CREATE_TNC_CACHE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_tnc_cache_dia ON tnc_eventos_cache(dia_tnc)",
    "CREATE INDEX IF NOT EXISTS idx_tnc_cache_dia_turno ON tnc_eventos_cache(dia_tnc, turno_key)",
    "CREATE INDEX IF NOT EXISTS idx_tnc_cache_codigo ON tnc_eventos_cache(codigo_tnc, dia_tnc)",
    "CREATE INDEX IF NOT EXISTS idx_tnc_cache_legajo ON tnc_eventos_cache(legajo, dia_tnc)",
    "CREATE INDEX IF NOT EXISTS idx_tnc_cache_area ON tnc_eventos_cache(area, dia_tnc)",
    "CREATE INDEX IF NOT EXISTS idx_tnc_cache_puesto ON tnc_eventos_cache(puesto, dia_tnc)",
]

CREATE_RRHH_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_rrhh_batches_imported ON rrhh_import_batches(imported_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_legajero_batch_legajo ON rrhh_legajero(batch_id, legajo)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_legajero_sector ON rrhh_legajero(batch_id, desc_sector_generico)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_personas_active ON rrhh_personas(active, es_gerencia)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_personas_sector ON rrhh_personas(desc_sector_generico)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_personas_changes_batch ON rrhh_personas_changes(batch_id, change_type)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_personas_changes_legajo ON rrhh_personas_changes(legajo, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_actividad_fecha ON rrhh_actividad_diaria(batch_id, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_actividad_legajo_fecha ON rrhh_actividad_diaria(batch_id, legajo, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_actividad_sector ON rrhh_actividad_diaria(batch_id, sector)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_actividad_aus_tipo ON rrhh_actividad_diaria(batch_id, ausentismo_clasificacion, ausentismo_contabiliza)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_codigos_norm ON rrhh_codigos_ausentismo(batch_id, codigo_normalizado)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_reglas_batch ON rrhh_ausentismo_reglas(batch_id, regla_tipo, active)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_fichadas_legajo_fecha ON rrhh_fichadas(batch_id, legajo, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_fichadas_fecha ON rrhh_fichadas(batch_id, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_sanciones_legajo ON rrhh_sanciones(batch_id, legajo)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_sanciones_creacion ON rrhh_sanciones(batch_id, creacion)",
]

CREATE_AUTH_USERS = """
CREATE TABLE IF NOT EXISTS auth_users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_AUTH_DEVICES = """
CREATE TABLE IF NOT EXISTS auth_devices (
    device_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    user_agent TEXT,
    ip_address TEXT,
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    approved_at DATETIME,
    approved_by TEXT,
    rejected_at DATETIME,
    rejected_by TEXT,
    revoked_at DATETIME,
    revoked_by TEXT
);
"""

CREATE_AUTH_SESSIONS = """
CREATE TABLE IF NOT EXISTS auth_sessions (
    session_token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
);
"""

CREATE_AUTH_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_auth_devices_username ON auth_devices(username, status)",
    "CREATE INDEX IF NOT EXISTS idx_auth_sessions_username ON auth_sessions(username, expires_at)",
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
        await db.execute(CREATE_CUMPLIMIENTO_ONLINE_SNAPSHOTS)
        await db.execute(CREATE_PLANTEL_SCENARIOS)
        await db.execute(CREATE_PLANTEL_SCENARIO_ALMACEN)
        await db.execute(CREATE_PLANTEL_SCENARIO_ASIGNACION)
        await db.execute(CREATE_PLANTEL_SCENARIO_METRICA)
        await db.execute(CREATE_PLANTEL_HISTORY_CACHE)
        await db.execute(CREATE_PLANTEL_MOVIMIENTOS_HIST)
        await db.execute(CREATE_UBICACIONES_ORACLE)
        await db.execute(CREATE_PICKING_UBICACIONES_HIST)
        await db.execute(CREATE_PICKING_ANALYSIS_CACHE_RUNS)
        await db.execute(CREATE_PICKING_ANALYSIS_CACHE_ROWS)
        await db.execute(CREATE_PRODUCTIVIDAD_ONLINE_CACHE_RUNS)
        await db.execute(CREATE_PRODUCTIVIDAD_ONLINE_CACHE_ROWS)
        await db.execute(CREATE_PRODUCTIVIDAD_HOURLY_IA_CACHE)
        await db.execute(CREATE_TNC_EVENTOS_CACHE)
        await db.execute(CREATE_TNC_CACHE_SYNC)
        await db.execute(CREATE_RRHH_IMPORT_BATCHES)
        await db.execute(CREATE_RRHH_LEGAJERO)
        await db.execute(CREATE_RRHH_PERSONAS)
        await db.execute(CREATE_RRHH_PERSONAS_CHANGES)
        await db.execute(CREATE_RRHH_ACTIVIDAD)
        await db.execute(CREATE_RRHH_FICHADAS)
        await db.execute(CREATE_RRHH_SANCIONES)
        await db.execute(CREATE_RRHH_CODIGOS_AUSENTISMO)
        await db.execute(CREATE_RRHH_CODIGOS_AUSENTISMO_MAESTRO)
        await db.execute(CREATE_RRHH_AUSENTISMO_REGLAS)
        async with db.execute("PRAGMA table_info(rrhh_actividad_diaria)") as cur:
            rrhh_act_cols = {row[1] for row in await cur.fetchall()}
        for column_name, column_type in {
            "aus_pres_codigo_norm": "TEXT",
            "ausentismo_tratamiento": "TEXT",
            "ausentismo_tipo": "TEXT",
            "ausentismo_clasificacion": "TEXT",
            "ausentismo_contabiliza": "INTEGER DEFAULT 0",
            "ausentismo_regla": "TEXT",
        }.items():
            if column_name not in rrhh_act_cols:
                await db.execute(f"ALTER TABLE rrhh_actividad_diaria ADD COLUMN {column_name} {column_type}")
        async with db.execute("PRAGMA table_info(rrhh_codigos_ausentismo)") as cur:
            rrhh_cod_cols = {row[1] for row in await cur.fetchall()}
        if "codigo_normalizado" not in rrhh_cod_cols:
            await db.execute("ALTER TABLE rrhh_codigos_ausentismo ADD COLUMN codigo_normalizado TEXT")
        await db.execute(CREATE_AUTH_USERS)
        await db.execute(CREATE_AUTH_DEVICES)
        await db.execute(CREATE_AUTH_SESSIONS)
        async with db.execute("PRAGMA table_info(picking_analysis_cache_runs)") as cur:
            picking_cache_cols = {row[1] for row in await cur.fetchall()}
        if "resumen_hash" not in picking_cache_cols:
            await db.execute("ALTER TABLE picking_analysis_cache_runs ADD COLUMN resumen_hash TEXT")
        if "ia_provider" not in picking_cache_cols:
            await db.execute("ALTER TABLE picking_analysis_cache_runs ADD COLUMN ia_provider TEXT")
        if "ia_model" not in picking_cache_cols:
            await db.execute("ALTER TABLE picking_analysis_cache_runs ADD COLUMN ia_model TEXT")
        if "ia_prompt_version" not in picking_cache_cols:
            await db.execute("ALTER TABLE picking_analysis_cache_runs ADD COLUMN ia_prompt_version TEXT")
        if "ia_summary_hash" not in picking_cache_cols:
            await db.execute("ALTER TABLE picking_analysis_cache_runs ADD COLUMN ia_summary_hash TEXT")
        if "ia_json" not in picking_cache_cols:
            await db.execute("ALTER TABLE picking_analysis_cache_runs ADD COLUMN ia_json TEXT")
        if "ia_generated_at" not in picking_cache_cols:
            await db.execute("ALTER TABLE picking_analysis_cache_runs ADD COLUMN ia_generated_at DATETIME")
        async with db.execute("PRAGMA table_info(productividad_online_cache_runs)") as cur:
            online_cache_cols = {row[1] for row in await cur.fetchall()}
        for column_name, column_type in {
            "evaluacion_json": "TEXT",
            "evaluacion_hash": "TEXT",
            "ia_provider": "TEXT",
            "ia_model": "TEXT",
            "ia_prompt_version": "TEXT",
            "ia_summary_hash": "TEXT",
            "ia_json": "TEXT",
            "ia_generated_at": "DATETIME",
        }.items():
            if column_name not in online_cache_cols:
                await db.execute(f"ALTER TABLE productividad_online_cache_runs ADD COLUMN {column_name} {column_type}")
        for statement in CREATE_PRODUCTIVIDAD_ANALISIS_INDEXES:
            await db.execute(statement)
        for statement in CREATE_CUMPLIMIENTO_ONLINE_INDEXES:
            await db.execute(statement)
        for statement in CREATE_PLANTEL_INDEXES:
            await db.execute(statement)
        for statement in CREATE_UBICACIONES_ORACLE_INDEXES:
            await db.execute(statement)
        for statement in CREATE_PICKING_UBICACIONES_HIST_INDEXES:
            await db.execute(statement)
        for statement in CREATE_PICKING_ANALYSIS_CACHE_INDEXES:
            await db.execute(statement)
        for statement in CREATE_PRODUCTIVIDAD_ONLINE_CACHE_INDEXES:
            await db.execute(statement)
        for statement in CREATE_PRODUCTIVIDAD_HOURLY_IA_INDEXES:
            await db.execute(statement)
        for statement in CREATE_TNC_CACHE_INDEXES:
            await db.execute(statement)
        for statement in CREATE_RRHH_INDEXES:
            await db.execute(statement)
        for statement in CREATE_AUTH_INDEXES:
            await db.execute(statement)

        await db.commit()
    print(f"[DB] Base de datos inicializada: {DB_PATH}")
    print(
        "[DB] OK - Tablas creadas: olas, operarios, asignaciones_ola, "
        "estandares_sector, historico_olas, productividad_analisis_*, plantel_*"
    )


async def get_db():
    """Context manager para obtener una conexión."""
    return aiosqlite.connect(DB_PATH)
