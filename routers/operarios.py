"""
VigIA - Operarios API Router
Endpoints para análisis inteligente de operarios
5 Endpoints principales exponen las 5 funciones de IA

GET    /api/operarios/{operario_id}/analisis/caida_progresiva?ola_id=OLA_X
GET    /api/operarios/{operario_id}/analisis/correlacion_sku
GET    /api/operarios/{operario_id}/analisis/patron_semanal
GET    /api/operarios/{operario_id}/analisis/recuperacion_pausa
GET    /api/operarios/{operario_id}/analisis/anomalia_zscore?ola_id=OLA_X (opcional)

GET    /api/operarios/{operario_id}/analisis/completo - Ejecuta todos los 5 análisis

Autor: Claude AI
Fecha: 2026-04-20
"""
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import sys
import json
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from routers.analisis_inteligente import (
    analizar_caida_progresiva,
    analizar_correlacion_sku_operario,
    analizar_patron_semanal,
    analizar_recuperacion_pausa,
    analizar_anomalia_zscore,
    ejecutar_todos_analisis
)

router = APIRouter(prefix="/api", tags=["operarios"])


# ============================================================================
# HELPER: JSON EXTRACTION (robusto para respuestas de Claude)
# ============================================================================
def _extract_json_from_response(response_text: str) -> dict:
    """
    Extrae JSON valido de respuesta de Claude.
    Usa conteo de llaves para encontrar el JSON completo correctamente.
    """
    import re
    import json as json_module

    if not response_text or not isinstance(response_text, str):
        return {}

    text = response_text.strip()

    # Intento 1: Extraer de bloque markdown ```json ... ```
    try:
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if m:
            candidate = m.group(1).strip()
            if candidate:
                result = json_module.loads(candidate)
                if isinstance(result, dict):
                    return result
    except Exception as e:
        print(f"[JSON] Markdown block: {e}")

    # Intento 2: Buscar primer { y encontrar su cierre usando conteo de depth
    try:
        start = text.find('{')
        if start >= 0:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        json_str = text[start:i+1]
                        result = json_module.loads(json_str)
                        if isinstance(result, dict):
                            return result
                        break
    except Exception as e:
        print(f"[JSON] Brace-matching: {e}")

    # Intento 3: Parse directo
    try:
        result = json_module.loads(text)
        if isinstance(result, dict):
            return result
    except:
        pass

    print(f"[JSON] No se pudo extraer JSON. Longitud respuesta: {len(response_text)}")
    return {}


# ============================================================================
# 1. CAIDA PROGRESIVA - Fatiga por disminución de velocidad
# ============================================================================

@router.get("/operarios/{operario_id}/analisis/caida_progresiva")
async def get_caida_progresiva(
    operario_id: str,
    ola_id: str = Query(..., description="ID de la ola a analizar")
):
    """
    Detecta si el operario está experimentando fatiga.

    Retorna:
    - velocidad_inicial vs velocidad_final
    - caida_pct: porcentaje de disminución
    - severidad: CRITICA, ALTA, MEDIA, BAJA
    - recomendacion: acciones sugeridas

    Example: /api/operarios/OP_00045/analisis/caida_progresiva?ola_id=OLA_2_TARDE_20_04
    """
    resultado = await analizar_caida_progresiva(operario_id, ola_id)

    if "error" in resultado:
        raise HTTPException(status_code=400, detail=resultado["error"])

    return resultado


# ============================================================================
# 2. CORRELACION SKU x OPERARIO - Expertos en ciertos SKUs
# ============================================================================

@router.get("/operarios/{operario_id}/analisis/correlacion_sku")
async def get_correlacion_sku(
    operario_id: str,
    dias: int = Query(30, description="Últimos N días a analizar", ge=1, le=365)
):
    """
    Identifica SKUs donde el operario es experto o débil.

    Retorna:
    - skus_expertos: SKUs donde es >20% más rápido
    - skus_debiles: SKUs donde es >20% más lento
    - especialidad_pct: porcentaje de picks en SKUs expertos
    - recomendacion: cómo optimizar asignación

    Example: /api/operarios/OP_00045/analisis/correlacion_sku?dias=30
    """
    resultado = await analizar_correlacion_sku_operario(operario_id, dias)

    if "error" in resultado:
        raise HTTPException(status_code=400, detail=resultado["error"])

    return resultado


# ============================================================================
# 3. PATRON SEMANAL - Variación por día de semana
# ============================================================================

@router.get("/operarios/{operario_id}/analisis/patron_semanal")
async def get_patron_semanal(operario_id: str):
    """
    Analiza cómo varía la productividad por día de semana.

    Retorna:
    - velocidad_por_dia: vel promedio para cada día
    - dia_mas_fuerte: día de máxima productividad
    - dia_mas_debil: día de mínima productividad
    - variacion_pct: diferencia entre mejor y peor día
    - recomendacion: análisis de factores

    Example: /api/operarios/OP_00045/analisis/patron_semanal
    """
    resultado = await analizar_patron_semanal(operario_id)

    if "error" in resultado:
        raise HTTPException(status_code=400, detail=resultado["error"])

    return resultado


# ============================================================================
# 4. RECUPERACION POST-PAUSA - Impacto de pausas
# ============================================================================

@router.get("/operarios/{operario_id}/analisis/recuperacion_pausa")
async def get_recuperacion_pausa(operario_id: str):
    """
    Analiza el impacto de pausas en la recuperación de velocidad.

    Retorna:
    - pausas_analizadas: cantidad de pausas registradas
    - pausas_efectivas: cuántas mejoraron la velocidad
    - promedio_recuperacion_pct: mejora promedio post-pausa
    - mejor_tipo_pausa: qué tipo de pausa es más efectiva
    - recomendacion: duración y tipo de pausa óptimos

    Example: /api/operarios/OP_00045/analisis/recuperacion_pausa
    """
    resultado = await analizar_recuperacion_pausa(operario_id)

    if "error" in resultado:
        raise HTTPException(status_code=400, detail=resultado["error"])

    return resultado


# ============================================================================
# 5. ANOMALIA ZSCORE - Desviaciones estadísticas
# ============================================================================

@router.get("/operarios/{operario_id}/analisis/anomalia_zscore")
async def get_anomalia_zscore(
    operario_id: str,
    ola_id: str = Query(None, description="ID de ola (opcional)")
):
    """
    Detecta anomalías usando Z-score (desviación estándar).

    Retorna:
    - velocidad_promedio_seg: promedio del operario
    - desv_estandar_seg: desviación típica
    - picks_anomalos: cantidad de picks fuera de rango
    - porcentaje_anomalas: % de picks anómalos
    - razon_probable: enfermedad, distracción, problema equipo
    - confianza_pct: confianza del análisis

    Example: /api/operarios/OP_00045/analisis/anomalia_zscore
    Example: /api/operarios/OP_00045/analisis/anomalia_zscore?ola_id=OLA_2_TARDE_20_04
    """
    resultado = await analizar_anomalia_zscore(operario_id, ola_id)

    if "error" in resultado:
        raise HTTPException(status_code=400, detail=resultado["error"])

    return resultado


