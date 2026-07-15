import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import socket
from datetime import datetime, timedelta
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from db.auth import auth_db
from utils.usage_log import write_usage_log

router = APIRouter(prefix="/api/auth", tags=["auth-local"])

SESSION_COOKIE = "vigia_session"
DEVICE_COOKIE = "vigia_device"
SESSION_DAYS = int(os.getenv("VIGIA_AUTH_SESSION_DAYS", "1"))
DEVICE_DAYS = int(os.getenv("VIGIA_AUTH_DEVICE_DAYS", "180"))
BOOTSTRAP_USER = os.getenv("VIGIA_AUTH_BOOTSTRAP_USER", "admin").strip().lower()
BOOTSTRAP_PASSWORD = os.getenv("VIGIA_AUTH_BOOTSTRAP_PASSWORD", "1234")
AUTO_APPROVE_DEVICES = os.getenv("VIGIA_AUTH_AUTO_APPROVE_DEVICES", "").strip().lower() in {"1", "true", "yes", "si"}


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None
    role: str = "user"


class DeviceActionRequest(BaseModel):
    device_id: str


class UserActionRequest(BaseModel):
    username: str


class UserScopeRequest(BaseModel):
    username: str
    module: str = "novedades_cd"
    scope: str = "operativo"
    sectors: list[str] = Field(default_factory=list)


class UserAccessRequest(BaseModel):
    username: str
    module: str
    enabled: bool = True
    profile: str | None = None
    scope: str | None = None
    sector: str | None = None
    email: str | None = None
    shift: str | None = None
    sectors: list[str] = Field(default_factory=list)


class BulkUserItem(BaseModel):
    username: str
    display_name: str | None = None


class BulkUsersRequest(BaseModel):
    users: list[BulkUserItem] = Field(default_factory=list)
    role: str = "user"
    module: str = "none"
    profile: str = "OPERACION"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _expires(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 150_000)
    return f"pbkdf2_sha256${salt}${base64.b64encode(raw).decode('ascii')}"


def _generate_initial_password(length: int = 10) -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, expected = stored.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    return hmac.compare_digest(_hash_password(password, salt=salt), stored)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


def _request_origin(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    scheme = forwarded_proto or request.url.scheme or "http"
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}".rstrip("/")


def _server_origin(request: Request) -> str:
    origin = _request_origin(request)
    hostname = (request.url.hostname or "").lower()
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        return origin
    server_name = (os.getenv("COMPUTERNAME") or socket.gethostname() or hostname).strip()
    port = request.url.port
    port_part = f":{port}" if port else ""
    return f"{request.url.scheme or 'http'}://{server_name}{port_part}"


def _is_local_request(request: Request) -> bool:
    host = (request.client.host if request.client else "").lower()
    return host in {"127.0.0.1", "::1", "localhost"}


def _normalize_username(value: str) -> str:
    return value.strip().lower()


APP_MODULES = [
    {"id": "productividad", "label": "Productividad", "path": "/productividad.html"},
    {"id": "novedades_cd", "label": "Tablero RRHH", "path": "/novedades-cd"},
    {"id": "gestion_operativa", "label": "Gestion Operativa", "path": "/gestion-operativa.html"},
    {"id": "casos", "label": "Gestion de Casos", "path": "/casos.html"},
    {"id": "panol", "label": "Panol Insumos", "path": "/panol-insumos"},
    {"id": "historia_legajo", "label": "Historia de Legajo", "path": "/historia-legajo.html"},
    {"id": "opex", "label": "OpEX", "path": "/opex.html"},
    {"id": "simulador_operativo", "label": "Simulador Operativo", "path": "/simulador-operativo.html"},
    {"id": "analisis_premio_productividad", "label": "Analisis Premio Productividad", "path": "/analisis-premio-productividad.html"},
    {"id": "plantel_optimo", "label": "Plantel Optimo", "path": "/plantel-optimo.html"},
    {"id": "rendimiento_online", "label": "Rendimiento Online", "path": "/rendimiento-online.html"},
    {"id": "checklist_tareas", "label": "CheckList Tareas", "path": "/checklist-tareas"},
    {"id": "recepcion", "label": "Recepcion", "path": "/recepcion.html", "available": False},
    {"id": "mapa", "label": "Mapa", "path": "", "available": False},
    {"id": "control_procesos", "label": "Control de Procesos", "path": "", "available": False},
    {"id": "trafico", "label": "Trafico", "path": "", "available": False},
    {"id": "generales", "label": "Generales", "path": "", "available": False},
]
APP_MODULE_IDS = {module["id"] for module in APP_MODULES}
DEFAULT_ENABLED_MODULES: set[str] = set()

