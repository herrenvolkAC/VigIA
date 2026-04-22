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

    movimientos = [dict(m) for m in movs]
    total_ejecutado = sum((m.get("bultos_ejecutados") or 0) for m in movimientos)
    objetivo_total = turno_dict.get("objetivo_total") or 0
    turno_dict["total_ejecutado"] = total_ejecutado
    turno_dict["pct_avance"] = round(total_ejecutado / objetivo_total * 100, 1) if objetivo_total else None
    turno_dict["proceso"] = "picking"

    return {
        "turno": turno_dict,
        "movimientos": movimientos,
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


@router.get("/cumplimiento/ultimo")
async def get_cumplimiento_ultimo():
    """
    Devuelve la ultima foto disponible de cumplimiento por ola usando historico_olas.
    La respuesta esta pensada para hidratar picking.html.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("SELECT MAX(fecha) as fecha FROM historico_olas")
        row = await cursor.fetchone()
        fecha = row["fecha"] if row else None

        if not fecha:
            return {"fecha": None, "programa": None, "olas": [], "turnoTotales": {}}

        cursor = await db.execute(
            """
            SELECT
                ola_num,
                ola_label,
                turno,
                hora_ini,
                hora_fin,
                prog_secos,
                prog_noa,
                ejec_secos,
                ejec_noa,
                dot_prog,
                dot_ejec,
                prod_prog,
                prod_ejec
            FROM historico_olas
            WHERE fecha = ?
            ORDER BY ola_num
            """,
            (fecha,),
        )
        rows = await cursor.fetchall()

    olas = []
    turno_totales = {}
    for r in rows:
        turno = r["turno"]
        prog_total = round((r["prog_secos"] or 0) + (r["prog_noa"] or 0))
        ejec_total = round((r["ejec_secos"] or 0) + (r["ejec_noa"] or 0))
        ini = int(str(r["hora_ini"]).split(":")[0])
        fin = int(str(r["hora_fin"]).split(":")[0])

        olas.append({
            "num": r["ola_num"],
            "label": r["ola_label"] or f"OLA {r['ola_num']}",
            "turno": turno,
            "ini": ini,
            "fin": fin,
            "progSecos": round(r["prog_secos"] or 0),
            "progNOA": round(r["prog_noa"] or 0),
            "progTotal": prog_total,
            "ejecSecos": round(r["ejec_secos"] or 0),
            "ejecNOA": round(r["ejec_noa"] or 0),
            "ejecTotal": ejec_total,
            "dotProg": r["dot_prog"] or 0,
            "dotEjec": r["dot_ejec"] or 0,
            "prodProg": round(r["prod_prog"] or 0, 2),
            "prodEjec": round(r["prod_ejec"] or 0, 2),
            "obs": "",
        })

        turno_totales.setdefault(turno, {"prog": 0, "ejec": 0})
        turno_totales[turno]["prog"] += prog_total
        turno_totales[turno]["ejec"] += ejec_total

    return {
        "fecha": fecha,
        "programa": f"Historico {fecha}",
        "olas": olas,
        "turnoTotales": turno_totales,
    }
