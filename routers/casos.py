"""
VigIA · Gestion de Casos.
Router API para motor comun de tickets y primer detalle especifico de racks.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiosqlite
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from db.casos import PERFILES, init_cases_db
from db.schema import DB_PATH
from routers.auth_local import current_auth

router = APIRouter(prefix="/api/casos", tags=["casos"])

ATTACHMENTS_DIR = Path(os.getenv("VIGIA_CASOS_ATTACHMENTS_DIR", Path(__file__).parent.parent / "resources" / "casos_adjuntos"))
RACK_PARAM_TABLES = {"rack_zona", "rack_cara", "rack_nivel", "rack_sector", "rack_descripcion", "rack_tipo"}
COMMON_PARAM_COLUMNS = {
    "ticket_tipo": {"codigo", "nombre", "descripcion", "activo"},
    "ticket_estado": {"tipo_id", "codigo", "nombre", "perfil_asignado", "orden", "es_inicial", "es_final", "activo"},
    "ticket_estado_transicion": {"tipo_id", "estado_origen_id", "estado_destino_id", "perfil_autorizado", "requiere_comentario", "activo"},
    "ticket_criticidad": {"tipo_id", "codigo", "nombre", "sla_horas", "color", "activo"},
    "ticket_permiso_perfil": {
        "tipo_id", "perfil", "puede_crear", "puede_ver_todos", "puede_ver_sector", "puede_editar",
        "puede_comentar", "puede_adjuntar", "puede_exportar", "activo",
    },
}


class RackNuevoRequest(BaseModel):
    zona_text: str
    pasillo: str
    cara_id: int
    ubicaciones: str
    niveles: list[int]
    sector_rack_id: int
    descripcion_rack_id: int
    criticidad_id: int
    tipo_rack_id: int
    comentario_operativo: str = ""
    fotografias: list[dict[str, str]] = []


class ComentarioRequest(BaseModel):
    comentario: str


class CambioEstadoRequest(BaseModel):
    estado_destino_id: int
    comentario: str = ""


class AdjuntoRequest(BaseModel):
    nombre_original: str
    tipo_mime: str = "application/octet-stream"
    contenido_base64: str


class ParametroRequest(BaseModel):
    id: int | None = None
    codigo: str
    nombre: str
    orden: int = 0
    activo: int = 1


class UsuarioPerfilCasoRequest(BaseModel):
    username: str
    tipo_codigo: str = "REPARACION_RACK"
    perfil: str
    sector: str = ""
    correo: str = ""
    activo: int = 1


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_username(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


async def _case_profile(auth: dict[str, Any], tipo_codigo: str = "REPARACION_RACK") -> str:
    username = _normalize_username(auth.get("username") or "")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await _fetch_one(
            db,
            """
            SELECT perfil
            FROM ticket_usuario_perfil
            WHERE username = ? AND tipo_codigo = ? AND activo = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (username, tipo_codigo),
        )
    if row and row.get("perfil"):
        return str(row["perfil"]).upper()
    if str(auth.get("role") or "").lower() == "admin":
        return "ADMIN"
    return str(os.getenv("VIGIA_CASOS_DEFAULT_PROFILE", "OPERACION")).upper()


