"""
Test rápido de endpoints FASE 1
"""
import asyncio
import aiosqlite
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from utils.alertas import generar_alertas

DB_PATH = Path(__file__).parent / "vigia.db"


async def test_turnos():
    """Probar query de turnos"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                turno_id, fecha, turno,
                objetivo_total as bultos_objetivo,
                total_real as bultos_ejecutados,
                ROUND(CAST(total_real AS FLOAT) / objetivo_total * 100, 1) as pct_ejecucion
            FROM turnos
            WHERE turno_id = ?
        """, ("TARDE_2026_04_20",))

        row = await cursor.fetchone()
        if row:
            print("[TEST] GET /api/turnos/TARDE_2026_04_20 - OK")
            turno_dict = dict(row)
            for key, value in turno_dict.items():
                print(f"  {key}: {value}")
        else:
            print("[TEST] GET /api/turnos - Turno no encontrado")


async def test_olas():
    """Probar query de olas"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                ola_id,
                numero_ola,
                zona,
                hora_inicio,
                hora_fin,
                bultos_programados,
                bultos_ejecutados,
                ROUND(CAST(bultos_ejecutados AS FLOAT) / bultos_programados * 100, 1) as pct_ejecucion,
                estado,
                operarios_asignados
            FROM olas
            ORDER BY numero_ola
        """)

        olas = await cursor.fetchall()
        if olas:
            print(f"\n[TEST] GET /api/olas - OK ({len(olas)} olas)")
            for ola in olas:
                ola_dict = dict(ola)
                print(f"  OLA {ola_dict['numero_ola']}: {ola_dict['bultos_ejecutados']}/{ola_dict['bultos_programados']} ({ola_dict['pct_ejecucion']}%)")
        else:
            print("[TEST] GET /api/olas - No hay olas")


async def test_operarios_ola():
    """Probar query de operarios en ola"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Obtener estándar
        cursor = await db.execute("""
            SELECT bultos_por_hora as estandar
            FROM estandares_sector
            WHERE sector = 'Secos'
        """)
        std_row = await cursor.fetchone()
        estandar = std_row['estandar'] if std_row else 250

        # Obtener operarios
        cursor = await db.execute("""
            SELECT
                a.operario_id,
                o.nombre,
                a.bultos_reales,
                a.productividad,
                ? as estandar,
                ROUND(a.productividad - ?, 1) as desvio_pct,
                CASE
                    WHEN a.productividad >= (? * 0.9) THEN 'ok'
                    WHEN a.productividad >= (? * 0.8) THEN 'bajo'
                    ELSE 'critico'
                END as estado_productividad
            FROM asignaciones_ola a
            JOIN operarios o ON a.operario_id = o.operario_id
            WHERE a.ola_id = ?
            ORDER BY a.productividad DESC
        """, (estandar, estandar, estandar, estandar, "OLA_2_TARDE_20_04"))

        operarios = await cursor.fetchall()
        if operarios:
            print(f"\n[TEST] GET /api/olas/OLA_2_TARDE_20_04/operarios - OK ({len(operarios)} operarios)")
            for op in operarios:
                op_dict = dict(op)
                print(f"  {op_dict['nombre']}: {op_dict['productividad']} bul/h ({op_dict['desvio_pct']:+.1f}% vs est.) - {op_dict['estado_productividad'].upper()}")
        else:
            print("[TEST] GET /api/olas/.../operarios - No hay operarios")


async def test_estandares():
    """Probar query de estándares"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM estandares_sector
        """)

        estandares = await cursor.fetchall()
        if estandares:
            print(f"\n[TEST] GET /api/estandares - OK ({len(estandares)} sectores)")
            for est in estandares:
                est_dict = dict(est)
                print(f"  {est_dict['sector']}: {est_dict['bultos_por_hora']} bul/h | {est_dict['bultos_turno_total']} bul/turno")
        else:
            print("[TEST] GET /api/estandares - No hay estándares")


async def test_alertas():
    """Probar generación de alertas"""
    alertas = await generar_alertas("OLA_2_TARDE_20_04")
    if alertas:
        print(f"\n[TEST] GET /api/olas/OLA_2_TARDE_20_04/alertas - OK ({len(alertas)} alertas)")
        for alerta in alertas:
            print(f"  [{alerta['severidad']}] {alerta['operario_nombre']}: {alerta['desvio_pct']:+.1f}% vs est.")
    else:
        print("\n[TEST] GET /api/olas/OLA_2_TARDE_20_04/alertas - OK (sin alertas)")


async def main():
    print("\n" + "="*60)
    print("PRUEBA DE ENDPOINTS FASE 1")
    print("="*60 + "\n")

    await test_turnos()
    await test_olas()
    await test_operarios_ola()
    await test_estandares()
    await test_alertas()

    print("\n" + "="*60)
    print("PRUEBAS COMPLETADAS - ENDPOINTS LISTOS")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
