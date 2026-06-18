from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from openpyxl import load_workbook
from pydantic import BaseModel
import xlrd

from db.auth import auth_db
from db.panol_insumos import panol_db
from routers.auth_local import current_auth


router = APIRouter(prefix="/panol-insumos/api", tags=["panol-insumos"])

FULL_PROFILES = {"ADMIN", "SUPERVISOR", "TODO"}
LIMITED_PROFILES = {"OPERACION", "OPERADOR", "USUARIO", ""}
MOVEMENT_TYPES = {"ALTA", "BAJA", "AJUSTE_POSITIVO", "AJUSTE_NEGATIVO", "TRANSFERENCIA"}
INCOMING_TYPES = {"ALTA", "AJUSTE_POSITIVO"}
OUTGOING_TYPES = {"BAJA", "AJUSTE_NEGATIVO"}


class ArticleRequest(BaseModel):
    codigo: str
    descripcion: str
    categoria: str = ""
    unidad: str = "UN"
    stock_minimo: float = 0
    activo: bool = True


class MovementRequest(BaseModel):
    articulo_id: int
    tipo: str
    ubicacion_origen_id: int | None = None
    ubicacion_destino_id: int | None = None
    cantidad: float
    motivo: str = ""
    observacion: str = ""


class ProductionRequest(BaseModel):
    articulo_id: int
    cantidad: float
    observacion: str = ""


class ProductionDeliveryRequest(BaseModel):
    articulo_id: int
    ubicacion_destino_id: int
    cantidad: float
    observacion: str = ""


class InventoryLine(BaseModel):
    articulo_id: int
    stock_fisico: float


class InventoryRequest(BaseModel):
    fecha: str
    turno: str
    ubicacion_id: int | None = None
    ubicacion_codigo: str = "OFICINA_ADO"
    observacion: str = ""
    items: list[InventoryLine]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _turno_por_hora(fecha_hora: str | None = None) -> str:
    dt = datetime.strptime(fecha_hora or _now(), "%Y-%m-%d %H:%M:%S")
    hour = dt.hour
    if 6 <= hour < 14:
        return "MANANA"
    if 14 <= hour < 22:
        return "TARDE"
    return "NOCHE"


def _norm_code(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).upper()


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _row_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", ".")
    if not text:
        return 0.0
    return float(text)


