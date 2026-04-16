"""
VigIA v2.0 · routers/data.py
Endpoints de datos: /api/snapshot, /api/turno/activo
"""
import logging
from datetime import datetime, date
from typing import Optional

import aiosqlite
from fastapi import APIRouter
from pydantic import BaseModel

from db.schema import DB_PATH

logger = logging.getLogger("vigia.data")
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────
class OlaData(BaseModel):
    ola_num: int
    sector: str
    hora_ini: str
    hora_fin: str
    bultos_prog: int
    bultos_ejec: int
    dot_prog: int
    dot_ejec: int
    prod_prog: float
    prod_ejec: float
    obs: Optional[str] = ""


class SnapshotRequest(BaseModel):
    programa: str
    fecha: str
    turno: str
    olas: list[OlaData]


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post("/snapshot")
async def save_snapshot(req: SnapshotRequest):
    """
    Recibe el snapshot parseado del xlsx y lo persiste en la BD.
    Crea o reutiliza el turno del día/programa.
    """
    logger.info(f"[/api/snapshot] programa={req.programa}, turno={req.turno}, olas={len(req.olas)}")

    objetivo_total = sum(o.bultos_prog for o in req.olas)
    dotacion = max((o.dot_ejec for o in req.olas if o.dot_ejec > 0), default=0)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Buscar turno existente para el mismo día/programa/turno
        cursor = await db.execute(
            "SELECT turno_id FROM turnos WHERE fecha=? AND programa_num=? AND turno=? AND cerrado=0",
            (req.fecha, req.programa, req.turno),
        )
        row = await cursor.fetchone()

        if row:
            turno_id = row["turno_id"]
            # Actualizar objetivo y dotación
            await db.execute(
                "UPDATE turnos SET objetivo_total=?, dotacion_real=? WHERE turno_id=?",
                (objetivo_total, dotacion, turno_id),
            )
            logger.info(f"[snapshot] Turno existente actualizado: id={turno_id}")
        else:
            cursor = await db.execute(
                """INSERT INTO turnos (fecha, turno, programa_num, objetivo_total, dotacion_real)
                   VALUES (?, ?, ?, ?, ?)""",
                (req.fecha, req.turno, req.programa, objetivo_total, dotacion),
            )
            turno_id = cursor.lastrowid
            logger.info(f"[snapshot] Nuevo turno creado: id={turno_id}")

        # Eliminar movimientos previos del turno y reinsertar (fresh snapshot)
        await db.execute("DELETE FROM movimientos WHERE turno_id=?", (turno_id,))

        for ola in req.olas:
            await db.execute(
                """INSERT INTO movimientos
                   (turno_id, hora, sector, bultos_programados, bultos_ejecutados,
                    dotacion_prog, dotacion_ejec, prod_prog, prod_ejec, observaciones, ola_num)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    turno_id,
                    ola.hora_ini,
                    ola.sector,
                    ola.bultos_prog,
                    ola.bultos_ejec,
                    ola.dot_prog,
                    ola.dot_ejec,
                    ola.prod_prog,
                    ola.prod_ejec,
                    ola.obs or "",
                    ola.ola_num,
                ),
            )

        await db.commit()

    return {
        "ok": True,
        "turno_id": turno_id,
        "olas_guardadas": len(req.olas),
        "objetivo_total": objetivo_total,
    }


@router.get("/turno/activo")
async def turno_activo():
    """
    Devuelve el turno abierto más reciente con sus movimientos.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """SELECT * FROM turnos WHERE cerrado=0
               ORDER BY created_at DESC LIMIT 1"""
        )
        turno = await cursor.fetchone()

        if not turno:
            return {"turno": None, "movimientos": []}

        turno_dict = dict(turno)

        cursor = await db.execute(
            "SELECT * FROM movimientos WHERE turno_id=? ORDER BY ola_num",
            (turno_dict["turno_id"],),
        )
        movs = await cursor.fetchall()

    return {
        "turno": turno_dict,
        "movimientos": [dict(m) for m in movs],
    }


@router.get("/turnos")
async def listar_turnos(limit: int = 20):
    """Lista los últimos N turnos (abiertos y cerrados)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM turnos ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
    return {"turnos": [dict(r) for r in rows]}
