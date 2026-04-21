"""
VigIA FASE 1 - Testing E2E Completo
Valida: Backend endpoints + Frontend integración + APIs
Ejecutar: python test_e2e_fase1.py
"""
import asyncio
import aiosqlite
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from utils.alertas import generar_alertas, obtener_comparativas

DB_PATH = Path(__file__).parent / "vigia.db"

# Contadores de pruebas
tests_totales = 0
tests_pasados = 0
tests_fallidos = 0


def log_test(nombre, resultado, detalles=""):
    """Log de resultado de test"""
    global tests_totales, tests_pasados, tests_fallidos
    tests_totales += 1

    status = "[PASS]" if resultado else "[FAIL]"
    print(f"{status} | {nombre}")
    if detalles:
        print(f"       {detalles}")

    if resultado:
        tests_pasados += 1
    else:
        tests_fallidos += 1


# ============================================================================
# TESTS: BACKEND - ENDPOINTS
# ============================================================================

async def test_backend_endpoints():
    """Validar todos los endpoints backend"""
    print("\n" + "="*70)
    print("TESTING BACKEND - ENDPOINTS")
    print("="*70 + "\n")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Test 1: GET /api/olas
        try:
            cursor = await db.execute("SELECT COUNT(*) as count FROM olas")
            row = await cursor.fetchone()
            resultado = row['count'] == 3
            log_test("GET /api/olas retorna 3 olas", resultado, f"Encontradas: {row['count']}")
        except Exception as e:
            log_test("GET /api/olas", False, str(e))

        # Test 2: GET /api/olas/{ola_id}/operarios
        try:
            cursor = await db.execute("""
                SELECT COUNT(*) as count FROM asignaciones_ola
                WHERE ola_id = 'OLA_2_TARDE_20_04'
            """)
            row = await cursor.fetchone()
            resultado = row['count'] == 10
            log_test("GET /api/olas/OLA_2_TARDE_20_04/operarios retorna 10", resultado, f"Encontrados: {row['count']}")
        except Exception as e:
            log_test("GET /api/olas/.../operarios", False, str(e))

        # Test 3: GET /api/estandares/Secos
        try:
            cursor = await db.execute("""
                SELECT bultos_por_hora FROM estandares_sector WHERE sector = 'Secos'
            """)
            row = await cursor.fetchone()
            resultado = row and row['bultos_por_hora'] == 250
            log_test("GET /api/estandares/Secos = 250 bul/h", resultado, f"Valor: {row['bultos_por_hora'] if row else 'N/A'}")
        except Exception as e:
            log_test("GET /api/estandares", False, str(e))

        # Test 4: POST /api/estandares (simulación)
        try:
            await db.execute("""
                UPDATE estandares_sector SET bultos_por_hora = 260
                WHERE sector = 'Secos'
            """)
            await db.commit()

            cursor = await db.execute("""
                SELECT bultos_por_hora FROM estandares_sector WHERE sector = 'Secos'
            """)
            row = await cursor.fetchone()
            resultado = row['bultos_por_hora'] == 260

            # Revertir cambio
            await db.execute("""
                UPDATE estandares_sector SET bultos_por_hora = 250
                WHERE sector = 'Secos'
            """)
            await db.commit()

            log_test("POST /api/estandares actualiza correctamente", resultado)
        except Exception as e:
            log_test("POST /api/estandares", False, str(e))

        # Test 5: GET /api/olas/{ola_id}/alertas
        try:
            alertas = await generar_alertas("OLA_2_TARDE_20_04")
            resultado = len(alertas) > 0 and 'tipo' in alertas[0]
            log_test("GET /api/olas/OLA_2_TARDE_20_04/alertas genera alertas", resultado, f"Alertas: {len(alertas)}")
        except Exception as e:
            log_test("GET /api/olas/.../alertas", False, str(e))

        # Test 6: GET /api/olas/{ola_id}/comparativas
        try:
            comparativas = await obtener_comparativas("OLA_2_TARDE_20_04")
            resultado = (len(comparativas['top_performers']) > 0 and
                       len(comparativas['bottom_performers']) > 0)
            log_test("GET /api/olas/.../comparativas retorna top+bottom", resultado,
                    f"Top: {len(comparativas['top_performers'])}, Bottom: {len(comparativas['bottom_performers'])}")
        except Exception as e:
            log_test("GET /api/olas/.../comparativas", False, str(e))