async def _fetch_rows(db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    async with db.execute(sql, args) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def _fetch_one(db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    async with db.execute(sql, args) as cur:
        return _row_dict(await cur.fetchone())


async def _require_panol_access(request: Request, *, full: bool = False) -> dict[str, Any]:
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    if auth.get("role") == "admin":
        auth["panol_profile"] = "ADMIN"
        auth["panol_full"] = True
        return auth

    async with auth_db(attach_operational=False) as db:
        try:
            row = await _fetch_one(
                db,
                """
                SELECT enabled, profile
                FROM auth_user_app_access
                WHERE username = ? AND module = 'panol'
                """,
                (auth["username"],),
            )
        except sqlite3.OperationalError:
            row = None

    if not row or not row.get("enabled"):
        raise HTTPException(status_code=403, detail="Sin acceso al modulo Panol.")

    profile = _norm_code(row.get("profile") or "OPERACION")
    can_full = profile in FULL_PROFILES
    if profile not in FULL_PROFILES and profile not in LIMITED_PROFILES:
        can_full = False
    if full and not can_full:
        raise HTTPException(status_code=403, detail="Requiere perfil completo de Panol.")
    auth["panol_profile"] = profile or "OPERACION"
    auth["panol_full"] = can_full
    return auth


async def _ubicacion_id(db: aiosqlite.Connection, codigo: str) -> int:
    row = await _fetch_one(db, "SELECT id FROM ubicaciones WHERE codigo = ? AND activo = 1", (_norm_code(codigo),))
    if not row:
        raise HTTPException(status_code=500, detail=f"Falta ubicacion {codigo}.")
    return int(row["id"])


async def _stock_ubicacion(db: aiosqlite.Connection, articulo_id: int, ubicacion_id: int, until: str | None = None) -> float:
    until_sql = "AND fecha_hora <= ?" if until else ""
    args: list[Any] = [articulo_id, ubicacion_id, articulo_id, ubicacion_id]
    if until:
        args.append(until)
    row = await _fetch_one(
        db,
        f"""
        SELECT
            COALESCE(SUM(CASE
                WHEN articulo_id = ? AND ubicacion_destino_id = ?
                     AND tipo IN ('ALTA','AJUSTE_POSITIVO','TRANSFERENCIA') THEN cantidad
                ELSE 0 END), 0)
          - COALESCE(SUM(CASE
                WHEN articulo_id = ? AND ubicacion_origen_id = ?
                     AND tipo IN ('BAJA','AJUSTE_NEGATIVO','TRANSFERENCIA') THEN cantidad
                ELSE 0 END), 0) AS stock
        FROM movimientos
        WHERE 1 = 1 {until_sql}
        """,
        tuple(args),
    )
    return float((row or {}).get("stock") or 0)


async def _latest_inventory(db: aiosqlite.Connection, articulo_id: int, ubicacion_id: int | None = None) -> dict[str, Any] | None:
    location_clause = "AND ubicacion_id = ?" if ubicacion_id else ""
    args: list[Any] = [articulo_id]
    if ubicacion_id:
        args.append(ubicacion_id)
    return await _fetch_one(
        db,
        f"""
        SELECT *
        FROM inventario_turno
        WHERE articulo_id = ?
        {location_clause}
        ORDER BY fecha_hora DESC, id DESC
        LIMIT 1
        """,
        tuple(args),
    )


async def _office_transfers_since(db: aiosqlite.Connection, articulo_id: int, since: str | None, until: str) -> tuple[float, float]:
    oficina_id = await _ubicacion_id(db, "OFICINA_ADO")
    jaula_id = await _ubicacion_id(db, "JAULA")
    where_since = "AND fecha_hora > ?" if since else ""
    args: list[Any] = [jaula_id, oficina_id, oficina_id, jaula_id, articulo_id, until]
    if since:
        args.append(since)
    row = await _fetch_one(
        db,
        f"""
        SELECT
            COALESCE(SUM(CASE
                WHEN ubicacion_origen_id = ? AND ubicacion_destino_id = ? THEN cantidad
                ELSE 0 END), 0) AS ingresos,
            COALESCE(SUM(CASE
                WHEN ubicacion_origen_id = ? AND ubicacion_destino_id = ? THEN cantidad
                ELSE 0 END), 0) AS egresos
        FROM movimientos
        WHERE articulo_id = ?
          AND tipo = 'TRANSFERENCIA'
          AND fecha_hora <= ?
          {where_since}
        """,
        tuple(args),
    )
    return float((row or {}).get("ingresos") or 0), float((row or {}).get("egresos") or 0)


async def _office_income_since(db: aiosqlite.Connection, articulo_id: int, since: str | None, until: str) -> float:
    ingresos, _ = await _office_transfers_since(db, articulo_id, since, until)
    return ingresos


async def _stock_oficina(db: aiosqlite.Connection, articulo_id: int) -> float:
    oficina_id = await _ubicacion_id(db, "OFICINA_ADO")
    latest = await _latest_inventory(db, articulo_id, oficina_id)
    if not latest:
        return 0.0
    ingresos, egresos = await _office_transfers_since(db, articulo_id, latest["fecha_hora"], _now())
    return float(latest["stock_fisico"] or 0) + ingresos - egresos


async def _stock_for_origin(db: aiosqlite.Connection, articulo_id: int, ubicacion_id: int) -> float:
    location = await _fetch_one(db, "SELECT codigo FROM ubicaciones WHERE id = ?", (ubicacion_id,))
    if _norm_code((location or {}).get("codigo")) == "OFICINA_ADO":
        return await _stock_oficina(db, articulo_id)
    return await _stock_ubicacion(db, articulo_id, ubicacion_id)


async def _stock_cd(db: aiosqlite.Connection, articulo_id: int) -> float:
    row = await _fetch_one(
        db,
        """
        SELECT stock_cd
        FROM stock_cd_importado
        WHERE articulo_id = ?
        ORDER BY fecha_importacion DESC, id DESC
        LIMIT 1
        """,
        (articulo_id,),
    )
    return float((row or {}).get("stock_cd") or 0)


async def _stock_producido(db: aiosqlite.Connection, articulo_id: int) -> float:
    row = await _fetch_one(
        db,
        """
        SELECT
            COALESCE(SUM(CASE WHEN tipo = 'PRODUCCION' THEN cantidad ELSE 0 END), 0)
          - COALESCE(SUM(CASE WHEN tipo = 'ENTREGA' THEN cantidad ELSE 0 END), 0) AS stock
        FROM produccion_movimientos
        WHERE articulo_id = ?
        """,
        (articulo_id,),
    )
    return float((row or {}).get("stock") or 0)


@router.get("/context")
async def context(request: Request):
    auth = await _require_panol_access(request)
    async with panol_db() as db:
        ubicaciones = await _fetch_rows(db, "SELECT * FROM ubicaciones WHERE activo = 1 ORDER BY id")
        turnos = await _fetch_rows(db, "SELECT * FROM turnos WHERE activo = 1 ORDER BY id")
    return {
        "user": {
            "username": auth.get("username"),
            "display_name": auth.get("display_name"),
            "role": auth.get("role"),
            "panol_profile": auth.get("panol_profile"),
            "can_full": bool(auth.get("panol_full")),
        },
        "ubicaciones": ubicaciones,
        "turnos": turnos,
    }


@router.get("/articulos")
async def list_articles(request: Request, include_inactive: bool = Query(False)):
    await _require_panol_access(request)
    where = "" if include_inactive else "WHERE activo = 1"
    async with panol_db() as db:
        return {
            "items": await _fetch_rows(
                db,
                f"""
                SELECT *
                FROM articulos
                {where}
                ORDER BY activo DESC, codigo
                """,
            )
        }


@router.post("/articulos")
async def create_article(req: ArticleRequest, request: Request):
    await _require_panol_access(request, full=True)
    codigo = _norm_code(req.codigo)
    descripcion = _clean(req.descripcion)
    if not codigo or not descripcion:
        raise HTTPException(status_code=400, detail="Codigo y descripcion son obligatorios.")
    now = _now()
    try:
        async with panol_db() as db:
            await db.execute(
                """
                INSERT INTO articulos
                    (codigo, descripcion, categoria, unidad, stock_minimo, activo, creado_en, actualizado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    codigo,
                    descripcion,
                    _clean(req.categoria),
                    _clean(req.unidad) or "UN",
                    max(float(req.stock_minimo or 0), 0),
                    1 if req.activo else 0,
                    now,
                    now,
                ),
            )
            await db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ya existe un articulo con ese codigo.")
    return {"ok": True}


@router.put("/articulos/{articulo_id}")
async def update_article(articulo_id: int, req: ArticleRequest, request: Request):
    await _require_panol_access(request)
    codigo = _norm_code(req.codigo)
    descripcion = _clean(req.descripcion)
    if not codigo or not descripcion:
        raise HTTPException(status_code=400, detail="Codigo y descripcion son obligatorios.")
    try:
        async with panol_db() as db:
            cur = await db.execute(
                """
                UPDATE articulos
                SET codigo = ?, descripcion = ?, categoria = ?, unidad = ?, stock_minimo = ?,
                    activo = ?, actualizado_en = ?
                WHERE id = ?
                """,
                (
                    codigo,
                    descripcion,
                    _clean(req.categoria),
                    _clean(req.unidad) or "UN",
                    max(float(req.stock_minimo or 0), 0),
                    1 if req.activo else 0,
                    _now(),
                    articulo_id,
                ),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Articulo no encontrado.")
            await db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ya existe otro articulo con ese codigo.")
    return {"ok": True}


@router.post("/movimientos")
async def create_movement(req: MovementRequest, request: Request):
    auth = await _require_panol_access(request)
    tipo = _norm_code(req.tipo)
    cantidad = float(req.cantidad or 0)
    if tipo not in MOVEMENT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de movimiento invalido.")
    if cantidad <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a cero.")

    async with panol_db() as db:
        article = await _fetch_one(db, "SELECT id FROM articulos WHERE id = ? AND activo = 1", (req.articulo_id,))
        if not article:
            raise HTTPException(status_code=404, detail="Articulo no encontrado o inactivo.")

        origin = req.ubicacion_origen_id
        dest = req.ubicacion_destino_id
        if tipo in INCOMING_TYPES and not dest:
            raise HTTPException(status_code=400, detail="El movimiento requiere ubicacion destino.")
        if tipo in OUTGOING_TYPES and not origin:
            raise HTTPException(status_code=400, detail="El movimiento requiere ubicacion origen.")
        if tipo == "TRANSFERENCIA":
            if not origin or not dest:
                raise HTTPException(status_code=400, detail="La transferencia requiere origen y destino.")
            if origin == dest:
                raise HTTPException(status_code=400, detail="Origen y destino deben ser distintos.")
        if origin:
            stock = await _stock_for_origin(db, req.articulo_id, origin)
            if stock + 0.000001 < cantidad:
                raise HTTPException(status_code=400, detail="El movimiento dejaria stock negativo.")

        await db.execute(
            """
            INSERT INTO movimientos
                (articulo_id, tipo, ubicacion_origen_id, ubicacion_destino_id, cantidad,
                 motivo, observacion, usuario, fecha_hora)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.articulo_id,
                tipo,
                origin,
                dest,
                cantidad,
                _clean(req.motivo),
                _clean(req.observacion),
                auth.get("username"),
                _now(),
            ),
        )
        await db.commit()
    return {"ok": True}


@router.get("/movimientos")
async def list_movements(
    request: Request,
    fecha_desde: str = Query(""),
    fecha_hasta: str = Query(""),
    articulo_id: int | None = Query(None),
    tipo: str = Query(""),
    usuario: str = Query(""),
):
    await _require_panol_access(request)
    where = []
    args: list[Any] = []
    if fecha_desde:
        where.append("m.fecha_hora >= ?")
        args.append(f"{fecha_desde} 00:00:00")
    if fecha_hasta:
        where.append("m.fecha_hora <= ?")
        args.append(f"{fecha_hasta} 23:59:59")
    if articulo_id:
        where.append("m.articulo_id = ?")
        args.append(articulo_id)
    if tipo:
        where.append("m.tipo = ?")
        args.append(_norm_code(tipo))
    if usuario:
        where.append("m.usuario LIKE ?")
        args.append(f"%{_clean(usuario)}%")
    clause = "WHERE " + " AND ".join(where) if where else ""
    async with panol_db() as db:
        rows = await _fetch_rows(
            db,
            f"""
            SELECT m.*, a.codigo, a.descripcion,
                   uo.codigo AS origen_codigo, ud.codigo AS destino_codigo
            FROM movimientos m
            JOIN articulos a ON a.id = m.articulo_id
            LEFT JOIN ubicaciones uo ON uo.id = m.ubicacion_origen_id
            LEFT JOIN ubicaciones ud ON ud.id = m.ubicacion_destino_id
            {clause}
            ORDER BY m.fecha_hora DESC, m.id DESC
            LIMIT 500
            """,
            tuple(args),
        )
    return {"items": rows}


@router.post("/produccion")
async def create_production(req: ProductionRequest, request: Request):
    auth = await _require_panol_access(request)
    cantidad = float(req.cantidad or 0)
    if cantidad <= 0:
        raise HTTPException(status_code=400, detail="La cantidad producida debe ser mayor a cero.")
    now = _now()
    turno = _turno_por_hora(now)
    async with panol_db() as db:
        article = await _fetch_one(db, "SELECT id FROM articulos WHERE id = ? AND activo = 1", (req.articulo_id,))
        if not article:
            raise HTTPException(status_code=404, detail="Articulo no encontrado o inactivo.")
        await db.execute(
            """
            INSERT INTO produccion_movimientos
                (articulo_id, tipo, ubicacion_destino_id, cantidad, turno, observacion, usuario, fecha_hora)
            VALUES (?, 'PRODUCCION', NULL, ?, ?, ?, ?, ?)
            """,
            (req.articulo_id, cantidad, turno, _clean(req.observacion), auth.get("username"), now),
        )
        await db.commit()
    return {"ok": True, "turno": turno, "fecha_hora": now}


@router.post("/produccion/entregas")
async def create_production_delivery(req: ProductionDeliveryRequest, request: Request):
    auth = await _require_panol_access(request)
    cantidad = float(req.cantidad or 0)
    if cantidad <= 0:
        raise HTTPException(status_code=400, detail="La cantidad entregada debe ser mayor a cero.")
    now = _now()
    turno = _turno_por_hora(now)
    async with panol_db() as db:
        article = await _fetch_one(db, "SELECT id FROM articulos WHERE id = ? AND activo = 1", (req.articulo_id,))
        if not article:
            raise HTTPException(status_code=404, detail="Articulo no encontrado o inactivo.")
        destination = await _fetch_one(
            db,
            "SELECT id FROM ubicaciones WHERE id = ? AND activo = 1",
            (req.ubicacion_destino_id,),
        )
        if not destination:
            raise HTTPException(status_code=400, detail="Destino invalido.")
        stock_actual = await _stock_producido(db, req.articulo_id)
        if stock_actual + 0.000001 < cantidad:
            raise HTTPException(status_code=400, detail="La entrega dejaria stock producido negativo.")
        await db.execute(
            """
            INSERT INTO produccion_movimientos
                (articulo_id, tipo, ubicacion_destino_id, cantidad, turno, observacion, usuario, fecha_hora)
            VALUES (?, 'ENTREGA', ?, ?, ?, ?, ?, ?)
            """,
            (
                req.articulo_id,
                req.ubicacion_destino_id,
                cantidad,
                turno,
                _clean(req.observacion),
                auth.get("username"),
                now,
            ),
        )
        await db.commit()
    return {"ok": True, "turno": turno, "fecha_hora": now}


@router.get("/produccion/stock")
async def production_stock(request: Request, q: str = Query("")):
    await _require_panol_access(request)
    async with panol_db() as db:
        rows = await _fetch_rows(
            db,
            """
            SELECT a.id AS articulo_id, a.codigo, a.descripcion, a.categoria, a.unidad,
                   COALESCE(SUM(CASE WHEN pm.tipo = 'PRODUCCION' THEN pm.cantidad ELSE 0 END), 0) AS producido,
                   COALESCE(SUM(CASE WHEN pm.tipo = 'ENTREGA' THEN pm.cantidad ELSE 0 END), 0) AS entregado,
                   COALESCE(SUM(CASE WHEN pm.tipo = 'PRODUCCION' THEN pm.cantidad ELSE 0 END), 0)
                 - COALESCE(SUM(CASE WHEN pm.tipo = 'ENTREGA' THEN pm.cantidad ELSE 0 END), 0) AS stock_producido
            FROM articulos a
            LEFT JOIN produccion_movimientos pm ON pm.articulo_id = a.id
            WHERE a.activo = 1
            GROUP BY a.id, a.codigo, a.descripcion, a.categoria, a.unidad
            ORDER BY a.codigo
            """,
        )
        today = await _fetch_one(
            db,
            """
            SELECT
                COALESCE(SUM(CASE WHEN tipo = 'PRODUCCION' THEN cantidad ELSE 0 END), 0) AS producido,
                COALESCE(SUM(CASE WHEN tipo = 'ENTREGA' THEN cantidad ELSE 0 END), 0) AS entregado
            FROM produccion_movimientos
            WHERE fecha_hora >= ?
            """,
            (f"{_today()} 00:00:00",),
        )
    items = []
    for row in rows:
        if q and q.lower() not in f"{row['codigo']} {row['descripcion']}".lower():
            continue
        items.append(row)
    return {
        "items": items,
        "metrics": {
            "producido_hoy": float((today or {}).get("producido") or 0),
            "entregado_hoy": float((today or {}).get("entregado") or 0),
            "stock_total_producido": sum(float(row.get("stock_producido") or 0) for row in rows),
        },
    }


@router.get("/produccion/movimientos")
async def list_production_movements(
    request: Request,
    fecha_desde: str = Query(""),
    fecha_hasta: str = Query(""),
    articulo_id: int | None = Query(None),
    tipo: str = Query(""),
    destino_id: int | None = Query(None),
    turno: str = Query(""),
):
    await _require_panol_access(request)
    where = []
    args: list[Any] = []
    if fecha_desde:
        where.append("pm.fecha_hora >= ?")
        args.append(f"{fecha_desde} 00:00:00")
    if fecha_hasta:
        where.append("pm.fecha_hora <= ?")
        args.append(f"{fecha_hasta} 23:59:59")
    if articulo_id:
        where.append("pm.articulo_id = ?")
        args.append(articulo_id)
    if tipo:
        where.append("pm.tipo = ?")
        args.append(_norm_code(tipo))
    if destino_id:
        where.append("pm.ubicacion_destino_id = ?")
        args.append(destino_id)
    if turno:
        where.append("pm.turno = ?")
        args.append(_norm_code(turno))
    clause = "WHERE " + " AND ".join(where) if where else ""
    async with panol_db() as db:
        rows = await _fetch_rows(
            db,
            f"""
            SELECT pm.*, a.codigo, a.descripcion, u.codigo AS destino_codigo
            FROM produccion_movimientos pm
            JOIN articulos a ON a.id = pm.articulo_id
            LEFT JOIN ubicaciones u ON u.id = pm.ubicacion_destino_id
            {clause}
            ORDER BY pm.fecha_hora DESC, pm.id DESC
            LIMIT 500
            """,
            tuple(args),
        )
    return {"items": rows}


@router.get("/produccion/indicadores")
async def production_indicators(request: Request):
    await _require_panol_access(request)
    async with panol_db() as db:
        by_turn = await _fetch_rows(
            db,
            """
            SELECT turno, COALESCE(SUM(cantidad), 0) AS cantidad
            FROM produccion_movimientos
            WHERE tipo = 'PRODUCCION'
            GROUP BY turno
            ORDER BY cantidad DESC
            """,
        )
        by_sector = await _fetch_rows(
            db,
            """
            SELECT u.id AS ubicacion_id, u.codigo AS sector, COALESCE(SUM(pm.cantidad), 0) AS cantidad
            FROM produccion_movimientos pm
            JOIN ubicaciones u ON u.id = pm.ubicacion_destino_id
            WHERE pm.tipo = 'ENTREGA'
            GROUP BY u.id, u.codigo
            ORDER BY cantidad DESC
            """,
        )
        by_sector_plu = await _fetch_rows(
            db,
            """
            SELECT u.codigo AS sector, a.codigo, a.descripcion, COALESCE(SUM(pm.cantidad), 0) AS cantidad
            FROM produccion_movimientos pm
            JOIN ubicaciones u ON u.id = pm.ubicacion_destino_id
            JOIN articulos a ON a.id = pm.articulo_id
            WHERE pm.tipo = 'ENTREGA'
            GROUP BY u.codigo, a.codigo, a.descripcion
            ORDER BY cantidad DESC, u.codigo, a.codigo
            LIMIT 200
            """,
        )
    return {"produccion_por_turno": by_turn, "entregas_por_sector": by_sector, "entregas_por_sector_plu": by_sector_plu}


@router.get("/stock")
async def stock(request: Request, q: str = Query(""), categoria: str = Query(""), bajo_minimo: bool = Query(False)):
    await _require_panol_access(request)
    async with panol_db() as db:
        jaula_id = await _ubicacion_id(db, "JAULA")
        articles = await _fetch_rows(
            db,
            """
            SELECT *
            FROM articulos
            WHERE activo = 1
            ORDER BY codigo
            """,
        )
        items = []
        for art in articles:
            if q and q.lower() not in f"{art['codigo']} {art['descripcion']}".lower():
                continue
            if categoria and categoria.lower() not in str(art.get("categoria") or "").lower():
                continue
            stock_cd = await _stock_cd(db, int(art["id"]))
            stock_jaula = await _stock_ubicacion(db, int(art["id"]), jaula_id)
            stock_oficina = await _stock_oficina(db, int(art["id"]))
            total = stock_cd + stock_jaula + stock_oficina
            minimo = float(art.get("stock_minimo") or 0)
            is_low = minimo > 0 and total < minimo
            if bajo_minimo and not is_low:
                continue
            avg = await _average_daily_consumption(db, int(art["id"]), 30)
            items.append(
                {
                    **art,
                    "stock_cd": stock_cd,
                    "stock_jaula": stock_jaula,
                    "stock_oficina": stock_oficina,
                    "stock_total": total,
                    "estado": "BAJO_MINIMO" if is_low else "OK",
                    "consumo_promedio_diario": avg,
                    "cobertura_dias": None if avg <= 0 else total / avg,
                }
            )
        latest_cd = await _fetch_one(
            db,
            "SELECT fecha_importacion, archivo_origen FROM stock_cd_importado ORDER BY fecha_importacion DESC, id DESC LIMIT 1",
        )
        latest_inv = await _fetch_one(
            db,
            "SELECT fecha_hora, fecha, turno FROM inventario_turno ORDER BY fecha_hora DESC, id DESC LIMIT 1",
        )
        today_moves = await _fetch_one(
            db,
            "SELECT COUNT(*) AS qty FROM movimientos WHERE fecha_hora >= ?",
            (f"{_today()} 00:00:00",),
        )
    return {
        "items": items,
        "metrics": {
            "total_articulos": len(articles),
            "bajo_minimo": sum(1 for item in items if item["estado"] == "BAJO_MINIMO"),
            "movimientos_hoy": int((today_moves or {}).get("qty") or 0),
            "ultima_importacion_cd": latest_cd,
            "ultimo_inventario_oficina": latest_inv,
        },
    }


async def _average_daily_consumption(db: aiosqlite.Connection, articulo_id: int, days: int) -> float:
    row = await _fetch_one(
        db,
        """
        SELECT COALESCE(SUM(consumo_calculado), 0) AS consumo,
               COUNT(DISTINCT fecha) AS dias
        FROM consumos_calculados
        WHERE articulo_id = ?
          AND consumo_calculado > 0
          AND fecha >= date('now', ?)
        """,
        (articulo_id, f"-{int(days)} days"),
    )
    dias = int((row or {}).get("dias") or 0)
    if dias <= 0:
        return 0.0
    return float((row or {}).get("consumo") or 0) / dias


@router.post("/inventario-turno")
async def save_inventory(req: InventoryRequest, request: Request):
    auth = await _require_panol_access(request)
    turno = _norm_code(req.turno)
    fecha = _clean(req.fecha)
    if not fecha or not turno:
        raise HTTPException(status_code=400, detail="Fecha y turno son obligatorios.")
    if not req.items:
        raise HTTPException(status_code=400, detail="No hay articulos para guardar.")
    now = _now()
    observacion = _clean(req.observacion)
    results = []
    async with panol_db() as db:
        turn = await _fetch_one(db, "SELECT 1 FROM turnos WHERE codigo = ? AND activo = 1", (turno,))
        if not turn:
            raise HTTPException(status_code=400, detail="Turno invalido.")
        if req.ubicacion_id:
            location = await _fetch_one(db, "SELECT id, codigo FROM ubicaciones WHERE id = ? AND activo = 1", (req.ubicacion_id,))
        else:
            location = await _fetch_one(db, "SELECT id, codigo FROM ubicaciones WHERE codigo = ? AND activo = 1", (_norm_code(req.ubicacion_codigo or "OFICINA_ADO"),))
        if not location:
            raise HTTPException(status_code=400, detail="Ubicacion invalida.")
        location_id = int(location["id"])
        location_code = _norm_code(location["codigo"])
        is_office = location_code == "OFICINA_ADO"
        is_jaula = location_code == "JAULA"
        if not (is_office or is_jaula):
            raise HTTPException(status_code=400, detail="Solo se permite inventario de Oficina ADO o Jaula.")
        for item in req.items:
            if item.stock_fisico < 0:
                raise HTTPException(status_code=400, detail="El stock fisico no puede ser negativo.")
            art = await _fetch_one(db, "SELECT id, codigo FROM articulos WHERE id = ? AND activo = 1", (item.articulo_id,))
            if not art:
                raise HTTPException(status_code=404, detail=f"Articulo {item.articulo_id} no encontrado.")
            consumo = None
            ingresos = 0.0
            if is_office:
                previous = await _latest_inventory(db, item.articulo_id, location_id)
                stock_initial = float((previous or {}).get("stock_fisico") or 0)
                since = (previous or {}).get("fecha_hora")
                ingresos, egresos = await _office_transfers_since(db, item.articulo_id, since, now)
                consumo = stock_initial + ingresos - egresos - float(item.stock_fisico)
                if consumo < -0.000001 and not observacion:
                    raise HTTPException(
                        status_code=400,
                        detail="Hay diferencias positivas de inventario. Carga una observacion o registra un ajuste.",
                    )
            else:
                stock_initial = await _stock_ubicacion(db, item.articulo_id, location_id)
                diff = float(item.stock_fisico) - stock_initial
                if abs(diff) > 0.000001:
                    await db.execute(
                        """
                        INSERT INTO movimientos
                            (articulo_id, tipo, ubicacion_origen_id, ubicacion_destino_id, cantidad,
                             motivo, observacion, usuario, fecha_hora)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.articulo_id,
                            "AJUSTE_POSITIVO" if diff > 0 else "AJUSTE_NEGATIVO",
                            None if diff > 0 else location_id,
                            location_id if diff > 0 else None,
                            abs(diff),
                            "INVENTARIO_JAULA",
                            observacion or "Ajuste automatico por inventario fisico de Jaula",
                            auth.get("username"),
                            now,
                        ),
                    )
            cur = await db.execute(
                """
                INSERT INTO inventario_turno
                    (articulo_id, ubicacion_id, turno, fecha, stock_fisico, usuario, fecha_hora, observacion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item.articulo_id, location_id, turno, fecha, float(item.stock_fisico), auth.get("username"), now, observacion),
            )
            inv_id = cur.lastrowid
            if is_office:
                await db.execute(
                    """
                    INSERT INTO consumos_calculados
                        (articulo_id, fecha, turno, stock_inicial, ingresos_turno, stock_final,
                         consumo_calculado, usuario, fecha_hora, inventario_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.articulo_id,
                        fecha,
                        turno,
                        stock_initial,
                        ingresos,
                        float(item.stock_fisico),
                        consumo,
                        auth.get("username"),
                        now,
                        inv_id,
                    ),
                )
            results.append(
                {
                    "articulo_id": item.articulo_id,
                    "codigo": art["codigo"],
                    "ubicacion": location_code,
                    "stock_inicial": stock_initial,
                    "ingresos_turno": ingresos,
                    "stock_final": float(item.stock_fisico),
                    "consumo_calculado": consumo,
                    "diferencia": float(item.stock_fisico) - stock_initial if is_jaula else None,
                }
            )
        await db.commit()
    return {"ok": True, "items": results}


@router.get("/inventario-turno")
async def list_inventory(
    request: Request,
    fecha: str = Query(""),
    turno: str = Query(""),
    articulo_id: int | None = Query(None),
    ubicacion_id: int | None = Query(None),
):
    await _require_panol_access(request)
    where = []
    args: list[Any] = []
    if fecha:
        where.append("i.fecha = ?")
        args.append(fecha)
    if turno:
        where.append("i.turno = ?")
        args.append(_norm_code(turno))
    if articulo_id:
        where.append("i.articulo_id = ?")
        args.append(articulo_id)
    if ubicacion_id:
        where.append("i.ubicacion_id = ?")
        args.append(ubicacion_id)
    clause = "WHERE " + " AND ".join(where) if where else ""
    async with panol_db() as db:
        rows = await _fetch_rows(
            db,
            f"""
            SELECT i.*, a.codigo, a.descripcion, u.codigo AS ubicacion_codigo,
                   c.stock_inicial, c.ingresos_turno,
                   c.consumo_calculado
            FROM inventario_turno i
            JOIN articulos a ON a.id = i.articulo_id
            LEFT JOIN ubicaciones u ON u.id = i.ubicacion_id
            LEFT JOIN consumos_calculados c ON c.inventario_id = i.id
            {clause}
            ORDER BY i.fecha_hora DESC, i.id DESC
            LIMIT 500
            """,
            tuple(args),
        )
    return {"items": rows}


def _read_stock_file(file_name: str, content: bytes) -> list[dict[str, Any]]:
    suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    rows: list[dict[str, Any]] = []
    if suffix == "csv":
        text = None
        for encoding in ("utf-8-sig", "latin-1", "cp1252"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise HTTPException(status_code=400, detail="No se pudo leer el CSV con una codificacion soportada.")
        sample = text[:2048]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t") if sample.strip() else csv.excel
        for row in csv.DictReader(io.StringIO(text), dialect=dialect):
            rows.append(row)
        return rows
    if suffix in {"xlsx", "xlsm"}:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        values = list(ws.iter_rows(values_only=True))
        if not values:
            return []
        headers = [_norm_code(v).lower() for v in values[0]]
        for raw in values[1:]:
            rows.append({headers[i]: raw[i] if i < len(raw) else None for i in range(len(headers))})
        return rows
    if suffix == "xls":
        book = xlrd.open_workbook(file_contents=content)
        sheet = book.sheet_by_index(0)
        if sheet.nrows == 0:
            return []
        headers = [_norm_code(sheet.cell_value(0, col)).lower() for col in range(sheet.ncols)]
        for row_idx in range(1, sheet.nrows):
            rows.append({headers[col]: sheet.cell_value(row_idx, col) for col in range(sheet.ncols)})
        return rows
    raise HTTPException(status_code=400, detail="Formato no soportado. Usa CSV o Excel .xlsx.")


@router.post("/importar-stock-cd")
async def import_cd_stock(
    request: Request,
    filename: str = Query("stock_cd.csv"),
    preview: bool = Query(True),
    fecha_reporte: str = Query(""),
):
    auth = await _require_panol_access(request, full=True)
    content = await request.body()
    raw_rows = _read_stock_file(filename or "stock_cd", content)
    now = _now()
    matched = []
    ignored = 0
    errors = []
    async with panol_db() as db:
        articles = await _fetch_rows(db, "SELECT id, codigo FROM articulos WHERE activo = 1")
        by_code = {_norm_code(row["codigo"]): int(row["id"]) for row in articles}
        for index, row in enumerate(raw_rows, start=2):
            codigo = _norm_code(row.get("codigo") or row.get("cod") or row.get("plu") or row.get("referencia"))
            if not codigo or codigo not in by_code:
                ignored += 1
                continue
            try:
                stock_cd = _to_float(
                    row.get("stock_cd")
                    or row.get("stock")
                    or row.get("cantidad")
                    or row.get("unidades")
                )
            except ValueError:
                errors.append({"fila": index, "codigo": codigo, "error": "Stock CD invalido"})
                continue
            if stock_cd < 0:
                errors.append({"fila": index, "codigo": codigo, "error": "Stock CD negativo"})
                continue
            matched.append({"articulo_id": by_code[codigo], "codigo": codigo, "stock_cd": stock_cd})
        if errors:
            return {"ok": False, "preview": True, "matched": matched[:100], "matched_count": len(matched), "ignored": ignored, "errors": errors[:100]}
        if not preview:
            await db.executemany(
                """
                INSERT INTO stock_cd_importado
                    (articulo_id, stock_cd, fecha_reporte, archivo_origen, usuario_importacion, fecha_importacion)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["articulo_id"],
                        row["stock_cd"],
                        _clean(fecha_reporte) or now,
                        filename or "",
                        auth.get("username"),
                        now,
                    )
                    for row in matched
                ],
            )
            await db.commit()
    return {
        "ok": True,
        "preview": preview,
        "matched": matched[:100],
        "matched_count": len(matched),
        "ignored": ignored,
        "errors": [],
        "fecha_importacion": now if not preview else None,
    }


