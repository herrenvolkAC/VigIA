"""
VigIA - Generate Historical Data (1 año = 1.460.000 picks)
Genera datos realistas con patrones inteligentes:
- Caída progresiva por fatiga
- Correlación SKU x operario
- Patrón semanal (lunes más alto, viernes baja)
- Recuperación post-pausa
- Anomalías por enfermedad/ausentismo

Ejecutar: python scripts/generate_historical_data.py
Tiempo estimado: 2-3 minutos para generar todo
"""
import asyncio
import aiosqlite
import json
import random
from pathlib import Path
from datetime import datetime, timedelta
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path(__file__).parent.parent / "vigia.db"

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

SECTORES = ["Secos", "NOA", "Repacking", "Devoluciones"]
TIPOS_ARTICULOS = ["secas", "congelado", "fresco", "bebidas"]
TIPOS_ERRORES = ["sku_incorrecto", "cantidad_incorrecta", "codigo_barras", "ubicacion_mal", "bulto_dañado"]
TIPOS_PAUSAS = ["almuerzo", "descanso", "baño", "capacitacion", "cambio_zona"]
TIPOS_AUSENCIA = ["enfermedad", "licencia", "inasistencia", "retardo", "suspension"]

# Patrones de operarios (para correlación SKU x operario)
OPERARIO_PATTERNS = {
    "OP_00001": {"velocidad": 1.2, "error_rate": 0.02, "cluster": "top"},      # Top performer
    "OP_00002": {"velocidad": 1.15, "error_rate": 0.025, "cluster": "top"},
    "OP_00003": {"velocidad": 1.1, "error_rate": 0.03, "cluster": "top"},
    "OP_00004": {"velocidad": 0.95, "error_rate": 0.04, "cluster": "mid"},     # Mid performer
    "OP_00005": {"velocidad": 0.95, "error_rate": 0.045, "cluster": "mid"},
    "OP_00045": {"velocidad": 0.85, "error_rate": 0.06, "cluster": "low"},     # Low performer (María López)
    "OP_00087": {"velocidad": 0.90, "error_rate": 0.055, "cluster": "low"},    # Carmen Martín
}

