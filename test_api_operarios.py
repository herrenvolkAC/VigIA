"""
Test API de Operarios - Valida los 5 nuevos endpoints
Ejecutar: python test_api_operarios.py

Nota: El servidor debe estar corriendo (python main.py)
"""
import asyncio
import aiosqlite
from pathlib import Path
from routers.analisis_inteligente import (
    analizar_caida_progresiva,
    analizar_correlacion_sku_operario,
    analizar_patron_semanal,
    analizar_recuperacion_pausa,
    analizar_anomalia_zscore,
    ejecutar_todos_analisis
)

DB_PATH = Path(__file__).parent / "vigia.db"


async def test_apis():
    """Test directo a las funciones de análisis"""

    print("\n" + "="*70)
    print("[TEST] API DE OPERARIOS - 5 ANALISIS INTELIGENTES")
    print("="*70 + "\n")

    # Obtener un operario y ola para test
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("SELECT operario_id FROM operarios LIMIT 1")
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

    tests_pasados = 0
    tests_totales = 5

    # Test 1: Caída Progresiva
    print("[TEST 1] analizar_caida_progresiva")
    try:
        resultado = await analizar_caida_progresiva(operario_id, ola_id)
        if "error" not in resultado:
            print(f"  [OK] Detectado: {resultado.get('detectado')}")
            if resultado.get('detectado'):
                print(f"       Caida: {resultado.get('caida_pct')}%")
                print(f"       Severidad: {resultado.get('severidad')}")
            tests_pasados += 1
        else:
            print(f"  [FAIL] {resultado['error']}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Test 2: Correlación SKU x Operario
    print("\n[TEST 2] analizar_correlacion_sku_operario")
    try:
        resultado = await analizar_correlacion_sku_operario(operario_id, dias=30)
        if "error" not in resultado:
            print(f"  [OK] Especialidad: {resultado.get('especialidad_pct')}%")
            print(f"       SKUs expertos: {len(resultado.get('skus_expertos', []))}")
            print(f"       SKUs débiles: {len(resultado.get('skus_debiles', []))}")
            tests_pasados += 1
        else:
            print(f"  [FAIL] {resultado['error']}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Test 3: Patrón Semanal
    print("\n[TEST 3] analizar_patron_semanal")
    try:
        resultado = await analizar_patron_semanal(operario_id)
        if "error" not in resultado:
            print(f"  [OK] Detectado: {resultado.get('detectado')}")
            print(f"       Día fuerte: {resultado.get('dia_mas_fuerte')}")
            print(f"       Día débil: {resultado.get('dia_mas_debil')}")
            print(f"       Variación: {resultado.get('variacion_pct')}%")
            tests_pasados += 1
        else:
            print(f"  [FAIL] {resultado['error']}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Test 4: Recuperación Post-Pausa
    print("\n[TEST 4] analizar_recuperacion_pausa")
    try:
        resultado = await analizar_recuperacion_pausa(operario_id)
        if "error" not in resultado:
            print(f"  [OK] Detectado: {resultado.get('detectado')}")
            print(f"       Pausas analizadas: {resultado.get('pausas_analizadas')}")
            print(f"       Pausas efectivas: {resultado.get('pausas_efectivas')}")
            print(f"       Recuperación promedio: {resultado.get('promedio_recuperacion_pct')}%")
            if resultado.get('mejor_tipo_pausa'):
                print(f"       Mejor tipo: {resultado.get('mejor_tipo_pausa')}")
            tests_pasados += 1
        else:
            print(f"  [FAIL] {resultado['error']}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Test 5: Anomalía Z-Score
    print("\n[TEST 5] analizar_anomalia_zscore")
    try:
        resultado = await analizar_anomalia_zscore(operario_id, ola_id)
        if "error" not in resultado:
            print(f"  [OK] Detectado: {resultado.get('detectado')}")
            print(f"       Vel promedio: {resultado.get('velocidad_promedio_seg')} seg")
            print(f"       Desv estándar: {resultado.get('desv_estandar_seg')} seg")
            print(f"       Picks anómalos: {resultado.get('picks_anomalos')}")
            print(f"       Confianza: {resultado.get('confianza_pct')}%")
            tests_pasados += 1
        else:
            print(f"  [FAIL] {resultado['error']}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Test Bonus: Análisis Completo
    print("\n[TEST BONUS] ejecutar_todos_analisis")
    try:
        resultado = await ejecutar_todos_analisis(operario_id, ola_id)
        print(f"  [OK] Análisis completo ejecutado")
        print(f"       Timestamp: {resultado.get('timestamp')}")
        print(f"       Análisis incluidos: {len(resultado.get('analisis', {}))}")
        for tipo in resultado.get('analisis', {}):
            print(f"         - {tipo}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Resumen
    print("\n" + "="*70)
    print(f"RESUMEN: {tests_pasados}/{tests_totales} tests pasados")
    if tests_pasados == tests_totales:
        print("[SUCCESS] Todos los análisis inteligentes funcionan")
    else:
        print(f"[WARNING] {tests_totales - tests_pasados} test(s) fallaron")
    print("="*70 + "\n")

    return tests_pasados == tests_totales


if __name__ == "__main__":
    success = asyncio.run(test_apis())
    exit(0 if success else 1)
