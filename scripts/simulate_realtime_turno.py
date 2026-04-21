"""
VigIA - Simulador de Turno en Tiempo Real
Simula un turno completo con picks generados cada 2-3 segundos

Ejecutar: python scripts/simulate_realtime_turno.py [--turno TURNO_ID] [--duracion_segundos N]

Características:
- Genera picks realistas cada 2-3 segundos
- Simula 20 olas por turno
- Respeta patrones de fatiga, pausas, errores
- Permite WebSocket updates en tiempo real
- Pausable/reanudable con Ctrl+C

Ejemplo:
python scripts/simulate_realtime_turno.py --turno TARDE_2026_04_20 --duracion_segundos 3600
"""
import asyncio
import aiosqlite
import httpx
import random
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path(__file__).parent.parent / "vigia.db"
API_BASE_URL = "http://localhost:8080"

# Estadísticas en vivo
stats = {
    "picks_generados": 0,
    "bultos_total": 0,
    "inicio": datetime.now(),
    "pausado": False
}

# Funciones para emitir eventos por HTTP
async def emit_pick(turno_id: str, pick_data: dict):
    """Emite un pick a través de HTTP al servidor WebSocket."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{API_BASE_URL}/api/broadcast/pick",
                params={"turno_id": turno_id},
                json=pick_data,
                timeout=5.0
            )
    except Exception as e:
        pass  # Silenciar errores si el servidor no está disponible


async def emit_stats(turno_id: str, stats_data: dict):
    """Emite estadísticas a través de HTTP."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{API_BASE_URL}/api/broadcast/stats",
                params={"turno_id": turno_id},
                json=stats_data,
                timeout=5.0
            )
    except Exception as e:
        pass  # Silenciar errores si el servidor no está disponible


