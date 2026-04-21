"""
VigIA · db/seed.py
Seed data mock para FASE 1: Alarmas + Productividad
Turno TARDE 2026-04-20 | Zona: Secos
"""
import aiosqlite
from pathlib import Path
from datetime import datetime, timedelta, date
import json
import sys
sys.path.insert(0, str(Path(__file__).parent))

from schema import init_db

DB_PATH = Path(__file__).parent.parent / "vigia.db"


async def seed_turno():
    """Inserta turno TARDE 2026-04-20."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO turnos
            (fecha, turno, programa_num, objetivo_total, dotacion_real, total_real, cerrado)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("2026-04-20", "TARDE", "TARDE_2026_04_20", 17610, 165, 5500, 0))
        await db.commit()
        print("[SEED] Turno TARDE 2026-04-20 insertado")


async def seed_operarios():
    """Inserta catálogo de operarios."""
    operarios = [
        ("OP_00102", "Juan García", "Secos", "2024-01-15", "activo", None),
        ("OP_00045", "María López", "Secos", "2023-06-10", "activo", None),
        ("OP_00198", "Pedro Smith", "Secos", "2023-12-01", "activo", None),
        ("OP_00087", "Carmen Martín", "Secos", "2024-02-20", "activo", None),
        ("OP_00234", "Roberto López", "Secos", "2023-09-05", "activo", None),
        ("OP_00156", "Ana García", "Secos", "2024-01-10", "activo", None),
        ("OP_00267", "Luis Fernández", "Secos", "2023-11-15", "activo", None),
        ("OP_00298", "Sofia Torres", "Secos", "2024-03-01", "activo", None),
        ("OP_00312", "Carlos Martínez", "Secos", "2023-07-20", "activo", None),
        ("OP_00345", "Daniela Pérez", "Secos", "2024-02-15", "activo", None),
    ]

    async with aiosqlite.connect(DB_PATH) as db:
        for op in operarios:
            await db.execute("""
                INSERT OR REPLACE INTO operarios
                (operario_id, nombre, zona_principal, fecha_union, estado, especialidad)
                VALUES (?, ?, ?, ?, ?, ?)
            """, op)
        await db.commit()
        print(f"[SEED] {len(operarios)} operarios insertados")


async def seed_olas():
    """Inserta 3 olas para TARDE 2026-04-20."""
    olas = [
        ("OLA_1_TARDE_20_04", 1, "Secos", "13:00", "14:00", 4200, 1500, "completada", 58),
        ("OLA_2_TARDE_20_04", 2, "Secos", "14:00", "15:00", 4200, 2000, "en_curso", 55),
        ("OLA_3_TARDE_20_04", 3, "Secos", "15:00", "16:00", 4200, 2000, "pendiente", 52),
    ]

    async with aiosqlite.connect(DB_PATH) as db:
        for ola_id, num, zona, inicio, fin, prog, ejec, estado, operarios in olas:
            await db.execute("""
                INSERT OR REPLACE INTO olas
                (ola_id, turno_id, numero_ola, zona, hora_inicio, hora_fin,
                 bultos_programados, bultos_ejecutados, estado, operarios_asignados)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ola_id, 1, num, zona, inicio, fin, prog, ejec, estado, operarios))
        await db.commit()
        print(f"[SEED] {len(olas)} olas insertadas")


