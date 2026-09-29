"""Regresión: fecha del hecho independiente de importaciones RRHH."""
import asyncio
from contextlib import contextmanager
from datetime import date
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import schema
from routers import rrhh_novedades as r
from starlette.requests import Request

@contextmanager
def connection(path):
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()

class SancionHechosTest(unittest.IsolatedAsyncioTestCase):
    async def test_reimportacion_actividad_auditoria_y_conflictos(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.db'
            with connection(path) as db:
                for name in ['IMPORT_BATCHES','LEGAJERO','ACTIVIDAD','SANCIONES','SANCION_HECHOS','SANCION_HECHOS_AUDIT']:
                    db.execute(getattr(schema, 'CREATE_RRHH_' + name))
                db.execute("INSERT INTO rrhh_import_batches(batch_key,source_dir) VALUES ('test','test')")
                db.execute("INSERT INTO rrhh_sanciones(batch_id,legajo,nombre,creacion,descripcion,cod) VALUES (1,'123','Persona','2026-09-29','Apercibimiento','A')")
                db.execute("INSERT INTO rrhh_actividad_diaria(batch_id,legajo,fecha) VALUES (1,'123','2026-09-24')")
            req = Request({'type':'http','query_string':b'', 'headers':[]})
            auth = {'role': next(iter(r.FULL_ACCESS_ROLES)), 'username':'test'}
            with patch.object(r,'DB_PATH',path), patch.object(r,'_require_auth',AsyncMock(return_value=auth)):
                rows = (await r.get_sanciones(req,limit=100))['rows']
                row = rows[0]
                payload = r.SancionHechoRequest(source_id=row['source_id'],sancion_key=row['sancion_key'],fecha_hecho=date(2026,9,24))
                await r.save_sancion_hecho(payload,req)
                with self.assertRaises(r.HTTPException) as error:
                    await r.save_sancion_hecho(payload,req)
                self.assertEqual(error.exception.status_code,409)
                activity = (await r.get_actividad(req,limit=100))['rows']
                self.assertEqual(len(activity),1)
                self.assertIn('Apercibimiento',activity[0]['sanciones_asociadas'])
                filtered = await r.get_sanciones(req,limit=100,criterio_fecha='hecho',fecha_desde='2026-09-24',fecha_hasta='2026-09-24')
                self.assertEqual(len(filtered['rows']),1)
                with connection(path) as db:
                    db.execute('DELETE FROM rrhh_sanciones')
                pending = (await r.get_sanciones(req,limit=100))['rows'][0]
                self.assertEqual(pending['fecha_hecho'],'2026-09-24')
                self.assertEqual(pending['pendiente_revision'],1)
                with connection(path) as db:
                    db.execute("INSERT INTO rrhh_sanciones(batch_id,legajo,nombre,creacion,descripcion,cod) VALUES (1,'123','Persona','2026-09-29','Apercibimiento','A')")
                restored = (await r.get_sanciones(req,limit=100))['rows']
                self.assertEqual(len(restored),1)
                self.assertEqual(restored[0]['fecha_hecho'],'2026-09-24')
                self.assertEqual(restored[0]['pendiente_revision'],0)
                with connection(path) as db:
                    db.execute("INSERT INTO rrhh_sanciones(batch_id,legajo,nombre,creacion,descripcion,cod) VALUES (1,'123','Persona','2026-09-29','Suspensión','B')")
                second = next(item for item in (await r.get_sanciones(req,limit=100))['rows'] if item['cod']=='B')
                await r.save_sancion_hecho(r.SancionHechoRequest(source_id=second['source_id'],sancion_key=second['sancion_key'],fecha_hecho=date(2026,9,24)),req)
                activity = (await r.get_actividad(req,limit=100))['rows']
                self.assertEqual(len(activity),1)
                self.assertIn('Suspensión',activity[0]['sanciones_asociadas'])
                with connection(path) as db:
                    db.execute("UPDATE rrhh_sanciones SET descripcion='Suspensión corregida' WHERE cod='B'")
                changed = (await r.get_sanciones(req,limit=100))['rows']
                self.assertEqual(sum(item['pendiente_revision'] for item in changed),1)
                self.assertIn('Pendiente de revisión',(await r.get_actividad(req,limit=100))['rows'][0]['sanciones_asociadas'])
                await r.save_sancion_hecho(r.SancionHechoRequest(sancion_key=second['sancion_key'],version=1,fecha_hecho=None),req)
                row=restored[0]
                await r.save_sancion_hecho(r.SancionHechoRequest(source_id=row['source_id'],sancion_key=row['sancion_key'],version=1,fecha_hecho=None),req)
                self.assertIsNone((await r.get_actividad(req,limit=100))['rows'][0]['sanciones_asociadas'])
                with connection(path) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM rrhh_sancion_hechos_audit').fetchone()[0],4)
            with patch.object(r,'_require_auth',AsyncMock(return_value={'role':'sin_permiso'})):
                with self.assertRaises(r.HTTPException) as error:
                    await r.save_sancion_hecho(payload,req)
                self.assertEqual(error.exception.status_code,403)

if __name__ == '__main__':
    unittest.main()
