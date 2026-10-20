
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'datos' / 'laboratorio_premios.db'
RUN_PREFIX = 'ETAPA_AGOSTO_2026_SIN_FILTRO_ID_R1_%'
ORIGEN = 'pago_actual_sin_wms'


def norm(value: object) -> str:
    return str(value or '').strip().upper()


def operacion_reconstruida(operacion: str) -> str:
    op = norm(operacion)
    if op == 'PICKING':
        return 'ARMADO'
    if op == 'CLARK':
        return 'CLARK'
    # Recepción queda auditada pero no se reconstruye desde pago actual: en
    # esas tablas la producción puede venir expresada como valor monetario o
    # índice de pago y no como palets físicos.
    # Carga y carreteo se dejan sólo en auditoría. PALETS OPERADOS se
    # construye desde etapas/pallet físico para evitar sumar dos veces una
    # misma contribución reconstruida desde el pago actual.
    return ''


def funcion_wms_reconstruida(operacion_rec: str) -> str:
    # El cálculo grupal compara contra componentes WMS. Estos nombres son
    # equivalentes medibles y permiten diferenciar el origen auditado sin
    # modificar el cache crudo.
    if operacion_rec == 'ARMADO':
        return 'PICKIN'
    if operacion_rec == 'CLARK':
        return 'GUARDAD'
    return operacion_rec


def division_reconstruida(sector: str, grupo: str, funcion: str) -> str:
    sector_n = norm(sector)
    grupo_n = norm(grupo)
    funcion_n = norm(funcion)
    if 'CAMARA 06' in grupo_n or 'T06' in funcion_n or 'CONGEL' in funcion_n:
        return '4'
    if 'OTRAS CAMARAS' in grupo_n or 'REFRIG' in sector_n or 'REFRIG' in grupo_n:
        return '2'
    if 'NOA' in sector_n or grupo_n == 'NOA':
        return '6'
    return '1'


