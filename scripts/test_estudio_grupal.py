"""Regresión del premio grupal. Ejecutar: python scripts/test_estudio_grupal.py."""
import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.estudio_grupal import calcular_grupal, inferir_turnos
from routers import estudio_premios_productividad as api
import aiosqlite
from fastapi import HTTPException


def fixtures():
    persons = [dict(legajo=str(i), nombre=f'Persona {i}', active=1,
                    desc_sector_generico='S', desc_funcion='F') for i in range(1, 7)]
    days = [dict(LEGAJO=str(i), FECHA='20260801', TURNO='1', AUSENTE='NO',
                 COD_AUSENTISMO='', DES_AUSENTISMO='') for i in range(1, 7)]
    for i, code in [(2, 'A'), (3, 'B'), (6, 'A')]:
        days[i-1].update(AUSENTE='SI', COD_AUSENTISMO=code, DES_AUSENTISMO='Permitida' if code == 'A' else 'No permitida')
    production = [dict(fecha='20260801', legajo=l, desc_funcion=o, palets=u, cantidad=u*10, plus=u*2)
                  for l, o, u in [('1', 'CARGA CAMION', 100), ('4', 'CARGA CAMION', 80),
                                  ('4', 'PICKIN', 2), ('6', 'CARGA CAMION', 10), ('6', 'PICKIN', 1)]]
    params = [dict(sector='S', funcion_legajero='F', turno='1', activo=1,
                   operacion_medible='CARGA CAMION', uc_por_operario=30,
                   factor_ausentismo=10, premio_grupal=500)]
    return persons, days, production, params