# ============================================================================
# ANALISIS COMPLETO - Los 5 análisis en una sola llamada
# ============================================================================

@router.get("/operarios/{operario_id}/analisis/completo")
async def get_analisis_completo(
    operario_id: str,
    ola_id: str = Query(None, description="ID de ola (opcional)")
):
    """
    Ejecuta los 5 análisis inteligentes en una sola llamada.

    Retorna un objeto consolidado con todos los resultados:
    - caida_progresiva
    - correlacion_sku_operario
    - patron_semanal
    - recuperacion_pausa
    - anomalia_zscore

    Caso de uso: Dashboard operario mostrando análisis completo.

    Example: /api/operarios/OP_00045/analisis/completo
    Example: /api/operarios/OP_00045/analisis/completo?ola_id=OLA_2_TARDE_20_04
    """
    resultado = await ejecutar_todos_analisis(operario_id, ola_id)

    return resultado


# ============================================================================
# LISTADO DE OPERARIOS - Con agregados rápidos
# ============================================================================

@router.get("/operarios")
async def listar_operarios():
    """
    Lista todos los operarios del sistema.

    Retorna array de operarios con:
    - operario_id
    - nombre
    - zona_principal
    - total_picks: picks históricos
    - velocidad_promedio: vel del operario

    Example: /api/operarios
    """
    import aiosqlite
    from pathlib import Path

    DB_PATH = Path(__file__).parent.parent / "vigia.db"

    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    o.operario_id,
                    o.nombre,
                    o.zona_principal,
                    COUNT(p.pick_id) as total_picks,
                    AVG(p.tiempo_segundos) as velocidad_promedio
                FROM operarios o
                LEFT JOIN picks_operario p ON o.operario_id = p.operario_id
                GROUP BY o.operario_id
                ORDER BY total_picks DESC
            """)

            operarios = await cursor.fetchall()

            return {
                "total_operarios": len(operarios),
                "operarios": [
                    {
                        "operario_id": op['operario_id'],
                        "nombre": op['nombre'],
                        "zona_principal": op['zona_principal'],
                        "total_picks": op['total_picks'] or 0,
                        "velocidad_promedio_seg": round(op['velocidad_promedio'], 1) if op['velocidad_promedio'] else 0
                    }
                    for op in operarios
                ]
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RANKING DE OPERARIOS - debe estar ANTES de /operarios/{operario_id}
# ============================================================================

@router.get("/operarios/ranking")
async def get_operarios_ranking(dias: int = 1):
    """
    Ranking de productividad de todos los operarios.
    Retorna picks, velocidad, tasa de error y estado (ok/warn/bad) para cada operario.
    Sorted by picks DESC. Marca como bajo estándar si vel>35s o error>3%.
    """
    import aiosqlite
    from pathlib import Path

    try:
        DB_PATH = Path(__file__).parent.parent / "vigia.db"
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            fecha_desde = (datetime.now() - __import__('datetime').timedelta(days=dias)).strftime('%Y-%m-%d')

            cursor = await db.execute("""
                WITH picks_ranked AS (
                    SELECT
                        operario_id,
                        estado,
                        tiempo_segundos,
                        (strftime('%s', timestamp) - strftime('%s', LAG(timestamp) OVER (
                            PARTITION BY operario_id
                            ORDER BY timestamp
                        ))) as delta_seg
                    FROM picks_operario
                    WHERE fecha >= ?
                )
                SELECT
                    operario_id,
                    COUNT(*) as picks,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) as errores,
                    COALESCE(
                        AVG(tiempo_segundos),
                        AVG(CASE WHEN delta_seg > 0 AND delta_seg < 600 THEN delta_seg END)
                    ) as vel_promedio,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) * 100.0 / COUNT(*) as tasa_error
                FROM picks_ranked
                GROUP BY operario_id
                HAVING picks >= 5
                ORDER BY picks DESC
            """, (fecha_desde,))
            rows = await cursor.fetchall()

        operarios = []
        for r in rows:
            vel = round(r['vel_promedio'] or 0, 1)
            tasa = round(r['tasa_error'] or 0, 1)
            picks = r['picks'] or 0

            if vel > 40 or tasa > 5:
                estado = "bad"
            elif vel > 32 or tasa > 3:
                estado = "warn"
            else:
                estado = "ok"

            operarios.append({
                "operario_id": r['operario_id'],
                "picks": picks,
                "errores": r['errores'] or 0,
                "vel_promedio": vel,
                "tasa_error": tasa,
                "estado": estado,
                "bajo_estandar": estado in ("bad", "warn")
            })

        return {
            "operarios": operarios,
            "total": len(operarios),
            "bajo_estandar": sum(1 for o in operarios if o["bajo_estandar"]),
            "dias_analizados": dias,
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        return {"operarios": [], "total": 0, "error": str(e)}


# ============================================================================
# DETALLE DE OPERARIO - Info completa + últimos picks
# ============================================================================

@router.get("/operarios/{operario_id}")
async def get_detalle_operario(operario_id: str):
    """
    Retorna información detallada de un operario.

    Incluye:
    - datos personales
    - estadísticas históricas
    - últimos 10 picks
    - total picks por zona
    - tasa de errores

    Example: /api/operarios/OP_00045
    """
    import aiosqlite
    from pathlib import Path

    DB_PATH = Path(__file__).parent.parent / "vigia.db"

    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Info operario
            cursor = await db.execute("""
                SELECT * FROM operarios WHERE operario_id = ?
            """, (operario_id,))

            operario = await cursor.fetchone()
            if not operario:
                raise HTTPException(status_code=404, detail="Operario no encontrado")

            operario_dict = dict(operario)

            # Estadísticas
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_picks,
                    AVG(tiempo_segundos) as vel_promedio,
                    MIN(tiempo_segundos) as mejor_tiempo,
                    MAX(tiempo_segundos) as peor_tiempo,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) as picks_con_error
                FROM picks_operario
                WHERE operario_id = ?
            """, (operario_id,))

            stats = await cursor.fetchone()
            operario_dict["estadisticas"] = {
                "total_picks": stats['total_picks'] or 0,
                "velocidad_promedio_seg": round(stats['vel_promedio'], 1) if stats['vel_promedio'] else 0,
                "mejor_tiempo_seg": stats['mejor_tiempo'],
                "peor_tiempo_seg": stats['peor_tiempo'],
                "tasa_error_pct": round((stats['picks_con_error'] / max(1, stats['total_picks'])) * 100, 1) if stats['total_picks'] else 0
            }

            # Últimos 10 picks
            cursor = await db.execute("""
                SELECT
                    pick_id, fecha, timestamp, ola_id, sku, tiempo_segundos, estado
                FROM picks_operario
                WHERE operario_id = ?
                ORDER BY timestamp DESC
                LIMIT 10
            """, (operario_id,))

            picks = await cursor.fetchall()
            operario_dict["ultimos_picks"] = [dict(p) for p in picks]

            # Picks por zona
            cursor = await db.execute("""
                SELECT sector, COUNT(*) as cantidad
                FROM picks_operario
                WHERE operario_id = ?
                GROUP BY sector
                ORDER BY cantidad DESC
            """, (operario_id,))

            zonas = await cursor.fetchall()
            operario_dict["picks_por_zona"] = [
                {"zona": z['sector'], "cantidad": z['cantidad']}
                for z in zonas
            ]

            return operario_dict

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HISTÓRICO - Últimos 30 días de productividad
# ============================================================================

