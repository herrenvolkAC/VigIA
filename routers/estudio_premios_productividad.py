from __future__ import annotations

from datetime import datetime, timedelta
from collections import Counter, defaultdict
import math
import re
from utils.estudio_grupal import calcular_grupal, inferir_turnos
import json
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request

from db.paths import ROOT_DIR
from routers.auth_local import current_auth


router = APIRouter(prefix="/api/estudio-premios-productividad", tags=["estudio-premios-productividad"])
LAB_CACHE_DB_PATH = ROOT_DIR / "datos" / "laboratorio_premios.db"
LAB_CACHE_RUN_PREFIX = "ETAPA_AGOSTO_2026_SIN_FILTRO_ID_R1_"
PREMIO_SOURCE_DB_PATH = ROOT_DIR / "datos" / "premio_productividad.db"
RRHH_GRUPAL_DB_PATH = ROOT_DIR / "datos" / "vigia.db"

RRHH_PROPIOS_FILTER = "active=1 AND UPPER(TRIM(COALESCE(desc_grupo_personal,'')))='PROPIOS'"

DIVISIONES_DESCRIPCION = {
    '1': 'SECOS',
    '2': 'REFRIGERADOS',
    '4': 'REFRIGERADOS',
    '6': 'NOA',
}


def _operacion_total(operacion: Any) -> str:
    """Nombre que vincula simulaciones unificadas con el pago Oracle."""
    valor = str(operacion or '').strip().upper()
    return 'CARGA' if valor in {'CARGA CAMION', 'CARGA REFRIGERADOS', 'PALETS OPERADOS'} else valor


def _division_codigo(value: Any) -> str:
    return str(value or '').strip()


def _division_codigos(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value or '').replace('|', ',').replace(';', ',').split(',')
    codigos = {_division_codigo(item) for item in raw_items}
    return sorted((codigo for codigo in codigos if codigo),
                  key=lambda item: (0, int(item)) if item.isdigit() else (1, item))


def _division_label(codigo: Any) -> str:
    codigo = _division_codigo(codigo)
    descripcion = DIVISIONES_DESCRIPCION.get(codigo, '')
    return f'{codigo} · {descripcion}' if descripcion else codigo


def _divisiones_label(value: Any) -> str:
    return ' / '.join(_division_label(codigo) for codigo in _division_codigos(value))


def _dia_semana(fecha: str) -> str:
    try:
        return ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'][datetime.strptime(str(fecha), '%Y%m%d').weekday()]
    except Exception:
        return ''


async def _catalogo_divisiones(db) -> list[dict[str, str]]:
    async with db.execute("""SELECT DISTINCT TRIM(division) division
            FROM lab_cache_agrupado
            WHERE TRIM(COALESCE(division,''))<>''
            ORDER BY CAST(TRIM(division) AS INTEGER), TRIM(division)""") as cur:
        codigos = [_division_codigo(row[0]) for row in await cur.fetchall()]
    conocidos = set(codigos)
    for codigo in DIVISIONES_DESCRIPCION:
        if codigo not in conocidos:
            codigos.append(codigo)
    codigos = sorted(set(codigos), key=lambda item: (0, int(item)) if item.isdigit() else (1, item))
    return [{'codigo': codigo, 'descripcion': DIVISIONES_DESCRIPCION.get(codigo, ''),
             'label': _division_label(codigo)} for codigo in codigos if codigo]


async def _ensure_config(db):
    await db.execute('CREATE INDEX IF NOT EXISTS idx_lab_cache_agrupado_desc_funcion ON lab_cache_agrupado(desc_funcion)')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_lab_etapa_raw_fecha_legajo ON lab_etapa_detalle_raw(fecha,legajo)')
    # El legajero operativo recibido para estos cinco casos conserva la
    # función genérica AUTOELEVADORISTA (REFRIG). La nómina validada por la
    # operación los identifica como Clark de congelados. Esta tabla es una
    # capa local, explícita y auditable: nunca modifica rrhh_personas ni la
    # fuente Oracle.
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_perfil_operativo_legajo(
        legajo TEXT PRIMARY KEY, sector TEXT NOT NULL DEFAULT '',
        funcion_legajero TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '',
        activo INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    await db.executemany('''INSERT OR IGNORE INTO lab_perfil_operativo_legajo
        (legajo,sector,funcion_legajero,motivo,activo) VALUES(?,?,?,?,?)''', [
            ('121583', 'CD-REFRIGERADOS', 'CLARK CONGELADOS', 'Nómina operativa validada: Clark congelados.', 1),
            ('80639',  'CD-REFRIGERADOS', 'CLARK CONGELADOS', 'Referencia histórica: no figura en el legajero vigente.', 0),
            ('89963',  'CD-REFRIGERADOS', 'CLARK CONGELADOS', 'Nómina operativa validada: Clark congelados.', 1),
            ('103993', 'CD-REFRIGERADOS', 'CLARK CONGELADOS', 'Referencia histórica: no figura en el legajero vigente.', 0),
            ('109203', 'CD-REFRIGERADOS', 'CLARK CONGELADOS', 'Nómina operativa validada: Clark congelados.', 1),
        ])
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_auditoria_pago_sin_wms(
        fecha TEXT NOT NULL, legajo TEXT NOT NULL, operacion_actual TEXT NOT NULL,
        grupo_actual TEXT NOT NULL DEFAULT '', unidad_actual TEXT NOT NULL DEFAULT '',
        produccion_actual REAL NOT NULL DEFAULT 0, tiempo_actual TEXT NOT NULL DEFAULT '',
        pago_centavos INTEGER NOT NULL DEFAULT 0, sector_legajero TEXT NOT NULL DEFAULT '',
        funcion_legajero TEXT NOT NULL DEFAULT '', turno_madre TEXT NOT NULL DEFAULT '',
        operacion_reconstruida TEXT NOT NULL DEFAULT '', division_reconstruida TEXT NOT NULL DEFAULT '',
        motivo TEXT NOT NULL DEFAULT '', snapshot TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(fecha,legajo,operacion_actual,grupo_actual,unidad_actual,snapshot))''')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_cache_agrupado_ajuste(
        fecha TEXT NOT NULL, legajo TEXT NOT NULL, desc_funcion TEXT NOT NULL,
        division TEXT NOT NULL DEFAULT '', sector TEXT NOT NULL DEFAULT '',
        palets REAL NOT NULL DEFAULT 0, plus REAL NOT NULL DEFAULT 0,
        cantidad REAL NOT NULL DEFAULT 0, peso REAL NOT NULL DEFAULT 0,
        detalle_filas INTEGER NOT NULL DEFAULT 1, origen TEXT NOT NULL DEFAULT 'pago_actual_sin_wms',
        snapshot TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(fecha,legajo,desc_funcion,division,sector,origen,snapshot))''')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_lab_cache_agrupado_ajuste_fecha_legajo ON lab_cache_agrupado_ajuste(fecha,legajo)')
    # Las escalas, grupos y asistencia se consultan por snapshot/fuente en
    # cada cálculo. Este índice evita recorridos completos del histórico al
    # abrir una operación sintética o al recalcular individuales.
    await db.execute('CREATE INDEX IF NOT EXISTS idx_lab_fuente_registro_snapshot_fuente ON lab_fuente_registro(snapshot,fuente,ordinal)')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_palets_carga_traslado(
        fecha TEXT NOT NULL, legajo TEXT NOT NULL, pallet TEXT NOT NULL,
        contribucion INTEGER NOT NULL, inicio TEXT NOT NULL DEFAULT '', fin TEXT NOT NULL DEFAULT '',
        etapas_traslado INTEGER NOT NULL DEFAULT 0, etapas_carga INTEGER NOT NULL DEFAULT 0,
        tipo TEXT NOT NULL DEFAULT '', detalle TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(fecha,legajo,pallet,contribucion))''')
    async with db.execute("PRAGMA table_info(lab_palets_carga_traslado)") as cur:
        columnas_ct = {row[1] for row in await cur.fetchall()}
    if 'division' not in columnas_ct:
        await db.execute("ALTER TABLE lab_palets_carga_traslado ADD COLUMN division TEXT NOT NULL DEFAULT ''")
    await db.execute('CREATE INDEX IF NOT EXISTS idx_palets_ct_fecha_legajo ON lab_palets_carga_traslado(fecha,legajo)')
    # Recepción es una unidad física del proceso, aun cuando el WMS registre
    # la etiqueta en Operación de recepción y también en Revisor recepción.
    # Se conserva un solo dueño determinista por fecha/pallet para que la
    # suma individual reconcilie con la producción grupal.
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_palets_recepcion(
        fecha TEXT NOT NULL, legajo TEXT NOT NULL, pallet TEXT NOT NULL,
        funcion_origen TEXT NOT NULL DEFAULT '', inicio TEXT NOT NULL DEFAULT '',
        fin TEXT NOT NULL DEFAULT '', funciones TEXT NOT NULL DEFAULT '',
        division TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(fecha,pallet,division))''')
    async with db.execute("PRAGMA table_info(lab_palets_recepcion)") as cur:
        columnas_recepcion = {row[1] for row in await cur.fetchall()}
    if 'division' not in columnas_recepcion:
        await db.execute("ALTER TABLE lab_palets_recepcion ADD COLUMN division TEXT NOT NULL DEFAULT ''")
    await db.execute('CREATE INDEX IF NOT EXISTS idx_palets_recepcion_fecha_legajo ON lab_palets_recepcion(fecha,legajo)')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_palets_recepcion_division(
        fecha TEXT NOT NULL, legajo TEXT NOT NULL, pallet TEXT NOT NULL,
        division TEXT NOT NULL DEFAULT '', funcion_origen TEXT NOT NULL DEFAULT '',
        inicio TEXT NOT NULL DEFAULT '', fin TEXT NOT NULL DEFAULT '', funciones TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(fecha,pallet,division))''')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_palets_recepcion_div_fecha_legajo ON lab_palets_recepcion_division(fecha,legajo)')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_escalas_propuestas_cache(
        fecha TEXT NOT NULL, operacion TEXT NOT NULL, division TEXT NOT NULL DEFAULT '',
        turno TEXT NOT NULL DEFAULT '', legajo TEXT NOT NULL, unidad_medida TEXT NOT NULL DEFAULT '',
        uc REAL NOT NULL DEFAULT 0, inicio TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(fecha,operacion,division,turno,legajo))''')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_escalas_prop_op_fecha ON lab_escalas_propuestas_cache(operacion,fecha,division,turno)')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_actividad_duracion_cache(
        fecha TEXT NOT NULL, legajo TEXT NOT NULL, operacion TEXT NOT NULL, division TEXT NOT NULL DEFAULT '',
        segundos_validos REAL NOT NULL DEFAULT 0, etapas_tiempo INTEGER NOT NULL DEFAULT 0,
        etapas_inconsistentes INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(fecha,legajo,operacion,division))''')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_actividad_duracion_fecha(
        fecha TEXT PRIMARY KEY, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_actividad_duracion_op_fecha ON lab_actividad_duracion_cache(operacion,fecha,division,legajo)')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_escala_override(
        operacion TEXT NOT NULL, grupo_productivo TEXT NOT NULL DEFAULT '', nivel INTEGER NOT NULL,
        desde REAL NOT NULL, hasta REAL NOT NULL, premio REAL NOT NULL DEFAULT 0,
        premio_por_unidad_excedente REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(operacion,grupo_productivo,nivel,desde,hasta))''')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_escala_individual_grupal(
        sector TEXT NOT NULL, funcion_legajero TEXT NOT NULL, turno TEXT NOT NULL,
        operacion_medible TEXT NOT NULL, division_madre TEXT NOT NULL DEFAULT '', nivel INTEGER NOT NULL,
        desde_uc REAL NOT NULL, hasta_uc REAL NOT NULL DEFAULT 0, premio REAL NOT NULL DEFAULT 0,
        pct_sobre_anterior REAL NOT NULL DEFAULT 0,
        activo INTEGER NOT NULL DEFAULT 1, origen TEXT NOT NULL DEFAULT 'generada',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(sector,funcion_legajero,turno,operacion_medible,division_madre,nivel))''')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_escala_ind_grupal_perfil ON lab_escala_individual_grupal(sector,funcion_legajero,operacion_medible,turno)')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_escala_propia(
        operacion TEXT NOT NULL, grupo_productivo TEXT NOT NULL DEFAULT '', nivel INTEGER NOT NULL,
        desde REAL NOT NULL, hasta REAL NOT NULL, premio REAL NOT NULL DEFAULT 0,
        premio_por_unidad_excedente REAL NOT NULL DEFAULT 0,
        observaciones TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(operacion,grupo_productivo,nivel))''')
    # Tabla de escenario para Clark: una sola escala, sin depender del grupo
    # operativo. Replica los cuatro primeros tramos pagos de Secos + NOA.
    await db.executemany('''INSERT OR IGNORE INTO lab_escala_propia
        (operacion,grupo_productivo,nivel,desde,hasta,premio,premio_por_unidad_excedente,observaciones)
        VALUES(?,?,?,?,?,?,0,?)''', [
            ('CLARK', 'Sin grupo operativo', 0, 0, 95, 0,
             'Banda inicial sin premio.'),
            ('CLARK', 'Sin grupo operativo', 1, 96, 124, 5287.31,
             'Base Secos + NOA.'),
            ('CLARK', 'Sin grupo operativo', 2, 125, 154, 8058.90,
             'Base Secos + NOA.'),
            ('CLARK', 'Sin grupo operativo', 3, 155, 184, 15658.00,
             'Base Secos + NOA.'),
            ('CLARK', 'Sin grupo operativo', 4, 185, 999999, 24535.26,
             'Base Secos + NOA; último tramo abierto.'),
        ])
    # Escalas iniciales de recepción: replican las tablas vigentes de los
    # submódulos Secos y NOA, para que la operación unificada sea editable
    # desde el estudio sin depender de grupo operativo.
    await db.executemany('''INSERT OR IGNORE INTO lab_escala_propia
        (operacion,grupo_productivo,nivel,desde,hasta,premio,premio_por_unidad_excedente,observaciones)
        VALUES(?,?,?,?,?,?,0,?)''', [
            ('RECEPCION', 'CD-SECOS - ZONA 2', 0, 0, 57, 0,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-SECOS - ZONA 2', 1, 58, 77, 4037.79,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-SECOS - ZONA 2', 2, 78, 87, 5102.62,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-SECOS - ZONA 2', 3, 88, 180, 5102.62,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-SECOS - ZONA 2', 4, 181, 999999, 18076.12,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-SECOS - ZONA 1', 0, 0, 57, 0,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-SECOS - ZONA 1', 1, 58, 77, 4037.79,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-SECOS - ZONA 1', 2, 78, 87, 5102.62,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-SECOS - ZONA 1', 3, 88, 180, 5102.62,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-SECOS - ZONA 1', 4, 181, 999999, 18076.12,
             'Base de RECEPCION_SECOS_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-NOA', 0, 0, 42, 0,
             'Base de RECEPCION_NOA_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-NOA', 1, 43, 62, 4037.79,
             'Base de RECEPCION_NOA_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-NOA', 2, 63, 72, 5102.62,
             'Base de RECEPCION_NOA_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-NOA', 3, 73, 152, 5102.62,
             'Base de RECEPCION_NOA_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-NOA', 4, 153, 999999, 16223.34,
             'Base de RECEPCION_NOA_TABLA_SUBMODULO.'),
            ('RECEPCION', 'CD-REFRIGERADOS', 0, 0, 999999, 3535.72,
             'Base de REFRIGERADOS | RECEPCION.'),
        ])
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_turno_fijo_legajo(
        legajo TEXT PRIMARY KEY, turno_fijo TEXT NOT NULL DEFAULT '',
        turno_probable TEXT NOT NULL DEFAULT '', dias_turno INTEGER NOT NULL DEFAULT 0,
        total_dias INTEGER NOT NULL DEFAULT 0, distribucion TEXT NOT NULL DEFAULT '{}',
        snapshot TEXT NOT NULL, criterio TEXT NOT NULL, origen TEXT NOT NULL DEFAULT 'automatico',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_evaluacion_premio(
        id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, legajo TEXT NOT NULL,
        desc_funcion TEXT NOT NULL, sector TEXT NOT NULL DEFAULT '*',
        operacion_premio TEXT NOT NULL DEFAULT '', grupo_productivo TEXT NOT NULL DEFAULT '',
        unidad_medida TEXT NOT NULL DEFAULT '', unidades_evaluadas REAL,
        nivel_nuevo INTEGER, premio_nuevo REAL, evaluacion_estado TEXT NOT NULL DEFAULT '',
        version_tabla TEXT NOT NULL DEFAULT '', calculado_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(fecha,legajo,desc_funcion,sector,operacion_premio,grupo_productivo))""")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_lab_eval_legajo_fecha ON lab_evaluacion_premio(legajo,fecha)")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_mapa_polivalencia(
        operacion_a TEXT NOT NULL, operacion_b TEXT NOT NULL, polivalencia INTEGER NOT NULL DEFAULT 0,
        premio_centavos INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(operacion_a, operacion_b))""")
    async with db.execute('PRAGMA table_info(lab_mapa_polivalencia)') as cur:
        columnas_polivalencia = {row[1] for row in await cur.fetchall()}
    if 'premio_centavos' not in columnas_polivalencia:
        await db.execute('ALTER TABLE lab_mapa_polivalencia ADD COLUMN premio_centavos INTEGER NOT NULL DEFAULT 0')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_polivalencia_regla(
        id INTEGER PRIMARY KEY, sector TEXT NOT NULL, funcion_legajero TEXT NOT NULL,
        operacion_madre TEXT NOT NULL, premio_centavos INTEGER NOT NULL DEFAULT 0,
        activo INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(sector,funcion_legajero,operacion_madre))''')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_polivalencia_regla_operacion(
        regla_id INTEGER NOT NULL, operacion_b TEXT NOT NULL,
        PRIMARY KEY(regla_id,operacion_b),
        FOREIGN KEY(regla_id) REFERENCES lab_polivalencia_regla(id) ON DELETE CASCADE)''')
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_polivalencia_division_equivalencia(
        operacion TEXT NOT NULL, grupo TEXT NOT NULL, division TEXT NOT NULL,
        activo INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(operacion,grupo,division))''')
    await db.executemany('''INSERT OR IGNORE INTO lab_polivalencia_division_equivalencia
            (operacion,grupo,division,activo) VALUES(?,?,?,1)''',
                         [(operacion, grupo, division)
                          for operacion in ('ARMADO', 'CLARK', 'CONTROL', 'PALETS OPERADOS', 'RECEPCION')
                          for grupo, divisiones in (('SECOS_NOA', ('1', '6')),
                                                    ('REFRIGERADOS', ('2', '4')))
                          for division in divisiones])
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_calculo_grupal_cache(
        fecha_desde TEXT NOT NULL, fecha_hasta TEXT NOT NULL,
        nivel_1_json TEXT NOT NULL DEFAULT '[]', nivel_2_json TEXT NOT NULL DEFAULT '[]',
        nivel_3_json TEXT NOT NULL DEFAULT '[]', polivalencia_json TEXT NOT NULL DEFAULT '[]',
        calculado_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(fecha_desde,fecha_hasta))''')
    async with db.execute('PRAGMA table_info(lab_calculo_grupal_cache)') as cur:
        columnas_calculo_cache = {row[1] for row in await cur.fetchall()}
    if 'polivalencia_json' not in columnas_calculo_cache:
        await db.execute("ALTER TABLE lab_calculo_grupal_cache ADD COLUMN polivalencia_json TEXT NOT NULL DEFAULT '[]'")
    if 'nivel_2_json' not in columnas_calculo_cache:
        await db.execute("ALTER TABLE lab_calculo_grupal_cache ADD COLUMN nivel_2_json TEXT NOT NULL DEFAULT '[]'")
    if 'nivel_3_json' not in columnas_calculo_cache:
        await db.execute("ALTER TABLE lab_calculo_grupal_cache ADD COLUMN nivel_3_json TEXT NOT NULL DEFAULT '[]'")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_ausencia_config(
        cod_ausentismo TEXT PRIMARY KEY, descripcion TEXT NOT NULL DEFAULT '', permitido INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_parametro_grupal(
        sector TEXT NOT NULL, funcion_legajero TEXT NOT NULL, turno TEXT NOT NULL,
        uc_por_operario REAL NOT NULL DEFAULT 0, factor_ausentismo REAL NOT NULL DEFAULT 0,
        premio_grupal REAL NOT NULL DEFAULT 0, activo INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(sector,funcion_legajero,turno))""")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_parametro_grupal_componente(
        sector TEXT NOT NULL, funcion_legajero TEXT NOT NULL, turno TEXT NOT NULL,
        funcion_wms TEXT NOT NULL, unidad_medida TEXT NOT NULL DEFAULT 'PALET', factor REAL NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(sector,funcion_legajero,turno,funcion_wms),
        FOREIGN KEY(sector,funcion_legajero,turno)
          REFERENCES lab_parametro_grupal(sector,funcion_legajero,turno) ON DELETE CASCADE)""")
    # Catálogo de operaciones compuestas. A diferencia de los componentes
    # particulares de un parámetro, estas relaciones son la definición
    # reutilizable de la métrica y se aplican por defecto al seleccionarla.
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_operacion_medible_componente(
        operacion_medible TEXT NOT NULL, funcion_wms TEXT NOT NULL,
        unidad_medida TEXT NOT NULL DEFAULT 'PALET', factor REAL NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(operacion_medible,funcion_wms))""")
    async with db.execute('PRAGMA table_info(lab_parametro_grupal)') as cur:
        columnas_grupales = {row[1] for row in await cur.fetchall()}
    if 'operacion_medible' not in columnas_grupales:
        await db.execute("ALTER TABLE lab_parametro_grupal ADD COLUMN operacion_medible TEXT NOT NULL DEFAULT ''")
    if 'grupo_productivo_id' not in columnas_grupales:
        await db.execute('ALTER TABLE lab_parametro_grupal ADD COLUMN grupo_productivo_id INTEGER')
    if 'division_madre' not in columnas_grupales:
        await db.execute("ALTER TABLE lab_parametro_grupal ADD COLUMN division_madre TEXT NOT NULL DEFAULT ''")
    async with db.execute('PRAGMA table_info(lab_escala_individual_grupal)') as cur:
        columnas_escala_ind = {row[1] for row in await cur.fetchall()}
    if 'pct_sobre_anterior' not in columnas_escala_ind:
        await db.execute('ALTER TABLE lab_escala_individual_grupal ADD COLUMN pct_sobre_anterior REAL NOT NULL DEFAULT 0')
    await db.execute('''UPDATE lab_escala_individual_grupal
        SET pct_sobre_anterior=CASE WHEN nivel=1 THEN 10 ELSE 5 END
        WHERE COALESCE(pct_sobre_anterior,0)=0 AND nivel BETWEEN 1 AND 5''')

    # Migración funcional: Cargador de Secos mide la operación unificada,
    # cuyo insumo es carga + traslado validado por palet/etapa.
    await db.execute("""UPDATE lab_parametro_grupal SET operacion_medible='PALETS OPERADOS'
        WHERE UPPER(TRIM(funcion_legajero))='CARGADOR DE SECOS'
          AND UPPER(TRIM(operacion_medible))='CARGA CAMION'""")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_cache_grupal(
        fecha TEXT NOT NULL, legajo TEXT NOT NULL, turno TEXT NOT NULL DEFAULT '', sector TEXT NOT NULL DEFAULT '',
        funcion_legajero TEXT NOT NULL DEFAULT '', operacion TEXT NOT NULL DEFAULT '',
        uc_brutas REAL NOT NULL DEFAULT 0, uc_polivalencia REAL NOT NULL DEFAULT 0,
        uc_computables REAL NOT NULL DEFAULT 0, ausencia TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(fecha,legajo,turno,sector,funcion_legajero,operacion))""")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_grupo_productivo_equivalencia(
        grupo_cache TEXT PRIMARY KEY, grupo_premio TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_funcion_equivalencia(
        desc_funcion TEXT PRIMARY KEY, operacion_premio TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_funcion_parametro(
        desc_funcion TEXT PRIMARY KEY, medible INTEGER NOT NULL DEFAULT 0,
        unidad_medida TEXT NOT NULL DEFAULT '', grupo_premio TEXT NOT NULL DEFAULT '',
        observaciones TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_parametro(desc_funcion)
        SELECT DISTINCT TRIM(desc_funcion) FROM lab_cache_agrupado
        WHERE TRIM(COALESCE(desc_funcion,'')) <> ''""")
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_parametro
        (desc_funcion,medible,unidad_medida,observaciones)
        VALUES('PALETS OPERADOS',1,'PALET','Carga y traslado: cada movimiento físico validado vale un palet.')""")
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_equivalencia(desc_funcion,operacion_premio)
        VALUES('PALETS OPERADOS','PALETS OPERADOS')""")
    # CLARK se mide por movimientos físicos de palets de sus cinco etapas.
    # La escala Oracle ya contiene la operación CLARK; este catálogo sólo
    # define cómo se produce su unidad de medición en el escenario.
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_parametro
        (desc_funcion,medible,unidad_medida,observaciones)
        VALUES('CLARK',1,'PALET',
        'Operación compuesta: Guardado, Surtido PC, Ubicación y Extracción de reapro, y Extracción/traspaso.')""")
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_equivalencia(desc_funcion,operacion_premio)
        VALUES('CLARK','CLARK')""")
    await db.executemany("""INSERT OR IGNORE INTO lab_operacion_medible_componente
        (operacion_medible,funcion_wms,unidad_medida,factor) VALUES(?,?,?,1)""", [
            ('CLARK', 'GUARDAD', 'PALET'),
            ('CLARK', 'SURTIDO P.C', 'PALET'),
            ('CLARK', 'UBICAC.REAPRO', 'PALET'),
            ('CLARK', 'EXTRAC.REAPRO', 'PALET'),
            ('CLARK', 'EXTRAC.TRASP', 'PALET'),
        ])
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_parametro
        (desc_funcion,medible,unidad_medida,observaciones)
        VALUES('ARMADO',1,'BULTO',
        'Operación compuesta inicial para armado/picking medida por bultos.')""")
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_equivalencia(desc_funcion,operacion_premio)
        VALUES('ARMADO','ARMADO')""")
    await db.executemany("""INSERT OR IGNORE INTO lab_operacion_medible_componente
        (operacion_medible,funcion_wms,unidad_medida,factor) VALUES(?,?,?,1)""", [
            ('ARMADO', 'PICKIN', 'BULTO'),
        ])
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_parametro
        (desc_funcion,medible,unidad_medida,observaciones)
        VALUES('RECEPCION',1,'PALET',
        'Operación compuesta: recepción y revisión, por etiqueta física única.')""")
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_equivalencia(desc_funcion,operacion_premio)
        VALUES('RECEPCION','RECEPCION')""")
    await db.executemany("""INSERT OR IGNORE INTO lab_operacion_medible_componente
        (operacion_medible,funcion_wms,unidad_medida,factor) VALUES(?,?,?,1)""", [
            ('RECEPCION', 'OPERACIÓN DE RECEPCION', 'PALET'),
            ('RECEPCION', 'RECEPCION DE IMPORTADO NOA', 'PALET'),
            ('RECEPCION', 'REVISION', 'PALET'),
            ('RECEPCION', 'REVISION SECOS', 'PALET'),
            ('RECEPCION', 'REVISION NOA', 'PALET'),
            ('RECEPCION', 'REVISOR RECEPCION SECOS', 'PALET'),
            ('RECEPCION', 'REVISOR RECEPCION NOA', 'PALET'),
            ('RECEPCION', 'DESCARGA CAMION NOA', 'PALET'),
        ])
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_parametro
        (desc_funcion,medible,unidad_medida,observaciones)
        VALUES('CONTROL',1,'PLU',
        'Operación compuesta: Control CHP, Control CBF y Control de Hueco, medida por PLUs distintos.')""")
    await db.execute("""INSERT OR IGNORE INTO lab_funcion_equivalencia(desc_funcion,operacion_premio)
        VALUES('CONTROL','CONTROL')""")
    await db.executemany("""INSERT OR IGNORE INTO lab_operacion_medible_componente
        (operacion_medible,funcion_wms,unidad_medida,factor) VALUES(?,?,?,1)""", [
            ('CONTROL', 'CONTROL CHP', 'PLU'),
            ('CONTROL', 'CONTROL CBF', 'PLU'),
            ('CONTROL', 'CONTROL DE HUECO', 'PLU'),
        ])
    await db.execute("""INSERT OR IGNORE INTO lab_grupo_productivo_equivalencia(grupo_cache)
        SELECT DISTINCT TRIM(division) FROM lab_cache_agrupado
        WHERE TRIM(COALESCE(division,'')) <> ''""")
    # Clark Congelados nace con la misma configuración que Clark Refri. Los
    # umbrales y pagos quedan independientes desde este momento y se pueden
    # editar por separado en Parámetros y Escalas individuales.
    await db.execute("""INSERT OR IGNORE INTO lab_parametro_grupal
        (sector,funcion_legajero,turno,uc_por_operario,factor_ausentismo,premio_grupal,
         activo,operacion_medible,grupo_productivo_id,division_madre)
        SELECT sector,'CLARK CONGELADOS',turno,uc_por_operario,factor_ausentismo,premio_grupal,
               activo,operacion_medible,grupo_productivo_id,division_madre
        FROM lab_parametro_grupal
        WHERE sector='CD-REFRIGERADOS' AND funcion_legajero='AUTOELEVADORISTA (REFRIG)'
          AND UPPER(TRIM(operacion_medible))='CLARK'""")
    await db.execute("""INSERT OR IGNORE INTO lab_escala_individual_grupal
        (sector,funcion_legajero,turno,operacion_medible,division_madre,nivel,desde_uc,hasta_uc,
         premio,pct_sobre_anterior,activo,origen)
        SELECT sector,'CLARK CONGELADOS',turno,operacion_medible,division_madre,nivel,desde_uc,hasta_uc,
               premio,pct_sobre_anterior,activo,'copiada de AUTOELEVADORISTA (REFRIG)'
        FROM lab_escala_individual_grupal
        WHERE sector='CD-REFRIGERADOS' AND funcion_legajero='AUTOELEVADORISTA (REFRIG)'
          AND UPPER(TRIM(operacion_medible))='CLARK'""")
    await db.execute("""INSERT OR IGNORE INTO lab_polivalencia_regla
        (sector,funcion_legajero,operacion_madre,premio_centavos,activo)
        SELECT sector,'CLARK CONGELADOS',operacion_madre,premio_centavos,activo
        FROM lab_polivalencia_regla
        WHERE sector='CD-REFRIGERADOS' AND funcion_legajero='AUTOELEVADORISTA (REFRIG)'
          AND UPPER(TRIM(operacion_madre))='CLARK'""")
    await db.execute("""INSERT OR IGNORE INTO lab_polivalencia_regla_operacion(regla_id,operacion_b)
        SELECT destino.id,detalle.operacion_b
        FROM lab_polivalencia_regla origen
        JOIN lab_polivalencia_regla_operacion detalle ON detalle.regla_id=origen.id
        JOIN lab_polivalencia_regla destino
          ON destino.sector=origen.sector AND destino.funcion_legajero='CLARK CONGELADOS'
         AND destino.operacion_madre=origen.operacion_madre
        WHERE origen.sector='CD-REFRIGERADOS'
          AND origen.funcion_legajero='AUTOELEVADORISTA (REFRIG)'
          AND UPPER(TRIM(origen.operacion_madre))='CLARK'""")
    await db.commit()


