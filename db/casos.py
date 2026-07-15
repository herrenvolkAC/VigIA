"""
VigIA · Gestión de Casos.
Tablas y seed inicial para el motor común de tickets/casos.
"""
from __future__ import annotations

import aiosqlite

from db.auth import attach_auth_db
from db.schema import DB_PATH


CREATE_TICKET_TIPO = """
CREATE TABLE IF NOT EXISTS ticket_tipo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TICKET_ESTADO = """
CREATE TABLE IF NOT EXISTS ticket_estado (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_id INTEGER NOT NULL REFERENCES ticket_tipo(id),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    perfil_asignado TEXT,
    orden INTEGER NOT NULL DEFAULT 0,
    es_inicial INTEGER NOT NULL DEFAULT 0,
    es_final INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    UNIQUE(tipo_id, codigo)
);
"""

CREATE_TICKET_ESTADO_TRANSICION = """
CREATE TABLE IF NOT EXISTS ticket_estado_transicion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_id INTEGER NOT NULL REFERENCES ticket_tipo(id),
    estado_origen_id INTEGER NOT NULL REFERENCES ticket_estado(id),
    estado_destino_id INTEGER NOT NULL REFERENCES ticket_estado(id),
    perfil_autorizado TEXT NOT NULL,
    requiere_comentario INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    UNIQUE(tipo_id, estado_origen_id, estado_destino_id, perfil_autorizado)
);
"""

CREATE_TICKET_CRITICIDAD = """
CREATE TABLE IF NOT EXISTS ticket_criticidad (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_id INTEGER NOT NULL REFERENCES ticket_tipo(id),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    sla_horas INTEGER NOT NULL DEFAULT 72,
    color TEXT NOT NULL DEFAULT '#64748b',
    activo INTEGER NOT NULL DEFAULT 1,
    UNIQUE(tipo_id, codigo)
);
"""

CREATE_TICKET = """
CREATE TABLE IF NOT EXISTS ticket (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_visible TEXT UNIQUE,
    tipo_id INTEGER NOT NULL REFERENCES ticket_tipo(id),
    estado_id INTEGER NOT NULL REFERENCES ticket_estado(id),
    criticidad_id INTEGER NOT NULL REFERENCES ticket_criticidad(id),
    titulo TEXT NOT NULL,
    descripcion TEXT,
    usuario_creacion_id TEXT NOT NULL,
    sector_creacion_id TEXT,
    perfil_asignado TEXT,
    sector_asignado TEXT,
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_ultima_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_cierre DATETIME,
    sla_vencimiento DATETIME,
    activo INTEGER NOT NULL DEFAULT 1
);
"""

CREATE_TICKET_HISTORIAL = """
CREATE TABLE IF NOT EXISTS ticket_historial (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES ticket(id),
    fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
    usuario_id TEXT NOT NULL,
    perfil TEXT,
    accion TEXT NOT NULL,
    estado_anterior_id INTEGER REFERENCES ticket_estado(id),
    estado_nuevo_id INTEGER REFERENCES ticket_estado(id),
    comentario TEXT
);
"""

CREATE_TICKET_COMENTARIO = """
CREATE TABLE IF NOT EXISTS ticket_comentario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES ticket(id),
    fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
    usuario_id TEXT NOT NULL,
    comentario TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1
);
"""

CREATE_TICKET_ADJUNTO = """
CREATE TABLE IF NOT EXISTS ticket_adjunto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES ticket(id),
    fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
    usuario_id TEXT NOT NULL,
    nombre_original TEXT NOT NULL,
    nombre_archivo TEXT NOT NULL,
    ruta_archivo TEXT NOT NULL,
    tipo_mime TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);