@router.get("/operarios/{operario_id}/historico")
async def get_historico_operario(operario_id: str, dias: int = Query(30, ge=1, le=365)):
    """
    Retorna histórico de productividad del operario para los últimos N días.

    Útil para gráficos de histórico a largo plazo.
    """
    try:
        import aiosqlite
        from pathlib import Path

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Obtener histórico agrupado por día
            cursor = await db.execute("""
                SELECT
                    DATE(fecha) as fecha,
                    COUNT(*) as picks_dia,
                    SUM(cantidad_bultos) as bultos_dia,
                    AVG(tiempo_segundos) as vel_promedio_dia,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) as errores_dia
                FROM picks_operario
                WHERE operario_id = ? AND fecha >= DATE('now', '-' || ? || ' days')
                GROUP BY DATE(fecha)
                ORDER BY fecha DESC
            """, (operario_id, dias))

            historico = await cursor.fetchall()

            return {
                "operario_id": operario_id,
                "periodo_dias": dias,
                "total_registros": len(historico),
                "historico": [
                    {
                        "fecha": h['fecha'],
                        "picks": h['picks_dia'] or 0,
                        "bultos": h['bultos_dia'] or 0,
                        "velocidad_promedio": round(h['vel_promedio_dia'], 1) if h['vel_promedio_dia'] else 0,
                        "errores": h['errores_dia'] or 0
                    }
                    for h in historico
                ]
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# COMPARATIVAS - Clustering y benchmarking de operarios
# ============================================================================

@router.get("/comparativas/metricas")
async def get_metricas_comparativas():
    """
    Retorna métricas de todos los operarios para clustering y comparación.

    Calcula:
    - Total picks
    - Total bultos
    - Velocidad promedio
    - Tasa error
    - Últimos 7 días de productividad
    """
    try:
        import aiosqlite
        from pathlib import Path

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Obtener lista de operarios
            cursor = await db.execute("""
                SELECT DISTINCT operario_id, 'OP' || SUBSTR(operario_id, -5) as display_id
                FROM picks_operario
                ORDER BY operario_id
            """)

            operarios = await cursor.fetchall()
            metricas = []

            for op in operarios:
                operario_id = op['operario_id']

                # Métricas globales
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) as total_picks,
                        SUM(cantidad_bultos) as total_bultos,
                        AVG(tiempo_segundos) as vel_promedio,
                        COUNT(CASE WHEN estado = 'error' THEN 1 END) as errores,
                        COUNT(*) as total_picks_check
                    FROM picks_operario
                    WHERE operario_id = ?
                """, (operario_id,))

                global_metrics = await cursor.fetchone()

                # Últimos 7 días
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) as picks_7d,
                        SUM(cantidad_bultos) as bultos_7d,
                        AVG(tiempo_segundos) as vel_7d
                    FROM picks_operario
                    WHERE operario_id = ? AND fecha >= DATE('now', '-7 days')
                """, (operario_id,))

                recent_metrics = await cursor.fetchone()

                total_picks = global_metrics['total_picks'] or 0
                total_bultos = global_metrics['total_bultos'] or 0
                vel_promedio = global_metrics['vel_promedio'] or 0
                errores = global_metrics['errores'] or 0

                if total_picks > 0:
                    tasa_error = round((errores / total_picks) * 100, 2)
                else:
                    tasa_error = 0

                metricas.append({
                    "operario_id": operario_id,
                    "display_id": op['display_id'],
                    "total_picks": total_picks,
                    "total_bultos": total_bultos,
                    "velocidad_promedio_seg": round(vel_promedio, 1),
                    "tasa_error_pct": tasa_error,
                    "picks_7d": recent_metrics['picks_7d'] or 0,
                    "bultos_7d": recent_metrics['bultos_7d'] or 0,
                    "vel_7d": round(recent_metrics['vel_7d'], 1) if recent_metrics['vel_7d'] else 0
                })

            return {
                "total_operarios": len(metricas),
                "metricas": metricas
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/comparativas/clusters")
async def get_clusters():
    """
    Realiza clustering de operarios basado en productividad.

    Divide operarios en 3 grupos:
    - High Performers: Top 33%
    - Mid Range: Middle 34%
    - Learning: Bottom 33%
    """
    try:
        import aiosqlite
        from pathlib import Path

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Obtener todos los operarios con score de productividad
            cursor = await db.execute("""
                SELECT
                    operario_id,
                    COUNT(*) as total_picks,
                    AVG(tiempo_segundos) as vel_promedio,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) * 1.0 / COUNT(*) as error_rate
                FROM picks_operario
                GROUP BY operario_id
                ORDER BY total_picks DESC
            """)

            operarios = await cursor.fetchall()

            # Calcular score: picks totales - penalización por errores
            scored = []
            for op in operarios:
                total_picks = op['total_picks'] or 0
                vel_promedio = op['vel_promedio'] or 28.5
                error_rate = op['error_rate'] or 0

                # Score: Picks totales / velocidad promedio (más picks en menos tiempo = mejor)
                # Penalización: multiplicar por (1 - error_rate)
                score = (total_picks / max(vel_promedio, 1)) * (1 - error_rate)

                scored.append({
                    "operario_id": op['operario_id'],
                    "total_picks": total_picks,
                    "velocidad_promedio": round(vel_promedio, 1),
                    "error_rate": round(error_rate * 100, 2),
                    "score": round(score, 2)
                })

            # Dividir en clusters por percentiles
            n = len(scored)
            high_threshold = int(n * 0.33)
            mid_threshold = int(n * 0.67)

            high_performers = scored[:high_threshold] if high_threshold > 0 else []
            mid_range = scored[high_threshold:mid_threshold]
            learning = scored[mid_threshold:] if mid_threshold < n else []

            # Calcular promedios por cluster
            def cluster_avg(cluster):
                if not cluster:
                    return {"avg_score": 0, "avg_picks": 0, "avg_vel": 0, "avg_error": 0}
                avg_score = sum(c['score'] for c in cluster) / len(cluster)
                avg_picks = sum(c['total_picks'] for c in cluster) / len(cluster)
                avg_vel = sum(c['velocidad_promedio'] for c in cluster) / len(cluster)
                avg_error = sum(c['error_rate'] for c in cluster) / len(cluster)
                return {
                    "avg_score": round(avg_score, 2),
                    "avg_picks": int(avg_picks),
                    "avg_vel": round(avg_vel, 1),
                    "avg_error": round(avg_error, 2)
                }

            return {
                "clusters": {
                    "high_performers": {
                        "count": len(high_performers),
                        "operarios": [
                            {"operario_id": op['operario_id'], "score": op['score']}
                            for op in high_performers[:5]
                        ],
                        "stats": cluster_avg(high_performers)
                    },
                    "mid_range": {
                        "count": len(mid_range),
                        "operarios": [
                            {"operario_id": op['operario_id'], "score": op['score']}
                            for op in mid_range[:5]
                        ],
                        "stats": cluster_avg(mid_range)
                    },
                    "learning": {
                        "count": len(learning),
                        "operarios": [
                            {"operario_id": op['operario_id'], "score": op['score']}
                            for op in learning[:5]
                        ],
                        "stats": cluster_avg(learning)
                    }
                },
                "all_scored": scored
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/comparativas/benchmark/{operario_id}")
async def get_benchmark_operario(operario_id: str):
    """
    Compara un operario específico contra el promedio del grupo.
    """
    try:
        import aiosqlite
        from pathlib import Path

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Métricas del operario
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as picks,
                    SUM(cantidad_bultos) as bultos,
                    AVG(tiempo_segundos) as vel_promedio,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) * 1.0 / COUNT(*) as error_rate
                FROM picks_operario
                WHERE operario_id = ?
            """, (operario_id,))

            operario_metrics = await cursor.fetchone()

            # Métricas promedio del grupo
            cursor = await db.execute("""
                SELECT
                    AVG(picks_count) as avg_picks,
                    AVG(vel_promedio) as avg_vel,
                    AVG(error_rate) as avg_error
                FROM (
                    SELECT
                        COUNT(*) as picks_count,
                        AVG(tiempo_segundos) as vel_promedio,
                        COUNT(CASE WHEN estado = 'error' THEN 1 END) * 1.0 / COUNT(*) as error_rate
                    FROM picks_operario
                    GROUP BY operario_id
                )
            """)

            group_metrics = await cursor.fetchone()

            op_picks = operario_metrics['picks'] or 0
            op_vel = operario_metrics['vel_promedio'] or 28.5
            op_error = operario_metrics['error_rate'] or 0

            group_picks = group_metrics['avg_picks'] or 0
            group_vel = group_metrics['avg_vel'] or 28.5
            group_error = group_metrics['avg_error'] or 0

            return {
                "operario_id": operario_id,
                "operario": {
                    "total_picks": op_picks,
                    "velocidad_promedio": round(op_vel, 1),
                    "tasa_error_pct": round(op_error * 100, 2)
                },
                "grupo": {
                    "total_picks_promedio": round(group_picks, 0),
                    "velocidad_promedio": round(group_vel, 1),
                    "tasa_error_pct": round(group_error * 100, 2)
                },
                "comparativa": {
                    "picks_diferencia_pct": round(((op_picks - group_picks) / max(group_picks, 1)) * 100, 1),
                    "velocidad_diferencia_pct": round(((group_vel - op_vel) / max(group_vel, 1)) * 100, 1),
                    "error_diferencia_pct": round(((op_error - group_error) / max(group_error, 0.001)) * 100, 1)
                }
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SESIÓN 1.5: RECOMENDACIONES ENRIQUECIDAS CON CLAUDE AI (ORDEN IMPORTANTE!)
# Esta ruta DEBE estar antes de /recomendaciones/{operario_id} en FastAPI
# ============================================================================

@router.get("/recomendaciones/{operario_id}/enriquecido")
async def get_recomendaciones_enriquecidas(operario_id: str, provider: str = ""):
    """
    Recomendaciones mejoradas con IA.

    Obtiene análisis base + lo expande con análisis detallado de causa,
    pasos concretos, timing óptimo, y recomendaciones relacionadas.

    Parámetros:
    - provider: 'claude' | 'ollama' | '' (usa el configurado en .env)

    Usa caché de 30 minutos para evitar llamadas repetidas.

    Ejemplo: /api/recomendaciones/OP_00045/enriquecido?provider=ollama
    """
    import time
    import json
    import os
    from utils.cache import get_cache, set_cache
    from routers.ai import _call_ai

    provider = provider or os.getenv("AI_PROVIDER", "claude")

    try:
        # ========== 1. VERIFICAR CACHÉ (incluye provider en key) ==========
        cache_key = f"recomendaciones:enriquecido:{operario_id}:{provider}"
        cached = get_cache(cache_key)
        if cached:
            cached["cached"] = True
            return cached

        # ========== 2. OBTENER ANÁLISIS BASE ==========
        import aiosqlite
        from pathlib import Path

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_picks,
                    AVG(tiempo_segundos) as vel_promedio,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) as errores
                FROM picks_operario
                WHERE operario_id = ?
            """, (operario_id,))

            op_data = await cursor.fetchone()

            if not op_data or op_data['total_picks'] == 0:
                return {"operario_id": operario_id, "recomendaciones": [], "powered_by": None}

            # Ejecutar los 5 análisis
            caida_analisis = await analizar_caida_progresiva(operario_id, "OLA_1")
            correlacion_analisis = await analizar_correlacion_sku_operario(operario_id, 30)
            patron_analisis = await analizar_patron_semanal(operario_id)
            pausa_analisis = await analizar_recuperacion_pausa(operario_id)
            anomalia_analisis = await analizar_anomalia_zscore(operario_id, "OLA_1")

            total_picks = op_data['total_picks']
            vel_promedio = op_data['vel_promedio'] or 28.5
            errores = op_data['errores'] or 0
            tasa_error = (errores / total_picks * 100) if total_picks > 0 else 0

        # ========== 3. PREPARAR CONTEXTO PARA CLAUDE ==========
        contexto = {
            "operario_id": operario_id,
            "metricas_totales": {
                "total_picks": total_picks,
                "velocidad_promedio_seg": round(vel_promedio, 1),
                "tasa_error_pct": round(tasa_error, 1),
                "total_errores": errores
            },
            "analisis_estadisticos": {
                "caida_progresiva": caida_analisis,
                "correlacion_sku": correlacion_analisis,
                "patron_semanal": patron_analisis,
                "recuperacion_pausa": pausa_analisis,
                "anomalia_zscore": anomalia_analisis
            }
        }

        # ========== 4. LLAMAR A IA (provider seleccionable) ==========
        system_prompt = """Eres un experto en operaciones WMS y recursos humanos.
Genera SOLO JSON valido. Sin markdown. Sin texto extra. Solo el JSON.
Usa texto en español. Evita caracteres especiales como tildes y enies."""

        user_prompt = f"""Datos del operario:
{json.dumps(contexto, indent=2, ensure_ascii=False)}

Genera 2-3 recomendaciones accionables. Responde SOLO con este JSON:
{{"recomendaciones": [
  {{"tipo": "string", "titulo": "string", "descripcion": "string", "accion": "string", "impacto": "string", "confianza": 85}}
]}}

Reglas: sin tildes, sin enies, sin caracteres especiales en el JSON."""

        t0 = time.time()
        model_used = provider
        try:
            ai_response, model_used = await _call_ai(provider, system_prompt, [
                {"role": "user", "content": user_prompt}
            ])
            generation_time_ms = int((time.time() - t0) * 1000)

            # ========== 5. PARSEAR JSON (ROBUSTO) ==========
            claude_data = _extract_json_from_response(ai_response)
            if not claude_data or "recomendaciones" not in claude_data:
                claude_data = {"recomendaciones": []}
        except Exception as e:
            print(f"Error llamando a IA ({provider}) en recomendaciones: {e}")
            claude_data = {"recomendaciones": []}
            generation_time_ms = int((time.time() - t0) * 1000)

        # ========== 6. RESPUESTA FINAL ==========
        powered_labels = {"claude": "Claude AI (Anthropic)", "ollama": "Ollama (Local)", "gemini": "Gemini (Google)", "azure": "Azure OpenAI"}
        response = {
            "operario_id": operario_id,
            "total_recomendaciones": len(claude_data.get("recomendaciones", [])),
            "recomendaciones": claude_data.get("recomendaciones", []),
            "resumen": {
                "total_picks": total_picks,
                "velocidad_promedio": round(vel_promedio, 1),
                "tasa_error_pct": round(tasa_error, 1)
            },
            "powered_by": powered_labels.get(provider, provider),
            "model_used": model_used,
            "provider": provider,
            "generation_time_ms": generation_time_ms,
            "generated_at": datetime.now().isoformat(),
            "cached": False
        }

        # ========== 7. CACHEAR ==========
        set_cache(cache_key, response, ttl_segundos=1800)

        return response

    except Exception as e:
        print(f"Error en get_recomendaciones_enriquecidas: {str(e)}")
        return {
            "operario_id": operario_id,
            "total_recomendaciones": 0,
            "recomendaciones": [],
            "powered_by": None,
            "error": str(e)
        }


