"""
VigIA · Gestion de Casos.
Router API para motor comun de tickets y primer detalle especifico de racks.
"""
from __future__ import annotations

import base64
import asyncio
import csv
import difflib
import io
import json
import logging
import mimetypes
import os
import re
import secrets
import subprocess
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from db.auth import attach_auth_db, auth_db
from db.casos import PERFILES, init_cases_db
from db.schema import DB_PATH
from routers.auth_local import current_auth

router = APIRouter(prefix="/api/casos", tags=["casos"])
logger = logging.getLogger("vigia.casos")

try:
    CASES_TZ = ZoneInfo(os.getenv("VIGIA_CASES_TIMEZONE", "America/Buenos_Aires"))
except ZoneInfoNotFoundError:
    CASES_TZ = timezone(timedelta(hours=-3))
ATTACHMENTS_DIR = Path(os.getenv("VIGIA_CASOS_ATTACHMENTS_DIR", Path(__file__).parent.parent / "resources" / "casos_adjuntos"))
FORMS_ATTACHMENT_ERROR_PREFIX = "No se pudieron adjuntar fotos Forms:"
JAVA_HELPER_SRC = Path(__file__).parent.parent / "scripts" / "OracleProductividadQuery.java"
JAVA_BUILD_DIR = Path(__file__).parent.parent / ".codex_tmp" / "java_build"
RACK_PARAM_TABLES = {"rack_zona", "rack_cara", "rack_nivel", "rack_sector", "rack_descripcion", "rack_tipo"}
_FORMS_IMPORT_TASK: asyncio.Task | None = None
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
    service_externo_id: str = ""
    traspasos_wms: str = ""
    vaciado_confirmado: bool = False
    inutilizacion_wms_confirmada: bool = False
    mantenimiento_finalizado: bool = False
    relevamiento_mapa: str = ""
    reetiquetado_requerido: bool = False
    rehabilitacion_wms_confirmada: bool = False


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


class FormsReclamoRequest(BaseModel):
    comentario: str = ""


def _now() -> str:
    return datetime.now(CASES_TZ).strftime("%Y-%m-%d %H:%M:%S")


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
    return ""


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
    if str(auth.get("role") or "").lower() == "admin":
        return {"perfil": "ADMIN", "sector": "ADMIN"}
    return {"perfil": "", "sector": ""}


async def _require_auth(request: Request) -> tuple[dict[str, Any], str]:
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    assignment = await _case_assignment(auth)
    if not assignment["perfil"]:
        raise HTTPException(status_code=403, detail="Sin acceso a Gestion de Casos.")
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
            (ticket_id, fecha, usuario_id, perfil, accion, estado_anterior_id, estado_nuevo_id, comentario)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ticket_id, _now(), auth["username"], perfil, accion, estado_anterior_id, estado_nuevo_id, comentario),
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
    stamp = datetime.now(CASES_TZ).strftime("%Y%m%d_%H%M%S")
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
            (ticket_id, fecha, usuario_id, nombre_original, nombre_archivo, ruta_archivo, tipo_mime, activo)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (ticket_id, _now(), auth["username"], original, filename, str(path), mime),
    )
    await _historial(db, ticket_id, auth, perfil, "AGREGA_ADJUNTO", original)
    return {"nombre_original": original, "nombre_archivo": filename, "tipo_mime": mime}


