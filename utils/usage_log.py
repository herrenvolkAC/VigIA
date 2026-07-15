from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Request


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
}

_last_cleanup_date: str | None = None


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
) -> None:
    now = datetime.now()
    _cleanup_once_per_day(now)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{LOG_PREFIX}{now:%Y%m%d}{LOG_SUFFIX}"
    if not path.exists() or path.stat().st_size == 0:
        path.write_text(HEADER, encoding="utf-8")

    module_text = module_label(module)
    action_text = action_label(action, module)
    line = (
        f"{now:%Y-%m-%d}\t"
        f"{now:%H:%M:%S}\t"
        f"{_clean(username) or 'sin_usuario':<24}\t"
        f"{_clean(_client_ip(request)) or 'sin_ip':<15}\t"
        f"{module_text:<32}\t"
        f"{_clean(action_text)}\n"
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


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
