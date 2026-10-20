import sqlite3
import tempfile
import unittest
import asyncio
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from scripts import cargar_tnc_resumen as loader
from utils import tnc_scheduler as scheduler


class TncSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.db'
        self.patches = [patch.object(loader, 'DB_PATH', self.path), patch.object(scheduler, 'DB_PATH', self.path),
                        patch.object(loader, 'query_productive_db_tnc_master', return_value=[])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    @staticmethod
    def event(day, minutes=5):
        return {'DIA_TNC': day, 'LEGAJO': '10', 'CODIGO_TNC': '1', 'MINUTOS': minutes,
                'ESTADO': 'finalizado', 'EMPRESA': '1', 'ALMACEN': '1'}

    def test_backfill_refresh_and_retry(self):
        calls = []
        def source(start, end):
            day = start[:10]
            calls.append(day)
            return [self.event(day, 12)]
        now = datetime(2026, 10, 5, 6, tzinfo=scheduler.ARGENTINA)
        with patch.object(loader, 'query_productive_db_tnc_monitor', side_effect=source):
            self.assertEqual(scheduler.run_once(now), 'cargado')
            self.assertEqual(len(calls), 4)
            self.assertEqual(scheduler.run_once(now), 'completo')
            self.assertEqual(scheduler.run_once(datetime(2026, 10, 6, 6, tzinfo=scheduler.ARGENTINA)), 'cargado')
        self.assertEqual(calls[4:], ['2026-10-03', '2026-10-04', '2026-10-05'])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tnc_resumen_sync').fetchone()[0], 5)
            self.assertEqual(db.execute('SELECT count(*) FROM tnc_resumen_diario').fetchone()[0], 5)

    def test_failed_refresh_preserves_previous_day_and_allows_retry(self):
        with patch.object(loader, 'query_productive_db_tnc_monitor', return_value=[self.event('2026-10-01')]):
            loader.load(date(2026, 10, 1), date(2026, 10, 1))
        now = datetime(2026, 10, 2, 6, tzinfo=scheduler.ARGENTINA)
        with patch.object(loader, 'query_productive_db_tnc_monitor', side_effect=RuntimeError('Oracle caído')):
            with self.assertRaises(RuntimeError):
                scheduler.run_once(now)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT minutos_total FROM tnc_resumen_diario').fetchone()[0], 5)
            self.assertEqual(db.execute('SELECT count(*) FROM tnc_resumen_sync').fetchone()[0], 1)
            self.assertIn('Oracle caído', db.execute('SELECT last_error FROM tnc_job_control').fetchone()[0])
        with patch.object(loader, 'query_productive_db_tnc_monitor', return_value=[self.event('2026-10-01', 9)]):
            self.assertEqual(scheduler.run_once(now), 'cargado')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT minutos_total FROM tnc_resumen_diario').fetchone()[0], 9)

    def test_scheduler_only_starts_in_production(self):
        async def check():
            for environment in ('test', '', 'development'):
                with patch.dict('os.environ', {'VIGIA_APP_ENV': environment, 'TNC_SCHEDULER_ENABLED': '1'}):
                    scheduler.start_tnc_scheduler()
                    self.assertIsNone(scheduler._task)
            with patch.dict('os.environ', {'VIGIA_APP_ENV': 'production', 'TNC_SCHEDULER_ENABLED': '1'}):
                scheduler.start_tnc_scheduler()
                self.assertIsNotNone(scheduler._task)
                await scheduler.stop_tnc_scheduler()
        asyncio.run(check())

    def test_daily_excess_uses_total_and_preserves_unknown(self):
        master = [{'CODIGO_TNC': '1', 'DURACION_MINUTOS_PRODUCTIVIDAD': 30,
                   'TIENE_TIEMPO_MAXIMO': 'SI'}]
        events = [self.event('2026-10-01', 20), self.event('2026-10-01', 11)]
        with patch.object(loader, 'query_productive_db_tnc_master', return_value=master), \
             patch.object(loader, 'query_productive_db_tnc_monitor', return_value=events):
            loader.load(date(2026, 10, 1), date(2026, 10, 1))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT minutos_total, minutos_maximos, excedido FROM tnc_excesos_diarios').fetchone(), (31, 30, 1))
            db.execute('UPDATE tnc_resumen_diario SET minutos_total=30')
            self.assertEqual(db.execute('SELECT excedido FROM tnc_excesos_diarios').fetchone()[0], 0)
            db.execute('UPDATE tnc_resumen_diario SET activos=1')
            self.assertIsNone(db.execute('SELECT excedido FROM tnc_excesos_diarios').fetchone()[0])
            db.execute('UPDATE tnc_resumen_diario SET activos=0, minutos_maximos=NULL')
            self.assertIsNone(db.execute('SELECT excedido FROM tnc_excesos_diarios').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
