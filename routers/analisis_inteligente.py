"""
VigIA - Análisis Inteligente (5 funciones IA)
Detección automática de patrones y anomalías:
1. caida_progresiva - Fatiga detectada por disminución de velocidad
2. correlacion_sku_operario - Operarios expertos en ciertos SKUs
3. patron_semanal - Variación de productividad por día semana
4. recuperacion_pausa - Impacto de pausas en velocidad post-pausa
5. anomalia_zscore - Desviaciones estadísticas

Autor: Claude AI
Fecha: 2026-04-20
"""
import aiosqlite
from pathlib import Path
import json
from datetime import datetime, timedelta
from statistics import mean, stdev, median
from typing import Dict, List, Any

DB_PATH = Path(__file__).parent.parent / "vigia.db"


# ============================================================================
# 1. CAIDA PROGRESIVA - Fatiga detectada por disminución de velocidad
# ============================================================================

async def analizar_caida_progresiva(operario_id: str, ola_id: str) -> Dict[str, Any]:
    """
    Detecta si el operario está experimentando fatiga dentro de la ola.
    Calcula la velocidad en los primeros picks vs últimos picks.

    Indicadores:
    - velocidad_inicial: promedio picks primeros 30 minutos
    - velocidad_final: promedio picks últimos 30 minutos
    - caida_pct: porcentaje de disminución
    - severidad: 'baja' (<10%), 'media' (10-20%), 'alta' (>20%)
    - recomendacion: si caída > 15%, sugerir pausa
    """
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Obtener picks del operario en esta ola
            cursor = await db.execute("""
                SELECT timestamp, tiempo_segundos
                FROM picks_operario
                WHERE operario_id = ? AND ola_id = ?
                ORDER BY timestamp
            """, (operario_id, ola_id))

            picks = await cursor.fetchall()

            if len(picks) < 4:
                return {
                    "operario_id": operario_id,
                    "ola_id": ola_id,
                    "tipo": "caida_progresiva",
                    "detectado": False,
                    "razon": "Insuficientes picks para analizar"
                }

            # Dividir en primeros y últimos
            mid = len(picks) // 2
            picks_iniciales = picks[:mid]
            picks_finales = picks[mid:]

            # Calcular velocidad (picks por minuto)
            tiempo_inicial = sum(p['tiempo_segundos'] for p in picks_iniciales) / 60
            tiempo_final = sum(p['tiempo_segundos'] for p in picks_finales) / 60

            velocidad_inicial = len(picks_iniciales) / (tiempo_inicial if tiempo_inicial > 0 else 1)
            velocidad_final = len(picks_finales) / (tiempo_final if tiempo_final > 0 else 1)

            caida_pct = round((1 - velocidad_final / velocidad_inicial) * 100, 1) if velocidad_inicial > 0 else 0

            if caida_pct < 0:
                caida_pct = 0  # No considerar mejoras

            # Determinar severidad
            if caida_pct > 20:
                severidad = "CRITICA"
                recomendacion = "Ofrecer pausa INMEDIATA - fatiga severa detectada"
            elif caida_pct > 15:
                severidad = "ALTA"
                recomendacion = "Sugerir pausa preventiva próxima hora"
            elif caida_pct > 10:
                severidad = "MEDIA"
                recomendacion = "Monitorear próximas olas"
            else:
                severidad = "BAJA"
                recomendacion = "Sin acción - fatiga normal"

            return {
                "operario_id": operario_id,
                "ola_id": ola_id,
                "tipo": "caida_progresiva",
                "detectado": caida_pct > 10,
                "caida_pct": caida_pct,
                "velocidad_inicial_pick_min": round(velocidad_inicial, 2),
                "velocidad_final_pick_min": round(velocidad_final, 2),
                "picks_analizados": len(picks),
                "severidad": severidad,
                "recomendacion": recomendacion
            }

    except Exception as e:
        return {
            "operario_id": operario_id,
            "ola_id": ola_id,
            "tipo": "caida_progresiva",
            "error": str(e)
        }


