"""Copia un snapshot local del estudio para extenderlo sin alterar el original."""
import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'datos' / 'laboratorio_premios.db'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origen', required=True)
    parser.add_argument('--destino', required=True)
    args = parser.parse_args()
    if args.origen == args.destino:
        raise SystemExit('El snapshot destino debe ser diferente del origen.')
    with sqlite3.connect(DB, timeout=60) as db:
        db.execute('PRAGMA busy_timeout=60000')
        existe = db.execute('SELECT COUNT(*) FROM lab_fuente_lote WHERE snapshot=?', (args.destino,)).fetchone()[0]
        if existe:
            print(f'{args.destino}: ya existe con {existe} lotes; no se modifica.')
            return
        lotes = db.execute('''SELECT ?,fuente,segmento,capturado,filas,sha256,consulta
                              FROM lab_fuente_lote WHERE snapshot=?''',
                           (args.destino, args.origen)).fetchall()
        registros = db.execute('''SELECT ?,fuente,segmento,ordinal,payload
                                  FROM lab_fuente_registro WHERE snapshot=?''',
                                (args.destino, args.origen)).fetchall()
        if not lotes or not registros:
            raise SystemExit(f'No hay fuentes para el snapshot {args.origen}.')
        with db:
            db.executemany('INSERT INTO lab_fuente_lote VALUES(?,?,?,?,?,?,?)', lotes)
            db.executemany('INSERT INTO lab_fuente_registro VALUES(?,?,?,?,?)', registros)
        print({'origen': args.origen, 'destino': args.destino,
               'lotes': len(lotes), 'registros': len(registros)})


if __name__ == '__main__':
    main()
