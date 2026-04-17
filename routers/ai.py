"""
VigIA v2.0 · routers/ai.py
Endpoints de IA: /api/analyze, /api/chat, /api/providers
Proveedores: gemini | claude | azure | ollama
"""
import os
import re
import json
import time
import logging
from datetime import datetime, date
from typing import Optional

import aiosqlite
import httpx
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("vigia.ai")
router = APIRouter()

# ── Prompts del sistema ───────────────────────────────────────────────────────
SYSTEM_ANALYZE = (
    "Sos un analista operativo senior de un centro de distribucion (CD Coto).\n"
    "Recibis el estado actual de la operacion de picking y generas alertas accionables "
    "para el supervisor de turno.\n"
    "Responde SOLO con JSON valido, sin markdown ni texto extra:\n"
    '{"alerts":[{"severity":"ok|warn|bad","title":"titulo breve max 8 palabras",'
    '"detail":"que esta pasando con numeros concretos",'
    '"action":"que hacer ahora, especifico y operativo"}],'
    '"resumen_turno":"una oracion del estado global"}\n'
    "Reglas: 2-4 alertas. bad=critico, warn=riesgo, ok=positivo. "
    "Acciones concretas con numeros."
)

SYSTEM_ANALYZE_HIST = (
    "Sos un analista operativo senior de un centro de distribucion (CD Coto).\n"
    "Recibes el estado actual del turno activo MAS un contexto historico real "
    "de 544 dias logisticos del mismo CD.\n\n"
    "Tu objetivo es generar alertas y recomendaciones accionables para el supervisor, "
    "usando el historico como referencia objetiva.\n\n"
    "REGLAS:\n"
    "- Comparas el turno actual contra el historico del MISMO dia de semana y turno\n"
    "- Si esta por debajo, indicas la brecha concreta con numeros del historico\n"
    "- Si esta por encima, lo destacas como positivo con la referencia historica\n"
    "- Tus recomendaciones son operativas: que hacer, cuando y por que\n"
    "- Nunca nombras operarios individuales\n"
    "- Siempre usas numeros concretos del contexto\n\n"
    "Responde SOLO con JSON valido, sin markdown ni texto extra:\n"
    '{"alerts":[{"severity":"ok|warn|bad","title":"titulo breve",'
    '"detail":"que esta pasando con numeros","action":"que hacer ahora con numeros",'
    '"fuente":"historico|actual|proyeccion"}],'
    '"resumen_turno":"una oracion del estado global vs historico"}\n\n'
    "Reglas: 2-4 alertas. bad=critico, warn=riesgo, ok=positivo."
)

SYSTEM_CHAT = (
    "Sos un asistente operativo del CD Coto. Respondes preguntas del supervisor de turno "
    "sobre el estado del picking.\n"
    "Respondes en español, de forma concisa y directa (max 3 oraciones).\n"
    "Solo usas datos del contexto operativo. No inventas informacion."
)

TIMEOUT = 60.0


# ── Helpers de configuración ──────────────────────────────────────────────────
def _gemini_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def _claude_configured() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    return bool(key and key.startswith("sk-ant-"))


def _azure_configured() -> bool:
    return all([
        os.getenv("AZURE_OPENAI_ENDPOINT"),
        os.getenv("AZURE_OPENAI_API_KEY"),
        os.getenv("AZURE_OPENAI_DEPLOYMENT"),
    ])


def _ollama_configured() -> bool:
    return bool(os.getenv("OLLAMA_URL", "").strip())


def _active_provider() -> str:
    return os.getenv("AI_PROVIDER", "gemini").lower()


# ── Extracción robusta de JSON ────────────────────────────────────────────────
def _extract_json(text: str) -> str:
    """Extrae el primer objeto JSON del texto, tolerando markdown y texto extra."""
    text = text.strip()
    # Bloque ```json ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    # Buscar primer { con su matching }
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text


# ── Llamadas a IA ─────────────────────────────────────────────────────────────
async def _call_gemini(system: str, messages: list) -> str:
    import asyncio as _asyncio
    t0 = time.time()
    api_key = os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )

    contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500},
    }

    # Retry con backoff para 429
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
                json=payload,
            )
        if resp.status_code == 429 and attempt < 2:
            wait = 5 * (attempt + 1)
            logger.warning(f"[Gemini] 429 rate limit, reintentando en {wait}s (intento {attempt+1}/3)")
            await _asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        break

    data = resp.json()
    elapsed = round(time.time() - t0, 2)
    logger.info(f"[Gemini] respuesta recibida en {elapsed}s ({model})")
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_claude(system: str, messages: list) -> str:
    import anthropic
    t0 = time.time()
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
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
        "max_tokens": 1200,
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


