"""Recepcion de refrigerados: Oracle para maestros, SQLite para operacion."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from db.recepcion import RECEPCION_DB_PATH
from routers.analisis_premio_productividad import _query_oracle
from routers.auth_local import current_auth

router = APIRouter(prefix="/api/recepcion", tags=["recepcion"])
ROOT_DIR = Path(__file__).resolve().parent.parent
PHOTOS_DIR = Path(os.getenv("VIGIA_RECEPCION_FOTOS_DIR", ROOT_DIR / "resources" / "recepcion_fotos"))
MAX_PHOTOS = int(os.getenv("VIGIA_RECEPCION_MAX_PHOTOS", "50"))
MAX_PHOTO_BYTES = int(os.getenv("VIGIA_RECEPCION_MAX_PHOTO_BYTES", str(15 * 1024 * 1024)))


async def _auth(request: Request) -> dict[str, Any]:
    auth = await current_auth(request)
    if not auth:
        raise HTTPException(status_code=401, detail="Sesion no valida.")
    return auth


async def _db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(RECEPCION_DB_PATH, timeout=60)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA busy_timeout = 60000")
    return db


def _oracle_rows(sql: str, binds: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return _query_oracle(sql, binds or {})


def _clean(value: Any) -> str:
    return str(value or "").strip()


async def _catalog(sql: str, binds: dict[str, Any], code_key: str, name_key: str) -> list[dict[str, str]]:
    rows = await asyncio.to_thread(_oracle_rows, sql, binds)
    return [{"codigo": _clean(row.get(code_key)), "nombre": _clean(row.get(name_key))} for row in rows]


@router.get("/catalogos/proveedores")
async def proveedores(request: Request, q: str = Query("", min_length=0, max_length=80)):
    await _auth(request)
    term = _clean(q).upper()
    sql = """
        SELECT cproveed AS Codigo, drazsoci AS Proveedor
        FROM f041prov
        WHERE (:q = '' OR UPPER(drazsoci) LIKE '%' || UPPER(:q) || '%' OR TO_CHAR(cproveed) LIKE '%' || :q || '%')
        AND ROWNUM <= 50
        ORDER BY drazsoci
    """
    return {"items": await _catalog(sql, {"q": term}, "CODIGO", "PROVEEDOR")}


@router.get("/catalogos/plus")
async def plus(request: Request, q: str = Query("", min_length=0, max_length=80)):
    await _auth(request)
    term = _clean(q).upper()
    sql = """
        SELECT plu, articulo
        FROM (
            SELECT a.creferen AS PLU, a.darticul AS Articulo
            FROM f002arti a
            WHERE (
                :q = ''
                OR TO_CHAR(a.creferen) LIKE '%' || :q || '%'
                OR UPPER(a.darticul) LIKE '%' || UPPER(:q) || '%'
            )
            AND EXISTS (
                SELECT 1
                FROM f602asec s
                WHERE s.creferen = a.creferen
                  AND s.cnsector IN (
                      'CO', 'FQ', 'HU', 'PA', 'F4',
                      'FB', 'F1', 'VE', 'MO', 'FC', 'BA'
                  )
            )
            ORDER BY a.darticul, a.creferen
        )
        WHERE ROWNUM <= 50
    """
    return {"items": await _catalog(sql, {"q": term}, "PLU", "ARTICULO")}


@router.get("/catalogos/legajos")
async def legajos(request: Request, q: str = Query("", min_length=0, max_length=80)):
    await _auth(request)
    term = _clean(q)
    sql = """
        SELECT CAST(legajo AS int) AS LEGAJO, Nombre
        FROM WF_ACTIVE_EMPLOYEE
        WHERE (:q = '' OR TO_CHAR(legajo) LIKE '%' || :q || '%' OR UPPER(Nombre) LIKE '%' || UPPER(:q) || '%')
        AND ROWNUM <= 100
        ORDER BY Nombre
    """
    return {"items": await _catalog(sql, {"q": term}, "LEGAJO", "NOMBRE")}


@router.get("")
async def listar(request: Request, fecha_desde: str = "", fecha_hasta: str = "", q: str = "", limit: int = Query(100, ge=1, le=500)):
    await _auth(request)
    clauses, args = [], []
    if fecha_desde:
        clauses.append("r.fecha_descarga >= ?"); args.append(fecha_desde)
    if fecha_hasta:
        clauses.append("r.fecha_descarga <= ?"); args.append(fecha_hasta + " 23:59:59")
    if _clean(q):
        clauses.append("(UPPER(r.proveedor_nombre) LIKE ? OR r.proveedor_codigo LIKE ? OR EXISTS (SELECT 1 FROM recepcion_plus p WHERE p.recepcion_id=r.id AND (p.plu_codigo LIKE ? OR UPPER(p.plu_articulo) LIKE ?)))")
        term = f"%{_clean(q).upper()}%"; args.extend([term, f"%{_clean(q)}%", f"%{_clean(q)}%", term])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    db = await _db()
    try:
        async with db.execute(f"""
            SELECT r.*, COUNT(DISTINCT p.id) AS cantidad_plus, COUNT(DISTINCT f.id) AS cantidad_fotos
            FROM recepciones r
            LEFT JOIN recepcion_plus p ON p.recepcion_id=r.id
            LEFT JOIN recepcion_fotos f ON f.recepcion_id=r.id
            {where}
            GROUP BY r.id ORDER BY r.id DESC LIMIT ?
        """, (*args, limit)) as cur:
            return {"items": [dict(row) for row in await cur.fetchall()]}
    finally:
        await db.close()


@router.get("/fotos/{foto_id}")
async def foto(foto_id: int, request: Request):
    await _auth(request)
    db = await _db()
    try:
        async with db.execute("SELECT * FROM recepcion_fotos WHERE id=?", (foto_id,)) as cur:
            row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Foto no encontrada.")
    path = PHOTOS_DIR / Path(row["nombre_archivo"]).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Archivo de foto no encontrado en el backend.")
    return FileResponse(str(path), filename=row["nombre_original"], media_type=row["tipo_mime"] or "application/octet-stream")


@router.get("/{recepcion_id}")
async def detalle(recepcion_id: int, request: Request):
    await _auth(request)
    db = await _db()
    try:
        async with db.execute("SELECT * FROM recepciones WHERE id=?", (recepcion_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Recepcion no encontrada.")
        async with db.execute("SELECT * FROM recepcion_plus WHERE recepcion_id=? ORDER BY id", (recepcion_id,)) as cur:
            plus_rows = [dict(x) for x in await cur.fetchall()]
        async with db.execute("SELECT id,recepcion_plus_id,nombre_original,tipo_mime,tamano_bytes,created_at FROM recepcion_fotos WHERE recepcion_id=? ORDER BY id", (recepcion_id,)) as cur:
            fotos = [dict(x) for x in await cur.fetchall()]
        return {"recepcion": dict(row), "plus": plus_rows, "fotos": fotos}
    finally:
        await db.close()


@router.post("")
async def crear(
    request: Request,
    fecha_descarga: str = Form(...),
    proveedor_codigo: str = Form(...),
    proveedor_nombre: str = Form(...),
    recepcionista_legajo: str = Form(...),
    recepcionista_nombre: str = Form(...),
    pallets_recibidos: int = Form(..., ge=0),
    pallets_auditados: int = Form(..., ge=0),
    cuenta_con_novedad: bool = Form(False),
    observacion: str = Form(""),
    plus_json: str = Form(...),
    foto_plu_indices: str = Form("[]"),
    fotos: list[UploadFile] = File(default=[]),
):
    auth = await _auth(request)
    if not all((_clean(proveedor_codigo), _clean(proveedor_nombre), _clean(recepcionista_legajo), _clean(recepcionista_nombre))):
        raise HTTPException(status_code=400, detail="Debe seleccionar proveedor y recepcionista desde Oracle.")
    try:
        plus_rows = json.loads(plus_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Detalle de PLU invalido.") from exc
    try:
        foto_indices = json.loads(foto_plu_indices or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Relacion de fotos por PLU invalida.") from exc
    if not isinstance(foto_indices, list):
        raise HTTPException(status_code=400, detail="Relacion de fotos por PLU invalida.")
    if not foto_indices and fotos:
        foto_indices = [None] * len(fotos)
    if len(foto_indices) != len(fotos):
        raise HTTPException(status_code=400, detail="La cantidad de relaciones de fotos no coincide con los archivos.")
    if not isinstance(plus_rows, list) or not plus_rows:
        raise HTTPException(status_code=400, detail="Debe agregar al menos un PLU.")
    if len(fotos) > MAX_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Se permiten hasta {MAX_PHOTOS} fotos.")
    for item in plus_rows:
        if not _clean(item.get("plu_codigo")) or not _clean(item.get("plu_articulo")):
            raise HTTPException(status_code=400, detail="Cada PLU debe tener codigo y articulo.")
    if pallets_auditados > pallets_recibidos:
        raise HTTPException(status_code=400, detail="Los pallets auditados no pueden superar los recibidos.")

    db = await _db()
    saved_paths: list[Path] = []
    try:
        cursor = await db.execute("""
            INSERT INTO recepciones (fecha_descarga, proveedor_codigo, proveedor_nombre, recepcionista_legajo,
                recepcionista_nombre, pallets_recibidos, pallets_auditados, cuenta_con_novedad, observacion, creado_por)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (fecha_descarga, _clean(proveedor_codigo), _clean(proveedor_nombre), _clean(recepcionista_legajo),
              _clean(recepcionista_nombre), pallets_recibidos, pallets_auditados, int(cuenta_con_novedad), _clean(observacion), auth["username"]))
        recepcion_id = cursor.lastrowid
        plus_ids: list[int] = []
        for item in plus_rows:
            plus_cursor = await db.execute(
                "INSERT INTO recepcion_plus (recepcion_id,plu_codigo,plu_articulo,afectacion,observacion) VALUES (?,?,?,?,?)",
                (recepcion_id, _clean(item.get("plu_codigo")), _clean(item.get("plu_articulo")), item.get("afectacion") or None, _clean(item.get("observacion"))),
            )
            plus_ids.append(plus_cursor.lastrowid)
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        for foto_index, upload in enumerate(fotos):
            plu_index = foto_indices[foto_index]
            plus_id = None
            if plu_index is not None:
                if isinstance(plu_index, bool) or not isinstance(plu_index, int) or plu_index < 0 or plu_index >= len(plus_ids):
                    raise HTTPException(status_code=400, detail="Una foto referencia un PLU invalido.")
                plus_id = plus_ids[plu_index]
            original = Path(upload.filename or "foto.jpg").name
            content = await upload.read()
            if len(content) > MAX_PHOTO_BYTES:
                raise HTTPException(status_code=400, detail=f"La foto {original} supera el limite permitido.")
            suffix = Path(original).suffix.lower() or ".jpg"
            scope = f"plu_{plus_id}_" if plus_id else "general_"
            filename = f"recepcion_{recepcion_id}_{scope}{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}{suffix}"
            path = PHOTOS_DIR / filename
            path.write_bytes(content); saved_paths.append(path)
            await db.execute("""INSERT INTO recepcion_fotos (recepcion_id,recepcion_plus_id,nombre_original,nombre_archivo,ruta_archivo,tipo_mime,tamano_bytes,creado_por)
                VALUES (?,?,?,?,?,?,?,?)""", (recepcion_id, plus_id, original, filename, filename, upload.content_type or mimetypes.guess_type(original)[0], len(content), auth["username"]))
        await db.commit()
        return {"ok": True, "id": recepcion_id}
    except Exception:
        await db.rollback()
        for path in saved_paths:
            path.unlink(missing_ok=True)
        raise
    finally:
        await db.close()