async def _guardar_adjunto_bytes(
    db: aiosqlite.Connection,
    ticket_id: int,
    codigo_visible: str,
    auth: dict[str, Any],
    perfil: str,
    nombre_original: str,
    tipo_mime: str,
    content: bytes,
) -> dict[str, Any]:
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    original = Path(nombre_original or "adjunto.bin").name
    mime = tipo_mime or mimetypes.guess_type(original)[0] or "application/octet-stream"
    suffix = Path(original).suffix.lower() or ".bin"
    stamp = datetime.now(CASES_TZ).strftime("%Y%m%d_%H%M%S")
    filename = f"{codigo_visible}_{stamp}_{secrets.token_hex(3)}{suffix}"
    path = ATTACHMENTS_DIR / filename
    path.write_bytes(content)
    await db.execute(
        """
        INSERT INTO ticket_adjunto
            (ticket_id, fecha, usuario_id, nombre_original, nombre_archivo, ruta_archivo, tipo_mime, activo)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (ticket_id, _now(), auth["username"], original, filename, str(path), mime),
    )
    await _historial(db, ticket_id, auth, perfil, "AGREGA_ADJUNTO_FORMS", original)
    return {"nombre_original": original, "nombre_archivo": filename, "tipo_mime": mime}


def _validate_ubicaciones(value: str) -> str:
    text = str(value or "").strip().upper()
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
    text = str(value or "").strip().upper()
    if not text or not text.isdigit():
        raise HTTPException(status_code=400, detail="Pasillo obligatorio y numerico.")
    return text


def _productive_db_local_only_enabled() -> bool:
    return os.getenv("PRODUCTIVE_DB_LOCAL_ONLY", "0").strip().lower() in {"1", "true", "yes", "si"}


def _ensure_rack_java_helper_compiled() -> None:
    javac_bin = os.getenv(
        "PRODUCTIVE_DB_JAVAC_BIN",
        r"C:\Program Files\Android\openjdk\jdk-21.0.8\bin\javac.exe",
    ).strip()
    if not Path(javac_bin).exists():
        raise RuntimeError(f"No se encontro javac para el fallback JDBC: {javac_bin}")

    JAVA_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    class_file = JAVA_BUILD_DIR / "OracleProductividadQuery.class"
    if class_file.exists() and class_file.stat().st_mtime >= JAVA_HELPER_SRC.stat().st_mtime:
        return

    result = subprocess.run(
        [javac_bin, "-d", str(JAVA_BUILD_DIR), str(JAVA_HELPER_SRC)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"No se pudo compilar el helper JDBC de Oracle. STDERR: {result.stderr.strip() or result.stdout.strip()}")


def _query_rack_oracle_stock_jdbc(zona: str, pasillo_cara: str, ubicaciones: list[str]) -> list[dict[str, Any]]:
    if _productive_db_local_only_enabled():
        raise RuntimeError("La BD productiva Oracle esta temporalmente bloqueada por configuracion.")

    user = os.getenv("PRODUCTIVE_DB_USER", "").strip()
    password = os.getenv("PRODUCTIVE_DB_PASSWORD", "").strip()
    host = os.getenv("PRODUCTIVE_DB_HOST", "").strip()
    port = os.getenv("PRODUCTIVE_DB_PORT", "1521").strip()
    service_name = os.getenv("PRODUCTIVE_DB_SERVICE_NAME", "").strip()
    java_bin = os.getenv(
        "PRODUCTIVE_DB_JAVA_BIN",
        r"C:\Users\207189\AppData\Local\DBeaver\jre\bin\java.exe",
    ).strip()
    ojdbc_jar = os.getenv(
        "PRODUCTIVE_DB_OJDBC_JAR",
        r"C:\Users\207189\AppData\Roaming\DBeaverData\drivers\maven\maven-central\com.oracle.database.jdbc\ojdbc11-23.2.0.0.jar",
    ).strip()

    if not all([user, password, host, service_name]):
        raise RuntimeError("Faltan variables JDBC PRODUCTIVE_DB_USER, PRODUCTIVE_DB_PASSWORD, PRODUCTIVE_DB_HOST o PRODUCTIVE_DB_SERVICE_NAME.")
    if not Path(java_bin).exists():
        raise RuntimeError(f"No se encontro Java para fallback JDBC: {java_bin}")
    if not Path(ojdbc_jar).exists():
        raise RuntimeError(f"No se encontro el driver JDBC Oracle: {ojdbc_jar}")

    _ensure_rack_java_helper_compiled()
    jdbc_url = f"jdbc:oracle:thin:@//{host}:{port}/{service_name}"
    classpath = os.pathsep.join([str(JAVA_BUILD_DIR), ojdbc_jar])
    command = [
        java_bin,
        "-cp",
        classpath,
        "OracleProductividadQuery",
        jdbc_url,
        user,
        password,
        "2000-01-01 00:00:00",
        "2000-01-01 00:00:00",
        "rack_stock",
        zona,
        pasillo_cara,
        ",".join(ubicaciones),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=int(os.getenv("PRODUCTIVE_DB_JDBC_TIMEOUT_SECONDS", "300")),
    )
    if result.returncode != 0:
        raise RuntimeError(f"No se pudo consultar Oracle via JDBC. STDERR: {result.stderr.strip() or result.stdout.strip()}")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"La respuesta JDBC no fue JSON valido. Salida: {result.stdout[:300]}") from exc

    normalized = []
    for row in rows:
        normalized.append(
            {
                "czonalma": str(row.get("CZONALMA") or row.get("czonalma") or "").strip().upper(),
                "cpasillo": str(row.get("CPASILLO") or row.get("cpasillo") or "").strip().upper(),
                "chuecopa": str(row.get("CHUECOPA") or row.get("chuecopa") or "").strip().upper(),
                "palet": str(row.get("PALET") or row.get("palet") or "").strip().upper(),
                "articulo": str(row.get("ARTICULO") or row.get("articulo") or "").strip().upper(),
            }
        )
    return normalized


def _query_rack_oracle_stock(zona: str, pasillo_cara: str, ubicaciones: list[str]) -> list[dict[str, Any]]:
    zona = str(zona or "").strip().upper()
    pasillo_cara = str(pasillo_cara or "").strip().upper()
    prefixes = [str(u or "").strip().upper() for u in ubicaciones if str(u or "").strip()]
    prefixes = list(dict.fromkeys(prefixes))
    if not zona or not pasillo_cara or not prefixes:
        return []
    return _query_rack_oracle_stock_jdbc(zona, pasillo_cara, prefixes)


def _query_rack_oracle_inutilizadas_jdbc() -> list[dict[str, Any]]:
    if _productive_db_local_only_enabled():
        raise RuntimeError("La BD productiva Oracle esta temporalmente bloqueada por configuracion.")

    user = os.getenv("PRODUCTIVE_DB_USER", "").strip()
    password = os.getenv("PRODUCTIVE_DB_PASSWORD", "").strip()
    host = os.getenv("PRODUCTIVE_DB_HOST", "").strip()
    port = os.getenv("PRODUCTIVE_DB_PORT", "1521").strip()
    service_name = os.getenv("PRODUCTIVE_DB_SERVICE_NAME", "").strip()
    java_bin = os.getenv(
        "PRODUCTIVE_DB_JAVA_BIN",
        r"C:\Users\207189\AppData\Local\DBeaver\jre\bin\java.exe",
    ).strip()
    ojdbc_jar = os.getenv(
        "PRODUCTIVE_DB_OJDBC_JAR",
        r"C:\Users\207189\AppData\Roaming\DBeaverData\drivers\maven\maven-central\com.oracle.database.jdbc\ojdbc11-23.2.0.0.jar",
    ).strip()

    if not all([user, password, host, service_name]):
        raise RuntimeError("Faltan variables JDBC PRODUCTIVE_DB_USER, PRODUCTIVE_DB_PASSWORD, PRODUCTIVE_DB_HOST o PRODUCTIVE_DB_SERVICE_NAME.")
    if not Path(java_bin).exists():
        raise RuntimeError(f"No se encontro Java para fallback JDBC: {java_bin}")
    if not Path(ojdbc_jar).exists():
        raise RuntimeError(f"No se encontro el driver JDBC Oracle: {ojdbc_jar}")

    _ensure_rack_java_helper_compiled()
    jdbc_url = f"jdbc:oracle:thin:@//{host}:{port}/{service_name}"
    classpath = os.pathsep.join([str(JAVA_BUILD_DIR), ojdbc_jar])
    command = [
        java_bin,
        "-cp",
        classpath,
        "OracleProductividadQuery",
        jdbc_url,
        user,
        password,
        "2000-01-01 00:00:00",
        "2000-01-01 00:00:00",
        "rack_inutilizadas",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=int(os.getenv("PRODUCTIVE_DB_JDBC_TIMEOUT_SECONDS", "300")),
    )
    if result.returncode != 0:
        raise RuntimeError(f"No se pudo consultar Oracle via JDBC. STDERR: {result.stderr.strip() or result.stdout.strip()}")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"La respuesta JDBC no fue JSON valido. Salida: {result.stdout[:300]}") from exc

    normalized = []
    for row in rows:
        normalized.append(
            {
                "czonalma": str(row.get("CZONALMA") or row.get("czonalma") or "").strip().upper(),
                "cpasillo": str(row.get("CPASILLO") or row.get("cpasillo") or "").strip().upper(),
                "chuecopa": str(row.get("CHUECOPA") or row.get("chuecopa") or "").strip().upper(),
                "qpalaltu": row.get("QPALALTU") or row.get("qpalaltu"),
                "fcreareg": str(row.get("FCREAREG") or row.get("fcreareg") or "").strip(),
                "usuacrea": str(row.get("USUACREA") or row.get("usuacrea") or "").strip(),
                "movimien": str(row.get("MOVIMIEN") or row.get("movimien") or "").strip(),
                "observac": str(row.get("OBSERVAC") or row.get("observac") or "").strip(),
            }
        )
    return normalized


def _position_key(zona: str, pasillo_cara: str, chuecopa: str) -> str:
    return "|".join([
        str(zona or "").strip().upper(),
        str(pasillo_cara or "").strip().upper(),
        str(chuecopa or "").strip().upper(),
    ])


def _position_label(zona: str, pasillo_cara: str, chuecopa: str) -> str:
    return f"{str(zona or '').strip().upper()}{str(pasillo_cara or '').strip().upper()}{str(chuecopa or '').strip().upper()}"


def _split_position_parts(value: Any) -> list[str]:
    return [part for part in re.split(r"[^A-Z0-9]+", str(value or "").strip().upper()) if part]


async def _active_service_locations(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    rows = await _fetch_all(
        db,
        """
        SELECT
            t.id ticket_id,
            t.codigo_visible,
            t.titulo,
            t.fecha_creacion,
            t.fecha_ultima_actualizacion,
            e.codigo estado_codigo,
            e.nombre estado,
            d.zona_text,
            d.pasillo,
            d.ubicaciones,
            d.niveles,
            rc.nombre cara
        FROM ticket t
        JOIN ticket_estado e ON e.id=t.estado_id
        JOIN ticket_rack_detalle d ON d.ticket_id=t.id
        LEFT JOIN rack_cara rc ON rc.id=d.cara_id
        WHERE t.activo=1 AND e.es_final=0
        ORDER BY t.fecha_ultima_actualizacion DESC, t.id DESC
        """,
    )
    nivel_rows = await _fetch_all(db, "SELECT id, codigo, nombre FROM rack_nivel WHERE activo=1")
    nivel_map = {int(row["id"]): str(row.get("nombre") or row.get("codigo") or "").strip().upper() for row in nivel_rows}
    locations = []
    for row in rows:
        zona = str(row.get("zona_text") or "").strip().upper()
        pasillo = str(row.get("pasillo") or "").strip().upper()
        cara = str(row.get("cara") or "").strip().upper()
        pasillo_cara = f"{pasillo}{cara}"
        ubicaciones = _split_position_parts(row.get("ubicaciones"))
        try:
            nivel_ids = json.loads(row.get("niveles") or "[]")
        except Exception:
            nivel_ids = []
        niveles = []
        for nivel_id in nivel_ids:
            text_id = str(nivel_id).strip()
            if not text_id:
                continue
            try:
                niveles.append(nivel_map.get(int(text_id), text_id.upper()))
            except ValueError:
                niveles.append(text_id.upper())
        for ubicacion in ubicaciones:
            for nivel in niveles:
                chuecopa = f"{ubicacion}{nivel}"
                locations.append(
                    {
                        "key": _position_key(zona, pasillo_cara, chuecopa),
                        "posicion": _position_label(zona, pasillo_cara, chuecopa),
                        "czonalma": zona,
                        "cpasillo": pasillo_cara,
                        "chuecopa": chuecopa,
                        "ticket_id": row["ticket_id"],
                        "codigo_visible": row["codigo_visible"],
                        "estado": row["estado"],
                        "estado_codigo": row["estado_codigo"],
                        "titulo": row["titulo"],
                        "fecha_creacion": row["fecha_creacion"],
                        "fecha_ultima_actualizacion": row["fecha_ultima_actualizacion"],
                    }
                )
    return locations


async def _append_system_comment(db: aiosqlite.Connection, ticket_id: int, username: str, comentario: str) -> None:
    await db.execute(
        "INSERT INTO ticket_comentario (ticket_id, fecha, usuario_id, comentario) VALUES (?, ?, ?, ?)",
        (ticket_id, _now(), username, comentario),
    )


async def _apply_rack_transition_payload(
    db: aiosqlite.Connection,
    ticket: dict[str, Any],
    req: CambioEstadoRequest,
    auth: dict[str, Any],
    destino_codigo: str,
) -> list[str]:
    if ticket.get("tipo_codigo") != "REPARACION_RACK":
        return []
    rack = await _fetch_one(db, "SELECT * FROM ticket_rack_detalle WHERE ticket_id=?", (ticket["id"],))
    if not rack:
        return []
    now = _now()
    notes: list[str] = []
    current = str(ticket.get("estado_codigo") or "").upper()
    destino = str(destino_codigo or "").upper()

    if current == "PENDIENTE_VALIDACION" and destino == "PENDIENTE_TRASPASOS":
        service = req.service_externo_id.strip()
        existing_service = str(rack.get("service_externo_id") or "").strip()
        if not service:
            service = existing_service
        if not service:
            raise HTTPException(status_code=400, detail="Para pasar de ADO a Mapa, primero se debe cargar el service externo.")
        if service != existing_service:
            await db.execute(
                """
                UPDATE ticket_rack_detalle
                SET service_externo_id=?, service_externo_usuario=?, service_externo_fecha=?
                WHERE ticket_id=?
                """,
                (service, auth["username"], now, ticket["id"]),
            )
        notes.append(f"Service externo: {service}")

    if current == "PENDIENTE_TRASPASOS" and destino == "TRASPASOS_ASIGNADOS":
        traspasos = req.traspasos_wms.strip() or req.comentario.strip()
        await db.execute(
            """
            UPDATE ticket_rack_detalle
            SET traspasos_wms=?, traspasos_usuario=?, traspasos_fecha=?
            WHERE ticket_id=?
            """,
            (traspasos, auth["username"], now, ticket["id"]),
        )
        notes.append(f"Observacion traspasos WMS: {traspasos}" if traspasos else "Traspasos WMS finalizados")

    if current == "TRASPASOS_ASIGNADOS" and destino == "POSICION_BLOQUEADA":
        if not req.vaciado_confirmado:
            raise HTTPException(status_code=400, detail="Debe confirmarse que las ubicaciones fueron vaciadas.")
        if not req.inutilizacion_wms_confirmada:
            raise HTTPException(status_code=400, detail="Mapa debe confirmar la inutilizacion 1 en WMS.")
        await db.execute(
            """
            UPDATE ticket_rack_detalle
            SET vaciado_confirmado=1, vaciado_usuario=?, vaciado_fecha=?,
                inutilizacion_wms_confirmada=1, inutilizacion_usuario=?, inutilizacion_fecha=?
            WHERE ticket_id=?
            """,
            (auth["username"], now, auth["username"], now, ticket["id"]),
        )
        notes.append("Ubicaciones vacias e inutilizacion 1 WMS confirmadas")

    if current == "EN_REPARACION" and destino == "REPARADO":
        await db.execute(
            """
            UPDATE ticket_rack_detalle
            SET mantenimiento_finalizado=1, mantenimiento_usuario=?, mantenimiento_fecha=?
            WHERE ticket_id=?
            """,
            (auth["username"], now, ticket["id"]),
        )
        notes.append("Mantenimiento finalizado")

    if current == "REPARADO" and destino == "PENDIENTE_HABILITACION":
        relevamiento = req.relevamiento_mapa.strip() or req.comentario.strip()
        if not relevamiento:
            raise HTTPException(status_code=400, detail="Mapa debe registrar el relevamiento fisico.")
        await db.execute(
            """
            UPDATE ticket_rack_detalle
            SET relevamiento_mapa=?, reetiquetado_requerido=?
            WHERE ticket_id=?
            """,
            (relevamiento, 1 if req.reetiquetado_requerido else 0, ticket["id"]),
        )
        notes.append(f"Relevamiento Mapa: {relevamiento}")
        if req.reetiquetado_requerido:
            notes.append("Reetiquetado requerido")

    if current == "PENDIENTE_HABILITACION" and destino == "CERRADO":
        if not req.rehabilitacion_wms_confirmada:
            raise HTTPException(status_code=400, detail="Mapa debe confirmar que quito la inutilizacion 1 en WMS.")
        await db.execute(
            """
            UPDATE ticket_rack_detalle
            SET rehabilitacion_wms_confirmada=1, rehabilitacion_usuario=?, rehabilitacion_fecha=?
            WHERE ticket_id=?
            """,
            (auth["username"], now, ticket["id"]),
        )
        notes.append("Rehabilitacion WMS confirmada")

    if notes:
        await _append_system_comment(db, int(ticket["id"]), auth["username"], "\n".join(notes))
    return notes


async def _ticket_row(db: aiosqlite.Connection, ticket_id: int) -> dict[str, Any]:
    await attach_auth_db(db)
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
        LEFT JOIN authdb.auth_users u ON u.username = t.usuario_creacion_id
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
            "ticket_forms_ingreso",
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
        await attach_auth_db(db)
        usuarios = await _fetch_all(
            db,
            """
            SELECT u.username, u.display_name, u.role, u.active,
                   cup.perfil casos_perfil, cup.sector casos_sector, cup.correo casos_correo,
                   cup.activo casos_activo, cup.updated_at casos_updated_at
            FROM authdb.auth_users u
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
    async with auth_db(attach_operational=False) as db:
        async with db.execute("SELECT 1 FROM auth_users WHERE username = ?", (username,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    async with aiosqlite.connect(DB_PATH) as db:
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


def _forms_import_dir() -> Path:
    configured = os.getenv("VIGIA_FORMS_RACKS_IN_DIR")
    if configured:
        return Path(configured)
    for candidate in [
        Path(r"C:\VigIA\ServiceRack\In"),
        Path(r"C:\VigIA\ServiceRacks\In"),
        Path(r"C:\VigIA\imports\ServiceRacks\In"),
    ]:
        if candidate.exists():
            return candidate
    return Path(r"C:\VigIA\ServiceRack\In")


def _forms_import_source() -> str:
    return os.getenv("VIGIA_FORMS_RACKS_SOURCE", "local").strip().lower()


def _norm_text(value: Any) -> str:
    text = str(value or "").strip()
    try:
        fixed = text.encode("latin1").decode("utf-8")
        if "Ã" in text and fixed:
            text = fixed
    except UnicodeError:
        pass
    return " ".join(text.upper().split())


def _match_key(value: Any) -> str:
    text = _norm_text(value).replace(chr(0xD1), "N")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]+", "", text)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return [part for part in re.split(r"[\s,;\-/]+", text) if part]
    return [value]


def _forms_attachment_lines(adjuntos: Any) -> list[str]:
    lines = []
    for item in _as_list(adjuntos):
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("nombre") or "Adjunto").strip()
            link = str(item.get("link") or item.get("url") or "").strip()
            lines.append(f"{name}: {link}" if link else name)
        elif str(item or "").strip():
            lines.append(str(item).strip())
    return lines


def _forms_attachment_items(adjuntos: Any) -> list[dict[str, Any]]:
    items = []
    for item in _as_list(adjuntos):
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("nombre") or "Adjunto").strip()
            if name:
                items.append(item)
    return items


