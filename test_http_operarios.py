"""
Test HTTP API de Operarios
Valida los endpoints cuando el servidor está corriendo

Ejecutar: python main.py (en otra terminal)
Luego: python test_http_operarios.py

Endpoints a testear:
GET /api/operarios
GET /api/operarios/{operario_id}
GET /api/operarios/{operario_id}/analisis/caida_progresiva?ola_id=X
GET /api/operarios/{operario_id}/analisis/correlacion_sku
GET /api/operarios/{operario_id}/analisis/patron_semanal
GET /api/operarios/{operario_id}/analisis/recuperacion_pausa
GET /api/operarios/{operario_id}/analisis/anomalia_zscore
GET /api/operarios/{operario_id}/analisis/completo
"""
import asyncio
import aiohttp
import aiosqlite
from pathlib import Path
import json

DB_PATH = Path(__file__).parent / "vigia.db"
BASE_URL = "http://localhost:8080/api"

tests_pasados = 0
tests_totales = 0


async def test_endpoint(nombre, url, esperado_status=200):
    """Test un endpoint HTTP"""
    global tests_totales, tests_pasados
    tests_totales += 1

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == esperado_status:
                    data = await resp.json()
                    print(f"[OK] {nombre}")
                    tests_pasados += 1
                    return True, data
                else:
                    print(f"[FAIL] {nombre} - Status {resp.status}")
                    return False, None
    except Exception as e:
        print(f"[FAIL] {nombre} - {e}")
        return False, None


async def main():
    print("\n" + "="*70)
    print("[TEST] HTTP API - ENDPOINTS DE OPERARIOS")
    print("="*70 + "\n")

    # Obtener operario de test
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("""
            SELECT operario_id FROM operarios LIMIT 1
        """)
        row = await cursor.fetchone()
        operario_id = row['operario_id'] if row else None

        cursor = await db.execute("SELECT ola_id FROM olas LIMIT 1")
        row = await cursor.fetchone()
        ola_id = row['ola_id'] if row else None

    if not operario_id or not ola_id:
        print("[ERROR] No hay operarios u olas en BD")
        return False

    print(f"Operario test: {operario_id}")
    print(f"Ola test: {ola_id}\n")

    # Test 1: Listado de operarios
    print("[TEST GROUP] Operarios")
    ok, data = await test_endpoint(
        "GET /api/operarios",
        f"{BASE_URL}/operarios"
    )
    if ok and data:
        print(f"  -> {data['total_operarios']} operarios encontrados")

    # Test 2: Detalle operario
    ok, data = await test_endpoint(
        f"GET /api/operarios/{operario_id}",
        f"{BASE_URL}/operarios/{operario_id}"
    )
    if ok and data:
        print(f"  -> Nombre: {data.get('nombre')}")
        print(f"  -> Total picks: {data.get('estadisticas', {}).get('total_picks')}")

    # Test 3: Caída Progresiva
    print("\n[TEST GROUP] Analisis Inteligentes")
    ok, data = await test_endpoint(
        f"GET caida_progresiva",
        f"{BASE_URL}/operarios/{operario_id}/analisis/caida_progresiva?ola_id={ola_id}"
    )
    if ok and data:
        print(f"  -> Detectado: {data.get('detectado')}")
        if data.get('detectado'):
            print(f"  -> Caida: {data.get('caida_pct')}%")

    # Test 4: Correlación SKU
    ok, data = await test_endpoint(
        f"GET correlacion_sku",
        f"{BASE_URL}/operarios/{operario_id}/analisis/correlacion_sku?dias=30"
    )
    if ok and data:
        print(f"  -> Especialidad: {data.get('especialidad_pct')}%")

    # Test 5: Patrón Semanal
    ok, data = await test_endpoint(
        f"GET patron_semanal",
        f"{BASE_URL}/operarios/{operario_id}/analisis/patron_semanal"
    )
    if ok and data:
        print(f"  -> Variación: {data.get('variacion_pct')}%")

    # Test 6: Recuperación Post-Pausa
    ok, data = await test_endpoint(
        f"GET recuperacion_pausa",
        f"{BASE_URL}/operarios/{operario_id}/analisis/recuperacion_pausa"
    )
    if ok and data:
        print(f"  -> Pausas analizadas: {data.get('pausas_analizadas')}")

    # Test 7: Anomalía Z-Score
    ok, data = await test_endpoint(
        f"GET anomalia_zscore",
        f"{BASE_URL}/operarios/{operario_id}/analisis/anomalia_zscore?ola_id={ola_id}"
    )
    if ok and data:
        print(f"  -> Picks anómalos: {data.get('picks_anomalos')}")

    # Test 8: Análisis Completo
    ok, data = await test_endpoint(
        f"GET analisis/completo",
        f"{BASE_URL}/operarios/{operario_id}/analisis/completo?ola_id={ola_id}"
    )
    if ok and data:
        print(f"  -> Análisis incluidos: {len(data.get('analisis', {}))}")

    # Resumen
    print("\n" + "="*70)
    print(f"RESUMEN: {tests_pasados}/{tests_totales} endpoints pasados")
    if tests_pasados == tests_totales:
        print("[SUCCESS] Todos los endpoints HTTP funcionan correctamente")
    else:
        print(f"[WARNING] {tests_totales - tests_pasados} endpoint(s) fallaron")
        print("\nNota: Asegúrate que el servidor esté corriendo:")
        print("  python main.py")
    print("="*70 + "\n")

    return tests_pasados == tests_totales


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[ABORTED] Test interrupted")
        exit(1)
