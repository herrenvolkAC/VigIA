"""Carga puntual: python -m scripts.cargar_tnc_resumen 2026-10-15 2026-10-19."""
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, timedelta

from db.schema import DB_PATH, CREATE_TNC_RESUMEN_DIARIO, CREATE_TNC_RESUMEN_SYNC, CREATE_TNC_EXCESOS_DIARIOS
from routers.productividad_analisis import query_productive_db_tnc_master, query_productive_db_tnc_monitor


def number(value):
    return None if value is None or str(value).strip() == '' else float(value)


def load(start, end, *, refresh_from=None):
    master = query_productive_db_tnc_master()
    rules = {}
    for row in master:
        code = str(row.get('CODIGO_TNC') or '').strip()
        rule = (number(row.get('DURACION_MINUTOS_PRODUCTIVIDAD')),
                number(row.get('CANTIDAD_DE_OCURRENCIAS')),
                number(row.get('TOLERANCIA_X_EXCESO')),
                row.get('TIENE_TIEMPO_MAXIMO'), row.get('TIENE_TOLERANCIA_X_EXCESO'))
        if code in rules and rules[code] != rule:
            raise RuntimeError(f'Reglas ambiguas para TNC {code}; no se cargaron datos.')
        rules[code] = rule

    with closing(sqlite3.connect(DB_PATH, timeout=30)) as db:
        db.execute(CREATE_TNC_RESUMEN_DIARIO)
        db.execute(CREATE_TNC_RESUMEN_SYNC)
        db.execute(CREATE_TNC_EXCESOS_DIARIOS)
        db.commit()
        day = start
        while day <= end:
            day_text = day.isoformat()
            if (refresh_from is None or day < refresh_from) and db.execute('SELECT 1 FROM tnc_resumen_sync WHERE fecha=?', (day_text,)).fetchone():
                print(f'{day_text}: ya cargado, se conserva', flush=True)
                day += timedelta(days=1)
                continue
            next_day = day + timedelta(days=1)
            rows = query_productive_db_tnc_monitor(f'{day_text} 00:00:00', f'{next_day.isoformat()} 00:00:00')
            groups = {}
            for row in rows:
                key = (day_text, str(row.get('EMPRESA') or ''), str(row.get('ALMACEN') or ''),
                       str(row.get('LEGAJO') or '').strip(), str(row.get('CODIGO_TNC') or '').strip())
                if not key[3] or not key[4] or str(row.get('DIA_TNC') or '') != day_text:
                    raise ValueError(f'Registro Oracle sin identidad o fuera de fecha: {day_text}')
                group = groups.setdefault(key, {'descripcion': row.get('TNC'), 'eventos': 0, 'minutos': 0,
                                                 'activos': 0, 'finalizados': 0, 'inicio': None, 'fin': None})
                group['eventos'] += 1
                group['minutos'] += int(number(row.get('MINUTOS')) or 0)
                active = str(row.get('ESTADO') or '').strip().lower() == 'activo'
                group['activos' if active else 'finalizados'] += 1
                start_time, end_time = row.get('LOTEINFORMACION_TS'), row.get('ULTIMAMODIFICACION_TS') if not active else None
                if start_time and (not group['inicio'] or start_time < group['inicio']): group['inicio'] = start_time
                if end_time and (not group['fin'] or end_time > group['fin']): group['fin'] = end_time
            synced = datetime.now().isoformat(timespec='seconds')
            payload = [(*key, value['descripcion'], value['eventos'], value['minutos'], value['activos'],
                        value['finalizados'], value['inicio'], value['fin'], *rules.get(key[4], (None,)*5), synced)
                       for key, value in groups.items()]
            with db:
                db.execute('DELETE FROM tnc_resumen_diario WHERE fecha=?', (day_text,))
                db.execute('DELETE FROM tnc_resumen_sync WHERE fecha=?', (day_text,))
                db.executemany('INSERT INTO tnc_resumen_diario VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', payload)
                db.execute('INSERT INTO tnc_resumen_sync VALUES (?,?,?,?)', (day_text, synced, len(rows), len(payload)))
            print(f'{day_text}: {len(rows)} eventos, {len(payload)} filas agrupadas', flush=True)
            day = next_day


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Indicar fecha desde y hasta en formato AAAA-MM-DD.')
    start_date, end_date = map(date.fromisoformat, sys.argv[1:])
    if end_date < start_date or end_date >= date.today():
        raise SystemExit('El rango debe estar ordenado y ser de días anteriores a hoy.')
    load(start_date, end_date)