async def _aplicar_perfiles_operativos(personas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Superpone perfiles locales auditables a la foto de legajero de RRHH."""
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_config(db)
        async with db.execute('''SELECT legajo,sector,funcion_legajero
                FROM lab_perfil_operativo_legajo WHERE activo=1''') as cur:
            overrides = {str(row['legajo']).strip(): dict(row) for row in await cur.fetchall()}
    resultado = []
    for persona in personas:
        item = dict(persona)
        override = overrides.get(str(item.get('legajo') or '').strip())
        if override:
            if str(override.get('sector') or '').strip():
                item['desc_sector_generico'] = str(override['sector']).strip()
            if str(override.get('funcion_legajero') or '').strip():
                item['desc_funcion'] = str(override['funcion_legajero']).strip()
        resultado.append(item)
    return resultado

@router.get("/mapa-polivalencia")
async def mapa_polivalencia(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT DISTINCT UPPER(TRIM(operacion_premio)) op FROM lab_evaluacion_premio WHERE TRIM(COALESCE(operacion_premio,''))<>'' UNION SELECT DISTINCT UPPER(TRIM(desc_funcion)) FROM lab_cache_agrupado WHERE TRIM(COALESCE(desc_funcion,''))<>'' ORDER BY 1") as cur:
            operaciones = [r[0] for r in await cur.fetchall()]
        async with db.execute("SELECT operacion_a,operacion_b,polivalencia,premio_centavos,updated_at FROM lab_mapa_polivalencia ORDER BY operacion_a,operacion_b") as cur:
            relaciones = [dict(r) for r in await cur.fetchall()]
    return {"operaciones": operaciones, "relaciones": relaciones}


@router.get('/polivalencia-reglas')
async def polivalencia_reglas(request: Request):
    """Reglas de polivalencia acotadas a sector, función y operación madre."""
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_config(db)
        async with db.execute('''SELECT DISTINCT sector,funcion_legajero,UPPER(TRIM(operacion_medible)) operacion_madre
                FROM lab_parametro_grupal
                WHERE activo=1 AND TRIM(COALESCE(operacion_medible,''))<>''
                ORDER BY sector,funcion_legajero,operacion_madre''') as cur:
            perfiles = [dict(row) for row in await cur.fetchall()]
        async with db.execute('''SELECT r.id,r.sector,r.funcion_legajero,r.operacion_madre,r.premio_centavos,r.activo,r.updated_at,
                GROUP_CONCAT(o.operacion_b, ' | ') operaciones_b
                FROM lab_polivalencia_regla r
                LEFT JOIN lab_polivalencia_regla_operacion o ON o.regla_id=r.id
                GROUP BY r.id ORDER BY r.sector,r.funcion_legajero,r.operacion_madre''') as cur:
            reglas = [dict(row) for row in await cur.fetchall()]
        async with db.execute("""SELECT DISTINCT UPPER(TRIM(desc_funcion)) operacion
                FROM lab_cache_agrupado WHERE TRIM(COALESCE(desc_funcion,''))<>'' ORDER BY operacion""") as cur:
            operaciones = [row['operacion'] for row in await cur.fetchall()]
    for regla in reglas:
        regla['operaciones_b'] = [x for x in str(regla.get('operaciones_b') or '').split(' | ') if x]
    return {'perfiles': perfiles, 'reglas': reglas, 'operaciones': operaciones,
            'nota': 'El pago se genera una sola vez por legajo, jornada y regla. Las operaciones B son opcionales: también dispara por cambio de función o división madre.'}


@router.put('/polivalencia-reglas')
async def guardar_polivalencia_regla(request: Request):
    await _admin(request)
    data = await request.json()
    sector = str(data.get('sector') or '').strip()
    funcion = str(data.get('funcion_legajero') or '').strip()
    madre = str(data.get('operacion_madre') or '').strip().upper()
    operaciones_b = sorted({str(item or '').strip().upper() for item in data.get('operaciones_b', []) if str(item or '').strip()})
    try:
        premio_centavos = int(data.get('premio_centavos', 0) or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, 'El importe debe ser un número válido.') from exc
    activo = bool(data.get('activo', True))
    if not sector or not funcion or not madre:
        raise HTTPException(400, 'Sector, función y operación madre son obligatorios.')
    if premio_centavos < 0:
        raise HTTPException(400, 'El importe no puede ser negativo.')
    prohibidas = {madre, 'CARGA CAMION', 'CARGA', 'TRASLADO'} if madre == 'PALETS OPERADOS' else {madre}
    operaciones_b = [item for item in operaciones_b if item not in prohibidas]
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_config(db)
        async with db.execute('''SELECT 1 FROM lab_parametro_grupal
                WHERE activo=1 AND sector=? AND funcion_legajero=?
                  AND UPPER(TRIM(operacion_medible))=? LIMIT 1''', (sector, funcion, madre)) as cur:
            if not await cur.fetchone():
                raise HTTPException(400, 'El perfil debe tener un parámetro grupal activo con esa operación madre.')
        await db.execute('''INSERT INTO lab_polivalencia_regla(sector,funcion_legajero,operacion_madre,premio_centavos,activo)
                VALUES(?,?,?,?,?) ON CONFLICT(sector,funcion_legajero,operacion_madre) DO UPDATE SET
                premio_centavos=excluded.premio_centavos,activo=excluded.activo,updated_at=CURRENT_TIMESTAMP''',
                (sector, funcion, madre, premio_centavos, 1 if activo else 0))
        async with db.execute('SELECT id FROM lab_polivalencia_regla WHERE sector=? AND funcion_legajero=? AND operacion_madre=?',
                              (sector, funcion, madre)) as cur:
            regla_id = int((await cur.fetchone())['id'])
        await db.execute('DELETE FROM lab_polivalencia_regla_operacion WHERE regla_id=?', (regla_id,))
        if operaciones_b:
            await db.executemany('INSERT INTO lab_polivalencia_regla_operacion(regla_id,operacion_b) VALUES(?,?)',
                                 [(regla_id, item) for item in operaciones_b])
        await db.execute('DELETE FROM lab_calculo_grupal_cache')
        await db.commit()
    return {'ok': True, 'regla_id': regla_id, 'operaciones_b': operaciones_b}


@router.get('/polivalencia-division-equivalencias')
async def polivalencia_division_equivalencias(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_config(db)
        async with db.execute('''SELECT operacion,grupo,division,activo,updated_at
                FROM lab_polivalencia_division_equivalencia
                ORDER BY operacion,grupo,CAST(division AS INTEGER),division''') as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    grupos: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row['operacion'], row['grupo'])
        item = grupos.setdefault(key, {'operacion': row['operacion'], 'grupo': row['grupo'],
                                       'divisiones': [], 'activo': bool(row['activo'])})
        item['divisiones'].append(row['division'])
        item['activo'] = item['activo'] and bool(row['activo'])
    return {'rows': list(grupos.values()), 'detalle': rows,
            'nota': 'Las divisiones en un mismo grupo no disparan polivalencia sólo para esa operación.'}


@router.put('/polivalencia-division-equivalencias')
async def guardar_polivalencia_division_equivalencia(request: Request):
    await _admin(request)
    data = await request.json()
    operacion = str(data.get('operacion') or '').strip().upper()
    grupo = str(data.get('grupo') or '').strip().upper()
    divisiones = sorted(_division_codigos(data.get('divisiones') or data.get('division') or []),
                        key=lambda item: (0, int(item)) if item.isdigit() else (1, item))
    activo = bool(data.get('activo', True))
    if not operacion or not grupo:
        raise HTTPException(400, 'Operación y grupo son obligatorios.')
    if len(divisiones) < 2 and activo:
        raise HTTPException(400, 'El grupo debe tener al menos dos divisiones activas.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        await db.execute('DELETE FROM lab_polivalencia_division_equivalencia WHERE operacion=? AND grupo=?',
                         (operacion, grupo))
        if divisiones:
            await db.executemany('''INSERT INTO lab_polivalencia_division_equivalencia
                    (operacion,grupo,division,activo,updated_at)
                    VALUES(?,?,?,?,CURRENT_TIMESTAMP)''',
                                 [(operacion, grupo, division, 1 if activo else 0) for division in divisiones])
        await db.execute('DELETE FROM lab_calculo_grupal_cache')
        await db.commit()
    return {'ok': True, 'operacion': operacion, 'grupo': grupo, 'divisiones': divisiones, 'activo': activo}


@router.get("/polivalencias")
async def polivalencias(request: Request, fecha_desde: str = '2026-08-01', fecha_hasta: str = '2026-08-31', legajo: str = '', sector: str = '', funcion: str = '', turno: str = ''):
    await _admin(request)
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as config_db:
        config_db.row_factory = aiosqlite.Row
        await _ensure_config(config_db)
        async with config_db.execute('''SELECT polivalencia_json,calculado_at
                FROM lab_calculo_grupal_cache WHERE fecha_desde=? AND fecha_hasta=?''',
                                     (desde, hasta)) as cur:
            calculo_cache = await cur.fetchone()
    rows = json.loads(calculo_cache['polivalencia_json']) if calculo_cache else []
    rows = [row for row in rows if (not legajo or legajo.strip() in str(row.get('legajo') or ''))
            and (not sector or row.get('sector','').upper() == sector.strip().upper())
            and (not funcion or row.get('funcion','').upper() == funcion.strip().upper())
            and (not turno or str(row.get('turno') or '') == turno.strip())]
    for row in rows:
        row['operacion_b'] = row.get('operaciones_b', '')
        row['operacion_madre'] = row.get('operacion_a', '')
        row['pago_polivalencia'] = int(row.get('premio_centavos') or 0) / 100
    return {'rows': rows, 'total': len(rows),
            'pago_total': sum(float(row.get('pago_polivalencia') or 0) for row in rows),
            'calculado_at': calculo_cache['calculado_at'] if calculo_cache else None,
            'nota': ('Polivalencias del último cálculo diario guardado.' if calculo_cache else
                     'Cálculo pendiente: abrí Cálculo grupal diario y usá Actualizar cálculo.')}

@router.get('/ausencias-config')
async def ausencias_config(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        await db.execute("INSERT OR IGNORE INTO lab_ausencia_config(cod_ausentismo,descripcion) SELECT DISTINCT COALESCE(NULLIF(ausencia,''),'SIN_CODIGO'),COALESCE(ausencia,'Sin ausencia informada') FROM lab_cache_grupal")
        # Completar también los tipos de los ausentes sin actividad WMS.
        async with db.execute("SELECT payload FROM lab_fuente_registro WHERE fuente='oracle.PV_DIA_LABORAL' AND snapshot=(SELECT snapshot FROM lab_fuente_lote WHERE fuente='oracle.PV_DIA_LABORAL' ORDER BY capturado DESC LIMIT 1)") as cur:
            jornadas = [json.loads(r[0]) for r in await cur.fetchall()]
        catalogo = {str(r.get('COD_AUSENTISMO') or '').strip(): str(r.get('DES_AUSENTISMO') or r.get('COD_AUSENTISMO') or '').strip()
                    for r in jornadas if str(r.get('COD_AUSENTISMO') or '').strip()}
        for codigo, descripcion in catalogo.items():
            await db.execute('''INSERT OR IGNORE INTO lab_ausencia_config(cod_ausentismo,descripcion,permitido)
                VALUES(?,?,COALESCE((SELECT permitido FROM lab_ausencia_config WHERE cod_ausentismo=?),0))''',
                (codigo, descripcion, descripcion))
        await db.commit(); db.row_factory=aiosqlite.Row
        async with db.execute('SELECT * FROM lab_ausencia_config ORDER BY descripcion,cod_ausentismo') as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        # Las antiguas claves por descripción siguen siendo compatibles, pero
        # se muestra la entrada por código cuando ya existe en el snapshot.
        rows = [r for r in rows if r['cod_ausentismo'] not in set(catalogo.values()) or r['cod_ausentismo'] in catalogo]
    return {'rows':rows}

@router.put('/ausencias-config')
async def guardar_ausencia_config(request: Request):
    await _admin(request); data=await request.json(); cod=str(data.get('cod_ausentismo') or '').strip()
    if not cod: raise HTTPException(400,'Código de ausencia requerido.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db); await db.execute("INSERT INTO lab_ausencia_config(cod_ausentismo,descripcion,permitido) VALUES(?,?,?) ON CONFLICT(cod_ausentismo) DO UPDATE SET descripcion=excluded.descripcion,permitido=excluded.permitido,updated_at=CURRENT_TIMESTAMP",(cod,str(data.get('descripcion') or cod),1 if data.get('permitido') else 0)); await db.commit()
    return {'ok':True}

async def _operaciones_grupales(db):
    async with db.execute("SELECT desc_funcion,unidad_medida FROM lab_funcion_parametro WHERE medible=1 AND unidad_medida IN ('PALET','BULTO','PLU','HUECO') ORDER BY desc_funcion") as cur:
        return {row[0]: row[1] for row in await cur.fetchall()}


async def _componentes_operaciones_medibles(db) -> dict[str, list[dict[str, Any]]]:
    """Componentes definidos en el catálogo, indexados por operación."""
    async with db.execute('''SELECT operacion_medible,funcion_wms,unidad_medida,factor
            FROM lab_operacion_medible_componente
            ORDER BY operacion_medible,funcion_wms''') as cur:
        rows = [dict(operacion_medible=row[0], funcion_wms=row[1],
                     unidad_medida=row[2], factor=row[3])
                for row in await cur.fetchall()]
    resultado: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        resultado[str(row['operacion_medible']).strip().upper()].append(row)
    return resultado


_RECEPCION_COMPONENTES = (
    'OPERACIÓN DE RECEPCION',
    'RECEPCION DE IMPORTADO NOA',
    'REVISION',
    'REVISION SECOS',
    'REVISION NOA',
    'REVISOR RECEPCION SECOS',
    'REVISOR RECEPCION NOA',
    'DESCARGA CAMION NOA',
)


async def _recalcular_palets_recepcion(db, desde: str, hasta: str) -> None:
    """Reconstruye RECEPCION por etiqueta física única.

    Una misma etiqueta puede figurar más de una vez en la extracción y puede
    pasar por Operación de recepción y Revisor. Se cuenta una sola unidad y
    se asigna al primer registro de la jornada; el desempate fijo evita que
    la producción individual y la grupal diverjan.
    """
    await db.execute('DELETE FROM lab_palets_recepcion WHERE fecha>=? AND fecha<=?', (desde, hasta))
    await db.execute('DELETE FROM lab_palets_recepcion_division WHERE fecha>=? AND fecha<=?', (desde, hasta))
    placeholders = ','.join('?' for _ in _RECEPCION_COMPONENTES)
    sql = f'''SELECT fecha,CAST(legajo AS TEXT),TRIM(desc_funcion),TRIM(pallet),
                     COALESCE(fyhini,''),COALESCE(fyhfin,''),CAST(id_etapa AS TEXT),
                     TRIM(COALESCE(division,''))
              FROM lab_etapa_detalle_raw
              WHERE fecha>=? AND fecha<=?
                AND UPPER(TRIM(desc_funcion)) IN ({placeholders})'''
    prioridad = {nombre: orden for orden, nombre in enumerate(_RECEPCION_COMPONENTES)}
    por_palet: dict[tuple[str, str, str], list[tuple[str, str, str, str, str]]] = defaultdict(list)
    async with db.execute(sql, (desde, hasta, *_RECEPCION_COMPONENTES)) as cur:
        async for fecha, legajo, funcion, pallet, inicio, fin, etapa, division in cur:
            etiqueta = str(pallet or '').strip()
            if etiqueta in {'', '0', '*', '-'}:
                continue
            funcion = str(funcion or '').strip().upper()
            division_norm = '6' if funcion in {
                'RECEPCION DE IMPORTADO NOA', 'REVISION NOA', 'REVISOR RECEPCION NOA',
                'DESCARGA CAMION NOA'
            } else str(division or '').strip()
            por_palet[(str(fecha), division_norm, etiqueta)].append((str(inicio or ''), funcion, str(legajo or ''),
                                                       str(fin or ''), str(etapa or '')))
    filas = []
    for (fecha, division, pallet), eventos in por_palet.items():
        # id_etapa solamente quita copias de la misma fila de origen; distintas
        # etapas del mismo pallet compiten para elegir el legajo acreditado.
        unicos = {(inicio, funcion, legajo, fin, etapa) for inicio, funcion, legajo, fin, etapa in eventos}
        ordenados = sorted(unicos, key=lambda item: (item[0] or '9999', prioridad.get(item[1], 99), item[2], item[4]))
        inicio, funcion, legajo, fin, _ = ordenados[0]
        funciones = ' | '.join(sorted({item[1] for item in ordenados}))
        filas.append((fecha, legajo, pallet, funcion, inicio, fin, funciones, division))
    if filas:
        await db.executemany('''INSERT OR REPLACE INTO lab_palets_recepcion
                (fecha,legajo,pallet,funcion_origen,inicio,fin,funciones,division)
                VALUES(?,?,?,?,?,?,?,?)''', filas)
        await db.executemany('''INSERT OR REPLACE INTO lab_palets_recepcion_division
                (fecha,legajo,pallet,funcion_origen,inicio,fin,funciones,division)
                VALUES(?,?,?,?,?,?,?,?)''', filas)
    await db.commit()


async def _asegurar_palets_recepcion(db, desde: str, hasta: str) -> None:
    async with db.execute('''SELECT COUNT(*) total,
                              SUM(CASE WHEN TRIM(COALESCE(division,''))<>'' THEN 1 ELSE 0 END) con_division
                          FROM lab_palets_recepcion_division WHERE fecha>=? AND fecha<=?''',
                          (desde, hasta)) as cur:
        row = await cur.fetchone()
        hay = int(row[0] or 0)
        con_division = int(row[1] or 0)
    if not hay or not con_division:
        await _recalcular_palets_recepcion(db, desde, hasta)


async def _catalogo_grupos_productivos(db):
    """Catálogo Oracle importado; no confundir con equivalencias de divisiones."""
    async with db.execute("SELECT snapshot FROM lab_fuente_lote WHERE fuente='oracle.PV_GRUPO_PRODUCTIVO_CAB' ORDER BY capturado DESC LIMIT 1") as cur:
        meta = await cur.fetchone()
    if not meta:
        return []
    async with db.execute("SELECT payload FROM lab_fuente_registro WHERE snapshot=? AND fuente='oracle.PV_GRUPO_PRODUCTIVO_CAB'", (meta[0],)) as cur:
        source = [json.loads(r[0]) for r in await cur.fetchall()]
    catalogo = {int(r['ID']): str(r['DESCRIPCION']).strip() for r in source}
    return [{'id': key, 'descripcion': value} for key, value in sorted(catalogo.items(), key=lambda x: x[1].casefold())]


def _identificar_grupos_parametros(parametros, catalogo):
    nombres = {r['id']: r['descripcion'] for r in catalogo}
    for parametro in parametros:
        group_id = parametro.get('grupo_productivo_id')
        parametro['grupo_productivo'] = nombres.get(group_id, f'Grupo {group_id} (fuera de catálogo)') if group_id is not None else ''


async def _nomina_grupal():
    async with aiosqlite.connect(RRHH_GRUPAL_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f'''SELECT legajo,nombre,desc_sector_generico,desc_funcion,active,
                fecha_ingreso,fecha_baja,desc_grupo_personal,proveedor,razon_social
                FROM rrhh_personas WHERE {RRHH_PROPIOS_FILTER}''') as cur:
            personas = [dict(row) for row in await cur.fetchall()]
    return await _aplicar_perfiles_operativos(personas)


async def _fijar_turnos_nuevos(db, personas, jornadas, snapshot):
    probables = inferir_turnos(jornadas)
    for person in personas:
        legajo = str(person['legajo']).strip()
        p = probables.get(legajo, {})
        await db.execute('''INSERT OR IGNORE INTO lab_turno_fijo_legajo
            (legajo,turno_fijo,turno_probable,dias_turno,total_dias,distribucion,snapshot,criterio)
            VALUES(?,?,?,?,?,?,?,?)''', (legajo, p.get('turno_probable', ''), p.get('turno_probable', ''),
            p.get('dias_turno', 0), p.get('total_dias', 0), json.dumps(p.get('distribucion', {})),
            snapshot, p.get('criterio', 'sin_historial')))
    await db.commit()
    async with db.execute('SELECT * FROM lab_turno_fijo_legajo ORDER BY legajo') as cur:
        return [dict(r) for r in await cur.fetchall()]


@router.get('/turnos-grupales')
async def turnos_grupales(request: Request):
    await _admin(request)
    personas = await _nomina_grupal()
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT snapshot FROM lab_fuente_lote WHERE fuente='oracle.PV_DIA_LABORAL' ORDER BY capturado DESC LIMIT 1") as cur:
            meta = await cur.fetchone()
        if not meta:
            raise HTTPException(409, 'No hay un snapshot local para estimar turnos.')
        async with db.execute("SELECT payload FROM lab_fuente_registro WHERE snapshot=? AND fuente='oracle.PV_DIA_LABORAL'", (meta[0],)) as cur:
            jornadas = [json.loads(r[0]) for r in await cur.fetchall()]
        rows = await _fijar_turnos_nuevos(db, personas, jornadas, meta[0])
    by_legajo = {str(p['legajo']).strip(): p for p in personas}
    rows = [dict(r, nombre=by_legajo[r['legajo']]['nombre'],
                 sector=by_legajo[r['legajo']]['desc_sector_generico'],
                 funcion_legajero=by_legajo[r['legajo']]['desc_funcion'])
            for r in rows if r['legajo'] in by_legajo]
    return {'rows': rows, 'sin_turno': sum(not r['turno_fijo'] for r in rows),
            'criterio': 'Mayor cantidad de días del snapshot completo; empate: uso más reciente, luego código menor. Se fija una vez y no cambia al filtrar fechas.'}


@router.put('/turnos-grupales')
async def guardar_turno_grupal(request: Request):
    await _admin(request)
    data = await request.json()
    legajo, turno = str(data.get('legajo') or '').strip(), str(data.get('turno_fijo') or '').strip()
    if not legajo or len(turno) > 20 or any(c.isspace() for c in turno):
        raise HTTPException(400, 'Legajo requerido y turno de hasta 20 caracteres, sin espacios.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        cursor = await db.execute("UPDATE lab_turno_fijo_legajo SET turno_fijo=?,origen='manual',updated_at=CURRENT_TIMESTAMP WHERE legajo=?", (turno, legajo))
        if cursor.rowcount != 1:
            raise HTTPException(404, 'Legajo no encontrado en la tabla de turnos.')
        await db.commit()
    return {'ok': True}


@router.get('/parametros-grupales')
async def parametros_grupales(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM lab_parametro_grupal ORDER BY sector,funcion_legajero,turno') as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        async with db.execute('''SELECT sector,funcion_legajero,turno,funcion_wms,unidad_medida,factor
                FROM lab_parametro_grupal_componente ORDER BY funcion_wms''') as cur:
            componentes = [dict(r) for r in await cur.fetchall()]
        componentes_catalogo = await _componentes_operaciones_medibles(db)
        por_parametro: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for componente in componentes:
            por_parametro[(componente['sector'], componente['funcion_legajero'], componente['turno'])].append(componente)
        for row in rows:
            propios = por_parametro.get((row['sector'], row['funcion_legajero'], row['turno']), [])
            predeterminados = componentes_catalogo.get(str(row.get('operacion_medible') or '').strip().upper(), [])
            row['componentes'] = propios or predeterminados
            row['componentes_origen'] = 'parametro' if propios else 'operacion' if predeterminados else ''
            row['division_madre'] = ','.join(_division_codigos(row.get('division_madre')))
            row['division_madre_descripcion'] = ' / '.join(
                DIVISIONES_DESCRIPCION.get(codigo, '') for codigo in _division_codigos(row['division_madre'])
                if DIVISIONES_DESCRIPCION.get(codigo, ''))
            row['division_madre_label'] = _divisiones_label(row['division_madre'])
        operaciones = await _operaciones_grupales(db)
        async with db.execute("SELECT DISTINCT UPPER(TRIM(desc_funcion)) FROM lab_cache_agrupado WHERE TRIM(COALESCE(desc_funcion,''))<>'' ORDER BY 1") as cur:
            funciones_wms = [row[0] for row in await cur.fetchall()]
        grupos = await _catalogo_grupos_productivos(db)
        _identificar_grupos_parametros(rows, grupos)
        divisiones = await _catalogo_divisiones(db)
    async with aiosqlite.connect(RRHH_GRUPAL_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"SELECT DISTINCT desc_sector_generico AS sector,desc_funcion AS funcion_legajero FROM rrhh_personas WHERE {RRHH_PROPIOS_FILTER} ORDER BY desc_sector_generico,desc_funcion") as cur:
            catalogo_base = [dict(r) for r in await cur.fetchall()]
    # El selector debe ofrecer también los perfiles operativos, aunque no
    # estén materializados como función en la fuente de RRHH.
    personas = await _nomina_grupal()
    catalogo = sorted({(str(x.get('sector') or x.get('desc_sector_generico') or ''),
                        str(x.get('funcion_legajero') or x.get('desc_funcion') or ''))
                       for x in [*catalogo_base, *personas] if (x.get('sector') or x.get('desc_sector_generico')) and (x.get('funcion_legajero') or x.get('desc_funcion'))},
                      key=lambda item: (item[0], item[1]))
    catalogo = [{'sector': sector, 'funcion_legajero': funcion} for sector, funcion in catalogo]
    return {'rows': rows, 'catalogo': catalogo, 'grupos_productivos': grupos,
            'divisiones': divisiones,
            'operaciones': [{'operacion': op, 'unidad_medida': unidad} for op, unidad in operaciones.items()],
            'funciones_wms': funciones_wms,
            'componentes_operaciones': componentes_catalogo}


@router.get('/calculo-grupal')
async def calculo_grupal(request: Request, fecha_desde: str='2026-08-01', fecha_hasta: str='2026-08-31'):
    await _admin(request)
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    if desde > hasta:
        raise HTTPException(400, 'La fecha desde debe ser anterior o igual a la fecha hasta.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM lab_parametro_grupal WHERE activo=1 ORDER BY sector,funcion_legajero,turno') as cur:
            parametros = [dict(r) for r in await cur.fetchall()]
        async with db.execute('SELECT sector,funcion_legajero,turno,funcion_wms,unidad_medida,factor FROM lab_parametro_grupal_componente') as cur:
            componentes = [dict(r) for r in await cur.fetchall()]
        componentes_catalogo = await _componentes_operaciones_medibles(db)
        componentes_por_parametro: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for componente in componentes:
            componentes_por_parametro[(componente['sector'], componente['funcion_legajero'], componente['turno'])].append(componente)
        for parametro in parametros:
            propios = componentes_por_parametro.get((parametro['sector'], parametro['funcion_legajero'], parametro['turno']), [])
            parametro['componentes'] = propios or componentes_catalogo.get(
                str(parametro.get('operacion_medible') or '').strip().upper(), [])
        operaciones = await _operaciones_grupales(db)
        grupos = await _catalogo_grupos_productivos(db)
        _identificar_grupos_parametros(parametros, grupos)
        async with db.execute('''SELECT r.sector,r.funcion_legajero,r.operacion_madre,o.operacion_b
                FROM lab_polivalencia_regla r
                LEFT JOIN lab_polivalencia_regla_operacion o ON o.regla_id=r.id
                WHERE r.activo=1''') as cur:
            relaciones: dict[tuple[str, str, str], set[str]] = defaultdict(set)
            for row in await cur.fetchall():
                clave_regla = (str(row['sector']).strip().upper(), str(row['funcion_legajero']).strip().upper(),
                               str(row['operacion_madre']).strip().upper())
                if row['operacion_b']:
                    relaciones[clave_regla].add(str(row['operacion_b']).strip().upper())
        # Polivalencia se paga una sola vez por jornada, al mismo valor que el
        # premio grupal configurado para ese perfil y turno. Los importes
        # históricos de lab_polivalencia_regla ya no fijan el pago.
        premios_polivalencia = {
            (str(p.get('sector') or '').strip().upper(),
             str(p.get('funcion_legajero') or '').strip().upper(),
             str(p.get('operacion_medible') or '').strip().upper(),
             str(p.get('turno') or '').strip()): int(round(float(p.get('premio_grupal') or 0) * 100))
            for p in parametros
        }
        async with db.execute('''SELECT operacion,grupo,division
                FROM lab_polivalencia_division_equivalencia
                WHERE activo=1
                ORDER BY operacion,grupo,division''') as cur:
            equivalencias_division: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
            for row in await cur.fetchall():
                equivalencias_division[str(row['operacion']).strip().upper()][str(row['grupo']).strip()].add(
                    str(row['division']).strip())
        async with db.execute('SELECT cod_ausentismo,permitido FROM lab_ausencia_config') as cur:
            ausencias = {str(r[0]): bool(r[1]) for r in await cur.fetchall()}
        async with db.execute("SELECT snapshot FROM lab_fuente_lote WHERE fuente='oracle.PV_DIA_LABORAL' ORDER BY capturado DESC LIMIT 1") as cur:
            snapshot_row = await cur.fetchone()
        if not snapshot_row:
            raise HTTPException(409, 'No hay un snapshot local de asistencia PV_DIA_LABORAL.')
        snapshot = snapshot_row[0]
        async with db.execute("SELECT payload FROM lab_fuente_registro WHERE snapshot=? AND fuente='oracle.PV_DIA_LABORAL'", (snapshot,)) as cur:
            jornadas = [json.loads(r[0]) for r in await cur.fetchall()]
        async with db.execute('''SELECT fecha,legajo,desc_funcion,division,sector,palets,plus,cantidad
                FROM lab_cache_agrupado WHERE fecha>=? AND fecha<=?
                UNION ALL
                SELECT fecha,legajo,desc_funcion,division,sector,palets,plus,cantidad
                FROM (
                    SELECT fecha,legajo,desc_funcion,division,sector,palets,plus,cantidad,
                           ROW_NUMBER() OVER (
                               PARTITION BY fecha,legajo,desc_funcion,division,sector,origen
                               ORDER BY created_at DESC,snapshot DESC
                           ) AS rn
                    FROM lab_cache_agrupado_ajuste WHERE fecha>=? AND fecha<=?
                ) WHERE rn=1''',
                              (desde, hasta, desde, hasta)) as cur:
            produccion = [dict(r) for r in await cur.fetchall()]
        # PALETS OPERADOS es la única medición de Carga: cada contribución
        # validada de carga/traslado vale un palet. Se agrega como actividad
        # sintética para que calcular_grupal conserve nómina, ausencias,
        # factor y polivalencias.
        if any(str(p.get('operacion_medible') or '').strip().upper() == 'PALETS OPERADOS'
               for p in parametros):
            async with db.execute('''SELECT COUNT(*) FROM lab_palets_carga_traslado
                    WHERE fecha>=? AND fecha<=?''', (desde, hasta)) as cur:
                hay_palets_unificados = int((await cur.fetchone())[0] or 0)
            if not hay_palets_unificados:
                await _recalcular_palets_carga_traslado(db, desde, hasta)
            async with db.execute('''SELECT fecha,legajo,TRIM(COALESCE(division,'')) AS division,COUNT(*) AS palets
                    FROM lab_palets_carga_traslado
                    WHERE fecha>=? AND fecha<=?
                    GROUP BY fecha,legajo,TRIM(COALESCE(division,''))''', (desde, hasta)) as cur:
                produccion.extend({
                    'fecha': row['fecha'], 'legajo': row['legajo'],
                    'desc_funcion': 'PALETS OPERADOS', 'palets': row['palets'],
                    'division': row['division'] or '', 'sector': '*', 'plus': 0, 'cantidad': 0,
                } for row in await cur.fetchall())
        # RECEPCION no suma las filas de cada etapa: toma el pallet físico
        # único y lo atribuye al primer legajo que lo registró. Reemplazar los
        # componentes por la actividad sintética impide duplicarlo en la meta.
        if any(str(p.get('operacion_medible') or '').strip().upper() == 'RECEPCION'
               for p in parametros):
            await _asegurar_palets_recepcion(db, desde, hasta)
            async with db.execute('''SELECT fecha,legajo,TRIM(COALESCE(division,'')) AS division,COUNT(*) palets
                    FROM lab_palets_recepcion_division WHERE fecha>=? AND fecha<=?
                    GROUP BY fecha,legajo,TRIM(COALESCE(division,''))''', (desde, hasta)) as cur:
                produccion.extend({
                    'fecha': row['fecha'], 'legajo': row['legajo'],
                    'desc_funcion': 'RECEPCION', 'palets': row['palets'],
                    'division': row['division'] or '', 'sector': '*', 'plus': 0, 'cantidad': 0,
                } for row in await cur.fetchall())
            for parametro in parametros:
                if str(parametro.get('operacion_medible') or '').strip().upper() == 'RECEPCION':
                    parametro['polivalencia_componentes'] = parametro.get('componentes', [])
                    parametro['componentes'] = [{'funcion_wms': 'RECEPCION', 'unidad_medida': 'PALET', 'factor': 1}]
    personas = await _nomina_grupal()
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        turnos = await _fijar_turnos_nuevos(db, personas, jornadas, snapshot)
    result = calcular_grupal(personas, jornadas, produccion, parametros, operaciones,
                             relaciones, ausencias, desde, hasta, {r['legajo']: r['turno_fijo'] for r in turnos},
                             equivalencias_division)
    result['snapshot'] = snapshot
    result['nota'] = 'Plantel fijo por sector/función y turno madre guardado. Toda actividad del legajo, aunque se ejecute en otro turno, se atribuye una sola vez al turno madre. Sin turno fijo: revisar la lista pendiente y asignar en Parámetros grupales. El legajero activo es el actual; no reconstruye transferencias históricas.'
    # La polivalencia ya está determinada por el cálculo diario. Se guarda una
    # vez por perfil, legajo y jornada para que Premios Totales sea una lectura
    # inmediata y nunca vuelva a recorrer el cache WMS al abrirse.
    actividades_por_jornada: dict[tuple[str, str], set[str]] = defaultdict(set)
    for actividad in produccion:
        actividades_por_jornada[(str(actividad.get('fecha') or ''), str(actividad.get('legajo') or ''))].add(
            str(actividad.get('desc_funcion') or '').strip().upper())
    polivalencias_cache: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for persona in result.get('nivel_3', []):
        clave_regla = (str(persona.get('sector') or '').strip().upper(),
                       str(persona.get('funcion_legajero') or '').strip().upper(),
                       str(persona.get('operacion') or '').strip().upper())
        clave_pago = (*clave_regla, str(persona.get('turno_fijo') or '').strip())
        premio_centavos = premios_polivalencia.get(clave_pago, 0)
        if not (persona.get('es_polivalencia') and persona.get('aplica_grupo')
                and persona.get('asistencia') == 'Presente'):
            continue
        clave_evento = (str(persona.get('fecha') or ''), str(persona.get('legajo') or ''), *clave_regla)
        operaciones_b = sorted({
            *(actividades_por_jornada[clave_evento[:2]] & relaciones.get(clave_regla, set())),
            *[str(item).strip().upper() for item in persona.get('polivalencia_operaciones', []) if str(item).strip()],
        })
        polivalencias_cache[clave_evento] = {
            'fecha': clave_evento[0], 'legajo': clave_evento[1],
            'nombre': persona.get('nombre', ''), 'sector': persona.get('sector', ''),
            'funcion': persona.get('funcion_legajero', ''),
            'turno': persona.get('turno_fijo', ''), 'operacion_a': persona.get('operacion', ''),
            'operaciones_b': ' · '.join(operaciones_b),
            'motivos': ' · '.join(persona.get('polivalencia_motivos', [])),
            'premio_centavos': premio_centavos,
        }
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await db.execute('''INSERT INTO lab_calculo_grupal_cache
                (fecha_desde,fecha_hasta,nivel_1_json,nivel_2_json,nivel_3_json,polivalencia_json)
                VALUES(?,?,?,?,?,?) ON CONFLICT(fecha_desde,fecha_hasta) DO UPDATE SET
                nivel_1_json=excluded.nivel_1_json,nivel_2_json=excluded.nivel_2_json,
                nivel_3_json=excluded.nivel_3_json,polivalencia_json=excluded.polivalencia_json,
                calculado_at=CURRENT_TIMESTAMP''',
                (desde, hasta, json.dumps(result.get('nivel_1', [])),
                 json.dumps(result.get('nivel_2', [])),
                 json.dumps(result.get('nivel_3', [])),
                 json.dumps(list(polivalencias_cache.values()))))
        await db.commit()
    return result



def _porcentajes_individuales_default() -> list[float]:
    return [10.0, 5.0, 10.0, 15.0, 20.0]


def _tramos_individuales_desde_porcentajes(base: float, porcentajes: list[float]) -> list[dict[str, Any]]:
    valor = float(base or 0)
    desde_por_nivel: list[int] = []
    porcentajes = (porcentajes + _porcentajes_individuales_default())[:5]
    for pct in porcentajes:
        valor = valor * (1 + float(pct or 0) / 100)
        # Evita que residuos binarios (por ejemplo 1300 × 1,10 =
        # 1430,0000000000002) agreguen una UC inexistente al usar ceil.
        desde_por_nivel.append(int(math.ceil(valor - 1e-9)))
    return [{
        'nivel': nivel,
        'pct_sobre_anterior': float(porcentajes[nivel - 1] or 0),
        'desde_uc': desde_por_nivel[nivel - 1],
        'hasta_uc': desde_por_nivel[nivel] if nivel < 5 else 0,
    } for nivel in range(1, 6)]


def _escala_individual_desde(base: float, nivel: int) -> int:
    # Compatibilidad con usos anteriores: usa el patrón vigente
    # 10% sobre grupal y luego 5%, 10%, 15%, 20% sobre nivel anterior.
    return _tramos_individuales_desde_porcentajes(base, _porcentajes_individuales_default())[nivel - 1]['desde_uc']


@router.post('/escalas-individuales-grupales/generar')
async def generar_escalas_individuales_grupales(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_config(db)
        async with db.execute("""SELECT sector,funcion_legajero,turno,UPPER(TRIM(operacion_medible)) operacion_medible,
                       COALESCE(division_madre,'') division_madre,uc_por_operario
                FROM lab_parametro_grupal
                WHERE activo=1 AND TRIM(COALESCE(operacion_medible,''))<>'' AND COALESCE(uc_por_operario,0)>0
                ORDER BY sector,funcion_legajero,turno""") as cur:
            params = [dict(row) for row in await cur.fetchall()]
        rows = []
        for par in params:
            base = float(par['uc_por_operario'] or 0)
            for tramo in _tramos_individuales_desde_porcentajes(base, _porcentajes_individuales_default()):
                rows.append((par['sector'], par['funcion_legajero'], str(par['turno']), par['operacion_medible'],
                             par['division_madre'] or '', tramo['nivel'], tramo['desde_uc'], tramo['hasta_uc'],
                             0, tramo['pct_sobre_anterior'], 1, 'generada'))
        if rows:
            await db.executemany("""INSERT INTO lab_escala_individual_grupal
                    (sector,funcion_legajero,turno,operacion_medible,division_madre,nivel,desde_uc,hasta_uc,premio,pct_sobre_anterior,activo,origen)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(sector,funcion_legajero,turno,operacion_medible,division_madre,nivel) DO UPDATE SET
                    desde_uc=excluded.desde_uc,hasta_uc=excluded.hasta_uc,pct_sobre_anterior=excluded.pct_sobre_anterior,activo=excluded.activo,
                    origen=excluded.origen,updated_at=CURRENT_TIMESTAMP""", rows)
        await db.commit()
    return {'ok': True, 'perfiles': len(params), 'filas': len(rows)}


@router.get('/escalas-individuales-grupales')
async def escalas_individuales_grupales(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_config(db)
        async with db.execute("""SELECT e.*,p.uc_por_operario,p.factor_ausentismo,p.premio_grupal
                FROM lab_escala_individual_grupal e
                LEFT JOIN lab_parametro_grupal p ON p.sector=e.sector AND p.funcion_legajero=e.funcion_legajero AND p.turno=e.turno
                ORDER BY e.sector,e.funcion_legajero,e.operacion_medible,e.division_madre,e.nivel,CAST(e.turno AS INTEGER),e.turno""") as cur:
            rows_raw = [dict(row) for row in await cur.fetchall()]
        async with db.execute("""SELECT DISTINCT sector,funcion_legajero FROM lab_parametro_grupal
                WHERE activo=1 ORDER BY sector,funcion_legajero""") as cur:
            filtros = [dict(row) for row in await cur.fetchall()]
    agrupadas: dict[tuple[str, str, str, str, int], dict[str, Any]] = {}
    for row in rows_raw:
        key = (row['sector'], row['funcion_legajero'], row['operacion_medible'], row.get('division_madre') or '', int(row['nivel'] or 0))
        item = agrupadas.setdefault(key, {**row, 'turnos': [], 'turno': 'Todos'})
        item['turnos'].append(str(row.get('turno') or ''))
        # Si algún turno fue editado manualmente, conservar el origen manual en la vista agrupada.
        if row.get('origen') == 'manual':
            item['origen'] = 'manual'
    rows = []
    for item in agrupadas.values():
        item['turnos'] = sorted(set(item['turnos']), key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)))
        item['turnos_label'] = ', '.join(item['turnos'])
        item['division_madre_label'] = _divisiones_label(item.get('division_madre'))
        rows.append(item)
    rows.sort(key=lambda x: (x['sector'], x['funcion_legajero'], x['operacion_medible'], x.get('division_madre') or '', int(x['nivel'] or 0)))
    return {'rows': rows, 'filtros': filtros}


@router.put('/escalas-individuales-grupales')
async def guardar_escala_individual_grupal(request: Request):
    await _admin(request)
    data = await request.json()
    sector = str(data.get('sector') or '').strip()
    funcion = str(data.get('funcion_legajero') or '').strip()
    operacion = str(data.get('operacion_medible') or '').strip().upper()
    division = str(data.get('division_madre') or '').strip()
    if not sector or not funcion or not operacion:
        raise HTTPException(400, 'Sector, función y operación son obligatorios.')
    modo_porcentajes = data.get('modo') == 'porcentajes_perfil' or isinstance(data.get('niveles'), list)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_config(db)
        if modo_porcentajes:
            niveles_raw = data.get('niveles') or []
            porcentajes_por_nivel: dict[int, float] = {}
            premios_por_nivel: dict[int, float] = {}
            for item in niveles_raw:
                try:
                    nivel = int(item.get('nivel'))
                    pct = float(item.get('pct_sobre_anterior') or 0)
                    premio = float(item.get('premio') or 0)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, 'Niveles con valores inválidos.') from exc
                if nivel < 1 or nivel > 5 or pct < 0 or not math.isfinite(pct) or not math.isfinite(premio):
                    raise HTTPException(400, 'Los porcentajes deben ser mayores o iguales a cero y niveles 1 a 5.')
                porcentajes_por_nivel[nivel] = pct
                premios_por_nivel[nivel] = premio
            if set(porcentajes_por_nivel) != {1, 2, 3, 4, 5}:
                raise HTTPException(400, 'Debe enviarse la configuración de los 5 niveles.')
            async with db.execute("""SELECT sector,funcion_legajero,turno,UPPER(TRIM(operacion_medible)) operacion_medible,
                           COALESCE(division_madre,'') division_madre,uc_por_operario
                    FROM lab_parametro_grupal
                    WHERE activo=1 AND sector=? AND funcion_legajero=? AND UPPER(TRIM(operacion_medible))=?
                      AND COALESCE(division_madre,'')=? AND COALESCE(uc_por_operario,0)>0
                    ORDER BY CAST(turno AS INTEGER),turno""", (sector, funcion, operacion, division)) as cur:
                params = [dict(row) for row in await cur.fetchall()]
            if not params:
                raise HTTPException(404, 'No hay parámetros grupales activos para ese perfil.')
            rows = []
            porcentajes = [porcentajes_por_nivel[n] for n in range(1, 6)]
            for par in params:
                for tramo in _tramos_individuales_desde_porcentajes(float(par['uc_por_operario'] or 0), porcentajes):
                    nivel = int(tramo['nivel'])
                    rows.append((sector, funcion, str(par['turno']), operacion, division, nivel,
                                 tramo['desde_uc'], tramo['hasta_uc'], premios_por_nivel.get(nivel, 0),
                                 tramo['pct_sobre_anterior'], 1, 'manual'))
            await db.executemany("""INSERT INTO lab_escala_individual_grupal
                    (sector,funcion_legajero,turno,operacion_medible,division_madre,nivel,desde_uc,hasta_uc,premio,pct_sobre_anterior,activo,origen)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(sector,funcion_legajero,turno,operacion_medible,division_madre,nivel) DO UPDATE SET
                    desde_uc=excluded.desde_uc,hasta_uc=excluded.hasta_uc,premio=excluded.premio,
                    pct_sobre_anterior=excluded.pct_sobre_anterior,activo=excluded.activo,origen='manual',updated_at=CURRENT_TIMESTAMP""", rows)
            await db.commit()
            return {'ok': True, 'turnos_actualizados': len(params), 'filas': len(rows)}

        required = ['turno', 'nivel']
        if any(str(data.get(key, '')).strip() == '' for key in required):
            raise HTTPException(400, 'Faltan datos de clave de la escala.')
        try:
            desde = float(data.get('desde_uc') or 0)
            hasta = float(data.get('hasta_uc') or 0)
            premio = float(data.get('premio') or 0)
            pct = float(data.get('pct_sobre_anterior') or 0)
            nivel = int(data.get('nivel'))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, 'Valores numéricos inválidos.') from exc
        await db.execute("""INSERT INTO lab_escala_individual_grupal
                (sector,funcion_legajero,turno,operacion_medible,division_madre,nivel,desde_uc,hasta_uc,premio,pct_sobre_anterior,activo,origen)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(sector,funcion_legajero,turno,operacion_medible,division_madre,nivel) DO UPDATE SET
                desde_uc=excluded.desde_uc,hasta_uc=excluded.hasta_uc,premio=excluded.premio,
                pct_sobre_anterior=excluded.pct_sobre_anterior,activo=excluded.activo,origen='manual',updated_at=CURRENT_TIMESTAMP""",
                (sector, funcion, str(data['turno']).strip(), operacion, division,
                 nivel, desde, hasta, premio, pct, 1 if data.get('activo', True) else 0, 'manual'))
        await db.commit()
    return {'ok': True}

def _nivel_individual_grupal(uc: float, escalas: list[dict[str, Any]]) -> int:
    nivel = 0
    for escala in escalas:
        desde = float(escala.get('desde_uc') or 0)
        hasta = float(escala.get('hasta_uc') or 0)
        if uc >= desde and (hasta <= 0 or uc < hasta):
            nivel = max(nivel, int(escala.get('nivel') or 0))
    return nivel


@router.get('/participacion-escalas-individuales')
async def participacion_escalas_individuales(request: Request, fecha_desde: str='2026-08-01', fecha_hasta: str='2026-08-31', sector: str='', funcion_legajero: str=''):
    await _admin(request)
    result = await calculo_grupal(request, fecha_desde, fecha_hasta)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_config(db)
        async with db.execute("""SELECT * FROM lab_escala_individual_grupal WHERE activo=1
                ORDER BY sector,funcion_legajero,turno,operacion_medible,division_madre,nivel""") as cur:
            escala_rows = [dict(row) for row in await cur.fetchall()]
        async with db.execute("""SELECT DISTINCT sector,funcion_legajero FROM lab_escala_individual_grupal
                WHERE activo=1 ORDER BY sector,funcion_legajero""") as cur:
            filtros = [dict(row) for row in await cur.fetchall()]
    escalas: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in escala_rows:
        escalas[(row['sector'], row['funcion_legajero'], str(row['turno']), row['operacion_medible'], row['division_madre'] or '')].append(row)
    diarios: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for persona in result.get('nivel_3', []):
        if sector and persona.get('sector') != sector:
            continue
        if funcion_legajero and persona.get('funcion_legajero') != funcion_legajero:
            continue
        clave_escala = (persona.get('sector'), persona.get('funcion_legajero'), str(persona.get('turno')), str(persona.get('operacion') or '').upper(), persona.get('division_madre') or '')
        escala = escalas.get(clave_escala, [])
        if not escala:
            continue
        if not (persona.get('aplica_grupo') and persona.get('asistencia') == 'Presente'):
            continue
        key = (persona.get('fecha'), persona.get('sector'), persona.get('funcion_legajero'), str(persona.get('turno')))
        item = diarios.setdefault(key, {'fecha': persona.get('fecha'), 'sector': persona.get('sector'), 'funcion_legajero': persona.get('funcion_legajero'),
                                        'turno': str(persona.get('turno')), 'evaluados': 0, 'grupal': 0, 'nivel_0': 0,
                                        'nivel_1': 0, 'nivel_2': 0, 'nivel_3': 0, 'nivel_4': 0, 'nivel_5': 0})
        nivel = _nivel_individual_grupal(float(persona.get('uc_brutas') or 0), escala)
        item['evaluados'] += 1
        if persona.get('cobra'):
            item['grupal'] += 1
        if nivel <= 0:
            item['nivel_0'] += 1
        else:
            for alcanzado in range(1, nivel + 1):
                item[f'nivel_{alcanzado}'] += 1
    rows = sorted(diarios.values(), key=lambda x: (x['sector'], x['funcion_legajero'], x['turno'], x['fecha']))
    resumen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row['sector'], row['funcion_legajero'], row['turno'])
        item = resumen.setdefault(key, {'sector': row['sector'], 'funcion_legajero': row['funcion_legajero'], 'turno': row['turno'], 'dias': 0, 'evaluados': 0, 'grupal': 0,
                                        'nivel_0': 0, 'nivel_1': 0, 'nivel_2': 0, 'nivel_3': 0, 'nivel_4': 0, 'nivel_5': 0})
        item['dias'] += 1
        for field in ['evaluados', 'grupal', 'nivel_0', 'nivel_1', 'nivel_2', 'nivel_3', 'nivel_4', 'nivel_5']:
            item[field] += int(row.get(field) or 0)
    return {'rows': rows, 'resumen': sorted(resumen.values(), key=lambda x: (x['sector'], x['funcion_legajero'], x['turno'])), 'filtros': filtros,
            'nota': 'Grupal cuenta eventos legajo-día que cobran grupal en el cálculo grupal. N1 a N5 son acumulados por umbral individual.'}


@router.get('/umbrales-grupales')
async def umbrales_grupales(request: Request, fecha_desde: str='2026-08-01', fecha_hasta: str='2026-08-31',
                            sector: str='', operacion: str='', funcion_legajero: str='', excluir_fines: int=1):
    await _admin(request)
    result = await calculo_grupal(request, fecha_desde, fecha_hasta)
    dias = result.get('nivel_2', [])
    sector = str(sector or '').strip()
    operacion = str(operacion or '').strip().upper()
    funcion_legajero = str(funcion_legajero or '').strip()
    excluir = bool(int(excluir_fines or 0))

    def es_fin(fecha: str) -> bool:
        try:
            return datetime.strptime(str(fecha).replace('-', ''), '%Y%m%d').weekday() >= 5
        except Exception:
            return False

    filtros_base = []
    filtros_seen = set()
    for r in dias:
        key = (r.get('sector') or '', r.get('funcion_legajero') or '', str(r.get('operacion') or '').upper(),
               ','.join(_division_codigos(r.get('division_madre'))))
        if key in filtros_seen:
            continue
        filtros_seen.add(key)
        filtros_base.append(dict(sector=key[0], funcion_legajero=key[1], operacion=key[2],
                                 division_madre=key[3], division_madre_label=_divisiones_label(key[3])))

    filtrados = []
    for row in dias:
        if sector and row.get('sector') != sector:
            continue
        if operacion and str(row.get('operacion') or '').upper() != operacion:
            continue
        if funcion_legajero and row.get('funcion_legajero') != funcion_legajero:
            continue
        if excluir and es_fin(row.get('fecha')):
            continue
        nomina = float(row.get('nomina_computable') or 0)
        factor = float(row.get('factor_ausentismo') or 0)
        produccion = float(row.get('uc_computables') or 0)
        divisor = nomina * max(0.000001, 1 - factor / 100)
        if not row.get('evaluable') or nomina <= 0 or divisor <= 0:
            continue
        item = dict(row)
        item['division_madre'] = ','.join(_division_codigos(item.get('division_madre')))
        item['division_madre_label'] = _divisiones_label(item['division_madre'])
        item['umbral_uc'] = produccion / divisor
        item['divisor_umbral'] = divisor
        item['cobra_actual'] = bool(row.get('cumple'))
        filtrados.append(item)

    porcentajes_objetivo = (25, 50, 75)

    def valores_perfil(items: list[dict[str, Any]]) -> list[float]:
        return sorted([float(x.get('umbral_uc') or 0) for x in items], reverse=True)

    def resumen_para(label: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        valores = valores_perfil(items)
        thresholds = {}
        referencias = []
        for porcentaje in porcentajes_objetivo:
            # Valores ordenados de mayor a menor: el valor de la posición N es
            # el umbral que deja cobrar N jornadas. N depende del período real,
            # no de una hipótesis fija de 30 días.
            dias_objetivo = math.ceil(len(valores) * porcentaje / 100) if valores else 0
            umbral = math.ceil(valores[dias_objetivo - 1]) if dias_objetivo else None
            thresholds[f'umbral_{porcentaje}'] = umbral
            thresholds[f'dias_objetivo_{porcentaje}'] = dias_objetivo
            if umbral is not None:
                referencias.append({'porcentaje': porcentaje, 'dias': dias_objetivo, 'uc': umbral})
        objetivos_activos = [float(x.get('objetivo_por_operario') or 0) for x in items if x.get('objetivo_por_operario') is not None]
        objetivo_unico = sorted(set(round(x, 6) for x in objetivos_activos))
        actual = objetivos_activos[0] if len(objetivo_unico) == 1 else (sum(objetivos_activos) / len(objetivos_activos) if objetivos_activos else 0)
        return {
            'turno': label,
            'perfil': label,
            'dias_evaluados': len(items),
            'dias_cobra_actual': sum(1 for x in items if x.get('cobra_actual')),
            'objetivo_actual_promedio': round(actual, 2),
            'objetivos_activos': objetivo_unico,
            'mejor_umbral': math.ceil(max(valores)) if valores else None,
            'peor_umbral': math.ceil(min(valores)) if valores else None,
            'mediana_umbral': math.ceil(sorted(valores)[len(valores)//2]) if valores else None,
            'referencias': referencias,
            **thresholds,
        }

    # El gráfico compara perfiles por día calendario, no por cantidad de
    # turnos ni por filas disponibles. Así agosto+septiembre siempre aporta
    # 61 días, o 43 días hábiles cuando se excluyen sábados y domingos.
    inicio = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
    fin = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
    dias_periodo = []
    cursor_fecha = inicio
    while cursor_fecha <= fin:
        if not excluir or cursor_fecha.weekday() < 5:
            dias_periodo.append(cursor_fecha.strftime('%Y%m%d'))
        cursor_fecha += timedelta(days=1)

    claves_perfil: set[tuple[str, str, str, str]] = set()
    for row in dias:
        if sector and row.get('sector') != sector:
            continue
        if operacion and str(row.get('operacion') or '').upper() != operacion:
            continue
        if funcion_legajero and row.get('funcion_legajero') != funcion_legajero:
            continue
        claves_perfil.add((row.get('sector') or '', row.get('funcion_legajero') or '',
                            str(row.get('operacion') or '').upper(), ','.join(_division_codigos(row.get('division_madre')))))

    por_perfil_fecha: dict[tuple[str, str, str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in filtrados:
        key = (row.get('sector') or '', row.get('funcion_legajero') or '', str(row.get('operacion') or '').upper(), row.get('division_madre') or '')
        claves_perfil.add(key)
        por_perfil_fecha[key][str(row.get('fecha') or '')].append(row)

    resumen = []
    series = []
    for key in sorted(claves_perfil):
        sec, fun, op, div = key
        label = ' · '.join(x for x in [sec, fun, _operacion_total(op), _divisiones_label(div) if div else ''] if x)
        items = []
        filas_por_fecha = por_perfil_fecha.get(key, {})
        objetivos_perfil = [float(x.get('objetivo_por_operario') or 0) for filas in filas_por_fecha.values() for x in filas if x.get('objetivo_por_operario') is not None]
        objetivo_defecto = sum(objetivos_perfil) / len(objetivos_perfil) if objetivos_perfil else 0
        for fecha in dias_periodo:
            filas_dia = filas_por_fecha.get(fecha, [])
            divisor_dia = sum(float(x.get('divisor_umbral') or 0) for x in filas_dia)
            produccion_dia = sum(float(x.get('uc_computables') or 0) for x in filas_dia)
            objetivo_dia = (sum(float(x.get('objetivo_por_operario') or 0) * float(x.get('divisor_umbral') or 0) for x in filas_dia) / divisor_dia) if divisor_dia else objetivo_defecto
            umbral_dia = produccion_dia / divisor_dia if divisor_dia else 0
            items.append({'fecha': fecha, 'umbral_uc': umbral_dia,
                          'objetivo_por_operario': objetivo_dia,
                          'cobra_actual': bool(divisor_dia and umbral_dia >= objetivo_dia),
                          'con_datos': bool(divisor_dia)})
        valores = valores_perfil(items)
        item_resumen = resumen_para(label, items)
        item_resumen['dias_con_datos'] = sum(1 for item in items if item.get('con_datos'))
        resumen.append(item_resumen)
        if valores:
            series.append({
                'turno': label,
                'perfil': label,
                'sector': sec,
                'funcion_legajero': fun,
                'operacion': op,
                'division_madre': div,
                'division_madre_label': _divisiones_label(div),
                'objetivo_actual': item_resumen['objetivo_actual_promedio'],
                'referencias': item_resumen['referencias'],
                'puntos': [{'dias': i + 1, 'uc': math.ceil(v)} for i, v in enumerate(valores)],
            })

    detalle = sorted([{
        'fecha': x.get('fecha'), 'sector': x.get('sector'), 'funcion_legajero': x.get('funcion_legajero'),
        'operacion': x.get('operacion'), 'division_madre': x.get('division_madre'),
        'division_madre_label': x.get('division_madre_label'), 'turno': str(x.get('turno') or ''),
        'nomina_computable': x.get('nomina_computable'), 'produccion': x.get('uc_computables'),
        'objetivo_actual': x.get('objetivo_por_operario'), 'umbral_uc': math.ceil(float(x.get('umbral_uc') or 0)),
        'cobra_actual': bool(x.get('cobra_actual')),
    } for x in filtrados], key=lambda x: (x['sector'] or '', x['funcion_legajero'] or '', x['operacion'] or '', x.get('division_madre') or '', x['turno'], x['fecha'] or ''))
    return {'resumen': resumen, 'series': series, 'detalle': detalle, 'dias_periodo': len(dias_periodo),
            'filtros': sorted(filtros_base, key=lambda x: (x['sector'], x['operacion'], x['funcion_legajero'], x.get('division_madre') or '')),
            'nota': 'Umbral UC = producción computable / (nómina computable × (1 - factor ausentismo)). Cada perfil se consolida por fecha y usa el mismo calendario del período; los días sin base computable se representan con producción cero.'}

@router.get('/actividad-legajo')
async def actividad_legajo(request: Request, fecha: str, legajo: str):
    """Actividad WMS agregada para auditar el legajo elegido en el detalle grupal."""
    await _admin(request)
    fecha_cache = fecha.replace('-', '').strip()
    if len(fecha_cache) != 8 or not fecha_cache.isdigit() or not str(legajo).strip():
        raise HTTPException(400, 'Fecha y legajo válidos son obligatorios.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''SELECT fecha,CAST(legajo AS TEXT) AS legajo,
                TRIM(desc_funcion) AS funcion_wms,COALESCE(division,'') AS division,
                COALESCE(sector,'') AS sector,
                COUNT(DISTINCT CASE WHEN TRIM(COALESCE(pallet,'')) NOT IN ('','0','*') THEN TRIM(pallet) END) AS palets,
                COUNT(DISTINCT CASE WHEN TRIM(COALESCE(plu,'')) NOT IN ('','0','*') THEN TRIM(plu) END) AS plus,
                SUM(COALESCE(cantidad,0)) AS cantidad,
                SUM(COALESCE(peso,0)) AS peso,COUNT(*) AS filas_cache
            FROM lab_etapa_detalle_raw
            WHERE run_id LIKE ? AND fecha=? AND CAST(legajo AS TEXT)=? AND TRIM(COALESCE(desc_funcion,''))<>''
            GROUP BY fecha,CAST(legajo AS TEXT),TRIM(desc_funcion),COALESCE(division,''),COALESCE(sector,'')
            ORDER BY UPPER(TRIM(desc_funcion)),division,sector''', (f"{LAB_CACHE_RUN_PREFIX}%", fecha_cache, str(legajo).strip())) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    return {'fecha': fecha_cache, 'legajo': str(legajo).strip(), 'rows': rows, 'total': len(rows)}


@router.put('/parametros-grupales')
async def guardar_parametro_grupal(request: Request):
    await _admin(request)
    data = await request.json()
    keys = ('sector', 'funcion_legajero', 'turno', 'operacion_medible')
    if any(not str(data.get(k) or '').strip() for k in keys):
        raise HTTPException(400, 'Sector, función, turno y operación medible son obligatorios.')
    try:
        uc, factor, premio = (float(data[k]) for k in ('uc_por_operario', 'factor_ausentismo', 'premio_grupal'))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(400, 'Objetivo, factor y premio deben ser números válidos.') from exc
    if not all(math.isfinite(v) for v in (uc, factor, premio)) or uc <= 0 or not 0 <= factor <= 100 or premio < 0:
        raise HTTPException(400, 'Objetivo mayor a cero, factor entre 0 y 100 y premio no negativo.')
    sector, funcion, turno, operacion = (str(data[k]).strip() for k in keys)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        operaciones = await _operaciones_grupales(db)
        if operacion not in operaciones:
            raise HTTPException(400, 'Elegí una operación marcada como medible, con unidad PALET, BULTO o PLU en Parámetros.')
        async with db.execute('''SELECT grupo_productivo_id,division_madre
                FROM lab_parametro_grupal
                WHERE sector=? AND funcion_legajero=? AND turno=?''',
                (sector, funcion, turno)) as cur:
            anterior = await cur.fetchone()
        # Omitir el campo conserva la asociación de clientes anteriores.
        # Enviar null o vacío la elimina de manera explícita.
        if 'grupo_productivo_id' in data:
            group_id = data['grupo_productivo_id']
            if group_id is None or group_id == '':
                group_id = None
            else:
                catalogo = await _catalogo_grupos_productivos(db)
                validos = {str(r['id']): r['id'] for r in catalogo}
                if str(group_id).strip() not in validos:
                    raise HTTPException(400, 'El grupo productivo no existe en el catálogo importado.')
                group_id = validos[str(group_id).strip()]
        else:
            group_id = anterior[0] if anterior else None
        division_madre_raw = data.get('division_madre') if 'division_madre' in data else (anterior[1] if anterior else '')
        division_madre = ','.join(_division_codigos(division_madre_raw))
        await db.execute("""INSERT INTO lab_parametro_grupal
            (sector,funcion_legajero,turno,operacion_medible,division_madre,uc_por_operario,factor_ausentismo,premio_grupal,activo,grupo_productivo_id)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sector,funcion_legajero,turno) DO UPDATE SET
            operacion_medible=excluded.operacion_medible,uc_por_operario=excluded.uc_por_operario,
            factor_ausentismo=excluded.factor_ausentismo,premio_grupal=excluded.premio_grupal,
            activo=excluded.activo,grupo_productivo_id=excluded.grupo_productivo_id,
            division_madre=excluded.division_madre,updated_at=CURRENT_TIMESTAMP""",
            (sector, funcion, turno, operacion, division_madre, uc, factor, premio,
             1 if data.get('activo', True) else 0, group_id))
        await db.execute('DELETE FROM lab_calculo_grupal_cache')
        await db.commit()
    return {'ok': True}


@router.put('/parametros-grupales/componentes')
async def guardar_componentes_parametro_grupal(request: Request):
    """Reemplaza los componentes Palet de una operación grupal compuesta."""
    await _admin(request)
    data = await request.json()
    try:
        sector = str(data['sector']).strip(); funcion = str(data['funcion_legajero']).strip(); turno = str(data['turno']).strip()
        componentes = sorted({str(x).strip().upper() for x in data.get('funciones_wms', []) if str(x).strip()})
    except (KeyError, TypeError) as exc:
        raise HTTPException(400, 'Parámetro y componentes inválidos.') from exc
    if not sector or not funcion or not turno:
        raise HTTPException(400, 'Sector, función y turno son obligatorios.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        async with db.execute('SELECT 1 FROM lab_parametro_grupal WHERE sector=? AND funcion_legajero=? AND turno=?', (sector, funcion, turno)) as cur:
            if not await cur.fetchone():
                raise HTTPException(404, 'Primero guardá el parámetro maestro.')
        if componentes:
            placeholders = ','.join('?' for _ in componentes)
            async with db.execute(f'''SELECT DISTINCT UPPER(TRIM(desc_funcion)) FROM lab_cache_agrupado
                WHERE UPPER(TRIM(desc_funcion)) IN ({placeholders})''', tuple(componentes)) as cur:
                existentes = {row[0] for row in await cur.fetchall()}
            faltantes = set(componentes) - existentes
            if faltantes:
                raise HTTPException(400, 'Funciones WMS inexistentes: ' + ', '.join(sorted(faltantes)))
        await db.execute('DELETE FROM lab_parametro_grupal_componente WHERE sector=? AND funcion_legajero=? AND turno=?', (sector, funcion, turno))
        await db.executemany('''INSERT INTO lab_parametro_grupal_componente
            (sector,funcion_legajero,turno,funcion_wms,unidad_medida,factor) VALUES(?,?,?,?,?,1)''',
            [(sector, funcion, turno, item, 'PALET') for item in componentes])
        await db.execute('DELETE FROM lab_calculo_grupal_cache')
        await db.commit()
    return {'ok': True, 'componentes': componentes}


@router.delete('/parametros-grupales')
async def borrar_parametro_grupal(request: Request):
    """Elimina un parámetro y sus componentes del escenario."""
    await _admin(request)
    data = await request.json()
    try:
        sector = str(data['sector']).strip()
        funcion = str(data['funcion_legajero']).strip()
        turno = str(data['turno']).strip()
    except (KeyError, TypeError) as exc:
        raise HTTPException(400, 'Sector, función y turno son obligatorios.') from exc
    if not sector or not funcion or not turno:
        raise HTTPException(400, 'Sector, función y turno son obligatorios.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        await db.execute('''DELETE FROM lab_parametro_grupal_componente
                WHERE sector=? AND funcion_legajero=? AND turno=?''', (sector, funcion, turno))
        result = await db.execute('''DELETE FROM lab_parametro_grupal
                WHERE sector=? AND funcion_legajero=? AND turno=?''', (sector, funcion, turno))
        if not result.rowcount:
            raise HTTPException(404, 'El parámetro ya no existe.')
        await db.execute('DELETE FROM lab_calculo_grupal_cache')
        await db.commit()
    return {'ok': True}


@router.put("/mapa-polivalencia")
async def guardar_mapa_polivalencia(request: Request):
    await _admin(request)
    data = await request.json()
    operaciones_a = data.get('operaciones_a', [data.get('operacion_a')])
    operaciones_b = data.get('operaciones_b', [data.get('operacion_b')])
    operaciones_a = sorted({str(x or '').strip().upper() for x in operaciones_a if str(x or '').strip()})
    operaciones_b = sorted({str(x or '').strip().upper() for x in operaciones_b if str(x or '').strip()})
    seleccionadas_b = set(operaciones_b)
    if data.get('modo') == 'matriz_completa':
        seleccionadas_b = {str(x or '').strip().upper() for x in data.get('operaciones_b_si', operaciones_b) if str(x or '').strip()}
        async with aiosqlite.connect(LAB_CACHE_DB_PATH) as catalog_db:
            async with catalog_db.execute("SELECT DISTINCT UPPER(TRIM(operacion_premio)) FROM lab_evaluacion_premio WHERE TRIM(COALESCE(operacion_premio,''))<>'' UNION SELECT DISTINCT UPPER(TRIM(desc_funcion)) FROM lab_cache_agrupado WHERE TRIM(COALESCE(desc_funcion,''))<>''") as cur:
                catalogo = {str(r[0]).strip() for r in await cur.fetchall() if r[0]}
        operaciones_b = sorted(catalogo)
    cruces = [(a, b) for a in operaciones_a for b in operaciones_b if a != b]
    if not cruces:
        raise HTTPException(400, 'Seleccioná al menos un cruce entre operaciones distintas.')
    try:
        premio_centavos = int(data.get('premio_centavos', 0) or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, 'El importe debe ser un número entero de centavos.') from exc
    if premio_centavos < 0:
        raise HTTPException(400, 'El importe de polivalencia no puede ser negativo.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        # El importe pertenece a la operación A y se replica en todas sus B.
        await db.executemany('UPDATE lab_mapa_polivalencia SET premio_centavos=?,updated_at=CURRENT_TIMESTAMP WHERE operacion_a=?',
                             [(premio_centavos, a) for a in operaciones_a])
        await db.executemany("INSERT INTO lab_mapa_polivalencia(operacion_a,operacion_b,polivalencia,premio_centavos) VALUES(?,?,?,?) ON CONFLICT(operacion_a,operacion_b) DO UPDATE SET polivalencia=excluded.polivalencia,premio_centavos=excluded.premio_centavos,updated_at=CURRENT_TIMESTAMP", [(a,b,1 if (b in seleccionadas_b if data.get('modo') == 'matriz_completa' else data.get('polivalencia')) else 0,premio_centavos) for a,b in cruces])
        await db.commit()
    return {'ok': True, 'cruces_guardados': len(cruces), 'cruces_omitidos_igualdad': len(operaciones_a) * len(operaciones_b) - len(cruces)}


async def _admin(request: Request):
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    if str(auth.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Requiere administrador.")
    return auth


def _cache_filter(fecha_desde: str, fecha_hasta: str, legajo: str, desc_funcion: str):
    try:
        desde = datetime.strptime(fecha_desde, "%Y-%m-%d").strftime("%Y%m%d")
        hasta = datetime.strptime(fecha_hasta, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Las fechas deben tener formato YYYY-MM-DD.") from exc
    if desde > hasta:
        raise HTTPException(status_code=400, detail="Fecha desde no puede ser posterior a fecha hasta.")
    where = ["run_id LIKE ?", "fecha >= ?", "fecha <= ?"]
    args: list[Any] = [f"{LAB_CACHE_RUN_PREFIX}%", desde, hasta]
    if legajo.strip():
        where.append("CAST(legajo AS TEXT) LIKE ?"); args.append(f"%{legajo.strip()}%")
    if desc_funcion.strip():
        where.append("UPPER(COALESCE(desc_funcion, '')) = ?"); args.append(desc_funcion.strip().upper())
    return " AND ".join(where), args


@router.get("/funciones")
async def funciones_cache(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        async with db.execute("""SELECT DISTINCT TRIM(desc_funcion) AS desc_funcion
            FROM lab_cache_agrupado WHERE TRIM(COALESCE(desc_funcion,'')) <> ''
            ORDER BY UPPER(TRIM(desc_funcion))""") as cur:
            funciones = [row[0] for row in await cur.fetchall()]
    return {"funciones": funciones, "source": str(LAB_CACHE_DB_PATH)}


@router.get("/parametros")
async def parametros(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row; await _ensure_config(db)
        async with db.execute("""SELECT p.desc_funcion,p.medible,p.unidad_medida,p.grupo_premio,p.observaciones,
            COALESCE(e.operacion_premio,'') AS operacion_premio
            FROM lab_funcion_parametro p LEFT JOIN lab_funcion_equivalencia e
            ON e.desc_funcion=p.desc_funcion ORDER BY UPPER(p.desc_funcion)""") as cur:
            rows=[dict(row) for row in await cur.fetchall()]
    return {"rows":rows}


@router.put("/parametros")
async def guardar_parametro(request: Request):
    await _admin(request)
    data=await request.json(); funcion=str(data.get("desc_funcion") or '').strip()
    if not funcion: raise HTTPException(status_code=400, detail="La función es obligatoria.")
    try:
        estado = int(data.get("estado", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Estado de función inválido.") from exc
    if estado not in {0, 1, 2}:
        raise HTTPException(status_code=400, detail="El estado debe ser 0, 1 o 2.")
    unidad = str(data.get('unidad_medida') or '').strip().upper()
    if unidad not in {'', 'BULTO', 'PALET', 'PLU', 'N/A'}:
        raise HTTPException(status_code=400, detail="Unidad de medida inválida.")
    operacion = data.get('operacion_premio')
    if operacion is not None:
        operacion = str(operacion).strip()
        catalogo = await escalas_premios(request)
        if operacion and operacion not in {r['operacion'] for r in catalogo['rows']}:
            raise HTTPException(status_code=400, detail="La operación no existe en las escalas importadas.")
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        await db.execute("""INSERT INTO lab_funcion_parametro(desc_funcion,medible,unidad_medida,grupo_premio,observaciones,updated_at)
            VALUES(?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(desc_funcion) DO UPDATE SET medible=excluded.medible,unidad_medida=excluded.unidad_medida,grupo_premio=excluded.grupo_premio,observaciones=excluded.observaciones,updated_at=CURRENT_TIMESTAMP""",
            (funcion,estado,unidad,str(data.get('grupo_premio') or '').strip(),str(data.get('observaciones') or '').strip()))
        if operacion is not None:
            await db.execute("""INSERT INTO lab_funcion_equivalencia(desc_funcion,operacion_premio)
                VALUES(?,?) ON CONFLICT(desc_funcion) DO UPDATE SET
                operacion_premio=excluded.operacion_premio,updated_at=CURRENT_TIMESTAMP""",
                (funcion, operacion))
        await db.commit()
    return {"ok":True,"desc_funcion":funcion}


@router.get("/grupos-productivos")
async def grupos_productivos(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row; await _ensure_config(db)
        async with db.execute("SELECT grupo_cache,grupo_premio FROM lab_grupo_productivo_equivalencia ORDER BY grupo_cache") as cur:
            return {"rows": [dict(r) for r in await cur.fetchall()]}


@router.put("/grupos-productivos")
async def guardar_grupo_productivo(request: Request):
    await _admin(request); data = await request.json()
    grupo_cache = str(data.get("grupo_cache") or "").strip()
    grupo_premio = str(data.get("grupo_premio") or "").strip()
    if not grupo_cache: raise HTTPException(status_code=400, detail="El grupo del cache es obligatorio.")
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        await db.execute("""INSERT INTO lab_grupo_productivo_equivalencia(grupo_cache,grupo_premio)
            VALUES(?,?) ON CONFLICT(grupo_cache) DO UPDATE SET grupo_premio=excluded.grupo_premio,updated_at=CURRENT_TIMESTAMP""", (grupo_cache,grupo_premio))
        await db.commit()
    return {"ok": True, "grupo_cache": grupo_cache}


@router.get("/escalas")
async def escalas_premios(request: Request):
    await _admin(request)
    # El snapshot manual del estudio tiene prioridad sobre el módulo anterior.
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as config_db:
        await _ensure_config(config_db)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri() + '?mode=ro', uri=True) as db:
        async with db.execute("SELECT 1 FROM sqlite_master WHERE name='lab_fuente_lote'") as cur:
            ready = await cur.fetchone()
        if ready:
            async with db.execute("""SELECT snapshot,capturado FROM lab_fuente_lote
                WHERE fuente='oracle.PV_ESCALA_DE_PREMIOS' ORDER BY capturado DESC LIMIT 1""") as cur:
                snapshot = await cur.fetchone()
            if snapshot:
                async def source(name):
                    async with db.execute('SELECT payload FROM lab_fuente_registro WHERE snapshot=? AND fuente=? ORDER BY ordinal', (snapshot[0], name)) as cur:
                        return [json.loads(r[0]) for r in await cur.fetchall()]
                groups = {str(r['ID']): r['DESCRIPCION'] for r in await source('oracle.PV_GRUPO_DE_FUNCIONES_CAB')}
                productive = {str(r['ID']): r['DESCRIPCION'] for r in await source('oracle.PV_GRUPO_PRODUCTIVO_CAB')}
                rows = [{**{k.lower(): v for k,v in r.items()},
                         'operacion': groups.get(str(r['ID_DE_GRUPO_DE_FUNCIONES']), str(r['ID_DE_GRUPO_DE_FUNCIONES'])),
                         'grupo_productivo': productive.get(str(r['ID_DE_GRUPO_PRODUCTIVO']), 'Sin grupo específico')}
                        for r in await source('oracle.PV_ESCALA_DE_PREMIOS')]
                # Operación única: cada aporte físico validado es un palet operado.
                carga = [(0, 0, 184), (1, 185, 204), (2, 205, 219),
                         (3, 220, 230), (4, 231, 240), (5, 241, 999999999)]
                carga_actual = [r for r in rows if str(r.get('operacion') or '').upper() == 'CARGA']
                importes_por_grupo = {}
                for actual in carga_actual:
                    grupo_actual = actual.get('grupo_productivo') or 'Sin grupo específico'
                    importes_por_grupo.setdefault(grupo_actual, {})[int(actual.get('nivel') or 0) - 1] = float(actual.get('premio') or 0)
                rows = [r for r in rows if str(r.get('operacion') or '').upper() != 'CARGA']
                rows.extend({'operacion': 'PALETS OPERADOS', 'grupo_productivo': grupo,
                             'nivel': nivel, 'desde': desde, 'hasta': hasta, 'premio': importes.get(nivel, 0),
                             'premio_por_unidad_excedente': 0, 'fecha_vigencia_desde': None,
                             'fecha_vigencia_hasta': None, 'tabla_propia': True,
                             'nota': 'Rango nuevo; importe tomado de nivel vigente equivalente'}
                            for grupo, importes in importes_por_grupo.items()
                            for nivel, desde, hasta in carga)
                # La simulación de Clark usa una única tabla propia, sin
                # grupo operativo. Se conserva el pago Oracle en su cache de
                # pagos actuales, pero sus escalas por grupo no intervienen
                # en esta nueva medición unificada.
                rows = [row for row in rows if str(row.get('operacion') or '').upper() != 'CLARK']
                async with db.execute('''SELECT operacion,grupo_productivo,nivel,desde,hasta,premio,
                        premio_por_unidad_excedente,observaciones,updated_at
                        FROM lab_escala_propia ORDER BY operacion,grupo_productivo,nivel''') as cur:
                    propias = [dict(operacion=row[0], grupo_productivo=row[1], nivel=row[2], desde=row[3],
                                    hasta=row[4], premio=row[5], premio_por_unidad_excedente=row[6],
                                    nota=row[7], updated_at=row[8], tabla_propia=True,
                                    fecha_vigencia_desde=None, fecha_vigencia_hasta=None)
                                for row in await cur.fetchall()]
                rows.extend(propias)
                async with db.execute('SELECT * FROM lab_escala_override') as cur:
                    # Esta conexión usa tuplas (no Row); convertir por posición
                    # evita que el refresco posterior al PUT falle con ValueError.
                    overrides = {}
                    for r in await cur.fetchall():
                        override = {
                            'operacion': r[0], 'grupo_productivo': r[1], 'nivel': int(r[2]),
                            'desde': float(r[3]), 'hasta': float(r[4]), 'premio': float(r[5]),
                            'premio_por_unidad_excedente': float(r[6]),
                        }
                        overrides[(r[0], r[1], int(r[2]), float(r[3]), float(r[4]))] = override
                for row in rows:
                    key = (str(row.get('operacion') or ''), str(row.get('grupo_productivo') or ''), int(row.get('nivel') or 0), float(row.get('desde') or 0), float(row.get('hasta') or 0))
                    # Las ediciones ya cargadas sobre CARGA se trasladan a la
                    # tabla unificada hasta que se editen directamente allí.
                    if key not in overrides and key[0] == 'PALETS OPERADOS':
                        key = ('CARGA', key[1], key[2], key[3], key[4])
                    if key in overrides:
                        row.update({field: overrides[key][field] for field in ('premio', 'premio_por_unidad_excedente')})
                        row['editado'] = True
                    else:
                        row['editado'] = False
                rows.sort(key=lambda r: (r['operacion'], r['grupo_productivo'], float(r.get('nivel') or 0)))
                return {'snapshot': {'snapshot_id': snapshot[0], 'captured_at': snapshot[1]},
                        'rows': rows, 'source': 'cache_estudio_oracle',
                        'nota': 'Escalas capturadas actualmente; aplicabilidad histórica pendiente de validación.'}
    if not PREMIO_SOURCE_DB_PATH.exists(): return {"snapshot":None,"rows":[]}
    async with aiosqlite.connect(PREMIO_SOURCE_DB_PATH) as db:
        db.row_factory=aiosqlite.Row
        async with db.execute("""SELECT operacion,grupo_productivo,nivel,desde,hasta,premio,premio_por_unidad_excedente,fecha_vigencia_desde,fecha_vigencia_hasta FROM pp_premio_foto_escala ORDER BY operacion,grupo_productivo,nivel""") as cur:
            rows=[dict(row) for row in await cur.fetchall()]
        async with db.execute("SELECT snapshot_id,captured_at,algorithm_version FROM pp_premio_foto_meta ORDER BY id DESC LIMIT 1") as cur:
            meta=await cur.fetchone()
    return {"snapshot":dict(meta) if meta else None,"rows":rows,"source":str(PREMIO_SOURCE_DB_PATH)}


@router.put('/escalas')
async def guardar_escala_override(request: Request):
    await _admin(request); data = await request.json()
    try:
        operacion = str(data['operacion']).strip(); grupo = str(data.get('grupo_productivo') or '').strip()
        nivel = int(data['nivel']); desde = float(data['desde']); hasta = float(data['hasta'])
        original_desde = float(data.get('original_desde', desde)); original_hasta = float(data.get('original_hasta', hasta))
        premio = float(data['premio']); excedente = float(data.get('premio_por_unidad_excedente') or 0)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, 'Valores de escala inválidos.') from exc
    if not operacion or nivel < 0 or desde < 0 or hasta < desde or premio < 0 or excedente < 0:
        raise HTTPException(400, 'Operación, rango y premios deben ser válidos.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        if data.get('tabla_propia'):
            cursor = await db.execute('''UPDATE lab_escala_propia
                SET desde=?,hasta=?,premio=?,premio_por_unidad_excedente=?,updated_at=CURRENT_TIMESTAMP
                WHERE operacion=? AND grupo_productivo=? AND nivel=?''',
                (desde, hasta, premio, excedente, operacion, grupo, nivel))
            if cursor.rowcount != 1:
                raise HTTPException(404, 'No se encontró el tramo de la tabla propia.')
            await db.commit()
            return {'ok': True, 'editado': True, 'tabla_propia': True}
        # Si se modifica el rango, el override anterior deja de representar a
        # esta escala y debe reemplazarse, no coexistir con el nuevo.
        await db.execute('''DELETE FROM lab_escala_override
            WHERE operacion=? AND grupo_productivo=? AND nivel=? AND desde=? AND hasta=?''',
            (operacion, grupo, nivel, original_desde, original_hasta))
        await db.execute('''INSERT INTO lab_escala_override(operacion,grupo_productivo,nivel,desde,hasta,premio,premio_por_unidad_excedente)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(operacion,grupo_productivo,nivel,desde,hasta) DO UPDATE SET premio=excluded.premio,premio_por_unidad_excedente=excluded.premio_por_unidad_excedente,updated_at=CURRENT_TIMESTAMP''',
            (operacion, grupo, nivel, desde, hasta, premio, excedente))
        await db.commit()
    return {'ok': True, 'editado': True}


@router.get("/agrupado")
async def cache_agrupado(
    request: Request,
    fecha_desde: str = Query("2026-08-01"), fecha_hasta: str = Query("2026-08-31"),
    legajo: str = Query(""), desc_funcion: str = Query(""),
    grupo_productivo: str = Query(""),
    limit: int = Query(250, ge=1, le=500), offset: int = Query(0, ge=0),
):
    await _admin(request)
    predicate, args = _cache_filter(fecha_desde, fecha_hasta, legajo, desc_funcion)
    predicate = predicate.replace("run_id LIKE ? AND ", "")
    args = args[1:]
    predicate = predicate.replace("desc_funcion", "desc_funcion")
    if grupo_productivo.strip():
        async with aiosqlite.connect(LAB_CACHE_DB_PATH) as lookup:
            async with lookup.execute("SELECT grupo_cache FROM lab_grupo_productivo_equivalencia WHERE UPPER(grupo_premio)=UPPER(?)", (grupo_productivo.strip(),)) as cur:
                caches = [r[0] for r in await cur.fetchall()]
        if not caches: return {"total": 0, "limit": limit, "offset": offset, "has_more": False, "rows": [], "filters": {"grupo_productivo": grupo_productivo.strip()}}
        predicate += " AND division IN (" + ",".join("?" for _ in caches) + ")"; args.extend(caches)
    desde_cache, hasta_cache = fecha_desde.replace('-', ''), fecha_hasta.replace('-', '')
    rows_source = '''SELECT fecha,legajo,desc_funcion,division,sector,palets,plus,cantidad,peso,detalle_filas
        FROM lab_cache_agrupado WHERE fecha>=? AND fecha<=?
        UNION ALL
        SELECT fecha,legajo,desc_funcion,division,sector,palets,plus,cantidad,peso,detalle_filas
        FROM (
            SELECT fecha,legajo,desc_funcion,division,sector,palets,plus,cantidad,peso,detalle_filas,
                   ROW_NUMBER() OVER (
                       PARTITION BY fecha,legajo,desc_funcion,division,sector,origen
                       ORDER BY created_at DESC,snapshot DESC
                   ) AS rn
            FROM lab_cache_agrupado_ajuste WHERE fecha>=? AND fecha<=?
        ) WHERE rn=1'''
    source_args = (desde_cache, hasta_cache, desde_cache, hasta_cache)
    grouped = f"""FROM ({rows_source}) WHERE {predicate}"""
    # La evaluación se hace sobre la fila agrupada, pero las reglas se leen
    # desde la configuración local del estudio. El cache operativo queda intacto.
    escala_catalogo = await escalas_premios(request)
    escalas = escala_catalogo.get("rows", [])
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("ATTACH DATABASE ? AS rrhh_legajero", (str(RRHH_GRUPAL_DB_PATH),))
        predicate_legajero = (predicate.replace('CAST(legajo AS TEXT)', 'CAST(w.legajo AS TEXT)')
                              .replace('desc_funcion', 'w.desc_funcion')
                              .replace('fecha', 'w.fecha').replace('division', 'w.division'))
        grouped_legajero = f'''FROM ({rows_source}) w
            JOIN (SELECT CAST(legajo AS TEXT) legajo,MAX(nombre) nombre,
                              MAX(desc_sector_generico) sector_legajero,
                              MAX(desc_funcion) funcion_legajero
                       FROM rrhh_legajero.rrhh_personas
                       WHERE active=1 AND UPPER(TRIM(COALESCE(desc_grupo_personal,'')))='PROPIOS'
                       GROUP BY CAST(legajo AS TEXT)) pers
              ON pers.legajo=CAST(w.legajo AS TEXT)
            WHERE {predicate_legajero}'''
        # RECEPCION no existe como fila cruda: evitar el recorrido completo
        # del cache cuando el usuario consulta sólo la operación sintética.
        consulta_sintetica = str(desc_funcion or '').strip().upper() == 'RECEPCION'
        if consulta_sintetica:
            total, rows = 0, []
        else:
            async with db.execute(f"SELECT COUNT(*) AS total {grouped}", (*source_args, *args)) as cur:
                total = int((await cur.fetchone())["total"] or 0)
            # Consolidar y evaluar siempre el conjunto completo antes de paginar.
            page_clause = ""
            page_args = (*source_args, *args)
            async with db.execute(f"""SELECT w.fecha, w.legajo, w.desc_funcion, w.division, w.sector,
                    w.palets, w.plus, w.cantidad, w.peso, w.detalle_filas,
                    COALESCE(pers.nombre,'') nombre,COALESCE(pers.sector_legajero,'') sector_legajero,
                    COALESCE(pers.funcion_legajero,'') funcion_legajero {grouped_legajero}
                    ORDER BY w.fecha, w.legajo, UPPER(TRIM(w.desc_funcion)){page_clause}""", page_args) as cur:
                rows = [dict(row) for row in await cur.fetchall()]
        await _ensure_config(db)
        componentes_medibles = await _componentes_operaciones_medibles(db)
        async with db.execute("""SELECT p.desc_funcion,p.medible,p.unidad_medida,
                p.grupo_premio,COALESCE(e.operacion_premio,'') AS operacion_premio
                FROM lab_funcion_parametro p LEFT JOIN lab_funcion_equivalencia e
                ON e.desc_funcion=p.desc_funcion""") as cur:
            parametros = {r["desc_funcion"]: dict(r) for r in await cur.fetchall()}
        await db.execute("""INSERT OR IGNORE INTO lab_funcion_parametro
            (desc_funcion,medible,unidad_medida,observaciones) VALUES('PALETS OPERADOS',1,'PALET',
            'Operación unificada: carga y traslado por etapa/palet.')""")
        await db.execute("""INSERT OR IGNORE INTO lab_funcion_equivalencia(desc_funcion,operacion_premio)
            VALUES('PALETS OPERADOS','PALETS OPERADOS')""")
        await db.commit()
        parametros['PALETS OPERADOS'] = {'desc_funcion': 'PALETS OPERADOS', 'medible': 1,
            'unidad_medida': 'PALET', 'grupo_premio': '', 'operacion_premio': 'PALETS OPERADOS'}
        # Las escalas individuales nuevas se administran por perfil del
        # legajero (sector, función y operación), no por grupo productivo de
        # la tabla histórica.
        async with db.execute('''SELECT sector,funcion_legajero,
                UPPER(TRIM(operacion_medible)) operacion_medible,
                COALESCE(division_madre,'') division_madre,nivel,desde_uc,hasta_uc,premio
            FROM lab_escala_individual_grupal
            WHERE activo=1
            ORDER BY sector,funcion_legajero,operacion_medible,division_madre,nivel''') as cur:
            escalas_perfil_raw = [dict(row) for row in await cur.fetchall()]
        async with db.execute('''SELECT CAST(legajo AS TEXT) legajo,sector,funcion_legajero
            FROM lab_perfil_operativo_legajo WHERE activo=1''') as cur:
            perfiles_operativos = {str(row['legajo']): dict(row) for row in await cur.fetchall()}
        async with db.execute('SELECT COUNT(*) FROM lab_palets_carga_traslado WHERE fecha>=? AND fecha<=?', (fecha_desde.replace('-', ''), fecha_hasta.replace('-', ''))) as cur:
            if not int((await cur.fetchone())[0] or 0):
                await _recalcular_palets_carga_traslado(db, fecha_desde.replace('-', ''), fecha_hasta.replace('-', ''))
        await db.execute("ATTACH DATABASE ? AS rrhh_unificada", (str(RRHH_GRUPAL_DB_PATH),))
        unificado_where = '' if not legajo.strip() else ' AND CAST(u.legajo AS TEXT) LIKE ?'
        unificado_args: list[Any] = [fecha_desde.replace('-', ''), fecha_hasta.replace('-', '')]
        if legajo.strip():
            unificado_args.append(f'%{legajo.strip()}%')
        async with db.execute(f'''SELECT u.fecha,u.legajo,MAX(p.nombre) nombre,
                    MAX(p.desc_sector_generico) sector_legajero,MAX(p.desc_funcion) funcion_legajero,
                    COUNT(*) palets
            FROM lab_palets_carga_traslado u JOIN rrhh_unificada.rrhh_personas p
              ON CAST(p.legajo AS TEXT)=CAST(u.legajo AS TEXT)
            WHERE u.fecha>=? AND u.fecha<=? AND UPPER(TRIM(p.desc_funcion))='CARGADOR DE SECOS'
              AND p.active=1 AND UPPER(TRIM(COALESCE(p.desc_grupo_personal,'')))='PROPIOS'
            {unificado_where} GROUP BY u.fecha,u.legajo''', tuple(unificado_args)) as cur:
            unificados = [dict(r) for r in await cur.fetchall()]
        claves_unificadas = {(x['fecha'], str(x['legajo'])) for x in unificados}
        rows = [r for r in rows if not ((r['fecha'], str(r['legajo'])) in claves_unificadas
                and str(r.get('desc_funcion') or '').upper() in {'CARGA CAMION', 'TRASLADO'})]
        rows.extend({'fecha': x['fecha'], 'legajo': x['legajo'], 'desc_funcion': 'PALETS OPERADOS',
            'division': '1', 'sector': '*', 'palets': x['palets'], 'plus': 0, 'cantidad': 0,
            'peso': 0, 'detalle_filas': x['palets'], 'nombre': x['nombre'] or '',
            'sector_legajero': x['sector_legajero'] or '',
            'funcion_legajero': x['funcion_legajero'] or ''} for x in unificados)
        # RECEPCION se forma desde el detalle de etiquetas, no desde el cache
        # agregado. Así Operación de recepción y Revisor no duplican un pallet
        # cuando corresponden al mismo movimiento físico.
        desde_cache, hasta_cache = fecha_desde.replace('-', ''), fecha_hasta.replace('-', '')
        await _asegurar_palets_recepcion(db, desde_cache, hasta_cache)
        filtro_funcion = str(desc_funcion or '').strip().upper()
        if not filtro_funcion or filtro_funcion == 'RECEPCION':
            recepcion_where = 'r.fecha>=? AND r.fecha<=?'
            recepcion_args: list[Any] = [desde_cache, hasta_cache]
            if legajo.strip():
                recepcion_where += ' AND CAST(r.legajo AS TEXT) LIKE ?'
                recepcion_args.append(f'%{legajo.strip()}%')
            async with db.execute(f'''SELECT r.fecha,r.legajo,COUNT(*) palets,
                    MAX(p.nombre) nombre,MAX(p.desc_sector_generico) sector_legajero,
                    MAX(p.desc_funcion) funcion_legajero
                FROM lab_palets_recepcion r
                JOIN rrhh_unificada.rrhh_personas p ON CAST(p.legajo AS TEXT)=CAST(r.legajo AS TEXT)
                WHERE {recepcion_where}
                  AND p.active=1 AND UPPER(TRIM(COALESCE(p.desc_grupo_personal,'')))='PROPIOS'
                GROUP BY r.fecha,r.legajo''', tuple(recepcion_args)) as cur:
                recepcion_unificada = [dict(row) for row in await cur.fetchall()]
            rows.extend({'fecha': x['fecha'], 'legajo': x['legajo'], 'desc_funcion': 'RECEPCION',
                'division': '', 'sector': '*', 'palets': x['palets'], 'plus': 0, 'cantidad': 0,
                'peso': 0, 'detalle_filas': x['palets'], 'nombre': x['nombre'] or '',
                'sector_legajero': x['sector_legajero'] or '',
                'funcion_legajero': x['funcion_legajero'] or ''} for x in recepcion_unificada)
        # Las operaciones compuestas se consolidan por jornada y legajo. En
        # Clark no interviene la división ni el grupo operativo: todos sus
        # movimientos físicos alimentan una única escala diaria.
        for operacion_compuesta, componentes in componentes_medibles.items():
            if operacion_compuesta in {'PALETS OPERADOS', 'RECEPCION'}:
                continue
            unidad_componentes = {str(item.get('unidad_medida') or '').strip().upper() for item in componentes
                                  if str(item.get('unidad_medida') or '').strip()}
            unidad_compuesta = next(iter(unidad_componentes)) if len(unidad_componentes) == 1 else 'PALET'
            columna_compuesta = {'PALET': 'palets', 'BULTO': 'cantidad', 'PLU': 'plus', 'HUECO': 'plus'}.get(unidad_compuesta, 'palets')
            funciones = {str(item.get('funcion_wms') or '').strip().upper() for item in componentes}
            acumuladas: dict[tuple[str, str], dict[str, Any]] = {}
            for row in rows:
                if str(row.get('desc_funcion') or '').strip().upper() not in funciones:
                    continue
                clave = (str(row['fecha']), str(row['legajo']))
                total_compuesto = acumuladas.setdefault(clave, {'fecha': row['fecha'], 'legajo': row['legajo'],
                    'desc_funcion': operacion_compuesta, 'division': '', 'sector': '*',
                    'palets': 0.0, 'plus': 0, 'cantidad': 0, 'peso': 0, 'detalle_filas': 0,
                    'nombre': row.get('nombre') or '',
                    'sector_legajero': row.get('sector_legajero') or '',
                    'funcion_legajero': row.get('funcion_legajero') or ''})
                total_compuesto[columna_compuesta] += float(row.get(columna_compuesta) or 0)
                total_compuesto['detalle_filas'] += float(row.get('detalle_filas') or 0)
            rows.extend(acumuladas.values())
        division_grupo = {}
        async with db.execute("""SELECT payload FROM lab_fuente_registro
                WHERE fuente='oracle.PV_GRUPO_PRODUCTIVO_DET' ORDER BY ordinal""") as cur:
            detalles = [json.loads(r[0]) for r in await cur.fetchall()]
        async with db.execute("""SELECT payload FROM lab_fuente_registro
                WHERE fuente='oracle.PV_GRUPO_PRODUCTIVO_CAB' ORDER BY ordinal""") as cur:
            grupos = {str((x := json.loads(r[0]))['ID']): x['DESCRIPCION'] for r in await cur.fetchall()}
        por_division = {}
        for item in detalles:
            por_division.setdefault(str(item.get('ID_DE_DIVISION')), []).append(grupos.get(str(item.get('ID_DE_GRUPO_PRODUCTIVO')), ''))
        division_grupo = {k: Counter(v).most_common(1)[0][0] for k, v in por_division.items() if v}
        async with db.execute("SELECT grupo_cache,grupo_premio FROM lab_grupo_productivo_equivalencia WHERE grupo_premio<>''") as cur:
            equivalencias = {str(r[0]).strip().upper(): str(r[1]).strip() for r in await cur.fetchall()}

    # La configuración se comparte entre turnos. Se deduplica aquí para que
    # la evaluación individual use la escala del perfil sin volver a inferir
    # el turno desde la actividad WMS.
    escalas_perfil: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    vistos_perfil: set[tuple[str, str, str, str, int]] = set()
    for escala in escalas_perfil_raw:
        clave = (str(escala.get('sector') or '').strip().upper(),
                 str(escala.get('funcion_legajero') or '').strip().upper(),
                 str(escala.get('operacion_medible') or '').strip().upper())
        division_escala = ','.join(_division_codigos(escala.get('division_madre')))
        nivel = int(escala.get('nivel') or 0)
        clave_nivel = (*clave, division_escala, nivel)
        if clave_nivel in vistos_perfil:
            continue
        vistos_perfil.add(clave_nivel)
        escalas_perfil[clave][division_escala].append(escala)

    def tramo_escala_perfil(row: dict[str, Any], operacion: str, unidades: Any) -> dict[str, Any] | None:
        """Tramo nuevo aplicable al perfil, solamente si es inequívoco."""
        clave = (str(row.get('sector_legajero') or '').strip().upper(),
                 str(row.get('funcion_legajero') or '').strip().upper(),
                 str(operacion or '').strip().upper())
        por_division = escalas_perfil.get(clave)
        if not por_division or unidades is None:
            return None
        division_fila = ','.join(_division_codigos(row.get('division')))
        if division_fila and division_fila in por_division:
            tramos = por_division[division_fila]
        elif len(por_division) == 1:
            # Las operaciones compuestas se consolidan sin división propia.
            tramos = next(iter(por_division.values()))
        else:
            return None
        valor = float(unidades or 0)
        for tramo in sorted(tramos, key=lambda item: int(item.get('nivel') or 0)):
            desde = float(tramo.get('desde_uc') or 0)
            hasta = float(tramo.get('hasta_uc') or 0)
            if valor >= desde and (hasta <= 0 or valor < hasta):
                return tramo
        return None

    for row in rows:
        perfil_operativo = perfiles_operativos.get(str(row.get('legajo') or ''))
        if perfil_operativo:
            row['sector_legajero'] = perfil_operativo.get('sector') or row.get('sector_legajero') or ''
            row['funcion_legajero'] = perfil_operativo.get('funcion_legajero') or row.get('funcion_legajero') or ''
        p = parametros.get(row["desc_funcion"], {})
        unidad = str(p.get("unidad_medida") or "").upper()
        operacion = str(p.get("operacion_premio") or "").strip()
        if operacion.upper() == "TRASLADO":
            operacion = "TRASLADOS"
        # Los ajustes de pago sin detalle WMS se guardan con el código PICKIN.
        # Para Armado son una imputación de bultos, igual que en el cálculo
        # grupal. No se habilita PICKIN como operación medible de forma global.
        es_ajuste_armado_sin_wms = (
            str(row.get("desc_funcion") or "").strip().upper() == "PICKIN"
            and str(row.get("sector") or "").strip().upper() == "AJUSTE PAGO ACTUAL SIN WMS"
        )
        if es_ajuste_armado_sin_wms:
            operacion, unidad = "ARMADO", "BULTO"
        grupo = str(p.get("grupo_premio") or "").strip()
        grupo_operativo = division_grupo.get(str(row.get("division") or "").strip(), "")
        grupo_escala = grupo or equivalencias.get(grupo_operativo.upper(), grupo_operativo)
        if operacion.upper() == 'CLARK':
            grupo_escala = 'Sin grupo operativo'
        elif operacion.upper() == 'RECEPCION':
            # La tabla propia de recepción es por sector de legajero, no por
            # división WMS: Secos y NOA tienen escalas históricas distintas.
            grupo_escala = str(row.get('sector_legajero') or '').strip()
        if operacion.upper() == "TRASLADOS" and not unidad:
            unidad = "PALET"
        unidades = {"PALET": row.get("palets"), "PLU": row.get("plus"),
                    "BULTO": row.get("cantidad")}.get(unidad)
        tramo_perfil = tramo_escala_perfil(row, operacion, unidades)
        if tramo_perfil:
            # Persistir el perfil evita que Armado quede asociado al sector
            # WMS "*" y deja trazable la escala que se aplicó.
            row['sector'] = row.get('sector_legajero') or row.get('sector') or '*'
            row.update({'evaluacion_estado': 'Evaluado', 'operacion_premio': operacion,
                        'unidad_medida': unidad, 'grupo_productivo': grupo_escala,
                        'unidades_evaluadas': unidades,
                        'nivel_nuevo': tramo_perfil.get('nivel'),
                        'premio_nuevo': float(tramo_perfil.get('premio') or 0),
                        '_escala_perfil': True})
            continue
        candidatos = [x for x in escalas if str(x.get("operacion") or "").strip().upper() == operacion.upper()
                      and (str(x.get("grupo_productivo") or "").strip().upper() == grupo_escala.upper()
                           if operacion.upper() == 'CLARK' else
                           (not grupo_escala or str(x.get("grupo_productivo") or "").strip().upper() == grupo_escala.upper()))]
        tramo = next((x for x in candidatos if float(x.get("desde") or 0) <= float(unidades or 0)
                      <= float(x.get("hasta") or 0)), None) if unidades is not None else None
        if operacion.upper() not in {"CARGA", "TRASLADOS", "PALETS OPERADOS", "CLARK", "RECEPCION", "ARMADO", "CONTROL"}:
            row.update({"evaluacion_estado": "Fuera del piloto", "operacion_premio": operacion,
                       "unidad_medida": unidad, "unidades_evaluadas": None, "nivel_nuevo": None,
                       "premio_nuevo": None})
        elif int(p.get("medible") or 0) != 1:
            row.update({"evaluacion_estado": "No medible", "operacion_premio": operacion,
                       "unidad_medida": unidad, "grupo_productivo": grupo_escala, "unidades_evaluadas": unidades, "nivel_nuevo": None,
                       "premio_nuevo": None})
        elif not operacion or not unidad or not candidatos:
            row.update({"evaluacion_estado": "Falta configuración", "operacion_premio": operacion,
                       "unidad_medida": unidad, "grupo_productivo": grupo_escala, "unidades_evaluadas": unidades, "nivel_nuevo": None,
                       "premio_nuevo": None})
        elif not tramo:
            row.update({"evaluacion_estado": "Sin tramo", "operacion_premio": operacion,
                       "unidad_medida": unidad, "grupo_productivo": grupo_escala, "unidades_evaluadas": unidades, "nivel_nuevo": None,
                       "premio_nuevo": None})
        else:
            exceso = max(0.0, float(unidades) - float(tramo.get("hasta") or 0))
            premio = float(tramo.get("premio") or 0) + exceso * float(tramo.get("premio_por_unidad_excedente") or 0)
            row.update({"evaluacion_estado": "Evaluado", "operacion_premio": operacion,
                       "unidad_medida": unidad, "grupo_productivo": grupo_escala, "unidades_evaluadas": unidades,
                       "nivel_nuevo": tramo.get("nivel"), "premio_nuevo": premio})
    consolidated = {}
    for row in rows:
        if str(row.get("operacion_premio") or "").upper() == "TRASLADOS":
            row["sector"] = "*"
        key = (row["fecha"], row["legajo"], row["desc_funcion"], row.get("sector") or "", row.get("grupo_productivo") or "")
        if key not in consolidated:
            consolidated[key] = row.copy()
        else:
            target = consolidated[key]
            for field in ("palets", "plus", "cantidad", "peso", "detalle_filas", "unidades_evaluadas", "premio_nuevo"):
                if target.get(field) is not None and row.get(field) is not None:
                    target[field] = (float(target[field] or 0) + float(row[field] or 0))
            if target.get("evaluacion_estado") != "Evaluado" and row.get("evaluacion_estado") == "Evaluado":
                target["evaluacion_estado"] = "Evaluado"
            target["division"] = ""
    rows = list(consolidated.values())
    # La escala se aplica sobre el total consolidado, no sobre cada división.
    for row in rows:
        if str(row.get("operacion_premio") or "").upper() not in {"CARGA", "TRASLADOS", "PALETS OPERADOS", "CLARK", "RECEPCION", "ARMADO", "CONTROL"}:
            continue
        op = str(row.get("operacion_premio") or "").upper()
        if row.get('_escala_perfil'):
            # Ya se aplicó sobre el total de la operación compuesta. La tabla
            # histórica no debe reemplazar la escala nueva por perfil.
            continue
        unidades = row.get("palets") if str(row.get("unidad_medida") or "").upper() == "PALET" else row.get("cantidad")
        grupo = str(row.get("grupo_productivo") or "").upper()
        candidatos = [x for x in escalas if str(x.get("operacion") or "").upper() == op
                      and str(x.get("grupo_productivo") or "").upper() == grupo]
        tramo = next((x for x in candidatos if float(x.get("desde") or 0) <= float(unidades or 0) <= float(x.get("hasta") or 0)), None)
        if tramo:
            row["nivel_nuevo"] = tramo.get("nivel")
            row["premio_nuevo"] = float(tramo.get("premio") or 0)
            row["evaluacion_estado"] = "Evaluado"
        else:
            row["nivel_nuevo"] = None; row["premio_nuevo"] = None; row["evaluacion_estado"] = "Sin tramo"
    resumen = {}
    for row in rows:
        key = (row["fecha"], row["legajo"])
        item = resumen.setdefault(key, {"fecha": row["fecha"], "legajo": row["legajo"], "operaciones": {}, "total_premio": 0.0})
        op = str(row.get("operacion_premio") or row.get("desc_funcion") or "Sin vincular")
        item["operaciones"][op] = round(item["operaciones"].get(op, 0.0) + float(row.get("premio_nuevo") or 0), 2)
        item["total_premio"] = round(item["total_premio"] + float(row.get("premio_nuevo") or 0), 2)
    for item in resumen.values():
        item["operaciones"] = [{"operacion": op, "premio": value} for op, value in sorted(item["operaciones"].items())]
    full_rows = rows
    visible_rows = full_rows[offset:offset + limit]
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        await db.executemany("""INSERT INTO lab_evaluacion_premio(fecha,legajo,desc_funcion,sector,operacion_premio,grupo_productivo,unidad_medida,unidades_evaluadas,nivel_nuevo,premio_nuevo,evaluacion_estado,version_tabla)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(fecha,legajo,desc_funcion,sector,operacion_premio,grupo_productivo) DO UPDATE SET unidad_medida=excluded.unidad_medida,unidades_evaluadas=excluded.unidades_evaluadas,nivel_nuevo=excluded.nivel_nuevo,premio_nuevo=excluded.premio_nuevo,evaluacion_estado=excluded.evaluacion_estado,version_tabla=excluded.version_tabla,calculado_at=CURRENT_TIMESTAMP""",
            [(r['fecha'],r['legajo'],str(r.get('desc_funcion') or '').strip(),r.get('sector') or '*',r.get('operacion_premio') or '',r.get('grupo_productivo') or '',r.get('unidad_medida') or '',r.get('unidades_evaluadas'),r.get('nivel_nuevo'),r.get('premio_nuevo'),r.get('evaluacion_estado') or '',str(escala_catalogo.get('snapshot') or '')) for r in full_rows if str(r.get('desc_funcion') or '').strip()])
        await db.commit()
    return {"total": len(full_rows), "limit": limit, "offset": offset, "has_more": offset + len(visible_rows) < len(full_rows), "rows": visible_rows,
            "resumen_pagos": list(resumen.values()), "hierarchy_rows": full_rows,
            "filters": {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta, "legajo": legajo.strip(), "desc_funcion": desc_funcion.strip()}}


@router.post("/recalcular-individual")
async def recalcular_individual(request: Request, fecha_desde: str = '2026-08-01',
                                fecha_hasta: str = '2026-08-31'):
    """Reemplaza por completo la cache de evaluación individual del período."""
    await _admin(request)
    try:
        datetime.strptime(fecha_desde, '%Y-%m-%d')
        datetime.strptime(fecha_hasta, '%Y-%m-%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        await db.execute('DELETE FROM lab_evaluacion_premio WHERE fecha>=? AND fecha<=?',
                         (fecha_desde.replace('-', ''), fecha_hasta.replace('-', '')))
        await db.commit()
    # La función de ruta usa Query como valor por defecto cuando se invoca
    # directamente; pasar filtros explícitos evita que llegue un objeto Query
    # al filtro de texto durante el recálculo.
    result = await cache_agrupado(request, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                                  legajo='', desc_funcion='', grupo_productivo='',
                                  limit=500, offset=0)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri() + '?mode=ro', uri=True) as db:
        async with db.execute('''SELECT COUNT(*), SUM(CASE WHEN evaluacion_estado='Evaluado' THEN 1 ELSE 0 END),
                COALESCE(SUM(premio_nuevo),0) FROM lab_evaluacion_premio
                WHERE fecha>=? AND fecha<=?''', (fecha_desde.replace('-', ''), fecha_hasta.replace('-', ''))) as cur:
            total, evaluadas, premio = await cur.fetchone()
    return {'ok': True, 'filas_procesadas': int(total or 0), 'filas_evaluadas': int(evaluadas or 0),
            'filas_pendientes': int((total or 0) - (evaluadas or 0)),
            'premio_individual_nuevo': float(premio or 0), 'fecha_desde': fecha_desde,
            'fecha_hasta': fecha_hasta, 'cache_reemplazado': True,
            'snapshot_tablas': str(result.get('filters', {}).get('fecha_desde') or '')}


@router.get("/pagos-actuales")
async def pagos_actuales(request: Request, fecha_desde: str = '2026-08-01',
                         fecha_hasta: str = '2026-08-31', legajo: str = ''):
    await _admin(request)
    _, args = _cache_filter(fecha_desde, fecha_hasta, legajo, '')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT 1 FROM sqlite_master WHERE name='lab_pago_actual_meta'") as cur:
            if not await cur.fetchone():
                raise HTTPException(409, 'La cache de pagos actuales todavía no está preparada.')
        async with db.execute('SELECT * FROM lab_pago_actual_meta ORDER BY capturado DESC LIMIT 1') as cur:
            meta = await cur.fetchone()
        if not meta:
            raise HTTPException(409, 'La cache de pagos actuales no tiene una captura disponible.')
        condition = ' AND legajo LIKE ?' if legajo.strip() else ''
        params = [meta['snapshot'], args[1], args[2]] + ([f'%{legajo.strip()}%'] if legajo.strip() else [])
        async with db.execute('''SELECT fecha,legajo,jornadas,pago_centavos,detalle_centavos,
                diferencia_centavos,faltantes FROM lab_pago_actual_dia
                WHERE snapshot=? AND fecha>=? AND fecha<=?''' + condition + ' ORDER BY fecha,legajo', params) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    return {'rows':rows, 'snapshot':meta['snapshot'], 'capturado':meta['capturado'],
            'coverage':json.loads(meta['reporte']),
            'scope':'Pago actual completo por jornada; los filtros de función/grupo sólo afectan la simulación.'}


@router.get("/pagos-actuales/detalle")
async def pagos_actuales_detalle(request: Request, snapshot: str, fecha: str, legajo: str):
    await _admin(request)
    try:
        datetime.strptime(fecha, '%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fecha inválida.') from exc
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''SELECT * FROM lab_pago_actual_operacion
                WHERE snapshot=? AND fecha=? AND legajo=? ORDER BY operacion,id''', (snapshot,fecha,legajo)) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    return {'rows':rows, 'snapshot':snapshot, 'fecha':fecha, 'legajo':legajo}


def _turno_inferido_desde_inicio(inicio: Any) -> str:
    texto = str(inicio or '').strip()
    if not texto:
        return 'Sin turno'
    match = re.search(r'T?(\d{1,2}):(\d{2})', texto)
    if not match:
        return 'Sin turno'
    valor = int(match.group(1)) * 60 + int(match.group(2))
    if 6 * 60 <= valor < 14 * 60:
        return '1 - Manana'
    if 14 * 60 <= valor < 22 * 60:
        return '2 - Tarde'
    return '3 - Noche'


def _division_operativa(codigo: Any) -> tuple[str, str]:
    valor = str(codigo or '').strip()
    if valor == '1':
        return '1', '1 - SECOS'
    if valor in {'2', '4', '2,4'}:
        return '2,4', '2/4 - REFRIGERADOS'
    if valor == '6':
        return '6', '6 - NOA'
    if valor in {'SIN_DIVISION', ''}:
        return 'SIN_DIVISION', 'Sin division'
    return valor, f'{valor} - Sin division'


async def _reconstruir_escalas_propuestas_cache(db: aiosqlite.Connection, desde: str, hasta: str) -> None:
    await db.execute('DELETE FROM lab_escalas_propuestas_cache WHERE fecha>=? AND fecha<=?', (desde, hasta))
    await _asegurar_palets_recepcion(db, desde, hasta)
    async with db.execute("""SELECT COUNT(*) total,
                              SUM(CASE WHEN TRIM(COALESCE(division,''))<>'' THEN 1 ELSE 0 END) con_division
                    FROM lab_palets_carga_traslado WHERE fecha>=? AND fecha<=?""", (desde, hasta)) as cur:
        row = await cur.fetchone()
        if not int(row[0] or 0) or not int(row[1] or 0):
            await _recalcular_palets_carga_traslado(db, desde, hasta)
    filas: list[tuple[Any, ...]] = []
    async with db.execute("""SELECT fecha,CAST(legajo AS TEXT) legajo,TRIM(COALESCE(division,'')) division,
                   COALESCE(inicio,'') inicio,COUNT(*) uc
            FROM lab_palets_carga_traslado
            WHERE fecha>=? AND fecha<=?
            GROUP BY fecha,CAST(legajo AS TEXT),TRIM(COALESCE(division,'')),COALESCE(inicio,'')""",
            (desde, hasta)) as cur:
        async for row in cur:
            division_key, _ = _division_operativa(row['division'])
            filas.append((row['fecha'], 'PALETS OPERADOS', division_key, _turno_inferido_desde_inicio(row['inicio']),
                          row['legajo'], 'PALET', float(row['uc'] or 0), row['inicio'] or ''))
    async with db.execute("""SELECT fecha,CAST(legajo AS TEXT) legajo,TRIM(COALESCE(division,'')) division,
                   COALESCE(inicio,'') inicio,COUNT(*) uc
            FROM lab_palets_recepcion_division
            WHERE fecha>=? AND fecha<=?
            GROUP BY fecha,CAST(legajo AS TEXT),TRIM(COALESCE(division,'')),COALESCE(inicio,'')""",
            (desde, hasta)) as cur:
        async for row in cur:
            division_key, _ = _division_operativa(row['division'])
            filas.append((row['fecha'], 'RECEPCION', division_key, _turno_inferido_desde_inicio(row['inicio']),
                          row['legajo'], 'PALET', float(row['uc'] or 0), row['inicio'] or ''))
    componentes = await _componentes_operaciones_medibles(db)
    for operacion, items in componentes.items():
        operacion = str(operacion or '').strip().upper()
        if operacion in {'PALETS OPERADOS', 'RECEPCION'}:
            continue
        funciones = sorted({str(item.get('funcion_wms') or '').strip().upper() for item in items if str(item.get('funcion_wms') or '').strip()})
        unidades = {str(item.get('unidad_medida') or '').strip().upper() for item in items if str(item.get('unidad_medida') or '').strip()}
        unidad = next(iter(unidades)) if len(unidades) == 1 else ''
        expresion_uc = {
            'PALET': "COUNT(DISTINCT NULLIF(TRIM(COALESCE(pallet,'')),''))",
            'BULTO': "SUM(COALESCE(cantidad,0))",
            'PLU': "COUNT(DISTINCT NULLIF(TRIM(COALESCE(plu,'')),''))",
        }.get(unidad, '')
        if not funciones or not expresion_uc:
            continue
        placeholders = ','.join('?' for _ in funciones)
        async with db.execute(f"""SELECT fecha,CAST(legajo AS TEXT) legajo,TRIM(COALESCE(division,'')) division,
                       MIN(COALESCE(fyhini,'')) inicio,{expresion_uc} uc
                FROM lab_etapa_detalle_raw
                WHERE fecha>=? AND fecha<=? AND UPPER(TRIM(desc_funcion)) IN ({placeholders})
                GROUP BY fecha,CAST(legajo AS TEXT),TRIM(COALESCE(division,'')),id_etapa""",
                (desde, hasta, *funciones)) as cur:
            async for row in cur:
                division_key, _ = _division_operativa(row['division'])
                filas.append((row['fecha'], operacion, division_key, _turno_inferido_desde_inicio(row['inicio']),
                              row['legajo'], unidad, float(row['uc'] or 0), row['inicio'] or ''))
    if filas:
        await db.executemany("""INSERT INTO lab_escalas_propuestas_cache
            (fecha,operacion,division,turno,legajo,unidad_medida,uc,inicio)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(fecha,operacion,division,turno,legajo) DO UPDATE SET
                uc=uc+excluded.uc,
                inicio=CASE WHEN inicio='' OR (excluded.inicio<>'' AND excluded.inicio<inicio) THEN excluded.inicio ELSE inicio END,
                unidad_medida=excluded.unidad_medida, updated_at=CURRENT_TIMESTAMP""", filas)
    await db.commit()


async def _asegurar_escalas_propuestas_cache(db: aiosqlite.Connection, desde: str, hasta: str) -> None:
    async with db.execute('SELECT COUNT(*) FROM lab_escalas_propuestas_cache WHERE fecha>=? AND fecha<=?', (desde, hasta)) as cur:
        hay = int((await cur.fetchone())[0] or 0)
    if not hay:
        await _reconstruir_escalas_propuestas_cache(db, desde, hasta)

@router.get("/escalas-propuestas")
async def escalas_propuestas(request: Request, fecha_desde: str = '2026-08-01',
                             fecha_hasta: str = '2026-08-31', operacion: str = '',
                             division: str = '', sector: str = '', turno: str = ''):
    """Propone umbrales desde cache materializada: UC por operario activo, división y turno inferido."""
    await _admin(request)
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    if desde > hasta:
        raise HTTPException(400, 'La fecha desde debe ser anterior o igual a la fecha hasta.')

    def _unidad_label(unidad: str) -> str:
        valor = str(unidad or '').strip().upper()
        if valor == 'PALET': return 'Palets'
        if valor == 'BULTO': return 'Bultos'
        return valor or 'UC real'

    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        db.row_factory = aiosqlite.Row
        operaciones_catalogo = await _operaciones_grupales(db)
        operaciones_disponibles = sorted({str(op or '').strip().upper() for op in operaciones_catalogo if str(op or '').strip()} - {'CARGA CAMION', 'TRASLADO', 'TRASLADOS'})
        filtro_operacion = str(operacion or '').strip().upper()
        await _asegurar_escalas_propuestas_cache(db, desde, hasta)
        filtro_division = str(division or sector or '').strip()
        filtro_turno = str(turno or '').strip()
        catalog_where = ['fecha>=?', 'fecha<=?']
        catalog_args: list[Any] = [desde, hasta]
        if filtro_operacion:
            catalog_where.append('operacion=?'); catalog_args.append(filtro_operacion)
        async with db.execute(f"""SELECT DISTINCT division FROM lab_escalas_propuestas_cache
                WHERE {' AND '.join(catalog_where)} ORDER BY division""", tuple(catalog_args)) as cur:
            divisiones_catalogo = [{'value': row['division'], 'label': _division_operativa(row['division'])[1]} for row in await cur.fetchall()]
        async with db.execute(f"""SELECT DISTINCT turno FROM lab_escalas_propuestas_cache
                WHERE {' AND '.join(catalog_where)} ORDER BY turno""", tuple(catalog_args)) as cur:
            turnos_catalogo = [row['turno'] for row in await cur.fetchall()]
        where = ['fecha>=?', 'fecha<=?']
        args: list[Any] = [desde, hasta]
        if filtro_operacion:
            where.append('operacion=?'); args.append(filtro_operacion)
        if filtro_division:
            where.append('division=?'); args.append(filtro_division)
        if filtro_turno:
            where.append('turno=?'); args.append(filtro_turno)
        async with db.execute(f"""SELECT fecha,operacion,division,turno,CAST(legajo AS TEXT) legajo,
                       MAX(unidad_medida) unidad_medida,SUM(uc) uc
                FROM lab_escalas_propuestas_cache
                WHERE {' AND '.join(where)}
                GROUP BY fecha,operacion,division,turno,CAST(legajo AS TEXT)""", tuple(args)) as cur:
            eventos = [dict(row) for row in await cur.fetchall()]

    diarios: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for evento in eventos:
        if not evento.get('uc'):
            continue
        op_key = str(evento.get('operacion') or '').strip().upper()
        div_key = str(evento.get('division') or 'SIN_DIVISION')
        turno_key = str(evento.get('turno') or 'Sin turno')
        clave = (op_key, div_key, turno_key, str(evento['fecha']))
        dia = diarios.setdefault(clave, {'operacion': op_key, 'division': div_key, 'division_label': _division_operativa(div_key)[1], 'turno': turno_key, 'fecha': str(evento['fecha']), 'unidad_medida': str(evento.get('unidad_medida') or ''), 'uc_total': 0.0, 'legajos': set()})
        dia['uc_total'] += float(evento.get('uc') or 0)
        dia['legajos'].add(str(evento.get('legajo') or ''))
        if not dia.get('unidad_medida'):
            dia['unidad_medida'] = str(evento.get('unidad_medida') or '')

    por_grupo: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for dia in diarios.values():
        if dia['legajos']:
            dia['operarios'] = len(dia['legajos'])
            dia['uc_promedio_operario'] = dia['uc_total'] / dia['operarios'] if dia['operarios'] else 0
            por_grupo[(dia['operacion'], dia['division'], dia['turno'])].append(dia)

    rows, series = [], []
    for (op_key, div_key, turno_key), dias in sorted(por_grupo.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
        unidad = next((str(dia.get('unidad_medida') or '') for dia in dias if dia.get('unidad_medida')), '')
        thresholds = [float(dia['uc_promedio_operario'] or 0) for dia in dias]
        max_uc = max(thresholds or [0])
        step = 1 if max_uc <= 80 else 2 if max_uc <= 160 else 5
        limite = int(math.ceil(max_uc / step) * step + step)
        puntos = []
        uc = 0
        while uc <= limite:
            dias_cobra = sum(1 for th in thresholds if th > uc)
            puntos.append({'uc': uc, 'dias_cobra': dias_cobra, 'pct_dias': round(dias_cobra / len(dias) * 100, 2) if dias else 0})
            uc += step
        ordenados = sorted(thresholds, reverse=True)
        def uc_para_pct(pct: float) -> float:
            if not ordenados: return 0
            idx = max(0, min(len(ordenados) - 1, math.ceil(len(ordenados) * pct / 100) - 1))
            return float(ordenados[idx])
        uc_total = sum(float(dia['uc_total'] or 0) for dia in dias)
        operarios_total = sum(int(dia['operarios'] or 0) for dia in dias)
        row = {'operacion': op_key, 'division': div_key, 'division_label': dias[0]['division_label'], 'turno': turno_key,
               'unidad_medida': unidad, 'unidad_label': _unidad_label(unidad), 'dias': len(dias),
               'uc_min': round(min(thresholds or [0]), 2), 'uc_max': round(max_uc, 2),
               'uc_sugerido_75': round(uc_para_pct(75), 2), 'uc_sugerido_50': round(uc_para_pct(50), 2), 'uc_sugerido_25': round(uc_para_pct(25), 2),
               'uc_total': round(uc_total, 2), 'uc_promedio_dia': round(uc_total / len(dias), 2) if dias else 0,
               'operarios_dia_promedio': round(operarios_total / len(dias), 2) if dias else 0,
               'uc_promedio_operario': round(sum(thresholds) / len(thresholds), 2) if thresholds else 0}
        rows.append(row)
        series.append({**row, 'points': puntos})
    return {'rows': rows, 'series': series, 'filtros': {'operaciones': operaciones_disponibles, 'divisiones': divisiones_catalogo, 'turnos': turnos_catalogo},
            'nota': 'Simulación desde cache materializada: UC por operario con actividad real, división WMS y turno inferido por hora de inicio.'}

@router.get("/premios-totales")
async def premios_totales(request: Request, fecha_desde: str = '2026-08-01',
                          fecha_hasta: str = '2026-08-31'):
    """Distribuye el pago real de cada tarea en los tres conceptos del estudio."""
    await _admin(request)
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as config_db:
        await _ensure_config(config_db)
        config_db.row_factory = aiosqlite.Row
        async with config_db.execute('''SELECT nivel_1_json,polivalencia_json,calculado_at FROM lab_calculo_grupal_cache
                WHERE fecha_desde=? AND fecha_hasta=?''', (desde, hasta)) as cur:
            calculo_cache = await cur.fetchone()
        async with config_db.execute('''SELECT * FROM lab_parametro_grupal
                WHERE activo=1 ORDER BY sector,funcion_legajero,turno''') as cur:
            parametros = [dict(row) for row in await cur.fetchall()]
        grupos_catalogo = await _catalogo_grupos_productivos(config_db)
        _identificar_grupos_parametros(parametros, grupos_catalogo)
    nivel_1_cache = json.loads(calculo_cache['nivel_1_json']) if calculo_cache else []
    eventos_polivalencia = json.loads(calculo_cache['polivalencia_json']) if calculo_cache else []
    perfiles: dict[tuple[str, str], dict[str, Any]] = {}
    for parametro in parametros:
        clave = (str(parametro['sector']).strip(), str(parametro['funcion_legajero']).strip())
        perfil = perfiles.setdefault(clave, {'sector': clave[0], 'funcion': clave[1],
                                             'operaciones': set(), 'operaciones_normalizadas': set(), 'grupos': set()})
        perfil['operaciones'].add(str(parametro.get('operacion_medible') or '').strip().upper())
        perfil['operaciones_normalizadas'].add(_operacion_total(parametro.get('operacion_medible')))
        if str(parametro.get('grupo_productivo') or '').strip():
            perfil['grupos'].add(str(parametro['grupo_productivo']).strip())
    async with aiosqlite.connect(RRHH_GRUPAL_DB_PATH.as_uri()+'?mode=ro', uri=True) as rrhh_db:
        rrhh_db.row_factory = aiosqlite.Row
        async with rrhh_db.execute(f'''SELECT CAST(legajo AS TEXT) legajo,desc_sector_generico,desc_funcion
                FROM rrhh_personas WHERE {RRHH_PROPIOS_FILTER}''') as cur:
            perfil_por_legajo = {
                str(row['legajo']): (str(row['desc_sector_generico']).strip(), str(row['desc_funcion']).strip())
                for row in await cur.fetchall()
            }
    acumulados: dict[tuple[str, str], dict[str, Any]] = {}
    def fila_perfil(clave: tuple[str, str]) -> dict[str, Any]:
        perfil = perfiles[clave]
        return acumulados.setdefault(clave, {
            'sector': perfil['sector'], 'funcion': perfil['funcion'],
            'operaciones_medibles': ' · '.join(sorted(perfil['operaciones'])),
            'grupos_productivos': ' · '.join(sorted(perfil['grupos'])) or 'Sin grupo productivo',
            'tareas_actuales': 0, 'legajos_actuales': set(), 'total_centavos': 0,
            'individual_nuevo_centavos': 0, 'grupal_nuevo_centavos': 0,
            'polivalencia_nuevo_centavos': 0,
        })
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT snapshot FROM lab_pago_actual_meta ORDER BY capturado DESC LIMIT 1') as cur:
            meta = await cur.fetchone()
        if not meta:
            raise HTTPException(409, 'La cache de pagos actuales todavía no está preparada.')
        async with db.execute('''SELECT CAST(legajo AS TEXT) legajo,operacion,grupo,COUNT(*) AS tareas,
                SUM(pago_centavos) AS total_centavos
                FROM lab_pago_actual_operacion
                WHERE snapshot=? AND fecha>=? AND fecha<=?
                GROUP BY CAST(legajo AS TEXT),operacion,grupo''',
                (meta['snapshot'], desde, hasta)) as cur:
            pagos_actuales = [dict(row) for row in await cur.fetchall()]
        async with db.execute('''SELECT CAST(legajo AS TEXT) legajo,operacion_premio,
                COALESCE(SUM(premio_nuevo),0) AS simulado
                FROM lab_evaluacion_premio WHERE fecha>=? AND fecha<=?
                GROUP BY CAST(legajo AS TEXT),operacion_premio''', (desde, hasta)) as cur:
            simulados_individuales = [dict(row) for row in await cur.fetchall()]
    for pago in pagos_actuales:
        clave = perfil_por_legajo.get(str(pago['legajo']))
        if clave not in perfiles or _operacion_total(pago.get('operacion')) not in perfiles[clave]['operaciones_normalizadas']:
            continue
        fila = fila_perfil(clave)
        fila['tareas_actuales'] += int(pago.get('tareas') or 0)
        fila['legajos_actuales'].add(str(pago['legajo']))
        fila['total_centavos'] += int(pago.get('total_centavos') or 0)
    for simulado in simulados_individuales:
        clave = perfil_por_legajo.get(str(simulado['legajo']))
        if clave not in perfiles or _operacion_total(simulado.get('operacion_premio')) not in perfiles[clave]['operaciones_normalizadas']:
            continue
        fila_perfil(clave)['individual_nuevo_centavos'] += int(round(float(simulado.get('simulado') or 0) * 100))
    for item in nivel_1_cache:
        clave = (str(item.get('sector') or '').strip(), str(item.get('funcion_legajero') or '').strip())
        if clave in perfiles:
            fila_perfil(clave)['grupal_nuevo_centavos'] += int(round(float(item.get('premio_grupal_total') or 0) * 100))
    for evento in eventos_polivalencia:
        clave = (str(evento.get('sector') or '').strip(), str(evento.get('funcion') or '').strip())
        if clave in perfiles:
            fila_perfil(clave)['polivalencia_nuevo_centavos'] += int(evento.get('premio_centavos') or 0)
    rows = []
    for fila in acumulados.values():
        fila['legajos_actuales'] = len(fila['legajos_actuales'])
        fila['total_nuevo_centavos'] = (fila['grupal_nuevo_centavos'] + fila['individual_nuevo_centavos']
                                        + fila['polivalencia_nuevo_centavos'])
        fila['diferencia_centavos'] = fila['total_nuevo_centavos'] - fila['total_centavos']
        if fila['total_nuevo_centavos'] > 0:
            rows.append(fila)
    rows.sort(key=lambda row: (row['sector'].casefold(), row['funcion'].casefold()))
    return {'snapshot': meta['snapshot'], 'rows': rows,
            'nota': 'Cada fila reúne el perfil Sector / Función. El pago Oracle y el individual se asignan al perfil activo del legajo sólo cuando coinciden con su operación medible. El grupal y la polivalencia provienen del último cálculo diario explícito.',
            'grupal': {'filas': len(nivel_1_cache), 'grupos_con_premio': sum(1 for row in rows if row['grupal_nuevo_centavos']),
                       'total_centavos': sum(row['grupal_nuevo_centavos'] for row in rows),
                       'calculado_at': calculo_cache['calculado_at'] if calculo_cache else None}}


@router.get("/resumen-legajos/filtros")
async def resumen_legajos_filtros(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_config(db)
        async with db.execute("""SELECT DISTINCT sector,funcion_legajero,UPPER(TRIM(operacion_medible)) operacion,
                       COALESCE(division_madre,'') division_madre
                FROM lab_parametro_grupal
                WHERE activo=1 AND TRIM(COALESCE(operacion_medible,''))<>''
                ORDER BY sector,funcion_legajero,operacion,division_madre""") as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    for row in rows:
        row['division_madre'] = ','.join(_division_codigos(row.get('division_madre')))
        row['division_madre_label'] = _divisiones_label(row['division_madre'])
    return {'filtros': rows}


@router.get("/resumen-legajos")
async def resumen_legajos(request: Request, fecha_desde: str = '2026-08-01', fecha_hasta: str = '2026-08-31',
                          sector: str = '', funcion_legajero: str = '', operacion: str = '', division_madre: str = ''):
    """Vista operativa por legajo basada en el mismo cálculo grupal diario."""
    await _admin(request)
    result = await calculo_grupal(request, fecha_desde, fecha_hasta)
    nivel_3 = result.get('nivel_3', [])
    sector = str(sector or '').strip()
    funcion_legajero = str(funcion_legajero or '').strip()
    operacion = str(operacion or '').strip().upper()
    division_madre = ','.join(_division_codigos(division_madre))

    def pasa(row: dict[str, Any]) -> bool:
        if sector and row.get('sector') != sector:
            return False
        if funcion_legajero and row.get('funcion_legajero') != funcion_legajero:
            return False
        if operacion and str(row.get('operacion') or '').upper() != operacion:
            return False
        if division_madre and ','.join(_division_codigos(row.get('division_madre'))) != division_madre:
            return False
        return bool(str(row.get('legajo') or '').strip())

    filas = [dict(row) for row in nivel_3 if pasa(row)]
    # El pago actual debe compararse contra la operación histórica equivalente
    # del perfil seleccionado. Antes se sumaba toda la jornada del legajo
    # (recepción, Clark, otras tareas, etc.), lo que hacía ver como pérdidas
    # diferencias que no pertenecían a Armado.
    def operaciones_actuales_equivalentes(operacion_nueva: str) -> set[str]:
        valor = str(operacion_nueva or '').strip().upper()
        if valor == 'ARMADO':
            return {'PICKING'}
        if valor == 'CLARK':
            return {'CLARK'}
        if valor == 'RECEPCION':
            return {'RECEPCION', 'RECEPCION NOA', 'RECEPCION SECOS',
                    'RECEPCION IMPORTADO DE NOA', 'REFRIGERADOS | RECEPCION'}
        if valor in {'CARGA', 'PALETS OPERADOS'}:
            return {'CARGA', 'CARRETEO', 'REFRIGERADOS | CARGA'}
        if valor == 'CONTROL':
            # Oracle no concentra el premio de Control bajo un único nombre:
            # las dos operaciones productivas vigentes son las que deben
            # compararse con la operación unificada CONTROL del laboratorio.
            return {'CONTROL', 'CONTROL PROCESOS MANUAL', 'CONTROL DE PROCESOS CHP + CBF'}
        return {valor}

    operaciones_actuales = set()
    for fila_operacion in filas:
        operaciones_actuales.update(operaciones_actuales_equivalentes(fila_operacion.get('operacion') or ''))
    filtros_seen = set()
    filtros = []
    for row in nivel_3:
        key = (row.get('sector') or '', row.get('funcion_legajero') or '', str(row.get('operacion') or '').upper(), ','.join(_division_codigos(row.get('division_madre'))))
        if key in filtros_seen:
            continue
        filtros_seen.add(key)
        filtros.append({'sector': key[0], 'funcion_legajero': key[1], 'operacion': key[2],
                        'division_madre': key[3], 'division_madre_label': _divisiones_label(key[3])})

    legajos: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    dias = []
    escalas_individuales: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    premio_grupal_config: dict[tuple[str, str, str, str, str], float] = {}
    pago_actual_legajo: dict[str, int] = defaultdict(int)
    pago_actual_legajo_fecha: dict[tuple[str, str], int] = defaultdict(int)
    pago_actual_otras_legajo: dict[str, int] = defaultdict(int)
    pago_actual_otras_legajo_fecha: dict[tuple[str, str], int] = defaultdict(int)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri() + '?mode=ro', uri=True) as db_ind:
        db_ind.row_factory = aiosqlite.Row
        async with db_ind.execute('''SELECT * FROM lab_escala_individual_grupal
                WHERE activo=1
                ORDER BY sector,funcion_legajero,turno,operacion_medible,division_madre,nivel''') as cur:
            for escala in await cur.fetchall():
                item = dict(escala)
                clave = (item['sector'], item['funcion_legajero'], str(item['turno']),
                         str(item['operacion_medible'] or '').upper(), item.get('division_madre') or '')
                escalas_individuales[clave].append(item)
        async with db_ind.execute('''SELECT sector,funcion_legajero,turno,UPPER(TRIM(operacion_medible)) operacion_medible,
                       COALESCE(division_madre,'') division_madre,COALESCE(premio_grupal,0) premio_grupal
                FROM lab_parametro_grupal
                WHERE activo=1 AND TRIM(COALESCE(operacion_medible,''))<>'' ''') as cur:
            for parametro in await cur.fetchall():
                item = dict(parametro)
                clave = (item['sector'], item['funcion_legajero'], str(item['turno']),
                         str(item['operacion_medible'] or '').upper(), item.get('division_madre') or '')
                premio_grupal_config[clave] = float(item.get('premio_grupal') or 0)
        async with db_ind.execute('SELECT snapshot FROM lab_pago_actual_meta ORDER BY capturado DESC LIMIT 1') as cur:
            snap_row = await cur.fetchone()
        if snap_row:
            snapshot = snap_row['snapshot']
            fd = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
            fh = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
            async with db_ind.execute('''SELECT legajo,fecha,UPPER(TRIM(operacion)) operacion,
                    SUM(COALESCE(pago_centavos,0)) pago_centavos
                    FROM lab_pago_actual_operacion
                    WHERE snapshot=? AND fecha BETWEEN ? AND ? AND COALESCE(pago_centavos,0)>0
                    GROUP BY legajo,fecha,UPPER(TRIM(operacion))''', (snapshot, fd, fh)) as cur:
                for pago in await cur.fetchall():
                    leg = str(pago['legajo'] or '')
                    fecha_pago = str(pago['fecha'] or '')
                    centavos = int(pago['pago_centavos'] or 0)
                    if str(pago['operacion'] or '').strip().upper() in operaciones_actuales:
                        pago_actual_legajo[leg] += centavos
                        pago_actual_legajo_fecha[(leg, fecha_pago)] += centavos
                    else:
                        pago_actual_otras_legajo[leg] += centavos
                        pago_actual_otras_legajo_fecha[(leg, fecha_pago)] += centavos

    def premio_individual_interno(persona: dict[str, Any], op: str, div: str) -> int:
        if not (persona.get('aplica_grupo') and persona.get('asistencia') == 'Presente'):
            return 0
        escala = escalas_individuales.get((persona.get('sector') or '', persona.get('funcion_legajero') or '',
                                           str(persona.get('turno') or persona.get('turno_fijo') or ''), op, div), [])
        if not escala:
            return 0
        uc = float(persona.get('uc_brutas') or persona.get('uc') or persona.get('produccion') or 0)
        premio = 0.0
        for tramo in escala:
            desde = float(tramo.get('desde_uc') or 0)
            hasta = float(tramo.get('hasta_uc') or 0)
            if uc >= desde and (hasta <= 0 or uc < hasta):
                premio = max(premio, float(tramo.get('premio') or 0))
        return int(round(premio * 100))

    for row in filas:
        legajo = str(row.get('legajo') or '').strip()
        op = str(row.get('operacion') or '').upper()
        div = ','.join(_division_codigos(row.get('division_madre')))
        key = (legajo, row.get('sector') or '', row.get('funcion_legajero') or '', str(row.get('turno') or row.get('turno_fijo') or ''), op, div)
        item = legajos.setdefault(key, {
            'legajo': legajo, 'nombre': row.get('nombre') or '', 'sector': row.get('sector') or '',
            'funcion_legajero': row.get('funcion_legajero') or '', 'turno_madre': str(row.get('turno') or row.get('turno_fijo') or ''),
            'operacion': op, 'division_madre': div, 'division_madre_label': _divisiones_label(div),
            'dias_evaluados': 0, 'dias_presente': 0, 'dias_cobra_grupal': 0, 'dias_polivalente': 0,
            'dias_integra_meta': 0, 'produccion_total': 0.0, 'produccion_computable_total': 0.0,
            'pago_grupal_centavos': 0, 'pago_individual_centavos': 0, 'pago_polivalencia_centavos': 0,
            'pago_total_nuevo_centavos': 0, 'pago_actual_centavos': 0,
            'pago_actual_otras_centavos': 0, 'diferencia_centavos': 0,
        })
        item['dias_evaluados'] += 1
        if row.get('asistencia') == 'Presente':
            item['dias_presente'] += 1
        if row.get('cobra'):
            item['dias_cobra_grupal'] += 1
        if row.get('es_polivalencia'):
            item['dias_polivalente'] += 1
        if row.get('integra_meta'):
            item['dias_integra_meta'] += 1
        item['produccion_total'] += float(row.get('uc_brutas') or row.get('uc') or row.get('produccion') or 0)
        item['produccion_computable_total'] += float(row.get('uc_computables') or 0)
        pago_individual = premio_individual_interno(row, op, div)
        pago_grupal = int(round(float(row.get('premio_grupal') or 0) * 100))
        clave_premio = (row.get('sector') or '', row.get('funcion_legajero') or '',
                        str(row.get('turno') or row.get('turno_fijo') or ''), op, div)
        pago_polivalencia = 0
        if row.get('es_polivalencia') and row.get('asistencia') == 'Presente':
            pago_polivalencia = int(round(float(premio_grupal_config.get(clave_premio, 0) or 0) * 100))
        item['pago_grupal_centavos'] += pago_grupal
        item['pago_individual_centavos'] += pago_individual
        item['pago_polivalencia_centavos'] += pago_polivalencia
        dias.append({
            'fecha': row.get('fecha'), 'dia_semana': _dia_semana(str(row.get('fecha') or '')),
            'legajo': legajo, 'nombre': row.get('nombre') or '', 'sector': row.get('sector') or '',
            'funcion_legajero': row.get('funcion_legajero') or '', 'turno_madre': str(row.get('turno') or row.get('turno_fijo') or ''),
            'operacion': op, 'division_madre': div, 'division_madre_label': _divisiones_label(div),
            'asistencia': row.get('asistencia') or '', 'ausencia': row.get('ausencia') or '',
            'ausencia_permitida': bool(row.get('ausencia_permitida')), 'polivalente': bool(row.get('es_polivalencia')),
            'integra_meta': bool(row.get('integra_meta')), 'produccion': float(row.get('uc_brutas') or row.get('uc') or row.get('produccion') or 0),
            'produccion_computable': float(row.get('uc_computables') or 0), 'cobra_grupal': bool(row.get('cobra')),
            'pago_grupal_centavos': pago_grupal,
            'pago_individual_centavos': pago_individual,
            'pago_polivalencia_centavos': pago_polivalencia,
            'pago_total_nuevo_centavos': pago_grupal + pago_individual + pago_polivalencia,
            'pago_actual_centavos': int(pago_actual_legajo_fecha.get((legajo, str(row.get('fecha') or '')), 0)),
            'pago_actual_otras_centavos': int(pago_actual_otras_legajo_fecha.get((legajo, str(row.get('fecha') or '')), 0)),
            'diferencia_centavos': pago_grupal + pago_individual + pago_polivalencia - int(pago_actual_legajo_fecha.get((legajo, str(row.get('fecha') or '')), 0)),
            'motivo': row.get('motivo') or row.get('estado') or '',
        })
    legajo_rows = []
    for item in legajos.values():
        item['produccion_promedio_dia'] = item['produccion_total'] / item['dias_evaluados'] if item['dias_evaluados'] else 0
        item['produccion_computable_promedio_dia'] = item['produccion_computable_total'] / item['dias_evaluados'] if item['dias_evaluados'] else 0
        item['pago_total_nuevo_centavos'] = int(item.get('pago_grupal_centavos') or 0) + int(item.get('pago_individual_centavos') or 0) + int(item.get('pago_polivalencia_centavos') or 0)
        item['pago_actual_centavos'] = int(pago_actual_legajo.get(str(item.get('legajo') or ''), 0))
        item['pago_actual_otras_centavos'] = int(pago_actual_otras_legajo.get(str(item.get('legajo') or ''), 0))
        item['diferencia_centavos'] = item['pago_total_nuevo_centavos'] - item['pago_actual_centavos']
        legajo_rows.append(item)
    legajo_rows.sort(key=lambda x: (x['sector'], x['funcion_legajero'], x['turno_madre'], x['legajo']))
    dias.sort(key=lambda x: (x['legajo'], x['fecha'] or ''))
    return {'legajos': legajo_rows, 'dias': dias, 'filtros': sorted(filtros, key=lambda x: (x['sector'], x['funcion_legajero'], x['operacion'], x['division_madre'])),
            'nota': result.get('nota') or 'Basado en el cálculo grupal del rango consultado.'}

@router.get("/resumen-legajos/detalle")
async def resumen_legajo_detalle(request: Request, legajo: str,
                                 fecha_desde: str = '2026-08-01', fecha_hasta: str = '2026-08-31'):
    """Desglosa el pago del legajo por día y operación comparable."""
    await _admin(request)
    legajo = str(legajo or '').strip()
    if not legajo:
        raise HTTPException(400, 'El legajo es obligatorio.')
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    if desde > hasta:
        raise HTTPException(400, 'La fecha desde no puede ser posterior a la fecha hasta.')

    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as config_db:
        config_db.row_factory = aiosqlite.Row
        await _ensure_config(config_db)
        async with config_db.execute('''SELECT nivel_3_json,polivalencia_json,calculado_at
                FROM lab_calculo_grupal_cache WHERE fecha_desde=? AND fecha_hasta=?''',
                                     (desde, hasta)) as cur:
            calculo_cache = await cur.fetchone()
    nivel_3_cache = json.loads(calculo_cache['nivel_3_json']) if calculo_cache else []
    eventos_polivalencia = json.loads(calculo_cache['polivalencia_json']) if calculo_cache else []

    detalle: dict[tuple[str, str], dict[str, Any]] = {}
    def fila(fecha: str, operacion: str, grupo: str = '') -> dict[str, Any]:
        op = _operacion_total(operacion) or 'Sin operación'
        key = (str(fecha), op)
        row = detalle.setdefault(key, {
            'fecha': str(fecha), 'operacion': op, 'grupo_productivo': '',
            'pago_actual_centavos': 0, 'individual_nuevo_centavos': 0,
            'polivalencia_nuevo_centavos': 0, 'grupal_nuevo_centavos': 0,
        })
        if grupo and not row['grupo_productivo']:
            row['grupo_productivo'] = grupo
        return row

    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''SELECT fecha,operacion,grupo,COALESCE(SUM(pago_centavos),0) pago
                FROM lab_pago_actual_operacion
                WHERE fecha>=? AND fecha<=? AND CAST(legajo AS TEXT)=?
                GROUP BY fecha,operacion,grupo''', (desde, hasta, legajo)) as cur:
            for item in await cur.fetchall():
                fila(item['fecha'], item['operacion'], item['grupo'])['pago_actual_centavos'] += int(item['pago'] or 0)
        async with db.execute('''SELECT fecha,operacion_premio,grupo_productivo,COALESCE(SUM(premio_nuevo),0) pago
                FROM lab_evaluacion_premio
                WHERE fecha>=? AND fecha<=? AND CAST(legajo AS TEXT)=?
                GROUP BY fecha,operacion_premio,grupo_productivo''', (desde, hasta, legajo)) as cur:
            for item in await cur.fetchall():
                pago = int(round(float(item['pago'] or 0) * 100))
                if pago:
                    fila(item['fecha'], item['operacion_premio'], item['grupo_productivo'])['individual_nuevo_centavos'] += pago

    for evento in eventos_polivalencia:
        if str(evento.get('legajo') or '').strip() == legajo:
            fila(evento['fecha'], evento['operacion_a'])['polivalencia_nuevo_centavos'] += int(evento.get('premio_centavos') or 0)

    for item in nivel_3_cache:
        if str(item.get('legajo') or '').strip() != legajo:
            continue
        pago = int(round(float(item.get('premio_grupal') or 0) * 100))
        if pago:
            fila(item['fecha'], item.get('operacion', ''), item.get('grupo_productivo', ''))['grupal_nuevo_centavos'] += pago

    rows = []
    for row in detalle.values():
        row['total_nuevo_centavos'] = (row['individual_nuevo_centavos'] + row['polivalencia_nuevo_centavos']
                                       + row['grupal_nuevo_centavos'])
        row['diferencia_centavos'] = row['total_nuevo_centavos'] - row['pago_actual_centavos']
        if row['pago_actual_centavos'] or row['total_nuevo_centavos']:
            rows.append(row)
    rows.sort(key=lambda row: (row['fecha'], row['operacion'], row['grupo_productivo']))
    return {'legajo': legajo, 'rows': rows,
            'nota': ('Palets operados se compara bajo Carga; el pago grupal se muestra en la operación medida del grupo.'
                     if nivel_3_cache else
                     'Cálculo grupal pendiente para este período.')}


def _actividad_operacion(desc_funcion: Any) -> str:
    funcion = str(desc_funcion or '').strip().upper()
    if funcion == 'PICKIN':
        return 'ARMADO'
    if funcion in {'CARGA CAMION', 'CARGA REFRIGERADOS', 'TRASLADO', 'CARRETEO'}:
        return 'CARGA'
    if funcion in {'GUARDAD', 'SURTIDO P.C', 'UBICAC.REAPRO', 'EXTRAC.REAPRO', 'EXTRAC. TRASP.'}:
        return 'CLARK'
    if funcion in {'RECEPCION', 'REVISION', 'REVISIÓN'}:
        return 'RECEPCION'
    return funcion or 'SIN OPERACION'


ACTIVIDAD_OPERACION_SQL = """CASE
    WHEN UPPER(TRIM(COALESCE(w.desc_funcion,''))) = 'PICKIN' THEN 'ARMADO'
    WHEN UPPER(TRIM(COALESCE(w.desc_funcion,''))) IN ('CARGA CAMION','CARGA REFRIGERADOS','TRASLADO','CARRETEO') THEN 'CARGA'
    WHEN UPPER(TRIM(COALESCE(w.desc_funcion,''))) IN ('GUARDAD','SURTIDO P.C','UBICAC.REAPRO','EXTRAC.REAPRO','EXTRAC. TRASP.') THEN 'CLARK'
    WHEN UPPER(TRIM(COALESCE(w.desc_funcion,''))) IN ('RECEPCION','REVISION','REVISIÓN') THEN 'RECEPCION'
    ELSE UPPER(TRIM(COALESCE(w.desc_funcion,'')))
END"""


async def _ensure_actividad_duracion_cache(desde: str, hasta: str) -> None:
    """Materializa segundos por fecha/legajo/operación/división desde el detalle crudo."""
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        db.row_factory = aiosqlite.Row
        await db.execute('''INSERT OR IGNORE INTO lab_actividad_duracion_fecha(fecha)
            SELECT DISTINCT fecha FROM lab_actividad_duracion_cache WHERE fecha>=? AND fecha<=?''', (desde, hasta))
        start = datetime.strptime(desde, '%Y%m%d')
        end = datetime.strptime(hasta, '%Y%m%d')
        fechas = [(start + timedelta(days=i)).strftime('%Y%m%d') for i in range((end - start).days + 1)]
        placeholders_all = ','.join('?' for _ in fechas)
        async with db.execute(f'''SELECT fecha FROM lab_actividad_duracion_fecha
                WHERE fecha IN ({placeholders_all})''', tuple(fechas)) as cur:
            cached = {row['fecha'] for row in await cur.fetchall()}
        missing = [fecha for fecha in fechas if fecha not in cached]
        if not missing:
            await db.commit()
            return
        placeholders = ','.join('?' for _ in missing)
        await db.execute(f"DELETE FROM lab_actividad_duracion_cache WHERE fecha IN ({placeholders})", tuple(missing))
        await db.execute(f'''
            INSERT INTO lab_actividad_duracion_cache
                (fecha,legajo,operacion,division,segundos_validos,etapas_tiempo,etapas_inconsistentes,updated_at)
            WITH etapas AS (
                SELECT w.fecha, CAST(w.legajo AS TEXT) legajo, w.id_etapa,
                       {ACTIVIDAD_OPERACION_SQL} operacion,
                       TRIM(COALESCE(w.division,'')) division,
                       MIN(w.fyhini) inicio, MAX(w.fyhfin) fin
                FROM lab_etapa_detalle_raw w
                WHERE w.fecha IN ({placeholders})
                  AND TRIM(COALESCE(w.desc_funcion,'')) <> ''
                  AND UPPER(TRIM(COALESCE(w.desc_funcion,''))) NOT IN ('FICHADA ENTRADA','FIN DEL TURNO')
                  AND w.fyhini IS NOT NULL AND w.fyhfin IS NOT NULL
                GROUP BY w.fecha, CAST(w.legajo AS TEXT), w.id_etapa, {ACTIVIDAD_OPERACION_SQL},
                         TRIM(COALESCE(w.division,''))
            ), dif AS (
                SELECT fecha,legajo,operacion,division,
                       ROUND((julianday(fin)-julianday(inicio))*86400) diff
                FROM etapas
            ), normalizado AS (
                SELECT fecha,legajo,operacion,division,
                       CASE
                         WHEN diff>=0 THEN diff
                         WHEN diff<0 AND diff+86400 BETWEEN 0 AND 43200 THEN diff+86400
                         ELSE 0
                       END segundos,
                       CASE
                         WHEN diff>=0 THEN 1
                         WHEN diff<0 AND diff+86400 BETWEEN 0 AND 43200 THEN 1
                         ELSE 0
                       END valido,
                       CASE
                         WHEN diff<0 AND NOT (diff+86400 BETWEEN 0 AND 43200) THEN 1
                         ELSE 0
                       END inconsistente
                FROM dif
            )
            SELECT fecha,legajo,operacion,division,
                   COALESCE(SUM(segundos),0) segundos_validos,
                   COALESCE(SUM(valido),0) etapas_tiempo,
                   COALESCE(SUM(inconsistente),0) etapas_inconsistentes,
                   CURRENT_TIMESTAMP
            FROM normalizado
            GROUP BY fecha,legajo,operacion,division
            HAVING COALESCE(SUM(segundos),0)<>0 OR COALESCE(SUM(inconsistente),0)<>0
        ''', tuple(missing))
        await db.executemany('''INSERT INTO lab_actividad_duracion_fecha(fecha,updated_at)
                VALUES(?,CURRENT_TIMESTAMP)
                ON CONFLICT(fecha) DO UPDATE SET updated_at=CURRENT_TIMESTAMP''',
                             [(fecha,) for fecha in missing])
        await db.commit()


@router.get("/resumen-legajos/actividad/catalogo")
async def resumen_legajo_actividad_catalogo(request: Request):
    """Operaciones disponibles para consultar actividad productiva."""
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri() + '?mode=ro', uri=True) as db:
        async with db.execute(f'''
            SELECT operacion FROM (
                SELECT DISTINCT {ACTIVIDAD_OPERACION_SQL} AS operacion
                FROM lab_cache_agrupado w
                WHERE TRIM(COALESCE(w.desc_funcion,'')) <> ''
                  AND UPPER(TRIM(COALESCE(w.desc_funcion,''))) NOT IN ('FICHADA ENTRADA','FIN DEL TURNO')
                  AND (COALESCE(w.palets,0)<>0 OR COALESCE(w.cantidad,0)<>0 OR COALESCE(w.peso,0)<>0)
            )
            WHERE TRIM(COALESCE(operacion,'')) <> ''
            ORDER BY operacion
        ''') as cur:
            operaciones = [r[0] for r in await cur.fetchall()]
    preferidas = [op for op in ['ARMADO', 'CARGA', 'CLARK', 'RECEPCION'] if op in operaciones]
    resto = [op for op in operaciones if op not in preferidas]
    return {'operaciones': preferidas + resto}


@router.get("/resumen-legajos/actividad/resumen")
async def resumen_legajo_actividad_resumen(request: Request,
                                           fecha_desde: str = '2026-08-01',
                                           fecha_hasta: str = '2026-08-31'):
    """Resumen de actividad productiva por operación y división."""
    await _admin(request)
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    if desde > hasta:
        raise HTTPException(400, 'La fecha desde no puede ser posterior a la fecha hasta.')
    await _ensure_actividad_duracion_cache(desde, hasta)

    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f'''
            SELECT {ACTIVIDAD_OPERACION_SQL} operacion_agrupada,
                   TRIM(COALESCE(w.division,'')) division,
                   COUNT(DISTINCT w.fecha) dias_con_actividad,
                   COUNT(DISTINCT CAST(w.legajo AS TEXT)) legajos_con_actividad,
                   COALESCE(SUM(w.cantidad),0) bultos,
                   COALESCE(SUM(w.palets),0) palets,
                   COALESCE(SUM(w.detalle_filas),0) etapas,
                   COALESCE(MAX(tiempo.segundos_validos),0) segundos_validos,
                   COALESCE(MAX(tiempo.etapas_inconsistentes),0) etapas_inconsistentes
            FROM lab_cache_agrupado w
            LEFT JOIN (
                SELECT operacion,division,
                       COALESCE(SUM(segundos_validos),0) segundos_validos,
                       COALESCE(SUM(etapas_inconsistentes),0) etapas_inconsistentes
                FROM lab_actividad_duracion_cache
                WHERE fecha>=? AND fecha<=?
                GROUP BY operacion,division
            ) tiempo
              ON tiempo.operacion={ACTIVIDAD_OPERACION_SQL}
             AND tiempo.division=TRIM(COALESCE(w.division,''))
            WHERE w.fecha>=? AND w.fecha<=?
              AND TRIM(COALESCE(w.desc_funcion,'')) <> ''
              AND UPPER(TRIM(COALESCE(w.desc_funcion,''))) NOT IN ('FICHADA ENTRADA','FIN DEL TURNO')
              AND (COALESCE(w.palets,0)<>0 OR COALESCE(w.cantidad,0)<>0 OR COALESCE(w.peso,0)<>0)
            GROUP BY {ACTIVIDAD_OPERACION_SQL}, TRIM(COALESCE(w.division,''))
            HAVING (
                {ACTIVIDAD_OPERACION_SQL} = 'ARMADO' AND COALESCE(SUM(w.cantidad),0) <> 0
            ) OR (
                {ACTIVIDAD_OPERACION_SQL} IN ('CARGA','CLARK','RECEPCION') AND COALESCE(SUM(w.palets),0) <> 0
            ) OR (
                {ACTIVIDAD_OPERACION_SQL} NOT IN ('ARMADO','CARGA','CLARK','RECEPCION')
                AND (COALESCE(SUM(w.cantidad),0) <> 0 OR COALESCE(SUM(w.palets),0) <> 0)
            )
            ORDER BY operacion_agrupada, CAST(TRIM(COALESCE(w.division,'')) AS INTEGER)
        ''', (desde, hasta, desde, hasta)) as cur:
            source_rows = [dict(row) for row in await cur.fetchall()]

    rows: list[dict[str, Any]] = []
    for row in source_rows:
        operacion = row.get('operacion_agrupada') or ''
        bultos = float(row.get('bultos') or 0)
        palets = float(row.get('palets') or 0)
        if operacion == 'ARMADO':
            produccion = bultos
            unidad = 'BULTO'
        elif operacion in {'CARGA', 'CLARK', 'RECEPCION'}:
            produccion = palets
            unidad = 'PALET'
        else:
            produccion = bultos if bultos else palets
            unidad = 'BULTO' if bultos else 'PALET'
        rows.append({
            'operacion_agrupada': operacion,
            'division': row.get('division') or '',
            'division_desc': DIVISIONES_DESCRIPCION.get(str(row.get('division') or '').strip(), ''),
            'dias_con_actividad': int(row.get('dias_con_actividad') or 0),
            'legajos_con_actividad': int(row.get('legajos_con_actividad') or 0),
            'unidad': unidad,
            'bultos': round(bultos, 3),
            'palets': round(palets, 3),
            'produccion_real': round(produccion, 3),
            'productividad_promedio': round(produccion / max(1, int(row.get('dias_con_actividad') or 0)), 3),
            'segundos_validos': int(round(float(row.get('segundos_validos') or 0))),
            'etapas_inconsistentes_tiempo': int(row.get('etapas_inconsistentes') or 0),
            'etapas': int(row.get('etapas') or 0),
        })
    return {'rows': rows, 'total': len(rows),
            'nota': 'Resumen agrupado por operación y división para el rango seleccionado.'}


@router.get("/resumen-legajos/actividad")
async def resumen_legajo_actividad(request: Request, legajo: str = '',
                                   fecha_desde: str = '2026-08-01',
                                   fecha_hasta: str = '2026-08-31',
                                   operacion: str = '',
                                   division: str = '',
                                   limit: int = 1000,
                                   offset: int = 0):
    """Actividad productiva WMS del legajo en el rango seleccionado."""
    await _admin(request)
    legajo = str(legajo or '').strip()
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    if desde > hasta:
        raise HTTPException(400, 'La fecha desde no puede ser posterior a la fecha hasta.')
    limit = max(100, min(int(limit or 1000), 5000))
    offset = max(0, int(offset or 0))
    operacion = str(operacion or '').strip().upper()
    division = str(division or '').strip()
    await _ensure_actividad_duracion_cache(desde, hasta)

    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("ATTACH DATABASE ? AS rrhh_legajero", (str(RRHH_GRUPAL_DB_PATH),))
        legajo_filter = "AND CAST(w.legajo AS TEXT) LIKE ?" if legajo else ""
        operacion_filter = f"AND {ACTIVIDAD_OPERACION_SQL} = ?" if operacion else ""
        division_filter = "AND TRIM(COALESCE(w.division,'')) = ?" if division else ""
        args: list[Any] = [desde, hasta]
        if legajo:
            args.append(f"%{legajo}%")
        if operacion:
            args.append(operacion)
        if division:
            args.append(division)
        grouped_sql = f'''
            SELECT w.fecha, CAST(w.legajo AS TEXT) legajo,
                   COALESCE(pers.nombre,'') nombre,
                   COALESCE(pers.sector_legajero,'') sector_legajero,
                   COALESCE(pers.funcion_legajero,'') funcion_legajero,
                   {ACTIVIDAD_OPERACION_SQL} operacion_agrupada,
                   GROUP_CONCAT(DISTINCT TRIM(COALESCE(w.desc_funcion,''))) desc_funcion,
                   TRIM(COALESCE(w.division,'')) division,
                   COALESCE(otras.otras_operaciones,'') otras_operaciones,
                   COALESCE(MAX(tiempo.segundos_validos),0) segundos_validos,
                   COALESCE(MAX(tiempo.etapas_inconsistentes),0) etapas_inconsistentes,
                   COALESCE(SUM(w.palets),0) palets,
                   COALESCE(SUM(w.cantidad),0) cantidad,
                   COALESCE(SUM(w.peso),0) peso,
                   COALESCE(SUM(w.detalle_filas),0) etapas
            FROM lab_cache_agrupado
            w LEFT JOIN (SELECT CAST(legajo AS TEXT) legajo, MAX(nombre) nombre,
                                MAX(desc_sector_generico) sector_legajero,
                                MAX(desc_funcion) funcion_legajero
                         FROM rrhh_legajero.rrhh_personas GROUP BY CAST(legajo AS TEXT)) pers
              ON pers.legajo=CAST(w.legajo AS TEXT)
            LEFT JOIN (
                SELECT fecha, CAST(legajo AS TEXT) legajo,
                       GROUP_CONCAT(DISTINCT operacion) otras_operaciones
                FROM (
                    SELECT fecha, legajo, {ACTIVIDAD_OPERACION_SQL} operacion
                    FROM lab_cache_agrupado w
                    WHERE fecha>=? AND fecha<=?
                      AND TRIM(COALESCE(w.desc_funcion,'')) <> ''
                      AND UPPER(TRIM(COALESCE(w.desc_funcion,''))) NOT IN ('FICHADA ENTRADA','FIN DEL TURNO')
                      AND (COALESCE(w.palets,0)<>0 OR COALESCE(w.cantidad,0)<>0 OR COALESCE(w.peso,0)<>0)
                      AND {ACTIVIDAD_OPERACION_SQL} IN ('ARMADO','CARGA','CLARK','RECEPCION')
                      AND {ACTIVIDAD_OPERACION_SQL} <> ?
                    GROUP BY fecha, CAST(legajo AS TEXT), {ACTIVIDAD_OPERACION_SQL}
                )
                GROUP BY fecha, CAST(legajo AS TEXT)
            ) otras ON otras.fecha=w.fecha AND otras.legajo=CAST(w.legajo AS TEXT)
            LEFT JOIN lab_actividad_duracion_cache tiempo
              ON tiempo.fecha=w.fecha
             AND tiempo.legajo=CAST(w.legajo AS TEXT)
             AND tiempo.operacion={ACTIVIDAD_OPERACION_SQL}
             AND tiempo.division=TRIM(COALESCE(w.division,''))
            WHERE w.fecha>=? AND w.fecha<=? {legajo_filter} {operacion_filter} {division_filter}
              AND TRIM(COALESCE(w.desc_funcion,'')) <> ''
              AND UPPER(TRIM(COALESCE(w.desc_funcion,''))) NOT IN ('FICHADA ENTRADA','FIN DEL TURNO')
              AND (COALESCE(w.palets,0)<>0 OR COALESCE(w.cantidad,0)<>0 OR COALESCE(w.peso,0)<>0)
            GROUP BY w.fecha, CAST(w.legajo AS TEXT), COALESCE(pers.nombre,''),
                     COALESCE(pers.sector_legajero,''), COALESCE(pers.funcion_legajero,''),
                     {ACTIVIDAD_OPERACION_SQL}, TRIM(COALESCE(w.division,'')), COALESCE(otras.otras_operaciones,'')
            HAVING (
                {ACTIVIDAD_OPERACION_SQL} = 'ARMADO' AND COALESCE(SUM(w.cantidad),0) <> 0
            ) OR (
                {ACTIVIDAD_OPERACION_SQL} IN ('CARGA','CLARK','RECEPCION') AND COALESCE(SUM(w.palets),0) <> 0
            ) OR (
                {ACTIVIDAD_OPERACION_SQL} NOT IN ('ARMADO','CARGA','CLARK','RECEPCION')
                AND (COALESCE(SUM(w.cantidad),0) <> 0 OR COALESCE(SUM(w.palets),0) <> 0)
            )
        '''
        query_args: list[Any] = [desde, hasta, operacion or '']
        query_args.extend(args)
        async with db.execute(f'SELECT COUNT(*) FROM ({grouped_sql}) conteo', tuple(query_args)) as cur:
            total = int((await cur.fetchone())[0] or 0)
        async with db.execute(f'''{grouped_sql}
            ORDER BY w.fecha, CAST(w.legajo AS TEXT), operacion_agrupada,
                     CAST(TRIM(COALESCE(w.division,'')) AS INTEGER)
            LIMIT ? OFFSET ?''', tuple(query_args + [limit, offset])) as cur:
            source_rows = [dict(row) for row in await cur.fetchall()]

    rows: list[dict[str, Any]] = []
    for row in source_rows:
        operacion_row = row.get('operacion_agrupada') or _actividad_operacion(row.get('desc_funcion'))
        cantidad = float(row.get('cantidad') or 0)
        palets = float(row.get('palets') or 0)
        if operacion_row == 'ARMADO':
            produccion = cantidad
            unidad = 'BULTO'
        elif operacion_row in {'CARGA', 'CLARK', 'RECEPCION'}:
            produccion = palets
            unidad = 'PALET'
        else:
            produccion = cantidad if cantidad else palets
            unidad = 'BULTO' if cantidad else 'PALET'
        rows.append({
            'fecha': row['fecha'],
            'legajo': row['legajo'],
            'nombre': row.get('nombre') or '',
            'sector_legajero': row.get('sector_legajero') or '',
            'funcion_legajero': row.get('funcion_legajero') or '',
            'funcion_realizada': row.get('desc_funcion') or '',
            'operacion_agrupada': operacion_row,
            'otras_operaciones_medibles': row.get('otras_operaciones') or '',
            'hizo_otra_operacion_medible': bool(row.get('otras_operaciones')),
            'division': row.get('division') or '',
            'division_desc': DIVISIONES_DESCRIPCION.get(str(row.get('division') or '').strip(), ''),
            'produccion_real': round(produccion, 3),
            'unidad': unidad,
            'bultos': round(cantidad, 3),
            'palets': round(palets, 3),
            'peso': round(float(row.get('peso') or 0), 3),
            'segundos_validos': int(round(float(row.get('segundos_validos') or 0))),
            'etapas_inconsistentes_tiempo': int(row.get('etapas_inconsistentes') or 0),
            'etapas': int(row.get('etapas') or 0),
        })
    return {'legajo': legajo, 'operacion': operacion, 'division': division, 'rows': rows, 'total': total, 'limit': limit, 'offset': offset,
            'has_more': offset + len(rows) < total,
            'nota': 'Actividad productiva agrupada por fecha, legajo, operación y división; Producción real usa bultos para Armado y palets para Carga, Clark y Recepción.'}


@router.get("/propuesta-individual-carga")
async def propuesta_individual_carga(request: Request, fecha_desde: str = '2026-08-01',
                                     fecha_hasta: str = '2026-08-31'):
    """Busca cortes Desde/Hasta para acercar Carga Secos al 35%, sin cambiar premios."""
    await _admin(request)
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''SELECT unidades_evaluadas,premio_nuevo FROM lab_evaluacion_premio
                WHERE fecha>=? AND fecha<=? AND UPPER(operacion_premio)='CARGA'
                AND UPPER(grupo_productivo)='AREA SECOS Y NO ALIMENTOS'
                AND unidad_medida='PALET' AND unidades_evaluadas IS NOT NULL''', (desde, hasta)) as cur:
            activity = [(float(r['unidades_evaluadas']), float(r['premio_nuevo'] or 0)) for r in await cur.fetchall()]
        async with db.execute('''SELECT COALESCE(SUM(pago_centavos),0) FROM lab_pago_actual_operacion
                WHERE fecha>=? AND fecha<=? AND UPPER(operacion)='CARGA' AND UPPER(grupo)=?''', (desde, hasta, 'AREA SECOS Y NO ALIMENTOS')) as cur:
            actual = int((await cur.fetchone())[0] or 0)
    target = round(actual * 0.35)
    payments = [0, 663341, 1010484, 1539025, 2076950, 3290396, 5162537]
    current_edges = [159, 174, 189, 199, 209, 214]
    def score(factor):
        edges = [round(x * factor) for x in current_edges]
        total = 0
        for units, _ in activity:
            level = 0
            while level < len(edges) and units > edges[level]: level += 1
            total += payments[min(level, 6)]
        return total, edges
    candidates = [(abs(score(f)[0]-target), f, *score(f)) for f in [0.25+i*0.0025 for i in range(1001)]]
    _, factor, proposed, edges = min(candidates, key=lambda x:x[0])
    return {'universo': {'operacion':'CARGA','grupo_productivo':'AREA SECOS Y NO ALIMENTOS','unidad':'PALET','fecha_desde':desde,'fecha_hasta':hasta},
            'muestra_filas':len(activity),'pago_actual_centavos':actual,'objetivo_35_centavos':target,
            'premio_nuevo_actual_centavos':round(sum(x[1] for x in activity)*100),
            'propuesta_centavos':proposed,'diferencia_propuesta_centavos':proposed-target,
            'factor_cortes':factor,
            'escala_propuesta':[{'nivel':0,'desde':0,'hasta':edges[0],'premio_centavos':payments[0]},
                *[{'nivel':i,'desde':edges[i-1]+1,'hasta':edges[i],'premio_centavos':payments[i]} for i in range(1,6)],
                {'nivel':6,'desde':edges[5]+1,'hasta':999999999,'premio_centavos':payments[6]}],
            'nota':'Sólo se ajustan cortes Desde/Hasta. Los premios son los importes actuales y no se aplica ningún cambio.'}


@router.get("/cache-wms")
async def cache_wms(
    request: Request,
    fecha_desde: str = Query("2026-08-01"),
    fecha_hasta: str = Query("2026-08-31"),
    legajo: str = Query(""),
    desc_funcion: str = Query(""),
    limit: int = Query(250, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    if str(auth.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Requiere administrador.")
    try:
        desde = datetime.strptime(fecha_desde, "%Y-%m-%d").strftime("%Y%m%d")
        hasta = datetime.strptime(fecha_hasta, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Las fechas deben tener formato YYYY-MM-DD.") from exc
    if desde > hasta:
        raise HTTPException(status_code=400, detail="Fecha desde no puede ser posterior a fecha hasta.")
    where = ["run_id LIKE ?", "fecha >= ?", "fecha <= ?"]
    args: list[Any] = [f"{LAB_CACHE_RUN_PREFIX}%", desde, hasta]
    if legajo.strip():
        where.append("CAST(legajo AS TEXT) LIKE ?")
        args.append(f"%{legajo.strip()}%")
    if desc_funcion.strip():
        where.append("UPPER(COALESCE(desc_funcion, '')) LIKE ?")
        args.append(f"%{desc_funcion.strip().upper()}%")
    predicate = " AND ".join(where)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        agrupada = f"""SELECT MIN(row_id) AS row_id, fecha,legajo,id_etapa,fyhini,fyhfin,cod_funcion,desc_funcion,division,sector,
                COUNT(*) AS filas_fuente, COUNT(DISTINCT CASE WHEN TRIM(COALESCE(pallet,'')) NOT IN ('','0','*') THEN TRIM(pallet) END) AS pallet,
                COUNT(DISTINCT NULLIF(plu,'')) AS plu, SUM(COALESCE(cantidad,0)) AS cantidad,
                SUM(COALESCE(peso,0)) AS peso
            FROM lab_etapa_detalle_raw WHERE {predicate}
            GROUP BY run_id,fecha,legajo,id_etapa,fyhini,fyhfin,cod_funcion,desc_funcion,division,sector"""
        async with db.execute(f"SELECT COUNT(*) AS total FROM ({agrupada})", tuple(args)) as cur:
            total = int((await cur.fetchone())["total"] or 0)
        async with db.execute(
            f"""SELECT * FROM ({agrupada})
                ORDER BY fecha, legajo, fyhini, id_etapa LIMIT ? OFFSET ?""",
            tuple(args + [limit, offset]),
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    return {
        "filters": {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta, "legajo": legajo.strip(), "desc_funcion": desc_funcion.strip()},
        "total": total, "limit": limit, "offset": offset,
        "has_more": offset + len(rows) < total, "rows": rows,
        "source": {"db": str(LAB_CACHE_DB_PATH), "run_prefix": LAB_CACHE_RUN_PREFIX},
    }


@router.get("/cache-wms/etapa-detalle")
async def cache_wms_etapa_detalle(request: Request, fecha: str, legajo: str, id_etapa: str):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""SELECT source_row_num,pallet,plu,cantidad,peso
            FROM lab_etapa_detalle_raw WHERE run_id LIKE ? AND fecha=? AND CAST(legajo AS TEXT)=? AND id_etapa=?
            ORDER BY source_row_num""", (f"{LAB_CACHE_RUN_PREFIX}%", fecha, legajo, id_etapa)) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    return {"rows": rows}


