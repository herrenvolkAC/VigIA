"""
VigIA · utils/alertas.py
Logica de generacion de alertas para FASE 1: Alarmas + Productividad
"""
import aiosqlite
from pathlib import Path
from typing import List, Dict, Any

DB_PATH = Path(__file__).parent.parent / "vigia.db"


async def generar_alertas(ola_id: str) -> List[Dict[str, Any]]:
    """
    Genera alertas para una ola basado en:
    1. Productividad actual vs estándar sector
    2. Comparativa con compañeros en misma ola
    3. Tendencia histórica del operario

    Retorna lista de alertas con severidad (CRITICA, ALTA, MEDIA, BAJA)
    """
    alertas = []

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1. Obtener datos de la ola
        cursor = await db.execute("""
            SELECT zona FROM olas WHERE ola_id = ?
        """, (ola_id,))
        ola_row = await cursor.fetchone()
        if not ola_row:
            return []

        zona = ola_row['zona']

        # 2. Obtener estándar del sector
        cursor = await db.execute("""
            SELECT bultos_por_hora FROM estandares_sector WHERE sector = ?
        """, (zona,))
        std_row = await cursor.fetchone()
        estandar = std_row['bultos_por_hora'] if std_row else 250

        # 3. Obtener productividad promedio de la ola
        cursor = await db.execute("""
            SELECT AVG(productividad) as prod_promedio
            FROM asignaciones_ola
            WHERE ola_id = ?
        """, (ola_id,))
        prom_row = await cursor.fetchone()
        prod_promedio_ola = prom_row['prod_promedio'] if prom_row else estandar

        # 4. Obtener operarios con sus datos
        cursor = await db.execute("""
            SELECT
                a.asignacion_id,
                a.operario_id,
                o.nombre,
                a.productividad,
                a.bultos_reales,
                a.estado
            FROM asignaciones_ola a
            JOIN operarios o ON a.operario_id = o.operario_id
            WHERE a.ola_id = ? AND a.estado = 'en_curso'
            ORDER BY a.productividad
        """, (ola_id,))

        operarios = await cursor.fetchall()

        # 5. Procesar cada operario y generar alertas
        for operario in operarios:
            op_id = operario['operario_id']
            op_nombre = operario['nombre']
            prod_actual = operario['productividad']
            bultos_reales = operario['bultos_reales']

            # Cálculo de desvíos
            desvio_estandar = ((prod_actual - estandar) / estandar * 100) if estandar > 0 else 0
            desvio_compañeros = ((prod_actual - prod_promedio_ola) / prod_promedio_ola * 100) if prod_promedio_ola > 0 else 0

            # Regla 1: Productividad baja vs estándar
            if prod_actual < estandar * 0.8:  # Más de 20% bajo
                severidad = "CRITICA" if prod_actual < estandar * 0.6 else "ALTA"
                alerta = {
                    "tipo": "PRODUCTIVIDAD_BAJA",
                    "operario_id": op_id,
                    "operario_nombre": op_nombre,
                    "valor_actual": prod_actual,
                    "estandar": estandar,
                    "desvio_pct": round(desvio_estandar, 1),
                    "desvio_compañeros_pct": round(desvio_compañeros, 1),
                    "descripcion": f"{op_nombre}: {prod_actual:.0f} bul/h vs {estandar} estándar ({desvio_estandar:.1f}%)",
                    "sugerencia": "Revisar capacidad, aptitud o factores externos (máquina, material)",
                    "severidad": severidad,
                    "accion_recomendada": "mentoring" if prod_actual > estandar * 0.6 else "evaluacion"
                }
                alertas.append(alerta)

            # Regla 2: Operario significativamente por debajo de compañeros
            elif prod_actual < prod_promedio_ola * 0.85:  # Más de 15% bajo vs compañeros
                alerta = {
                    "tipo": "DESEMPENIO_COMPAÑEROS",
                    "operario_id": op_id,
                    "operario_nombre": op_nombre,
                    "valor_actual": prod_actual,
                    "promedio_compañeros": round(prod_promedio_ola, 1),
                    "desvio_pct": round(desvio_compañeros, 1),
                    "descripcion": f"{op_nombre}: {prod_actual:.0f} bul/h vs {prod_promedio_ola:.0f} promedio ({desvio_compañeros:.1f}%)",
                    "sugerencia": "Potencial: mentoring de compañero top performer",
                    "severidad": "MEDIA",
                    "accion_recomendada": "peer_mentoring"
                }
                alertas.append(alerta)

        return alertas


