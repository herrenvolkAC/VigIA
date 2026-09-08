"""Materializa pagos Oracle ya capturados. Manual, local, idempotente por snapshot."""
import argparse
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def build(path, snapshot):
    db = sqlite3.connect(path, timeout=60)
    try:
        db.execute('BEGIN IMMEDIATE')
        def source(name):
            return [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM lab_fuente_registro WHERE snapshot=? AND fuente=?', (snapshot, name))]
        days = source('oracle.PV_DIA_LABORAL')
        payments = source('oracle.PV_LIQUIDAC_DIA_DET1')
        if not days or not payments:
            raise ValueError('Snapshot sin jornadas o liquidaciones completas')
        for name, records in [('oracle.PV_DIA_LABORAL', days), ('oracle.PV_LIQUIDAC_DIA_DET1', payments)]:
            expected = db.execute('SELECT SUM(filas) FROM lab_fuente_lote WHERE snapshot=? AND fuente=?', (snapshot, name)).fetchone()[0]
            if expected != len(records) or len({r['ID'] for r in records}) != len(records):
                raise ValueError('Filas faltantes o IDs duplicados: ' + name)
        headers = {str(r['ID']): r for r in days}
        groups = {str(r['ID']): r['DESCRIPCION'] for r in source('oracle.PV_GRUPO_DE_FUNCIONES_CAB')}
        productive = {str(r['ID']): r['DESCRIPCION'] for r in source('oracle.PV_GRUPO_PRODUCTIVO_CAB')}
        for sql in [
            '''CREATE TABLE IF NOT EXISTS lab_pago_actual_meta(
                snapshot TEXT PRIMARY KEY, capturado TEXT, generado TEXT DEFAULT CURRENT_TIMESTAMP, reporte TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS lab_pago_actual_dia(
                snapshot TEXT, fecha TEXT, legajo TEXT, jornadas INTEGER, pago_centavos INTEGER,
                detalle_centavos INTEGER, diferencia_centavos INTEGER, faltantes INTEGER,
                PRIMARY KEY(snapshot,fecha,legajo))''',
            '''CREATE TABLE IF NOT EXISTS lab_pago_actual_operacion(
                snapshot TEXT, id TEXT, id_dia TEXT, fecha TEXT, legajo TEXT, operacion TEXT,
                grupo TEXT, unidad TEXT, nivel REAL, produccion REAL, tiempo TEXT,
                proporcion REAL, excedente REAL, penalizacion_tnc REAL, penalizacion_error REAL,
                pago_centavos INTEGER, pago_original TEXT, PRIMARY KEY(snapshot,id))''',
            'CREATE INDEX IF NOT EXISTS idx_lab_pago_actual_fecha ON lab_pago_actual_dia(snapshot,fecha,legajo)',
            'CREATE INDEX IF NOT EXISTS idx_lab_pago_actual_det ON lab_pago_actual_operacion(snapshot,fecha,legajo)',
        ]:
            db.execute(sql)
        # Sólo reemplaza esta derivación; los JSON fuente y otros snapshots permanecen.
        for table in ['lab_pago_actual_dia', 'lab_pago_actual_operacion', 'lab_pago_actual_meta']:
            db.execute(f'DELETE FROM {table} WHERE snapshot=?', (snapshot,))
        grouped = defaultdict(lambda: {'cab': Decimal(0), 'det': 0, 'jornadas': 0, 'faltantes': 0})
        for r in days:
            if not r.get('FECHA') or not r.get('LEGAJO'):
                raise ValueError('Jornada sin fecha o legajo')
            x = grouped[(str(r['FECHA']), str(r['LEGAJO']).strip())]
            x['jornadas'] += 1
            if r.get('PREMIO') is None:
                x['faltantes'] += 1
            else:
                x['cab'] += Decimal(str(r['PREMIO']))
        details = []
        for r in payments:
            header = headers.get(str(r['ID_PV_DIA_LABORAL']))
            if header is None:
                raise ValueError('Liquidación sin jornada: ' + str(r['ID']))
            key = (str(header['FECHA']), str(header['LEGAJO']).strip())
            value = r.get('A_PAGAR_TOTAL')
            amount = None if value is None else cents(value)
            grouped[key]['det'] += amount or 0
            if amount is None:
                grouped[key]['faltantes'] += 1
            details.append((snapshot, str(r['ID']), str(header['ID']), *key,
                groups.get(str(r.get('ID_PV_GRUPO_DE_FUNCIONES')), 'Grupo ' + str(r.get('ID_PV_GRUPO_DE_FUNCIONES'))),
                productive.get(str(r.get('ID_PV_GRUPO_PRODUCTIVO')), 'Sin grupo específico'),
                r.get('ID_PV_UNIDAD_DE_PRODUCCION'), r.get('OBJETIVO_NIVEL_ALCANZADO'),
                r.get('PRODUCCION_TOTAL'), r.get('TIEMPO_TOTAL_HHMMSS'),
                r.get('A_PAGAR_EN_PROPORC_AL_TIEMPO'), r.get('A_PAGAR_POR_EXCEDENTE'),
                r.get('PENALIZACION_EXCESO_TNC'), r.get('PENALIZACION_POR_ERROR'), amount,
                None if value is None else str(value)))
        daily = [(snapshot, f, l, x['jornadas'], None if x['faltantes'] else cents(x['cab']),
                  x['det'], None if x['faltantes'] else cents(x['cab'])-x['det'], x['faltantes'])
                 for (f,l),x in grouped.items()]
        db.executemany('INSERT INTO lab_pago_actual_dia VALUES(?,?,?,?,?,?,?,?)', daily)
        db.executemany('INSERT INTO lab_pago_actual_operacion VALUES('+','.join('?' for _ in range(17))+')', details)
        captured = db.execute('SELECT MAX(capturado) FROM lab_fuente_lote WHERE snapshot=?', (snapshot,)).fetchone()[0]
        report = {'snapshot':snapshot, 'jornadas':len(days), 'dias_legajo':len(daily), 'operaciones':len(details),
                  'legajos':len({r[2] for r in daily}), 'pago_centavos':sum(r[4] or 0 for r in daily),
                  'detalle_centavos':sum(r[5] for r in daily),
                  'dias_por_conciliar':sum(abs(r[6] or 0)>1 for r in daily),
                  'fecha_desde':min(r[1] for r in daily), 'fecha_hasta':max(r[1] for r in daily)}
        assert sum(r[15] or 0 for r in details) == report['detalle_centavos']
        db.execute('INSERT INTO lab_pago_actual_meta(snapshot,capturado,reporte) VALUES(?,?,?)', (snapshot,captured,json.dumps(report)))
        db.commit()
        return report
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', default='estudio_20260907')
    parser.add_argument('--db', type=Path, default=ROOT/'datos/laboratorio_premios.db')
    args = parser.parse_args()
    print(json.dumps(build(args.db, args.snapshot), indent=2))