async def _clear_resolved_forms_attachment_errors(
    db: aiosqlite.Connection,
    ticket_id: int,
    payload: dict[str, Any],
    adjuntos: list[dict[str, Any]] | None = None,
) -> bool:
    expected = {
        Path(str(item.get("name") or item.get("nombre") or "")).name.casefold()
        for item in _forms_attachment_items((payload.get("raw_response") or {}).get("adjuntos"))
    }
    expected.discard("")
    if not expected:
        return False
    if adjuntos is None:
        adjuntos = await _fetch_all(
            db,
            "SELECT nombre_original FROM ticket_adjunto WHERE ticket_id=? AND activo=1",
            (ticket_id,),
        )
    actual = {Path(str(row.get("nombre_original") or "")).name.casefold() for row in adjuntos}
    if not expected.issubset(actual):
        return False
    await db.execute(
        "UPDATE ticket_comentario SET activo=0 WHERE ticket_id=? AND activo=1 AND comentario LIKE ?",
        (ticket_id, f"{FORMS_ATTACHMENT_ERROR_PREFIX}%"),
    )
    return True


def _forms_attachment_roots(source_file: str = "") -> list[Path]:
    roots: list[Path] = []
    configured = os.getenv("VIGIA_FORMS_RACKS_ATTACHMENTS_DIRS", "")
    for raw in re.split(r"[;|]", configured):
        raw = raw.strip()
        if raw:
            roots.append(Path(raw))
    if source_file and not source_file.startswith("graph://"):
        path = Path(source_file)
        roots.extend([path.parent, path.parent.parent])
    roots.append(_forms_import_dir())
    unique = []
    seen = set()
    for root in roots:
        key = str(root).lower()
        if key not in seen and root.exists():
            seen.add(key)
            unique.append(root)
    return unique


