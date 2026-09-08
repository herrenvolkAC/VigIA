"""Carga controlada de la cache grupal desde PV_DIA_LABORAL."""
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from routers.analisis_premio_productividad import _query_oracle
LAB = ROOT / 'datos' / 'laboratorio_premios.db'
RRHH = ROOT / 'datos' / 'vigia.db'

def main():
    dias = _query_oracle("""SELECT ID,LEGAJO,FECHA,TURNO,AUSENTE,COD_AUSENTISMO,DES_AUSENTISMO,SITUACION,ESTADO
                           FROM PV_DIA_LABORAL WHERE FECHA BETWEEN 20260801 AND 20260831""")
    con = sqlite3.connect(LAB, timeout=60); con.execute('PRAGMA busy_timeout=60000'); con.execute("ATTACH DATABASE ? AS rrhh", (str(RRHH),))
    con.execute("DELETE FROM lab_cache_grupal WHERE fecha BETWEEN '20260801' AND '20260831'")
    personas = {str(r[0]).strip(): (r[1] or '', r[2] or '', r[3] or '') for r in con.execute("""SELECT legajo,nombre,desc_sector_generico,desc_funcion FROM rrhh.rrhh_personas""")}
    ops = defaultdict(lambda: [0.0, 0.0, 0.0])
    absence_by_key = {}
    cache_rows = con.execute("SELECT fecha,legajo,desc_funcion,palets,plus,cantidad FROM lab_cache_agrupado WHERE fecha BETWEEN '20260801' AND '20260831'").fetchall()
    by_person = defaultdict(list)
    for row in cache_rows: by_person[(str(row[0]), str(row[1]).strip())].append(row)
    for r in dias:
        fecha, legajo = str(r['FECHA']), str(r['LEGAJO']).strip()
        aus = str(r.get('DES_AUSENTISMO') or r.get('COD_AUSENTISMO') or '').strip()
        turno = str(r.get('TURNO') or '').strip()
        nombre, sector, funcion = personas.get(legajo, ('', '', ''))
        for _,_,oper,pal,plu,cant in by_person.get((fecha,legajo),[]):
            key=(fecha,legajo,turno,sector,funcion,oper or '')
            absence_by_key[key] = aus
            item=ops[key]; item[0]+=float(pal or 0); item[1]+=float(plu or 0); item[2]+=float(cant or 0)
        if not any(k[0]==fecha and k[1]==legajo for k in ops):
            ops[(fecha,legajo,turno,sector,funcion,'')]
    con.executemany("""INSERT OR REPLACE INTO lab_cache_grupal(fecha,legajo,turno,sector,funcion_legajero,operacion,uc_brutas,uc_polivalencia,uc_computables,ausencia)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""", [(k[0],k[1],k[2],k[3],k[4],k[5],v[0],0,v[0],absence_by_key.get(k,'')) for k,v in ops.items()])
    con.commit(); print({'oracle_dias':len(dias),'cache_filas':len(ops),'personas':len(personas)})

if __name__ == '__main__': main()
