"""Carga manual y reanudable del estudio. Oracle sólo SELECT; sin scheduler."""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env', override=True)
from routers.analisis_premio_productividad import _query_oracle

MASTERS = ['PV_ESCALA_DE_PREMIOS', 'PV_FUNCION', 'PV_GRUPO_DE_FUNCIONES_CAB',
           'PV_GRUPO_DE_FUNCIONES_DET', 'PV_GRUPO_PRODUCTIVO_CAB', 'PV_GRUPO_PRODUCTIVO_DET']
LOCAL = ['pp_premio_foto_meta', 'pp_premio_foto_escala', 'pp_premio_foto_sector', 'pp_premio_sector_escala_hora']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--payments', action='store_true')
    args = parser.parse_args()
    dest = ROOT / 'datos/laboratorio_premios.db'
    if not dest.exists():
        raise RuntimeError('No existe la base de estudio.')
    with sqlite3.connect(dest, timeout=30) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS lab_fuente_lote (
          snapshot TEXT, fuente TEXT, segmento TEXT, capturado TEXT, filas INTEGER,
          sha256 TEXT, consulta TEXT, PRIMARY KEY(snapshot,fuente,segmento));
        CREATE TABLE IF NOT EXISTS lab_fuente_registro (
          snapshot TEXT, fuente TEXT, segmento TEXT, ordinal INTEGER, payload TEXT,
          PRIMARY KEY(snapshot,fuente,segmento,ordinal));
        ''')
        def save(source, segment, query, fetch):
            key = (args.snapshot, source, segment)
            if db.execute('SELECT 1 FROM lab_fuente_lote WHERE snapshot=? AND fuente=? AND segmento=?', key).fetchone():
                print(source, segment, 'YA CARGADO', flush=True)
                return
            rows = fetch()
            payloads = [json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows]
            digest = hashlib.sha256('\n'.join(payloads).encode('utf-8')).hexdigest()
            with db:
                db.executemany('INSERT INTO lab_fuente_registro VALUES(?,?,?,?,?)',
                               [(*key, i, p) for i, p in enumerate(payloads)])
                db.execute('INSERT INTO lab_fuente_lote VALUES(?,?,?,?,?,?,?)',
                           (*key, datetime.now().isoformat(), len(rows), digest, query))
            print(source, segment, len(rows), 'OK', flush=True)
        source = ROOT / 'datos/premio_productividad.db'
        with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as old:
            old.row_factory = sqlite3.Row
            old.execute('BEGIN')
            for table in LOCAL:
                query = 'SELECT * FROM ' + table
                save('local.'+table, 'snapshot', query,
                     lambda q=query: [dict(r) for r in old.execute(q)])
        for table in MASTERS:
            query = 'SELECT * FROM ' + table
            save('oracle.'+table, 'snapshot', query, lambda q=query: _query_oracle(q, {}))
        if args.payments:
            day = date(2026, 8, 1)
            while day < date(2026, 9, 1):
                segment = day.strftime('%Y%m%d')
                for table in ['PV_DIA_LABORAL', 'PV_LIQUIDAC_DIA_DET1', 'PV_LIQUIDAC_DIA_DET2']:
                    query = ('SELECT C.* FROM PV_DIA_LABORAL C WHERE C.FECHA=:fecha' if table == 'PV_DIA_LABORAL'
                             else f'SELECT B.* FROM {table} B JOIN PV_DIA_LABORAL C ON C.ID=B.ID_PV_DIA_LABORAL WHERE C.FECHA=:fecha')
                    save('oracle.'+table, segment, query,
                         lambda q=query, d=segment: _query_oracle(q, {'fecha': int(d)}))
                day += timedelta(days=1)

if __name__ == '__main__':
    main()