async def _case_assignment(auth: dict[str, Any], tipo_codigo: str = "REPARACION_RACK") -> dict[str, str]:
    username = _normalize_username(auth.get("username") or "")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await _fetch_one(
            db,
            """
            SELECT perfil, sector
            FROM ticket_usuario_perfil
            WHERE username = ? AND tipo_codigo = ? AND activo = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (username, tipo_codigo),
        )
    if row:
        return {"perfil": str(row.get("perfil") or "").upper(), "sector": row.get("sector") or ""}
    perfil = "ADMIN" if str(auth.get("role") or "").lower() == "admin" else str(os.getenv("VIGIA_CASOS_DEFAULT_PROFILE", "OPERACION")).upper()
    return {"perfil": perfil, "sector": ""}


async def _require_auth(request: Request) -> tuple[dict[str, Any], str]:
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    assignment = await _case_assignment(auth)
    return auth, assignment["perfil"]


async def _require_admin(request: Request) -> dict[str, Any]:
    auth, _ = await _require_auth(request)
    if str(auth.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Requiere administrador.")
    return auth


async def _fetch_one(db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    async with db.execute(sql, args) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def _fetch_all(db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    async with db.execute(sql, args) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def _tipo_id(db: aiosqlite.Connection, codigo: str = "REPARACION_RACK") -> int:
    row = await _fetch_one(db, "SELECT id FROM ticket_tipo WHERE codigo = ? AND activo = 1", (codigo,))
    if not row:
        raise HTTPException(status_code=404, detail="Tipo de caso no configurado.")
    return int(row["id"])


async def _permiso(db: aiosqlite.Connection, tipo_id: int, perfil: str) -> dict[str, Any]:
    row = await _fetch_one(
        db,
        """
        SELECT *
        FROM ticket_permiso_perfil
        WHERE tipo_id = ? AND perfil = ? AND activo = 1
        """,
        (tipo_id, perfil),
    )
    if not row and perfil != "ADMIN":
        row = await _fetch_one(
            db,
            "SELECT * FROM ticket_permiso_perfil WHERE tipo_id = ? AND perfil = 'OPERACION' AND activo = 1",
            (tipo_id,),
        )
    return row or {}


async def _historial(
    db: aiosqlite.Connection,
    ticket_id: int,
    auth: dict[str, Any],
    perfil: str,
    accion: str,
    comentario: str = "",
    estado_anterior_id: int | None = None,
    estado_nuevo_id: int | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO ticket_historial
            (ticket_id, usuario_id, perfil, accion, estado_anterior_id, estado_nuevo_id, comentario)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (ticket_id, auth["username"], perfil, accion, estado_anterior_id, estado_nuevo_id, comentario),
    )


async def _evento(db: aiosqlite.Connection, ticket_id: int, evento: str, payload: dict[str, Any] | None = None) -> None:
    await db.execute(
        "INSERT INTO ticket_evento_notificacion (ticket_id, evento, payload_json) VALUES (?, ?, ?)",
        (ticket_id, evento, json.dumps(payload or {}, ensure_ascii=False)),
    )


async def _mailto_ticket(
    db: aiosqlite.Connection,
    ticket_id: int,
    evento: str,
    destino: str,
    comentario: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    ticket = await _ticket_row(db, ticket_id)
    destino_norm = str(destino or "").strip().upper()
    rows = await _fetch_all(
        db,
        """
        SELECT DISTINCT correo
        FROM ticket_usuario_perfil
        WHERE tipo_codigo = ?
          AND activo = 1
          AND TRIM(COALESCE(correo, '')) <> ''
          AND (
                UPPER(COALESCE(sector, '')) = ?
                OR UPPER(COALESCE(perfil, '')) = ?
          )
        ORDER BY correo
        """,
        (ticket["tipo_codigo"], destino_norm, destino_norm),
    )
    destinatarios = [row["correo"].strip() for row in rows if row.get("correo")]
    creador = await _fetch_one(
        db,
        """
        SELECT correo
        FROM ticket_usuario_perfil
        WHERE username = ?
          AND tipo_codigo = ?
          AND activo = 1
          AND TRIM(COALESCE(correo, '')) <> ''
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (ticket["usuario_creacion_id"], ticket["tipo_codigo"]),
    )
    copias = []
    creador_correo = str((creador or {}).get("correo") or "").strip()
    if creador_correo and creador_correo.lower() not in {mail.lower() for mail in destinatarios}:
        copias.append(creador_correo)
    url = f"{base_url.rstrip('/')}/casos.html" if base_url else "casos.html"
    subject = f"{ticket['codigo_visible']} - {evento} - {ticket['estado_nombre']}"
    body_lines = [
        f"Caso: {ticket['codigo_visible']}",
        f"Tipo: {ticket['tipo_nombre']}",
        f"Estado: {ticket['estado_nombre']}",
        f"Asignado a: {ticket.get('perfil_asignado') or destino}",
        f"Criticidad: {ticket['criticidad_nombre']}",
        f"Titulo: {ticket['titulo']}",
        f"Ver en VigIA: {url}",
    ]
    if comentario.strip():
        body_lines.extend(["", f"Comentario: {comentario.strip()}"])
    href = ""
    if destinatarios or copias:
        query = []
        if copias:
            query.append(f"cc={quote(';'.join(copias))}")
        query.extend([f"subject={quote(subject)}", f"body={quote(chr(10).join(body_lines))}"])
        href = f"mailto:{';'.join(destinatarios)}?{'&'.join(query)}"
    return {
        "destinatarios": destinatarios,
        "copias": copias,
        "mailto_url": href,
        "asunto": subject,
        "destino": destino_norm,
    }


