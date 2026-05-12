import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from db.schema import DB_PATH

router = APIRouter(prefix="/api/auth", tags=["auth-local"])

SESSION_COOKIE = "vigia_session"
DEVICE_COOKIE = "vigia_device"
SESSION_DAYS = int(os.getenv("VIGIA_AUTH_SESSION_DAYS", "1"))
DEVICE_DAYS = int(os.getenv("VIGIA_AUTH_DEVICE_DAYS", "180"))
BOOTSTRAP_USER = os.getenv("VIGIA_AUTH_BOOTSTRAP_USER", "admin").strip().lower()
BOOTSTRAP_PASSWORD = os.getenv("VIGIA_AUTH_BOOTSTRAP_PASSWORD", "1234")


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


def _is_local_request(request: Request) -> bool:
    host = (request.client.host if request.client else "").lower()
    return host in {"127.0.0.1", "::1", "localhost"}


def _normalize_username(value: str) -> str:
    return value.strip().lower()


async def ensure_bootstrap_admin() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
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


async def current_auth(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    device_id = request.cookies.get(DEVICE_COOKIE, "")
    if not token or not device_id:
        return None
    token_hash = _token_hash(token)
    async with aiosqlite.connect(DB_PATH) as db:
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
        await db.execute(
            "UPDATE auth_sessions SET last_seen = ? WHERE session_token_hash = ?",
            (_now(), token_hash),
        )
        await db.execute(
            "UPDATE auth_devices SET last_seen = ?, ip_address = ?, user_agent = ? WHERE device_id = ? AND username = ?",
            (_now(), _client_ip(request), request.headers.get("user-agent", ""), device_id, data["username"]),
        )
        await db.commit()
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT username, password_hash, role, active FROM auth_users WHERE username = ?",
            (username,),
        ) as cur:
            user = await cur.fetchone()
        if not user or not user["active"] or not _verify_password(req.password, user["password_hash"]):
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
        auto_status = "approved" if user["role"] == "admin" and device is None and approved_admin_devices == 0 else "pending"
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

    response = JSONResponse({"ok": True, "username": username, "role": user["role"], "device_status": device_status})
    _set_cookie(response, SESSION_COOKIE, session_token, SESSION_DAYS)
    _set_cookie(response, DEVICE_COOKIE, device_id, DEVICE_DAYS)
    return response


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM auth_sessions WHERE session_token_hash = ?", (_token_hash(token),))
            await db.commit()
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
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


async def _require_admin(request: Request) -> dict[str, Any]:
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Requiere administrador.")
    return auth


@router.get("/admin/devices")
async def list_devices(request: Request):
    await _require_admin(request)
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT username, display_name, role, active, created_at, updated_at FROM auth_users ORDER BY username"
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    return {"users": rows}


@router.post("/admin/users")
async def create_user(req: UserCreateRequest, request: Request):
    await _require_admin(request)
    username = _normalize_username(req.username)
    role = req.role if req.role in {"user", "admin"} else "user"
    if not username or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Usuario requerido y contraseña mínima de 4 caracteres.")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
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


async def _set_user_active(req: UserActionRequest, request: Request, active: int) -> dict[str, bool]:
    await _require_admin(request)
    username = _normalize_username(req.username)
    if active == 0:
        async with aiosqlite.connect(DB_PATH) as db:
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
        async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