async def generar_alertas_turno(turno_id: int) -> List[Dict[str, Any]]:
    """
    Genera alertas para todas las olas del turno.
    """
    todas_alertas = []

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Obtener todas las olas del turno en curso
        cursor = await db.execute("""
            SELECT ola_id FROM olas
            WHERE turno_id = ?
            AND estado IN ('en_curso', 'completada')
            ORDER BY numero_ola
        """, (turno_id,))

        olas = await cursor.fetchall()

        # Generar alertas para cada ola
        for ola in olas:
            ola_id = ola['ola_id']
            alertas_ola = await generar_alertas(ola_id)
            todas_alertas.extend(alertas_ola)

    # Ordenar por severidad (CRITICA > ALTA > MEDIA > BAJA)
    orden_severidad = {"CRITICA": 0, "ALTA": 1, "MEDIA": 2, "BAJA": 3}
    todas_alertas.sort(key=lambda a: orden_severidad.get(a['severidad'], 999))

    return todas_alertas


async def obtener_comparativas(ola_id: str) -> Dict[str, Any]:
    """
    Obtiene datos comparativos para una ola:
    - Top performers
    - Bottom performers
    - Histórico vs misma ola días anteriores
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Top 3 performers
        cursor = await db.execute("""
            SELECT
                a.operario_id,
                o.nombre,
                a.productividad
            FROM asignaciones_ola a
            JOIN operarios o ON a.operario_id = o.operario_id
            WHERE a.ola_id = ?
            ORDER BY a.productividad DESC
            LIMIT 3
        """, (ola_id,))
        top = await cursor.fetchall()
        top_performers = [dict(row) for row in top]

        # Bottom 3 performers
        cursor = await db.execute("""
            SELECT
                a.operario_id,
                o.nombre,
                a.productividad
            FROM asignaciones_ola a
            JOIN operarios o ON a.operario_id = o.operario_id
            WHERE a.ola_id = ?
            ORDER BY a.productividad ASC
            LIMIT 3
        """, (ola_id,))
        bottom = await cursor.fetchall()
        bottom_performers = [dict(row) for row in bottom]

        return {
            "top_performers": top_performers,
            "bottom_performers": bottom_performers,
            "total_operarios": len(top) + len(bottom)  # Simplificado
        }


def calcular_tendencia(productividades: List[float]) -> str:
    """
    Calcula tendencia de productividad en últimos dias.
    productividades: lista de valores en orden cronológico
    Retorna: 'subiendo', 'bajando', 'estable'
    """
    if len(productividades) < 2:
        return "sin_datos"

    promedio_primeros = sum(productividades[:len(productividades)//2]) / (len(productividades)//2)
    promedio_ultimos = sum(productividades[len(productividades)//2:]) / (len(productividades) - len(productividades)//2)

    diferencia_pct = ((promedio_ultimos - promedio_primeros) / promedio_primeros * 100) if promedio_primeros > 0 else 0

    if diferencia_pct > 5:
        return "subiendo"
    elif diferencia_pct < -5:
        return "bajando"
    else:
        return "estable"


if __name__ == "__main__":
    import asyncio

    async def test_alertas():
        print("\n" + "="*60)
        print("TEST ALERTAS - OLA 2")
        print("="*60 + "\n")

        alertas = await generar_alertas("OLA_2_TARDE_20_04")

        if alertas:
            print(f"Alertas generadas: {len(alertas)}\n")
            for alerta in alertas:
                print(f"[{alerta['severidad']}] {alerta['operario_nombre']}")
                print(f"  Tipo: {alerta['tipo']}")
                print(f"  Descripcion: {alerta['descripcion']}")
                print(f"  Sugerencia: {alerta['sugerencia']}\n")
        else:
            print("Sin alertas para esta ola.")

        print("="*60)

    asyncio.run(test_alertas())
