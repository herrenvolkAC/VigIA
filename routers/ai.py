"""
VigIA v2.0 · routers/ai.py
Endpoints de IA: /api/analyze, /api/chat, /api/providers
"""
import os
import json
import time
import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("vigia.ai")
router = APIRouter()

# ── Prompts del sistema ───────────────────────────────────────────────────────
SYSTEM_ANALYZE = (
    "Sos un analista operativo senior de un centro de distribución (CD Coto).\n"
    "Recibís el estado actual de la operación de picking y generás alertas accionables "
    "para el supervisor de turno.\n"
    "Respondé SOLO con JSON válido, sin markdown ni texto extra:\n"
    '{"alerts":[{"severity":"ok|warn|bad","title":"título breve máx 8 palabras",'
    '"detail":"qué está pasando con números concretos",'
    '"action":"qué hacer ahora, específico y operativo"}]}\n'
    "Reglas: 2-4 alertas. bad=crítico, warn=riesgo, ok=positivo. "
    "Acciones concretas con números."
)

SYSTEM_CHAT = (
    "Sos un asistente operativo del CD Coto. Respondés preguntas del supervisor de turno "
    "sobre el estado del picking.\n"
    "Respondés en español, de forma concisa y directa (máx 3 oraciones).\n"
    "Solo usás datos del contexto operativo. No inventás información."
)

TIMEOUT = 30.0


# ── Helpers de configuración ──────────────────────────────────────────────────
def _claude_configured() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    return bool(key and key.startswith("sk-ant-"))


def _azure_configured() -> bool:
    return all([
        os.getenv("AZURE_OPENAI_ENDPOINT"),
        os.getenv("AZURE_OPENAI_API_KEY"),
        os.getenv("AZURE_OPENAI_DEPLOYMENT"),
    ])


def _active_provider() -> str:
    return os.getenv("AI_PROVIDER", "claude").lower()


# ── Llamadas a IA ─────────────────────────────────────────────────────────────
async def _call_claude(system: str, messages: list) -> str:
    import anthropic
    t0 = time.time()
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=system,
        messages=messages,
    )
    elapsed = round(time.time() - t0, 2)
    logger.info(f"[Claude] respuesta recibida en {elapsed}s")
    return response.content[0].text


async def _call_azure(system: str, messages: list) -> str:
    t0 = time.time()
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT").rstrip("/")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    payload = {
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": 1000,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json", "api-key": api_key},
            json=payload,
        )
        resp.raise_for_status()

    elapsed = round(time.time() - t0, 2)
    logger.info(f"[Azure OpenAI] respuesta recibida en {elapsed}s ({deployment})")
    return resp.json()["choices"][0]["message"]["content"]


async def _call_ai(provider: str, system: str, messages: list) -> tuple[str, str]:
    """Llama al proveedor indicado. Devuelve (texto, modelo_usado)."""
    if provider == "azure":
        if not _azure_configured():
            raise ValueError("Azure OpenAI no está configurado en .env")
        text = await _call_azure(system, messages)
        model_used = os.getenv("AZURE_OPENAI_DEPLOYMENT", "azure-gpt")
    else:
        if not _claude_configured():
            raise ValueError("Anthropic API key no configurada en .env")
        text = await _call_claude(system, messages)
        model_used = "claude-sonnet-4-6"

    return text, model_used


# ── Schemas ───────────────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    provider: Optional[str] = None
    context: str
    turno_id: Optional[int] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    provider: Optional[str] = None
    message: str
    history: Optional[list[ChatMessage]] = []
    context: Optional[str] = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Analiza el estado operativo y devuelve alertas."""
    provider = (req.provider or _active_provider()).lower()
    logger.info(f"[/api/analyze] provider={provider}")

    try:
        raw_text, model_used = await _call_ai(
            provider,
            SYSTEM_ANALYZE,
            [{"role": "user", "content": req.context}],
        )

        # Limpiar posible markdown residual
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip()

        parsed = json.loads(clean)
        alerts = parsed.get("alerts", [])

        # Persistir predicción si hay turno_id
        if req.turno_id:
            await _save_prediction(req.turno_id, alerts, provider, model_used)

        return {
            "alerts": alerts,
            "provider_used": provider,
            "model_used": model_used,
        }

    except Exception as e:
        logger.error(f"[/api/analyze] error con {provider}: {e}")
        return {
            "alerts": [],
            "provider_used": provider,
            "model_used": "—",
            "error": str(e),
        }


@router.post("/chat")
async def chat(req: ChatRequest):
    """Responde preguntas del supervisor usando el contexto operativo."""
    provider = (req.provider or _active_provider()).lower()
    logger.info(f"[/api/chat] provider={provider}, msg='{req.message[:60]}'")

    system = SYSTEM_CHAT
    if req.context:
        system += f"\n\nCONTEXTO OPERATIVO:\n{req.context}"

    history = [{"role": m.role, "content": m.content} for m in (req.history or [])]
    history.append({"role": "user", "content": req.message})

    try:
        reply, model_used = await _call_ai(provider, system, history)
        return {
            "reply": reply,
            "provider_used": provider,
            "model_used": model_used,
        }
    except Exception as e:
        logger.error(f"[/api/chat] error con {provider}: {e}")
        return {
            "reply": f"Error al consultar la IA ({provider}): {e}",
            "provider_used": provider,
            "model_used": "—",
        }


@router.get("/providers")
async def providers():
    """Lista los proveedores disponibles y cuál está activo."""
    active = _active_provider()
    return {
        "active": active,
        "available": [
            {
                "id": "claude",
                "name": "Claude (Anthropic)",
                "configured": _claude_configured(),
            },
            {
                "id": "azure",
                "name": "Azure OpenAI",
                "configured": _azure_configured(),
            },
        ],
    }


# ── Persistencia de predicciones ──────────────────────────────────────────────
async def _save_prediction(turno_id: int, alerts: list, provider: str, model: str):
    try:
        import aiosqlite
        from db.schema import DB_PATH

        now = datetime.now().strftime("%H:%M")
        async with aiosqlite.connect(DB_PATH) as db:
            for alert in alerts:
                await db.execute(
                    """INSERT INTO predicciones
                       (turno_id, hora_pred, factor_top, proveedor_ia, modelo_ver)
                       VALUES (?, ?, ?, ?, ?)""",
                    (turno_id, now, alert.get("title", ""), provider, model),
                )
            await db.commit()
    except Exception as e:
        logger.warning(f"No se pudo persistir predicción: {e}")
