"""
VigIA · tests_phase1.py
Tests para endpoints FASE 1: Alarmas + Productividad
Ejecutar: pytest tests_phase1.py -v
"""
import pytest
import asyncio
import aiosqlite
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from utils.alertas import generar_alertas, obtener_comparativas

DB_PATH = Path(__file__).parent / "vigia.db"


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
async def db():
    """Conexión a base de datos para tests."""
    async with aiosqlite.connect(DB_PATH) as connection:
        connection.row_factory = aiosqlite.Row
        yield connection


# ============================================================================
# TESTS: TABLAS Y DATOS
# ============================================================================

@pytest.mark.asyncio
async def test_tabla_olas_existe():
    """Verificar que tabla olas existe con datos."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT COUNT(*) as count FROM olas")
        row = await cursor.fetchone()
        assert row['count'] > 0, "Tabla olas debe tener datos"


@pytest.mark.asyncio
async def test_tabla_operarios_existe():
    """Verificar que tabla operarios existe con datos."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT COUNT(*) as count FROM operarios")
        row = await cursor.fetchone()
        assert row['count'] > 0, "Tabla operarios debe tener datos"


@pytest.mark.asyncio
async def test_tabla_asignaciones_ola_existe():
    """Verificar que tabla asignaciones_ola existe con datos."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT COUNT(*) as count FROM asignaciones_ola")
        row = await cursor.fetchone()
        assert row['count'] > 0, "Tabla asignaciones_ola debe tener datos"


@pytest.mark.asyncio
async def test_tabla_estandares_existe():
    """Verificar que tabla estandares_sector existe con datos."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT COUNT(*) as count FROM estandares_sector")
        row = await cursor.fetchone()
        assert row['count'] > 0, "Tabla estandares_sector debe tener datos"


# ============================================================================
# TESTS: CONSULTAS GET /API/OLAS
# ============================================================================

@pytest.mark.asyncio
async def test_get_olas_retorna_3_olas():
    """GET /api/olas debe retornar 3 olas."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT COUNT(*) as count FROM olas
        """)
        row = await cursor.fetchone()
        assert row['count'] == 3, "Debe haber 3 olas"


@pytest.mark.asyncio
async def test_get_olas_estructura():
    """GET /api/olas retorna estructura correcta."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT ola_id, numero_ola, bultos_programados, bultos_ejecutados, estado
            FROM olas LIMIT 1
        """)
        row = await cursor.fetchone()
        assert row is not None
        assert row['ola_id'] is not None
        assert row['numero_ola'] in [1, 2, 3]
        assert row['bultos_programados'] > 0
        assert row['bultos_ejecutados'] >= 0
        assert row['estado'] in ['en_curso', 'completada', 'pendiente']


@pytest.mark.asyncio
async def test_ola_2_en_curso():
    """OLA 2 debe estar en estado 'en_curso'."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT estado FROM olas WHERE ola_id = 'OLA_2_TARDE_20_04'
        """)
        row = await cursor.fetchone()
        assert row is not None
        assert row['estado'] == 'en_curso', "OLA 2 debe estar en curso"


# ============================================================================
# TESTS: CONSULTAS GET /API/OLAS/{OLA_ID}/OPERARIOS
# ============================================================================

@pytest.mark.asyncio
async def test_get_operarios_ola_retorna_10():
    """GET /api/olas/{ola_id}/operarios debe retornar 10 operarios."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT COUNT(*) as count FROM asignaciones_ola
            WHERE ola_id = 'OLA_2_TARDE_20_04'
        """)
        row = await cursor.fetchone()
        assert row['count'] == 10, "Debe haber 10 operarios en OLA 2"


@pytest.mark.asyncio
async def test_operarios_tienen_productividad():
    """Todos los operarios deben tener productividad registrada."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT COUNT(*) as count FROM asignaciones_ola
            WHERE ola_id = 'OLA_2_TARDE_20_04' AND productividad > 0
        """)
        row = await cursor.fetchone()
        assert row['count'] == 10, "Todos los operarios deben tener productividad"


@pytest.mark.asyncio
async def test_operarios_productividad_rango():
    """Productividad debe estar en rango razonable (100-300 bul/h)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT MIN(productividad) as min_prod, MAX(productividad) as max_prod
            FROM asignaciones_ola WHERE ola_id = 'OLA_2_TARDE_20_04'
        """)
        row = await cursor.fetchone()
        assert row['min_prod'] >= 100, f"Productividad mínima debe ser >=100, es {row['min_prod']}"
        assert row['max_prod'] <= 300, f"Productividad máxima debe ser <=300, es {row['max_prod']}"


