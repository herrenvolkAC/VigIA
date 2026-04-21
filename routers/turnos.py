"""
VigIA · routers/turnos.py
Endpoints para gestionar turnos y olas (FASE 1: Alarmas + Productividad)
"""
from fastapi import APIRouter, HTTPException
import aiosqlite
from pathlib import Path
from datetime import datetime
from typing import List
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.alertas import generar_alertas, obtener_comparativas
from pydantic import BaseModel


# ============================================================================
# MODELOS PYDANTIC
# ============================================================================

class RebalanceRequest(BaseModel):
    """Request body para POST /api/rebalance/simular"""
    ola_id: str
    operarios_mover: List[str]  # IDs de operarios a mover
    zona_origen: str
    zona_destino: str

DB_PATH = Path(__file__).parent.parent / "vigia.db"

router = APIRouter(prefix="/api", tags=["turnos"])


@router.get("/turnos/{turno_id}")
async def get_turno(turno_id: str):
    """
    GET /api/turnos/{turno_id}
    Retorna datos del turno actual con KPIs.

    Example: /api/turnos/TARDE_2026_04_20
    """
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
        """, (turno_id,))

        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Turno no encontrado")

        # Calcular proyección (si turno tiene 8 horas y está a mitad)
        turno_dict = dict(row)
        if turno_dict['bultos_objetivo'] > 0:
            # Proyección simplificada basada en % ejecución actual
            turno_dict['proyeccion_bultos'] = int(
                turno_dict['bultos_ejecutados'] / (turno_dict['pct_ejecucion'] / 100)
            ) if turno_dict['pct_ejecucion'] > 0 else 0

        return turno_dict


@router.get("/olas/{turno_id}")
async def get_olas(turno_id: str = None):
    """
    GET /api/olas/{turno_id}
    Retorna todas las olas del turno actual.

    Example: /api/olas/TARDE_2026_04_20
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Si no especifica turno_id, obtener del turno en curso
        if not turno_id or turno_id == "actual":
            cursor = await db.execute("""
                SELECT turno_id FROM turnos WHERE cerrado = 0 LIMIT 1
            """)
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="No hay turno en curso")
            turno_id = row['turno_id']

        # Obtener olas del turno
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
            WHERE turno_id = (SELECT turno_id FROM turnos WHERE turno_id = ?)
            ORDER BY numero_ola
        """, (turno_id,))

        olas = await cursor.fetchall()
        if not olas:
            raise HTTPException(status_code=404, detail="No hay olas para este turno")

        return [dict(ola) for ola in olas]


@router.get("/olas/{ola_id}/operarios")
async def get_operarios_ola(ola_id: str):
    """
    GET /api/olas/{ola_id}/operarios
    Retorna todos los operarios asignados a una ola con productividad.

    Example: /api/olas/OLA_2_TARDE_20_04/operarios
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Obtener estándar del sector para comparación
        cursor = await db.execute("""
            SELECT zona FROM olas WHERE ola_id = ?
        """, (ola_id,))
        ola_row = await cursor.fetchone()
        if not ola_row:
            raise HTTPException(status_code=404, detail="Ola no encontrada")

        zona = ola_row['zona']

        cursor = await db.execute("""
            SELECT bultos_por_hora as estandar
            FROM estandares_sector
            WHERE sector = ?
        """, (zona,))
        std_row = await cursor.fetchone()
        estandar = std_row['estandar'] if std_row else 250

        # Obtener operarios de la ola
        cursor = await db.execute("""
            SELECT
                a.asignacion_id,
                a.operario_id,
                o.nombre,
                a.bultos_programados,
                a.bultos_reales,
                a.productividad,
                ? as estandar,
                ROUND(a.productividad - ?, 1) as desvio_pct,
                CASE
                    WHEN a.productividad >= (? * 0.9) THEN 'ok'
                    WHEN a.productividad >= (? * 0.8) THEN 'bajo'
                    ELSE 'critico'
                END as estado_productividad,
                a.estado
            FROM asignaciones_ola a
            JOIN operarios o ON a.operario_id = o.operario_id
            WHERE a.ola_id = ?
            ORDER BY a.productividad DESC
        """, (estandar, estandar, estandar, estandar, ola_id))

        operarios = await cursor.fetchall()
        if not operarios:
            raise HTTPException(status_code=404, detail="No hay operarios en esta ola")

        return [dict(op) for op in operarios]


@router.get("/estandares/{sector}")
async def get_estandares(sector: str):
    """
    GET /api/estandares/{sector}
    Retorna estándares del sector (ej: Secos, NOA)

    Example: /api/estandares/Secos
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                estandar_id,
                sector,
                bultos_por_hora,
                bultos_turno_total,
                efectivo_desde,
                actualizado_por,
                actualizado_en
            FROM estandares_sector
            WHERE sector = ?
        """, (sector,))

        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Sector '{sector}' no encontrado")

        return dict(row)


