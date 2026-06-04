r"""
Restaura usuarios y accesos de VigIA directamente sobre vigia.db.

Uso:
    python scripts/restore_auth_users.py --csv usuarios_produccion.csv --db C:\VigIA\vigia.db

CSV esperado:
username,password,display_name,role,panol_profile,novedades_cd,casos,panol
operador1,clave,Operador Uno,user,OPERACION,1,0,1
supervisor1,clave,Supervisor Uno,user,ADMIN,1,1,1
admin,clave,Administrador,admin,ADMIN,1,1,1
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import secrets
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS auth_user_module_scopes (
    scope_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    module TEXT NOT NULL DEFAULT 'novedades_cd',
    scope TEXT NOT NULL DEFAULT 'operativo',
    sector TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
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


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def truthy(value: str | None, default: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "si", "s", "x"}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 150_000)
    return f"pbkdf2_sha256${salt}${base64.b64encode(raw).decode('ascii')}"


def clean_role(value: str) -> str:
    role = str(value or "user").strip().lower()
    return role if role in {"user", "admin", "rrhh"} else "user"


def clean_panol_profile(value: str) -> str:
    profile = str(value or "OPERACION").strip().upper()
    return profile if profile in {"OPERACION", "ADMIN"} else "OPERACION"


def backup_database(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_name(f"{db_path.stem}.before_auth_restore_{stamp}{db_path.suffix}")
    shutil.copy2(db_path, backup)
    return backup


def upsert_access(
    conn: sqlite3.Connection,
    username: str,
    module: str,
    enabled: bool,
    profile: str = "",
    scope: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO auth_user_app_access
            (username, module, enabled, profile, scope, metadata_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username, module) DO UPDATE SET
            enabled=excluded.enabled,
            profile=excluded.profile,
            scope=excluded.scope,
            metadata_json=excluded.metadata_json,
            updated_at=excluded.updated_at
        """,
        (username, module, 1 if enabled else 0, profile or None, scope or None, json.dumps({}), now()),
    )


def restore_user(conn: sqlite3.Connection, row: dict[str, str]) -> str:
    username = str(row.get("username") or "").strip().lower()
    password = str(row.get("password") or "")
    if not username or not password:
        raise ValueError("Cada fila requiere username y password.")

    role = clean_role(row.get("role") or "user")
    display_name = str(row.get("display_name") or username).strip()
    panol_profile = clean_panol_profile(row.get("panol_profile") or ("ADMIN" if role == "admin" else "OPERACION"))
    novedades = truthy(row.get("novedades_cd"), default=True)
    casos = truthy(row.get("casos"), default=False)
    panol = truthy(row.get("panol"), default=True)

    conn.execute(
        """
        INSERT INTO auth_users (username, password_hash, display_name, role, active, updated_at)
        VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT(username) DO UPDATE SET
            password_hash=excluded.password_hash,
            display_name=excluded.display_name,
            role=excluded.role,
            active=1,
            updated_at=excluded.updated_at
        """,
        (username, hash_password(password), display_name, role, now()),
    )

    conn.execute(
        "UPDATE auth_user_module_scopes SET active = 0, updated_at = ? WHERE username = ? AND module = 'novedades_cd'",
        (now(), username),
    )
    conn.execute(
        """
        INSERT INTO auth_user_module_scopes (username, module, scope, sector, active)
        VALUES (?, 'novedades_cd', ?, NULL, 1)
        """,
        (username, "global" if novedades else "sin_acceso"),
    )
    upsert_access(conn, username, "novedades_cd", novedades, scope="global" if novedades else "sin_acceso")
    upsert_access(conn, username, "casos", casos, profile="ADMIN" if role == "admin" else "OPERACION", scope="perfil")
    upsert_access(conn, username, "panol", panol, profile=panol_profile, scope="perfil")

    try:
        conn.execute(
            """
            INSERT INTO ticket_usuario_perfil (username, tipo_codigo, perfil, activo, updated_at)
            VALUES (?, 'REPARACION_RACK', ?, ?, ?)
            ON CONFLICT(username, tipo_codigo) DO UPDATE SET
                perfil=excluded.perfil,
                activo=excluded.activo,
                updated_at=excluded.updated_at
            """,
            (username, "ADMIN" if role == "admin" else "OPERACION", 1 if casos else 0, now()),
        )
    except sqlite3.OperationalError:
        pass
    return username


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, type=Path, help="CSV con usuarios y claves.")
    parser.add_argument("--db", required=True, type=Path, help="Ruta a vigia.db.")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"No existe la base: {args.db}")
    if not args.csv.exists():
        raise SystemExit(f"No existe el CSV: {args.csv}")

    backup = backup_database(args.db)
    restored: list[str] = []
    with args.csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("El CSV no contiene usuarios.")

    with sqlite3.connect(args.db) as conn:
        conn.executescript(AUTH_SCHEMA)
        for row in rows:
            restored.append(restore_user(conn, row))
        conn.commit()

    print(f"Backup creado: {backup}")
    print(f"Usuarios restaurados: {len(restored)}")
    for username in restored:
        print(f" - {username}")


if __name__ == "__main__":
    main()
