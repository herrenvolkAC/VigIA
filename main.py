"""
VigIA v2.0 · main.py
Servidor FastAPI principal.
"""
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import quote

import uvicorn
import aiosqlite
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv(override=True)

from db.schema import DB_PATH, init_db
from db.recepcion import init_recepcion_db, migrate_legacy_recepcion_db
from db.auth import init_auth_db
from db.checklist_tareas import init_checklist_tareas_db
from db.casos import init_cases_db
from db.daily_operativa import init_daily_db
from db.panol_insumos import init_panol_db
from db.plantel_optimo import init_plantel_optimo_db
from routers.auth_local import current_auth, ensure_bootstrap_admin, router as auth_router, user_has_module_access
from routers.checklist_tareas import router as checklist_tareas_router
from routers.ai import router as ai_router
from routers.data import router as data_router
from routers.turnos import router as turnos_router
from routers.operarios import router as operarios_router
from routers.productividad_analisis import router as productividad_analisis_router
from routers.plantel_operativo import router as plantel_operativo_router
from routers.gestion_operativa import router as gestion_operativa_router
from routers.gestion_operativa import start_daily_auto_scheduler, stop_daily_auto_scheduler
from routers.herramientas import router as herramientas_router
from routers.casos import router as casos_router, start_forms_import_monitor, stop_forms_import_monitor
from routers.recepcion import router as recepcion_router
from routers.historia_legajo import (
    router as historia_legajo_router,
    start_historia_actividad_scheduler,
    stop_historia_actividad_scheduler,
)
from routers.rrhh_novedades import (
    router as rrhh_novedades_router,
    start_rrhh_folder_monitor,
    start_rrhh_oracle_activity_scheduler,
    stop_rrhh_folder_monitor,
    stop_rrhh_oracle_activity_scheduler,
)
from routers.panol_insumos import (
    router as panol_insumos_router,
    start_panol_stock_cd_scheduler,
    stop_panol_stock_cd_scheduler,
)
from routers.plantel_optimo import router as plantel_optimo_router
from routers.simulador_operativo import init_simulador_db, router as simulador_operativo_router
from routers.analisis_premio_productividad import (
    init_premio_productividad_db,
    router as analisis_premio_productividad_router,
)
from routers.rendimiento_online import (
    router as rendimiento_online_router,
    start_rendimiento_historico_scheduler,
    stop_rendimiento_historico_scheduler,
)
from routers.monitor_cargas import router as monitor_cargas_router
from routers.websocket import router as websocket_router
from utils.db_backup import start_db_backup_scheduler, stop_db_backup_scheduler
from utils.usage_log import cleanup_old_usage_logs, ensure_usage_events_schema, request_action, write_usage_event, write_usage_log