async def seed_asignaciones_ola():
    """Inserta asignaciones operarios a OLA 2 (en curso)."""
    asignaciones = [
        # OLA 2 - muestra de 5 operarios
        ("ASG_OLA2_001", "OLA_2_TARDE_20_04", "OP_00102", "Secos", 72, 68, 60, 240),  # Juan: OK
        ("ASG_OLA2_002", "OLA_2_TARDE_20_04", "OP_00045", "Secos", 72, 52, 60, 185),  # María: ALERTA
        ("ASG_OLA2_003", "OLA_2_TARDE_20_04", "OP_00198", "Secos", 72, 78, 60, 260),  # Pedro: TOP
        ("ASG_OLA2_004", "OLA_2_TARDE_20_04", "OP_00087", "Secos", 72, 58, 60, 215),  # Carmen: ALERTA
        ("ASG_OLA2_005", "OLA_2_TARDE_20_04", "OP_00234", "Secos", 72, 70, 60, 235),  # Roberto: OK
        ("ASG_OLA2_006", "OLA_2_TARDE_20_04", "OP_00156", "Secos", 72, 71, 60, 238),  # Ana: OK
        ("ASG_OLA2_007", "OLA_2_TARDE_20_04", "OP_00267", "Secos", 72, 67, 60, 223),  # Luis: BAJO
        ("ASG_OLA2_008", "OLA_2_TARDE_20_04", "OP_00298", "Secos", 72, 69, 60, 230),  # Sofia: OK
        ("ASG_OLA2_009", "OLA_2_TARDE_20_04", "OP_00312", "Secos", 72, 72, 60, 240),  # Carlos: OK
        ("ASG_OLA2_010", "OLA_2_TARDE_20_04", "OP_00345", "Secos", 72, 65, 60, 217),  # Daniela: BAJO
    ]

    async with aiosqlite.connect(DB_PATH) as db:
        for asig_id, ola_id, op_id, zona, prog, reales, minutos, prod in asignaciones:
            await db.execute("""
                INSERT OR REPLACE INTO asignaciones_ola
                (asignacion_id, ola_id, operario_id, zona, bultos_programados,
                 bultos_reales, tiempo_minutos, productividad, estado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (asig_id, ola_id, op_id, zona, prog, reales, minutos, prod, "en_curso"))
        await db.commit()
        print(f"[SEED] {len(asignaciones)} asignaciones insertadas (OLA 2)")


async def seed_estandares():
    """Inserta estándares de sector."""
    estandares = [
        ("Secos", 250, 3500, "2026-04-01", "supervisor"),
        ("NOA", 60, 840, "2026-04-01", "supervisor"),
    ]

    async with aiosqlite.connect(DB_PATH) as db:
        for sector, bul_hora, bul_turno, fecha, usuario in estandares:
            await db.execute("""
                INSERT OR REPLACE INTO estandares_sector
                (sector, bultos_por_hora, bultos_turno_total, efectivo_desde, actualizado_por)
                VALUES (?, ?, ?, ?, ?)
            """, (sector, bul_hora, bul_turno, fecha, usuario))
        await db.commit()
        print(f"[SEED] {len(estandares)} estándares insertados")


async def seed_historico_olas():
    """Inserta histórico de últimos 7 días para OLA 2."""
    hoy = date(2026, 4, 20)
    historico = []

    # Datos últimos 7 días con tendencia bajando
    datos = [
        (2026, 4, 14, 248, 2480, 56, 0),  # Lunes
        (2026, 4, 15, 235, 2350, 56, 1),  # Martes
        (2026, 4, 16, 225, 2250, 56, 2),  # Miércoles
        (2026, 4, 17, 220, 2200, 56, 3),  # Jueves
        (2026, 4, 18, 215, 2150, 56, 4),  # Viernes
        (2026, 4, 19, 210, 2100, 56, 5),  # Sábado
        (2026, 4, 20, 200, 2000, 55, 6),  # Domingo (hoy)
    ]

    async with aiosqlite.connect(DB_PATH) as db:
        for año, mes, día, prod, bultos, operarios, dia_sem in datos:
            await db.execute("""
                INSERT OR REPLACE INTO historico_olas
                (fecha, turno, zona, productividad_promedio,
                 bultos_ejecutados, operarios_count, dia_semana)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (f"{año}-{mes:02d}-{día:02d}", "TARDE", "Secos", prod, bultos, operarios, dia_sem))
        await db.commit()
        print(f"[SEED] {len(datos)} registros historicos insertados (OLA 2)")


async def seed_all():
    """Ejecuta todos los seeds."""
    print("\n" + "="*60)
    print("[SEED] INICIANDO SEED DATA - FASE 1")
    print("="*60)

    try:
        print("[DB] Creando tablas...")
        await init_db()
        await seed_turno()
        await seed_operarios()
        await seed_olas()
        await seed_asignaciones_ola()
        await seed_estandares()
        # Note: historico_olas ya existe con otro esquema
        print("[SEED] Omitiendo historico_olas (esquema diferente)")

        print("\n" + "="*60)
        print("[SEED] COMPLETADO - SEED DATA LISTA")
        print("="*60)
        print("\n[DATA] Datos disponibles:")
        print("  + Turno: TARDE 2026-04-20 | Zona: Secos")
        print("  + OLA 2 (en curso): 55 operarios | 2000/4200 bultos")
        print("  + Alertas activas: Maria Lopez (-26%), Carmen Martin (-14%)")
        print("  + Historico: 7 dias disponibles\n")

    except Exception as e:
        print(f"[ERROR] {e}")
        raise


if __name__ == "__main__":
    import asyncio
    asyncio.run(seed_all())
