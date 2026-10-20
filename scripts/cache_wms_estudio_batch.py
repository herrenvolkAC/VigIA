"""Extrae WMS por día, confirma cada lote localmente y permite reanudarlo."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / '.env', override=True)
from routers.analisis_premio_productividad import _query_oracle

DB = ROOT / 'datos' / 'laboratorio_premios.db'
RUN_PREFIX = 'ETAPA_AGOSTO_2026_SIN_FILTRO_ID_R1_'

QUERY = '''
SELECT D.FECHA, D.ID AS ID_DIA_LABORAL, A.LEGAJO, A.ID AS ID_ETAPA,
       A.FYHINI, A.FYHFIN, A.COD_FUNCION, A.DESC_FUNCION,
       A.DIVISION, A.SECTOR, B.CNUPALET AS PALLET, B.CREFEREN AS PLU,
       NVL(B.QCANTIDA,0) AS CANTIDAD, NVL(B.QPESOREG,0) AS PESO, B.ID AS ID_DETALLE
FROM PV_DIA_LABORAL D
JOIN PV_ETAPA_CAB A ON A.ID_PV_DIA_LABORAL=D.ID
LEFT JOIN PV_ETAPA_DET B ON B.ID_ETAPA_CAB=A.ID AND B.ID_PV_DIA_LABORAL=A.ID_PV_DIA_LABORAL
WHERE D.FECHA=:fecha
ORDER BY A.ID,B.ID'''


def text(value: object) -> str:
    return '' if value is None else str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desde', required=True)
    parser.add_argument('--hasta', required=True)
    parser.add_argument('--pausa-segundos', type=float, default=1.0)
    parser.add_argument('--forzar', action='store_true',
                        help='Vuelve a extraer días ya confirmados.')
    args = parser.parse_args()
    inicio = datetime.strptime(args.desde, '%Y-%m-%d').date()
    fin = datetime.strptime(args.hasta, '%Y-%m-%d').date()
    if fin < inicio:
        raise SystemExit('--hasta no puede ser anterior a --desde.')
    with sqlite3.connect(DB, timeout=120) as db:
        db.execute('PRAGMA busy_timeout=120000')
        db.execute('''CREATE TABLE IF NOT EXISTS lab_cache_wms_batch(
            fecha TEXT PRIMARY KEY, run_id TEXT NOT NULL, estado TEXT NOT NULL,
            filas INTEGER NOT NULL DEFAULT 0, legajos INTEGER NOT NULL DEFAULT 0,
            iniciado_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finalizado_at TEXT, error TEXT NOT NULL DEFAULT '')''')
    day = inicio
    while day <= fin:
        fecha = day.strftime('%Y%m%d')
        run_id = RUN_PREFIX + fecha
        with sqlite3.connect(DB, timeout=30) as db:
            estado = db.execute('SELECT estado FROM lab_cache_wms_batch WHERE fecha=?', (fecha,)).fetchone()
        if estado and estado[0] == 'OK' and not args.forzar:
            print(fecha, 'YA_CONFIRMADO', flush=True)
            day += timedelta(days=1)
            continue
        print(fecha, 'CONSULTANDO_ORACLE', flush=True)
        try:
            source = _query_oracle(QUERY, {'fecha': int(fecha)})
            now = datetime.now().isoformat(timespec='seconds')
            rows = []
            for ordinal, item in enumerate(source, start=1):
                payload = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                row_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
                rows.append((run_id, ordinal, row_hash, text(item.get('FECHA')), text(item.get('ID_DIA_LABORAL')),
                             text(item.get('LEGAJO')), text(item.get('ID_ETAPA')), text(item.get('FYHINI')),
                             text(item.get('FYHFIN')), text(item.get('COD_FUNCION')), text(item.get('DESC_FUNCION')),
                             text(item.get('DIVISION')), text(item.get('SECTOR')), text(item.get('PALLET')),
                             text(item.get('PLU')), float(item.get('CANTIDAD') or 0), float(item.get('PESO') or 0), payload))
            legajos = len({row[5] for row in rows if row[5]})
            with sqlite3.connect(DB, timeout=120) as db:
                db.execute('PRAGMA busy_timeout=120000')
                with db:
                    db.execute('''INSERT INTO lab_cache_wms_batch(fecha,run_id,estado,filas,legajos,iniciado_at,finalizado_at,error)
                                  VALUES(?,?, 'EN_PROCESO',0,0,?,'','')
                                  ON CONFLICT(fecha) DO UPDATE SET run_id=excluded.run_id,estado='EN_PROCESO',
                                  iniciado_at=excluded.iniciado_at,finalizado_at='',error='' ''', (fecha, run_id, now))
                    db.execute('DELETE FROM lab_etapa_detalle_raw WHERE run_id=?', (run_id,))
                    db.executemany('''INSERT INTO lab_etapa_detalle_raw
                        (run_id,source_row_num,row_hash,fecha,id_dia_laboral,legajo,id_etapa,fyhini,fyhfin,
                         cod_funcion,desc_funcion,division,sector,pallet,plu,cantidad,peso,raw_json)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', rows)
                    db.execute('DELETE FROM lab_cache_agrupado WHERE fecha=?', (fecha,))
                    db.execute('''INSERT INTO lab_cache_agrupado
                        (fecha,legajo,desc_funcion,division,sector,palets,plus,cantidad,peso,detalle_filas)
                        SELECT fecha,legajo,desc_funcion,division,sector,
                               COUNT(DISTINCT pallet),COUNT(DISTINCT plu),SUM(COALESCE(cantidad,0)),
                               SUM(COALESCE(peso,0)),COUNT(*)
                        FROM lab_etapa_detalle_raw WHERE run_id=?
                        GROUP BY fecha,legajo,desc_funcion,division,sector''', (run_id,))
                    db.execute('''UPDATE lab_cache_wms_batch SET estado='OK',filas=?,legajos=?,finalizado_at=?,error=''
                                  WHERE fecha=?''', (len(rows), legajos, datetime.now().isoformat(timespec='seconds'), fecha))
            print(fecha, f'OK filas={len(rows)} legajos={legajos}', flush=True)
        except Exception as exc:
            with sqlite3.connect(DB, timeout=30) as db:
                db.execute('''INSERT INTO lab_cache_wms_batch(fecha,run_id,estado,error)
                              VALUES(?,?, 'ERROR',?) ON CONFLICT(fecha) DO UPDATE SET estado='ERROR',error=excluded.error,
                              finalizado_at=?''', (fecha, run_id, str(exc)[:2000], datetime.now().isoformat(timespec='seconds')))
                db.commit()
            raise
        if args.pausa_segundos > 0:
            time.sleep(args.pausa_segundos)
        day += timedelta(days=1)


if __name__ == '__main__':
    main()