async def _recalcular_palets_carga_traslado(db: aiosqlite.Connection, desde: str, hasta: str) -> int:
    """Construye contribuciones auditables por palet a partir de etapas WMS."""
    db.row_factory = aiosqlite.Row
    query = '''SELECT fecha,CAST(legajo AS TEXT) legajo,pallet,id_etapa,
        MIN(COALESCE(fyhini,'')) inicio,MAX(COALESCE(fyhfin,'')) fin,
        UPPER(TRIM(desc_funcion)) funcion,MAX(TRIM(COALESCE(division,''))) division
        FROM lab_etapa_detalle_raw
        WHERE run_id LIKE ? AND fecha>=? AND fecha<=? AND TRIM(COALESCE(pallet,''))<>''
          AND UPPER(TRIM(desc_funcion)) IN ('CARGA CAMION','CARGA REFRIGERADOS','TRASLADO')
        GROUP BY fecha,CAST(legajo AS TEXT),pallet,id_etapa,UPPER(TRIM(desc_funcion))
        ORDER BY fecha,pallet,inicio,fin,id_etapa'''
    async with db.execute(query, (f'{LAB_CACHE_RUN_PREFIX}%', desde, hasta)) as cur:
        etapas = [dict(row) for row in await cur.fetchall()]
    por_palet: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for etapa in etapas:
        por_palet[(etapa['fecha'], str(etapa['pallet']))].append(etapa)
    resultado = []
    for (fecha, pallet), secuencia in por_palet.items():
        contribuciones: list[dict[str, Any]] = []
        for etapa in secuencia:
            if etapa['funcion'] == 'TRASLADO':
                contribuciones.append({'legajo': etapa['legajo'], 'inicio': etapa['inicio'], 'fin': etapa['fin'],
                    'division': str(etapa.get('division') or '').strip(),
                    'traslado': 1, 'carga': 0, 'tipo': 'Traslado', 'detalle': f"Traslado etapa {etapa['id_etapa']}"})
                continue
            # Una carga posterior del mismo operario absorbe sólo su traslado
            # físico más reciente. Con otro legajo, ambos conservan un crédito.
            previa = next((item for item in reversed(contribuciones)
                           if item['legajo'] == etapa['legajo'] and item['traslado'] and not item['carga']), None)
            if previa:
                previa['carga'] = 1; previa['fin'] = etapa['fin'] or previa['fin']
                if etapa.get('division'):
                    previa['division'] = str(etapa.get('division') or '').strip()
                previa['tipo'] = 'Traslado + carga'
                previa['detalle'] += f" · Carga etapa {etapa['id_etapa']}"
            else:
                contribuciones.append({'legajo': etapa['legajo'], 'inicio': etapa['inicio'], 'fin': etapa['fin'],
                    'division': str(etapa.get('division') or '').strip(),
                    'traslado': 0, 'carga': 1, 'tipo': 'Carga', 'detalle': f"Carga etapa {etapa['id_etapa']}"})
        por_legajo: dict[str, int] = defaultdict(int)
        for item in contribuciones:
            por_legajo[item['legajo']] += 1
            resultado.append((fecha, item['legajo'], pallet, por_legajo[item['legajo']], item['inicio'], item['fin'],
                              item['traslado'], item['carga'], item['tipo'], item['detalle'], item.get('division','')))
    await db.execute('DELETE FROM lab_palets_carga_traslado WHERE fecha>=? AND fecha<=?', (desde, hasta))
    await db.executemany('''INSERT INTO lab_palets_carga_traslado
        (fecha,legajo,pallet,contribucion,inicio,fin,etapas_traslado,etapas_carga,tipo,detalle,division)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)''', resultado)
    await db.commit()