CASOS_FALLBACK_PROFILES = ["OPERACION", "ADO", "MAPA_ALMACEN", "PLANEAMIENTO", "MANTENIMIENTO", "ADMIN"]

AUTH_ACCESS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS auth_user_app_access (
    access_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    module TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    profile TEXT,
    scope TEXT,
    sector TEXT,
    email TEXT,
    metadata_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(username, module)
);
"""

AUTH_ACCESS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_auth_app_access_user_module "
    "ON auth_user_app_access(username, module, enabled)"
)


def _clean_text(value: str | None) -> str:
    return " ".join(str(value or "").split())


def _clean_sectors(values: list[str] | None) -> list[str]:
    sectors: list[str] = []
    for sector in values or []:
        value = _clean_text(sector)
        if value and value not in sectors:
            sectors.append(value)
    return sectors


async def ensure_auth_access_schema() -> None:
    async with auth_db() as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute(AUTH_ACCESS_SCHEMA_SQL)
        await db.execute(AUTH_ACCESS_INDEX_SQL)
        await db.commit()


async def ensure_bootstrap_admin() -> None:
    await ensure_auth_access_schema()
    async with auth_db() as db:
        async with db.execute("SELECT COUNT(*) FROM auth_users") as cur:
            count = (await cur.fetchone())[0]
        if count == 0 and BOOTSTRAP_USER and BOOTSTRAP_PASSWORD:
            await db.execute(
                """
                INSERT INTO auth_users (username, password_hash, display_name, role, active)
                VALUES (?, ?, ?, 'admin', 1)
                """,
                (BOOTSTRAP_USER, _hash_password(BOOTSTRAP_PASSWORD), "Administrador"),
            )
            await db.commit()


async def module_access_for_user(username: str, role: str = "user") -> dict[str, bool]:
    if role == "admin":
        return {module["id"]: True for module in APP_MODULES}
    access = {module["id"]: module["id"] in DEFAULT_ENABLED_MODULES for module in APP_MODULES}
    async with auth_db(attach_operational=True) as db:
        db.row_factory = aiosqlite.Row
        rows = await _fetch_rows(
            db,
            "SELECT module, enabled FROM auth_user_app_access WHERE username = ?",
            (username,),
        )
        for row in rows:
            if row["module"] in access:
                access[row["module"]] = bool(row["enabled"])
        async with db.execute(
            """
            SELECT scope FROM auth_user_module_scopes
            WHERE username = ? AND module = 'novedades_cd' AND active = 1
            """,
            (username,),
        ) as cur:
            scopes = [row[0] for row in await cur.fetchall()]
        if scopes:
            access["novedades_cd"] = any(scope != "sin_acceso" for scope in scopes)
        try:
            async with db.execute(
                """
                SELECT activo FROM ticket_usuario_perfil
                WHERE username = ? AND tipo_codigo = 'REPARACION_RACK'
                """,
                (username,),
            ) as cur:
                row = await cur.fetchone()
            if row is not None:
                access["casos"] = bool(row[0])
        except sqlite3.OperationalError:
            pass
    return access


async def user_has_module_access(auth: dict[str, Any], module: str) -> bool:
    if module not in APP_MODULE_IDS:
        return False
    access = await module_access_for_user(auth["username"], auth.get("role") or "user")
    return bool(access.get(module))


async def current_auth(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    device_id = request.cookies.get(DEVICE_COOKIE, "")
    if not token or not device_id:
        return None
    token_hash = _token_hash(token)
    async with auth_db() as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT s.username, s.device_id, s.expires_at, u.role, u.display_name, u.active,
                   d.status AS device_status
            FROM auth_sessions s
            JOIN auth_users u ON u.username = s.username
            JOIN auth_devices d ON d.device_id = s.device_id AND d.username = s.username
            WHERE s.session_token_hash = ?
            """,
            (token_hash,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        if not data.get("active"):
            return None
        if data.get("expires_at") <= _now():
            await db.execute("DELETE FROM auth_sessions WHERE session_token_hash = ?", (token_hash,))
            await db.commit()
            return None
        try:
            await db.execute(
                "UPDATE auth_sessions SET last_seen = ? WHERE session_token_hash = ?",
                (_now(), token_hash),
            )
            await db.execute(
                "UPDATE auth_devices SET last_seen = ?, ip_address = ?, user_agent = ? WHERE device_id = ? AND username = ?",
                (_now(), _client_ip(request), request.headers.get("user-agent", ""), device_id, data["username"]),
            )
            await db.commit()
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
    return data


def _set_cookie(response: Response, name: str, value: str, max_age_days: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age_days * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
    )

@router.post("/login")
async def login(req: LoginRequest, request: Request):
    username = _normalize_username(req.username)
    device_id = request.cookies.get(DEVICE_COOKIE) or secrets.token_urlsafe(32)
    async with auth_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT username, password_hash, display_name, role, active FROM auth_users WHERE username = ?",
            (username,),
        ) as cur:
            user = await cur.fetchone()
        if not user or not user["active"] or not _verify_password(req.password, user["password_hash"]):
            write_usage_log(request, username, "acceso", "login_failed")
            raise HTTPException(status_code=401, detail="Usuario o contraseña inválidos.")

        async with db.execute("SELECT status, username FROM auth_devices WHERE device_id = ?", (device_id,)) as cur:
            device = await cur.fetchone()
        if device is not None and device["username"] != username:
            device_id = secrets.token_urlsafe(32)
            device = None
        async with db.execute(
            """
            SELECT COUNT(*)
            FROM auth_devices d
            JOIN auth_users u ON u.username = d.username
            WHERE u.role = 'admin' AND d.status = 'approved'
            """
        ) as cur:
            approved_admin_devices = (await cur.fetchone())[0]
        auto_status = (
            "approved"
            if AUTO_APPROVE_DEVICES or (user["role"] == "admin" and device is None and approved_admin_devices == 0)
            else "pending"
        )
        if device is None:
            await db.execute(
                """
                INSERT INTO auth_devices (device_id, username, status, user_agent, ip_address,
                                          approved_at, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    username,
                    auto_status,
                    request.headers.get("user-agent", ""),
                    _client_ip(request),
                    _now() if auto_status == "approved" else None,
                    username if auto_status == "approved" else None,
                ),
            )
            device_status = auto_status
        else:
            device_status = device["status"]
            await db.execute(
                "UPDATE auth_devices SET last_seen = ?, ip_address = ?, user_agent = ? WHERE device_id = ? AND username = ?",
                (_now(), _client_ip(request), request.headers.get("user-agent", ""), device_id, username),
            )

        if user["role"] == "admin" and device_status != "approved" and _is_local_request(request):
            await db.execute(
                """
                UPDATE auth_devices
                SET status = 'approved', approved_at = ?, approved_by = ?
                WHERE device_id = ? AND username = ?
                """,
                (_now(), username, device_id, username),
            )
            device_status = "approved"

        session_token = secrets.token_urlsafe(32)
        await db.execute(
            """
            INSERT INTO auth_sessions (session_token_hash, username, device_id, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (_token_hash(session_token), username, device_id, _expires(SESSION_DAYS)),
        )
        await db.commit()

    response = JSONResponse(
        {
            "ok": True,
            "username": username,
            "display_name": user["display_name"],
            "role": user["role"],
            "device_status": device_status,
        }
    )
    _set_cookie(response, SESSION_COOKIE, session_token, SESSION_DAYS)
    _set_cookie(response, DEVICE_COOKIE, device_id, DEVICE_DAYS)
    write_usage_log(request, username, "acceso", "login_ok")
    return response


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE, "")
    auth = await current_auth(request) if token else None
    if token:
        async with auth_db() as db:
            await db.execute("DELETE FROM auth_sessions WHERE session_token_hash = ?", (_token_hash(token),))
            await db.commit()
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    write_usage_log(request, auth.get("username") if auth else None, "acceso", "logout")
    return response


