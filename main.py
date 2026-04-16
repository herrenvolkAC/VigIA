"""
VigIA v2.0 · main.py
Servidor FastAPI principal.
"""
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from db.schema import init_db
from routers.ai import router as ai_router
from routers.data import router as data_router

# ── Configuración ─────────────────────────────────────────────────────────────
load_dotenv()

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

# Archivos estáticos (JS, CSS si hubiera)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/resources", StaticFiles(directory=RESOURCES_DIR), name="resources")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# ── Arranque ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
    )