async def _eventos_polivalencia_nueva(db, desde: str, hasta: str, legajo: str = '') -> list[dict[str, Any]]:
    """Una regla de perfil abona una sola vez por legajo, jornada y regla."""
    await db.execute("ATTACH DATABASE ? AS rrhh", (str(RRHH_GRUPAL_DB_PATH),))
    condicion_legajo = " AND CAST(m.legajo AS TEXT)=?" if legajo else ""
    q = '''WITH asistencia AS (
             SELECT CAST(json_extract(payload,'$.FECHA') AS TEXT) fecha,
                    CAST(json_extract(payload,'$.LEGAJO') AS TEXT) legajo,
                    MAX(CASE WHEN UPPER(TRIM(COALESCE(json_extract(payload,'$.AUSENTE'),'')))='SI' THEN 1 ELSE 0 END) ausente
             FROM lab_fuente_registro
             WHERE fuente='oracle.PV_DIA_LABORAL'
               AND snapshot=(SELECT snapshot FROM lab_fuente_lote
                             WHERE fuente='oracle.PV_DIA_LABORAL'
                             ORDER BY capturado DESC LIMIT 1)
             GROUP BY CAST(json_extract(payload,'$.FECHA') AS TEXT),
                      CAST(json_extract(payload,'$.LEGAJO') AS TEXT)),
             personas AS (
             SELECT CAST(legajo AS TEXT) legajo,MAX(nombre) nombre,MAX(desc_sector_generico) sector,
                    MAX(desc_funcion) funcion FROM rrhh.rrhh_personas GROUP BY CAST(legajo AS TEXT)),
             madres AS (
             SELECT DISTINCT w.fecha,w.legajo,p.nombre,p.sector,p.funcion,tf.turno_fijo AS turno,
                    UPPER(TRIM(pg.operacion_medible)) operacion_madre
             FROM lab_cache_agrupado w
             JOIN personas p ON p.legajo=CAST(w.legajo AS TEXT)
             JOIN lab_turno_fijo_legajo tf ON CAST(tf.legajo AS TEXT)=CAST(w.legajo AS TEXT)
             JOIN asistencia a ON a.fecha=w.fecha AND a.legajo=CAST(w.legajo AS TEXT)
                             AND a.ausente=0
             JOIN lab_parametro_grupal pg ON pg.activo=1
                AND UPPER(TRIM(pg.sector))=UPPER(TRIM(p.sector))
                AND UPPER(TRIM(pg.funcion_legajero))=UPPER(TRIM(p.funcion))
                AND TRIM(pg.turno)=TRIM(tf.turno_fijo)
             WHERE w.fecha>=? AND w.fecha<=? AND TRIM(COALESCE(pg.operacion_medible,''))<>''),
             ops AS (SELECT DISTINCT fecha,legajo,UPPER(TRIM(desc_funcion)) operacion_b
             FROM lab_cache_agrupado WHERE fecha>=? AND fecha<=?)
             SELECT m.fecha,CAST(m.legajo AS TEXT) legajo,m.nombre,m.sector,m.funcion,m.turno,
                    r.operacion_madre operacion_a,GROUP_CONCAT(DISTINCT o.operacion_b) operaciones_b,
                    r.premio_centavos
             FROM madres m
             JOIN lab_polivalencia_regla r ON r.activo=1
                  AND UPPER(TRIM(r.sector))=UPPER(TRIM(m.sector))
                  AND UPPER(TRIM(r.funcion_legajero))=UPPER(TRIM(m.funcion))
                  AND UPPER(TRIM(r.operacion_madre))=m.operacion_madre
             JOIN lab_polivalencia_regla_operacion configurada ON configurada.regla_id=r.id
             JOIN ops o ON o.fecha=m.fecha AND o.legajo=m.legajo AND o.operacion_b=configurada.operacion_b
             WHERE r.premio_centavos>0''' + condicion_legajo + '''
             GROUP BY m.fecha,m.legajo,r.id'''
    async with db.execute(q, (desde, hasta, desde, hasta, *([legajo] if legajo else []))) as cur:
        return [dict(row) for row in await cur.fetchall()]
    return len(resultado)


