"""
VigIA - WebSocket Router
Actualizaciones en tiempo real de análisis y picks

Endpoint: ws://localhost:8080/ws/turno/{turno_id}

Flujo:
1. Cliente conecta al WebSocket
2. Simulador genera picks y emite eventos
3. Backend procesa análisis en tiempo real
4. Frontend recibe updates y actualiza dashboard
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import aiosqlite
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Set, Any
import asyncio

DB_PATH = Path(__file__).parent.parent / "vigia.db"

router = APIRouter(prefix="/ws", tags=["websocket"])

# Conexiones activas (para broadcasting)
active_connections: Dict[str, Set[WebSocket]] = {}


# Pydantic models para HTTP endpoints
class PickData(BaseModel):
    pick_id: str
    operario_id: str
    operario_nombre: str
    ola_id: str
    sku: str
    cantidad_bultos: int
    peso_kg: float
    tiempo_segundos: int
    estado: str
    timestamp: str


class AnalisisResultado(BaseModel):
    data: Dict[str, Any]


class StatsData(BaseModel):
    turno_id: str
    picks_generados: int = 0
    bultos_totales: int = 0
    tiempo_promedio_seg: float = 0
    operarios_activos: int = 0


@router.websocket("/ws/turno/{turno_id}")
async def websocket_turno(websocket: WebSocket, turno_id: str):
    """
    WebSocket endpoint para actualizaciones en tiempo real de turno.

    Emite eventos:
    - pick_creado: cuando se genera un nuevo pick
    - analisis_actualizado: cuando se actualiza un análisis
    - estadisticas: stats del turno en vivo

    Ejemplo cliente:
    ```javascript
    const ws = new WebSocket('ws://localhost:8080/ws/turno/TARDE_2026_04_20');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log(data.tipo); // 'pick_creado', 'analisis_actualizado', etc
    }
    ```
    """
    await websocket.accept()

    # Registrar conexión
    if turno_id not in active_connections:
        active_connections[turno_id] = set()
    active_connections[turno_id].add(websocket)

    print(f"[WS] Cliente conectado a turno {turno_id}")
    print(f"[WS] Conexiones activas: {len(active_connections[turno_id])}")

    try:
        while True:
            # Recibir mensaje del cliente (mantener conexión viva)
            data = await websocket.receive_text()

            # Comandos del cliente
            if data == "ping":
                await websocket.send_json({
                    "tipo": "pong",
                    "timestamp": datetime.now().isoformat()
                })
            elif data.startswith("get_stats"):
                # Cliente solicita estadísticas actuales
                stats = await get_turno_stats(turno_id)
                await websocket.send_json({
                    "tipo": "estadisticas",
                    "datos": stats
                })

    except WebSocketDisconnect:
        active_connections[turno_id].discard(websocket)
        print(f"[WS] Cliente desconectado de turno {turno_id}")

    except Exception as e:
        print(f"[WS ERROR] {e}")
        active_connections[turno_id].discard(websocket)


async def broadcast_pick(turno_id: str, pick_data: dict):
    """
    Envía un nuevo pick a todos los clientes conectados.
    Llamado por el simulador cuando genera un pick.
    """
    if turno_id not in active_connections:
        return

    message = {
        "tipo": "pick_creado",
        "timestamp": datetime.now().isoformat(),
        "pick": pick_data
    }

    # Enviar a todos los clientes del turno
    for websocket in list(active_connections[turno_id]):
        try:
            await websocket.send_json(message)
        except Exception as e:
            print(f"[WS ERROR] Error enviando mensaje: {e}")
            active_connections[turno_id].discard(websocket)


async def broadcast_analisis(turno_id: str, operario_id: str, analisis_tipo: str, resultado: dict):
    """
    Envía un análisis actualizado a todos los clientes conectados.
    """
    if turno_id not in active_connections:
        return

    message = {
        "tipo": "analisis_actualizado",
        "timestamp": datetime.now().isoformat(),
        "operario_id": operario_id,
        "analisis_tipo": analisis_tipo,
        "resultado": resultado
    }

    for websocket in list(active_connections[turno_id]):
        try:
            await websocket.send_json(message)
        except Exception as e:
            print(f"[WS ERROR] Error enviando análisis: {e}")
            active_connections[turno_id].discard(websocket)


async def broadcast_stats(turno_id: str, stats: dict):
    """
    Envía estadísticas del turno a todos los clientes conectados.
    """
    if turno_id not in active_connections:
        return

    message = {
        "tipo": "estadisticas",
        "timestamp": datetime.now().isoformat(),
        "datos": stats
    }

    for websocket in list(active_connections[turno_id]):
        try:
            await websocket.send_json(message)
        except Exception as e:
            print(f"[WS ERROR] Error enviando stats: {e}")
            active_connections[turno_id].discard(websocket)


@router.post("/api/broadcast/pick")
async def api_broadcast_pick(turno_id: str, pick_data: PickData):
    """
    HTTP endpoint para emitir un pick a través de WebSocket.
    Llamado por el simulador.
    """
    await broadcast_pick(turno_id, pick_data.dict())
    return {"status": "ok", "turno_id": turno_id}


@router.post("/api/broadcast/analisis")
async def api_broadcast_analisis(turno_id: str, operario_id: str, analisis_tipo: str, resultado: AnalisisResultado):
    """
    HTTP endpoint para emitir un análisis.
    """
    await broadcast_analisis(turno_id, operario_id, analisis_tipo, resultado.data)
    return {"status": "ok"}


@router.post("/api/broadcast/stats")
async def api_broadcast_stats(turno_id: str, stats: StatsData):
    """
    HTTP endpoint para emitir estadísticas.
    """
    await broadcast_stats(turno_id, stats.dict())
    return {"status": "ok"}


async def get_turno_stats(turno_id: str) -> dict:
    """
    Obtiene estadísticas actuales del turno.
    """
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            # Stats generales
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
        print(f"[ERROR] Error obteniendo stats: {e}")
        return {"error": str(e)}
