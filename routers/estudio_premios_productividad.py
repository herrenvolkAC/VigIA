from __future__ import annotations

from datetime import datetime
from collections import Counter
import math
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


async def _ensure_config(db):
    await db.execute('''CREATE TABLE IF NOT EXISTS lab_escala_override(
        operacion TEXT NOT NULL, grupo_productivo TEXT NOT NULL DEFAULT '', nivel INTEGER NOT NULL,
        desde REAL NOT NULL, hasta REAL NOT NULL, premio REAL NOT NULL DEFAULT 0,
        premio_por_unidad_excedente REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(operacion,grupo_productivo,nivel,desde,hasta))''')
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
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(operacion_a, operacion_b))""")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_ausencia_config(
        cod_ausentismo TEXT PRIMARY KEY, descripcion TEXT NOT NULL DEFAULT '', permitido INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    await db.execute("""CREATE TABLE IF NOT EXISTS lab_parametro_grupal(
        sector TEXT NOT NULL, funcion_legajero TEXT NOT NULL, turno TEXT NOT NULL,
        uc_por_operario REAL NOT NULL DEFAULT 0, factor_ausentismo REAL NOT NULL DEFAULT 0,
        premio_grupal REAL NOT NULL DEFAULT 0, activo INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(sector,funcion_legajero,turno))""")
    async with db.execute('PRAGMA table_info(lab_parametro_grupal)') as cur:
        columnas_grupales = {row[1] for row in await cur.fetchall()}
    if 'operacion_medible' not in columnas_grupales:
        await db.execute("ALTER TABLE lab_parametro_grupal ADD COLUMN operacion_medible TEXT NOT NULL DEFAULT ''")
    if 'grupo_productivo_id' not in columnas_grupales:
        await db.execute('ALTER TABLE lab_parametro_grupal ADD COLUMN grupo_productivo_id INTEGER')
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
    await db.execute("""INSERT OR IGNORE INTO lab_grupo_productivo_equivalencia(grupo_cache)
        SELECT DISTINCT TRIM(division) FROM lab_cache_agrupado
        WHERE TRIM(COALESCE(division,'')) <> ''""")
    await db.commit()

@router.get("/mapa-polivalencia")
async def mapa_polivalencia(request: Request):
    await _admin(request)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT DISTINCT UPPER(TRIM(operacion_premio)) op FROM lab_evaluacion_premio WHERE TRIM(COALESCE(operacion_premio,''))<>'' UNION SELECT DISTINCT UPPER(TRIM(desc_funcion)) FROM lab_cache_agrupado WHERE TRIM(COALESCE(desc_funcion,''))<>'' ORDER BY 1") as cur:
            operaciones = [r[0] for r in await cur.fetchall()]
        async with db.execute("SELECT operacion_a,operacion_b,polivalencia,updated_at FROM lab_mapa_polivalencia ORDER BY operacion_a,operacion_b") as cur:
            relaciones = [dict(r) for r in await cur.fetchall()]
    return {"operaciones": operaciones, "relaciones": relaciones}

@router.get("/polivalencias")
async def polivalencias(request: Request, fecha_desde: str = '2026-08-01', fecha_hasta: str = '2026-08-31', legajo: str = ''):
    await _admin(request)
    try:
        desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
        hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise HTTPException(400, 'Fechas inválidas.') from exc
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("ATTACH DATABASE ? AS rrhh", (str(ROOT_DIR / 'datos' / 'vigia.db'),))
        q = '''WITH madres AS (SELECT DISTINCT fecha,legajo,UPPER(TRIM(desc_funcion)) operacion_madre
             FROM lab_cache_agrupado WHERE fecha>=? AND fecha<=? AND UPPER(TRIM(desc_funcion)) IN ('CARGA CAMION','TRASLADO')
             AND (?='' OR CAST(legajo AS TEXT) LIKE ?)), ops AS (SELECT DISTINCT fecha,legajo,UPPER(TRIM(desc_funcion)) operacion_b
             FROM lab_cache_agrupado WHERE fecha>=? AND fecha<=?)
             SELECT m.fecha,m.legajo,pers.nombre,pers.desc_sector_generico AS sector,pers.desc_funcion AS funcion,m.operacion_madre,o.operacion_b,0.0 AS pago_polivalencia
             FROM madres m JOIN ops o ON o.fecha=m.fecha AND o.legajo=m.legajo
             JOIN lab_mapa_polivalencia p ON p.operacion_a=CASE WHEN m.operacion_madre='CARGA CAMION' THEN 'CARGA' ELSE m.operacion_madre END AND p.operacion_b=o.operacion_b AND p.polivalencia=1
             LEFT JOIN (SELECT legajo,MAX(nombre) nombre,MAX(desc_sector_generico) desc_sector_generico,MAX(desc_funcion) desc_funcion FROM rrhh.rrhh_personas GROUP BY legajo) pers ON CAST(pers.legajo AS TEXT)=CAST(m.legajo AS TEXT)
             WHERE o.operacion_b NOT IN ('CARGA CAMION','CARGA','TRASLADO') ORDER BY m.fecha,m.legajo,m.operacion_madre,o.operacion_b'''
        async with db.execute(q, (desde,hasta,legajo.strip(),f'%{legajo.strip()}%',desde,hasta)) as cur:
            rows=[dict(r) for r in await cur.fetchall()]
    return {'rows':rows,'total':len(rows),'pago_total':0}

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
    async with db.execute("SELECT desc_funcion,unidad_medida FROM lab_funcion_parametro WHERE medible=1 AND unidad_medida IN ('PALET','BULTO','PLU') ORDER BY desc_funcion") as cur:
        return {row[0]: row[1] for row in await cur.fetchall()}


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
        async with db.execute('SELECT legajo,nombre,desc_sector_generico,desc_funcion,active,fecha_ingreso,fecha_baja FROM rrhh_personas WHERE active=1') as cur:
            return [dict(r) for r in await cur.fetchall()]


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
        operaciones = await _operaciones_grupales(db)
        grupos = await _catalogo_grupos_productivos(db)
        _identificar_grupos_parametros(rows, grupos)
    async with aiosqlite.connect(RRHH_GRUPAL_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT DISTINCT desc_sector_generico AS sector,desc_funcion AS funcion_legajero FROM rrhh_personas WHERE active=1 ORDER BY desc_sector_generico,desc_funcion") as cur:
            catalogo = [dict(r) for r in await cur.fetchall()]
    return {'rows': rows, 'catalogo': catalogo, 'grupos_productivos': grupos,
            'operaciones': [{'operacion': op, 'unidad_medida': unidad} for op, unidad in operaciones.items()]}


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
        operaciones = await _operaciones_grupales(db)
        grupos = await _catalogo_grupos_productivos(db)
        _identificar_grupos_parametros(parametros, grupos)
        async with db.execute('SELECT operacion_a,operacion_b FROM lab_mapa_polivalencia WHERE polivalencia=1') as cur:
            relaciones = [tuple(r) for r in await cur.fetchall()]
        async with db.execute('SELECT cod_ausentismo,permitido FROM lab_ausencia_config') as cur:
            ausencias = {str(r[0]): bool(r[1]) for r in await cur.fetchall()}
        async with db.execute("SELECT snapshot FROM lab_fuente_lote WHERE fuente='oracle.PV_DIA_LABORAL' ORDER BY capturado DESC LIMIT 1") as cur:
            snapshot_row = await cur.fetchone()
        if not snapshot_row:
            raise HTTPException(409, 'No hay un snapshot local de asistencia PV_DIA_LABORAL.')
        snapshot = snapshot_row[0]
        async with db.execute("SELECT payload FROM lab_fuente_registro WHERE snapshot=? AND fuente='oracle.PV_DIA_LABORAL'", (snapshot,)) as cur:
            jornadas = [json.loads(r[0]) for r in await cur.fetchall()]
        async with db.execute('SELECT fecha,legajo,desc_funcion,palets,plus,cantidad FROM lab_cache_agrupado WHERE fecha>=? AND fecha<=?', (desde, hasta)) as cur:
            produccion = [dict(r) for r in await cur.fetchall()]
    async with aiosqlite.connect(RRHH_GRUPAL_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT legajo,nombre,desc_sector_generico,desc_funcion,active,fecha_ingreso,fecha_baja FROM rrhh_personas WHERE active=1') as cur:
            personas = [dict(r) for r in await cur.fetchall()]
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        turnos = await _fijar_turnos_nuevos(db, personas, jornadas, snapshot)
    result = calcular_grupal(personas, jornadas, produccion, parametros, operaciones,
                             relaciones, ausencias, desde, hasta, {r['legajo']: r['turno_fijo'] for r in turnos})
    result['snapshot'] = snapshot
    result['nota'] = 'Plantel fijo por sector/función y turno madre guardado. Toda actividad del legajo, aunque se ejecute en otro turno, se atribuye una sola vez al turno madre. Sin turno fijo: revisar la lista pendiente y asignar en Parámetros grupales. El legajero activo es el actual; no reconstruye transferencias históricas.'
    return result


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
            async with db.execute('SELECT grupo_productivo_id FROM lab_parametro_grupal WHERE sector=? AND funcion_legajero=? AND turno=?', (sector, funcion, turno)) as cur:
                anterior = await cur.fetchone()
            group_id = anterior[0] if anterior else None
        await db.execute("""INSERT INTO lab_parametro_grupal
            (sector,funcion_legajero,turno,operacion_medible,uc_por_operario,factor_ausentismo,premio_grupal,activo,grupo_productivo_id)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(sector,funcion_legajero,turno) DO UPDATE SET
            operacion_medible=excluded.operacion_medible,uc_por_operario=excluded.uc_por_operario,
            factor_ausentismo=excluded.factor_ausentismo,premio_grupal=excluded.premio_grupal,
            activo=excluded.activo,grupo_productivo_id=excluded.grupo_productivo_id,updated_at=CURRENT_TIMESTAMP""",
            (sector, funcion, turno, operacion, uc, factor, premio, 1 if data.get('activo', True) else 0, group_id))
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
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
        await db.executemany("INSERT INTO lab_mapa_polivalencia(operacion_a,operacion_b,polivalencia) VALUES(?,?,?) ON CONFLICT(operacion_a,operacion_b) DO UPDATE SET polivalencia=excluded.polivalencia,updated_at=CURRENT_TIMESTAMP", [(a,b,1 if (b in seleccionadas_b if data.get('modo') == 'matriz_completa' else data.get('polivalencia')) else 0) for a,b in cruces])
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
                # Tabla propia del piloto: Carga se evalúa por palets efectivos.
                carga = [(0, 0, 184), (1, 185, 204), (2, 205, 219),
                         (3, 220, 230), (4, 231, 240), (5, 241, 999999999)]
                carga_actual = [r for r in rows if str(r.get('operacion') or '').upper() == 'CARGA']
                importes_por_grupo = {}
                for actual in carga_actual:
                    grupo_actual = actual.get('grupo_productivo') or 'Sin grupo específico'
                    importes_por_grupo.setdefault(grupo_actual, {})[int(actual.get('nivel') or 0) - 1] = float(actual.get('premio') or 0)
                rows = [r for r in rows if str(r.get('operacion') or '').upper() != 'CARGA']
                rows.extend({'operacion': 'CARGA', 'grupo_productivo': grupo,
                             'nivel': nivel, 'desde': desde, 'hasta': hasta, 'premio': importes.get(nivel, 0),
                             'premio_por_unidad_excedente': 0, 'fecha_vigencia_desde': None,
                             'fecha_vigencia_hasta': None, 'tabla_propia': True,
                             'nota': 'Rango nuevo; importe tomado de nivel vigente equivalente'}
                            for grupo, importes in importes_por_grupo.items()
                            for nivel, desde, hasta in carga)
                traslados = [(0, 0, 19, 0), (1, 20, 27, 6633.41), (2, 28, 34, 10104.84),
                             (3, 35, 40, 15390.25), (4, 41, 46, 20769.50),
                             (5, 47, 51, 32903.96), (6, 52, 999999999, 51625.37)]
                grupos_todos = sorted({str(r.get('grupo_productivo') or '').strip() for r in rows if str(r.get('grupo_productivo') or '').strip()})
                rows.extend({'operacion': 'TRASLADOS', 'grupo_productivo': grupo,
                             'nivel': nivel, 'desde': desde, 'hasta': hasta, 'premio': premio,
                             'premio_por_unidad_excedente': 0, 'fecha_vigencia_desde': None,
                             'fecha_vigencia_hasta': None, 'tabla_propia': True}
                            for grupo in grupos_todos for nivel, desde, hasta, premio in traslados)
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
                    if key in overrides:
                        row.update(overrides[key]); row['editado'] = True
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
        premio = float(data['premio']); excedente = float(data.get('premio_por_unidad_excedente') or 0)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, 'Valores de escala inválidos.') from exc
    if not operacion or nivel < 0 or desde < 0 or hasta < desde or premio < 0 or excedente < 0:
        raise HTTPException(400, 'Operación, rango y premios deben ser válidos.')
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        await _ensure_config(db)
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
    grouped = f"""FROM lab_cache_agrupado WHERE {predicate}"""
    # La evaluación se hace sobre la fila agrupada, pero las reglas se leen
    # desde la configuración local del estudio. El cache operativo queda intacto.
    escala_catalogo = await escalas_premios(request)
    escalas = escala_catalogo.get("rows", [])
    async with aiosqlite.connect(LAB_CACHE_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"SELECT COUNT(*) AS total {grouped}", tuple(args)) as cur:
            total = int((await cur.fetchone())["total"] or 0)
        # Consolidar y evaluar siempre el conjunto completo antes de paginar.
        page_clause = ""
        page_args = tuple(args)
        async with db.execute(f"""SELECT fecha, legajo, desc_funcion, division, sector,
                palets, plus, cantidad, peso, detalle_filas {grouped}
                ORDER BY fecha, legajo, UPPER(TRIM(desc_funcion)){page_clause}""", page_args) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
        await _ensure_config(db)
        async with db.execute("""SELECT p.desc_funcion,p.medible,p.unidad_medida,
                p.grupo_premio,COALESCE(e.operacion_premio,'') AS operacion_premio
                FROM lab_funcion_parametro p LEFT JOIN lab_funcion_equivalencia e
                ON e.desc_funcion=p.desc_funcion""") as cur:
            parametros = {r["desc_funcion"]: dict(r) for r in await cur.fetchall()}
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

    for row in rows:
        p = parametros.get(row["desc_funcion"], {})
        unidad = str(p.get("unidad_medida") or "").upper()
        operacion = str(p.get("operacion_premio") or "").strip()
        if operacion.upper() == "TRASLADO":
            operacion = "TRASLADOS"
        grupo = str(p.get("grupo_premio") or "").strip()
        grupo_operativo = division_grupo.get(str(row.get("division") or "").strip(), "")
        grupo_escala = grupo or equivalencias.get(grupo_operativo.upper(), grupo_operativo)
        if operacion.upper() == "TRASLADOS" and not unidad:
            unidad = "PALET"
        unidades = {"PALET": row.get("palets"), "PLU": row.get("plus"),
                    "BULTO": row.get("cantidad")}.get(unidad)
        candidatos = [x for x in escalas if str(x.get("operacion") or "").strip().upper() == operacion.upper()
                      and (not grupo_escala or str(x.get("grupo_productivo") or "").strip().upper() == grupo_escala.upper())]
        tramo = next((x for x in candidatos if float(x.get("desde") or 0) <= float(unidades or 0)
                      <= float(x.get("hasta") or 0)), None) if unidades is not None else None
        if operacion.upper() not in {"CARGA", "TRASLADOS"}:
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
        if str(row.get("operacion_premio") or "").upper() not in {"CARGA", "TRASLADOS"}:
            continue
        op = str(row.get("operacion_premio") or "").upper()
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
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT snapshot FROM lab_pago_actual_meta ORDER BY capturado DESC LIMIT 1') as cur:
            meta = await cur.fetchone()
        if not meta:
            raise HTTPException(409, 'La cache de pagos actuales todavía no está preparada.')
        async with db.execute('''SELECT operacion,grupo,COUNT(*) AS tareas,
                SUM(pago_centavos) AS total_centavos
                FROM lab_pago_actual_operacion
                WHERE snapshot=? AND fecha>=? AND fecha<=?
                GROUP BY operacion,grupo ORDER BY operacion,grupo''',
                (meta['snapshot'], desde, hasta)) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        async with db.execute('''SELECT operacion_premio,grupo_productivo,
                COALESCE(SUM(premio_nuevo),0) AS simulado
                FROM lab_evaluacion_premio WHERE fecha>=? AND fecha<=?
                GROUP BY operacion_premio,grupo_productivo''', (desde, hasta)) as cur:
            simulated = {(str(r[0] or '').upper(), str(r[1] or '').upper()): dict(r)
                         for r in await cur.fetchall()}
    simulador_grupal = await calculo_grupal(request, fecha_desde, fecha_hasta)
    grupal_nuevo = {}
    for item in simulador_grupal.get('nivel_1', []):
        grupo = str(item.get('grupo_productivo') or '').strip()
        operacion = str(item.get('operacion') or '').strip().upper()
        if not grupo or not operacion:
            continue
        operacion = 'CARGA' if operacion == 'CARGA CAMION' else operacion
        grupal_nuevo[(operacion, grupo.upper())] = grupal_nuevo.get((operacion, grupo.upper()), 0) + int(round(float(item.get('premio_grupal_total') or 0) * 100))
    for row in rows:
        total = int(row.get('total_centavos') or 0)
        grupal_actual = round(total * 0.55)
        individual = round(total * 0.35)
        sim = simulated.get((str(row.get('operacion') or '').upper(), str(row.get('grupo') or '').upper()), {})
        individual_nuevo = int(round(float(sim.get('simulado') or 0) * 100))
        key = (str(row.get('operacion') or '').upper(), str(row.get('grupo') or '').upper())
        grupal_nuevo_centavos = grupal_nuevo.get(key, 0)
        polivalencia_nueva = 0
        total_nuevo = grupal_nuevo_centavos + individual_nuevo + polivalencia_nueva
        row.update({'total_centavos': total, 'grupal_centavos': grupal_actual,
                    'individual_centavos': individual,
                    'polivalencia_centavos': total - grupal_actual - individual,
                    'simulado_centavos': total_nuevo,
                    'grupal_nuevo_centavos': grupal_nuevo_centavos,
                    'individual_nuevo_centavos': individual_nuevo,
                    'polivalencia_nuevo_centavos': polivalencia_nueva,
                    'total_nuevo_centavos': total_nuevo,
                    'diferencia_centavos': total_nuevo - total})
    return {'snapshot': meta['snapshot'], 'rows': rows,
            'porcentajes': {'grupal': 55, 'individual': 35, 'polivalencia': 10},
            'nota': 'Total nuevo = grupal simulado + individual simulado + polivalencia nueva. El grupal se suma desde Cálculo grupal diario por operación y grupo productivo; no reemplaza la liquidación Oracle.',
            'grupal': {'filas': len(simulador_grupal.get('nivel_1', [])), 'grupos_con_premio': len(grupal_nuevo),
                       'total_centavos': sum(grupal_nuevo.values())}}


@router.get("/resumen-legajos")
async def resumen_legajos(request: Request, fecha_desde: str = '2026-08-01', fecha_hasta: str = '2026-08-31'):
    """Consolida por legajo pago actual, individual, polivalencia y grupal."""
    await _admin(request)
    desde = datetime.strptime(fecha_desde, '%Y-%m-%d').strftime('%Y%m%d')
    hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').strftime('%Y%m%d')
    grupal = await calculo_grupal(request, fecha_desde, fecha_hasta)
    por_legajo = {}
    for item in grupal.get('nivel_3', []):
        l = str(item.get('legajo') or '').strip()
        if not l: continue
        x = por_legajo.setdefault(l, {'legajo': l, 'nombre': item.get('nombre',''), 'sector': item.get('sector',''), 'funcion': item.get('funcion_legajero',''), 'turno_madre': item.get('turno_fijo',''), 'grupal_nuevo_centavos': 0})
        x['grupal_nuevo_centavos'] += int(round(float(item.get('premio_grupal') or 0) * 100))
    async with aiosqlite.connect(LAB_CACHE_DB_PATH.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT legajo,COALESCE(SUM(pago_centavos),0) actual FROM lab_pago_actual_operacion WHERE fecha>=? AND fecha<=? GROUP BY legajo',(desde,hasta)) as cur:
            actual = {str(r['legajo']): int(r['actual'] or 0) for r in await cur.fetchall()}
        async with db.execute('SELECT legajo,COALESCE(SUM(premio_nuevo),0) individual FROM lab_evaluacion_premio WHERE fecha>=? AND fecha<=? GROUP BY legajo',(desde,hasta)) as cur:
            individual = {str(r['legajo']): int(round(float(r['individual'] or 0)*100)) for r in await cur.fetchall()}
    # El universo queda restringido a legajos que pertenecen a una combinación
    # sector/función/turno con parámetro grupal activo (nivel_3).
    rows=[]
    for x in por_legajo.values():
        x['pago_actual_centavos']=actual.get(x['legajo'],0); x['individual_nuevo_centavos']=individual.get(x['legajo'],0); x['polivalencia_nuevo_centavos']=0
        x['total_nuevo_centavos']=x.get('grupal_nuevo_centavos',0)+x['individual_nuevo_centavos']; x['diferencia_centavos']=x['total_nuevo_centavos']-x['pago_actual_centavos']; rows.append(x)
    rows.sort(key=lambda x:x['legajo'])
    return {'rows':rows,'snapshot':None,'nota':'La nómina grupal proviene del cálculo diario; polivalencia queda separada para su asignación específica.'}


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
        async with db.execute(f"SELECT COUNT(*) AS total FROM lab_etapa_detalle_raw WHERE {predicate}", tuple(args)) as cur:
            total = int((await cur.fetchone())["total"] or 0)
        async with db.execute(
            f"""SELECT row_id, fecha, legajo, id_etapa, fyhini, fyhfin, cod_funcion,
                       desc_funcion, division, sector, pallet, plu, cantidad, peso
                FROM lab_etapa_detalle_raw WHERE {predicate}
                ORDER BY fecha, legajo, fyhini, id_etapa, row_id LIMIT ? OFFSET ?""",
            tuple(args + [limit, offset]),
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    return {
        "filters": {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta, "legajo": legajo.strip(), "desc_funcion": desc_funcion.strip()},
        "total": total, "limit": limit, "offset": offset,
        "has_more": offset + len(rows) < total, "rows": rows,
        "source": {"db": str(LAB_CACHE_DB_PATH), "run_prefix": LAB_CACHE_RUN_PREFIX},
    }
