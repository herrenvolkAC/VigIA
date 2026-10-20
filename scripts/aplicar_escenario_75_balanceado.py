"""Aplica umbrales ~75%, calibra montos a +15% y reemplaza los caches.

No genera ni modifica la presentación. Conserva auditoría previa en SQLite.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import routers.estudio_premios_productividad as estudio
from generar_informe_gerencial_umbrales import analyze
from simular_montos_10_15 import simulate


UMBRALES = {
    ('CD-ADMINISTRACION', 'CONTROLADOR DE STOCK SECOS NOA', 'CONTROL', '1,6'): 1120,
    ('CD-NOA', 'ARMADOR', 'ARMADO', '6'): 730,
    ('CD-NOA', 'AUTOELEVADORISTA ARMADO Y GUARDADO NOA', 'CLARK', '6'): 155,
    ('CD-NOA', 'RECEPCIONISTA', 'RECEPCION', '6'): 75,
    ('CD-REFRIGERADOS', 'ARMADOR', 'ARMADO', '2,4'): 800,
    ('CD-REFRIGERADOS', 'ARMADOR T06', 'ARMADO', '2,4'): 445,
    ('CD-REFRIGERADOS', 'AUTOELEVADORISTA (REFRIG)', 'CLARK', '2,4'): 165,
    ('CD-REFRIGERADOS', 'CARGADOR (REFRIG)', 'PALETS OPERADOS', '2,4'): 85,
    ('CD-REFRIGERADOS', 'CLARK CONGELADOS', 'CLARK', '2,4'): 70,
    ('CD-REFRIGERADOS', 'RECEPCIONISTA (REFRIG.)', 'RECEPCION', '2,4'): 40,
    ('CD-SECOS - ZONA 1', 'ARMADOR', 'ARMADO', '1'): 1090,
    ('CD-SECOS - ZONA 1', 'AUTOELEVADORISTA', 'CLARK', '1'): 150,
    ('CD-SECOS - ZONA 1', 'CARGADOR DE SECOS', 'PALETS OPERADOS', '1,6'): 130,
    ('CD-SECOS - ZONA 1', 'RECEPCIONISTA', 'RECEPCION', '1'): 65,
    ('CD-SECOS - ZONA 2', 'ARMADOR', 'ARMADO', '1'): 1090,
    ('CD-SECOS - ZONA 2', 'AUTOELEVADORISTA', 'CLARK', '1'): 150,
    ('CD-SECOS - ZONA 2', 'RECEPCIONISTA DE SECO', 'RECEPCION', '1'): 60,
}


async def admin_local(_request):
    return {'role': 'admin', 'device_status': 'approved'}


def audit_and_thresholds() -> str:
    db_path = ROOT / 'datos' / 'laboratorio_premios.db'
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    execution = datetime.now().astimezone().isoformat(timespec='seconds')
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS lab_ajuste_umbral_auditoria(
            ejecucion TEXT NOT NULL, tipo TEXT NOT NULL, payload_json TEXT NOT NULL,
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(ejecucion,tipo))''')
        for kind, table, order in (
            ('parametros_antes_75', 'lab_parametro_grupal', 'sector,funcion_legajero,turno'),
            ('escalas_antes_75', 'lab_escala_individual_grupal', 'sector,funcion_legajero,turno,nivel')):
            rows = [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE activo=1 ORDER BY {order}')]
            db.execute('INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)',
                       (execution, kind, json.dumps(rows, ensure_ascii=False)))
        for (sector, function, operation, division), value in UMBRALES.items():
            cur = db.execute('''UPDATE lab_parametro_grupal
                SET uc_por_operario=?,updated_at=CURRENT_TIMESTAMP
                WHERE activo=1 AND sector=? AND funcion_legajero=?
                  AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?''',
                (value, sector, function, operation, division))
            if cur.rowcount != 3:
                raise RuntimeError(f'Perfil inesperado: {sector}/{function}/{operation}: {cur.rowcount}')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return execution


def apply_awards(report: dict, scenario: dict, execution: str) -> None:
    settings = {pid: values for family in scenario['familias'].values()
                for pid, values in family['montos'].items()}
    db = sqlite3.connect(ROOT / 'datos' / 'laboratorio_premios.db')
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)',
                   (execution, 'escenario_montos_75', json.dumps(scenario, ensure_ascii=False)))
        for p in report['perfiles']:
            values = settings[p['id']]
            common = (p['sector'], p['funcion'], p['operacion'], p['division'])
            cur = db.execute('''UPDATE lab_parametro_grupal SET premio_grupal=?,updated_at=CURRENT_TIMESTAMP
                WHERE activo=1 AND sector=? AND funcion_legajero=?
                  AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?''',
                (values['grupal'], *common))
            if cur.rowcount != 3:
                raise RuntimeError(f'Premio grupal inesperado: {p["id"]}: {cur.rowcount}')
            for level, award in values['individual'].items():
                cur = db.execute('''UPDATE lab_escala_individual_grupal
                    SET premio=?,updated_at=CURRENT_TIMESTAMP
                    WHERE activo=1 AND sector=? AND funcion_legajero=?
                      AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=? AND nivel=?''',
                    (award, *common, int(level)))
                if cur.rowcount != 3:
                    raise RuntimeError(f'Escala inesperada: {p["id"]}/N{level}: {cur.rowcount}')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def recalculate():
    group = await estudio.calculo_grupal(None, '2026-08-01', '2026-09-30')
    individual = await estudio.recalcular_individual(None, '2026-08-01', '2026-09-30')
    return len(group.get('nivel_2', [])), len(group.get('nivel_3', [])), individual


async def main():
    execution = audit_and_thresholds()
    estudio._admin = admin_local
    await estudio.generar_escalas_individuales_grupales(None)
    await recalculate()
    interim = analyze('2026-08-01', '2026-09-30')
    scenario = simulate(1.15, interim, balanced=True)
    apply_awards(interim, scenario, execution)
    groups, people_days, individual = await recalculate()
    final = analyze('2026-08-01', '2026-09-30')
    output = ROOT / 'outputs' / 'escenario_75_balanceado_resultado.json'
    output.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ejecucion': execution, 'grupos_diarios': groups,
                      'legajo_dias': people_days, 'individual': individual,
                      'escenario_estimado': scenario['total'], 'resultado': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
