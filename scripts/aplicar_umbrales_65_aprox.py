"""Aplica umbrales grupales redondos, regenera escalas y recalcula agosto-septiembre.

La auditoria previa se conserva dentro de laboratorio_premios.db. La corrida es
idempotente: repetirla vuelve a establecer los mismos umbrales y reemplaza caches.
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

import routers.estudio_premios_productividad as estudio


UMBRALES = {
    ('CD-ADMINISTRACION', 'CONTROLADOR DE STOCK SECOS NOA', 'CONTROL', '1,6'): 1160,
    ('CD-NOA', 'ARMADOR', 'ARMADO', '6'): 750,
    ('CD-NOA', 'AUTOELEVADORISTA ARMADO Y GUARDADO NOA', 'CLARK', '6'): 160,
    ('CD-NOA', 'RECEPCIONISTA', 'RECEPCION', '6'): 80,
    ('CD-REFRIGERADOS', 'ARMADOR', 'ARMADO', '2,4'): 900,
    ('CD-REFRIGERADOS', 'ARMADOR T06', 'ARMADO', '2,4'): 470,
    ('CD-REFRIGERADOS', 'AUTOELEVADORISTA (REFRIG)', 'CLARK', '2,4'): 170,
    ('CD-REFRIGERADOS', 'CARGADOR (REFRIG)', 'PALETS OPERADOS', '2,4'): 90,
    ('CD-REFRIGERADOS', 'CLARK CONGELADOS', 'CLARK', '2,4'): 75,
    ('CD-REFRIGERADOS', 'RECEPCIONISTA (REFRIG.)', 'RECEPCION', '2,4'): 50,
    ('CD-SECOS - ZONA 1', 'ARMADOR', 'ARMADO', '1'): 1090,
    ('CD-SECOS - ZONA 1', 'AUTOELEVADORISTA', 'CLARK', '1'): 155,
    ('CD-SECOS - ZONA 1', 'CARGADOR DE SECOS', 'PALETS OPERADOS', '1,6'): 135,
    ('CD-SECOS - ZONA 1', 'RECEPCIONISTA', 'RECEPCION', '1'): 65,
    ('CD-SECOS - ZONA 2', 'ARMADOR', 'ARMADO', '1'): 1090,
    ('CD-SECOS - ZONA 2', 'AUTOELEVADORISTA', 'CLARK', '1'): 155,
    ('CD-SECOS - ZONA 2', 'RECEPCIONISTA DE SECO', 'RECEPCION', '1'): 65,
}


def aplicar_datos() -> str:
    db_path = ROOT / 'datos' / 'laboratorio_premios.db'
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    ejecucion = datetime.now().astimezone().isoformat(timespec='seconds')
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS lab_ajuste_umbral_auditoria(
            ejecucion TEXT NOT NULL, tipo TEXT NOT NULL, payload_json TEXT NOT NULL,
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(ejecucion,tipo))''')
        parametros = [dict(r) for r in db.execute(
            'SELECT * FROM lab_parametro_grupal WHERE activo=1 ORDER BY sector,funcion_legajero,turno')]
        escalas = [dict(r) for r in db.execute(
            'SELECT * FROM lab_escala_individual_grupal WHERE activo=1 ORDER BY sector,funcion_legajero,turno,nivel')]
        db.execute('INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)',
                   (ejecucion, 'parametros_antes', json.dumps(parametros, ensure_ascii=False)))
        db.execute('INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)',
                   (ejecucion, 'escalas_antes', json.dumps(escalas, ensure_ascii=False)))
        for (sector, funcion, operacion, division), valor in UMBRALES.items():
            cur = db.execute('''UPDATE lab_parametro_grupal SET uc_por_operario=?,updated_at=CURRENT_TIMESTAMP
                WHERE activo=1 AND sector=? AND funcion_legajero=?
                  AND UPPER(TRIM(operacion_medible))=? AND COALESCE(division_madre,'')=?''',
                (valor, sector, funcion, operacion, division))
            if cur.rowcount != 3:
                raise RuntimeError(f'Perfil inesperado: {sector} / {funcion} / {operacion}: {cur.rowcount} turnos')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return ejecucion


async def admin_local(_request):
    return {'role': 'admin', 'device_status': 'approved'}


async def main() -> None:
    ejecucion = aplicar_datos()
    estudio._admin = admin_local
    escalas = await estudio.generar_escalas_individuales_grupales(None)
    grupal = await estudio.calculo_grupal(None, '2026-08-01', '2026-09-30')
    individual = await estudio.recalcular_individual(None, '2026-08-01', '2026-09-30')
    print(json.dumps({
        'ejecucion': ejecucion,
        'umbrales': len(UMBRALES),
        'escalas': escalas,
        'grupos_diarios': len(grupal.get('nivel_2', [])),
        'legajo_dias': len(grupal.get('nivel_3', [])),
        'individual': individual,
    }, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
