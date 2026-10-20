"""Reconstruye la cache grupal desde fuentes ya materializadas en el laboratorio."""
import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / 'datos' / 'laboratorio_premios.db'
RRHH = ROOT / 'datos' / 'vigia.db'


def _ymd(value):
    return value.replace('-', '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desde', default='2026-08-01')
    parser.add_argument('--hasta', default='2026-08-31')
    parser.add_argument('--snapshot', default='estudio_20261014_agosep')
    args = parser.parse_args()
    desde, hasta = _ymd(args.desde), _ymd(args.hasta)
    con = sqlite3.connect(LAB, timeout=60)
    con.execute('PRAGMA busy_timeout=60000')
    con.execute("ATTACH DATABASE ? AS rrhh", (str(RRHH),))
    dias = [json.loads(payload) for (payload,) in con.execute(
        """SELECT payload FROM lab_fuente_registro
           WHERE snapshot=? AND fuente='oracle.PV_DIA_LABORAL'
             AND segmento BETWEEN ? AND ? ORDER BY segmento, ordinal""",
        (args.snapshot, desde, hasta))]
    if not dias:
        raise SystemExit(f'No hay PV_DIA_LABORAL para {args.snapshot} entre {desde} y {hasta}.')
    con.execute('DELETE FROM lab_cache_grupal WHERE fecha BETWEEN ? AND ?', (desde, hasta))
    personas = {str(r[0]).strip(): (r[1] or '', r[2] or '', r[3] or '') for r in con.execute(
        'SELECT legajo,nombre,desc_sector_generico,desc_funcion FROM rrhh.rrhh_personas')}
    # El legajero fuente se conserva intacto. Los perfiles operativos
    # auditables sólo corrigen la clasificación usada por esta cache de
    # escenario (por ejemplo, Clark Congelados).
    try:
        perfiles_operativos = {
            str(r[0]).strip(): (r[1] or '', r[2] or '')
            for r in con.execute('''SELECT legajo,sector,funcion_legajero
                                    FROM lab_perfil_operativo_legajo WHERE activo=1''')
        }
    except sqlite3.OperationalError:
        perfiles_operativos = {}
    for legajo, (_, sector, funcion) in list(personas.items()):
        override = perfiles_operativos.get(legajo)
        if override:
            personas[legajo] = (personas[legajo][0], override[0] or sector, override[1] or funcion)
    ops = defaultdict(lambda: [0.0, 0.0, 0.0])
    absence_by_key = {}
    cache_rows = con.execute(
        'SELECT fecha,legajo,desc_funcion,palets,plus,cantidad FROM lab_cache_agrupado WHERE fecha BETWEEN ? AND ?',
        (desde, hasta)).fetchall()
    by_person = defaultdict(list)
    for row in cache_rows:
        by_person[(str(row[0]), str(row[1]).strip())].append(row)
    personas_con_actividad = set(by_person)
    for r in dias:
        fecha, legajo = str(r.get('FECHA')), str(r.get('LEGAJO') or '').strip()
        aus = str(r.get('DES_AUSENTISMO') or r.get('COD_AUSENTISMO') or '').strip()
        turno = str(r.get('TURNO') or '').strip()
        _, sector, funcion = personas.get(legajo, ('', '', ''))
        for _, _, oper, pal, plu, cant in by_person.get((fecha, legajo), []):
            key = (fecha, legajo, turno, sector, funcion, oper or '')
            absence_by_key[key] = aus
            item = ops[key]
            item[0] += float(pal or 0); item[1] += float(plu or 0); item[2] += float(cant or 0)
        if (fecha, legajo) not in personas_con_actividad:
            ops[(fecha, legajo, turno, sector, funcion, '')]
    con.executemany("""INSERT OR REPLACE INTO lab_cache_grupal
        (fecha,legajo,turno,sector,funcion_legajero,operacion,uc_brutas,uc_polivalencia,uc_computables,ausencia)
        VALUES(?,?,?,?,?,?,?,?,?,?)""", [
        (k[0], k[1], k[2], k[3], k[4], k[5], v[0], 0, v[0], absence_by_key.get(k, ''))
        for k, v in ops.items()])
    con.commit()
    print({'snapshot': args.snapshot, 'dias_origen': len(dias), 'cache_filas': len(ops), 'personas': len(personas)})


if __name__ == '__main__':
    main()