def _find_forms_attachment_file(item: dict[str, Any], source_file: str = "") -> Path | None:
    name = Path(str(item.get("name") or item.get("nombre") or "")).name
    if not name:
        return None
    for root in _forms_attachment_roots(source_file):
        direct = root / name
        if direct.exists() and direct.is_file():
            return direct
        try:
            found = next(root.rglob(name), None)
        except OSError:
            found = None
        if found and found.is_file():
            return found
    return None


def _forms_attachment_roots_diagnostic(source_file: str = "") -> str:
    configured = os.getenv("VIGIA_FORMS_RACKS_ATTACHMENTS_DIRS", "")
    candidates = [Path(raw.strip()) for raw in re.split(r"[;|]", configured) if raw.strip()]
    if source_file and not source_file.startswith("graph://"):
        source_path = Path(source_file)
        candidates.extend([source_path.parent, source_path.parent.parent])
    candidates.append(_forms_import_dir())
    unique: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            status = "disponible" if path.exists() and path.is_dir() else "no existe o sin acceso"
        except OSError:
            status = "sin acceso"
        unique.append(f"{path} [{status}]")
    return "; ".join(unique) or "sin rutas locales configuradas"


async def _param_id_by_text(db: aiosqlite.Connection, table: str, value: Any) -> int | None:
    text = _norm_text(value)
    if not text:
        return None
    rows = await _fetch_all(
        db,
        f"SELECT id, codigo, nombre FROM {table} WHERE activo = 1 ORDER BY orden, id",
    )
    target = _match_key(text)
    for row in rows:
        candidates = {_match_key(row.get("codigo")), _match_key(row.get("nombre"))}
        if target in candidates:
            return int(row["id"])
        if len(target) >= 8 and any(difflib.SequenceMatcher(None, target, candidate).ratio() >= 0.9 for candidate in candidates):
            return int(row["id"])
    return None


async def _criticidad_id_by_forms(db: aiosqlite.Connection, tipo_id: int, value: Any) -> int | None:
    text = _norm_text(value)
    aliases = {
        "URGENTE": ["CRITICA", "ALTA"],
        "CRITICO": ["CRITICA", "ALTA"],
        "CRITICA": ["CRITICA"],
        "ALTA": ["ALTA"],
        "MEDIA": ["MEDIA"],
        "NORMAL": ["MEDIA", "BAJA"],
        "BAJA": ["BAJA"],
    }
    candidates = aliases.get(text, [text])
    placeholders = ",".join("?" for _ in candidates)
    row = await _fetch_one(
        db,
        f"""
        SELECT id
        FROM ticket_criticidad
        WHERE tipo_id = ? AND activo = 1
          AND (UPPER(codigo) IN ({placeholders}) OR UPPER(nombre) IN ({placeholders}))
        ORDER BY sla_horas, id
        LIMIT 1
        """,
        (tipo_id, *candidates, *candidates),
    )
    if row:
        return int(row["id"])
    row = await _fetch_one(
        db,
        "SELECT id FROM ticket_criticidad WHERE tipo_id = ? AND activo = 1 ORDER BY sla_horas DESC, id LIMIT 1",
        (tipo_id,),
    )
    return int(row["id"]) if row else None