@router.post('/palets-carga-traslado/recalcular')
async def recalcular_palets_carga_traslado(request: Request, fecha_desde: str = '2026-08-01', fecha_hasta: str = '2026-08-31'):
    await _admin(request)
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        total = await _recalcular_palets_carga_traslado(db, desde, hasta)
    return {'ok': True, 'contribuciones': total, 'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta,
            'regla': 'Traslado seguido de carga por el mismo legajo cuenta una vez; con otro legajo cuenta para ambos; cada etapa de traslado adicional cuenta otra vez.'}


@router.get('/palets-carga-traslado')
async def palets_carga_traslado(request: Request, fecha_desde: str = '2026-08-01', fecha_hasta: str = '2026-08-31', legajo: str = ''):
    await _admin(request)
    desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
    hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    where = ['fecha>=?', 'fecha<=?']; args: list[Any] = [desde, hasta]
    if legajo.strip(): where.append('legajo LIKE ?'); args.append(f'%{legajo.strip()}%')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f'''SELECT fecha,legajo,COUNT(*) palets_trabajados,
            SUM(etapas_traslado) traslados,SUM(etapas_carga) cargas
            FROM lab_palets_carga_traslado WHERE {' AND '.join(where)}
            GROUP BY fecha,legajo ORDER BY fecha,legajo''', tuple(args)) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    return {'rows': rows, 'total': len(rows)}