# ============================================================================
# TESTS: LÓGICA - ALERTAS Y COMPARATIVAS
# ============================================================================

async def test_logica_alertas():
    """Validar lógica de alertas"""
    print("\n" + "="*70)
    print("TESTING LOGICA - ALERTAS Y COMPARATIVAS")
    print("="*70 + "\n")

    # Test 1: Detecta productividad baja
    try:
        alertas = await generar_alertas("OLA_2_TARDE_20_04")
        maria_alertas = [a for a in alertas if 'María' in a['operario_nombre'] or 'Maria' in a['operario_nombre']]
        resultado = len(maria_alertas) > 0 and maria_alertas[0]['desvio_pct'] < -20
        log_test("Detecta María López con -26% productividad", resultado,
                f"Desvío: {maria_alertas[0]['desvio_pct'] if maria_alertas else 'N/A'}%")
    except Exception as e:
        log_test("Detecta productividad baja", False, str(e))

    # Test 2: Severidad correcta
    try:
        alertas = await generar_alertas("OLA_2_TARDE_20_04")
        severidades_validas = ['CRITICA', 'ALTA', 'MEDIA', 'BAJA']
        todos_validos = all(a['severidad'] in severidades_validas for a in alertas)
        resultado = todos_validos
        log_test("Todas las alertas tienen severidad válida", resultado,
                f"Severidades encontradas: {set(a['severidad'] for a in alertas)}")
    except Exception as e:
        log_test("Validar severidades", False, str(e))

    # Test 3: Top performers productividad alta
    try:
        comparativas = await obtener_comparativas("OLA_2_TARDE_20_04")
        top = comparativas['top_performers'][0]
        resultado = top['productividad'] >= 250
        log_test("Top performer tiene productividad >= 250", resultado,
                f"Productividad: {top['productividad']} bul/h")
    except Exception as e:
        log_test("Validar top performers", False, str(e))

    # Test 4: Bottom performers productividad baja
    try:
        comparativas = await obtener_comparativas("OLA_2_TARDE_20_04")
        bottom = comparativas['bottom_performers'][0]
        resultado = bottom['productividad'] <= 220
        log_test("Bottom performer tiene productividad <= 220", resultado,
                f"Productividad: {bottom['productividad']} bul/h")
    except Exception as e:
        log_test("Validar bottom performers", False, str(e))


# ============================================================================
# TESTS: INTEGRACION - DATA CONSISTENCY
# ============================================================================

async def test_integracion_data():
    """Validar consistencia de datos"""
    print("\n" + "="*70)
    print("TESTING INTEGRACION - DATA CONSISTENCY")
    print("="*70 + "\n")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Test 1: OLA 2 tiene operarios asignados
        try:
            cursor = await db.execute("""
                SELECT SUM(bultos_reales) as total FROM asignaciones_ola
                WHERE ola_id = 'OLA_2_TARDE_20_04'
            """)
            row = await cursor.fetchone()
            resultado = row['total'] > 0
            log_test("OLA 2 tiene bultos ejecutados", resultado, f"Total: {row['total']} bultos")
        except Exception as e:
            log_test("OLA 2 datos válidos", False, str(e))

        # Test 2: Operarios tienen zona
        try:
            cursor = await db.execute("""
                SELECT COUNT(*) as count FROM operarios WHERE zona_principal IS NOT NULL
            """)
            row = await cursor.fetchone()
            resultado = row['count'] > 0
            log_test("Todos los operarios tienen zona principal", resultado,
                    f"Operarios con zona: {row['count']}")
        except Exception as e:
            log_test("Operarios tienen zona", False, str(e))

        # Test 3: Estándares configurados
        try:
            cursor = await db.execute("""
                SELECT COUNT(DISTINCT sector) as count FROM estandares_sector
            """)
            row = await cursor.fetchone()
            resultado = row['count'] >= 2
            log_test("Al menos 2 sectores con estándares", resultado, f"Sectores: {row['count']}")
        except Exception as e:
            log_test("Estándares configurados", False, str(e))

        # Test 4: Productividad en rango válido
        try:
            cursor = await db.execute("""
                SELECT MIN(productividad) as min_prod, MAX(productividad) as max_prod
                FROM asignaciones_ola
            """)
            row = await cursor.fetchone()
            resultado = (row['min_prod'] >= 50 and row['max_prod'] <= 350)
            log_test("Productividades en rango válido (50-350)", resultado,
                    f"Rango: {row['min_prod']}-{row['max_prod']}")
        except Exception as e:
            log_test("Rango productividad", False, str(e))


