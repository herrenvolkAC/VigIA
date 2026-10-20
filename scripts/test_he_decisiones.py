import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
from fastapi import HTTPException
from routers import horas_extras as he


class DecisionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_atomic_validation_and_manager_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            async def current(request, legajo, fecha):
                return dict(legajo=legajo, fecha=fecha, horas_extras_detectadas=3, cargado_sap=0)

            with patch.object(he, 'HORAS_EXTRAS_DB_PATH', Path(directory)/'he.db'), \
                 patch.object(he, '_require_auth', AsyncMock(return_value={'username':'test'})), \
                 patch.object(he, '_find_current_row', current):
                def decision(legajo='1', estado='pre_autorizada', hours=1.75, reason='Cierre de descarga'):
                    return he.DecisionRequest(legajo=legajo, fecha='2026-10-13', estado=estado,
                        etapa='gerencia' if estado=='aprobada_gerente' else 'pre_autorizacion',
                        horas_autorizadas=hours, justificacion=reason)

                async def save(*items):
                    return await he.decisiones(None, he.BulkDecisionRequest(rows=list(items)))

                with self.assertRaises(HTTPException):
                    await save(decision(), decision('2', reason='  '))
                async with aiosqlite.connect(he.HORAS_EXTRAS_DB_PATH) as db:
                    self.assertEqual((await (await db.execute('SELECT COUNT(*) FROM he_eventos')).fetchone())[0], 0)
                for value in (0, 4):
                    with self.assertRaises(HTTPException):
                        await save(decision(hours=value))
                rejected = await save(decision(estado='rechazada_jefe', hours=None))
                self.assertEqual(rejected['guardadas'], 1)
                async with aiosqlite.connect(he.HORAS_EXTRAS_DB_PATH) as db:
                    rejection = await (await db.execute('SELECT estado_actual FROM he_eventos WHERE legajo=?', ('1',))).fetchone()
                    self.assertEqual(rejection[0], 'rechazada_jefe')
                await save(decision())
                async with aiosqlite.connect(he.HORAS_EXTRAS_DB_PATH) as db:
                    await db.execute("INSERT INTO he_mail_destinatarios_legajos VALUES ('20','Destino')")
                    await db.execute("INSERT INTO he_mail_destinatarios_legajos VALUES ('21','Destino 2')")
                    await db.commit()
                with self.assertRaises(HTTPException):
                    await save(decision(estado='aprobada_gerente', hours=3))
                result = await save(decision(estado='aprobada_gerente', hours=None, reason=''))
                self.assertEqual(result['mail']['to'], '20;21')
                self.assertIn('01:45', result['mail']['body'])
                self.assertIn('Sin sector: 1 legajo | 01:45 hs aprobadas', result['mail']['body'])
                self.assertNotIn('Cierre de descarga', result['mail']['body'])
                historic = await he.historial(None, he.date(2026, 10, 1), he.date(2026, 10, 31), legajo='1')
                self.assertEqual(len(historic['rows']), 1)
                self.assertEqual(historic['rows'][0]['estado'], 'aprobada_gerente')
                self.assertEqual(historic['rows'][0]['horas_autorizadas'], 1.75)
                async with aiosqlite.connect(he.HORAS_EXTRAS_DB_PATH) as db:
                    record = await (await db.execute('SELECT horas_autorizadas, horas_preautorizadas, justificacion FROM he_eventos')).fetchone()
                    self.assertEqual(record, (1.75, 1.75, 'Cierre de descarga'))
                    history = await (await db.execute('SELECT detalle_json FROM he_historial ORDER BY historial_id DESC LIMIT 1')).fetchone()
                    self.assertIn('Cierre de descarga', history[0])

    def test_approval_mail_groups_by_sector_and_counts_unique_legajos(self):
        result = he._approval_mail([
            {'legajo': '10', 'sector': 'CD-NOA', 'horas_autorizadas': 1.5},
            {'legajo': '10', 'sector': 'CD-NOA', 'horas_autorizadas': 0.5},
            {'legajo': '11', 'sector': 'CD-NOA', 'horas_autorizadas': 1},
            {'legajo': '12', 'sector': 'CD-SUR', 'horas_autorizadas': 2},
        ], 'Nombre desde legajero', ['99'])
        self.assertIn('Aprobado por: Nombre desde legajero', result['body'])
        self.assertIn('CD-NOA: 2 legajos | 03:00 hs aprobadas', result['body'])
        self.assertIn('CD-SUR: 1 legajo | 02:00 hs aprobadas', result['body'])
        self.assertIn('Total: 3 legajos | 05:00 hs aprobadas', result['body'])
        self.assertEqual(result['body'].count('legajo |') + result['body'].count('legajos |'), 3)

    def test_normalization_preserves_zero_hours_after_adjustment(self):
        row = {'fecha': '2026-10-13', 'legajo': '1', 'hs_ext_realiz': 2}
        normalized = he._normalize_row(row, {'estado_actual': 'aprobada_gerente', 'horas_autorizadas': 0})
        self.assertEqual(normalized['horas_autorizadas'], 0)

    async def test_approver_name_comes_from_linked_legajo(self):
        with tempfile.TemporaryDirectory() as directory:
            auth_path = Path(directory) / 'auth.db'
            operational_path = Path(directory) / 'operational.db'
            async with aiosqlite.connect(auth_path) as db:
                await db.execute('CREATE TABLE auth_user_legajos (username TEXT, legajo TEXT)')
                await db.execute("INSERT INTO auth_user_legajos VALUES ('manager', '184548')")
                await db.commit()
            async with aiosqlite.connect(operational_path) as db:
                await db.execute('CREATE TABLE rrhh_legajero (legajo TEXT, nombre TEXT, batch_id INTEGER, id INTEGER)')
                await db.execute("INSERT INTO rrhh_legajero VALUES ('184548', 'Nombre Legajero', 2, 1)")
                await db.commit()
            with patch.object(he, 'AUTH_DB_PATH', auth_path), patch.object(he, 'OPERATIVA_DB_PATH', operational_path):
                name = await he._approver_legajero_name({'username': 'manager', 'display_name': 'Nombre de usuario'})
            self.assertEqual(name, 'Nombre Legajero')

    async def test_rrhh_adjustment_updates_hours_with_reason_and_reopens_sap_record(self):
        with tempfile.TemporaryDirectory() as directory:
            async def current(request, legajo, fecha):
                return {'legajo': legajo, 'fecha': fecha, 'empleado': 'Empleado', 'sector': 'CD-NOA',
                        'horas_extras_detectadas': 3, 'cargado_sap': 0}

            with patch.object(he, 'HORAS_EXTRAS_DB_PATH', Path(directory) / 'he.db'), \
                 patch.object(he, '_require_auth', AsyncMock(return_value={'username': 'hr'})), \
                 patch.object(he, '_access', AsyncMock(return_value={'profile': 'RRHH', 'scope': 'global'})), \
                 patch.object(he, '_find_current_row', current):
                payload = he.BulkAdjustmentRequest(rows=[he.AdjustmentRow(
                    legajo='1', fecha='2026-10-13', horas_autorizadas=1.5, motivo='Correccion RRHH')])
                result = await he.ajustar_registros(None, payload)
                self.assertEqual(result['guardadas'], 1)
                async with aiosqlite.connect(he.HORAS_EXTRAS_DB_PATH) as db:
                    await db.execute("UPDATE he_eventos SET estado_actual='cargada_sap',cargado_sap=1,sap_usuario='hr',sap_at='2026-10-14'")
                    await db.commit()
                payload = he.BulkAdjustmentRequest(rows=[he.AdjustmentRow(
                    legajo='1', fecha='2026-10-13', horas_autorizadas=2, motivo='Reajuste tras SAP')])
                result = await he.ajustar_registros(None, payload)
                self.assertEqual(result['rows'][0]['estado'], 'aprobada_gerente')
                async with aiosqlite.connect(he.HORAS_EXTRAS_DB_PATH) as db:
                    event = await (await db.execute('SELECT estado_actual,horas_autorizadas,cargado_sap,sap_usuario FROM he_eventos')).fetchone()
                    self.assertEqual(event, ('aprobada_gerente', 2.0, 0, None))
                    adjustments = await (await db.execute('SELECT COUNT(*),MAX(motivo) FROM he_ajustes WHERE estado=\'aplicado\'')).fetchone()
                    self.assertEqual(adjustments, (2, 'Reajuste tras SAP'))
                    history = await (await db.execute("SELECT COUNT(*) FROM he_historial WHERE accion='ajuste_rrhh'")).fetchone()
                    self.assertEqual(history[0], 2)
                decision = (await he._decisions([('1', '2026-10-13')]))[('1', '2026-10-13')]
                self.assertEqual(decision['ajuste_motivo'], 'Reajuste tras SAP')
                self.assertEqual(decision['usuario_cambio'], 'hr')

    async def test_non_rrhh_cannot_adjust_records(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(he, 'HORAS_EXTRAS_DB_PATH', Path(directory) / 'he.db'), \
                 patch.object(he, '_require_auth', AsyncMock(return_value={'username': 'manager'})), \
                 patch.object(he, '_access', AsyncMock(return_value={'profile': 'GERENTE', 'scope': 'sector'})):
                payload = he.BulkAdjustmentRequest(rows=[he.AdjustmentRow(
                    legajo='1', fecha='2026-10-13', horas_autorizadas=1, motivo='No autorizado')])
                with self.assertRaises(HTTPException) as error:
                    await he.ajustar_registros(None, payload)
                self.assertEqual(error.exception.status_code, 403)

    async def test_rrhh_profile_has_global_sector_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            auth_path = Path(directory) / 'auth.db'
            async with aiosqlite.connect(auth_path) as db:
                await db.execute('CREATE TABLE auth_user_app_access (username TEXT,module TEXT,profile TEXT,scope TEXT,sector TEXT,metadata_json TEXT,enabled INTEGER)')
                await db.execute("INSERT INTO auth_user_app_access VALUES ('hr','horas_extras','RRHH','sector','CD-NOA','{}',1)")
                await db.commit()
            with patch.object(he, 'AUTH_DB_PATH', auth_path):
                access = await he._access({'username': 'hr', 'role': 'user'})
            self.assertEqual(access['scope'], 'global')
            self.assertEqual(access['sectors'], [])


if __name__ == '__main__':
    unittest.main()