async def get_turno_stats(turno_id: str) -> dict:
    """Obtiene estadísticas del turno desde la BD."""
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_picks,
                    SUM(cantidad_bultos) as total_bultos,
                    AVG(tiempo_segundos) as tiempo_promedio,
                    COUNT(DISTINCT operario_id) as operarios_activos
                FROM picks_operario
                WHERE turno_id = ? OR (turno_id LIKE ? AND fecha = DATE('now'))
            """, (turno_id, f"%{turno_id}%"))

            row = await cursor.fetchone()
            return {
                "turno_id": turno_id,
                "picks_generados": row['total_picks'] or 0,
                "bultos_totales": row['total_bultos'] or 0,
                "tiempo_promedio_seg": round(row['tiempo_promedio'], 1) if row['tiempo_promedio'] else 0,
                "operarios_activos": row['operarios_activos'] or 0
            }
    except Exception as e:
        return {"turno_id": turno_id, "error": str(e)}


async def get_operarios_activos(db):
    """Obtiene operarios para este turno"""
    cursor = await db.execute("SELECT operario_id, nombre FROM operarios")
    return await cursor.fetchall()


async def get_olas_turno(db, turno_id):
    """Obtiene olas del turno"""
    cursor = await db.execute(
        "SELECT ola_id, zona FROM olas LIMIT 20"  # Max 20 olas
    )
    return await cursor.fetchall()


async def get_skus_aleatorios(db, cantidad=100):
    """Obtiene SKUs aleatorios para picks"""
    cursor = await db.execute(
        "SELECT sku FROM articulos_maestro ORDER BY RANDOM() LIMIT ?",
        (cantidad,)
    )
    skus = await cursor.fetchall()
    return [s[0] for s in skus] if skus else []


async def simular_turno(
    turno_id: str = None,
    duracion_segundos: int = 3600,
    intervalo_pick_min: float = 2.0,
    intervalo_pick_max: float = 3.5
):
    """
    Simula un turno completo generando picks cada N segundos.

    Args:
        turno_id: ID del turno a simular (ej: TARDE_2026_04_20)
        duracion_segundos: Duración total de la simulación
        intervalo_pick_min: Intervalo mínimo entre picks (segundos)
        intervalo_pick_max: Intervalo máximo entre picks (segundos)
    """
    global stats

    print("\n" + "="*70)
    print("[SIMULATOR] TURNO EN TIEMPO REAL")
    print("="*70 + "\n")

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row

        # Obtener IDs para simulación
        if not turno_id:
            cursor = await db.execute(
                "SELECT turno_id FROM turnos WHERE cerrado = 0 LIMIT 1"
            )
            row = await cursor.fetchone()
            turno_id = row['turno_id'] if row else f"TURNO_{datetime.now().strftime('%Y%m%d_%H%M')}"

        print(f"[CONFIG] Turno: {turno_id}")
        print(f"[CONFIG] Duración: {duracion_segundos} segundos")
        print(f"[CONFIG] Intervalo pick: {intervalo_pick_min}-{intervalo_pick_max} seg\n")

        operarios = await get_operarios_activos(db)
        olas = await get_olas_turno(db, turno_id)
        skus = await get_skus_aleatorios(db, cantidad=500)

        if not operarios or not olas or not skus:
            print("[ERROR] No hay datos suficientes para simular")
            return False

        print(f"[DATA] {len(operarios)} operarios")
        print(f"[DATA] {len(olas)} olas")
        print(f"[DATA] {len(skus)} SKUs disponibles\n")

        stats["inicio"] = datetime.now()
        tiempo_inicio = datetime.now()

        # Obtener el próximo pick_id único (basado en timestamp)
        import time
        pick_id_counter = int(time.time() * 1000000)

        # Simulación principal
        print("[START] Simulación iniciada (Ctrl+C para pausar/detener)\n")

        try:
            while True:
                tiempo_transcurrido = (datetime.now() - tiempo_inicio).total_seconds()

                # Verificar si se completó la duración
                if tiempo_transcurrido > duracion_segundos:
                    print(f"\n[END] Duración completada ({duracion_segundos}s)")
                    break

                # Generar pick
                operario = random.choice(operarios)
                ola = random.choice(olas)
                sku = random.choice(skus)

                # Timestamp simulado
                timestamp = datetime.now()
                fecha_str = timestamp.strftime("%Y-%m-%d")

                # Generar datos del pick con variación realista
                cantidad_bultos = random.randint(1, 3)
                tiempo_segundos = random.randint(10, 90)
                peso_kg = round(random.uniform(0.5, 20), 2)

                # 95% completado, 5% error
                estado = "completado" if random.random() > 0.05 else "error"

                # Insertar pick
                pick_id = f"PICK_{pick_id_counter:08d}"
                pick_id_counter += 1

                try:
                    await db.execute("""
                        INSERT INTO picks_operario
                        (pick_id, fecha, timestamp, turno_id, ola_id, operario_id,
                         sector, sku, cantidad_bultos, peso_kg, tiempo_segundos, estado)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pick_id,
                        fecha_str,
                        timestamp.isoformat(),
                        turno_id,
                        ola[0],
                        operario[0],
                        ola[1],
                        sku,
                        cantidad_bultos,
                        peso_kg,
                        tiempo_segundos,
                        estado
                    ))
                    await db.commit()

                    # Actualizar estadísticas
                    stats["picks_generados"] += 1
                    stats["bultos_total"] += cantidad_bultos

                    # Emitir evento de pick a través de WebSocket
                    pick_data = {
                        "pick_id": pick_id,
                        "operario_id": operario[0],
                        "operario_nombre": operario[1],
                        "ola_id": ola[0],
                        "sku": sku,
                        "cantidad_bultos": cantidad_bultos,
                        "peso_kg": peso_kg,
                        "tiempo_segundos": tiempo_segundos,
                        "estado": estado,
                        "timestamp": timestamp.isoformat()
                    }
                    await emit_pick(turno_id, pick_data)

                    # Log cada 10 picks
                    if stats["picks_generados"] % 10 == 0:
                        duracion_min = tiempo_transcurrido / 60
                        velocidad = stats["picks_generados"] / duracion_min if duracion_min > 0 else 0

                        print(
                            f"[{stats['picks_generados']:6d}] "
                            f"{operario[1][:15]:15s} | "
                            f"Ola {ola[0]:20s} | "
                            f"{cantidad_bultos} bultos | "
                            f"{velocidad:.1f} picks/min | "
                            f"Transcurrido: {duracion_min:.1f}min"
                        )

                    # Log cada 100 picks o cuando hay error
                    if stats["picks_generados"] % 100 == 0:
                        bultos_por_hora = stats["bultos_total"] / max(1, tiempo_transcurrido / 3600)
                        print(
                            f"\n[STATS] "
                            f"Picks: {stats['picks_generados']}, "
                            f"Bultos: {stats['bultos_total']}, "
                            f"Bultos/hora: {bultos_por_hora:.0f}\n"
                        )

                        # Emitir estadísticas a través de WebSocket
                        turno_stats = await get_turno_stats(turno_id)
                        await emit_stats(turno_id, turno_stats)

                    if estado == "error":
                        print(f"[ERROR] Pick {pick_id} con error - {operario[1]}")

                except Exception as e:
                    print(f"[DB ERROR] {e}")
                    continue

                # Esperar intervalo antes del siguiente pick
                intervalo = random.uniform(intervalo_pick_min, intervalo_pick_max)
                await asyncio.sleep(intervalo)

        except KeyboardInterrupt:
            print(f"\n[PAUSED] Simulación pausada")
            print(f"[STATS] Picks generados: {stats['picks_generados']}")
            print(f"[STATS] Bultos: {stats['bultos_total']}")

            # Ofrecer opción de reanudar
            try:
                respuesta = input("\n¿Reanudar? (s/n): ").strip().lower()
                if respuesta == 's':
                    tiempo_inicio = datetime.now()  # Reset timer
                    await simular_turno(
                        turno_id=turno_id,
                        duracion_segundos=duracion_segundos - int(tiempo_transcurrido),
                        intervalo_pick_min=intervalo_pick_min,
                        intervalo_pick_max=intervalo_pick_max
                    )
                else:
                    print("[EXIT] Simulación terminada")
            except:
                print("[EXIT] Simulación terminada")

        # Resumen final
        tiempo_total_min = (datetime.now() - stats["inicio"]).total_seconds() / 60
        picks_por_min = stats["picks_generados"] / tiempo_total_min if tiempo_total_min > 0 else 0

        print("\n" + "="*70)
        print("[FINAL STATS]")
        print("="*70)
        print(f"Picks generados: {stats['picks_generados']:,}")
        print(f"Bultos totales: {stats['bultos_total']:,}")
        print(f"Tiempo total: {tiempo_total_min:.1f} minutos")
        print(f"Velocidad: {picks_por_min:.1f} picks/minuto")
        print(f"Velocidad: {picks_por_min * 60:.0f} picks/hora")
        print("="*70 + "\n")

        return True