@router.get("/me")
async def me(request: Request):
    auth = await current_auth(request)
    if not auth:
        raise HTTPException(status_code=401, detail="No autenticado.")
    return {
        "username": auth["username"],
        "role": auth["role"],
        "display_name": auth.get("display_name"),
        "device_status": auth.get("device_status"),
    }


@router.get("/apps")
async def my_apps(request: Request):
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    return {
        "modules": APP_MODULES,
        "access": await module_access_for_user(auth["username"], auth.get("role") or "user"),
    }


async def _require_admin(request: Request) -> dict[str, Any]:
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Requiere administrador.")
    return auth


async def _fetch_rows(db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    async with db.execute(sql, args) as cur:
        return [dict(row) for row in await cur.fetchall()]


@router.get("/admin/devices")
async def list_devices(request: Request):
    await _require_admin(request)
    async with auth_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT device_id, username, status, ip_address, user_agent, first_seen, last_seen,
                   approved_at, approved_by, rejected_at, rejected_by, revoked_at, revoked_by
            FROM auth_devices
            ORDER BY
              CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
              last_seen DESC
            """
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    for row in rows:
        row["device_short"] = row["device_id"][:10]
    return {"devices": rows}


@router.get("/admin/users")
async def list_users(request: Request):
    await _require_admin(request)
    async with auth_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT u.username, u.display_name, u.role, u.active, u.created_at, u.updated_at,
                   COALESCE(MAX(CASE WHEN s.module = 'novedades_cd' AND s.active = 1 THEN s.scope END), 'operativo') rrhh_scope,
                   GROUP_CONCAT(CASE WHEN s.module = 'novedades_cd' AND s.active = 1 AND s.sector IS NOT NULL THEN s.sector END, '|') rrhh_sectors
            FROM auth_users u
            LEFT JOIN auth_user_module_scopes s ON s.username = u.username
            GROUP BY u.username, u.display_name, u.role, u.active, u.created_at, u.updated_at
            ORDER BY u.username
            """
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    for row in rows:
        row["rrhh_sectors"] = [item for item in (row.get("rrhh_sectors") or "").split("|") if item]
    return {"users": rows}


@router.get("/admin/rrhh-sectors")
async def list_rrhh_sectors(request: Request):
    await _require_admin(request)
    async with auth_db(attach_operational=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT DISTINCT desc_sector_generico value
            FROM rrhh_legajero
            WHERE TRIM(COALESCE(desc_sector_generico, '')) <> ''
            ORDER BY value
            """
        ) as cur:
            rows = [row["value"] for row in await cur.fetchall()]
    return {"sectors": rows}


async def _case_profiles(db: aiosqlite.Connection) -> list[str]:
    try:
        rows = []
        async with db.execute(
            """
            SELECT DISTINCT perfil
            FROM ticket_permiso_perfil
            WHERE activo = 1
            ORDER BY perfil
            """
        ) as cur:
            rows = [row[0] for row in await cur.fetchall() if row[0]]
        return sorted({*CASOS_FALLBACK_PROFILES, *rows})
    except sqlite3.OperationalError:
        return CASOS_FALLBACK_PROFILES


async def _upsert_app_access(
    db: aiosqlite.Connection,
    *,
    username: str,
    module: str,
    enabled: bool,
    profile: str = "",
    scope: str = "",
    sector: str = "",
    email: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO auth_user_app_access
            (username, module, enabled, profile, scope, sector, email, metadata_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username, module) DO UPDATE SET
            enabled=excluded.enabled,
            profile=excluded.profile,
            scope=excluded.scope,
            sector=excluded.sector,
            email=excluded.email,
            metadata_json=excluded.metadata_json,
            updated_at=excluded.updated_at
        """,
        (
            username,
            module,
            1 if enabled else 0,
            profile or None,
            scope or None,
            sector or None,
            email or None,
            json.dumps(metadata or {}, ensure_ascii=True),
            _now(),
        ),
    )


async def _set_rrhh_scope_db(db: aiosqlite.Connection, username: str, scope: str, sectors: list[str]) -> None:
    await db.execute(
        "UPDATE auth_user_module_scopes SET active = 0, updated_at = ? WHERE username = ? AND module = 'novedades_cd'",
        (_now(), username),
    )
    if scope in {"sin_acceso", "operativo", "global"}:
        await db.execute(
            """
            INSERT INTO auth_user_module_scopes (username, module, scope, sector, active)
            VALUES (?, 'novedades_cd', ?, NULL, 1)
            """,
            (username, scope),
        )
        return
    for sector in sectors:
        await db.execute(
            """
            INSERT INTO auth_user_module_scopes (username, module, scope, sector, active)
            VALUES (?, 'novedades_cd', 'sector_completo', ?, 1)
            """,
            (username, sector),
        )


async def _set_cases_access_db(
    db: aiosqlite.Connection,
    *,
    username: str,
    enabled: bool,
    profile: str,
    sector: str,
    email: str,
) -> None:
    await db.execute(
        """
        INSERT INTO ticket_usuario_perfil (username, tipo_codigo, perfil, sector, correo, activo, updated_at)
        VALUES (?, 'REPARACION_RACK', ?, ?, ?, ?, ?)
        ON CONFLICT(username, tipo_codigo) DO UPDATE SET
            perfil=excluded.perfil,
            sector=excluded.sector,
            correo=excluded.correo,
            activo=excluded.activo,
            updated_at=excluded.updated_at
        """,
        (username, profile, sector or None, email or None, 1 if enabled else 0, _now()),
    )


@router.get("/admin/access-context")
async def access_context(request: Request):
    await _require_admin(request)
    await ensure_auth_access_schema()
    async with auth_db(attach_operational=True) as db:
        db.row_factory = aiosqlite.Row
        users = await _fetch_rows(
            db,
            """
            SELECT username, display_name, role, active
            FROM auth_users
            ORDER BY username
            """,
        )
        rrhh_sectors = [
            row["value"]
            for row in await _fetch_rows(
                db,
                """
                SELECT DISTINCT desc_sector_generico value
                FROM rrhh_legajero
                WHERE TRIM(COALESCE(desc_sector_generico, '')) <> ''
                ORDER BY value
                """,
            )
        ]
        casos_profiles = await _case_profiles(db)
        access_rows = await _fetch_rows(db, "SELECT * FROM auth_user_app_access")
        rrhh_rows = await _fetch_rows(
            db,
            """
            SELECT username, scope, sector
            FROM auth_user_module_scopes
            WHERE module = 'novedades_cd' AND active = 1
            """,
        )
        try:
            casos_rows = await _fetch_rows(
                db,
                """
                SELECT username, perfil, sector, correo, activo
                FROM ticket_usuario_perfil
                WHERE tipo_codigo = 'REPARACION_RACK'
                """,
            )
        except sqlite3.OperationalError:
            casos_rows = []

    accesses: dict[str, dict[str, Any]] = {}
    for user in users:
        defaults = await module_access_for_user(user["username"], user["role"])
        accesses[user["username"]] = {
            module["id"]: {"module": module["id"], "enabled": defaults[module["id"]]}
            for module in APP_MODULES
        }
        accesses[user["username"]]["novedades_cd"].update({"scope": "sin_acceso", "sectors": []})
        accesses[user["username"]]["casos"].update({"profile": "", "sector": "", "email": ""})
        accesses[user["username"]]["panol"].update({"profile": "", "scope": "", "sector": "", "email": ""})
        accesses[user["username"]]["checklist_tareas"].update({"profile": "", "scope": "sector", "sector": "", "shift": ""})

    for row in access_rows:
        username = row["username"]
        module = row["module"]
        if username not in accesses or module not in accesses[username]:
            continue
        metadata = {}
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        accesses[username][module].update(
            {
                "enabled": bool(row["enabled"]),
                "profile": row["profile"] or "",
                "scope": row["scope"] or "",
                "sector": row["sector"] or "",
                "email": row["email"] or "",
                "sectors": metadata.get("sectors") or [],
                "shift": metadata.get("shift") or "",
            }
        )

    rrhh_by_user: dict[str, list[dict[str, Any]]] = {}
    for row in rrhh_rows:
        rrhh_by_user.setdefault(row["username"], []).append(row)
    for username, rows in rrhh_by_user.items():
        if username not in accesses:
            continue
        if any(row["scope"] == "sin_acceso" for row in rows):
            scope = "sin_acceso"
        elif any(row["scope"] == "global" for row in rows):
            scope = "global"
        elif any(row["scope"] == "sector_completo" for row in rows):
            scope = "sector_completo"
        else:
            scope = "operativo"
        sectors = [row["sector"] for row in rows if row["sector"]]
        accesses[username]["novedades_cd"].update(
            {"enabled": scope != "sin_acceso", "scope": scope, "sectors": sectors}
        )

    for row in casos_rows:
        username = row["username"]
        if username not in accesses:
            continue
        accesses[username]["casos"].update(
            {
                "enabled": bool(row["activo"]),
                "profile": row["perfil"] or "",
                "sector": row["sector"] or "",
                "email": row["correo"] or "",
            }
        )

    return {
        "users": users,
        "modules": APP_MODULES,
        "accesses": accesses,
        "rrhh_sectors": rrhh_sectors,
        "casos_profiles": casos_profiles,
        "panol_profiles": ["SOLICITANTE", "OPERACION", "ADMIN"],
    }


@router.post("/admin/users/access")
async def set_user_access(req: UserAccessRequest, request: Request):
    await _require_admin(request)
    await ensure_auth_access_schema()
    username = _normalize_username(req.username)
    module = (req.module or "").strip().lower()
    if module not in APP_MODULE_IDS:
        raise HTTPException(status_code=400, detail="Modulo no soportado.")
    async with auth_db(attach_operational=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT 1 FROM auth_users WHERE username = ?", (username,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Usuario no encontrado.")

        if module == "novedades_cd":
            scope = (req.scope or ("operativo" if req.enabled else "sin_acceso")).strip().lower()
            if not req.enabled:
                scope = "sin_acceso"
            if scope not in {"sin_acceso", "operativo", "sector_completo", "global"}:
                raise HTTPException(status_code=400, detail="Alcance invalido.")
            sectors = _clean_sectors(req.sectors)
            if scope == "sector_completo" and not sectors:
                raise HTTPException(status_code=400, detail="El alcance por sector requiere al menos un sector.")
            await _set_rrhh_scope_db(db, username, scope, sectors)
            await _upsert_app_access(
                db,
                username=username,
                module=module,
                enabled=scope != "sin_acceso",
                scope=scope,
                metadata={"sectors": sectors},
            )
        elif module == "casos":
            profile = (req.profile or "OPERACION").strip().upper()
            profiles = await _case_profiles(db)
            if profile not in profiles:
                raise HTTPException(status_code=400, detail="Perfil de casos invalido.")
            sector = _clean_text(req.sector)
            email = (req.email or "").strip()
            await _set_cases_access_db(
                db,
                username=username,
                enabled=req.enabled,
                profile=profile,
                sector=sector,
                email=email,
            )
            await _upsert_app_access(
                db,
                username=username,
                module=module,
                enabled=req.enabled,
                profile=profile,
                scope="perfil",
                sector=sector,
                email=email,
            )
        elif module == "checklist_tareas":
            sector = _clean_text(req.sector) or "Mapa de Almacén"
            profile = (req.profile or "OPERADOR").strip().upper()
            if profile not in {"OPERADOR", "ADMIN_SECTOR"}:
                raise HTTPException(status_code=400, detail="Perfil de CheckList Tareas invalido.")
            shift = _clean_text(req.shift)
            if shift not in {"", "Mañana", "Tarde", "Noche"}:
                raise HTTPException(status_code=400, detail="Turno de CheckList Tareas invalido.")
            await _upsert_app_access(
                db,
                username=username,
                module=module,
                enabled=req.enabled,
                profile=profile,
                scope="sector",
                sector=sector,
                metadata={
                    "sectors": _clean_sectors(req.sectors) or ["MAPA_ALMACEN"],
                    "shift": shift or None,
                },
            )
        else:
            profile = (req.profile or "").strip().upper()
            scope = _clean_text(req.scope)
            sector = _clean_text(req.sector)
            email = (req.email or "").strip()
            await _upsert_app_access(
                db,
                username=username,
                module=module,
                enabled=req.enabled,
                profile=profile,
                scope=scope,
                sector=sector,
                email=email,
            )
        await db.commit()
    return {"ok": True}


@router.post("/admin/db/ensure-access-schema")
async def admin_ensure_access_schema(request: Request):
    await _require_admin(request)
    await ensure_auth_access_schema()
    return {"ok": True, "table": "auth_user_app_access"}


@router.post("/admin/users/scope")
async def set_user_scope(req: UserScopeRequest, request: Request):
    await _require_admin(request)
    username = _normalize_username(req.username)
    module = req.module.strip().lower() or "novedades_cd"
    scope = req.scope.strip().lower()
    if module != "novedades_cd":
        raise HTTPException(status_code=400, detail="Modulo no soportado.")
    if scope not in {"sin_acceso", "operativo", "sector_completo", "global"}:
        raise HTTPException(status_code=400, detail="Alcance invalido.")
    sectors = _clean_sectors(req.sectors)
    if scope == "sector_completo" and not sectors:
        raise HTTPException(status_code=400, detail="El alcance por sector requiere al menos un sector.")
    async with auth_db() as db:
        async with db.execute("SELECT 1 FROM auth_users WHERE username = ?", (username,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        await _set_rrhh_scope_db(db, username, scope, sectors)
        await _upsert_app_access(
            db,
            username=username,
            module=module,
            enabled=scope != "sin_acceso",
            scope=scope,
            metadata={"sectors": sectors},
        )
        await db.commit()
    return {"ok": True}


@router.get("/admin/mail-context")
async def mail_context(request: Request):
    await _require_admin(request)
    selector_origin = os.getenv("VIGIA_PUBLIC_ORIGIN", "").strip().rstrip("/") or _server_origin(request)
    return {
        "origin": selector_origin,
        "selector_url": f"{selector_origin}/selector.html",
        "request_origin": _request_origin(request),
        "server_name": (os.getenv("COMPUTERNAME") or socket.gethostname() or "").strip(),
    }


@router.post("/admin/users")
async def create_user(req: UserCreateRequest, request: Request):
    await _require_admin(request)
    username = _normalize_username(req.username)
    role = req.role if req.role in {"user", "admin", "rrhh"} else "user"
    if not username or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Usuario requerido y contraseña mínima de 4 caracteres.")
    try:
        async with auth_db() as db:
            await db.execute(
                """
                INSERT INTO auth_users (username, password_hash, display_name, role, active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (username, _hash_password(req.password), req.display_name or username, role),
            )
            await db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="El usuario ya existe.")
    return {"ok": True}


@router.post("/admin/users/bulk")
async def create_users_bulk(req: BulkUsersRequest, request: Request):
    await _require_admin(request)
    await ensure_auth_access_schema()
    role = req.role if req.role in {"user", "admin", "rrhh"} else "user"
    module = (req.module or "none").strip().lower()
    if module in {"", "sin_modulo", "sin-modulo"}:
        module = "none"
    if module not in {"none", "panol"}:
        raise HTTPException(status_code=400, detail="Modulo inicial no soportado para alta masiva.")
    profile = (req.profile or "OPERACION").strip().upper()
    if module == "panol" and profile not in {"SOLICITANTE", "OPERACION", "ADMIN"}:
        raise HTTPException(status_code=400, detail="Perfil de Panol invalido.")

    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in req.users:
        username = _normalize_username(item.username)
        display_name = _clean_text(item.display_name) or username
        if not username:
            continue
        if username in seen:
            continue
        seen.add(username)
        cleaned.append({"username": username, "display_name": display_name})
    if not cleaned:
        raise HTTPException(status_code=400, detail="No hay usuarios validos para crear.")
    if len(cleaned) > 200:
        raise HTTPException(status_code=400, detail="El alta masiva permite hasta 200 usuarios por vez.")

    results: list[dict[str, Any]] = []
    async with auth_db() as db:
        db.row_factory = aiosqlite.Row
        for item in cleaned:
            username = item["username"]
            display_name = item["display_name"]
            async with db.execute("SELECT username, active FROM auth_users WHERE username = ?", (username,)) as cur:
                existing = await cur.fetchone()
            if existing:
                await db.execute(
                    "UPDATE auth_users SET active = 1, updated_at = ? WHERE username = ?",
                    (_now(), username),
                )
                if module == "panol":
                    await _upsert_app_access(
                        db,
                        username=username,
                        module=module,
                        enabled=True,
                        profile=profile,
                        scope="perfil",
                    )
                    message = "Ya existia. Acceso a Panol actualizado."
                else:
                    message = "Ya existia. Sin cambios de modulos."
                results.append(
                    {
                        "username": username,
                        "display_name": display_name,
                        "status": "exists",
                        "message": message,
                    }
                )
                continue

            password = _generate_initial_password()
            await db.execute(
                """
                INSERT INTO auth_users (username, password_hash, display_name, role, active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (username, _hash_password(password), display_name, role),
            )
            if module == "panol":
                await _upsert_app_access(
                    db,
                    username=username,
                    module=module,
                    enabled=True,
                    profile=profile,
                    scope="perfil",
                )
            results.append(
                {
                    "username": username,
                    "display_name": display_name,
                    "status": "created",
                    "message": "Usuario creado.",
                    "password": password,
                }
            )
        await db.commit()

    return {"ok": True, "module": module, "profile": profile if module == "panol" else "", "results": results}


async def _set_user_active(req: UserActionRequest, request: Request, active: int) -> dict[str, bool]:
    await _require_admin(request)
    username = _normalize_username(req.username)
    if active == 0:
        async with auth_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT role, active FROM auth_users WHERE username = ?", (username,)) as cur:
                target = await cur.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="Usuario no encontrado.")
            if target["role"] == "admin" and target["active"]:
                async with db.execute(
                    "SELECT COUNT(*) FROM auth_users WHERE role = 'admin' AND active = 1 AND username <> ?",
                    (username,),
                ) as cur:
                    remaining_admins = (await cur.fetchone())[0]
                if remaining_admins == 0:
                    raise HTTPException(status_code=400, detail="No se puede desactivar el ultimo admin activo.")
            await db.execute(
                "UPDATE auth_users SET active = 0, updated_at = ? WHERE username = ?",
                (_now(), username),
            )
            await db.execute("DELETE FROM auth_sessions WHERE username = ?", (username,))
            await db.commit()
    else:
        async with auth_db() as db:
            await db.execute(
                "UPDATE auth_users SET active = 1, updated_at = ? WHERE username = ?",
                (_now(), username),
            )
            await db.commit()
    return {"ok": True}


@router.post("/admin/users/deactivate")
async def deactivate_user(req: UserActionRequest, request: Request):
    return await _set_user_active(req, request, 0)


@router.post("/admin/users/activate")
async def activate_user(req: UserActionRequest, request: Request):
    return await _set_user_active(req, request, 1)


async def _set_device_status(req: DeviceActionRequest, request: Request, status: str) -> dict[str, bool]:
    admin = await _require_admin(request)
    now = _now()
    fields = {
        "approved": ("approved_at", "approved_by"),
        "rejected": ("rejected_at", "rejected_by"),
        "revoked": ("revoked_at", "revoked_by"),
    }[status]
    async with auth_db() as db:
        await db.execute(
            f"UPDATE auth_devices SET status = ?, {fields[0]} = ?, {fields[1]} = ? WHERE device_id = ?",
            (status, now, admin["username"], req.device_id),
        )
        if status in {"rejected", "revoked"}:
            await db.execute("DELETE FROM auth_sessions WHERE device_id = ?", (req.device_id,))
        await db.commit()
    return {"ok": True}


@router.post("/admin/devices/approve")
async def approve_device(req: DeviceActionRequest, request: Request):
    return await _set_device_status(req, request, "approved")


@router.post("/admin/devices/reject")
async def reject_device(req: DeviceActionRequest, request: Request):
    return await _set_device_status(req, request, "rejected")


@router.post("/admin/devices/revoke")
async def revoke_device(req: DeviceActionRequest, request: Request):
    return await _set_device_status(req, request, "revoked")


@router.get("/pending", include_in_schema=False)
async def pending_page():
    return HTMLResponse(
        """
        <!doctype html><html lang="es"><head><meta charset="utf-8"><title>Dispositivo pendiente</title>
        <style>body{font-family:system-ui;margin:0;background:#f2f4f1;color:#0e1620;display:grid;place-items:center;min-height:100vh}
        main{background:white;border:1px solid #d4dbd8;padding:28px;max-width:520px}h1{margin-top:0}</style></head>
        <body><main><h1>Dispositivo pendiente de aprobación</h1>
        <p>Tu usuario fue validado, pero este navegador todavía no está aprobado para usar Tiempos muertos y TNC.</p>
        <p>Pedile a un administrador que apruebe la solicitud en <strong>/admin/dispositivos</strong>.</p>
        <button onclick="fetch('/api/auth/logout',{method:'POST'}).then(()=>location.href='/login')">Salir</button>
        </main></body></html>
        """
    )