# ── Configuración ─────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
TECH_LOG_PATH = Path(os.getenv("VIGIA_TECH_LOG_PATH", str(LOG_DIR / "vigia.txt")))
TECH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(TECH_LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger("vigia")

STATIC_DIR = Path(__file__).parent / "static"
RESOURCES_DIR = Path(__file__).parent / "resources"


# ── Lifespan (arranque / cierre) ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializando VigIA v2.0...")
    await init_db()
    await init_recepcion_db()
    await migrate_legacy_recepcion_db(DB_PATH)
    await init_auth_db()
    await init_checklist_tareas_db()
    await init_cases_db()
    await init_daily_db()
    await init_panol_db()
    await init_plantel_optimo_db()
    await init_simulador_db()
    await init_premio_productividad_db()
    await ensure_bootstrap_admin()
    ensure_usage_events_schema()
    cleanup_old_usage_logs()
    start_daily_auto_scheduler()
    start_historia_actividad_scheduler()
    start_panol_stock_cd_scheduler()
    start_rendimiento_historico_scheduler()
    start_rrhh_folder_monitor()
    start_rrhh_oracle_activity_scheduler()
    start_forms_import_monitor()
    start_db_backup_scheduler()
    provider = os.getenv("AI_PROVIDER", "claude")
    logger.info(f"Proveedor IA configurado: {provider}")
    # Si está en modo Ollama, log de la URL
    if provider == "ollama":
        ollama_url = os.getenv("OLLAMA_URL", "no configurada")
        ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
        logger.info(f"  Ollama URL: {ollama_url}")
        logger.info(f"  Ollama Model: {ollama_model}")
    try:
        yield
    finally:
        await stop_rrhh_folder_monitor()
        await stop_rrhh_oracle_activity_scheduler()
        await stop_panol_stock_cd_scheduler()
        await stop_forms_import_monitor()
        await stop_db_backup_scheduler()
        await stop_rendimiento_historico_scheduler()
        await stop_daily_auto_scheduler()
        await stop_historia_actividad_scheduler()
        logger.info("VigIA detenido.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="VigIA",
    description="Gemelo Operativo WMS — CD Coto",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(ai_router, prefix="/api")
app.include_router(data_router, prefix="/api")
app.include_router(turnos_router)
app.include_router(operarios_router)
app.include_router(productividad_analisis_router)
app.include_router(plantel_operativo_router)
app.include_router(gestion_operativa_router)
app.include_router(herramientas_router)
app.include_router(casos_router)
app.include_router(recepcion_router)
app.include_router(historia_legajo_router)
app.include_router(rrhh_novedades_router)
app.include_router(panol_insumos_router)
app.include_router(plantel_optimo_router)
app.include_router(simulador_operativo_router)
app.include_router(analisis_premio_productividad_router)
app.include_router(rendimiento_online_router)
app.include_router(monitor_cargas_router)
app.include_router(websocket_router)
app.include_router(auth_router)
app.include_router(checklist_tareas_router)


PROTECTED_PAGE_PATHS = {
    "/tiempos-muertos",
    "/tiempos-muertos.html",
    "/gestion-operativa",
    "/gestion-operativa.html",
    "/opex",
    "/opex.html",
    "/opex-daily",
    "/opex-daily.html",
    "/opex-shift",
    "/opex-shift.html",
    "/opex-olas",
    "/opex-olas.html",
    "/novedades-cd",
    "/novedades-cd.html",
    "/historia-legajo",
    "/historia-legajo.html",
    "/casos",
    "/casos.html",
    "/panol-insumos",
    "/panol-insumos.html",
    "/simulador-operativo",
    "/simulador-operativo.html",
    "/analisis-premio-productividad",
    "/analisis-premio-productividad.html",
    "/plantel-optimo",
    "/plantel-optimo.html",
    "/rendimiento-online",
    "/rendimiento-online.html",
    "/monitor-cargas",
    "/monitor-cargas.html",
    "/checklist-tareas",
    "/checklist-tareas.html",
    "/herramientas",
    "/herramientas.html",
}
PROTECTED_API_PREFIXES = (
    "/api/productividad/tnc",
    "/api/productividad/picking/tiempos-muertos",
    "/api/gestion-operativa",
    "/api/historia-legajo",
    "/api/rrhh",
    "/api/casos",
    "/panol-insumos/api",
    "/api/simulador-operativo",
    "/api/analisis-premio-productividad",
    "/api/plantel-optimo",
    "/api/rendimiento-online",
    "/api/monitor-cargas",
    "/api/checklist-tareas",
    "/api/herramientas",
)
ADMIN_PAGE_PATHS = {
    "/admin/dispositivos",
    "/admin/dispositivos.html",
    "/admin/usuarios",
    "/admin/usuarios.html",
    "/admin/accesos",
    "/admin/accesos.html",
    "/admin/auditoria",
    "/admin/auditoria.html",
}
PAGE_MODULES = {
    "/productividad": "productividad",
    "/productividad.html": "productividad",
    "/picking": "productividad",
    "/picking.html": "productividad",
    "/produccion": "productividad",
    "/produccion.html": "productividad",
    "/gestion-operativa": "gestion_operativa",
    "/gestion-operativa.html": "gestion_operativa",
    "/opex": "opex",
    "/opex.html": "opex",
    "/opex-daily": "opex",
    "/opex-daily.html": "opex",
    "/opex-shift": "opex",
    "/opex-shift.html": "opex",
    "/opex-olas": "opex",
    "/opex-olas.html": "opex",
    "/novedades-cd": "novedades_cd",
    "/novedades-cd.html": "novedades_cd",
    "/historia-legajo": "historia_legajo",
    "/historia-legajo.html": "historia_legajo",
    "/casos": "casos",
    "/casos.html": "casos",
    "/panol-insumos": "panol",
    "/panol-insumos.html": "panol",
    "/simulador-operativo": "simulador_operativo",
    "/simulador-operativo.html": "simulador_operativo",
    "/analisis-premio-productividad": "analisis_premio_productividad",
    "/analisis-premio-productividad.html": "analisis_premio_productividad",
    "/plantel-optimo": "plantel_optimo",
    "/plantel-optimo.html": "plantel_optimo",
    "/rendimiento-online": "rendimiento_online",
    "/rendimiento-online.html": "rendimiento_online",
    "/monitor-cargas": "control_procesos",
    "/monitor-cargas.html": "control_procesos",
    "/checklist-tareas": "checklist_tareas",
    "/checklist-tareas.html": "checklist_tareas",
    "/herramientas": "generales",
    "/herramientas.html": "generales",
    "/reposicion": "reposicion",
    "/reposicion.html": "reposicion",
    "/recepcion": "recepcion",
    "/recepcion.html": "recepcion",
}
API_MODULE_PREFIXES = (
    ("/api/gestion-operativa/daily", "opex"),
    ("/api/gestion-operativa/cambio-turno", "opex"),
    ("/api/gestion-operativa/olas", "opex"),
    ("/api/gestion-operativa", "gestion_operativa"),
    ("/api/historia-legajo", "historia_legajo"),
    ("/api/rrhh", "novedades_cd"),
    ("/api/casos", "casos"),
    ("/api/recepcion", "recepcion"),
    ("/panol-insumos/api", "panol"),
    ("/api/simulador-operativo", "simulador_operativo"),
    ("/api/analisis-premio-productividad", "analisis_premio_productividad"),
    ("/api/plantel-optimo", "plantel_optimo"),
    ("/api/rendimiento-online", "rendimiento_online"),
    ("/api/monitor-cargas", "control_procesos"),
    ("/api/checklist-tareas", "checklist_tareas"),
    ("/api/herramientas", "generales"),
)


def _login_redirect(path: str) -> RedirectResponse:
    return RedirectResponse(f"/login?next={quote(path)}", status_code=303)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    is_protected_page = path in PROTECTED_PAGE_PATHS
    is_admin_page = path in ADMIN_PAGE_PATHS
    is_protected_api = any(path.startswith(prefix) for prefix in PROTECTED_API_PREFIXES)
    is_module_page = path in PAGE_MODULES
    is_module_api = any(path.startswith(prefix) for prefix, _ in API_MODULE_PREFIXES)

    if not (is_protected_page or is_admin_page or is_protected_api or is_module_page or is_module_api):
        return await call_next(request)

    auth = await current_auth(request)
    if not auth:
        module = PAGE_MODULES.get(path)
        if not module:
            module = next((module_id for prefix, module_id in API_MODULE_PREFIXES if path.startswith(prefix)), None)
        write_usage_log(request, None, module or "acceso", "unauthenticated", status_code=401)
        if is_protected_api:
            return JSONResponse({"detail": "No autenticado."}, status_code=401)
        return _login_redirect(path)

    if auth.get("device_status") != "approved":
        write_usage_log(request, auth.get("username"), "acceso", "pending_device", status_code=403)
        if is_protected_api:
            return JSONResponse({"detail": "Dispositivo pendiente de aprobacion."}, status_code=403)
        return RedirectResponse("/api/auth/pending", status_code=303)

    if is_admin_page and auth.get("role") != "admin":
        write_usage_log(request, auth.get("username"), "admin", "access_denied", status_code=403)
        return JSONResponse({"detail": "Requiere administrador."}, status_code=403)

    module = PAGE_MODULES.get(path)
    if not module:
        module = next((module_id for prefix, module_id in API_MODULE_PREFIXES if path.startswith(prefix)), None)
    if module and not await user_has_module_access(auth, module):
        write_usage_log(request, auth.get("username"), module, "access_denied", status_code=403)
        if is_protected_api or path.startswith("/api/") or path.startswith("/panol-insumos/api"):
            return JSONResponse({"detail": "No tenes acceso habilitado a este modulo."}, status_code=403)
        return RedirectResponse(f"/selector?denied={quote(module)}", status_code=303)

    try:
        response = await call_next(request)
    except Exception:
        username = auth.get("username")
        module_for_log = module or ("admin" if is_admin_page else "sistema")
        logger.exception(
            "Error no controlado en request: usuario=%s ip=%s metodo=%s path=%s modulo=%s",
            username,
            request.client.host if request.client else "",
            request.method,
            path,
            module_for_log,
        )
        try:
            write_usage_log(request, username, module_for_log, "server_error", status_code=500)
        except Exception:
            write_usage_event(
                username=username,
                ip=request.client.host if request.client else "",
                module=module_for_log,
                action="server_error",
                action_text="Error del servidor. No se pudo guardar el detalle en la base de auditoria.",
                attention=True,
            )
        raise
    if response.status_code < 400:
        write_usage_log(
            request,
            auth.get("username"),
            module or ("admin" if is_admin_page else "sistema"),
            request_action(request.method, is_module_page or is_admin_page),
            status_code=response.status_code,
        )
    return response

# Archivos estáticos — css, js y resources
app.mount("/css",       StaticFiles(directory=STATIC_DIR / "css"),  name="css")
app.mount("/js",        StaticFiles(directory=STATIC_DIR / "js"),   name="js")
app.mount("/resources", StaticFiles(directory=RESOURCES_DIR),       name="resources")

# Páginas HTML
@app.get("/api/app-info")
async def app_info():
    environment = os.getenv("VIGIA_APP_ENV", "test").strip().lower()
    banner = os.getenv(
        "VIGIA_APP_BANNER",
        "VERSION DE PRUEBAS - pendiente de implementacion en servidor",
    ).strip()
    return {
        "environment": environment,
        "banner": banner,
        "show_banner": bool(banner) and environment not in {"prod", "production", "produccion"},
    }


_PAGES = [
    "/",             "index.html",
    "/login",        "login.html",
    "/selector",     "selector.html",
    "/productividad","productividad.html",
    "/picking",      "productividad.html",
    "/produccion",   "productividad.html",
    "/recepcion",    "recepcion.html",
    "/reposicion",   "reposicion.html",
    "/opex",         "opex.html",
    "/opex-daily",   "opex_daily.html",
    "/opex-shift",   "opex_shift.html",
    "/opex-olas",    "opex_olas.html",
    "/planificacion","planificacion.html",
    "/fase1",        "fase1_dashboard.html",
]

@app.get("/",              include_in_schema=False)
async def page_index():        return FileResponse(STATIC_DIR / "login.html")

@app.get("/login.html",    include_in_schema=False)
@app.get("/login",         include_in_schema=False)
async def page_login():        return FileResponse(STATIC_DIR / "login.html")

@app.get("/selector.html", include_in_schema=False)
@app.get("/selector",      include_in_schema=False)
async def page_selector():     return FileResponse(STATIC_DIR / "selector.html")

@app.get("/picking.html",     include_in_schema=False)
@app.get("/picking",          include_in_schema=False)
@app.get("/produccion.html",  include_in_schema=False)
@app.get("/produccion",       include_in_schema=False)
async def page_picking():      return FileResponse(STATIC_DIR / "productividad.html")

@app.get("/productividad.html", include_in_schema=False)
@app.get("/productividad",      include_in_schema=False)
async def page_productividad():  return FileResponse(STATIC_DIR / "productividad.html")

@app.get("/tiempos-muertos.html", include_in_schema=False)
@app.get("/tiempos-muertos",      include_in_schema=False)
async def page_tiempos_muertos(): return FileResponse(STATIC_DIR / "tiempos_muertos.html")

@app.get("/gestion-operativa.html", include_in_schema=False)
@app.get("/gestion-operativa",      include_in_schema=False)
async def page_gestion_operativa(): return FileResponse(STATIC_DIR / "gestion_operativa.html")

@app.get("/opex.html", include_in_schema=False)
@app.get("/opex",      include_in_schema=False)
async def page_opex(): return FileResponse(STATIC_DIR / "opex.html")

@app.get("/opex-daily.html", include_in_schema=False)
@app.get("/opex-daily",      include_in_schema=False)
async def page_opex_daily(): return FileResponse(STATIC_DIR / "opex_daily.html")

@app.get("/opex-shift.html", include_in_schema=False)
@app.get("/opex-shift",      include_in_schema=False)
async def page_opex_shift(): return FileResponse(STATIC_DIR / "opex_shift.html")

@app.get("/opex-olas.html", include_in_schema=False)
@app.get("/opex-olas",      include_in_schema=False)
async def page_opex_olas(): return FileResponse(STATIC_DIR / "opex_olas.html")

@app.get("/novedades-cd.html", include_in_schema=False)
@app.get("/novedades-cd",      include_in_schema=False)
async def page_novedades_cd(): return FileResponse(STATIC_DIR / "novedades_cd.html")

@app.get("/historia-legajo.html", include_in_schema=False)
@app.get("/historia-legajo",      include_in_schema=False)
async def page_historia_legajo(): return FileResponse(STATIC_DIR / "historia_legajo.html")

@app.get("/casos.html", include_in_schema=False)
@app.get("/casos",      include_in_schema=False)
async def page_casos(): return FileResponse(STATIC_DIR / "casos.html")

@app.get("/panol-insumos.html", include_in_schema=False)
@app.get("/panol-insumos",      include_in_schema=False)
async def page_panol_insumos():
    return FileResponse(
        STATIC_DIR / "panol_insumos.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/simulador-operativo.html", include_in_schema=False)
@app.get("/simulador-operativo",      include_in_schema=False)
async def page_simulador_operativo(): return FileResponse(STATIC_DIR / "simulador_operativo.html")

@app.get("/analisis-premio-productividad.html", include_in_schema=False)
@app.get("/analisis-premio-productividad",      include_in_schema=False)
async def page_analisis_premio_productividad():
    return FileResponse(
        STATIC_DIR / "analisis_premio_productividad.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/plantel-optimo.html", include_in_schema=False)
@app.get("/plantel-optimo",      include_in_schema=False)
async def page_plantel_optimo():
    return FileResponse(STATIC_DIR / "plantel_optimo.html")

@app.get("/rendimiento-online.html", include_in_schema=False)
@app.get("/rendimiento-online",      include_in_schema=False)
async def page_rendimiento_online():
    return FileResponse(STATIC_DIR / "rendimiento_online.html")

@app.get("/monitor-cargas.html", include_in_schema=False)
@app.get("/monitor-cargas",      include_in_schema=False)
async def page_monitor_cargas():
    return FileResponse(
        STATIC_DIR / "monitor_cargas.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/checklist-tareas.html", include_in_schema=False)
@app.get("/checklist-tareas",      include_in_schema=False)
async def page_checklist_tareas():
    return FileResponse(
        STATIC_DIR / "checklist_tareas.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/herramientas.html", include_in_schema=False)
@app.get("/herramientas",      include_in_schema=False)
async def page_herramientas():
    return FileResponse(
        STATIC_DIR / "herramientas.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/admin/dispositivos.html", include_in_schema=False)
@app.get("/admin/dispositivos",      include_in_schema=False)
async def page_admin_dispositivos(): return FileResponse(STATIC_DIR / "admin_dispositivos.html")

@app.get("/admin/usuarios.html", include_in_schema=False)
@app.get("/admin/usuarios",      include_in_schema=False)
async def page_admin_usuarios(): return FileResponse(STATIC_DIR / "admin_usuarios.html")

@app.get("/admin/accesos.html", include_in_schema=False)
@app.get("/admin/accesos",      include_in_schema=False)
async def page_admin_accesos(): return FileResponse(STATIC_DIR / "admin_accesos.html")

@app.get("/admin/auditoria.html", include_in_schema=False)
@app.get("/admin/auditoria",      include_in_schema=False)
async def page_admin_auditoria(): return FileResponse(STATIC_DIR / "admin_auditoria.html")

@app.get("/recepcion.html",    include_in_schema=False)
@app.get("/recepcion",         include_in_schema=False)
async def page_recepcion():    return FileResponse(STATIC_DIR / "recepcion.html")

@app.get("/reposicion.html",   include_in_schema=False)
@app.get("/reposicion",        include_in_schema=False)
async def page_reposicion():   return FileResponse(STATIC_DIR / "reposicion.html")

@app.get("/planificacion.html",include_in_schema=False)
@app.get("/planificacion",     include_in_schema=False)
async def page_planificacion():return FileResponse(STATIC_DIR / "planificacion.html")

@app.get("/fase1.html",        include_in_schema=False)
@app.get("/fase1",             include_in_schema=False)
async def page_fase1():        return FileResponse(STATIC_DIR / "fase1_dashboard.html")

@app.get("/turno_realtime.html", include_in_schema=False)
@app.get("/turno_realtime",      include_in_schema=False)
async def page_turno_realtime(): return FileResponse(STATIC_DIR / "turno_realtime.html")

@app.get("/detalle_operario.html", include_in_schema=False)
@app.get("/detalle_operario",      include_in_schema=False)
async def page_detalle_operario(): return FileResponse(STATIC_DIR / "detalle_operario.html")

@app.get("/comparativas.html",   include_in_schema=False)
@app.get("/comparativas",        include_in_schema=False)
async def page_comparativas():   return FileResponse(STATIC_DIR / "comparativas.html")

@app.get("/config_y_recomendaciones.html", include_in_schema=False)
@app.get("/config_y_recomendaciones",      include_in_schema=False)
async def page_config_y_recomendaciones(): return FileResponse(STATIC_DIR / "config_y_recomendaciones.html")


@app.get("/api/config/ia", include_in_schema=False)
async def config_ia():
    """Expone el proveedor IA activo (sin claves). Configurar via AI_PROVIDER en .env."""
    provider = os.getenv("AI_PROVIDER", "claude")
    labels = {
        "claude": "Claude AI (Anthropic)",
        "ollama": "Ollama (Local)",
        "gemini": "Gemini (Google)",
        "azure": "Azure OpenAI",
    }
    return JSONResponse({"provider": provider, "label": labels.get(provider, provider)})


# ── Turno activo con campo proceso (v3) ───────────────────────────────────────
# Wrapper que enriquece la respuesta del router data con `proceso: "picking"`
@app.get("/api/turno/activo/v3", include_in_schema=False)
async def turno_activo_v3():
    """Igual que /api/turno/activo pero agrega campo proceso para el selector."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM turnos WHERE cerrado=0 ORDER BY created_at DESC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return JSONResponse({"turno": None, "proceso": "picking"})
            turno_dict = dict(row)
            turno_dict["proceso"] = "picking"
            # Calcular pct_avance básico si hay objetivo_total
            obj = turno_dict.get("objetivo_total") or 0
            if obj > 0:
                async with db.execute(
                    "SELECT SUM(bultos_ejecutados) as total FROM movimientos WHERE turno_id=?",
                    (turno_dict["turno_id"],),
                ) as cur2:
                    row2 = await cur2.fetchone()
                ejec = (dict(row2).get("total") or 0) if row2 else 0
                turno_dict["pct_avance"] = round(ejec / obj * 100, 1)
            return JSONResponse(turno_dict)
    except Exception as e:
        logger.warning(f"turno_activo_v3 error: {e}")
        return JSONResponse({"turno": None, "proceso": "picking"})


# ── Arranque ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=9999, reload=False)
  
