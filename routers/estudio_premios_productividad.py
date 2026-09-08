from __future__ import annotations

from datetime import datetime
from collections import Counter
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


async def _ensure_config(db):
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

    # Piloto solicitado: Carga. Las demás funciones se muestran agrupadas,
    # pero todavía no se les asigna un importe nuevo.
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
    for row in rows:
        total = int(row.get('total_centavos') or 0)
        grupal = round(total * 0.55)
        individual = round(total * 0.35)
        sim = simulated.get((str(row.get('operacion') or '').upper(), str(row.get('grupo') or '').upper()), {})
        nuevo = int(round(float(sim.get('simulado') or 0) * 100))
        row.update({'total_centavos': total, 'grupal_centavos': grupal,
                    'individual_centavos': individual,
                    'polivalencia_centavos': total - grupal - individual,
                    'simulado_centavos': nuevo,
                    'grupal_nuevo_centavos': 0,
                    'individual_nuevo_centavos': nuevo,
                    'polivalencia_nuevo_centavos': 0})
    return {'snapshot': meta['snapshot'], 'rows': rows,
            'porcentajes': {'grupal': 55, 'individual': 35, 'polivalencia': 10},
            'nota': 'Distribución teórica del pago real por tarea; no reemplaza la liquidación Oracle.'}


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