@router.get("/indicadores")
async def indicators(request: Request):
    await _require_panol_access(request)
    async with panol_db() as db:
        daily = await _fetch_rows(
            db,
            """
            SELECT c.articulo_id, a.codigo, a.descripcion, c.fecha,
                   SUM(c.consumo_calculado) AS consumo
            FROM consumos_calculados c
            JOIN articulos a ON a.id = c.articulo_id
            WHERE c.consumo_calculado > 0
            GROUP BY c.articulo_id, c.fecha
            ORDER BY c.fecha DESC, a.codigo
            LIMIT 200
            """,
        )
        by_turn = await _fetch_rows(
            db,
            """
            SELECT c.articulo_id, a.codigo, a.descripcion, c.turno,
                   SUM(c.consumo_calculado) AS consumo
            FROM consumos_calculados c
            JOIN articulos a ON a.id = c.articulo_id
            WHERE c.consumo_calculado > 0
            GROUP BY c.articulo_id, c.turno
            ORDER BY a.codigo, c.turno
            """,
        )
    return {"consumo_diario": daily, "consumo_por_turno": by_turn}


@router.get("/exportar-stock")
async def export_stock(request: Request):
    await _require_panol_access(request)
    data = await stock(request)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["codigo", "descripcion", "categoria", "unidad", "stock_cd", "stock_jaula", "stock_oficina", "stock_total", "stock_minimo", "estado", "cobertura_dias"])
    for row in data["items"]:
        writer.writerow(
            [
                row.get("codigo"),
                row.get("descripcion"),
                row.get("categoria"),
                row.get("unidad"),
                row.get("stock_cd"),
                row.get("stock_jaula"),
                row.get("stock_oficina"),
                row.get("stock_total"),
                row.get("stock_minimo"),
                row.get("estado"),
                row.get("cobertura_dias"),
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=panol_stock.csv"},
    )