# ============================================================================
# TESTS: LOGICA ALERTAS
# ============================================================================

@pytest.mark.asyncio
async def test_generar_alertas_ola_2():
    """generar_alertas debe retornar alertas para OLA 2."""
    alertas = await generar_alertas("OLA_2_TARDE_20_04")
    assert isinstance(alertas, list), "generar_alertas debe retornar lista"
    assert len(alertas) > 0, "Debe haber al menos 1 alerta en OLA 2"


@pytest.mark.asyncio
async def test_alertas_estructura():
    """Alertas deben tener estructura correcta."""
    alertas = await generar_alertas("OLA_2_TARDE_20_04")
    if alertas:
        alerta = alertas[0]
        assert 'tipo' in alerta
        assert 'operario_id' in alerta
        assert 'operario_nombre' in alerta
        assert 'severidad' in alerta
        assert 'desvio_pct' in alerta
        assert 'sugerencia' in alerta


@pytest.mark.asyncio
async def test_alertas_detectan_maria_lopez():
    """Debe detectar a María López con baja productividad."""
    alertas = await generar_alertas("OLA_2_TARDE_20_04")

    # Buscar alerta para María López
    maria_alertas = [a for a in alertas if 'María' in a['operario_nombre'] or 'Maria' in a['operario_nombre']]
    assert len(maria_alertas) > 0, "Debe haber alerta para María López"

    alerta_maria = maria_alertas[0]
    assert alerta_maria['desvio_pct'] < -20, "María debe estar más de 20% bajo"
    assert alerta_maria['severidad'] in ['ALTA', 'CRITICA'], "Alerta debe ser ALTA o CRITICA"


@pytest.mark.asyncio
async def test_alertas_severidad_valida():
    """Todas las alertas deben tener severidad válida."""
    alertas = await generar_alertas("OLA_2_TARDE_20_04")
    severidades_validas = ['CRITICA', 'ALTA', 'MEDIA', 'BAJA']
    for alerta in alertas:
        assert alerta['severidad'] in severidades_validas, f"Severidad inválida: {alerta['severidad']}"


# ============================================================================
# TESTS: COMPARATIVAS
# ============================================================================

@pytest.mark.asyncio
async def test_obtener_comparativas():
    """obtener_comparativas debe retornar top y bottom performers."""
    comparativas = await obtener_comparativas("OLA_2_TARDE_20_04")
    assert 'top_performers' in comparativas
    assert 'bottom_performers' in comparativas
    assert len(comparativas['top_performers']) > 0
    assert len(comparativas['bottom_performers']) > 0


@pytest.mark.asyncio
async def test_top_performers_tienen_productividad_alta():
    """Top performers deben tener productividad alta."""
    comparativas = await obtener_comparativas("OLA_2_TARDE_20_04")
    top = comparativas['top_performers'][0]
    assert top['productividad'] >= 250, f"Top performer debe tener >=250 bul/h, tiene {top['productividad']}"


@pytest.mark.asyncio
async def test_bottom_performers_tienen_productividad_baja():
    """Bottom performers deben tener productividad baja."""
    comparativas = await obtener_comparativas("OLA_2_TARDE_20_04")
    bottom = comparativas['bottom_performers'][0]
    assert bottom['productividad'] <= 220, f"Bottom performer debe tener <=220 bul/h, tiene {bottom['productividad']}"


# ============================================================================
# TESTS: ESTANDARES
# ============================================================================

@pytest.mark.asyncio
async def test_estandar_secos_existe():
    """Debe existir estándar para sector Secos."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT bultos_por_hora FROM estandares_sector WHERE sector = 'Secos'
        """)
        row = await cursor.fetchone()
        assert row is not None
        assert row['bultos_por_hora'] == 250, "Estándar Secos debe ser 250 bul/h"


@pytest.mark.asyncio
async def test_estandar_noa_existe():
    """Debe existir estándar para sector NOA."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT bultos_por_hora FROM estandares_sector WHERE sector = 'NOA'
        """)
        row = await cursor.fetchone()
        assert row is not None
        assert row['bultos_por_hora'] == 60, "Estándar NOA debe ser 60 bul/h"


# ============================================================================
# MAIN: Ejecutar tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