# ============================================================================
# 2. CORRELACION SKU x OPERARIO - Operarios expertos en ciertos SKUs
# ============================================================================

async def analizar_correlacion_sku_operario(operario_id: str, dias: int = 30) -> Dict[str, Any]:
    """
    Detecta si el operario tiene SKUs favoritos/expertos.
    Compara velocidad en SKUs específicos vs velocidad promedio.

    Indicadores:
    - skus_expertos: SKUs donde es >20% más rápido
    - skus_debiles: SKUs donde es >20% más lento
    - especialidad_pct: porcentaje de picks en SKUs expertos
    """
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Fecha límite (últimos N días)
            fecha_limite = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")

            # Velocidad promedio del operario
            cursor = await db.execute("""
                SELECT AVG(tiempo_segundos) as vel_promedio
                FROM picks_operario
                WHERE operario_id = ? AND fecha >= ?
            """, (operario_id, fecha_limite))

            row = await cursor.fetchone()
            vel_promedio = row['vel_promedio'] if row and row['vel_promedio'] else 30

            # Velocidad por SKU
            cursor = await db.execute("""
                SELECT
                    p.sku,
                    COUNT(*) as num_picks,
                    AVG(p.tiempo_segundos) as vel_promedio,
                    AVG(CAST(a.complejidad AS TEXT)) as complejidad
                FROM picks_operario p
                LEFT JOIN articulos_maestro a ON p.sku = a.sku
                WHERE p.operario_id = ? AND p.fecha >= ? AND p.sku IS NOT NULL
                GROUP BY p.sku
                HAVING COUNT(*) >= 3
                ORDER BY vel_promedio
            """, (operario_id, fecha_limite))

            skus = await cursor.fetchall()

            skus_expertos = []
            skus_debiles = []

            for sku_row in skus:
                vel_sku = sku_row['vel_promedio']
                diferencia_pct = ((vel_promedio - vel_sku) / vel_promedio * 100) if vel_promedio > 0 else 0

                if diferencia_pct > 20:  # 20% más rápido
                    skus_expertos.append({
                        "sku": sku_row['sku'],
                        "picks": sku_row['num_picks'],
                        "velocidad_seg": round(vel_sku, 1),
                        "ventaja_pct": round(diferencia_pct, 1)
                    })
                elif diferencia_pct < -20:  # 20% más lento
                    skus_debiles.append({
                        "sku": sku_row['sku'],
                        "picks": sku_row['num_picks'],
                        "velocidad_seg": round(vel_sku, 1),
                        "debilidad_pct": round(-diferencia_pct, 1)
                    })

            # Calcular especialidad
            picks_expertos = sum(s['picks'] for s in skus_expertos)
            total_picks = sum(s['picks'] for s in skus_expertos) + sum(s['picks'] for s in skus_debiles)
            especialidad_pct = round((picks_expertos / total_picks * 100) if total_picks > 0 else 0, 1)

            return {
                "operario_id": operario_id,
                "tipo": "correlacion_sku_operario",
                "periodo_dias": dias,
                "velocidad_promedio_seg": round(vel_promedio, 1),
                "skus_expertos": skus_expertos,
                "skus_debiles": skus_debiles,
                "especialidad_pct": especialidad_pct,
                "recomendacion": f"Asignar preferentemente a SKUs expertos para maximizar productividad" if skus_expertos else "Explorar oportunidades de especialización"
            }

    except Exception as e:
        return {
            "operario_id": operario_id,
            "tipo": "correlacion_sku_operario",
            "error": str(e)
        }


# ============================================================================
# 3. PATRON SEMANAL - Variación de productividad por día de semana
# ============================================================================