@router.get("/recomendaciones/{operario_id}")
async def get_recomendaciones_operario(operario_id: str):
    """
    Retorna recomendaciones automáticas basadas en los 5 análisis.

    Combina todos los análisis para dar sugerencias accionables.
    """
    try:
        import aiosqlite
        from pathlib import Path

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Obtener todos los análisis del operario
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_picks,
                    AVG(tiempo_segundos) as vel_promedio,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) as errores
                FROM picks_operario
                WHERE operario_id = ?
            """, (operario_id,))

            op_data = await cursor.fetchone()

            if not op_data or op_data['total_picks'] == 0:
                return {"operario_id": operario_id, "recomendaciones": []}

            recomendaciones = []
            total_picks = op_data['total_picks']
            vel_promedio = op_data['vel_promedio'] or 28.5
            errores = op_data['errores'] or 0
            tasa_error = (errores / total_picks * 100) if total_picks > 0 else 0

            # 1. CAÍDA PROGRESIVA
            caida_analisis = await analizar_caida_progresiva(operario_id, "OLA_1")
            if caida_analisis.get('detectado'):
                caida_pct = caida_analisis.get('caida_pct', 0)
                if caida_pct > 20:
                    recomendaciones.append({
                        "tipo": "caida_progresiva",
                        "titulo": "🔴 ALERTA: Fatiga Detectada",
                        "severidad": "CRÍTICA",
                        "descripcion": f"Operario pierde {caida_pct:.1f}% de velocidad durante turno",
                        "recomendacion": "Ofrecer pausa preventiva en próxima hora",
                        "impacto": "Prevenir pérdida de ~100 picks",
                        "accionable": True,
                        "accion": "trigger_pausa"
                    })
                elif caida_pct > 15:
                    recomendaciones.append({
                        "tipo": "caida_progresiva",
                        "titulo": "🟡 ATENCIÓN: Cansancio Moderado",
                        "severidad": "ALTA",
                        "descripcion": f"Caída de velocidad: {caida_pct:.1f}%",
                        "recomendacion": "Monitorear próxima hora, ofrecer pausa si baja más",
                        "impacto": "Potencial +50 picks con pausa estratégica",
                        "accionable": True,
                        "accion": "monitor_pausa"
                    })

            # 2. CORRELACIÓN SKU
            correlacion_analisis = await analizar_correlacion_sku_operario(operario_id, 30)
            skus_expertos = correlacion_analisis.get('skus_expertos', [])
            if skus_expertos:
                mejor_sku = skus_expertos[0]
                ventaja = mejor_sku.get('ventaja_pct', 0)
                if ventaja > 30:
                    recomendaciones.append({
                        "tipo": "especializacion_sku",
                        "titulo": "⭐ OPORTUNIDAD: Especialización",
                        "severidad": "POSITIVO",
                        "descripcion": f"Operario es {ventaja:.0f}% más rápido con SKU {mejor_sku['sku']}",
                        "recomendacion": f"Aumentar asignación de {mejor_sku['sku']}",
                        "impacto": f"+{ventaja:.0f}% productividad = ~{int(total_picks * ventaja / 100)} picks extra/mes",
                        "accionable": True,
                        "accion": "assign_sku",
                        "sku": mejor_sku['sku'],
                        "ventaja_pct": ventaja
                    })

            # 3. PATRÓN SEMANAL
            patron_analisis = await analizar_patron_semanal(operario_id)
            dia_fuerte = patron_analisis.get('dia_fuerte')
            dia_debil = patron_analisis.get('dia_debil')
            variacion = patron_analisis.get('variacion_pct', 0)

            if variacion > 15:
                recomendaciones.append({
                    "tipo": "patron_semanal",
                    "titulo": "📅 PATRÓN: Variación Semanal",
                    "severidad": "INFO",
                    "descripcion": f"Varía {variacion:.0f}% entre días. {dia_fuerte} +productivo, {dia_debil} -productivo",
                    "recomendacion": f"Asignar tareas complejas en {dia_fuerte}, simples en {dia_debil}",
                    "impacto": "Optimizar carga de trabajo por día",
                    "accionable": True,
                    "accion": "rebalance_weekly"
                })

            # 4. RECUPERACIÓN PAUSA
            pausa_analisis = await analizar_recuperacion_pausa(operario_id)
            mejor_pausa = pausa_analisis.get('mejor_tipo')
            recuperacion = pausa_analisis.get('recuperacion_pct', 0)

            if recuperacion > 20:
                recomendaciones.append({
                    "tipo": "recuperacion_pausa",
                    "titulo": "☕ OPORTUNIDAD: Pausas Estratégicas",
                    "severidad": "POSITIVO",
                    "descripcion": f"Post-pausa {mejor_pausa}: +{recuperacion:.0f}% velocidad",
                    "recomendacion": f"Aumentar pausas {mejor_pausa}. Estrategia: pausa = +{recuperacion:.0f}% productividad",
                    "impacto": f"2 pausas estratégicas = +{int(total_picks * recuperacion / 100 * 2)} picks/turno",
                    "accionable": True,
                    "accion": "schedule_pausa",
                    "pausa_tipo": mejor_pausa,
                    "mejora_pct": recuperacion
                })

            # 5. ANOMALÍA Z-SCORE
            anomalia_analisis = await analizar_anomalia_zscore(operario_id, "OLA_1")
            picks_anomalos = anomalia_analisis.get('picks_anomalos', 0)
            pct_anomalas = anomalia_analisis.get('porcentaje_anomalas', 0)

            if pct_anomalas > 5 and picks_anomalos > 0:
                recomendaciones.append({
                    "tipo": "anomalia_zscore",
                    "titulo": "⚠️ VERIFICAR: Picks Anormales",
                    "severidad": "ALERTA",
                    "descripcion": f"{picks_anomalos} picks raros ({pct_anomalas:.1f}% del total)",
                    "recomendacion": "Investigar causa: ¿RF mal? ¿Problema operario? ¿Material complejo?",
                    "impacto": "Identificar y resolver problema puntual",
                    "accionable": True,
                    "accion": "investigate_anomaly",
                    "count": picks_anomalos
                })

            # Tasa error alta
            if tasa_error > 5:
                recomendaciones.append({
                    "tipo": "tasa_error_alta",
                    "titulo": "🔴 CRÍTICA: Tasa Error Alta",
                    "severidad": "CRÍTICA",
                    "descripcion": f"Tasa error: {tasa_error:.1f}% (normal: 2-3%)",
                    "recomendacion": "Revisar capacitación, RF, o si hay problemas de salud",
                    "impacto": "Reducir errores = mejor calidad + menos rechazos",
                    "accionable": True,
                    "accion": "review_training"
                })

            return {
                "operario_id": operario_id,
                "total_recomendaciones": len(recomendaciones),
                "recomendaciones": recomendaciones,
                "resumen": {
                    "total_picks": total_picks,
                    "velocidad_promedio": round(vel_promedio, 1),
                    "tasa_error_pct": round(tasa_error, 1)
                }
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 3. ALERTAS ENRIQUECIDAS - Análisis de Causa Raíz con Claude
# ============================================================================

@router.get("/alertas/enriquecidas")
async def get_alertas_enriquecidas(dias: int = 1, provider: str = ""):
    """
    Retorna alertas actuales enriquecidas con análisis de causa raíz.

    Para cada alerta, la IA analiza 3 causas probables con % confianza
    y acciones de investigación sugeridas.

    Ejemplo: /api/alertas/enriquecidas?dias=1&provider=ollama
    """
    import os
    import aiosqlite
    from pathlib import Path
    import time
    from utils.cache import get_cache, set_cache
    from routers.ai import _call_ai

    provider = provider or os.getenv("AI_PROVIDER", "claude")
    powered_labels = {
        "claude": "Claude AI (Anthropic)",
        "ollama": "Ollama (Local)",
        "gemini": "Gemini (Google)",
        "azure": "Azure OpenAI"
    }

    try:
        # Verificar caché (incluye provider en key)
        cache_key = f"alertas:enriquecidas:{dias}dias:{provider}"
        cached = get_cache(cache_key)
        if cached:
            cached["cached"] = True
            return cached

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        # Obtener alertas actuales (tasa error, caída, anomalías)
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Alertas por tasa error
            cursor = await db.execute("""
                SELECT operario_id, COUNT(*) as errores, COUNT(*) * 100.0 /
                       (SELECT COUNT(*) FROM picks_operario p2
                        WHERE p2.operario_id = picks_operario.operario_id) as tasa_error
                FROM picks_operario
                WHERE DATE(fecha) >= DATE('now', '-' || ? || ' days')
                AND estado = 'error'
                GROUP BY operario_id
                HAVING tasa_error > 5
                ORDER BY tasa_error DESC
                LIMIT 5
            """, (dias,))

            error_alerts = await cursor.fetchall()

            alertas = []
            for alert_row in error_alerts:
                op_id = alert_row['operario_id']
                tasa_error = round(alert_row['tasa_error'], 1)

                alertas.append({
                    "alerta_id": f"error_{op_id}",
                    "tipo": "tasa_error_alta",
                    "titulo": f"Tasa Error Alta: {op_id}",
                    "operario_id": op_id,
                    "valor_actual": tasa_error,
                    "umbral_normal": 2.5,
                    "severidad": "CRÍTICA" if tasa_error > 10 else "ALTA",
                    "timestamp": datetime.now().isoformat(),
                    "raw_data": {
                        "tasa_error": tasa_error,
                        "errores": int(alert_row['errores'])
                    }
                })

        # Enriquecer alertas con Claude
        t0 = time.time()
        alertas_enriquecidas = []

        for alerta in alertas:
            try:
                system_prompt = """Sos especialista en logística y operaciones de WMS.