async def _guardar_adjunto(
    db: aiosqlite.Connection,
    ticket_id: int,
    codigo_visible: str,
    auth: dict[str, Any],
    perfil: str,
    adjunto: dict[str, str],
) -> dict[str, Any]:
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    original = Path(adjunto.get("nombre_original") or "adjunto.bin").name
    mime = adjunto.get("tipo_mime") or "application/octet-stream"
    suffix = Path(original).suffix.lower() or ".bin"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{codigo_visible}_{stamp}_{secrets.token_hex(3)}{suffix}"
    raw = adjunto.get("contenido_base64") or ""
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        content = base64.b64decode(raw, validate=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Adjunto invalido: {original}") from exc
    path = ATTACHMENTS_DIR / filename
    path.write_bytes(content)
    await db.execute(
        """
        INSERT INTO ticket_adjunto
            (ticket_id, usuario_id, nombre_original, nombre_archivo, ruta_archivo, tipo_mime, activo)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (ticket_id, auth["username"], original, filename, str(path), mime),
    )
    await _historial(db, ticket_id, auth, perfil, "AGREGA_ADJUNTO", original)
    return {"nombre_original": original, "nombre_archivo": filename, "tipo_mime": mime}


def _validate_ubicaciones(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Ubicacion obligatoria.")
    parts = [part for part in re.split(r"[\s,;\-/]+", text) if part]
    if not parts or any(not part.isdigit() for part in parts):
        raise HTTPException(
            status_code=400,
            detail='Ubicacion invalida. Usa 55 o multiples posiciones separadas por espacio, coma, punto y coma, guion o barra.',
        )
    return "-".join(parts)


def _validate_pasillo(value: str) -> str:
    text = str(value or "").strip()
    if not text or not text.isdigit():
        raise HTTPException(status_code=400, detail="Pasillo obligatorio y numerico.")
    return text


async def _ticket_row(db: aiosqlite.Connection, ticket_id: int) -> dict[str, Any]:
    row = await _fetch_one(
        db,
        """
        SELECT t.*, tt.codigo tipo_codigo, tt.nombre tipo_nombre, e.codigo estado_codigo, e.nombre estado_nombre,
               e.es_final, c.codigo criticidad_codigo, c.nombre criticidad_nombre, c.color criticidad_color,
               u.display_name creado_por_nombre
        FROM ticket t
        JOIN ticket_tipo tt ON tt.id = t.tipo_id
        JOIN ticket_estado e ON e.id = t.estado_id
        JOIN ticket_criticidad c ON c.id = t.criticidad_id
        LEFT JOIN auth_users u ON u.username = t.usuario_creacion_id
        WHERE t.id = ? AND t.activo = 1
        """,
        (ticket_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Caso no encontrado.")
    return row


@router.get("/config")
async def config(request: Request):
    auth, perfil = await _require_auth(request)
    assignment = await _case_assignment(auth)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        tipos = await _fetch_all(db, "SELECT * FROM ticket_tipo WHERE activo = 1 ORDER BY nombre")
        criticidades = await _fetch_all(db, "SELECT * FROM ticket_criticidad WHERE activo = 1 ORDER BY tipo_id, sla_horas")
        estados = await _fetch_all(db, "SELECT * FROM ticket_estado WHERE activo = 1 ORDER BY tipo_id, orden")
        rack_params = {}
        for table in sorted(RACK_PARAM_TABLES):
            rack_params[table] = await _fetch_all(db, f"SELECT * FROM {table} ORDER BY activo DESC, orden, nombre")
    return {
        "perfil": perfil,
        "sector": assignment.get("sector") or "",
        "tipos": tipos,
        "criticidades": criticidades,
        "estados": estados,
        "rack_params": rack_params,
    }


@router.post("/admin/db/init")
async def admin_init_db(request: Request):
    await _require_admin(request)
    await init_cases_db()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        tables = [
            "ticket_tipo",
            "ticket",
            "ticket_estado",
            "ticket_estado_transicion",
            "ticket_criticidad",
            "ticket_historial",
            "ticket_comentario",
            "ticket_adjunto",
            "ticket_permiso_perfil",
            "ticket_usuario_perfil",
            "ticket_rack_detalle",
            "ticket_evento_notificacion",
            "rack_zona",
            "rack_cara",
            "rack_nivel",
            "rack_sector",
            "rack_descripcion",
            "rack_tipo",
        ]
        counts = {}
        for table in tables:
            row = await _fetch_one(db, f"SELECT COUNT(*) count FROM {table}")
            counts[table] = int(row["count"] if row else 0)
        async with db.execute("PRAGMA table_info(ticket_rack_detalle)") as cur:
            rack_detail_columns = [dict(row) for row in await cur.fetchall()]
    return {
        "ok": True,
        "message": "Gestion de Casos inicializada desde backend.",
        "db_path": str(DB_PATH),
        "counts": counts,
        "ticket_rack_detalle_columns": [row["name"] for row in rack_detail_columns],
    }


@router.get("/admin/usuarios-perfiles")
async def listar_usuarios_perfiles(request: Request, tipo_codigo: str = "REPARACION_RACK"):
    await _require_admin(request)
    tipo_codigo = tipo_codigo.strip().upper() or "REPARACION_RACK"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        usuarios = await _fetch_all(
            db,
            """
            SELECT u.username, u.display_name, u.role, u.active,
                   cup.perfil casos_perfil, cup.sector casos_sector, cup.correo casos_correo,
                   cup.activo casos_activo, cup.updated_at casos_updated_at
            FROM auth_users u
            LEFT JOIN ticket_usuario_perfil cup
                   ON cup.username = u.username AND cup.tipo_codigo = ?
            ORDER BY u.username
            """,
            (tipo_codigo,),
        )
        perfiles_rows = await _fetch_all(
            db,
            """
            SELECT DISTINCT perfil
            FROM ticket_permiso_perfil pp
            JOIN ticket_tipo tt ON tt.id = pp.tipo_id
            WHERE tt.codigo = ? AND pp.activo = 1
            ORDER BY perfil
            """,
            (tipo_codigo,),
        )
    perfiles = sorted({*(row["perfil"] for row in perfiles_rows), *PERFILES})
    return {"usuarios": usuarios, "perfiles": perfiles, "tipo_codigo": tipo_codigo}


@router.post("/admin/usuarios-perfiles")
async def guardar_usuario_perfil(req: UsuarioPerfilCasoRequest, request: Request):
    await _require_admin(request)
    username = _normalize_username(req.username)
    tipo_codigo = req.tipo_codigo.strip().upper() or "REPARACION_RACK"
    perfil = req.perfil.strip().upper()
    sector = " ".join(req.sector.split()) if req.sector else ""
    correo = req.correo.strip()
    activo = 1 if int(req.activo or 0) else 0
    if not username:
        raise HTTPException(status_code=400, detail="Usuario obligatorio.")
    if perfil not in PERFILES:
        raise HTTPException(status_code=400, detail="Perfil de casos invalido.")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM auth_users WHERE username = ?", (username,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        async with db.execute("SELECT 1 FROM ticket_tipo WHERE codigo = ?", (tipo_codigo,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Tipo de caso no encontrado.")
        await db.execute(
            """
            INSERT INTO ticket_usuario_perfil (username, tipo_codigo, perfil, sector, correo, activo, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, tipo_codigo) DO UPDATE SET
                perfil=excluded.perfil,
                sector=excluded.sector,
                correo=excluded.correo,
                activo=excluded.activo,
                updated_at=excluded.updated_at
            """,
            (username, tipo_codigo, perfil, sector or None, correo or None, activo, _now()),
        )
        await db.commit()
    return {"ok": True}


@router.post("/rack")
async def crear_rack(req: RackNuevoRequest, request: Request):
    auth, perfil = await _require_auth(request)
    assignment = await _case_assignment(auth)
    pasillo = _validate_pasillo(req.pasillo)
    ubicaciones = _validate_ubicaciones(req.ubicaciones)
    if not req.niveles:
        raise HTTPException(status_code=400, detail="Selecciona al menos un nivel afectado.")
    if not req.fotografias:
        raise HTTPException(status_code=400, detail="Al menos una fotografia es obligatoria.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        db.row_factory = aiosqlite.Row
        tipo_id = await _tipo_id(db)
        permiso = await _permiso(db, tipo_id, perfil)
        if not permiso.get("puede_crear"):
            raise HTTPException(status_code=403, detail="Tu perfil no puede crear este tipo de caso.")
        criticidad = await _fetch_one(
            db,
            "SELECT * FROM ticket_criticidad WHERE id = ? AND tipo_id = ? AND activo = 1",
            (req.criticidad_id, tipo_id),
        )
        if not criticidad:
            raise HTTPException(status_code=400, detail="Criticidad invalida.")
        if str(criticidad["codigo"]).upper() in {"ALTA", "CRITICA"} and not req.comentario_operativo.strip():
            raise HTTPException(status_code=400, detail="Comentarios obligatorio para criticidad alta o critica.")
        estado = await _fetch_one(db, "SELECT * FROM ticket_estado WHERE tipo_id = ? AND es_inicial = 1 AND activo = 1", (tipo_id,))
        if not estado:
            raise HTTPException(status_code=400, detail="No hay estado inicial configurado.")
        for table, value in [
            ("rack_cara", req.cara_id),
            ("rack_sector", req.sector_rack_id),
            ("rack_descripcion", req.descripcion_rack_id),
            ("rack_tipo", req.tipo_rack_id),
        ]:
            if not await _fetch_one(db, f"SELECT id FROM {table} WHERE id = ? AND activo = 1", (value,)):
                raise HTTPException(status_code=400, detail=f"Parametro invalido: {table}.")
        zona_text = " ".join(req.zona_text.split())
        if not zona_text:
            raise HTTPException(status_code=400, detail="Zona obligatoria.")
        placeholders = ",".join("?" for _ in req.niveles)
        niveles_rows = await _fetch_all(db, f"SELECT id, nombre FROM rack_nivel WHERE id IN ({placeholders}) AND activo = 1", tuple(req.niveles))
        if len(niveles_rows) != len(set(req.niveles)):
            raise HTTPException(status_code=400, detail="Niveles invalidos.")
        sla_vencimiento = (datetime.now() + timedelta(hours=int(criticidad["sla_horas"]))).strftime("%Y-%m-%d %H:%M:%S")
        titulo = f"Reparacion de rack Z{zona_text} P{pasillo} U{ubicaciones}"
        cur = await db.execute(
            """
            INSERT INTO ticket
                (tipo_id, estado_id, criticidad_id, titulo, descripcion, usuario_creacion_id,
                 sector_creacion_id, perfil_asignado, sector_asignado, sla_vencimiento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tipo_id,
                estado["id"],
                req.criticidad_id,
                titulo,
                req.comentario_operativo,
                auth["username"],
                assignment.get("sector") or perfil,
                estado.get("perfil_asignado") or "ADO",
                estado.get("perfil_asignado") or "ADO",
                sla_vencimiento,
            ),
        )
        ticket_id = int(cur.lastrowid)
        codigo_visible = f"RCK-{ticket_id:06d}"
        await db.execute("UPDATE ticket SET codigo_visible = ? WHERE id = ?", (codigo_visible, ticket_id))
        await db.execute(
            """
            INSERT INTO ticket_rack_detalle
                (ticket_id, zona_text, pasillo, cara_id, ubicaciones, niveles, sector_rack_id,
                 descripcion_rack_id, tipo_rack_id, comentario_operativo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                zona_text,
                pasillo,
                req.cara_id,
                ubicaciones,
                json.dumps(req.niveles),
                req.sector_rack_id,
                req.descripcion_rack_id,
                req.tipo_rack_id,
                req.comentario_operativo.strip(),
            ),
        )
        await _historial(db, ticket_id, auth, perfil, "CREACION", "Caso creado", None, int(estado["id"]))
        await _evento(db, ticket_id, "ticket_creado", {"tipo": "REPARACION_RACK"})
        for foto in req.fotografias:
            await _guardar_adjunto(db, ticket_id, codigo_visible, auth, perfil, foto)
        mailto = await _mailto_ticket(
            db,
            ticket_id,
            "Caso creado",
            estado.get("perfil_asignado") or "ADO",
            "Nuevo caso creado y derivado.",
            str(request.base_url),
        )
        await db.commit()
    return {"ok": True, "ticket_id": ticket_id, "codigo_visible": codigo_visible, "mailto": mailto}


@router.get("")
async def listar(
    request: Request,
    tipo_id: int | None = None,
    codigo_visible: str = "",
    estado_id: int | None = None,
    criticidad_id: int | None = None,
    fecha_desde: str = "",
    fecha_hasta: str = "",
    usuario_creador: str = "",
    sector_creador: str = "",
    solo_mis_casos: bool = False,
    pendientes_mi_perfil: bool = False,
    vencidos_sla: bool = False,
):
    auth, perfil = await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = ["t.activo = 1"]
        args: list[Any] = []
        if tipo_id:
            where.append("t.tipo_id = ?")
            args.append(tipo_id)
        if codigo_visible:
            where.append("t.codigo_visible LIKE ?")
            args.append(f"%{codigo_visible.strip()}%")
        if estado_id:
            where.append("t.estado_id = ?")
            args.append(estado_id)
        if criticidad_id:
            where.append("t.criticidad_id = ?")
            args.append(criticidad_id)
        if fecha_desde:
            where.append("date(t.fecha_creacion) >= date(?)")
            args.append(fecha_desde)
        if fecha_hasta:
            where.append("date(t.fecha_creacion) <= date(?)")
            args.append(fecha_hasta)
        if usuario_creador:
            where.append("t.usuario_creacion_id LIKE ?")
            args.append(f"%{usuario_creador.strip()}%")
        if sector_creador:
            where.append("t.sector_creacion_id LIKE ?")
            args.append(f"%{sector_creador.strip()}%")
        if solo_mis_casos:
            where.append("t.usuario_creacion_id = ?")
            args.append(auth["username"])
        if vencidos_sla:
            where.append("t.sla_vencimiento < CURRENT_TIMESTAMP AND e.es_final = 0")
        if pendientes_mi_perfil:
            where.append("t.perfil_asignado = ?")
            args.append(perfil)
        rows = await _fetch_all(
            db,
            f"""
            SELECT t.id, t.codigo_visible, tt.nombre tipo, t.fecha_creacion, e.nombre estado, e.es_final,
                   c.nombre criticidad, c.codigo criticidad_codigo, c.color criticidad_color,
                   t.titulo, t.sector_creacion_id sector, t.perfil_asignado, t.sector_asignado, t.usuario_creacion_id creado_por,
                   t.fecha_ultima_actualizacion, t.sla_vencimiento
            FROM ticket t
            JOIN ticket_tipo tt ON tt.id = t.tipo_id
            JOIN ticket_estado e ON e.id = t.estado_id
            JOIN ticket_criticidad c ON c.id = t.criticidad_id
            WHERE {" AND ".join(where)}
            ORDER BY t.fecha_ultima_actualizacion DESC, t.id DESC
            LIMIT 500
            """,
            tuple(args),
        )
    return {"items": rows, "count": len(rows), "perfil": perfil}


@router.get("/dashboard")
async def dashboard(request: Request):
    auth, perfil = await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        base = await _fetch_one(
            db,
            """
            SELECT
              SUM(CASE WHEN e.es_final = 0 THEN 1 ELSE 0 END) abiertos,
              SUM(CASE WHEN e.es_final = 1 AND date(t.fecha_cierre) = date('now') THEN 1 ELSE 0 END) cerrados_hoy,
              SUM(CASE WHEN e.es_final = 0 AND c.codigo IN ('ALTA','CRITICA') THEN 1 ELSE 0 END) criticos_abiertos,
              SUM(CASE WHEN e.es_final = 0 AND t.sla_vencimiento < CURRENT_TIMESTAMP THEN 1 ELSE 0 END) vencidos_sla
            FROM ticket t
            JOIN ticket_estado e ON e.id = t.estado_id
            JOIN ticket_criticidad c ON c.id = t.criticidad_id
            WHERE t.activo = 1
            """,
        )
        pendientes = await _fetch_one(
            db,
            """
            SELECT COUNT(*) pendientes
            FROM ticket t
            JOIN ticket_estado e ON e.id = t.estado_id
            WHERE t.activo = 1 AND e.es_final = 0 AND t.perfil_asignado = ?
            """,
            (perfil,),
        )
        groups = {}
        for key, sql in {
            "por_tipo": "SELECT tt.nombre label, COUNT(*) value FROM ticket t JOIN ticket_tipo tt ON tt.id=t.tipo_id WHERE t.activo=1 GROUP BY tt.nombre",
            "por_estado": "SELECT e.nombre label, COUNT(*) value FROM ticket t JOIN ticket_estado e ON e.id=t.estado_id WHERE t.activo=1 GROUP BY e.nombre ORDER BY e.orden",
            "por_criticidad": "SELECT c.nombre label, COUNT(*) value FROM ticket t JOIN ticket_criticidad c ON c.id=t.criticidad_id WHERE t.activo=1 GROUP BY c.nombre",
            "por_sector": "SELECT COALESCE(t.sector_creacion_id,'Sin sector') label, COUNT(*) value FROM ticket t WHERE t.activo=1 GROUP BY label",
            "tendencia_creacion": "SELECT date(fecha_creacion) label, COUNT(*) value FROM ticket WHERE activo=1 GROUP BY date(fecha_creacion) ORDER BY label DESC LIMIT 14",
            "tendencia_cierre": "SELECT date(fecha_cierre) label, COUNT(*) value FROM ticket WHERE activo=1 AND fecha_cierre IS NOT NULL GROUP BY date(fecha_cierre) ORDER BY label DESC LIMIT 14",
            "racks_por_zona": "SELECT COALESCE(NULLIF(d.zona_text,''), rz.nombre, 'Sin zona') label, COUNT(*) value FROM ticket_rack_detalle d LEFT JOIN rack_zona rz ON rz.id=d.zona_id GROUP BY label",
            "racks_por_tipo": "SELECT rt.nombre label, COUNT(*) value FROM ticket_rack_detalle d JOIN rack_tipo rt ON rt.id=d.tipo_rack_id GROUP BY rt.nombre",
            "racks_por_descripcion": "SELECT rd.nombre label, COUNT(*) value FROM ticket_rack_detalle d JOIN rack_descripcion rd ON rd.id=d.descripcion_rack_id GROUP BY rd.nombre",
        }.items():
            groups[key] = await _fetch_all(db, sql)
        racks = await _fetch_one(
            db,
            """
            SELECT
              SUM(CASE WHEN e.es_final = 0 THEN 1 ELSE 0 END) abiertos,
              SUM(CASE WHEN e.es_final = 0 AND c.codigo IN ('ALTA','CRITICA') THEN 1 ELSE 0 END) criticos
            FROM ticket t
            JOIN ticket_tipo tt ON tt.id=t.tipo_id
            JOIN ticket_estado e ON e.id=t.estado_id
            JOIN ticket_criticidad c ON c.id=t.criticidad_id
            WHERE tt.codigo='REPARACION_RACK' AND t.activo=1
            """,
        )
    return {"kpis": {**(base or {}), **(pendientes or {})}, "groups": groups, "racks": racks or {}, "user": auth["username"]}


@router.get("/ticket/{ticket_id}")
async def detalle(ticket_id: int, request: Request):
    _, perfil = await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        ticket = await _ticket_row(db, ticket_id)
        rack = None
        if ticket["tipo_codigo"] == "REPARACION_RACK":
            rack = await _fetch_one(
                db,
                """
                SELECT d.*, COALESCE(NULLIF(d.zona_text,''), rz.nombre) zona, rc.nombre cara, rs.nombre sector_rack,
                       rd.nombre descripcion_rack, rt.nombre tipo_rack
                FROM ticket_rack_detalle d
                LEFT JOIN rack_zona rz ON rz.id=d.zona_id
                LEFT JOIN rack_cara rc ON rc.id=d.cara_id
                LEFT JOIN rack_sector rs ON rs.id=d.sector_rack_id
                LEFT JOIN rack_descripcion rd ON rd.id=d.descripcion_rack_id
                LEFT JOIN rack_tipo rt ON rt.id=d.tipo_rack_id
                WHERE d.ticket_id = ?
                """,
                (ticket_id,),
            )
            if rack:
                rack["niveles"] = json.loads(rack.get("niveles") or "[]")
        comentarios = await _fetch_all(db, "SELECT * FROM ticket_comentario WHERE ticket_id=? AND activo=1 ORDER BY fecha", (ticket_id,))
        adjuntos = await _fetch_all(db, "SELECT id, fecha, usuario_id, nombre_original, nombre_archivo, tipo_mime FROM ticket_adjunto WHERE ticket_id=? AND activo=1 ORDER BY fecha", (ticket_id,))
        historial = await _fetch_all(
            db,
            """
            SELECT h.*, ea.nombre estado_anterior, en.nombre estado_nuevo
            FROM ticket_historial h
            LEFT JOIN ticket_estado ea ON ea.id=h.estado_anterior_id
            LEFT JOIN ticket_estado en ON en.id=h.estado_nuevo_id
            WHERE h.ticket_id=?
            ORDER BY h.fecha, h.id
            """,
            (ticket_id,),
        )
        transiciones = await _fetch_all(
            db,
            """
        SELECT tr.id, tr.estado_destino_id, tr.requiere_comentario, e.nombre estado_destino,
               e.perfil_asignado perfil_destino
            FROM ticket_estado_transicion tr
            JOIN ticket_estado e ON e.id=tr.estado_destino_id
            WHERE tr.tipo_id=? AND tr.estado_origen_id=? AND tr.perfil_autorizado=? AND tr.activo=1
            ORDER BY e.orden
            """,
            (ticket["tipo_id"], ticket["estado_id"], perfil),
        )
    return {"ticket": ticket, "rack": rack, "comentarios": comentarios, "adjuntos": adjuntos, "historial": historial, "transiciones": transiciones, "perfil": perfil}


@router.post("/ticket/{ticket_id}/comentarios")
async def comentar(ticket_id: int, req: ComentarioRequest, request: Request):
    auth, perfil = await _require_auth(request)
    comentario = req.comentario.strip()
    if not comentario:
        raise HTTPException(status_code=400, detail="Comentario obligatorio.")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        ticket = await _ticket_row(db, ticket_id)
        permiso = await _permiso(db, int(ticket["tipo_id"]), perfil)
        if not permiso.get("puede_comentar"):
            raise HTTPException(status_code=403, detail="Tu perfil no puede comentar.")
        await db.execute("INSERT INTO ticket_comentario (ticket_id, usuario_id, comentario) VALUES (?, ?, ?)", (ticket_id, auth["username"], comentario))
        await db.execute("UPDATE ticket SET fecha_ultima_actualizacion = ? WHERE id = ?", (_now(), ticket_id))
        await _historial(db, ticket_id, auth, perfil, "AGREGA_COMENTARIO", comentario)
        await db.commit()
    return {"ok": True}


@router.post("/ticket/{ticket_id}/adjuntos")
async def adjuntar(ticket_id: int, req: AdjuntoRequest, request: Request):
    auth, perfil = await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        ticket = await _ticket_row(db, ticket_id)
        permiso = await _permiso(db, int(ticket["tipo_id"]), perfil)
        if not permiso.get("puede_adjuntar"):
            raise HTTPException(status_code=403, detail="Tu perfil no puede adjuntar.")
        saved = await _guardar_adjunto(db, ticket_id, ticket["codigo_visible"], auth, perfil, req.model_dump())
        await db.execute("UPDATE ticket SET fecha_ultima_actualizacion = ? WHERE id = ?", (_now(), ticket_id))
        await db.commit()
    return {"ok": True, "adjunto": saved}


@router.get("/adjuntos/{adjunto_id}/download")
async def descargar_adjunto(adjunto_id: int, request: Request):
    await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        adj = await _fetch_one(db, "SELECT * FROM ticket_adjunto WHERE id=? AND activo=1", (adjunto_id,))
    if not adj or not Path(adj["ruta_archivo"]).exists():
        raise HTTPException(status_code=404, detail="Adjunto no encontrado.")
    return FileResponse(adj["ruta_archivo"], filename=adj["nombre_original"], media_type=adj.get("tipo_mime") or "application/octet-stream")


@router.post("/ticket/{ticket_id}/estado")
async def cambiar_estado(ticket_id: int, req: CambioEstadoRequest, request: Request):
    auth, perfil = await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        ticket = await _ticket_row(db, ticket_id)
        transicion = await _fetch_one(
            db,
            """
            SELECT tr.*, e.es_final, e.perfil_asignado perfil_destino
            FROM ticket_estado_transicion tr
            JOIN ticket_estado e ON e.id=tr.estado_destino_id
            WHERE tr.tipo_id=? AND tr.estado_origen_id=? AND tr.estado_destino_id=?
              AND tr.perfil_autorizado=? AND tr.activo=1
            """,
            (ticket["tipo_id"], ticket["estado_id"], req.estado_destino_id, perfil),
        )
        if not transicion:
            raise HTTPException(status_code=403, detail="Transicion no permitida para tu perfil.")
        comentario = req.comentario.strip()
        if transicion.get("requiere_comentario") and not comentario:
            raise HTTPException(status_code=400, detail="Esta transicion requiere comentario.")
        fecha_cierre = _now() if transicion.get("es_final") else None
        nuevo_perfil = transicion.get("perfil_destino") or ticket.get("perfil_asignado")
        await db.execute(
            """
            UPDATE ticket
            SET estado_id=?, perfil_asignado=?, sector_asignado=?, fecha_ultima_actualizacion=?, fecha_cierre=COALESCE(?, fecha_cierre)
            WHERE id=?
            """,
            (req.estado_destino_id, nuevo_perfil, nuevo_perfil, _now(), fecha_cierre, ticket_id),
        )
        asignacion_msg = f"Asignado a {nuevo_perfil}" if nuevo_perfil else ""
        hist_comment = " | ".join(part for part in [comentario, asignacion_msg] if part)
        await _historial(db, ticket_id, auth, perfil, "CAMBIO_ESTADO", hist_comment, int(ticket["estado_id"]), req.estado_destino_id)
        await _evento(db, ticket_id, "cambio_estado", {"estado_destino_id": req.estado_destino_id, "perfil_asignado": nuevo_perfil})
        if fecha_cierre:
            await _historial(db, ticket_id, auth, perfil, "CIERRE", comentario, int(ticket["estado_id"]), req.estado_destino_id)
            await _evento(db, ticket_id, "ticket_cerrado", {})
        mailto = await _mailto_ticket(
            db,
            ticket_id,
            "Cambio de estado",
            nuevo_perfil or "",
            hist_comment,
            str(request.base_url),
        )
        await db.commit()
    return {"ok": True, "mailto": mailto}


@router.get("/parametros/{tabla}")
async def listar_parametros(tabla: str, request: Request):
    await _require_auth(request)
    if tabla not in RACK_PARAM_TABLES:
        raise HTTPException(status_code=400, detail="Tabla de parametros invalida.")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _fetch_all(db, f"SELECT * FROM {tabla} ORDER BY activo DESC, orden, nombre")
    return {"items": rows}


@router.post("/parametros/{tabla}")
async def guardar_parametro(tabla: str, req: ParametroRequest, request: Request):
    _, perfil = await _require_auth(request)
    if perfil != "ADMIN":
        raise HTTPException(status_code=403, detail="Solo ADMIN puede administrar parametros.")
    if tabla not in RACK_PARAM_TABLES:
        raise HTTPException(status_code=400, detail="Tabla de parametros invalida.")
    async with aiosqlite.connect(DB_PATH) as db:
        if req.id:
            await db.execute(
                f"UPDATE {tabla} SET codigo=?, nombre=?, orden=?, activo=? WHERE id=?",
                (req.codigo.strip().upper(), req.nombre.strip(), req.orden, int(req.activo), req.id),
            )
        else:
            await db.execute(
                f"INSERT INTO {tabla} (codigo, nombre, orden, activo) VALUES (?, ?, ?, ?)",
                (req.codigo.strip().upper(), req.nombre.strip(), req.orden, int(req.activo)),
            )
        await db.commit()
    return {"ok": True}


@router.get("/parametros-comunes/{tabla}")
async def listar_parametros_comunes(tabla: str, request: Request):
    await _require_auth(request)
    if tabla not in COMMON_PARAM_COLUMNS:
        raise HTTPException(status_code=400, detail="Tabla comun invalida.")
    order = "id"
    if tabla == "ticket_estado":
        order = "tipo_id, orden, id"
    elif tabla == "ticket_criticidad":
        order = "tipo_id, sla_horas, id"
    elif tabla == "ticket_estado_transicion":
        order = "tipo_id, estado_origen_id, id"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _fetch_all(db, f"SELECT * FROM {tabla} ORDER BY {order}")
    return {"items": rows, "columns": ["id", *sorted(COMMON_PARAM_COLUMNS[tabla])]}


@router.post("/parametros-comunes/{tabla}")
async def guardar_parametro_comun(tabla: str, request: Request, payload: dict[str, Any] = Body(...)):
    _, perfil = await _require_auth(request)
    if perfil != "ADMIN":
        raise HTTPException(status_code=403, detail="Solo ADMIN puede administrar parametros.")
    if tabla not in COMMON_PARAM_COLUMNS:
        raise HTTPException(status_code=400, detail="Tabla comun invalida.")
    allowed = COMMON_PARAM_COLUMNS[tabla]
    item_id = payload.get("id")
    values = {k: payload[k] for k in allowed if k in payload}
    if not values:
        raise HTTPException(status_code=400, detail="No hay campos validos para guardar.")
    async with aiosqlite.connect(DB_PATH) as db:
        if item_id:
            assignments = ", ".join(f"{column}=?" for column in values)
            await db.execute(f"UPDATE {tabla} SET {assignments} WHERE id=?", (*values.values(), item_id))
        else:
            columns = ", ".join(values.keys())
            placeholders = ", ".join("?" for _ in values)
            await db.execute(f"INSERT INTO {tabla} ({columns}) VALUES ({placeholders})", tuple(values.values()))
        await db.commit()
    return {"ok": True}


@router.get("/export/csv")
async def export_csv(request: Request, tipo_id: int | None = Query(None)):
    await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = "WHERE t.activo = 1"
        args: tuple[Any, ...] = ()
        if tipo_id:
            where += " AND t.tipo_id = ?"
            args = (tipo_id,)
        rows = await _fetch_all(
            db,
            f"""
            SELECT t.codigo_visible, tt.nombre tipo, t.fecha_creacion, e.nombre estado, c.nombre criticidad,
                   t.titulo, t.sector_creacion_id sector, t.usuario_creacion_id creado_por,
                   t.fecha_ultima_actualizacion, t.sla_vencimiento,
                   COALESCE(NULLIF(d.zona_text,''), rz.nombre) zona, d.pasillo, rc.nombre cara, d.ubicaciones, d.niveles,
                   rt.nombre tipo_rack, rd.nombre descripcion_rack
            FROM ticket t
            JOIN ticket_tipo tt ON tt.id=t.tipo_id
            JOIN ticket_estado e ON e.id=t.estado_id
            JOIN ticket_criticidad c ON c.id=t.criticidad_id
            LEFT JOIN ticket_rack_detalle d ON d.ticket_id=t.id
            LEFT JOIN rack_zona rz ON rz.id=d.zona_id
            LEFT JOIN rack_cara rc ON rc.id=d.cara_id
            LEFT JOIN rack_tipo rt ON rt.id=d.tipo_rack_id
            LEFT JOIN rack_descripcion rd ON rd.id=d.descripcion_rack_id
            {where}
            ORDER BY t.fecha_creacion DESC
            """,
            args,
        )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else ["codigo_visible"])
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=casos.csv"},
    )