@router.post("/estandares/{sector}")
async def update_estandares(sector: str, bultos_por_hora: int, bultos_turno_total: int):
    """
    POST /api/estandares/{sector}
    Actualiza estándares del sector.

    Body: {"bultos_por_hora": 250, "bultos_turno_total": 3500}
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE estandares_sector
            SET bultos_por_hora = ?,
                bultos_turno_total = ?,
                actualizado_en = CURRENT_TIMESTAMP,
                actualizado_por = 'api'
            WHERE sector = ?
        """, (bultos_por_hora, bultos_turno_total, sector))

        await db.commit()

        return {
            "status": "updated",
            "sector": sector,
            "bultos_por_hora": bultos_por_hora,
            "bultos_turno_total": bultos_turno_total
        }


@router.get("/olas/{ola_id}/alertas")
async def get_alertas_ola(ola_id: str):
    """
    GET /api/olas/{ola_id}/alertas
    Retorna alertas generadas para una ola.

    Analiza:
    - Productividad actual vs estándar sector
    - Productividad vs compañeros
    - Tendencia histórica

    Example: /api/olas/OLA_2_TARDE_20_04/alertas
    """
    alertas = await generar_alertas(ola_id)

    if alertas:
        return {
            "ola_id": ola_id,
            "cantidad_alertas": len(alertas),
            "alertas_criticas": len([a for a in alertas if a['severidad'] == 'CRITICA']),
            "alertas_altas": len([a for a in alertas if a['severidad'] == 'ALTA']),
            "alertas": alertas
        }
    else:
        return {
            "ola_id": ola_id,
            "cantidad_alertas": 0,
            "alertas_criticas": 0,
            "alertas_altas": 0,
            "alertas": [],
            "mensaje": "Sin alertas - Toda la ola dentro de parametros"
        }


@router.get("/olas/{ola_id}/comparativas")
async def get_comparativas_ola(ola_id: str):
    """
    GET /api/olas/{ola_id}/comparativas
    Retorna top performers y bottom performers de una ola.

    Example: /api/olas/OLA_2_TARDE_20_04/comparativas
    """
    comparativas = await obtener_comparativas(ola_id)

    return {
        "ola_id": ola_id,
        "top_performers": comparativas['top_performers'],
        "bottom_performers": comparativas['bottom_performers']
    }


@router.post("/rebalance/simular")
async def simular_rebalance(request: RebalanceRequest):
    """
    POST /api/rebalance/simular
    Simula movimiento de operarios entre zonas y calcula impacto en bultos.

    Body:
    {
        "ola_id": "OLA_2_TARDE_20_04",
        "operarios_mover": ["OP_00045", "OP_00087"],
        "zona_origen": "Secos",
        "zona_destino": "NOA"
    }

    Calcula:
    - Bultos perdidos en zona origen
    - Bultos ganados en zona destino
    - Neto del turno
    - Recomendación (hacer o no)
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1. Obtener estándares de ambas zonas
        cursor = await db.execute("""
            SELECT bultos_por_hora FROM estandares_sector WHERE sector = ?
        """, (request.zona_origen,))
        std_origen = await cursor.fetchone()
        est_origen = std_origen['bultos_por_hora'] if std_origen else 250

        cursor = await db.execute("""
            SELECT bultos_por_hora FROM estandares_sector WHERE sector = ?
        """, (request.zona_destino,))
        std_destino = await cursor.fetchone()
        est_destino = std_destino['bultos_por_hora'] if std_destino else 60

        # 2. Calcular bultos que se pierden (zona origen)
        bultos_perdidos = 0
        operarios_nombres_origen = []

        for op_id in request.operarios_mover:
            cursor = await db.execute("""
                SELECT o.nombre, a.bultos_reales
                FROM asignaciones_ola a
                JOIN operarios o ON a.operario_id = o.operario_id
                WHERE a.ola_id = ? AND a.operario_id = ?
            """, (request.ola_id, op_id))
            op_data = await cursor.fetchone()

            if op_data:
                bultos_perdidos += op_data['bultos_reales']
                operarios_nombres_origen.append(op_data['nombre'])

        # 3. Calcular bultos que se ganan (zona destino)
        # Asumir que operarios tendrán productividad promedio de destino
        productividad_promedio_destino = est_destino  # Simplificado
        bultos_ganados = len(request.operarios_mover) * (productividad_promedio_destino / 60 * 60)  # 1 hora

        # 4. Calcular impacto neto
        impacto_neto = bultos_ganados - bultos_perdidos

        # 5. Generar recomendación
        recomendacion = "HACER"
        razon = ""

        if impacto_neto < 0:
            recomendacion = "NO HACER"
            razon = f"Pérdida neta de {abs(impacto_neto):.0f} bultos"
        elif impacto_neto == 0:
            recomendacion = "NEUTRAL"
            razon = "Sin impacto neto"
        else:
            recomendacion = "HACER"
            razon = f"Ganancia neta de {impacto_neto:.0f} bultos"

        return {
            "ola_id": request.ola_id,
            "operarios_a_mover": request.operarios_mover,
            "operarios_nombres": operarios_nombres_origen,
            "zona_origen": request.zona_origen,
            "zona_destino": request.zona_destino,
            "impacto": {
                "bultos_perdidos_zona_origen": bultos_perdidos,
                "bultos_ganados_zona_destino": int(bultos_ganados),
                "impacto_neto": int(impacto_neto),
                "operarios_origen_restantes": f"Calcular dinamicamente"
            },
            "recomendacion": recomendacion,
            "razon": razon,
            "advertencia": "Simulación - No aplica cambios en BD"
        }