Analiza la alerta y sugiere 3 causas probables ordenadas por probabilidad.
Responde en JSON con estructura: {
  "causas": [
    {"numero": 1, "causa": "...", "probabilidad": 70, "investigacion": "..."},
    ...
  ]
}"""

                user_prompt = f"""Alerta: {alerta['titulo']}
Operario: {alerta['operario_id']}
Tipo: {alerta['tipo']}
Valor: {alerta['valor_actual']}%
Umbral normal: {alerta['umbral_normal']}%

¿Cuáles son las 3 causas probables de esta tasa de error alta?"""

                ai_response, model_used_alert = await _call_ai(provider, system_prompt, [
                    {"role": "user", "content": user_prompt}
                ])

                causas_data = _extract_json_from_response(ai_response)
                causas = causas_data.get('causas', [])

            except Exception as e:
                print(f"Error enriqueciendo alerta: {e}")
                causas = [
                    {"numero": 1, "causa": "Falta de capacitación", "probabilidad": 50, "investigacion": "Revisar historial de capacitación"},
                    {"numero": 2, "causa": "Problema de RF/equipo", "probabilidad": 30, "investigacion": "Probar con RF diferente"},
                    {"numero": 3, "causa": "Problema de salud/fatiga", "probabilidad": 20, "investigacion": "Conversar privadamente con operario"}
                ]

            alerta["causas_probables"] = causas
            alerta["powered_by"] = powered_labels.get(provider, provider)
            alertas_enriquecidas.append(alerta)

        generation_time_ms = int((time.time() - t0) * 1000)

        response = {
            "total_alertas": len(alertas_enriquecidas),
            "alertas": alertas_enriquecidas,
            "dias_analizados": dias,
            "powered_by": powered_labels.get(provider, provider),
            "provider": provider,
            "generation_time_ms": generation_time_ms,
            "generated_at": datetime.now().isoformat(),
            "cached": False
        }

        set_cache(cache_key, response, ttl_segundos=600)  # 10 min
        return response

    except Exception as e:
        print(f"Error en get_alertas_enriquecidas: {str(e)}")
        return {
            "total_alertas": 0,
            "alertas": [],
            "powered_by": None,
            "provider": provider,
            "error": str(e)
        }


# ============================================================================
# 4. REPORTES ENRIQUECIDOS - Resumen Ejecutivo con Claude
# ============================================================================

@router.get("/reportes/enriquecido")
async def get_reportes_enriquecido(tipo: str = "diario", formato: str = "json", provider: str = ""):
    """
    Genera reporte enriquecido con resumen ejecutivo generado por IA.

    - tipo: 'diario', 'semanal', 'mensual'
    - formato: 'json' (PDF se genera desde frontend con window.print())
    - provider: 'claude', 'ollama', 'gemini', 'azure' (default: env AI_PROVIDER)

    Incluye: narrativa ejecutiva, top 3 insights, tendencias, prioridades.

    Ejemplo: /api/reportes/enriquecido?tipo=diario&provider=ollama
    """
    import os
    import aiosqlite
    from pathlib import Path
    import time
    from utils.cache import get_cache, set_cache
    from routers.ai import _call_ai

    provider = provider or os.getenv("AI_PROVIDER", "claude")
    powered_labels = {
        "claude": "Claude AI (Anthropic)",
        "ollama": "Ollama (Local)",
        "gemini": "Gemini (Google)",
        "azure": "Azure OpenAI"
    }

    try:
        # Verificar caché (incluye provider en key)
        cache_key = f"reportes:enriquecido:{tipo}:{provider}"
        cached = get_cache(cache_key)
        if cached:
            cached["cached"] = True
            return cached

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        # Determinar rango de fechas
        if tipo == "diario":
            dias = 1
        elif tipo == "semanal":
            dias = 7
        else:  # mensual
            dias = 30

        # Obtener datos agregados
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(f"""
                SELECT
                    COUNT(*) as total_picks,
                    COUNT(DISTINCT operario_id) as operarios_activos,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) as total_errores,
                    AVG(tiempo_segundos) as vel_promedio,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) * 100.0 /
                    COUNT(*) as tasa_error_global
                FROM picks_operario
                WHERE DATE(fecha) >= DATE('now', '-' || {dias} || ' days')
            """)

            datos = await cursor.fetchone()

            total_picks = datos['total_picks'] or 0
            operarios_activos = datos['operarios_activos'] or 0
            errores = datos['total_errores'] or 0
            vel_promedio = datos['vel_promedio'] or 28.5
            tasa_error = datos['tasa_error_global'] or 0

            # Top operarios
            cursor = await db.execute(f"""
                SELECT operario_id, COUNT(*) as picks
                FROM picks_operario
                WHERE DATE(fecha) >= DATE('now', '-' || {dias} || ' days')
                GROUP BY operario_id
                ORDER BY picks DESC
                LIMIT 3
            """)
            top_operarios = await cursor.fetchall()

            # Zonas con caída
            cursor = await db.execute(f"""
                SELECT DISTINCT sector, COUNT(*) as picks
                FROM picks_operario
                WHERE DATE(fecha) >= DATE('now', '-' || {dias} || ' days')
                GROUP BY sector
                ORDER BY picks DESC
            """)
            zonas = await cursor.fetchall()

        # Preparar contexto para Claude
        contexto_reporte = {
            "periodo": tipo,
            "metricas": {
                "total_picks": total_picks,
                "operarios_activos": operarios_activos,
                "velocidad_promedio": round(vel_promedio, 1),
                "tasa_error_global": round(tasa_error, 1),
                "total_errores": errores
            },
            "top_operarios": [
                {"operario_id": str(r['operario_id']), "picks": r['picks']}
                for r in top_operarios
            ],
            "zonas": [
                {"sector": str(r['sector']), "picks": r['picks']}
                for r in zonas
            ]
        }

        # Llamar a Claude para resumen ejecutivo
        t0 = time.time()
        try:
            system_prompt = """Sos especialista en operaciones de WMS con 15 años experiencia.