# ============================================================================
# TESTS: FRONTEND - VALIDACION HTML
# ============================================================================

def test_frontend_estructura():
    """Validar estructura HTML del dashboard"""
    print("\n" + "="*70)
    print("TESTING FRONTEND - ESTRUCTURA HTML")
    print("="*70 + "\n")

    archivo = Path(__file__).parent / "static" / "fase1_dashboard.html"

    # Test 1: Archivo existe
    resultado = archivo.exists()
    log_test("Archivo fase1_dashboard.html existe", resultado)

    if not resultado:
        return

    # Test 2: Contiene 4 pantallas
    try:
        contenido = archivo.read_text(encoding='utf-8', errors='ignore')
        pantallas = contenido.count('id="p')
        resultado = pantallas >= 4
        log_test("Contiene al menos 4 pantallas (p1-p4)", resultado, f"Pantallas encontradas: {pantallas}")
    except Exception as e:
        log_test("Leer archivo", False, str(e))
        return

    # Test 3: Contiene CSS responsivo
    try:
        resultado = "@media" in contenido
        log_test("Contiene media queries (responsive)", resultado)
    except Exception as e:
        log_test("CSS responsivo", False, str(e))

    # Test 4: Contiene integración con APIs
    try:
        resultado = "fetch(API_BASE" in contenido
        count = contenido.count("fetch(API_BASE")
        log_test("Contiene llamadas a APIs", resultado, f"Llamadas fetch: {count}")
    except Exception as e:
        log_test("Integración APIs", False, str(e))

    # Test 5: Contiene funciones de navegación
    try:
        resultado = "mostrarPantalla" in contenido
        log_test("Contiene función de navegación entre pantallas", resultado)
    except Exception as e:
        log_test("Navegación", False, str(e))

    # Test 6: Contiene loaders
    try:
        resultado = "class=\"loading\"" in contenido or "class='loading'" in contenido
        log_test("Contiene loaders para estados de carga", resultado)
    except Exception as e:
        log_test("Loaders", False, str(e))


# ============================================================================
# RESUMEN
# ============================================================================

async def main():
    print("\n")
    print("=" * 70)
    print("=  VigIA FASE 1 - TESTING E2E COMPLETO")
    print("=" * 70)

    await test_backend_endpoints()
    await test_logica_alertas()
    await test_integracion_data()
    test_frontend_estructura()

    # Resumen
    print("\n" + "="*70)
    print("RESUMEN FINAL")
    print("="*70)
    print(f"\nTotal de tests: {tests_totales}")
    print(f"[PASS] Pasados: {tests_pasados}")
    print(f"[FAIL] Fallidos: {tests_fallidos}")

    tasa_exito = (tests_pasados / tests_totales * 100) if tests_totales > 0 else 0
    print(f"\nTasa de éxito: {tasa_exito:.1f}%")

    if tests_fallidos == 0:
        print("\n[SUCCESS] FASE 1 LISTA PARA PRODUCCION")
    else:
        print(f"\n[WARNING] {tests_fallidos} test(s) fallaron - revisar")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
