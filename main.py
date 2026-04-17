"""
VigIA v2.0 · main.py
Servidor FastAPI principal.
"""
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
import aiosqlite
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv

from db.schema import init_db
from routers.ai import router as ai_router
from routers.data import router as data_router

# ── Configuración ─────────────────────────────────────────────────────────────
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vigia")

STATIC_DIR = Path(__file__).parent / "static"
RESOURCES_DIR = Path(__file__).parent / "resources"


# ── Lifespan (arranque / cierre) ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inicializando VigIA v2.0...")
    await init_db()
    provider = os.getenv("AI_PROVIDER", "claude")
    logger.info(f"Proveedor IA configurado: {provider}")
    # Si está en modo Ollama, log de la URL
    if provider == "ollama":
        ollama_url = os.getenv("OLLAMA_URL", "no configurada")
        ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
        logger.info(f"  Ollama URL: {ollama_url}")
        logger.info(f"  Ollama Model: {ollama_model}")
    yield
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

# Archivos estáticos — css, js y resources
app.mount("/css",       StaticFiles(directory=STATIC_DIR / "css"),  name="css")
app.mount("/js",        StaticFiles(directory=STATIC_DIR / "js"),   name="js")
app.mount("/resources", StaticFiles(directory=RESOURCES_DIR),       name="resources")

# Páginas HTML
_PAGES = [
    "/",             "index.html",
    "/login",        "login.html",
    "/selector",     "selector.html",
    "/picking",      "picking.html",
    "/recepcion",    "recepcion.html",
    "/reposicion",   "reposicion.html",
    "/planificacion","planificacion.html",
]

@app.get("/",              include_in_schema=False)
async def page_index():        return FileResponse(STATIC_DIR / "login.html")

@app.get("/login.html",    include_in_schema=False)
@app.get("/login",         include_in_schema=False)
async def page_login():        return FileResponse(STATIC_DIR / "login.html")

@app.get("/selector.html", include_in_schema=False)
@app.get("/selector",      include_in_schema=False)
async def page_selector():     return FileResponse(STATIC_DIR / "selector.html")

@app.get("/picking.html",  include_in_schema=False)
@app.get("/picking",       include_in_schema=False)
async def page_picking():      return FileResponse(STATIC_DIR / "picking.html")

@app.get("/recepcion.html",    include_in_schema=False)
@app.get("/recepcion",         include_in_schema=False)
async def page_recepcion():    return FileResponse(STATIC_DIR / "recepcion.html")

@app.get("/reposicion.html",   include_in_schema=False)
@app.get("/reposicion",        include_in_schema=False)
async def page_reposicion():   return FileResponse(STATIC_DIR / "reposicion.html")

@app.get("/planificacion.html",include_in_schema=False)
@app.get("/planificacion",     include_in_schema=False)
async def page_planificacion():return FileResponse(STATIC_DIR / "planificacion.html")


# ── Turno activo con campo proceso (v3) ───────────────────────────────────────
# Wrapper que enriquece la respuesta del router data con `proceso: "picking"`
@app.get("/api/turno/activo/v3", include_in_schema=False)
async def turno_activo_v3():
    """Igual que /api/turno/activo pero agrega campo proceso para el selector."""
    import os
    DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent / "vigia.db"))
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
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
  