async def _forms_payload_to_case(db: aiosqlite.Connection, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    raw = payload.get("raw_response") or {}
    errors: list[str] = []
    tipo_id = await _tipo_id(db)
    zona = _norm_text(raw.get("zona"))
    pasillo = _norm_text(raw.get("pasillo"))
    ubicaciones = _norm_text(raw.get("ubicaciones"))
    comentario = str(raw.get("comentario") or "").strip()
    if not zona:
        errors.append("Falta zona.")
    try:
        pasillo = _validate_pasillo(pasillo)
    except HTTPException as exc:
        errors.append(str(exc.detail))
    try:
        ubicaciones = _validate_ubicaciones(ubicaciones)
    except HTTPException as exc:
        errors.append(str(exc.detail))

    cara_id = await _param_id_by_text(db, "rack_cara", raw.get("cara"))
    sector_id = await _param_id_by_text(db, "rack_sector", raw.get("sector"))
    tipo_rack_id = await _param_id_by_text(db, "rack_tipo", raw.get("tipo_rack"))
    descripcion_id = await _param_id_by_text(db, "rack_descripcion", raw.get("descripcion_rotura"))
    criticidad_id = await _criticidad_id_by_forms(db, tipo_id, raw.get("criticidad"))
    for label, value in [
        ("cara", cara_id),
        ("sector", sector_id),
        ("tipo de rack", tipo_rack_id),
        ("descripcion de rotura", descripcion_id),
        ("criticidad", criticidad_id),
    ]:
        if not value:
            errors.append(f"No se pudo mapear {label}.")

    niveles: list[int] = []
    for nivel in _as_list(raw.get("niveles")):
        nivel_id = await _param_id_by_text(db, "rack_nivel", nivel)
        if nivel_id:
            niveles.append(nivel_id)
        else:
            errors.append(f"Nivel invalido: {nivel}.")
    niveles = list(dict.fromkeys(niveles))
    if not niveles:
        errors.append("Falta nivel.")

    adjuntos = _forms_attachment_lines(raw.get("adjuntos"))
    if adjuntos:
        comentario = "\n".join([line for line in [comentario, "Adjuntos Forms:", *adjuntos] if line])
    else:
        errors.append("Faltan adjuntos/fotos.")

    if errors:
        return None, errors
    return {
        "tipo_id": tipo_id,
        "zona_text": zona,
        "pasillo": pasillo,
        "cara_id": cara_id,
        "ubicaciones": ubicaciones,
        "niveles": niveles,
        "sector_rack_id": sector_id,
        "descripcion_rack_id": descripcion_id,
        "criticidad_id": criticidad_id,
        "tipo_rack_id": tipo_rack_id,
        "comentario_operativo": comentario,
    }, []


async def _create_rack_case_from_forms(
    db: aiosqlite.Connection,
    case_data: dict[str, Any],
    payload: dict[str, Any],
    source_file: str = "",
) -> tuple[int, str]:
    tipo_id = int(case_data["tipo_id"])
    criticidad = await _fetch_one(db, "SELECT * FROM ticket_criticidad WHERE id = ? AND tipo_id = ? AND activo = 1", (case_data["criticidad_id"], tipo_id))
    estado = await _fetch_one(db, "SELECT * FROM ticket_estado WHERE tipo_id = ? AND es_inicial = 1 AND activo = 1", (tipo_id,))
    if not criticidad or not estado:
        raise RuntimeError("Faltan parametros base para crear el caso.")
    fecha_actual = _now()
    sla_vencimiento = (datetime.now(CASES_TZ) + timedelta(hours=int(criticidad["sla_horas"]))).strftime("%Y-%m-%d %H:%M:%S")
    titulo = f"Reparacion de rack Z{case_data['zona_text']} P{case_data['pasillo']} U{case_data['ubicaciones']}"
    creador = os.getenv("VIGIA_FORMS_RACKS_USER", "forms_import").strip() or "forms_import"
    cur = await db.execute(
        """
        INSERT INTO ticket
            (tipo_id, estado_id, criticidad_id, titulo, descripcion, usuario_creacion_id,
             sector_creacion_id, perfil_asignado, sector_asignado, fecha_creacion,
             fecha_ultima_actualizacion, sla_vencimiento)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tipo_id,
            estado["id"],
            case_data["criticidad_id"],
            titulo,
            case_data["comentario_operativo"],
            creador,
            "FORMS",
            estado.get("perfil_asignado") or "ADO",
            estado.get("perfil_asignado") or "ADO",
            fecha_actual,
            fecha_actual,
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
            case_data["zona_text"],
            case_data["pasillo"],
            case_data["cara_id"],
            case_data["ubicaciones"],
            json.dumps(case_data["niveles"]),
            case_data["sector_rack_id"],
            case_data["descripcion_rack_id"],
            case_data["tipo_rack_id"],
            case_data["comentario_operativo"],
        ),
    )
    auth = {"username": creador}
    await _historial(db, ticket_id, auth, "FORMS", "CREACION_FORMS", f"Importado desde Forms response_id={payload.get('response_id')}")
    await _attach_forms_files(db, ticket_id, codigo_visible, auth, payload, source_file)
    await _evento(db, ticket_id, "ticket_creado_forms", {"response_id": payload.get("response_id")})
    return ticket_id, codigo_visible


async def _upsert_forms_payload(db: aiosqlite.Connection, payload: dict[str, Any], source_file: str) -> tuple[int, bool]:
    source = str(payload.get("source") or "microsoft_forms")
    form = str(payload.get("form") or "service_racks")
    response_id = str(payload.get("response_id") or "").strip()
    if not response_id:
        response_id = secrets.token_hex(8)
    existing = await _fetch_one(db, "SELECT id FROM ticket_forms_ingreso WHERE source=? AND form=? AND response_id=?", (source, form, response_id))
    if existing:
        return int(existing["id"]), False
    cur = await db.execute(
        """
        INSERT INTO ticket_forms_ingreso
            (source, form, response_id, source_file, received_at, payload_json, estado_importacion, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'PENDIENTE', ?)
        """,
        (source, form, response_id, source_file, str(payload.get("received_at") or ""), json.dumps(payload, ensure_ascii=False), _now()),
    )
    return int(cur.lastrowid), True


async def _process_forms_ingreso(db: aiosqlite.Connection, ingreso_id: int) -> dict[str, Any]:
    row = await _fetch_one(db, "SELECT * FROM ticket_forms_ingreso WHERE id=?", (ingreso_id,))
    if not row:
        raise RuntimeError("Ingreso Forms no encontrado.")
    if row.get("ticket_id"):
        payload = json.loads(row["payload_json"] or "{}")
        ticket = await _fetch_one(db, "SELECT codigo_visible, usuario_creacion_id FROM ticket WHERE id=?", (row["ticket_id"],))
        if ticket:
            auth = {"username": ticket.get("usuario_creacion_id") or os.getenv("VIGIA_FORMS_RACKS_USER", "forms_import")}
            failures = await _attach_forms_files(
                db,
                int(row["ticket_id"]),
                str(ticket.get("codigo_visible") or f"RCK-{int(row['ticket_id']):06d}"),
                auth,
                payload,
                str(row.get("source_file") or ""),
            )
            return {"id": ingreso_id, "estado": row["estado_importacion"], "ticket_id": row["ticket_id"], "adjuntos_error": failures, "skipped": True}
        return {"id": ingreso_id, "estado": row["estado_importacion"], "ticket_id": row["ticket_id"], "skipped": True}
    payload = json.loads(row["payload_json"] or "{}")
    case_data, errors = await _forms_payload_to_case(db, payload)
    if errors or not case_data:
        await db.execute(
            "UPDATE ticket_forms_ingreso SET estado_importacion='ERROR_VALIDACION', motivo_error=?, updated_at=? WHERE id=?",
            (" ".join(errors), _now(), ingreso_id),
        )
        return {"id": ingreso_id, "estado": "ERROR_VALIDACION", "errors": errors}
    try:
        ticket_id, codigo_visible = await _create_rack_case_from_forms(db, case_data, payload, str(row.get("source_file") or ""))
        await db.execute(
            "UPDATE ticket_forms_ingreso SET estado_importacion='IMPORTADO', motivo_error=NULL, ticket_id=?, updated_at=? WHERE id=?",
            (ticket_id, _now(), ingreso_id),
        )
        return {"id": ingreso_id, "estado": "IMPORTADO", "ticket_id": ticket_id, "codigo_visible": codigo_visible}
    except Exception as exc:
        await db.execute(
            "UPDATE ticket_forms_ingreso SET estado_importacion='ERROR_TECNICO', motivo_error=?, updated_at=? WHERE id=?",
            (str(exc), _now(), ingreso_id),
        )
        return {"id": ingreso_id, "estado": "ERROR_TECNICO", "error": str(exc)}


def _read_forms_json_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("El JSON raiz debe ser un objeto.")
    return payload


async def _reload_forms_ingreso_from_source(db: aiosqlite.Connection, ingreso_id: int) -> None:
    row = await _fetch_one(db, "SELECT * FROM ticket_forms_ingreso WHERE id=?", (ingreso_id,))
    if not row or row.get("ticket_id"):
        return
    source_file = str(row.get("source_file") or "")
    if not source_file or source_file.startswith("graph://"):
        return
    path = Path(source_file)
    if not path.exists():
        return
    payload = await asyncio.to_thread(_read_forms_json_file, path)
    await db.execute(
        """
        UPDATE ticket_forms_ingreso
        SET payload_json=?, received_at=?, estado_importacion='PENDIENTE', motivo_error=NULL, updated_at=?
        WHERE id=?
        """,
        (json.dumps(payload, ensure_ascii=False), str(payload.get("received_at") or ""), _now(), ingreso_id),
    )


def _graph_required_env(require_drive: bool = True) -> dict[str, str]:
    values = {
        "tenant_id": os.getenv("VIGIA_MS_TENANT_ID", "").strip(),
        "client_id": os.getenv("VIGIA_MS_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("VIGIA_MS_CLIENT_SECRET", "").strip(),
        "drive_id": os.getenv("VIGIA_FORMS_RACKS_GRAPH_DRIVE_ID", "").strip(),
        "folder_path": os.getenv("VIGIA_FORMS_RACKS_GRAPH_FOLDER_PATH", "VigIA/ServiceRack/In").strip().strip("/"),
    }
    optional = {"folder_path"}
    if not require_drive:
        optional.add("drive_id")
    missing = [key for key, value in values.items() if key not in optional and not value]
    if missing:
        raise RuntimeError(f"Falta configurar Microsoft Graph para Forms: {', '.join(missing)}")
    return values


def _graph_request(url: str, token: str | None = None, data: dict[str, str] | None = None) -> Any:
    body = urllib.parse.urlencode(data).encode("utf-8") if data else None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as res:
        raw = res.read()
        content_type = res.headers.get("Content-Type", "")
    if "application/json" in content_type:
        return json.loads(raw.decode("utf-8"))
    return raw.decode("utf-8-sig")


def _graph_request_bytes(url: str, token: str) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return res.read()


def _graph_token(values: dict[str, str]) -> str:
    url = f"https://login.microsoftonline.com/{values['tenant_id']}/oauth2/v2.0/token"
    data = {
        "client_id": values["client_id"],
        "client_secret": values["client_secret"],
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    payload = _graph_request(url, data=data)
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("Microsoft Graph no devolvio access_token.")
    return token


def _graph_list_forms_files(values: dict[str, str], token: str) -> list[dict[str, Any]]:
    folder = urllib.parse.quote(values["folder_path"], safe="/")
    url = f"https://graph.microsoft.com/v1.0/drives/{values['drive_id']}/root:/{folder}:/children?$select=id,name,file,lastModifiedDateTime,size"
    items: list[dict[str, Any]] = []
    while url:
        payload = _graph_request(url, token=token)
        items.extend(
            item for item in payload.get("value", [])
            if item.get("file") and str(item.get("name") or "").lower().endswith(".json")
        )
        url = payload.get("@odata.nextLink")
    return sorted(items, key=lambda item: str(item.get("lastModifiedDateTime") or ""))


def _graph_download_text(values: dict[str, str], token: str, item_id: str) -> str:
    url = f"https://graph.microsoft.com/v1.0/drives/{values['drive_id']}/items/{item_id}/content"
    return str(_graph_request(url, token=token))


def _graph_download_attachment_bytes(item: dict[str, Any]) -> bytes:
    values = _graph_required_env(require_drive=False)
    drive_id = str(item.get("driveId") or values["drive_id"]).strip()
    item_id = str(item.get("id") or "").strip()
    if not drive_id or not item_id:
        raise RuntimeError("Adjunto Forms sin driveId/id.")
    token = _graph_token(values)
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content"
    return _graph_request_bytes(url, token)


async def _resolve_forms_attachment_bytes(item: dict[str, Any], source_file: str = "") -> tuple[bytes, str, str]:
    name = Path(str(item.get("name") or item.get("nombre") or "adjunto.bin")).name
    mime = str(item.get("type") or "") or mimetypes.guess_type(name)[0] or "application/octet-stream"
    local_path = await asyncio.to_thread(_find_forms_attachment_file, item, source_file)
    if local_path:
        return await asyncio.to_thread(local_path.read_bytes), name, mime
    if item.get("id") and item.get("driveId") and os.getenv("VIGIA_MS_CLIENT_ID") and os.getenv("VIGIA_MS_CLIENT_SECRET"):
        return await asyncio.to_thread(_graph_download_attachment_bytes, item), name, mime
    roots = await asyncio.to_thread(_forms_attachment_roots_diagnostic, source_file)
    raise RuntimeError(
        f"No se encontro adjunto local ni Graph configurado: {name}. "
        f"Rutas revisadas: {roots}"
    )


async def _attach_forms_files(
    db: aiosqlite.Connection,
    ticket_id: int,
    codigo_visible: str,
    auth: dict[str, Any],
    payload: dict[str, Any],
    source_file: str = "",
) -> list[str]:
    failures = []
    raw = payload.get("raw_response") or {}
    for item in _forms_attachment_items(raw.get("adjuntos")):
        name = str(item.get("name") or item.get("nombre") or "Adjunto").strip()
        try:
            existing = await _fetch_one(
                db,
                "SELECT id FROM ticket_adjunto WHERE ticket_id=? AND nombre_original=? AND activo=1",
                (ticket_id, Path(name).name),
            )
            if existing:
                continue
            content, original, mime = await _resolve_forms_attachment_bytes(item, source_file)
            await _guardar_adjunto_bytes(db, ticket_id, codigo_visible, auth, "FORMS", original, mime, content)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    current_attachments = await _fetch_all(
        db,
        "SELECT nombre_original FROM ticket_adjunto WHERE ticket_id=? AND activo=1",
        (ticket_id,),
    )
    if not failures:
        await _clear_resolved_forms_attachment_errors(db, ticket_id, payload, current_attachments)
        return failures
    if failures:
        failure_comment = f"{FORMS_ATTACHMENT_ERROR_PREFIX}\n" + "\n".join(failures)
        await db.execute(
            "UPDATE ticket_comentario SET activo=0 WHERE ticket_id=? AND activo=1 AND comentario LIKE ?",
            (ticket_id, f"{FORMS_ATTACHMENT_ERROR_PREFIX}%"),
        )
        await db.execute(
            """
            INSERT INTO ticket_comentario (ticket_id, fecha, usuario_id, comentario, activo)
            VALUES (?, ?, ?, ?, 1)
            """,
            (ticket_id, _now(), auth["username"], failure_comment),
        )
    return failures


async def _import_forms_graph() -> dict[str, Any]:
    values = _graph_required_env()
    token = await asyncio.to_thread(_graph_token, values)
    files = await asyncio.to_thread(_graph_list_forms_files, values, token)
    results = []
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        db.row_factory = aiosqlite.Row
        for item in files:
            source_file = f"graph://{values['drive_id']}/{values['folder_path']}/{item.get('name')}"
            try:
                text = await asyncio.to_thread(_graph_download_text, values, token, str(item["id"]))
                payload = json.loads(text)
            except Exception as exc:
                payload = {
                    "source": "microsoft_forms",
                    "form": "service_racks",
                    "response_id": str(item.get("id") or item.get("name") or secrets.token_hex(8)),
                    "raw_response": {},
                }
                ingreso_id, inserted = await _upsert_forms_payload(db, payload, source_file)
                await db.execute(
                    "UPDATE ticket_forms_ingreso SET estado_importacion='ERROR_TECNICO', motivo_error=?, updated_at=? WHERE id=?",
                    (f"JSON OneDrive invalido: {exc}", _now(), ingreso_id),
                )
                results.append({"file": source_file, "inserted": inserted, "estado": "ERROR_TECNICO", "error": str(exc)})
                continue
            ingreso_id, inserted = await _upsert_forms_payload(db, payload, source_file)
            result = await _process_forms_ingreso(db, ingreso_id)
            result.update({"file": source_file, "inserted": inserted})
            results.append(result)
        await db.commit()
    return {"ok": True, "source": "graph", "folder": values["folder_path"], "count": len(results), "results": results}


async def _import_forms_files(raise_missing: bool = True) -> dict[str, Any]:
    if _forms_import_source() == "graph":
        return await _import_forms_graph()
    folder = _forms_import_dir()
    if not folder.exists():
        if raise_missing:
            raise HTTPException(status_code=400, detail=f"No existe carpeta de importacion Forms: {folder}")
        return {"ok": True, "folder": str(folder), "count": 0, "results": [], "missing": True}
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime)
    results = []
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        db.row_factory = aiosqlite.Row
        for path in files:
            try:
                payload = await asyncio.to_thread(_read_forms_json_file, path)
            except OSError as exc:
                results.append({"file": str(path), "inserted": False, "estado": "NO_DISPONIBLE", "error": str(exc)})
                continue
            except Exception as exc:
                payload = {
                    "source": "microsoft_forms",
                    "form": "service_racks",
                    "response_id": path.stem,
                    "raw_response": {},
                }
                ingreso_id, inserted = await _upsert_forms_payload(db, payload, str(path))
                await db.execute(
                    "UPDATE ticket_forms_ingreso SET estado_importacion='ERROR_TECNICO', motivo_error=?, updated_at=? WHERE id=?",
                    (f"JSON invalido: {exc}", _now(), ingreso_id),
                )
                results.append({"file": str(path), "inserted": inserted, "estado": "ERROR_TECNICO", "error": str(exc)})
                continue
            ingreso_id, inserted = await _upsert_forms_payload(db, payload, str(path))
            result = await _process_forms_ingreso(db, ingreso_id)
            result.update({"file": str(path), "inserted": inserted})
            results.append(result)
        await db.commit()
    return {"ok": True, "folder": str(folder), "count": len(results), "results": results}


async def _forms_import_loop() -> None:
    interval = max(10, int(os.getenv("VIGIA_FORMS_RACKS_POLL_SECONDS", "60") or "60"))
    while True:
        try:
            result = await _import_forms_files(raise_missing=False)
            inserted = [row for row in result.get("results", []) if row.get("inserted")]
            if inserted:
                logger.info("Importacion Forms Service Racks: %s archivos nuevos procesados.", len(inserted))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("No se pudo importar Forms Service Racks: %s", exc)
        await asyncio.sleep(interval)


def start_forms_import_monitor() -> None:
    global _FORMS_IMPORT_TASK
    enabled = os.getenv("VIGIA_FORMS_RACKS_MONITOR", "1").strip().lower() not in {"0", "false", "no"}
    if not enabled:
        logger.info("Monitor Forms Service Racks deshabilitado.")
        return
    if _FORMS_IMPORT_TASK and not _FORMS_IMPORT_TASK.done():
        return
    _FORMS_IMPORT_TASK = asyncio.create_task(_forms_import_loop())
    source = _forms_import_source()
    target = os.getenv("VIGIA_FORMS_RACKS_GRAPH_FOLDER_PATH", "VigIA/ServiceRack/In") if source == "graph" else str(_forms_import_dir())
    logger.info("Monitor Forms Service Racks iniciado. Origen: %s. Carpeta: %s", source, target)


async def stop_forms_import_monitor() -> None:
    global _FORMS_IMPORT_TASK
    if not _FORMS_IMPORT_TASK:
        return
    _FORMS_IMPORT_TASK.cancel()
    try:
        await _FORMS_IMPORT_TASK
    except asyncio.CancelledError:
        pass
    _FORMS_IMPORT_TASK = None


@router.post("/forms/import")
async def importar_forms(request: Request):
    await _require_auth(request)
    return await _import_forms_files()


@router.get("/forms/ingresos")
async def listar_forms_ingresos(request: Request, estado: str = "", limit: int = Query(200, ge=1, le=1000)):
    await _require_auth(request)
    where = []
    args: list[Any] = []
    if estado:
        where.append("estado_importacion = ?")
        args.append(estado.strip().upper())
    sql_where = f"WHERE {' AND '.join(where)}" if where else ""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _fetch_all(
            db,
            f"""
            SELECT f.*, t.codigo_visible
            FROM ticket_forms_ingreso f
            LEFT JOIN ticket t ON t.id=f.ticket_id
            {sql_where}
            ORDER BY f.created_at DESC, f.id DESC
            LIMIT ?
            """,
            (*args, limit),
        )
    return {"items": rows, "count": len(rows)}


@router.post("/forms/ingresos/{ingreso_id}/reintentar")
async def reintentar_forms_ingreso(ingreso_id: int, request: Request):
    await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        db.row_factory = aiosqlite.Row
        try:
            await _reload_forms_ingreso_from_source(db, ingreso_id)
        except Exception as exc:
            await db.execute(
                "UPDATE ticket_forms_ingreso SET estado_importacion='ERROR_TECNICO', motivo_error=?, updated_at=? WHERE id=?",
                (f"No se pudo releer archivo origen: {exc}", _now(), ingreso_id),
            )
            await db.commit()
            return {"id": ingreso_id, "estado": "ERROR_TECNICO", "error": str(exc)}
        result = await _process_forms_ingreso(db, ingreso_id)
        await db.commit()
    return result


@router.post("/forms/ingresos/{ingreso_id}/reclamar")
async def reclamar_forms_ingreso(ingreso_id: int, req: FormsReclamoRequest, request: Request):
    auth, _ = await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE ticket_forms_ingreso
            SET estado_importacion='RECLAMADO', reclamado_por=?, fecha_reclamo=?, comentario_reclamo=?, updated_at=?
            WHERE id=? AND ticket_id IS NULL
            """,
            (auth["username"], _now(), req.comentario.strip(), _now(), ingreso_id),
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
        zona_text = " ".join(req.zona_text.split()).upper()
        if not zona_text:
            raise HTTPException(status_code=400, detail="Zona obligatoria.")
        placeholders = ",".join("?" for _ in req.niveles)
        niveles_rows = await _fetch_all(db, f"SELECT id, nombre FROM rack_nivel WHERE id IN ({placeholders}) AND activo = 1", tuple(req.niveles))
        if len(niveles_rows) != len(set(req.niveles)):
            raise HTTPException(status_code=400, detail="Niveles invalidos.")
        fecha_actual = _now()
        sla_vencimiento = (datetime.now(CASES_TZ) + timedelta(hours=int(criticidad["sla_horas"]))).strftime("%Y-%m-%d %H:%M:%S")
        titulo = f"Reparacion de rack Z{zona_text} P{pasillo} U{ubicaciones}"
        cur = await db.execute(
            """
            INSERT INTO ticket
                (tipo_id, estado_id, criticidad_id, titulo, descripcion, usuario_creacion_id,
                 sector_creacion_id, perfil_asignado, sector_asignado, fecha_creacion,
                 fecha_ultima_actualizacion, sla_vencimiento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                fecha_actual,
                fecha_actual,
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
            where.append("t.sla_vencimiento < ? AND e.es_final = 0")
            args.append(_now())
        if pendientes_mi_perfil:
            where.append("t.perfil_asignado = ?")
            args.append(perfil)
        rows = await _fetch_all(
            db,
            f"""
            SELECT t.id, t.codigo_visible, tt.nombre tipo, t.fecha_creacion, e.codigo estado_codigo, e.nombre estado, e.es_final,
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


@router.get("/control-ubicaciones")
async def control_ubicaciones(request: Request, limit: int = Query(500, ge=50, le=5000)):
    await _require_auth(request)
    oracle_error = ""
    try:
        wms_rows = await asyncio.to_thread(_query_rack_oracle_inutilizadas_jdbc)
    except Exception as exc:
        wms_rows = []
        oracle_error = str(exc)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        service_rows = await _active_service_locations(db)

    wms_by_key: dict[str, dict[str, Any]] = {}
    for row in wms_rows:
        key = _position_key(row.get("czonalma", ""), row.get("cpasillo", ""), row.get("chuecopa", ""))
        if not key.strip("|"):
            continue
        item = dict(row)
        item["key"] = key
        item["posicion"] = _position_label(item["czonalma"], item["cpasillo"], item["chuecopa"])
        wms_by_key[key] = item

    services_by_key: dict[str, list[dict[str, Any]]] = {}
    for row in service_rows:
        services_by_key.setdefault(row["key"], []).append(row)

    wms_keys = set(wms_by_key)
    service_keys = set(services_by_key)
    matched_keys = sorted(wms_keys & service_keys)
    wms_without_service_keys = sorted(wms_keys - service_keys)
    services_without_wms_keys = sorted(service_keys - wms_keys)

    matched = []
    for key in matched_keys[:limit]:
        for service in services_by_key.get(key, []):
            matched.append({"wms": wms_by_key[key], "service": service})
            if len(matched) >= limit:
                break
        if len(matched) >= limit:
            break

    services_without_wms = []
    for key in services_without_wms_keys[:limit]:
        services_without_wms.extend(services_by_key.get(key, []))
        if len(services_without_wms) >= limit:
            services_without_wms = services_without_wms[:limit]
            break

    wms_without_service = [wms_by_key[key] for key in wms_without_service_keys[:limit]]
    return {
        "refreshed_at": _now(),
        "oracle_error": oracle_error,
        "summary": {
            "wms_inutilizadas": len(wms_by_key),
            "servicios_activos_ubicaciones": len(service_rows),
            "coincidencias": len(matched_keys),
            "wms_sin_service": len(wms_without_service_keys),
            "services_sin_wms": len(services_without_wms_keys),
        },
        "wms_without_service": wms_without_service,
        "services_without_wms": services_without_wms,
        "matched": matched,
        "limit": limit,
    }


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
              SUM(CASE WHEN e.es_final = 0 AND t.sla_vencimiento < ? THEN 1 ELSE 0 END) vencidos_sla
            FROM ticket t
            JOIN ticket_estado e ON e.id = t.estado_id
            JOIN ticket_criticidad c ON c.id = t.criticidad_id
            WHERE t.activo = 1
            """,
            (_now(),),
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
            "tickets_por_sector_asignado": "SELECT COALESCE(NULLIF(t.perfil_asignado,''),'Sin sector') label, COUNT(*) value FROM ticket t JOIN ticket_estado e ON e.id=t.estado_id WHERE t.activo=1 AND e.es_final=0 GROUP BY label ORDER BY value DESC, label",
            "tendencia_creacion": "SELECT date(fecha_creacion) label, COUNT(*) value FROM ticket WHERE activo=1 GROUP BY date(fecha_creacion) ORDER BY label DESC LIMIT 14",
            "tendencia_cierre": "SELECT date(fecha_cierre) label, COUNT(*) value FROM ticket WHERE activo=1 AND fecha_cierre IS NOT NULL GROUP BY date(fecha_cierre) ORDER BY label DESC LIMIT 14",
            "racks_por_zona": "SELECT COALESCE(NULLIF(d.zona_text,''), rz.nombre, 'Sin zona') label, COUNT(*) value FROM ticket_rack_detalle d LEFT JOIN rack_zona rz ON rz.id=d.zona_id GROUP BY label",
            "racks_por_tipo": "SELECT rt.nombre label, COUNT(*) value FROM ticket_rack_detalle d JOIN rack_tipo rt ON rt.id=d.tipo_rack_id GROUP BY rt.nombre",
            "racks_por_descripcion": "SELECT rd.nombre label, COUNT(*) value FROM ticket_rack_detalle d JOIN rack_descripcion rd ON rd.id=d.descripcion_rack_id GROUP BY rd.nombre",
        }.items():
            groups[key] = await _fetch_all(db, sql)
        service_rows = await _active_service_locations(db)
        service_keys = {row["key"] for row in service_rows}
        service_zone_counts = Counter(str(row.get("czonalma") or "Sin zona").strip().upper() or "Sin zona" for row in service_rows)
        groups["services_activos_por_zona"] = [
            {"label": label, "value": value}
            for label, value in sorted(service_zone_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
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
    oracle_error = ""
    wms_keys: set[str] = set()
    try:
        wms_rows = await asyncio.to_thread(_query_rack_oracle_inutilizadas_jdbc)
        wms_keys = {
            _position_key(row.get("czonalma", ""), row.get("cpasillo", ""), row.get("chuecopa", ""))
            for row in wms_rows
        }
        wms_keys = {key for key in wms_keys if key.strip("|")}
    except Exception as exc:
        oracle_error = str(exc)
    control_summary = {"servicios_activos_ubicaciones": len(service_rows)}
    if oracle_error:
        control_summary.update(
            {
                "wms_inutilizadas": None,
                "coincidencias": None,
                "wms_sin_service": None,
                "services_sin_wms": None,
            }
        )
    else:
        control_summary.update(
            {
                "wms_inutilizadas": len(wms_keys),
                "coincidencias": len(wms_keys & service_keys),
                "wms_sin_service": len(wms_keys - service_keys),
                "services_sin_wms": len(service_keys - wms_keys),
            }
        )
    return {
        "kpis": {**(base or {}), **(pendientes or {})},
        "groups": groups,
        "racks": racks or {},
        "ubicaciones_control": control_summary,
        "oracle_error": oracle_error,
        "user": auth["username"],
    }


@router.get("/ticket/{ticket_id}")
async def detalle(ticket_id: int, request: Request):
    _, perfil = await _require_auth(request)
    rack_stock: list[dict[str, Any]] = []
    rack_stock_error = ""
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
                try:
                    ubicaciones = [part for part in re.split(r"[\s,;\-/]+", str(rack.get("ubicaciones") or "").upper()) if part]
                    rack_stock = await asyncio.to_thread(
                        _query_rack_oracle_stock,
                        str(rack.get("zona") or ""),
                        f"{rack.get('pasillo') or ''}{rack.get('cara') or ''}",
                        ubicaciones,
                    )
                except Exception as exc:
                    rack_stock_error = str(exc)
        adjuntos = await _fetch_all(db, "SELECT id, fecha, usuario_id, nombre_original, nombre_archivo, tipo_mime FROM ticket_adjunto WHERE ticket_id=? AND activo=1 ORDER BY fecha", (ticket_id,))
        forms_row = await _fetch_one(db, "SELECT payload_json FROM ticket_forms_ingreso WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (ticket_id,))
        if forms_row:
            try:
                forms_payload = json.loads(forms_row.get("payload_json") or "{}")
                if await _clear_resolved_forms_attachment_errors(db, ticket_id, forms_payload, adjuntos):
                    await db.commit()
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        comentarios = await _fetch_all(db, "SELECT * FROM ticket_comentario WHERE ticket_id=? AND activo=1 ORDER BY fecha", (ticket_id,))
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
        SELECT tr.id, tr.estado_destino_id, tr.requiere_comentario, e.codigo estado_destino_codigo, e.nombre estado_destino,
               e.perfil_asignado perfil_destino
            FROM ticket_estado_transicion tr
            JOIN ticket_estado e ON e.id=tr.estado_destino_id
            WHERE tr.tipo_id=? AND tr.estado_origen_id=? AND tr.perfil_autorizado=? AND tr.activo=1
            ORDER BY e.orden
            """,
            (ticket["tipo_id"], ticket["estado_id"], perfil),
        )
    return {"ticket": ticket, "rack": rack, "rack_stock": rack_stock, "rack_stock_error": rack_stock_error, "comentarios": comentarios, "adjuntos": adjuntos, "historial": historial, "transiciones": transiciones, "perfil": perfil}


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
        fecha_actual = _now()
        await db.execute("INSERT INTO ticket_comentario (ticket_id, fecha, usuario_id, comentario) VALUES (?, ?, ?, ?)", (ticket_id, fecha_actual, auth["username"], comentario))
        await db.execute("UPDATE ticket SET fecha_ultima_actualizacion = ? WHERE id = ?", (fecha_actual, ticket_id))
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
            SELECT tr.*, e.codigo estado_destino_codigo, e.es_final, e.perfil_asignado perfil_destino
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
        transition_notes = await _apply_rack_transition_payload(
            db,
            ticket,
            req,
            auth,
            str(transicion.get("estado_destino_codigo") or ""),
        )
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
        hitos_msg = " | ".join(transition_notes)
        hist_comment = " | ".join(part for part in [comentario, hitos_msg, asignacion_msg] if part)
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
