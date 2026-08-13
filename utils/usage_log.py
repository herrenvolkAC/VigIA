import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Request

from db.auth import AUTH_DB_PATH


BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "VigiaLog"
LOG_PREFIX = "VigiaLog_"
LOG_SUFFIX = ".txt"
HEADER = (
    f"{'fecha':<10}\t"
    f"{'hora':<8}\t"
    f"{'usuario':<24}\t"
    f"{'ip':<15}\t"
    f"{'modulo':<32}\t"
    "accion\n"
)


MODULE_LABELS = {
    "acceso": "Acceso",
    "admin": "Administracion",
    "productividad": "Productividad",
    "gestion_operativa": "Gestion Operativa",
    "opex": "OpEX",
    "novedades_cd": "Tablero RRHH",
    "historia_legajo": "Historia de Legajo",
    "casos": "Gestion de Casos",
    "panol": "Panol Insumos",
    "simulador_operativo": "Simulador Operativo",
    "analisis_premio_productividad": "Analisis Premio Productividad",
    "plantel_optimo": "Plantel Optimo",
    "rendimiento_online": "Rendimiento Online",
    "checklist_tareas": "CheckList Tareas",
    "reposicion": "Reposicion",
    "recepcion": "Recepcion",
    "generales": "Herramientas Operativas",
    "sistema": "Sistema",
}


ACTION_LABELS = {
    "login_ok": "Inicio sesion",
    "login_failed": "Intento iniciar sesion sin exito",
    "logout": "Cerro sesion",
    "open_page": "Abrio la pantalla {module}",
    "view_info": "Consulto informacion de {module}",
    "save_info": "Guardo cambios en {module}",
    "delete_info": "Elimino informacion de {module}",
    "access_denied": "Intento ingresar a {module} sin permiso habilitado",
    "pending_device": "Intento ingresar con dispositivo pendiente de aprobacion",
    "unauthenticated": "Intento ingresar sin iniciar sesion",
    "server_error": "Error del servidor en {module}. Revisar log tecnico.",
    "forms_import_error": "No se pudo importar Forms Service Racks. Revisar log tecnico.",
    "database_locked": "Base de datos ocupada. Reintentar la operacion.",
}

_last_cleanup_date: str | None = None

ATTENTION_ACTIONS = {
    "login_failed",
    "access_denied",
    "pending_device",
    "unauthenticated",
    "server_error",
    "forms_import_error",
    "database_locked",
}

USAGE_EVENTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS auth_usage_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha TEXT NOT NULL,
    hora TEXT NOT NULL,
    username TEXT,
    ip_address TEXT,
    module TEXT,
    module_label TEXT,
    action TEXT,
    action_label TEXT NOT NULL,
    path TEXT,
    method TEXT,
    status_code INTEGER,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_auth_usage_events_created ON auth_usage_events(created_at);