async def _call_ollama(system: str, messages: list) -> str:
    t0 = time.time()
    ollama_url = os.getenv("OLLAMA_URL", "").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "mistral")
    if not ollama_url:
        raise ValueError("OLLAMA_URL no esta configurada en .env")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(f"{ollama_url}/api/chat", json=payload)
        resp.raise_for_status()
    elapsed = round(time.time() - t0, 2)
    logger.info(f"[Ollama] respuesta recibida en {elapsed}s (modelo: {model})")
    return resp.json()["message"]["content"]


def _build_fallback_chain(primary: str) -> list[str]:
    """Devuelve lista ordenada de proveedores: primario + fallbacks configurados."""
    all_providers = [
        ("gemini", _gemini_configured()),
        ("ollama", _ollama_configured()),
        ("azure",  _azure_configured()),
        ("claude", _claude_configured()),
    ]
    chain = [primary]
    for pid, configured in all_providers:
        if configured and pid != primary:
            chain.append(pid)
    return chain


async def _call_ai(provider: str, system: str, messages: list) -> tuple[str, str]:
    """Llama al proveedor indicado. Devuelve (texto, modelo_usado)."""
    if provider == "gemini":
        if not _gemini_configured():
            raise ValueError("GEMINI_API_KEY no esta configurada en .env")
        text = await _call_gemini(system, messages)
        model_used = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    elif provider == "azure":
        if not _azure_configured():
            raise ValueError("Azure OpenAI no esta configurado en .env")
        text = await _call_azure(system, messages)
        model_used = os.getenv("AZURE_OPENAI_DEPLOYMENT", "azure-gpt")
    elif provider == "ollama":
        if not _ollama_configured():
            raise ValueError("Ollama no esta configurado en .env (OLLAMA_URL)")
        text = await _call_ollama(system, messages)
        model_used = os.getenv("OLLAMA_MODEL", "mistral")
    else:  # claude
        if not _claude_configured():
            raise ValueError("Anthropic API key no configurada en .env")
        text = await _call_claude(system, messages)
        model_used = "claude-sonnet-4-6"

    return text, model_used


# ── Histórico ─────────────────────────────────────────────────────────────────
async def get_historico_context(turno: str, fecha_str: str) -> dict:
    """Devuelve contexto historico y metadatos para generar sugerencias."""
    try:
        async with aiosqlite.connect("vigia.db") as db:
            db.row_factory = aiosqlite.Row

            try:
                fecha_dt = date.fromisoformat(fecha_str)
                dia_semana = fecha_dt.weekday()
            except Exception:
                return {"contexto": "", "info": {}}

            DIAS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
            dia_nombre = DIAS[dia_semana]

            async with db.execute(
                """
                SELECT o.ola_num, o.ola_label, o.hora_ini, o.hora_fin,
                       ROUND(AVG(o.ejec_total), 0) AS prom_ejec,
                       ROUND(AVG(o.prog_total), 0) AS prom_prog,
                       ROUND(AVG(o.dot_ejec), 1)   AS prom_dot,
                       COUNT(*) AS n
                FROM historico_olas o
                JOIN historico_dias d ON o.dia_id = d.dia_id
                WHERE o.turno = ? AND d.dia_semana = ?
                GROUP BY o.ola_num
                ORDER BY o.ola_num
                """,
                (turno, dia_semana),
            ) as cur:
                olas_hist = await cur.fetchall()

            if not olas_hist:
                return {"contexto": "", "info": {}}

            n_dias = olas_hist[0]["n"]
            prom_turno = sum(r["prom_ejec"] for r in olas_hist)

            async with db.execute(
                """
                SELECT fecha, ejec_total, prog_total,
                       ROUND(ejec_total * 100.0 / NULLIF(prog_total, 0), 1) AS pct
                FROM historico_dias
                WHERE dia_semana = ? AND fecha != ?
                ORDER BY fecha DESC
                LIMIT 5
                """,
                (dia_semana, fecha_str),
            ) as cur:
                ultimos = await cur.fetchall()

            tabla_olas = "\n".join(
                f"  OLA {r['ola_num']} ({r['hora_ini']}-{r['hora_fin']}): "
                f"prom {r['prom_ejec']:.0f} bultos | dot media {r['prom_dot']} ops"
                for r in olas_hist
            )
            tabla_ultimos = (
                "\n".join(
                    f"  {r['fecha']}: {r['ejec_total']:.0f} bultos ({r['pct']}% vs prog)"
                    for r in ultimos
                )
                if ultimos
                else "  (sin datos recientes)"
            )

            contexto = (
                f"=== HISTORICO — {dia_nombre.upper()}S, TURNO {turno.upper()} ===\n"
                f"Basado en {n_dias} {dia_nombre.lower()}s historicos:\n\n"
                f"Promedios por ola:\n{tabla_olas}\n\n"
                f"Total turno promedio historico: {prom_turno:.0f} bultos\n\n"
                f"Ultimos 5 {dia_nombre.lower()}s similares:\n{tabla_ultimos}\n"
            )

            info = {
                "dia_semana": dia_semana,
                "dia_nombre": dia_nombre,
                "n_dias": n_dias,
                "prom_turno": prom_turno,
                "olas_hist": {r["ola_num"]: r["prom_ejec"] for r in olas_hist},
            }
            return {"contexto": contexto, "info": info}

    except Exception as e:
        logger.warning(f"get_historico_context error: {e}")
        return {"contexto": "", "info": {}}