"""

CREATE_TICKET_PERMISO_PERFIL = """
CREATE TABLE IF NOT EXISTS ticket_permiso_perfil (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_id INTEGER NOT NULL REFERENCES ticket_tipo(id),
    perfil TEXT NOT NULL,
    puede_crear INTEGER NOT NULL DEFAULT 0,
    puede_ver_todos INTEGER NOT NULL DEFAULT 0,
    puede_ver_sector INTEGER NOT NULL DEFAULT 1,
    puede_editar INTEGER NOT NULL DEFAULT 0,
    puede_comentar INTEGER NOT NULL DEFAULT 1,
    puede_adjuntar INTEGER NOT NULL DEFAULT 1,
    puede_exportar INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    UNIQUE(tipo_id, perfil)
);
"""

CREATE_TICKET_USUARIO_PERFIL = """
CREATE TABLE IF NOT EXISTS ticket_usuario_perfil (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    tipo_codigo TEXT NOT NULL DEFAULT 'REPARACION_RACK',
    perfil TEXT NOT NULL,
    sector TEXT,
    correo TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(username, tipo_codigo)
);
"""

CREATE_TICKET_RACK_DETALLE = """
CREATE TABLE IF NOT EXISTS ticket_rack_detalle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL UNIQUE REFERENCES ticket(id),
    zona_id INTEGER REFERENCES rack_zona(id),
    zona_text TEXT,
    pasillo TEXT NOT NULL,
    cara_id INTEGER REFERENCES rack_cara(id),
    ubicaciones TEXT NOT NULL,
    niveles TEXT NOT NULL,
    sector_rack_id INTEGER REFERENCES rack_sector(id),
    descripcion_rack_id INTEGER REFERENCES rack_descripcion(id),
    tipo_rack_id INTEGER REFERENCES rack_tipo(id),
    comentario_operativo TEXT,
    service_externo_id TEXT,
    service_externo_usuario TEXT,
    service_externo_fecha DATETIME,
    traspasos_wms TEXT,
    traspasos_usuario TEXT,
    traspasos_fecha DATETIME,
    vaciado_confirmado INTEGER NOT NULL DEFAULT 0,
    vaciado_usuario TEXT,
    vaciado_fecha DATETIME,
    inutilizacion_wms_confirmada INTEGER NOT NULL DEFAULT 0,
    inutilizacion_usuario TEXT,
    inutilizacion_fecha DATETIME,
    mantenimiento_finalizado INTEGER NOT NULL DEFAULT 0,
    mantenimiento_usuario TEXT,
    mantenimiento_fecha DATETIME,
    relevamiento_mapa TEXT,
    reetiquetado_requerido INTEGER NOT NULL DEFAULT 0,
    rehabilitacion_wms_confirmada INTEGER NOT NULL DEFAULT 0,
    rehabilitacion_usuario TEXT,
    rehabilitacion_fecha DATETIME
);
"""

CREATE_TICKET_FORMS_INGRESO = """
CREATE TABLE IF NOT EXISTS ticket_forms_ingreso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'microsoft_forms',
    form TEXT NOT NULL DEFAULT 'service_racks',
    response_id TEXT NOT NULL,
    source_file TEXT,
    received_at TEXT,
    payload_json TEXT NOT NULL,
    estado_importacion TEXT NOT NULL DEFAULT 'PENDIENTE',
    motivo_error TEXT,
    ticket_id INTEGER REFERENCES ticket(id),
    reclamado_por TEXT,
    fecha_reclamo DATETIME,
    comentario_reclamo TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, form, response_id)
);
"""

CREATE_RACK_PARAM_TABLES = {
    "rack_zona": """
        CREATE TABLE IF NOT EXISTS rack_zona (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """,
    "rack_cara": """
        CREATE TABLE IF NOT EXISTS rack_cara (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """,
    "rack_nivel": """
        CREATE TABLE IF NOT EXISTS rack_nivel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """,
    "rack_sector": """
        CREATE TABLE IF NOT EXISTS rack_sector (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """,
    "rack_descripcion": """
        CREATE TABLE IF NOT EXISTS rack_descripcion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """,
    "rack_tipo": """
        CREATE TABLE IF NOT EXISTS rack_tipo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """,
}

CREATE_TICKET_EVENTO_NOTIFICACION = """
CREATE TABLE IF NOT EXISTS ticket_evento_notificacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER REFERENCES ticket(id),
    evento TEXT NOT NULL,
    payload_json TEXT,
    procesado INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ticket_tipo_estado ON ticket(tipo_id, estado_id, activo)",
    "CREATE INDEX IF NOT EXISTS idx_ticket_fechas ON ticket(fecha_creacion, fecha_cierre)",
    "CREATE INDEX IF NOT EXISTS idx_ticket_sla ON ticket(sla_vencimiento, estado_id)",
    "CREATE INDEX IF NOT EXISTS idx_ticket_historial_ticket ON ticket_historial(ticket_id, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_ticket_comentario_ticket ON ticket_comentario(ticket_id, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_ticket_adjunto_ticket ON ticket_adjunto(ticket_id, fecha)",
    "CREATE INDEX IF NOT EXISTS idx_ticket_usuario_perfil_user ON ticket_usuario_perfil(username, tipo_codigo, activo)",
    "CREATE INDEX IF NOT EXISTS idx_ticket_forms_estado ON ticket_forms_ingreso(estado_importacion, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_ticket_forms_ticket ON ticket_forms_ingreso(ticket_id)",
]

RACK_STATES = [
    ("REGISTRADO", "Registrado", "ADO", 10, 1, 0),
    ("PENDIENTE_VALIDACION", "Pendiente Validacion", "ADO", 20, 0, 0),
    ("REQUIERE_CORRECCION", "Requiere Correccion", "OPERACION", 30, 0, 0),
    ("PENDIENTE_TRASPASOS", "Pendiente Traspasos", "MAPA_ALMACEN", 40, 0, 0),
    ("TRASPASOS_ASIGNADOS", "Traspasos Asignados", "OPERACION", 50, 0, 0),
    ("EN_EJECUCION", "En Ejecucion", "OPERACION", 60, 0, 0),
    ("POSICION_BLOQUEADA", "Posicion Bloqueada", "MANTENIMIENTO", 70, 0, 0),
    ("EN_REPARACION", "En Reparacion", "MANTENIMIENTO", 80, 0, 0),
    ("REPARADO", "Reparado", "MAPA_ALMACEN", 90, 0, 0),
    ("PENDIENTE_HABILITACION", "Pendiente Habilitacion", "MAPA_ALMACEN", 100, 0, 0),
    ("CERRADO", "Cerrado", "OPERACION", 110, 0, 1),
    ("CANCELADO", "Cancelado", "OPERACION", 120, 0, 1),
]

RACK_CRITICIDADES = [
    ("BAJA", "Baja", 168, "#16a34a"),
    ("MEDIA", "Media", 72, "#ca8a04"),
    ("ALTA", "Alta", 24, "#ea580c"),
    ("CRITICA", "Critica", 8, "#dc2626"),
]

RACK_PARAMS = {
    "rack_zona": [("Z1", "Zona 1", 10), ("Z2", "Zona 2", 20), ("NOA", "NOA", 30)],
    "rack_cara": [("D", "D", 10), ("I", "I", 20)],
    "rack_nivel": [
        ("1", "1", 10),
        ("A", "A", 20),
        ("B", "B", 30),
        ("C", "C", 40),
        ("D", "D", 50),
        ("E", "E", 60),
        ("F", "F", 70),
        ("G", "G", 80),
    ],
    "rack_sector": [("SECOS", "Secos", 10), ("REFRI", "Refrigerados", 20), ("NOA", "NOA", 30)],
    "rack_descripcion": [
        ("CARRO_ROTO_PUSH_BACK", "Carro Roto (Push Back)", 10),
        ("GOTERA", "Gotera", 20),
        ("FALTA_POSA_PALLET", "Falta posa pallet", 30),
        ("FRENO", "Freno", 40),
        ("TRAVESANO_ROTO", "Travesaño roto", 50),
        ("TRAVESANO_SUELTO", "Travesaño Suelto", 60),
        ("MINIRIEL", "Miniriel", 70),
        ("PUNTAL_ROTO_DOBLADO", "Puntal roto/doblado", 80),
        ("RODILLO_ROTO", "Rodillo roto", 90),
        ("RODILLO_SUELTO", "Rodillo suelto", 100),
    ],
    "rack_tipo": [
        ("SELECTIVO", "Selectivo", 10),
        ("DRIVE_IN", "Drive in", 20),
        ("FLOW", "Flow", 30),
        ("PUSH_BACK", "Push back", 40),
        ("CASE_FLOW", "Case Flow", 50),
    ],
}

PERFILES = ["OPERACION", "ACTIVACION", "ADO", "MAPA_ALMACEN", "PLANEAMIENTO", "MANTENIMIENTO", "ADMIN"]


async def init_cases_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await attach_auth_db(db)
        for statement in [
            CREATE_TICKET_TIPO,
            CREATE_TICKET_ESTADO,
            CREATE_TICKET_ESTADO_TRANSICION,
            CREATE_TICKET_CRITICIDAD,
            CREATE_TICKET,
            CREATE_TICKET_HISTORIAL,
            CREATE_TICKET_COMENTARIO,
            CREATE_TICKET_ADJUNTO,
            CREATE_TICKET_PERMISO_PERFIL,
            CREATE_TICKET_USUARIO_PERFIL,
            CREATE_TICKET_RACK_DETALLE,
            CREATE_TICKET_EVENTO_NOTIFICACION,
            CREATE_TICKET_FORMS_INGRESO,
        ]:
            await db.execute(statement)
        for statement in CREATE_RACK_PARAM_TABLES.values():
            await db.execute(statement)
        async with db.execute("PRAGMA table_info(ticket_estado)") as cur:
            estado_cols = {row[1] for row in await cur.fetchall()}
        if "perfil_asignado" not in estado_cols:
            await db.execute("ALTER TABLE ticket_estado ADD COLUMN perfil_asignado TEXT")
        async with db.execute("PRAGMA table_info(ticket)") as cur:
            ticket_cols = {row[1] for row in await cur.fetchall()}
        if "perfil_asignado" not in ticket_cols:
            await db.execute("ALTER TABLE ticket ADD COLUMN perfil_asignado TEXT")
        if "sector_asignado" not in ticket_cols:
            await db.execute("ALTER TABLE ticket ADD COLUMN sector_asignado TEXT")
        async with db.execute("PRAGMA table_info(ticket_usuario_perfil)") as cur:
            usuario_perfil_cols = {row[1] for row in await cur.fetchall()}
        if "correo" not in usuario_perfil_cols:
            await db.execute("ALTER TABLE ticket_usuario_perfil ADD COLUMN correo TEXT")
        async with db.execute("PRAGMA table_info(ticket_rack_detalle)") as cur:
            rack_detail_cols = {row[1] for row in await cur.fetchall()}
        for column, ddl in {
            "zona_text": "ALTER TABLE ticket_rack_detalle ADD COLUMN zona_text TEXT",
            "service_externo_id": "ALTER TABLE ticket_rack_detalle ADD COLUMN service_externo_id TEXT",
            "service_externo_usuario": "ALTER TABLE ticket_rack_detalle ADD COLUMN service_externo_usuario TEXT",
            "service_externo_fecha": "ALTER TABLE ticket_rack_detalle ADD COLUMN service_externo_fecha DATETIME",
            "traspasos_wms": "ALTER TABLE ticket_rack_detalle ADD COLUMN traspasos_wms TEXT",
            "traspasos_usuario": "ALTER TABLE ticket_rack_detalle ADD COLUMN traspasos_usuario TEXT",
            "traspasos_fecha": "ALTER TABLE ticket_rack_detalle ADD COLUMN traspasos_fecha DATETIME",
            "vaciado_confirmado": "ALTER TABLE ticket_rack_detalle ADD COLUMN vaciado_confirmado INTEGER NOT NULL DEFAULT 0",
            "vaciado_usuario": "ALTER TABLE ticket_rack_detalle ADD COLUMN vaciado_usuario TEXT",
            "vaciado_fecha": "ALTER TABLE ticket_rack_detalle ADD COLUMN vaciado_fecha DATETIME",
            "inutilizacion_wms_confirmada": "ALTER TABLE ticket_rack_detalle ADD COLUMN inutilizacion_wms_confirmada INTEGER NOT NULL DEFAULT 0",
            "inutilizacion_usuario": "ALTER TABLE ticket_rack_detalle ADD COLUMN inutilizacion_usuario TEXT",
            "inutilizacion_fecha": "ALTER TABLE ticket_rack_detalle ADD COLUMN inutilizacion_fecha DATETIME",
            "mantenimiento_finalizado": "ALTER TABLE ticket_rack_detalle ADD COLUMN mantenimiento_finalizado INTEGER NOT NULL DEFAULT 0",
            "mantenimiento_usuario": "ALTER TABLE ticket_rack_detalle ADD COLUMN mantenimiento_usuario TEXT",
            "mantenimiento_fecha": "ALTER TABLE ticket_rack_detalle ADD COLUMN mantenimiento_fecha DATETIME",
            "relevamiento_mapa": "ALTER TABLE ticket_rack_detalle ADD COLUMN relevamiento_mapa TEXT",
            "reetiquetado_requerido": "ALTER TABLE ticket_rack_detalle ADD COLUMN reetiquetado_requerido INTEGER NOT NULL DEFAULT 0",
            "rehabilitacion_wms_confirmada": "ALTER TABLE ticket_rack_detalle ADD COLUMN rehabilitacion_wms_confirmada INTEGER NOT NULL DEFAULT 0",
            "rehabilitacion_usuario": "ALTER TABLE ticket_rack_detalle ADD COLUMN rehabilitacion_usuario TEXT",
            "rehabilitacion_fecha": "ALTER TABLE ticket_rack_detalle ADD COLUMN rehabilitacion_fecha DATETIME",
        }.items():
            if column not in rack_detail_cols:
                await db.execute(ddl)
        async with db.execute("PRAGMA table_info(ticket_forms_ingreso)") as cur:
            forms_cols = {row[1] for row in await cur.fetchall()}
        for column, ddl in {
            "source_file": "ALTER TABLE ticket_forms_ingreso ADD COLUMN source_file TEXT",
            "reclamado_por": "ALTER TABLE ticket_forms_ingreso ADD COLUMN reclamado_por TEXT",
            "fecha_reclamo": "ALTER TABLE ticket_forms_ingreso ADD COLUMN fecha_reclamo DATETIME",
            "comentario_reclamo": "ALTER TABLE ticket_forms_ingreso ADD COLUMN comentario_reclamo TEXT",
        }.items():
            if column not in forms_cols:
                await db.execute(ddl)
        for statement in INDEXES:
            await db.execute(statement)
        await seed_cases_db(db)
        await db.commit()


async def seed_cases_db(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        INSERT OR IGNORE INTO ticket_tipo (codigo, nombre, descripcion, activo)
        VALUES ('REPARACION_RACK', 'Reparacion de Racks', 'Casos operativos para reparacion de posiciones/racks', 1)
        """
    )
    async with db.execute("SELECT id FROM ticket_tipo WHERE codigo = 'REPARACION_RACK'") as cur:
        tipo_id = int((await cur.fetchone())[0])

    await db.executemany(
        """
        INSERT INTO ticket_estado (tipo_id, codigo, nombre, perfil_asignado, orden, es_inicial, es_final, activo)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(tipo_id, codigo) DO UPDATE SET
            nombre=excluded.nombre,
            perfil_asignado=excluded.perfil_asignado,
            orden=excluded.orden,
            es_inicial=excluded.es_inicial,
            es_final=excluded.es_final,
            activo=1
        """,
        [(tipo_id, *item) for item in RACK_STATES],
    )
    await db.executemany(
        """
        INSERT OR IGNORE INTO ticket_criticidad (tipo_id, codigo, nombre, sla_horas, color, activo)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        [(tipo_id, *item) for item in RACK_CRITICIDADES],
    )
    for table, rows in RACK_PARAMS.items():
        await db.executemany(
            f"""
            INSERT INTO {table} (codigo, nombre, orden, activo)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(codigo) DO UPDATE SET nombre=excluded.nombre, orden=excluded.orden, activo=1
            """,
            rows,
        )
        if table in {"rack_cara", "rack_nivel", "rack_descripcion", "rack_tipo"}:
            desired_codes = [row[0] for row in rows]
            placeholders = ",".join("?" for _ in desired_codes)
            await db.execute(
                f"UPDATE {table} SET activo = 0 WHERE codigo NOT IN ({placeholders})",
                tuple(desired_codes),
            )

    permisos = []
    for perfil in PERFILES:
        admin = 1 if perfil == "ADMIN" else 0
        permisos.append(
            (
                tipo_id,
                perfil,
                1,
                admin,
                1,
                1 if perfil in {"OPERACION", "ADO", "MANTENIMIENTO", "ADMIN"} else 0,
                1,
                1,
                1 if perfil in {"ADO", "PLANEAMIENTO", "ADMIN"} else 0,
                1,
            )
        )
    await db.executemany(
        """
        INSERT OR IGNORE INTO ticket_permiso_perfil
            (tipo_id, perfil, puede_crear, puede_ver_todos, puede_ver_sector, puede_editar,
             puede_comentar, puede_adjuntar, puede_exportar, activo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        permisos,
    )
    await db.execute(
        """
        INSERT OR IGNORE INTO ticket_usuario_perfil (username, tipo_codigo, perfil, sector, correo, activo)
        SELECT username, 'REPARACION_RACK', 'ADMIN', 'ADMIN', NULL, 1
        FROM authdb.auth_users
        WHERE LOWER(role) = 'admin'
        """
    )

    async with db.execute("SELECT id, codigo FROM ticket_estado WHERE tipo_id = ?", (tipo_id,)) as cur:
        state_ids = {row[1]: row[0] for row in await cur.fetchall()}
    transitions = [
        ("REGISTRADO", "PENDIENTE_VALIDACION", "ADO", 0),
        ("REGISTRADO", "CANCELADO", "OPERACION", 1),
        ("PENDIENTE_VALIDACION", "REQUIERE_CORRECCION", "ADO", 1),
        ("PENDIENTE_VALIDACION", "PENDIENTE_TRASPASOS", "ADO", 0),
        ("REQUIERE_CORRECCION", "REGISTRADO", "OPERACION", 1),
        ("PENDIENTE_TRASPASOS", "TRASPASOS_ASIGNADOS", "MAPA_ALMACEN", 0),
        ("TRASPASOS_ASIGNADOS", "EN_EJECUCION", "OPERACION", 0),
        ("TRASPASOS_ASIGNADOS", "EN_EJECUCION", "ACTIVACION", 0),
        ("EN_EJECUCION", "POSICION_BLOQUEADA", "MAPA_ALMACEN", 0),
        ("POSICION_BLOQUEADA", "EN_REPARACION", "MANTENIMIENTO", 0),
        ("EN_REPARACION", "REPARADO", "MANTENIMIENTO", 1),
        ("REPARADO", "PENDIENTE_HABILITACION", "MAPA_ALMACEN", 0),
        ("PENDIENTE_HABILITACION", "CERRADO", "MAPA_ALMACEN", 1),
    ]
    admin_transitions = [(a, b, "ADMIN", c) for a, b, _, c in transitions]
    await db.execute("UPDATE ticket_estado_transicion SET activo = 0 WHERE tipo_id = ?", (tipo_id,))
    await db.executemany(
        """
        INSERT INTO ticket_estado_transicion
            (tipo_id, estado_origen_id, estado_destino_id, perfil_autorizado, requiere_comentario, activo)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(tipo_id, estado_origen_id, estado_destino_id, perfil_autorizado) DO UPDATE SET
            requiere_comentario=excluded.requiere_comentario,
            activo=1
        """,
        [
            (tipo_id, state_ids[src], state_ids[dst], perfil, requiere)
            for src, dst, perfil, requiere in transitions + admin_transitions
            if src in state_ids and dst in state_ids
        ],
    )
    await db.execute(
        """
        UPDATE ticket
        SET perfil_asignado = (
                SELECT perfil_asignado FROM ticket_estado WHERE ticket_estado.id = ticket.estado_id
            ),
            sector_asignado = (
                SELECT perfil_asignado FROM ticket_estado WHERE ticket_estado.id = ticket.estado_id
            )
        WHERE tipo_id = ? AND (perfil_asignado IS NULL OR TRIM(perfil_asignado) = '')
        """,
        (tipo_id,),
    )