async def analizar_patron_semanal(operario_id: str) -> Dict[str, Any]:
    """
    Analiza cómo varía la productividad por día de semana.
    Identifica días fuertes y débiles del operario.

    Indicadores:
    - velocidad_por_dia: vel promedio para lunes, martes, etc.
    - dia_mas_fuerte: día donde es más productivo
    - dia_mas_debil: día donde es menos productivo
    - variacion_pct: diferencia entre mejor y peor día
    """
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    CAST(STRFTIME('%w', fecha) AS INTEGER) as dia_semana,
                    CASE
                        WHEN CAST(STRFTIME('%w', fecha) AS INTEGER) = 0 THEN 'Domingo'
                        WHEN CAST(STRFTIME('%w', fecha) AS INTEGER) = 1 THEN 'Lunes'
                        WHEN CAST(STRFTIME('%w', fecha) AS INTEGER) = 2 THEN 'Martes'
                        WHEN CAST(STRFTIME('%w', fecha) AS INTEGER) = 3 THEN 'Miercoles'
                        WHEN CAST(STRFTIME('%w', fecha) AS INTEGER) = 4 THEN 'Jueves'
                        WHEN CAST(STRFTIME('%w', fecha) AS INTEGER) = 5 THEN 'Viernes'
                        WHEN CAST(STRFTIME('%w', fecha) AS INTEGER) = 6 THEN 'Sabado'
                    END as nombre_dia,
                    AVG(tiempo_segundos) as vel_promedio,
                    COUNT(*) as num_picks,
                    MIN(tiempo_segundos) as mejor_tiempo,
                    MAX(tiempo_segundos) as peor_tiempo
                FROM picks_operario
                WHERE operario_id = ?
                GROUP BY dia_semana
                ORDER BY dia_semana
            """, (operario_id,))

            dias = await cursor.fetchall()

            if not dias:
                return {
                    "operario_id": operario_id,
                    "tipo": "patron_semanal",
                    "detectado": False
                }

            velocidades = []
            velocidad_por_dia = []

            for dia in dias:
                vel = dia['vel_promedio']
                velocidades.append(vel)
                velocidad_por_dia.append({
                    "dia": dia['nombre_dia'],
                    "velocidad_seg": round(vel, 1),
                    "picks": dia['num_picks'],
                    "mejor_tiempo_seg": dia['mejor_tiempo'],
                    "peor_tiempo_seg": dia['peor_tiempo']
                })

            max_vel = max(velocidades)
            min_vel = min(velocidades)
            variacion_pct = round(((max_vel - min_vel) / min_vel * 100), 1) if min_vel > 0 else 0

            dia_mas_fuerte = min(dias, key=lambda d: d['vel_promedio'])
            dia_mas_debil = max(dias, key=lambda d: d['vel_promedio'])

            return {
                "operario_id": operario_id,
                "tipo": "patron_semanal",
                "detectado": variacion_pct > 10,
                "velocidad_por_dia": velocidad_por_dia,
                "dia_mas_fuerte": dia_mas_fuerte['nombre_dia'],
                "dia_mas_debil": dia_mas_debil['nombre_dia'],
                "variacion_pct": variacion_pct,
                "recomendacion": f"Patrón detectado: máxima productividad {dia_mas_fuerte['nombre_dia']}, evaluar factores externos en {dia_mas_debil['nombre_dia']}"
            }

    except Exception as e:
        return {
            "operario_id": operario_id,
            "tipo": "patron_semanal",
            "error": str(e)
        }


# ============================================================================
# 4. RECUPERACION POST-PAUSA - Impacto de pausas en velocidad
# ============================================================================

async def analizar_recuperacion_pausa(operario_id: str) -> Dict[str, Any]:
    """
    Analiza cómo impactan las pausas en la recuperación de velocidad.

    Indicadores:
    - velocidad_pre_pausa: promedio antes de pausa
    - velocidad_post_pausa: promedio después de pausa
    - recuperacion_pct: % que mejora después
    - mejor_tipo_pausa: qué tipo de pausa es más efectiva
    """
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Obtener pausas del operario
            cursor = await db.execute("""
                SELECT
                    pausa_id,
                    timestamp_inicio,
                    timestamp_fin,
                    tipo as tipo_pausa,
                    duracion_minutos
                FROM pausas_operario
                WHERE operario_id = ?
                ORDER BY timestamp_inicio
                LIMIT 20
            """, (operario_id,))

            pausas = await cursor.fetchall()

            if not pausas:
                return {
                    "operario_id": operario_id,
                    "tipo": "recuperacion_pausa",
                    "detectado": False,
                    "razon": "Sin registro de pausas"
                }

            analisis_pausas = []

            for pausa in pausas:
                # Picks 30 minutos antes de pausa
                timestamp_inicio = pausa['timestamp_inicio']
                timestamp_hace_30 = (datetime.fromisoformat(timestamp_inicio) - timedelta(minutes=30)).isoformat()

                cursor = await db.execute("""
                    SELECT AVG(tiempo_segundos) as vel_promedio
                    FROM picks_operario
                    WHERE operario_id = ? AND timestamp >= ? AND timestamp < ?
                """, (operario_id, timestamp_hace_30, timestamp_inicio))

                vel_pre = (await cursor.fetchone())['vel_promedio'] or 30

                # Picks 30 minutos después de pausa
                timestamp_fin = pausa['timestamp_fin']
                timestamp_plus_30 = (datetime.fromisoformat(timestamp_fin) + timedelta(minutes=30)).isoformat()

                cursor = await db.execute("""
                    SELECT AVG(tiempo_segundos) as vel_promedio
                    FROM picks_operario
                    WHERE operario_id = ? AND timestamp >= ? AND timestamp < ?
                """, (operario_id, timestamp_fin, timestamp_plus_30))

                vel_post = (await cursor.fetchone())['vel_promedio'] or 30

                # Calcular recuperación (positivo = mejora)
                recuperacion_pct = round(((vel_pre - vel_post) / vel_pre * 100), 1) if vel_pre > 0 else 0

                analisis_pausas.append({
                    "tipo_pausa": pausa['tipo_pausa'],
                    "duracion_minutos": pausa['duracion_minutos'],
                    "velocidad_pre_seg": round(vel_pre, 1),
                    "velocidad_post_seg": round(vel_post, 1),
                    "recuperacion_pct": recuperacion_pct,
                    "efectivo": recuperacion_pct > 10
                })

            # Encontrar mejor tipo de pausa
            pausas_efectivas = [a for a in analisis_pausas if a['efectivo']]
            if pausas_efectivas:
                mejor_pausa = max(pausas_efectivas, key=lambda p: p['recuperacion_pct'])
                promedio_recuperacion = round(mean([a['recuperacion_pct'] for a in pausas_efectivas]), 1)
            else:
                mejor_pausa = None
                promedio_recuperacion = 0

            return {
                "operario_id": operario_id,
                "tipo": "recuperacion_pausa",
                "detectado": len(pausas_efectivas) > 0,
                "pausas_analizadas": len(analisis_pausas),
                "pausas_efectivas": len(pausas_efectivas),
                "promedio_recuperacion_pct": promedio_recuperacion,
                "mejor_tipo_pausa": mejor_pausa['tipo_pausa'] if mejor_pausa else None,
                "detalle_pausas": analisis_pausas[:5],  # Top 5
                "recomendacion": f"Pausas de {mejor_pausa['tipo_pausa']} de {mejor_pausa['duracion_minutos']} min recomendadas" if mejor_pausa else "Evaluar efectividad de pausas actuales"
            }

    except Exception as e:
        return {
            "operario_id": operario_id,
            "tipo": "recuperacion_pausa",
            "error": str(e)
        }


# ============================================================================
# 5. ANOMALIA ZSCORE - Detección de desviaciones estadísticas
# ============================================================================

async def analizar_anomalia_zscore(operario_id: str, ola_id: str = None) -> Dict[str, Any]:
    """
    Detecta anomalías usando desviación estándar (Z-score).
    Pick es anomalía si está >2 desv. est. del promedio.

    Indicadores:
    - velocidad_promedio: promedio del operario
    - desv_estandar: desviación típica
    - picks_anomalos: picks anómalamente lentos o rápidos
    - razon_probable: enfermedad, distracción, problema equipo
    """
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Obtener histórico de picks (últimos 7 días para velocidad análisis)
            fecha_limite = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

            if ola_id:
                cursor = await db.execute("""
                    SELECT tiempo_segundos
                    FROM picks_operario
                    WHERE operario_id = ? AND ola_id = ?
                """, (operario_id, ola_id))
            else:
                cursor = await db.execute("""
                    SELECT tiempo_segundos
                    FROM picks_operario
                    WHERE operario_id = ? AND fecha >= ?
                """, (operario_id, fecha_limite))

            picks = [row['tiempo_segundos'] for row in await cursor.fetchall()]

            if len(picks) < 5:
                return {
                    "operario_id": operario_id,
                    "ola_id": ola_id,
                    "tipo": "anomalia_zscore",
                    "detectado": False,
                    "razon": "Insuficientes picks para análisis estadístico"
                }

            # Calcular estadísticas
            media = mean(picks)
            try:
                desv_est = stdev(picks)
            except:
                desv_est = 0

            # Detectar anomalías (z-score > 2)
            picks_anomalos = []
            for i, tiempo in enumerate(picks):
                if desv_est > 0:
                    z_score = abs((tiempo - media) / desv_est)
                    if z_score > 2:
                        picks_anomalos.append({
                            "indice": i,
                            "tiempo_seg": tiempo,
                            "z_score": round(z_score, 2),
                            "tipo": "lento" if tiempo > media else "rapido"
                        })

            # Razón probable basada en contexto
            razon_probable = "Normal"
            if len(picks_anomalos) > 0:
                promedio_anomalas = mean([p['tiempo_seg'] for p in picks_anomalos])
                if promedio_anomalas > media * 1.5:
                    razon_probable = "Posible enfermedad, fatiga severa o problema de equipamiento"
                else:
                    razon_probable = "Variación excepcional - investigar contexto"

            return {
                "operario_id": operario_id,
                "ola_id": ola_id,
                "tipo": "anomalia_zscore",
                "detectado": len(picks_anomalos) > 0,
                "velocidad_promedio_seg": round(media, 1),
                "desv_estandar_seg": round(desv_est, 1),
                "picks_analizados": len(picks),
                "picks_anomalos": len(picks_anomalos),
                "porcentaje_anomalas": round((len(picks_anomalos) / len(picks) * 100), 1),
                "razon_probable": razon_probable,
                "muestra_anomalias": picks_anomalos[:5],
                "confianza_pct": min(100, round((len(picks_anomalos) / max(1, len(picks)) * 100) + 20, 0))
            }

    except Exception as e:
        return {
            "operario_id": operario_id,
            "tipo": "anomalia_zscore",
            "error": str(e)
        }


# ============================================================================
# FUNCIÓN CONSOLIDADA - Ejecutar todos los análisis
# ============================================================================

async def ejecutar_todos_analisis(operario_id: str, ola_id: str = None) -> Dict[str, Any]:
    """
    Ejecuta los 5 análisis inteligentes de una vez y retorna consolidado.
    """
    resultados = {
        "operario_id": operario_id,
        "ola_id": ola_id,
        "timestamp": datetime.now().isoformat(),
        "analisis": {}
    }

    # Ejecutar los 5 análisis en paralelo
    if ola_id:
        resultados["analisis"]["caida_progresiva"] = await analizar_caida_progresiva(operario_id, ola_id)

    resultados["analisis"]["correlacion_sku_operario"] = await analizar_correlacion_sku_operario(operario_id)
    resultados["analisis"]["patron_semanal"] = await analizar_patron_semanal(operario_id)
    resultados["analisis"]["recuperacion_pausa"] = await analizar_recuperacion_pausa(operario_id)
    resultados["analisis"]["anomalia_zscore"] = await analizar_anomalia_zscore(operario_id, ola_id)

    return resultados