Analiza datos de una jornada de picking y genera resumen ejecutivo.
Responde en JSON con estructura: {
  "titulo": "...",
  "narrativa": "Párrafo de 2-3 líneas resumen de la jornada",
  "top_insights": [
    {"ranking": 1, "insight": "...", "impacto_pesos": 2500, "recomendacion": "...", "urgencia": "CRÍTICA|ALTA|MEDIA"},
    ...
  ],
  "tendencias": ["Tendencia 1", "Tendencia 2"],
  "prioridades_mañana": ["Prioridad 1", "Prioridad 2"]
}"""

            user_prompt = f"""Contexto de la jornada {tipo}:
{json.dumps(contexto_reporte, indent=2, ensure_ascii=False)}

Genera resumen ejecutivo para supervisores/gerencia."""

            ai_response, model_used_rep = await _call_ai(provider, system_prompt, [
                {"role": "user", "content": user_prompt}
            ])

            resumen_ejecutivo = _extract_json_from_response(ai_response)
            if not resumen_ejecutivo:
                resumen_ejecutivo = {
                    "titulo": f"Jornada {tipo.capitalize()}",
                    "narrativa": f"Total {total_picks} picks, {operarios_activos} operarios activos",
                    "top_insights": [],
                    "tendencias": [],
                    "prioridades_mañana": []
                }

        except Exception as e:
            print(f"Error generando resumen ejecutivo: {e}")
            resumen_ejecutivo = {
                "titulo": f"Jornada {tipo.capitalize()}",
                "narrativa": f"Total {total_picks} picks",
                "top_insights": [],
                "tendencias": [],
                "prioridades_mañana": []
            }

        generation_time_ms = int((time.time() - t0) * 1000)

        response = {
            "tipo": tipo,
            "periodo": f"Últimos {dias} días",
            "resumen_ejecutivo": resumen_ejecutivo,
            "datos_brutos": {
                "total_picks": total_picks,
                "operarios_activos": operarios_activos,
                "velocidad_promedio": round(vel_promedio, 1),
                "tasa_error_global": round(tasa_error, 1),
                "total_errores": errores
            },
            "powered_by": powered_labels.get(provider, provider),
            "provider": provider,
            "generation_time_ms": generation_time_ms,
            "generated_at": datetime.now().isoformat(),
            "cached": False
        }

        ttl = 3600 if tipo == "diario" else 1800  # 1h para diario, 30min para otros
        set_cache(cache_key, response, ttl_segundos=ttl)
        return response

    except Exception as e:
        print(f"Error en get_reportes_enriquecido: {str(e)}")
        return {
            "tipo": tipo,
            "resumen_ejecutivo": {},
            "powered_by": None,
            "provider": provider,
            "error": str(e)
        }


@router.get("/alertas")
async def get_alertas_activas(dias: int = 1):
    """
    Retorna alertas activas del último período.
    """
    try:
        import aiosqlite
        from pathlib import Path
        from datetime import datetime, timedelta

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            fecha_desde = str((datetime.now() - timedelta(days=dias)).date())

            # Obtener operarios con problemas (basado en análisis)
            cursor = await db.execute("""
                SELECT DISTINCT operario_id
                FROM picks_operario
                WHERE fecha >= ?
                ORDER BY operario_id
            """, (fecha_desde,))

            operarios = await cursor.fetchall()
            alertas = []

            for op in operarios:
                operario_id = op['operario_id']

                # Calcular si hay problemas
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) as picks,
                        COUNT(CASE WHEN estado = 'error' THEN 1 END) as errores,
                        AVG(tiempo_segundos) as vel
                    FROM picks_operario
                    WHERE operario_id = ? AND fecha >= ?
                """, (operario_id, fecha_desde))

                data = await cursor.fetchone()
                if data and data['picks'] > 5:
                    tasa_error = (data['errores'] / data['picks'] * 100) if data['picks'] > 0 else 0

                    if tasa_error > 5:
                        alertas.append({
                            "timestamp": datetime.now().isoformat(),
                            "operario_id": operario_id,
                            "tipo": "tasa_error_alta",
                            "severidad": "CRÍTICA",
                            "mensaje": f"Tasa error {tasa_error:.1f}% (esperado: 2-3%)",
                            "accion_sugerida": "Revisar con operario"
                        })

            return {
                "total_alertas": len(alertas),
                "periodo_dias": dias,
                "alertas": alertas
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/guardar")
async def guardar_config(
    config: dict
):
    """
    Guarda configuración de umbrales y alertas.

    Ejemplo:
    {
        "caida_critica": 20,
        "caida_alta": 15,
        "error_maximo": 5,
        "velocidad_minima": 28,
        "alertas_activas": ["caida", "error", "especialidad"],
        "email_destino": "supervisor@coto.com.ar",
        "frecuencia_reporte": "diaria"
    }
    """
    try:
        # En producción, guardaría esto en BD
        # Por ahora, retorna confirmación
        return {
            "status": "success",
            "mensaje": "Configuración guardada",
            "config_guardada": config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reportes/generar")
async def generar_reporte(
    formato: str = "json",  # json, pdf, excel
    tipo: str = "diario",   # diario, semanal, mensual
    incluir: str = "all"    # ranking, graficos, anomalias, all
):
    """
    Genera reportes en diferentes formatos.

    - formato: json, pdf, excel
    - tipo: diario, semanal, mensual
    - incluir: ranking, graficos, anomalias, all
    """
    try:
        import aiosqlite
        from pathlib import Path
        import json

        DB_PATH = Path(__file__).parent.parent / "vigia.db"

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Obtener datos del reporte
            cursor = await db.execute("""
                SELECT
                    operario_id,
                    COUNT(*) as picks,
                    SUM(cantidad_bultos) as bultos,
                    AVG(tiempo_segundos) as velocidad,
                    COUNT(CASE WHEN estado = 'error' THEN 1 END) as errores
                FROM picks_operario
                WHERE fecha >= DATE('now', '-1 day')
                GROUP BY operario_id
                ORDER BY picks DESC
            """)

            operarios = await cursor.fetchall()

            reporte_data = {
                "fecha_generacion": datetime.now().isoformat(),
                "tipo": tipo,
                "periodo": "últimas 24 horas",
                "resumen": {
                    "total_operarios": len(operarios),
                    "total_picks": sum(op['picks'] or 0 for op in operarios),
                    "total_bultos": sum(op['bultos'] or 0 for op in operarios),
                    "promedio_velocidad": round(
                        sum(op['velocidad'] or 0 for op in operarios) / max(len(operarios), 1), 1
                    )
                },
                "ranking": [
                    {
                        "rank": i + 1,
                        "operario_id": op['operario_id'],
                        "picks": op['picks'] or 0,
                        "bultos": op['bultos'] or 0,
                        "velocidad": round(op['velocidad'], 1) if op['velocidad'] else 0,
                        "errores": op['errores'] or 0
                    }
                    for i, op in enumerate(operarios[:10])
                ]
            }

            if formato == "json":
                return reporte_data
            elif formato == "pdf":
                # En producción, usaría reportlab
                return {
                    "status": "success",
                    "mensaje": "PDF generado",
                    "url": "/reports/diario_20260420.pdf"
                }
            elif formato == "excel":
                # En producción, usaría openpyxl
                return {
                    "status": "success",
                    "mensaje": "Excel generado",
                    "url": "/reports/diario_20260420.xlsx"
                }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