def unidades_para_ajuste(operacion_rec: str, unidad: str, produccion: float) -> tuple[float, float, float]:
    unidad_n = norm(unidad)
    if operacion_rec in {'CLARK', 'RECEPCION'}:
        return produccion, 0.0, 0.0
    if operacion_rec == 'ARMADO':
        return 0.0, 0.0, produccion
    if 'PALLET' in unidad_n or 'PALET' in unidad_n:
        return produccion, 0.0, 0.0
    if 'PLU' in unidad_n or 'HUECO' in unidad_n:
        return 0.0, produccion, 0.0
    if 'BULTO' in unidad_n:
        return 0.0, 0.0, produccion
    return 0.0, 0.0, 0.0


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=30000')
    con.executescript("""
    CREATE TABLE IF NOT EXISTS lab_auditoria_pago_sin_wms(
        fecha TEXT NOT NULL, legajo TEXT NOT NULL, operacion_actual TEXT NOT NULL,
        grupo_actual TEXT NOT NULL DEFAULT '', unidad_actual TEXT NOT NULL DEFAULT '',
        produccion_actual REAL NOT NULL DEFAULT 0, tiempo_actual TEXT NOT NULL DEFAULT '',
        pago_centavos INTEGER NOT NULL DEFAULT 0, sector_legajero TEXT NOT NULL DEFAULT '',
        funcion_legajero TEXT NOT NULL DEFAULT '', turno_madre TEXT NOT NULL DEFAULT '',
        operacion_reconstruida TEXT NOT NULL DEFAULT '', division_reconstruida TEXT NOT NULL DEFAULT '',
        motivo TEXT NOT NULL DEFAULT '', snapshot TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(fecha,legajo,operacion_actual,grupo_actual,unidad_actual,snapshot));
    CREATE TABLE IF NOT EXISTS lab_cache_agrupado_ajuste(
        fecha TEXT NOT NULL, legajo TEXT NOT NULL, desc_funcion TEXT NOT NULL,
        division TEXT NOT NULL DEFAULT '', sector TEXT NOT NULL DEFAULT '',
        palets REAL NOT NULL DEFAULT 0, plus REAL NOT NULL DEFAULT 0,
        cantidad REAL NOT NULL DEFAULT 0, peso REAL NOT NULL DEFAULT 0,
        detalle_filas INTEGER NOT NULL DEFAULT 1, origen TEXT NOT NULL DEFAULT 'pago_actual_sin_wms',
        snapshot TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(fecha,legajo,desc_funcion,division,sector,origen,snapshot));
    CREATE INDEX IF NOT EXISTS idx_lab_cache_agrupado_ajuste_fecha_legajo ON lab_cache_agrupado_ajuste(fecha,legajo);
    """)
    snapshot_row = con.execute("SELECT snapshot FROM lab_pago_actual_operacion GROUP BY snapshot ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    if not snapshot_row:
        raise SystemExit('No hay snapshot de pago actual para auditar.')
    snapshot = snapshot_row['snapshot']
    con.execute('DELETE FROM lab_auditoria_pago_sin_wms WHERE snapshot=?', (snapshot,))
    con.execute('DELETE FROM lab_cache_agrupado_ajuste WHERE snapshot=? AND origen=?', (snapshot, ORIGEN))

    rows = con.execute("""
    WITH paid AS (
        SELECT fecha,legajo,TRIM(COALESCE(operacion,'')) operacion,TRIM(COALESCE(grupo,'')) grupo,
               TRIM(COALESCE(unidad,'')) unidad,SUM(COALESCE(produccion,0)) produccion,
               MAX(TRIM(COALESCE(tiempo,''))) tiempo,SUM(COALESCE(pago_centavos,0)) pago_centavos
        FROM lab_pago_actual_operacion
        WHERE snapshot=? AND COALESCE(pago_centavos,0)>0
        GROUP BY fecha,legajo,operacion,grupo,unidad
    ), raw AS (
        SELECT DISTINCT fecha,legajo FROM lab_etapa_detalle_raw WHERE run_id LIKE ?
    ), perfil AS (
        SELECT fecha,legajo,MAX(TRIM(COALESCE(sector,''))) sector,
               MAX(TRIM(COALESCE(funcion_legajero,''))) funcion_legajero,
               MAX(TRIM(COALESCE(turno,''))) turno
        FROM lab_cache_grupal
        GROUP BY fecha,legajo
    )
    SELECT p.*, COALESCE(perfil.sector,'') sector_legajero,
           COALESCE(perfil.funcion_legajero,'') funcion_legajero,
           COALESCE(perfil.turno,'') turno_madre
    FROM paid p
    LEFT JOIN raw r ON r.fecha=p.fecha AND r.legajo=p.legajo
    LEFT JOIN perfil ON perfil.fecha=p.fecha AND perfil.legajo=p.legajo
    WHERE r.legajo IS NULL
    ORDER BY p.fecha,p.legajo,p.operacion
    """, (snapshot, RUN_PREFIX)).fetchall()

    audit_rows = []
    ajuste_rows = []
    now = datetime.now().isoformat(timespec='seconds')
    for row in rows:
        oper_rec = operacion_reconstruida(row['operacion'])
        division = division_reconstruida(row['sector_legajero'], row['grupo'], row['funcion_legajero']) if oper_rec else ''
        motivo = 'sin_filas_wms_en_cache_raw'
        if not oper_rec:
            motivo += '|sin_mapeo_medible_seguro'
        elif float(row['produccion'] or 0) <= 0:
            motivo += '|sin_produccion_actual_reconstruible'
        audit_rows.append((row['fecha'], row['legajo'], row['operacion'], row['grupo'], row['unidad'], row['produccion'],
                           row['tiempo'], int(row['pago_centavos'] or 0), row['sector_legajero'], row['funcion_legajero'],
                           row['turno_madre'], oper_rec, division, motivo, snapshot, now))
        if oper_rec and float(row['produccion'] or 0) > 0:
            palets, plus, cantidad = unidades_para_ajuste(oper_rec, row['unidad'], float(row['produccion'] or 0))
            if palets or plus or cantidad:
                ajuste_rows.append((row['fecha'], row['legajo'], funcion_wms_reconstruida(oper_rec), division, 'AJUSTE PAGO ACTUAL SIN WMS',
                                    palets, plus, cantidad, 0.0, 1, ORIGEN, snapshot, now))
    con.executemany("""
        INSERT OR REPLACE INTO lab_auditoria_pago_sin_wms
        (fecha,legajo,operacion_actual,grupo_actual,unidad_actual,produccion_actual,tiempo_actual,pago_centavos,
         sector_legajero,funcion_legajero,turno_madre,operacion_reconstruida,division_reconstruida,motivo,snapshot,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, audit_rows)
    con.executemany("""
        INSERT OR REPLACE INTO lab_cache_agrupado_ajuste
        (fecha,legajo,desc_funcion,division,sector,palets,plus,cantidad,peso,detalle_filas,origen,snapshot,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, ajuste_rows)
    con.commit()

    print(f'snapshot={snapshot}')
    print(f'auditados={len(audit_rows)}')
    print(f'ajustes_medibles={len(ajuste_rows)}')
    for row in con.execute("""SELECT desc_funcion,division,COUNT(*) filas,COUNT(DISTINCT fecha||'-'||legajo) legajo_dias,
                                     ROUND(SUM(palets),2) palets,ROUND(SUM(plus),2) plus,ROUND(SUM(cantidad),2) cantidad
                              FROM lab_cache_agrupado_ajuste WHERE snapshot=? AND origen=?
                              GROUP BY desc_funcion,division ORDER BY desc_funcion,division""", (snapshot, ORIGEN)):
        print(dict(row))

if __name__ == '__main__':
    main()