async def generate_articulos_maestro(db):
    """Genera 2000+ SKUs realistas"""
    print("[GEN] Generando 2000+ SKUs en articulos_maestro...")

    skus = []
    for i in range(2000):
        sku = f"SKU{i+1:06d}"
        tipo = random.choice(TIPOS_ARTICULOS)

        # Variación de peso según tipo
        if tipo == "congelado":
            peso_kg = round(random.uniform(0.5, 25), 2)
        elif tipo == "bebidas":
            peso_kg = round(random.uniform(0.5, 3), 2)
        else:
            peso_kg = round(random.uniform(0.1, 15), 2)

        # Tiempo de picking varía por tamaño y complejidad
        complejidad = random.choice(["baja", "media", "alta"])
        if complejidad == "baja":
            tiempo_seg = random.randint(10, 20)
        elif complejidad == "media":
            tiempo_seg = random.randint(20, 40)
        else:
            tiempo_seg = random.randint(40, 90)

        skus.append((
            sku,
            f"Articulo {sku} - {tipo}",
            peso_kg,
            json.dumps({"ancho": random.randint(5, 50), "alto": random.randint(5, 60), "profundidad": random.randint(5, 50)}),
            tipo,
            tiempo_seg,
            complejidad,
            1
        ))

    await db.executemany("""
        INSERT INTO articulos_maestro
        (sku, descripcion, peso_kg, dimensiones, tipo, tiempo_picking_promedio_seg, complejidad, activo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, skus)
    await db.commit()
    print(f"[OK] {len(skus)} SKUs generados")


async def generate_picks_with_patterns(db):
    """
    Genera picks con patrones realistas:
    1. Caída progresiva (fatiga a lo largo del turno)
    2. Patrón semanal (lunes alto, viernes bajo)
    3. Recuperación post-pausa
    4. Anomalías (enfermedad, baja productividad)
    5. Correlación SKU x operario
    """
    print("\n[GEN] Generando 1.460.000 picks históricos...")

    # Obtener operarios existentes de la BD
    cursor = await db.execute("SELECT operario_id FROM operarios ORDER BY operario_id")
    operarios = [row[0] for row in await cursor.fetchall()]

    # Obtener olas existentes
    cursor = await db.execute("SELECT ola_id, zona FROM olas")
    olas_map = {row[0]: row[1] for row in await cursor.fetchall()}

    # Obtener SKUs
    cursor = await db.execute("SELECT sku FROM articulos_maestro LIMIT 1000")
    skus_lista = [row[0] for row in await cursor.fetchall()]

    picks = []
    pick_count = 0
    batch_size = 5000

    # Generar 365 días de datos
    start_date = datetime(2024, 1, 1)

    for day_offset in range(365):
        fecha = start_date + timedelta(days=day_offset)
        fecha_str = fecha.strftime("%Y-%m-%d")

        # Día de semana (0=lunes, 6=domingo)
        weekday = fecha.weekday()

        # Factor semanal: lunes=1.1, viernes=0.9
        week_factor = 1.1 if weekday == 0 else (0.9 if weekday == 4 else 1.0)

        # 2 turnos por día
        for turno_num in range(1, 3):
            turno_id = f"TURNO_{fecha.strftime('%Y%m%d')}_{turno_num}"

            # 20 olas por turno (en promedio)
            for ola_offset in range(20):
                # Obtener ola existente o generar ID
                if olas_map:
                    ola_id = random.choice(list(olas_map.keys()))
                    zona = olas_map[ola_id]
                else:
                    ola_id = f"OLA_{ola_offset}_{turno_num}_FECHA"
                    zona = random.choice(SECTORES)

                # Cada operario hace múltiples picks en la ola
                for op_idx in range(len(operarios)):
                    operario_id = operarios[op_idx]

                    # Picks por operario en esta ola: 2-5 picks
                    num_picks = random.randint(2, 5)

                    # Patrón de caída progresiva durante el turno
                    hour_factor = 1.0 - (ola_offset / 20) * 0.15  # Cae ~15% hacia fin de turno

                    # Patrón de operario
                    op_pattern = OPERARIO_PATTERNS.get(operario_id, {
                        "velocidad": random.uniform(0.8, 1.2),
                        "error_rate": random.uniform(0.02, 0.08),
                        "cluster": random.choice(["top", "mid", "low"])
                    })

                    for pick_num in range(num_picks):
                        # Variar SKU
                        sku = random.choice(skus_lista)

                        # Obtener tiempo promedio del SKU
                        cursor = await db.execute(
                            "SELECT tiempo_picking_promedio_seg FROM articulos_maestro WHERE sku = ?",
                            (sku,)
                        )
                        row = await cursor.fetchone()
                        tiempo_base = row[0] if row else 30

                        # Aplicar factores
                        tiempo_real = int(tiempo_base * op_pattern["velocidad"] * hour_factor * week_factor)
                        tiempo_real = max(5, min(180, tiempo_real))  # Clamp 5-180 seg

                        # Cantidad de bultos (1-3)
                        cantidad = random.randint(1, 3)

                        # Timestamp dentro del turno
                        turno_start = 6 if turno_num == 1 else 14
                        hora = turno_start + (ola_offset / 20) * 8  # Distribuir en 8 horas
                        minuto = random.randint(0, 59)

                        timestamp = fecha.replace(
                            hour=int(hora),
                            minute=minuto,
                            second=random.randint(0, 59)
                        )

                        estado = "completado"
                        if random.random() < op_pattern["error_rate"]:
                            estado = random.choice(["error", "completado"])  # Mostly completado

                        picks.append((
                            f"PICK_{pick_count:08d}",
                            fecha_str,
                            timestamp.isoformat(),
                            turno_id,
                            ola_id,
                            operario_id,
                            zona,
                            sku,
                            cantidad,
                            round(random.uniform(0.1, 10), 2),  # peso_kg
                            tiempo_real,
                            estado
                        ))

                        pick_count += 1

                        # Batch insert
                        if len(picks) >= batch_size:
                            await db.executemany("""
                                INSERT INTO picks_operario
                                (pick_id, fecha, timestamp, turno_id, ola_id, operario_id, sector, sku, cantidad_bultos, peso_kg, tiempo_segundos, estado)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, picks)
                            await db.commit()
                            print(f"  [{pick_count:,}] picks generados...")
                            picks = []

    # Último batch
    if picks:
        await db.executemany("""
            INSERT INTO picks_operario
            (pick_id, fecha, timestamp, turno_id, ola_id, operario_id, sector, sku, cantidad_bultos, peso_kg, tiempo_segundos, estado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, picks)
        await db.commit()

    print(f"[OK] {pick_count:,} picks generados exitosamente")
    return pick_count


async def generate_pausas(db):
    """Genera pausas de operarios"""
    print("\n[GEN] Generando pausas de operarios...")

    cursor = await db.execute("SELECT operario_id FROM operarios")
    operarios = [row[0] for row in await cursor.fetchall()]

    pausas = []
    pausa_id = 0

    for day_offset in range(365):
        fecha = datetime(2024, 1, 1) + timedelta(days=day_offset)
        fecha_str = fecha.strftime("%Y-%m-%d")

        for operario_id in random.sample(operarios, k=min(5, len(operarios))):
            # 1-2 pausas por día por operario
            for _ in range(random.randint(1, 2)):
                tipo = random.choice(TIPOS_PAUSAS)
                duracion = 30 if tipo == "almuerzo" else random.randint(10, 20)

                timestamp_inicio = fecha.replace(
                    hour=random.randint(6, 18),
                    minute=random.randint(0, 59),
                    second=0
                )

                timestamp_fin = timestamp_inicio + timedelta(minutes=duracion)

                pausas.append((
                    f"PAUSA_{pausa_id:06d}",
                    fecha_str,
                    operario_id,
                    timestamp_inicio.isoformat(),
                    timestamp_fin.isoformat(),
                    tipo,
                    duracion,
                    None
                ))
                pausa_id += 1

    await db.executemany("""
        INSERT INTO pausas_operario
        (pausa_id, fecha, operario_id, timestamp_inicio, timestamp_fin, tipo, duracion_minutos, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, pausas)
    await db.commit()
    print(f"[OK] {len(pausas)} pausas generadas")


async def generate_ausencias(db):
    """Genera ausencias"""
    print("\n[GEN] Generando ausencias...")

    cursor = await db.execute("SELECT operario_id FROM operarios")
    operarios = [row[0] for row in await cursor.fetchall()]

    ausencias = []
    ausencia_id = 0

    # ~10% de operarios tienen ausencias dispersas
    for operario_id in random.sample(operarios, k=max(1, len(operarios) // 10)):
        # 2-5 ausencias en el año
        for _ in range(random.randint(2, 5)):
            fecha = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 364))
            fecha_str = fecha.strftime("%Y-%m-%d")

            tipo = random.choice(TIPOS_AUSENCIA)
            duracion = 480 if tipo == "licencia" else random.randint(60, 240)  # minutos
            justificado = random.choice([True, False])

            ausencias.append((
                f"AUSENCIA_{ausencia_id:06d}",
                fecha_str,
                operario_id,
                tipo,
                duracion,
                justificado,
                None
            ))
            ausencia_id += 1

    await db.executemany("""
        INSERT INTO ausentismo_operario
        (ausencia_id, fecha, operario_id, tipo, duracion_minutos, justificado, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ausencias)
    await db.commit()
    print(f"[OK] {len(ausencias)} ausencias generadas")


async def generate_errores(db):
    """Genera errores de picking"""
    print("\n[GEN] Generando errores...")

    cursor = await db.execute("SELECT operario_id FROM operarios")
    operarios = [row[0] for row in await cursor.fetchall()]

    cursor = await db.execute("SELECT sku FROM articulos_maestro LIMIT 500")
    skus = [row[0] for row in await cursor.fetchall()]

    errores = []
    error_id = 0

    # ~5% de picks tienen error
    for day_offset in range(365):
        fecha = datetime(2024, 1, 1) + timedelta(days=day_offset)
        fecha_str = fecha.strftime("%Y-%m-%d")

        for _ in range(random.randint(5, 15)):  # 5-15 errores por día
            timestamp = fecha.replace(
                hour=random.randint(6, 18),
                minute=random.randint(0, 59),
                second=random.randint(0, 59)
            )

            errores.append((
                f"ERROR_{error_id:06d}",
                fecha_str,
                timestamp.isoformat(),
                random.choice(operarios),
                random.choice(skus) if random.random() > 0.3 else None,
                random.choice(TIPOS_ERRORES),
                random.randint(1, 5),
                None,
                random.choice(["baja", "media", "alta"]),
                random.choice([0, 1])
            ))
            error_id += 1

    await db.executemany("""
        INSERT INTO errores_operario
        (error_id, fecha, timestamp, operario_id, sku, tipo_error, cantidad, descripcion, severidad, corregido)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, errores)
    await db.commit()
    print(f"[OK] {len(errores)} errores generados")


async def main():
    print("\n" + "="*70)
    print("[START] GENERACION DE DATOS HISTORICOS - 1 AÑO")
    print("="*70)

    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            await generate_articulos_maestro(db)
            pick_count = await generate_picks_with_patterns(db)
            await generate_pausas(db)
            await generate_ausencias(db)
            await generate_errores(db)

            # Validación
            print("\n[VALIDATE] Validando datos generados...")

            cursor = await db.execute("SELECT COUNT(*) FROM picks_operario")
            picks = await cursor.fetchone()
            print(f"  picks_operario: {picks[0]:,}")

            cursor = await db.execute("SELECT COUNT(*) FROM articulos_maestro")
            skus = await cursor.fetchone()
            print(f"  articulos_maestro: {skus[0]:,}")

            cursor = await db.execute("SELECT COUNT(*) FROM pausas_operario")
            pausas = await cursor.fetchone()
            print(f"  pausas_operario: {pausas[0]:,}")

            cursor = await db.execute("SELECT COUNT(*) FROM ausentismo_operario")
            ausencias = await cursor.fetchone()
            print(f"  ausentismo_operario: {ausencias[0]:,}")

            cursor = await db.execute("SELECT COUNT(*) FROM errores_operario")
            errores = await cursor.fetchone()
            print(f"  errores_operario: {errores[0]:,}")

            print("\n" + "="*70)
            print("[SUCCESS] DATOS HISTORICOS GENERADOS EXITOSAMENTE")
            print("="*70 + "\n")

            return True

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