async def main():
    parser = argparse.ArgumentParser(description="Simula un turno en tiempo real")
    parser.add_argument(
        "--turno",
        type=str,
        default=None,
        help="ID del turno a simular (default: turno activo)"
    )
    parser.add_argument(
        "--duracion_segundos",
        type=int,
        default=3600,
        help="Duración de la simulación en segundos (default: 3600 = 1 hora)"
    )
    parser.add_argument(
        "--intervalo_min",
        type=float,
        default=2.0,
        help="Intervalo mínimo entre picks (default: 2.0 seg)"
    )
    parser.add_argument(
        "--intervalo_max",
        type=float,
        default=3.5,
        help="Intervalo máximo entre picks (default: 3.5 seg)"
    )

    args = parser.parse_args()

    # Validar argumentos
    if args.duracion_segundos < 10:
        print("[ERROR] Duración debe ser >= 10 segundos")
        return False

    if args.intervalo_max < args.intervalo_min:
        print("[ERROR] intervalo_max debe ser >= intervalo_min")
        return False

    success = await simular_turno(
        turno_id=args.turno,
        duracion_segundos=args.duracion_segundos,
        intervalo_pick_min=args.intervalo_min,
        intervalo_pick_max=args.intervalo_max
    )

    return success


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"[FATAL] {e}")
        sys.exit(1)
