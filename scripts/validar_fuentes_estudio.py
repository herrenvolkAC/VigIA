"""Control de cobertura y conciliación, sin modificar datos del estudio."""
import json
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

SNAPSHOT = 'estudio_20260907'
ROOT = Path(__file__).resolve().parents[1]

def main():
    with sqlite3.connect((ROOT/'datos/laboratorio_premios.db').as_uri()+'?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        def rows(table):
            return [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM lab_fuente_registro WHERE snapshot=? AND fuente=?', (SNAPSHOT, table))]
        counts = db.execute('SELECT fuente,COUNT(*),SUM(filas) FROM lab_fuente_lote WHERE snapshot=? GROUP BY fuente', (SNAPSHOT,)).fetchall()
        days = rows('oracle.PV_DIA_LABORAL')
        payments = rows('oracle.PV_LIQUIDAC_DIA_DET1')
        totals = defaultdict(Decimal)
        for r in payments:
            totals[str(r['ID_PV_DIA_LABORAL'])] += Decimal(str(r.get('A_PAGAR_TOTAL') or 0))
        actual = sum((Decimal(str(r.get('PREMIO') or 0)) for r in days), Decimal(0))
        differing = sum(abs(Decimal(str(r.get('PREMIO') or 0))-totals[str(r['ID'])]) > Decimal('.01') for r in days)
        ids = {str(r['ID']) for r in days}
        scales = rows('oracle.PV_ESCALA_DE_PREMIOS')
        result = {'snapshot': SNAPSHOT, 'fuentes_lotes_filas': counts,
                  'dias': len({r['FECHA'] for r in days}), 'legajos': len({r['LEGAJO'] for r in days}),
                  'premio_cabecera': str(actual), 'pago_det1': str(sum(totals.values(), Decimal(0))),
                  'jornadas_con_diferencias_cabecera_det1': differing,
                  'pagos_sin_cabecera': sum(str(r['ID_PV_DIA_LABORAL']) not in ids for r in payments),
                  'duplicados_id_cabecera': len(days)-len(ids),
                  'duplicados_id_det1': len(payments)-len({str(r['ID']) for r in payments}),
                  'grupos_con_escalas': len({r['ID_DE_GRUPO_DE_FUNCIONES'] for r in scales}),
                  'nota': 'PREMIO cabecera y A_PAGAR_TOTAL por grupo se conservan separados; diferencias pendientes de explicación.'}
        print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