# ── Schemas ───────────────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    provider: Optional[str] = None
    context: str
    turno: Optional[str] = "Tarde"
    fecha: Optional[str] = None
    ola_num: Optional[int] = 1
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
    """Analiza el estado operativo con historico y devuelve alertas + sugerencias."""
    provider = (req.provider or _active_provider()).lower()
    fecha_str = req.fecha or str(date.today())
    logger.info(f"[/api/analyze] provider={provider} turno={req.turno} fecha={fecha_str}")

    # 1. Obtener histórico de la BD
    hist = await get_historico_context(req.turno or "Tarde", fecha_str)

    # 2. Combinar contexto actual + histórico
    if hist["contexto"]:
        context_completo = f"{req.context}\n\n{hist['contexto']}"
        system = SYSTEM_ANALYZE_HIST
        logger.info(f"[/api/analyze] historico cargado: {hist['info'].get('n_dias')} dias")
    else:
        context_completo = req.context
        system = SYSTEM_ANALYZE
        logger.info("[/api/analyze] sin historico disponible, usando prompt basico")

    # 3. Cadena de proveedores: primary → fallbacks
    fallback_chain = _build_fallback_chain(provider)
    last_error = None

    for current_provider in fallback_chain:
        try:
            raw_text, model_used = await _call_ai(
                current_provider,
                system,
                [{"role": "user", "content": context_completo}],
            )
            if current_provider != provider:
                logger.info(f"[/api/analyze] usando fallback: {current_provider}")

            # 4. Extraer JSON tolerante a markdown y texto extra
            clean = _extract_json(raw_text)
            parsed = json.loads(clean)
            alerts = parsed.get("alerts", [])

            if req.turno_id:
                await _save_prediction(req.turno_id, alerts, current_provider, model_used)

            return {
                "alerts": alerts,
                "resumen_turno": parsed.get("resumen_turno", ""),
                "historico": hist["info"],
                "provider_used": current_provider,
                "model_used": model_used,
                "fallback": current_provider != provider,
            }

        except Exception as e:
            last_error = e
            logger.warning(f"[/api/analyze] {current_provider} fallo: {e}")
            continue

    logger.error(f"[/api/analyze] todos los proveedores fallaron. ultimo error: {last_error}")
    return {
        "alerts": [],
        "resumen_turno": "",
        "historico": hist.get("info", {}),
        "provider_used": provider,
        "model_used": "—",
        "error": str(last_error),
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

    for current_provider in _build_fallback_chain(provider):
        try:
            reply, model_used = await _call_ai(current_provider, system, history)
            return {
                "reply": reply,
                "provider_used": current_provider,
                "model_used": model_used,
            }
        except Exception as e:
            logger.warning(f"[/api/chat] {current_provider} fallo: {e}")
            continue

    return {
        "reply": "No se pudo consultar la IA. Intenta de nuevo en unos segundos.",
        "provider_used": provider,
        "model_used": "—",
    }


@router.get("/providers")
async def providers():
    """Lista los proveedores disponibles y cual esta activo."""
    active = _active_provider()
    return {
        "active": active,
        "available": [
            {
                "id": "gemini",
                "name": "Gemini (Google)",
                "configured": _gemini_configured(),
            },
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
            {
                "id": "ollama",
                "name": "Ollama (Local)",
                "configured": _ollama_configured(),
            },
        ],
    }


# ── Persistencia de predicciones ──────────────────────────────────────────────
async def _save_prediction(turno_id: int, alerts: list, provider: str, model: str):
    try:
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
        logger.warning(f"No se pudo persistir prediccion: {e}")
