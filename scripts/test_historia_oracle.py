"""Run: python -m unittest scripts.test_historia_oracle"""
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch
from fastapi import Response, HTTPException
from routers import historia_oracle as h

class HistoriaTests(unittest.IsolatedAsyncioTestCase):
    def test_period_validation(self):
        for start,end in [(date(2026,8,2),date(2026,8,1)),(date(2020,1,1),date(2026,1,1))]:
            with self.assertRaises(HTTPException): h.period(start,end)
        self.assertEqual(h.period(date(2026,8,1),date(2026,8,31)),{'desde':20260801,'hasta':20260831})

    async def test_independent_grains_and_no_local_fallback(self):
        async def fake(sql, binds):
            if 'FROM PV_LEGAJO' in sql: return [{'LEGAJO':'123','NOMBRE':'Prueba'}]
            if 'SELECT D.*' in sql: return [{'ID':1,'FECHA':20260801,'PREMIO':30}]
            if 'SELECT E.*' in sql: return []
            if 'JOIN PV_LIQUIDAC_DIA_DET1' in sql: return [{'ID':11,'A_PAGAR_TOTAL':10},{'ID':12,'A_PAGAR_TOTAL':20}]
            if 'JOIN PV_LIQUIDAC_DIA_DET2' in sql: return [{'ID':21,'PROD_REAL':100}]
            self.fail(sql)
        response=Response()
        with patch.object(h,'query',side_effect=fake) as q:
            r=await h.resumen(response,'123',date(2026,8,1),date(2026,8,31))
        self.assertEqual(sum(x['A_PAGAR_TOTAL'] for x in r['pagos']),30)
        self.assertEqual(sum(x['PROD_REAL'] for x in r['produccion']),100)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertTrue(all('DET2' not in c.args[0] or 'DET1' not in c.args[0] for c in q.call_args_list))

    async def test_search_is_bound_and_limited(self):
        with patch.object(h,'query',new_callable=AsyncMock,return_value=[]) as q:
            await h.buscar(Response(),"O'NEIL")
            sql,binds=q.call_args.args
        self.assertNotIn("O'NEIL",sql)
        self.assertEqual(binds['nombre'],"%O'NEIL%")
        self.assertIn('ROWNUM<=25',sql)

    async def test_movements_pagination_and_person_scope(self):
        with patch.object(h,'query',new_callable=AsyncMock,return_value=[{'ID':i} for i in range(101)]) as q:
            result=await h.movimientos(Response(),'123',9,100)
        self.assertEqual(len(result['rows']),100)
        self.assertTrue(result['has_more'])
        sql,binds=q.call_args.args
        self.assertIn('A.LEGAJO=:legajo',sql)
        self.assertEqual(binds,{'etapa':9,'legajo':'123','inicio':100,'fin':201})

    async def test_oracle_error_is_service_unavailable(self):
        with patch.object(h,'_query_oracle_via_jdbc',side_effect=RuntimeError('offline')):
            with self.assertRaises(HTTPException) as ctx: await h.query('SELECT 1 FROM DUAL',{})
        self.assertEqual(ctx.exception.status_code,503)
        self.assertNotIn('offline',ctx.exception.detail)
        self.assertNotIn('oracle',ctx.exception.detail.lower())


    async def test_protected_routes_and_new_page(self):
        import httpx
        import main
        from routers.auth_local import APP_MODULE_IDS
        self.assertIn('historia_legajo', APP_MODULE_IDS)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
            with patch.object(main,'current_auth',new_callable=AsyncMock,return_value=None), patch.object(main,'write_usage_log'):
                r=await client.get('/api/historia-legajo/oracle/resumen?legajo=123&desde=2026-08-01&hasta=2026-08-31')
                self.assertEqual(r.status_code,401)
            auth={'username':'qa','role':'user','device_status':'approved'}
            with patch.object(main,'current_auth',new_callable=AsyncMock,return_value=auth), patch.object(main,'user_has_module_access',new_callable=AsyncMock,return_value=False), patch.object(main,'write_usage_log'):
                r=await client.get('/api/historia-legajo/oracle/buscar?q=123')
                self.assertEqual(r.status_code,403)
            with patch.object(main,'current_auth',new_callable=AsyncMock,return_value=auth), patch.object(main,'user_has_module_access',new_callable=AsyncMock,return_value=True), patch.object(main,'write_usage_log'), patch.object(h,'query',new_callable=AsyncMock,return_value=[]):
                r=await client.get('/api/historia-legajo/oracle/buscar?q=123')
                self.assertEqual(r.status_code,200)
                self.assertEqual(r.json(),{'rows':[]})
                r=await client.get('/historia-legajo.html')
                self.assertEqual(r.status_code,200)
                self.assertIn('historia_operario.js',r.text)
                r=await client.get('/api/historia-legajo/oracle/resumen?legajo=bad&desde=2026-08-01&hasta=2026-08-31')
                self.assertEqual(r.status_code,422)

if __name__=='__main__': unittest.main()
