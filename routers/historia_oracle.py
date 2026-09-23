"""Historia individual: lecturas Oracle PV, sin persistencia ni fallback local."""
import asyncio
import logging
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, Response
from routers.analisis_premio_productividad import _query_oracle_via_jdbc

router = APIRouter(prefix="/api/historia-legajo/oracle", tags=["historia-oracle"])
logger = logging.getLogger(__name__)
_slots = asyncio.Semaphore(3)


async def query(sql, binds):
    async with _slots:
        try:
            return await asyncio.to_thread(_query_oracle_via_jdbc, sql, binds)
        except Exception:
            logger.exception("Consulta de historia Oracle fallida")
            raise HTTPException(503, "No se pudo consultar el sistema de datos. Reintentá con un período menor.")


def period(desde, hasta):
    if hasta < desde or (hasta-desde).days > 366:
        raise HTTPException(422, "Seleccioná un período ordenado de hasta 367 días.")
    return {"desde": int(desde.strftime('%Y%m%d')), "hasta": int(hasta.strftime('%Y%m%d'))}


DAY_FILTER = "D.LEGAJO=:legajo AND D.FECHA BETWEEN :desde AND :hasta"


@router.get('/buscar')
async def buscar(response: Response, q: str = Query(..., min_length=2, max_length=70)):
    response.headers['Cache-Control'] = 'no-store'
    term = q.strip().upper().replace('%', '').replace('_', '')
    if len(term) < 2:
        raise HTTPException(422, 'Ingresá al menos dos caracteres.')
    rows = await query("""SELECT * FROM (SELECT LEGAJO,NOMBRE,DESC_FUNCION,DESC_POSICION,EMPLEADOR
        FROM PV_LEGAJO WHERE LEGAJO=:exacto OR UPPER(NOMBRE) LIKE :nombre
        OR LEGAJO LIKE :prefijo ORDER BY CASE WHEN LEGAJO=:exacto THEN 0 ELSE 1 END,NOMBRE)
        WHERE ROWNUM<=25""", {'exacto': term, 'nombre': '%'+term+'%', 'prefijo': term+'%'})
    return {'rows': rows}


@router.get('/resumen')
async def resumen(response: Response, legajo: str = Query(..., pattern=r'^\d{1,12}$'),
                  desde: date = Query(...), hasta: date = Query(...)):
    response.headers['Cache-Control'] = 'no-store'
    binds = dict(period(desde, hasta), legajo=legajo)
    # Independent result sets preserve each table's grain: never join DET1 to DET2.
    persona = await query('SELECT LEGAJO,NOMBRE,DESC_FUNCION,DESC_POSICION,EMPLEADOR FROM PV_LEGAJO WHERE LEGAJO=:legajo', {'legajo': legajo})
    dias = await query(f'SELECT D.* FROM PV_DIA_LABORAL D WHERE {DAY_FILTER} ORDER BY D.FECHA,D.ID', binds)
    detalle_sql = lambda table: f'''SELECT D.FECHA,D.TURNO,B.*,G.DESCRIPCION OPERACION,
        P.DESCRIPCION GRUPO_PRODUCTIVO FROM PV_DIA_LABORAL D
        JOIN {table} B ON B.ID_PV_DIA_LABORAL=D.ID
        LEFT JOIN PV_GRUPO_DE_FUNCIONES_CAB G ON G.ID=B.ID_PV_GRUPO_DE_FUNCIONES
        LEFT JOIN PV_GRUPO_PRODUCTIVO_CAB P ON P.ID=B.ID_PV_GRUPO_PRODUCTIVO
        WHERE {DAY_FILTER} ORDER BY D.FECHA,B.ID'''
    pagos, produccion = await asyncio.gather(
        query(detalle_sql('PV_LIQUIDAC_DIA_DET1'), binds),
        query(detalle_sql('PV_LIQUIDAC_DIA_DET2'), binds))
    escalas = await query(f'''SELECT E.* FROM PV_ESCALA_DE_PREMIOS E WHERE EXISTS (
        SELECT 1 FROM PV_DIA_LABORAL D JOIN PV_LIQUIDAC_DIA_DET1 B ON B.ID_PV_DIA_LABORAL=D.ID
        WHERE {DAY_FILTER} AND B.ID_PV_GRUPO_DE_FUNCIONES=E.ID_DE_GRUPO_DE_FUNCIONES
        AND NVL(B.ID_PV_GRUPO_PRODUCTIVO,0)=NVL(E.ID_DE_GRUPO_PRODUCTIVO,0))
        ORDER BY E.ID_DE_GRUPO_DE_FUNCIONES,E.NIVEL,E.FECHA_VIGENCIA_DESDE''', binds)
    return {'persona': persona[0] if persona else {'LEGAJO': legajo, 'NOMBRE': 'Legajo histórico'},
            'dias': dias, 'pagos': pagos, 'produccion': produccion, 'escalas': escalas,
            'desde': str(desde), 'hasta': str(hasta), 'fuente': 'Sistema de productividad',
            'consultado': datetime.now().isoformat(timespec='seconds')}


@router.get('/dia')
async def dia(response: Response, legajo: str = Query(..., pattern=r'^\d{1,12}$'), fecha: date = Query(...)):
    response.headers['Cache-Control'] = 'no-store'
    binds = dict(period(fecha, fecha), legajo=legajo)
    etapas, cortes = await asyncio.gather(
        query(f'''SELECT A.* FROM PV_DIA_LABORAL D JOIN PV_ETAPA_CAB A ON A.ID_PV_DIA_LABORAL=D.ID
              WHERE {DAY_FILTER} ORDER BY A.FYHINI,A.ID''', binds),
        query(f'''SELECT B.* FROM PV_DIA_LABORAL D JOIN PV_LIQUIDAC_DIA_DET3 B ON B.ID_PV_DIA_LABORAL=D.ID
              WHERE {DAY_FILTER} ORDER BY B.ID''', binds))
    return {'etapas': etapas, 'cortes': cortes}


@router.get('/movimientos')
async def movimientos(response: Response, legajo: str = Query(..., pattern=r'^\d{1,12}$'),
                      etapa: int = Query(..., gt=0), offset: int = Query(0, ge=0, le=100000)):
    response.headers['Cache-Control'] = 'no-store'
    rows = await query('''SELECT * FROM (SELECT X.*,ROW_NUMBER() OVER (ORDER BY X.ID) RN
        FROM PV_ETAPA_DET X JOIN PV_ETAPA_CAB A ON A.ID=X.ID_ETAPA_CAB
        WHERE A.ID=:etapa AND A.LEGAJO=:legajo) WHERE RN>:inicio AND RN<=:fin ORDER BY RN''',
        {'etapa': etapa, 'legajo': legajo, 'inicio': offset, 'fin': offset+101})
    return {'rows': rows[:100], 'has_more': len(rows)>100}