class CalculationTests(unittest.TestCase):
    def setUp(self):
        self.persons, self.days, self.production, self.params = fixtures()
        self.operations = {'CARGA CAMION': 'PALET'}
        self.fixed = {str(i): '1' for i in range(1, 7)}

    def calculate(self):
        return calcular_grupal(self.persons, self.days, self.production, self.params,
                               self.operations, [('CARGA', 'PICKIN')], {'A': True, 'B': False},
                               '20260801', '20260801', self.fixed)

    def test_full_roster_union_deductions_and_present_poly_paid(self):
        result = self.calculate()
        day = result['nivel_2'][0]
        self.assertEqual(len(result['nivel_3']), 6)
        self.assertEqual(day['nomina_computable'], 3)  # 6 - union(2,4,6)
        self.assertEqual(day['target'], 81)  # 3 * 30 * 90%
        self.assertEqual(day['uc_computables'], 100)
        self.assertEqual(day['premio_grupal_total'], 1500)
        self.assertEqual({p['legajo'] for p in result['nivel_3'] if p['cobra']}, {'1', '4', '5'})
        self.assertTrue(next(p for p in result['nivel_3'] if p['legajo'] == '3')['integra_meta'])
        self.assertEqual(result['nivel_1'][0]['dias'], 1)
        self.assertEqual(result['nivel_1'][0]['premio_grupal_total'], 1500)

    def test_equal_to_threshold_does_not_pay(self):
        self.production[0]['palets'] = 81
        self.assertFalse(self.calculate()['nivel_2'][0]['cumple'])

    def test_fractional_production_not_rounded_before_threshold(self):
        self.production[0]['palets'] = 81.001
        self.assertTrue(self.calculate()['nivel_2'][0]['cumple'])

    def test_activity_in_multiple_shifts_is_paid_only_in_mother_shift(self):
        original = self.production[0]
        self.production[0] = dict(original, palets=40, turno='2')
        self.production.append(dict(original, palets=60, turno='3'))
        self.days[0]['TURNO'] = '2'
        self.days.append(dict(self.days[0], TURNO='3'))
        self.params.append(dict(self.params[0], turno='2'))
        self.params.append(dict(self.params[0], turno='3'))
        result = self.calculate()
        mother = next(d for d in result['nivel_2'] if d['turno'] == '1')
        self.assertEqual(mother['uc_computables'], 100)
        self.assertEqual(mother['premio_grupal_total'], 1500)
        self.assertEqual(sum(d['uc_computables'] for d in result['nivel_2']), 100)
        person = [p for p in result['nivel_3'] if p['legajo'] == '1']
        self.assertEqual(len(person), 1)
        self.assertEqual(person[0]['turno_fijo'], '1')
        self.assertTrue(person[0]['cobra'])
        self.assertNotIn('diferencia_turno', person[0])

    def test_polivalence_in_another_shift_still_uses_mother_rules(self):
        self.days[3]['TURNO'] = '3'
        for row in self.production:
            if row['legajo'] == '4':
                row['turno'] = '3'
        person = next(p for p in self.calculate()['nivel_3'] if p['legajo'] == '4')
        self.assertEqual(person['turno_fijo'], '1')
        self.assertTrue(person['es_polivalencia'])
        self.assertEqual(person['uc_computables'], 0)
        self.assertFalse(person['integra_meta'])
        self.assertTrue(person['cobra'])

    def test_poly_only_worked_in_additional_operation(self):
        self.production = [r for r in self.production if not (r['legajo'] == '4' and r['desc_funcion'] == 'CARGA CAMION')]
        person = next(p for p in self.calculate()['nivel_3'] if p['legajo'] == '4')
        self.assertTrue(person['es_polivalencia'])
        self.assertTrue(person['cobra'])

    def test_missing_attendance_keeps_person_and_blocks_payment(self):
        self.days = self.days[:-1]
        result = self.calculate()
        self.assertEqual(len(result['nivel_3']), 6)
        self.assertEqual(result['nivel_2'][0]['pendientes'], 1)
        self.assertFalse(result['nivel_2'][0]['evaluable'])
        self.assertFalse(any(p['cobra'] for p in result['nivel_3']))

    def test_duplicate_source_rows_do_not_duplicate_people(self):
        self.days += self.days.copy()
        self.assertEqual(self.calculate()['nivel_2'][0]['activos'], 6)

    def test_conflicting_attendance_is_pending(self):
        self.days.append(dict(self.days[0], AUSENTE='SI'))
        self.assertEqual(self.calculate()['nivel_2'][0]['pendientes'], 1)

    def test_daily_shift_does_not_move_fixed_roster(self):
        self.days[0]['TURNO'] = '2'
        self.persons[1]['active'] = 0
        result = self.calculate()
        self.assertEqual({p['legajo'] for p in result['nivel_3']}, {'1', '3', '4', '5', '6'})
        person = next(p for p in result['nivel_3'] if p['legajo'] == '1')
        self.assertEqual(person['motivo_inclusion'], 'Incluido')
        self.assertNotIn('turno_confirmado', person)
        self.assertEqual(person['turno_fijo'], '1')
        self.assertEqual(person['asistencia'], 'Presente')
        self.assertTrue(person['integra_meta'])
        self.assertTrue(person['beneficiario'])
        self.assertFalse(person['pendiente_calculo'])

    def test_daily_shift_has_no_effect_on_calculation_or_response(self):
        expected = self.calculate()
        for day in self.days:
            day['TURNO'] = 'otro'
        actual = self.calculate()
        self.assertEqual(actual, expected)
        removed = {'diferencia_turno', 'diferencias_turno', 'otro_turno', 'fuera_turno', 'turno_confirmado'}
        for level in ('nivel_1', 'nivel_2', 'nivel_3'):
            self.assertTrue(all(not (set(row) & removed) for row in actual[level]))

    def test_missing_operation_is_pending_not_guessed(self):
        self.params[0]['operacion_medible'] = ''
        result = self.calculate()
        self.assertEqual(len(result['nivel_3']), 6)
        self.assertFalse(result['nivel_2'][0]['evaluable'])

    def test_units_come_from_operation(self):
        for unit, expected in [('BULTO', 1000), ('PLU', 200)]:
            self.operations['CARGA CAMION'] = unit
            self.assertEqual(self.calculate()['nivel_2'][0]['uc_computables'], expected)

    def test_only_active_parameters_and_assignment_dates(self):
        self.persons[0]['fecha_ingreso'] = '2026-08-02'
        self.persons[1]['fecha_baja'] = '2026-08-01'
        result = self.calculate()
        self.assertEqual(len(result['nivel_3']), 6)
        self.assertEqual(result['nivel_2'][0]['fuera_vigencia'], 2)
        self.assertTrue(all(not p['integra_meta'] and not p['beneficiario'] for p in result['nivel_3'] if p['legajo'] in {'1', '2'}))
        self.params[0]['activo'] = 0
        self.assertEqual(self.calculate()['nivel_1'], [])

    def test_roster_fixed_across_dates_shifts_and_missing_records(self):
        self.persons.append(dict(self.persons[0], legajo='7', nombre='Sin registros'))
        self.persons[0]['fecha_ingreso'] = '2026-08-02'
        self.days += [dict(r, FECHA='20260802', TURNO='2') for r in self.days]
        self.params.append(dict(self.params[0], turno='2'))
        fixed = {str(i): '1' if i < 4 else '2' for i in range(1, 7)}
        result = calcular_grupal(self.persons, self.days, self.production, self.params,
                                 self.operations, [('CARGA', 'PICKIN')], {'A': True}, '20260801', '20260802', fixed)
        for group in result['nivel_1']:
            self.assertEqual(group['nomina_total'], 3)
        for day in result['nivel_2']:
            people = [p for p in result['nivel_3'] if p['fecha'] == day['fecha'] and p['turno'] == day['turno']]
            expected = {'1','2','3'} if day['turno'] == '1' else {'4','5','6'}
            self.assertEqual({p['legajo'] for p in people}, expected)
            self.assertEqual(day['nomina_total'], 3)
            self.assertEqual(day['nomina_total'], day['activos'] + day['fuera_vigencia'])
        self.assertEqual([p['legajo'] for p in result['sin_turno']], ['7'])

    def test_fixed_person_without_any_records_stays_visible(self):
        self.days = [r for r in self.days if r['LEGAJO'] != '5']
        result = self.calculate()
        missing = next(p for p in result['nivel_3'] if p['legajo'] == '5')
        self.assertEqual(missing['motivo_inclusion'], 'Sin asistencia ni actividad')
        self.assertFalse(missing['tiene_actividad'])
        self.assertFalse(result['nivel_2'][0]['evaluable'])

    def test_modal_shift_counts_distinct_days_and_tie_uses_recency(self):
        rows = [dict(LEGAJO='1',TURNO=t,FECHA=f) for t,f in
                [('1','20260801'),('1','20260802'),('2','20260803')]]
        rows += [rows[-1]] * 20
        self.assertEqual(inferir_turnos(rows)['1']['turno_probable'], '1')
        rows.append(dict(LEGAJO='1',TURNO='2',FECHA='20260804'))
        result = inferir_turnos(rows)['1']
        self.assertEqual(result['turno_probable'], '2')
        self.assertEqual(result['total_dias'], 4)
        rows.append(dict(LEGAJO='1',TURNO='1',FECHA='20260804'))
        rows.append(dict(LEGAJO='1',TURNO='2',FECHA='20260802'))
        self.assertEqual(inferir_turnos(rows)['1']['turno_probable'], '1')


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lab, self.rrhh = Path(self.tmp.name)/'lab.db', Path(self.tmp.name)/'rrhh.db'
        async def admin(request):
            pass
        self.patches = [patch.object(api, 'LAB_CACHE_DB_PATH', self.lab),
                        patch.object(api, 'RRHH_GRUPAL_DB_PATH', self.rrhh), patch.object(api, '_admin', admin)]
        for p in self.patches:
            p.start()
        persons, days, production, params = fixtures()
        self.params = params[0]
        with sqlite3.connect(self.lab) as db:
            db.execute('CREATE TABLE lab_cache_agrupado(fecha TEXT,legajo TEXT,desc_funcion TEXT,division TEXT,palets REAL,plus REAL,cantidad REAL)')
            db.executemany('INSERT INTO lab_cache_agrupado VALUES(?,?,?,"",?,?,?)',
                           [(r['fecha'],r['legajo'],r['desc_funcion'],r['palets'],r['plus'],r['cantidad']) for r in production])
            db.execute('CREATE TABLE lab_fuente_lote(snapshot TEXT,fuente TEXT,capturado TEXT)')
            db.execute("INSERT INTO lab_fuente_lote VALUES('test','oracle.PV_DIA_LABORAL','2026-09-08')")
            db.execute('CREATE TABLE lab_fuente_registro(snapshot TEXT,fuente TEXT,payload TEXT)')
            db.executemany("INSERT INTO lab_fuente_registro VALUES('test','oracle.PV_DIA_LABORAL',?)", [(json.dumps(r),) for r in days])
        db.close()
        async with aiosqlite.connect(self.lab) as db:
            await api._ensure_config(db)
            await db.execute("UPDATE lab_funcion_parametro SET medible=1,unidad_medida='PALET' WHERE desc_funcion='CARGA CAMION'")
            await db.execute("INSERT INTO lab_ausencia_config(cod_ausentismo,descripcion,permitido) VALUES('Permitida','Permitida',1)")
            await db.execute("INSERT INTO lab_mapa_polivalencia(operacion_a,operacion_b,polivalencia) VALUES('CARGA','PICKIN',1)")
            await db.commit()
        with sqlite3.connect(self.rrhh) as db:
            db.execute('CREATE TABLE rrhh_personas(legajo TEXT,nombre TEXT,desc_sector_generico TEXT,desc_funcion TEXT,active INTEGER,fecha_ingreso TEXT,fecha_baja TEXT)')
            db.executemany('INSERT INTO rrhh_personas VALUES(?,?,?,?,1,NULL,NULL)', [(r['legajo'],r['nombre'],'S','F') for r in persons])
        db.close()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    async def save(self, payload):
        class Request:
            async def json(self):
                return payload
        return await api.guardar_parametro_grupal(Request())

    async def test_save_reload_calculate_and_absence_migration(self):
        await self.save(self.params)
        config = await api.parametros_grupales(None)
        self.assertEqual(config['rows'][0]['operacion_medible'], 'CARGA CAMION')
        self.assertEqual(config['operaciones'][0]['unidad_medida'], 'PALET')
        absence = await api.ausencias_config(None)
        self.assertTrue(next(r for r in absence['rows'] if r['cod_ausentismo'] == 'A')['permitido'])
        result = await api.calculo_grupal(None, '2026-08-01', '2026-08-01')
        self.assertEqual(result['nivel_2'][0]['premio_grupal_total'], 1500)
        self.assertEqual(len(result['nivel_3']), 6)

    async def test_reject_invalid_inputs_without_mutating_saved_row(self):
        await self.save(self.params)
        for change in [dict(operacion_medible=''), dict(operacion_medible='PICKIN'),
                       dict(uc_por_operario=0), dict(factor_ausentismo=101), dict(premio_grupal=-1),
                       dict(premio_grupal='nan')]:
            with self.assertRaises(HTTPException):
                await self.save(dict(self.params, **change))
        self.assertEqual((await api.parametros_grupales(None))['rows'][0]['premio_grupal'], 500)

    async def test_migration_is_idempotent_and_preserves_values(self):
        await self.save(self.params)
        async with aiosqlite.connect(self.lab) as db:
            await db.execute('ALTER TABLE lab_parametro_grupal DROP COLUMN operacion_medible')
            await db.commit()
            await api._ensure_config(db)
            await api._ensure_config(db)
        row = (await api.parametros_grupales(None))['rows'][0]
        self.assertEqual(row['premio_grupal'], 500)
        self.assertEqual(row['operacion_medible'], '')

    async def test_invalid_dates(self):
        for dates in [('bad', '2026-08-01'), ('2026-08-02', '2026-08-01')]:
            with self.assertRaises(HTTPException):
                await api.calculo_grupal(None, *dates)

    async def test_fixed_shift_persists_manual_override_and_limits_roster(self):
        await self.save(self.params)
        await self.save(dict(self.params, turno='2'))
        initial = await api.turnos_grupales(None)
        self.assertTrue(all(r['turno_fijo'] == '1' for r in initial['rows']))
        class Request:
            async def json(self):
                return {'legajo': '1', 'turno_fijo': '2'}
        await api.guardar_turno_grupal(Request())
        async with aiosqlite.connect(self.lab) as db:
            # Nueva evidencia no debe reescribir lo que quedó fijado.
            await db.execute("UPDATE lab_fuente_registro SET payload=json_set(payload,'$.TURNO','3')")
            await db.commit()
        refreshed = await api.turnos_grupales(None)
        one = next(r for r in refreshed['rows'] if r['legajo'] == '1')
        self.assertEqual(one['turno_fijo'], '2')
        self.assertEqual(one['turno_probable'], '1')
        self.assertEqual(one['origen'], 'manual')
        result = await api.calculo_grupal(None, '2026-08-01', '2026-08-02')
        for day in result['nivel_2']:
            expected = 5 if day['turno'] == '1' else 1
            self.assertEqual(day['nomina_total'], expected)
        people = [p for p in result['nivel_3'] if p['legajo'] == '1']
        self.assertEqual(len(people), 2)
        self.assertTrue(all(p['turno_fijo'] == '2' for p in people))

    async def test_no_history_is_saved_unassigned(self):
        async with aiosqlite.connect(self.rrhh) as db:
            await db.execute("INSERT INTO rrhh_personas VALUES('7','Sin historial','S','F',1,NULL,NULL)")
            await db.commit()
        rows = (await api.turnos_grupales(None))['rows']
        missing = next(r for r in rows if r['legajo'] == '7')
        self.assertEqual(missing['turno_fijo'], '')
        self.assertEqual(missing['criterio'], 'sin_historial')

    async def add_group_catalog(self):
        async with aiosqlite.connect(self.lab) as db:
            await db.execute("INSERT INTO lab_fuente_lote VALUES('test','oracle.PV_GRUPO_PRODUCTIVO_CAB','2026-09-08')")
            await db.executemany("INSERT INTO lab_fuente_registro VALUES('test','oracle.PV_GRUPO_PRODUCTIVO_CAB',?)",
                [(json.dumps({'ID': 19, 'DESCRIPCION': 'AREA SECOS Y NO ALIMENTOS'}),),
                 (json.dumps({'ID': 21, 'DESCRIPCION': 'SECOS + NOA'}),)])
            await db.commit()

    async def test_group_optional_and_valid_even_without_catalog(self):
        await self.save(dict(self.params, grupo_productivo_id=None))
        row = (await api.parametros_grupales(None))['rows'][0]
        self.assertIsNone(row['grupo_productivo_id'])
        self.assertEqual(row['grupo_productivo'], '')
        result = await api.calculo_grupal(None, '2026-08-01', '2026-08-01')
        self.assertEqual(result['nivel_1'][0]['premio_grupal_total'], 1500)
        self.assertIsNone(result['nivel_1'][0]['grupo_productivo_id'])

    async def test_group_persisted_and_propagated_without_changing_payment(self):
        await self.add_group_catalog()
        await self.save(dict(self.params, grupo_productivo_id='19'))
        config = await api.parametros_grupales(None)
        self.assertEqual(config['rows'][0]['grupo_productivo_id'], 19)
        self.assertEqual(len(config['grupos_productivos']), 2)
        result = await api.calculo_grupal(None, '2026-08-01', '2026-08-01')
        for level in ('nivel_1', 'nivel_2', 'nivel_3'):
            self.assertTrue(all(r['grupo_productivo_id'] == 19 and r['grupo_productivo'] == 'AREA SECOS Y NO ALIMENTOS' for r in result[level]))
        self.assertEqual(result['nivel_1'][0]['premio_grupal_total'], 1500)

    async def test_group_can_be_cleared_and_omission_preserves_it(self):
        await self.add_group_catalog()
        await self.save(dict(self.params, grupo_productivo_id=19))
        await self.save(self.params)
        self.assertEqual((await api.parametros_grupales(None))['rows'][0]['grupo_productivo_id'], 19)
        for empty in ('', None):
            await self.save(dict(self.params, grupo_productivo_id=19))
            await self.save(dict(self.params, grupo_productivo_id=empty))
            self.assertIsNone((await api.parametros_grupales(None))['rows'][0]['grupo_productivo_id'])

    async def test_invalid_group_rejected_without_changing_association(self):
        await self.add_group_catalog()
        await self.save(dict(self.params, grupo_productivo_id=19))
        for invalid in (999, 'AREA SECOS Y NO ALIMENTOS', 19.5):
            with self.assertRaises(HTTPException):
                await self.save(dict(self.params, grupo_productivo_id=invalid))
        self.assertEqual((await api.parametros_grupales(None))['rows'][0]['grupo_productivo_id'], 19)


if __name__ == '__main__':
    unittest.main()