CREATE INDEX IF NOT EXISTS idx_auth_usage_events_user_created ON auth_usage_events(username, created_at);
CREATE INDEX IF NOT EXISTS idx_auth_usage_events_module_created ON auth_usage_events(module, created_at);
CREATE INDEX IF NOT EXISTS idx_auth_usage_events_action_created ON auth_usage_events(action, created_at);
"""


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\t", " ").split())


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


def module_label(module: str | None) -> str:
    return MODULE_LABELS.get(module or "", _clean(module) or MODULE_LABELS["sistema"])


def action_label(action: str, module: str | None = None) -> str:
    label = ACTION_LABELS.get(action, action)
    return label.format(module=module_label(module))


def _write_txt_enabled() -> str:
    return os.getenv("VIGIA_USAGE_TXT_MODE", "attention").strip().lower()


def _should_write_txt(action: str | None, attention: bool = False) -> bool:
    mode = _write_txt_enabled()
    if mode in {"0", "false", "no", "off", "none", "disabled"}:
        return False
    if mode in {"all", "todo"}:
        return True
    return attention or (action or "") in ATTENTION_ACTIONS


def ensure_usage_events_schema() -> None:
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(AUTH_DB_PATH, timeout=2)) as conn:
        conn.executescript(USAGE_EVENTS_SCHEMA_SQL)
        conn.commit()


def cleanup_old_usage_logs(now: datetime | None = None) -> None:
    now = now or datetime.now()
    cutoff = now - timedelta(days=31)
    if not LOG_DIR.exists():
        return
    for path in LOG_DIR.glob(f"{LOG_PREFIX}*{LOG_SUFFIX}"):
        stamp = path.stem.removeprefix(LOG_PREFIX)
        try:
            log_date = datetime.strptime(stamp, "%Y%m%d")
        except ValueError:
            continue
        if log_date < cutoff:
            try:
                path.unlink()
            except OSError:
                pass


def _cleanup_once_per_day(now: datetime) -> None:
    global _last_cleanup_date
    today = now.strftime("%Y-%m-%d")
    if _last_cleanup_date == today:
        return
    cleanup_old_usage_logs(now)
    _last_cleanup_date = today


def write_usage_log(
    request: Request,
    username: str | None,
    module: str | None,
    action: str,
    status_code: int | None = None,
) -> None:
    action_text = action_label(action, module)
    path = str(request.url.path)
    method = str(request.method or "").upper()
    ip = _client_ip(request)
    try:
        write_usage_db(
            username=username,
            ip=ip,
            module=module,
            action=action,
            action_text=action_text,
            path=path,
            method=method,
            status_code=status_code,
        )
    except Exception:
        write_usage_event(
            username="sistema",
            ip="servidor",
            module="sistema",
            action_text="No se pudo guardar un evento de uso en la base. Revisar base de autenticacion.",
            action="usage_db_error",
            attention=True,
        )
    write_usage_event(
        username=username,
        ip=ip,
        module=module,
        action_text=action_text,
        action=action,
        attention=False,
    )


def write_usage_event(
    username: str | None,
    ip: str | None,
    module: str | None,
    action_text: str,
    action: str | None = None,
    attention: bool = False,
) -> None:
    if not _should_write_txt(action, attention):
        return
    now = datetime.now()
    _cleanup_once_per_day(now)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{LOG_PREFIX}{now:%Y%m%d}{LOG_SUFFIX}"
    if not path.exists() or path.stat().st_size == 0:
        path.write_text(HEADER, encoding="utf-8")

    module_text = module_label(module)
    line = (
        f"{now:%Y-%m-%d}\t"
        f"{now:%H:%M:%S}\t"
        f"{_clean(username) or 'sin_usuario':<24}\t"
        f"{_clean(ip) or 'sin_ip':<15}\t"
        f"{module_text:<32}\t"
        f"{_clean(action_text)}\n"
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def write_usage_db(
    username: str | None,
    ip: str | None,
    module: str | None,
    action: str | None,
    action_text: str,
    path: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    now = datetime.now()
    module_text = module_label(module)
    clean_metadata = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")) if metadata else None
    with closing(sqlite3.connect(AUTH_DB_PATH, timeout=2)) as conn:
        conn.execute("PRAGMA busy_timeout = 2000")
        conn.executescript(USAGE_EVENTS_SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO auth_usage_events (
                created_at, fecha, hora, username, ip_address, module, module_label,
                action, action_label, path, method, status_code, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{now:%Y-%m-%d %H:%M:%S}",
                f"{now:%Y-%m-%d}",
                f"{now:%H:%M:%S}",
                _clean(username) or None,
                _clean(ip) or None,
                _clean(module) or None,
                module_text,
                _clean(action) or None,
                _clean(action_text),
                _clean(path) or None,
                _clean(method).upper() or None,
                status_code,
                clean_metadata,
            ),
        )
        conn.commit()


def request_action(method: str, is_page: bool) -> str:
    if is_page:
        return "open_page"
    method = (method or "").upper()
    if method == "GET":
        return "view_info"
    if method == "DELETE":
        return "delete_info"
    if method in {"POST", "PUT", "PATCH"}:
        return "save_info"
    return "view_info"
