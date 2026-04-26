"""
VigIA · Sugerencias de Plantel Operativo

V1 enfocada en dos almacenes de picking:
- SECTOR SECOS
- VARIOS NO ALIMENTOS

La lógica prioriza trazabilidad, baseline simple y explicaciones defendibles.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from statistics import mean, pstdev
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from db.schema import DB_PATH
from routers.ai import _call_ai, _extract_json
from routers.productividad_analisis import query_productive_db_plantel

logger = logging.getLogger("vigia.plantel_operativo")
router = APIRouter(prefix="/api/plantel", tags=["plantel-operativo"])

ALMACENES_VALIDOS = ["SECTOR SECOS", "VARIOS NO ALIMENTOS"]
TURN_CONFIG = {
    "manana": {"label": "Mañana", "start": time(6, 0), "end": time(14, 0)},
    "tarde": {"label": "Tarde", "start": time(14, 0), "end": time(22, 0)},
    "noche": {"label": "Noche", "start": time(22, 0), "end": time(6, 0)},
}
PLANTEL_AI_PROMPT_VERSION = "plantel-operativo-v1"
ORACLE_FETCH_TIMEOUT_SEC = float(os.getenv("PLANTEL_ORACLE_TIMEOUT_SEC", "20"))
PLANTEL_AI_TIMEOUT_SEC = float(os.getenv("PLANTEL_AI_TIMEOUT_SEC", "8"))
PLANTEL_CACHE_TTL_MINUTES = int(os.getenv("PLANTEL_CACHE_TTL_MINUTES", "360"))
PLANTEL_AI_ENABLED = os.getenv("PLANTEL_AI_ENABLED", "0").strip().lower() in {"1", "true", "yes", "si"}
PLANTEL_AI_SYSTEM = (
    "Sos un analista operativo senior de un centro de distribucion.\n"
    "Recibis una propuesta de planificacion de dotacion para picking entre dos almacenes.\n"
    "Tu trabajo es traducir el calculo a un lenguaje simple, accionable y sin vender magia.\n"
    "Responde SOLO JSON valido con esta forma:\n"
    '{"lectura_turno":"texto breve",'
    '"accion_principal":"accion breve y concreta",'
    '"alertas":["alerta 1","alerta 2"],'
    '"almacenes":[{"almacen":"...","explicacion":"..."}],'
    '"operarios":[{"operario_id":"...","explicacion":"..."}],'
    '"what_if":["idea 1","idea 2"]}\n'
    "Cada explicacion debe ser concreta y apoyarse en demanda, dotacion necesaria, brecha, experiencia o penalidades."
)


class AlmacenInput(BaseModel):
    almacen: str
    bultos_turno: float = Field(default=0, ge=0)
    lineas_turno: float = Field(default=0, ge=0)
    max_operarios: int | None = Field(default=None, ge=1, le=500)


class ScenarioWeights(BaseModel):
    capacidad: float = 0.4
    estabilidad: float = 0.15
    experiencia: float = 0.15
    recencia: float = 0.1
    criticidad: float = 0.1
    fairness: float = 0.1


class PlantelScenarioRequest(BaseModel):
    turno: str
    scenario_name: str | None = None
    almacenes: list[AlmacenInput]
    weights: ScenarioWeights | None = None
    history_days: int = Field(default=28, ge=7, le=90)
    force_refresh: bool = False


@dataclass
class TurnWindow:
    key: str
    label: str
    start_time: time
    end_time: time
    duration_hours: float
    display_range: str


def _normalize_turno(turno: str) -> str:
    raw = (turno or "").strip().lower()
    raw = (
        raw.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    if "man" in raw:
        return "manana"
    if "tar" in raw:
        return "tarde"
    if "noc" in raw:
        return "noche"
    raise HTTPException(status_code=400, detail=f"Turno no reconocido: {turno}")


def _turn_window(turno: str) -> TurnWindow:
    key = _normalize_turno(turno)
    cfg = TURN_CONFIG[key]
    start_minutes = cfg["start"].hour * 60 + cfg["start"].minute
    end_minutes = cfg["end"].hour * 60 + cfg["end"].minute
    duration = (end_minutes - start_minutes) / 60 if end_minutes > start_minutes else ((24 * 60 - start_minutes) + end_minutes) / 60
    return TurnWindow(
        key=key,
        label=cfg["label"],
        start_time=cfg["start"],
        end_time=cfg["end"],
        duration_hours=duration,
        display_range=f"{cfg['start'].strftime('%H:%M')} - {cfg['end'].strftime('%H:%M')}",
    )


def _time_in_shift(dt: datetime, window: TurnWindow) -> bool:
    current = dt.time()
    if window.start_time <= window.end_time:
        return window.start_time <= current < window.end_time
    return current >= window.start_time or current < window.end_time


def _infer_turno_key_from_dt(dt: datetime) -> str:
    current = dt.time()
    if TURN_CONFIG["manana"]["start"] <= current < TURN_CONFIG["manana"]["end"]:
        return "manana"
    if TURN_CONFIG["tarde"]["start"] <= current < TURN_CONFIG["tarde"]["end"]:
        return "tarde"
    return "noche"


def _serialize_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _safe_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


async def _load_turns_from_db() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT MAX(fecha) AS fecha FROM historico_olas")
        row = await cursor.fetchone()
        latest_fecha = row["fecha"] if row else None
        if not latest_fecha:
            return [
                {"turno_key": "tarde", "turno_label": "Tarde", "hora_inicio": "14:00", "hora_fin": "22:00"},
                {"turno_key": "noche", "turno_label": "Noche", "hora_inicio": "22:00", "hora_fin": "06:00"},
                {"turno_key": "manana", "turno_label": "Mañana", "hora_inicio": "06:00", "hora_fin": "14:00"},
            ]

        cursor = await db.execute(
            """
            SELECT turno, MIN(hora_ini) AS hora_inicio, MAX(hora_fin) AS hora_fin
            FROM historico_olas
            WHERE fecha = ?
            GROUP BY turno
            ORDER BY MIN(ola_num)
            """,
            (latest_fecha,),
        )
        rows = await cursor.fetchall()

    turnos = []
    for row in rows:
        key = _normalize_turno(row["turno"])
        turnos.append(
            {
                "turno_key": key,
                "turno_label": TURN_CONFIG[key]["label"],
                "hora_inicio": str(row["hora_inicio"])[:5],
                "hora_fin": str(row["hora_fin"])[:5],
            }
        )
    return turnos


def _history_range(days: int) -> tuple[str, str]:
    now = datetime.now()
    start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def _fallback_local_mapping(sector: str) -> str:
    text = (sector or "").strip().upper()
    if "NOA" in text or "NO AL" in text:
        return "VARIOS NO ALIMENTOS"
    return "SECTOR SECOS"


async def _load_local_history(window: TurnWindow, days: int) -> tuple[list[dict[str, Any]], str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                fecha,
                fh_movimiento AS FHMovimiento,
                operario_id AS Operario,
                COALESCE(operario_nombre, operario_id) AS OperarioNombre,
                cantidad AS Cantidad,
                zona_origen AS ZonaOrigen,
                almacen AS Almacen,
                peso_registrado AS PesoRegistrado,
                nro_pallet AS NroPallet
            FROM plantel_movimientos_hist
            WHERE turno_key = ?
              AND fecha >= DATE('now', '-' || ? || ' days')
            ORDER BY fh_movimiento
            """,
            (window.key, days),
        )
        hist_rows = [dict(row) for row in await cursor.fetchall()]
    if hist_rows:
        normalized = []
        for row in hist_rows:
            normalized.append(
                {
                    "FHMOVIMIENTO": str(row.get("FHMovimiento") or ""),
                    "OPERARIO": str(row.get("Operario") or "").strip(),
                    "OPERARIONOMBRE": str(row.get("OperarioNombre") or row.get("Operario") or "").strip(),
                    "CANTIDAD": _safe_float(row.get("Cantidad")),
                    "ZONAORIGEN": str(row.get("ZonaOrigen") or "").strip(),
                    "ALMACEN": str(row.get("Almacen") or "").strip(),
                    "PESOREGISTRADO": _safe_float(row.get("PesoRegistrado")),
                    "NROPALLET": str(row.get("NroPallet") or "").strip(),
                    "SYNTHETIC_TS": False,
                }
            )
        return normalized, "sqlite_plantel_hist"

    start_dt = (datetime.now() - timedelta(days=days)).date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                p.fecha AS fecha,
                p.timestamp AS FHMovimiento,
                p.turno_id AS TurnoId,
                p.operario_id AS Operario,
                COALESCE(o.nombre, p.operario_id) AS OperarioNombre,
                p.cantidad_bultos AS Cantidad,
                p.sector AS ZonaOrigen
            FROM picks_operario p
            LEFT JOIN operarios o ON o.operario_id = p.operario_id
            WHERE p.fecha >= ?
              AND p.estado = 'completado'
            ORDER BY p.timestamp
            """,
            (start_dt,),
        )
        rows = [dict(row) for row in await cursor.fetchall()]

    normalized = []
    for row in rows:
        fh = _parse_dt(row.get("FHMOVIMIENTO"))
        turno_id = str(row.get("TurnoId") or "").lower()
        turno_matches = window.key in turno_id
        if not fh and turno_matches:
            fh = datetime.combine(
                datetime.fromisoformat(str(row.get("fecha"))).date(),
                window.start_time,
            )
        if not fh and not turno_matches:
            continue
        if fh and not _time_in_shift(fh, window) and not turno_matches:
            continue
        normalized.append(
            {
                "FHMOVIMIENTO": fh.strftime("%Y-%m-%d %H:%M:%S"),
                "OPERARIO": str(row.get("Operario") or "").strip(),
                "OPERARIONOMBRE": str(row.get("OperarioNombre") or row.get("Operario") or "").strip(),
                "CANTIDAD": _safe_float(row.get("Cantidad")),
                "ZONAORIGEN": str(row.get("ZonaOrigen") or "").strip(),
                "ALMACEN": _fallback_local_mapping(str(row.get("ZonaOrigen") or "").strip()),
                "PESOREGISTRADO": 0,
                "NROPALLET": "",
                "SYNTHETIC_TS": not bool(row.get("FHMOVIMIENTO")),
            }
        )
    return normalized, "sqlite_local"


async def _has_plantel_hist_data(window: TurnWindow, days: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT 1
            FROM plantel_movimientos_hist
            WHERE turno_key = ?
              AND fecha >= DATE('now', '-' || ? || ' days')
            LIMIT 1
            """,
            (window.key, days),
        )
        row = await cursor.fetchone()
    return bool(row)


async def _load_history(window: TurnWindow, days: int) -> tuple[list[dict[str, Any]], str]:
    if await _has_plantel_hist_data(window, days):
        local_rows, source_name = await _load_local_history(window, days)
        logger.info("[plantel] Usando historico local materializado: %s filas", len(local_rows))
        return local_rows, source_name

    fecha_desde, fecha_hasta = _history_range(days)
    try:
        logger.info(
            "[plantel] Consultando Oracle para turno=%s rango=%s..%s",
            window.label,
            fecha_desde,
            fecha_hasta,
        )
        rows = await asyncio.wait_for(
            asyncio.to_thread(query_productive_db_plantel, fecha_desde, fecha_hasta),
            timeout=ORACLE_FETCH_TIMEOUT_SEC,
        )
        logger.info("[plantel] Oracle OK: %s filas", len(rows))
        return rows, "oracle_productiva"
    except Exception as exc:
        logger.warning("[plantel] Oracle no disponible, usando fallback local: %s", exc)
        local_rows, source_name = await _load_local_history(window, days)
        logger.info("[plantel] Fallback local OK: %s filas", len(local_rows))
        return local_rows, source_name


async def _load_cached_profiles(turno_key: str, history_days: int) -> tuple[list[dict[str, Any]], dict[str, Any], str] | None:
    freshness_limit = (datetime.now() - timedelta(minutes=PLANTEL_CACHE_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT source_name, payload_json
            FROM plantel_history_cache
            WHERE turno_key = ?
              AND history_days = ?
              AND updated_at >= ?
            ORDER BY CASE source_name
                WHEN 'sqlite_plantel_hist' THEN 0
                WHEN 'oracle_productiva' THEN 1
                WHEN 'sqlite_local' THEN 2
                ELSE 3
            END, updated_at DESC
            LIMIT 1
            """,
            (turno_key, history_days, freshness_limit),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    return payload.get("profiles", []), payload.get("metadata", {}), row["source_name"]


async def _save_cached_profiles(
    turno_key: str,
    history_days: int,
    source_name: str,
    profiles: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO plantel_history_cache (
                turno_key, history_days, source_name, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(turno_key, history_days, source_name) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                turno_key,
                history_days,
                source_name,
                _serialize_json({"profiles": profiles, "metadata": metadata}),
            ),
        )
        await db.commit()


def _build_operator_profiles(
    rows: list[dict[str, Any]],
    window: TurnWindow,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_by_operator: dict[str, list[dict[str, Any]]] = defaultdict(list)
    operator_names: dict[str, str] = {}
    per_operator_store_daily: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    per_store_daily: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    store_totals: dict[str, float] = defaultdict(float)
    total_rows = 0

    for row in rows:
        fh = _parse_dt(row.get("FHMOVIMIENTO"))
        if not fh or not _time_in_shift(fh, window):
            continue
        almacen = str(row.get("ALMACEN") or "").strip().upper()
        if almacen not in ALMACENES_VALIDOS:
            continue
        operario = str(row.get("OPERARIO") or "").strip()
        if not operario:
            continue
        cantidad = max(_safe_float(row.get("CANTIDAD")), 0.0)
        zona = str(row.get("ZONAORIGEN") or "").strip()
        nombre = str(row.get("OPERARIONOMBRE") or operario).strip() or operario
        operator_names[operario] = nombre
        total_rows += 1
        synthetic = bool(row.get("SYNTHETIC_TS"))
        rows_by_operator[operario].append({"fh": fh, "cantidad": cantidad, "almacen": almacen, "zona": zona, "synthetic": synthetic})
        store_totals[almacen] += cantidad

        day_key = fh.date().isoformat()
        store_day = per_operator_store_daily[operario][almacen].setdefault(
            day_key,
            {"bultos": 0.0, "first": fh, "last": fh, "movimientos": 0, "synthetic": False},
        )
        store_day["bultos"] += cantidad
        store_day["movimientos"] += 1
        store_day["synthetic"] = store_day["synthetic"] or synthetic
        if fh < store_day["first"]:
            store_day["first"] = fh
        if fh > store_day["last"]:
            store_day["last"] = fh

        store_daily = per_store_daily[almacen].setdefault(
            day_key,
            {"bultos": 0.0, "operarios": set()},
        )
        store_daily["bultos"] += cantidad
        store_daily["operarios"].add(operario)

    profiles = []
    capacity_candidates = []

    for operario, op_rows in rows_by_operator.items():
        global_days: dict[str, dict[str, Any]] = {}
        for item in op_rows:
            day_key = item["fh"].date().isoformat()
            day_data = global_days.setdefault(day_key, {"bultos": 0.0, "first": item["fh"], "last": item["fh"], "synthetic": False})
            day_data["bultos"] += item["cantidad"]
            day_data["synthetic"] = day_data["synthetic"] or item.get("synthetic", False)
            if item["fh"] < day_data["first"]:
                day_data["first"] = item["fh"]
            if item["fh"] > day_data["last"]:
                day_data["last"] = item["fh"]

        total_bultos = sum(item["cantidad"] for item in op_rows)
        total_hours = 0.0
        for day_data in global_days.values():
            span_hours = window.duration_hours if day_data.get("synthetic") else max((day_data["last"] - day_data["first"]).total_seconds() / 3600, 1.0)
            total_hours += min(max(span_hours, 1.0), window.duration_hours)
        global_hourly = total_bultos / total_hours if total_hours > 0 else 0.0

        stores = {}
        dominant_store = None
        dominant_share = 0.0
        recent_cut = datetime.now().date() - timedelta(days=14)

        for almacen in ALMACENES_VALIDOS:
            day_map = per_operator_store_daily[operario].get(almacen, {})
            day_items = list(day_map.values())
            bultos_total = sum(item["bultos"] for item in day_items)
            hours_total = sum(
                min(
                    max(window.duration_hours if item.get("synthetic") else (item["last"] - item["first"]).total_seconds() / 3600, 1.0),
                    window.duration_hours,
                )
                for item in day_items
            )
            hourly = bultos_total / hours_total if hours_total > 0 else 0.0
            daily_rates = [
                item["bultos"] / min(
                    max(window.duration_hours if item.get("synthetic") else (item["last"] - item["first"]).total_seconds() / 3600, 1.0),
                    window.duration_hours,
                )
                for item in day_items
                if item["bultos"] > 0
            ]
            variability = 0.35
            if len(daily_rates) >= 2:
                avg_daily = mean(daily_rates)
                variability = min(pstdev(daily_rates) / avg_daily, 1.5) if avg_daily > 0 else 1.0
            recent_days = sum(1 for key in day_map if datetime.fromisoformat(key).date() >= recent_cut)
            share = bultos_total / total_bultos if total_bultos > 0 else 0.0
            if share > dominant_share:
                dominant_store = almacen
                dominant_share = share
            stores[almacen] = {
                "bultos_total": round(bultos_total, 2),
                "days_count": len(day_items),
                "hours_total": round(hours_total, 2),
                "hourly_capacity": round(hourly, 2),
                "turn_capacity": round(hourly * window.duration_hours, 2),
                "variability_cv": round(variability, 3),
                "recent_days": recent_days,
                "share": round(share, 3),
                "has_history": bultos_total > 0 and len(day_items) > 0,
            }
            capacity_candidates.append(stores[almacen]["turn_capacity"])

        profiles.append(
            {
                "operario_id": operario,
                "operario_nombre": operator_names.get(operario, operario),
                "total_bultos": round(total_bultos, 2),
                "total_hours": round(total_hours, 2),
                "global_hourly_capacity": round(global_hourly, 2),
                "global_turn_capacity": round(global_hourly * window.duration_hours, 2),
                "days_count": len(global_days),
                "almacenes_trabajados": sum(1 for store in stores.values() if store["has_history"]),
                "dominant_store": dominant_store,
                "dominant_share": round(dominant_share, 3),
                "stores": stores,
            }
        )

    profiles.sort(key=lambda item: (item["global_turn_capacity"], item["total_bultos"]), reverse=True)
    profile_by_id = {item["operario_id"]: item for item in profiles}
    store_projection: dict[str, dict[str, Any]] = {}
    for almacen in ALMACENES_VALIDOS:
        day_map = per_store_daily.get(almacen, {})
        bultos_por_persona_samples: list[float] = []
        realized_factor_samples: list[float] = []
        avg_modeled_samples: list[float] = []
        dotacion_samples: list[int] = []
        for day_data in day_map.values():
            operarios = sorted(day_data.get("operarios", set()))
            headcount = len(operarios)
            if headcount <= 0:
                continue
            actual_team_bultos = float(day_data.get("bultos") or 0.0)
            actual_bultos_por_persona = actual_team_bultos / headcount
            modeled_capacities = []
            for operario in operarios:
                profile = profile_by_id.get(operario)
                if not profile:
                    continue
                store = profile["stores"].get(almacen, {})
                modeled_capacities.append(
                    float(store.get("turn_capacity") or profile.get("global_turn_capacity") or 0.0)
                )
            avg_modeled = mean(modeled_capacities) if modeled_capacities else 0.0
            team_modeled = sum(modeled_capacities)
            bultos_por_persona_samples.append(actual_bultos_por_persona)
            dotacion_samples.append(headcount)
            if avg_modeled > 0:
                avg_modeled_samples.append(avg_modeled)
            if team_modeled > 0:
                realized_factor_samples.append(actual_team_bultos / team_modeled)

        store_projection[almacen] = {
            "avg_bultos_por_persona_turno": round(mean(bultos_por_persona_samples), 2) if bultos_por_persona_samples else 0.0,
            "avg_modeled_por_persona_turno": round(mean(avg_modeled_samples), 2) if avg_modeled_samples else 0.0,
            "realization_factor": round(mean(realized_factor_samples), 3) if realized_factor_samples else 1.0,
            "avg_dotacion_historica": round(mean(dotacion_samples), 1) if dotacion_samples else 0.0,
            "days_sampled": len(bultos_por_persona_samples),
        }
    metadata = {
        "eligible_count": len(profiles),
        "rows_used": total_rows,
        "store_totals": {key: round(value, 2) for key, value in store_totals.items()},
        "max_turn_capacity": max(capacity_candidates) if capacity_candidates else 1.0,
        "avg_turn_capacity": mean(capacity_candidates) if capacity_candidates else 0.0,
        "store_projection": store_projection,
    }
    return profiles, metadata


def _demand_map(almacenes: list[AlmacenInput]) -> dict[str, dict[str, float]]:
    data: dict[str, dict[str, float]] = {}
    for item in almacenes:
        if item.almacen not in ALMACENES_VALIDOS:
            raise HTTPException(status_code=400, detail=f"Almacén no permitido: {item.almacen}")
        data[item.almacen] = {
            "bultos_turno": float(item.bultos_turno),
            "lineas_turno": float(item.lineas_turno),
            "max_operarios": int(item.max_operarios) if item.max_operarios else None,
        }
    for almacen in ALMACENES_VALIDOS:
        data.setdefault(almacen, {"bultos_turno": 0.0, "lineas_turno": 0.0, "max_operarios": None})
    return data


def _operator_store_score(
    profile: dict[str, Any],
    almacen: str,
    demand_share: float,
    weights: ScenarioWeights,
    max_turn_capacity: float,
    avg_turn_capacity: float,
) -> dict[str, Any]:
    store = profile["stores"][almacen]
    has_history = store["has_history"]
    base_turn_capacity = store["turn_capacity"] if has_history else max(profile["global_turn_capacity"] * 0.65, avg_turn_capacity * 0.55)
    stability = 1.0 - min(store["variability_cv"], 1.0) if has_history else 0.45
    experience = min(store["days_count"] / 8, 1.0) if has_history else 0.2
    recency = min(store["recent_days"] / 6, 1.0) if has_history else 0.15
    concentration_penalty = 0.0
    if profile["dominant_store"] == almacen and profile["almacenes_trabajados"] > 1:
        concentration_penalty = max(profile["dominant_share"] - 0.55, 0) * 0.5
    fairness = max(0.0, 1.0 - concentration_penalty)
    penalty = 0.0 if has_history else 0.28

    normalized_capacity = min(base_turn_capacity / max(max_turn_capacity, 1.0), 1.0)
    total_score = 100 * (
        normalized_capacity * weights.capacidad
        + stability * weights.estabilidad
        + experience * weights.experiencia
        + recency * weights.recencia
        + demand_share * weights.criticidad
        + fairness * weights.fairness
        - penalty
    )

    if has_history:
        if store["recent_days"] >= 3:
            reason = f"Mandarlo a {almacen}: viene trabajando bien ahí en las últimas jornadas."
        else:
            reason = f"Mandarlo a {almacen}: ya trabajó ahí y puede dar una buena mano en este turno."
    else:
        reason = f"Puede ir a {almacen}, pero con cuidado: casi no tiene experiencia ahí."

    return {
        "score": round(total_score, 2),
        "turn_capacity": round(base_turn_capacity, 2),
        "hourly_capacity": round(base_turn_capacity / 8, 2),
        "stability": round(stability, 3),
        "experience": round(experience, 3),
        "recency": round(recency, 3),
        "fairness": round(fairness, 3),
        "penalty": round(penalty + concentration_penalty, 3),
        "has_history": has_history,
        "reason": reason,
    }


def _plan_headcounts(
    demand: dict[str, dict[str, float]],
    total_available: int,
    store_projection: dict[str, dict[str, Any]] | None,
    avg_turn_capacity: float,
) -> dict[str, Any]:
    positive = [alm for alm, vals in demand.items() if vals["bultos_turno"] > 0]
    caps = {
        almacen: (
            int(demand[almacen]["max_operarios"])
            if demand[almacen].get("max_operarios") is not None
            else total_available
        )
        for almacen in ALMACENES_VALIDOS
    }
    required = {alm: 0 for alm in ALMACENES_VALIDOS}
    capacity_per_person = {alm: 0.0 for alm in ALMACENES_VALIDOS}
    sample_days = {alm: 0 for alm in ALMACENES_VALIDOS}
    for almacen in positive:
        projection_cfg = (store_projection or {}).get(almacen, {})
        per_person_turn = float(projection_cfg.get("avg_bultos_por_persona_turno") or 0.0)
        if per_person_turn <= 0:
            per_person_turn = max(avg_turn_capacity, 1.0)
        capacity_per_person[almacen] = round(per_person_turn, 2)
        sample_days[almacen] = int(projection_cfg.get("days_sampled") or 0)
        needed = max(1, math.ceil(demand[almacen]["bultos_turno"] / max(per_person_turn, 1.0)))
        required[almacen] = needed

    total_required = sum(required.values())
    total_capacity_slots = sum(caps.get(alm, total_available) for alm in positive) if positive else total_available
    assignable_total = min(total_available, total_required, total_capacity_slots)
    suggested = {alm: 0 for alm in ALMACENES_VALIDOS}
    if assignable_total > 0 and positive:
        base_assigned = 0
        for almacen in positive:
            if caps.get(almacen, total_available) <= 0:
                continue
            suggested[almacen] = min(required[almacen], 1, caps.get(almacen, total_available))
            base_assigned += suggested[almacen]
        remaining = max(assignable_total - base_assigned, 0)
        remainders = []
        total_required_weight = sum(required[alm] for alm in positive) or 1
        for almacen in positive:
            room = max(min(required[almacen], caps.get(almacen, total_available)) - suggested[almacen], 0)
            if room <= 0:
                continue
            exact = remaining * (required[almacen] / total_required_weight)
            floor_val = min(math.floor(exact), room)
            suggested[almacen] += floor_val
            remainders.append((exact - math.floor(exact), almacen))
        assigned = sum(suggested.values())
        for _, almacen in sorted(remainders, reverse=True):
            if assigned >= assignable_total:
                break
            room = max(min(required[almacen], caps.get(almacen, total_available)) - suggested[almacen], 0)
            if room <= 0:
                continue
            suggested[almacen] += 1
            assigned += 1
        if assigned < assignable_total:
            for almacen in sorted(positive, key=lambda alm: demand[alm]["bultos_turno"], reverse=True):
                room = max(min(required[almacen], caps.get(almacen, total_available)) - suggested[almacen], 0)
                if room <= 0:
                    continue
                add = min(room, assignable_total - assigned)
                suggested[almacen] += add
                assigned += add
                if assigned >= assignable_total:
                    break

    shortage = {alm: max(required[alm] - suggested[alm], 0) for alm in ALMACENES_VALIDOS}
    return {
        "required": required,
        "suggested": suggested,
        "shortage": shortage,
        "capacity_per_person": capacity_per_person,
        "sample_days": sample_days,
        "total_required": total_required,
        "total_suggested": sum(suggested.values()),
        "total_shortage": max(total_required - sum(suggested.values()), 0),
        "total_available": total_available,
    }


def _build_assignment(
    profiles: list[dict[str, Any]],
    demand: dict[str, dict[str, float]],
    target_headcounts: dict[str, int],
    weights: ScenarioWeights,
    mode: str,
    duration_hours: float,
    max_turn_capacity: float,
    avg_turn_capacity: float,
    store_projection: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    total_bultos = sum(vals["bultos_turno"] for vals in demand.values()) or 1
    demand_share = {
        almacen: (vals["bultos_turno"] / total_bultos) if total_bultos > 0 else 0.0
        for almacen, vals in demand.items()
    }
    targets = {alm: int(target_headcounts.get(alm, 0)) for alm in ALMACENES_VALIDOS}
    target_total = sum(targets.values())
    assignments = []
    grouped: dict[str, list[dict[str, Any]]] = {almacen: [] for almacen in ALMACENES_VALIDOS}
    unassigned = list(profiles)

    def score_profile(profile: dict[str, Any], almacen: str) -> dict[str, Any]:
        detail = _operator_store_score(profile, almacen, demand_share[almacen], weights, max_turn_capacity, avg_turn_capacity)
        if mode == "baseline":
            detail["score"] = round(profile["global_turn_capacity"], 2)
            detail["reason"] = "Reparto simple de gente, sin mirar dónde rindió mejor cada uno."
        return detail

    for almacen in ALMACENES_VALIDOS:
        if targets[almacen] <= 0:
            continue
        best_profile = None
        best_detail = None
        for profile in unassigned:
            detail = score_profile(profile, almacen)
            candidate_score = detail["score"] if mode == "ideal" else detail["turn_capacity"]
            if best_profile is None or candidate_score > (best_detail["score"] if mode == "ideal" else best_detail["turn_capacity"]):
                best_profile = profile
                best_detail = detail
        if best_profile is None:
            continue
        grouped[almacen].append({"profile": best_profile, "detail": best_detail})
        unassigned.remove(best_profile)

    while unassigned and sum(len(items) for items in grouped.values()) < target_total:
        profile = unassigned.pop(0) if mode == "baseline" else max(unassigned, key=lambda item: item["global_turn_capacity"])
        if mode == "ideal":
            unassigned.remove(profile)
        candidate_almacenes = [
            alm for alm in ALMACENES_VALIDOS
            if demand[alm]["bultos_turno"] > 0 and len(grouped[alm]) < targets.get(alm, 0)
        ] or [
            alm for alm in ALMACENES_VALIDOS
            if len(grouped[alm]) < targets.get(alm, 0)
        ]
        if not candidate_almacenes:
            break
        best_almacen = None
        best_detail = None
        best_value = None
        for almacen in candidate_almacenes:
            detail = score_profile(profile, almacen)
            current_capacity = sum(item["detail"]["turn_capacity"] for item in grouped[almacen])
            remaining_gap = demand[almacen]["bultos_turno"] - current_capacity
            urgency = (remaining_gap / max(demand[almacen]["bultos_turno"], 1)) if demand[almacen]["bultos_turno"] > 0 else -1
            headcount_gap = targets[almacen] - len(grouped[almacen])
            value = (
                detail["score"] + max(urgency, -0.5) * 20 + max(headcount_gap, -2) * 15
                if mode == "ideal"
                else (targets[almacen] - len(grouped[almacen]), detail["turn_capacity"])
            )
            if best_almacen is None or value > best_value:
                best_almacen = almacen
                best_detail = detail
                best_value = value
        grouped[best_almacen].append({"profile": profile, "detail": best_detail})

    summaries = []
    for almacen in ALMACENES_VALIDOS:
        members = grouped[almacen]
        raw_hourly_capacity = sum(item["detail"]["hourly_capacity"] for item in members)
        raw_turn_capacity = sum(item["detail"]["turn_capacity"] for item in members)
        projection_cfg = (store_projection or {}).get(almacen, {})
        comparable_per_person_turn = float(projection_cfg.get("avg_bultos_por_persona_turno") or 0.0)
        comparable_team_turn = comparable_per_person_turn * len(members)
        historical_avg_modeled = float(projection_cfg.get("avg_modeled_por_persona_turno") or 0.0)
        assigned_avg_modeled = (raw_turn_capacity / len(members)) if members else 0.0
        if comparable_per_person_turn > 0 and historical_avg_modeled > 0 and assigned_avg_modeled > 0:
            quality_factor = assigned_avg_modeled / historical_avg_modeled
            quality_factor = min(max(quality_factor, 0.85), 1.15)
            projected_turn_capacity = comparable_team_turn * quality_factor
        elif comparable_team_turn > 0:
            projected_turn_capacity = comparable_team_turn
        else:
            realization_factor = float(projection_cfg.get("realization_factor") or 1.0)
            projected_turn_capacity = raw_turn_capacity * min(max(realization_factor, 0.45), 1.0)
        turn_capacity = round(projected_turn_capacity, 2)
        hourly_capacity = round((turn_capacity / duration_hours), 2) if duration_hours > 0 else round(raw_hourly_capacity, 2)
        demand_bultos = demand[almacen]["bultos_turno"]
        coverage = (turn_capacity / demand_bultos * 100) if demand_bultos > 0 else 100.0
        finish_hours = (demand_bultos / hourly_capacity) if hourly_capacity > 0 else 0
        risk = "bajo" if coverage >= 105 else "medio" if coverage >= 90 else "alto"
        summaries.append(
            {
                "almacen": almacen,
                "bultos_turno": round(demand_bultos, 2),
                "lineas_turno": round(demand[almacen]["lineas_turno"], 2),
                "dotacion": len(members),
                "productividad_grupal_hora": round(hourly_capacity, 2),
                "capacidad_equipo": round(turn_capacity, 2),
                "capacidad_modelada_equipo": round(raw_turn_capacity, 2),
                "cobertura_pct": round(coverage, 1),
                "horas_estimadas": round(finish_hours, 2),
                "riesgo": risk,
                "projection_days_sampled": int(projection_cfg.get("days_sampled") or 0),
            }
        )

        for item in members:
            assignments.append(
                {
                    "operario_id": item["profile"]["operario_id"],
                    "operario_nombre": item["profile"]["operario_nombre"],
                    "almacen": almacen,
                    "score": item["detail"]["score"],
                    "capacidad_estimada": item["detail"]["turn_capacity"],
                    "penalizacion": item["detail"]["penalty"],
                    "motivo_principal": item["detail"]["reason"],
                    "has_history": item["detail"]["has_history"],
                    "detalle": item["detail"],
                }
            )

    summary_by_store = {item["almacen"]: item for item in summaries}
    return {
        "assignments": assignments,
        "summary_by_store": summary_by_store,
    }


def _finish_time_label(window: TurnWindow, hours_needed: float) -> str:
    base = datetime.combine(datetime.now().date(), window.start_time)
    finish = base + timedelta(hours=max(hours_needed, 0))
    if window.key == "noche" and finish.time() < window.start_time:
        return finish.strftime("%H:%M (+1)")
    return finish.strftime("%H:%M")


def _build_response_payload(
    scenario_id: int | None,
    request: PlantelScenarioRequest,
    window: TurnWindow,
    source_name: str,
    profiles: list[dict[str, Any]],
    headcount_plan: dict[str, Any],
    ideal: dict[str, Any],
    baseline: dict[str, Any],
    metadata: dict[str, Any],
    ia_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    ideal_store = ideal["summary_by_store"]
    baseline_store = baseline["summary_by_store"]
    resumen_almacenes = []
    for almacen in ALMACENES_VALIDOS:
        ideal_item = ideal_store.get(almacen, {})
        base_item = baseline_store.get(almacen, {})
        resumen_almacenes.append(
            {
                "almacen": almacen,
                "bultos_turno": ideal_item.get("bultos_turno", 0),
                "lineas_turno": ideal_item.get("lineas_turno", 0),
                "personas_necesarias": int(headcount_plan.get("required", {}).get(almacen, 0)),
                "dotacion_sugerida": ideal_item.get("dotacion", 0),
                "faltante_personas": int(headcount_plan.get("shortage", {}).get(almacen, 0)),
                "capacidad_por_persona_historica": headcount_plan.get("capacity_per_person", {}).get(almacen, 0),
                "capacidad_equipo": ideal_item.get("capacidad_equipo", 0),
                "capacidad_modelada_equipo": ideal_item.get("capacidad_modelada_equipo", 0),
                "productividad_grupal_hora": ideal_item.get("productividad_grupal_hora", 0),
                "hora_fin_estimada": _finish_time_label(window, ideal_item.get("horas_estimadas", 0)),
                "cobertura_pct": ideal_item.get("cobertura_pct", 0),
                "riesgo": ideal_item.get("riesgo", "medio"),
                "projection_days_sampled": int(headcount_plan.get("sample_days", {}).get(almacen, 0)),
                "baseline_dotacion": base_item.get("dotacion", 0),
                "baseline_capacidad": base_item.get("capacidad_equipo", 0),
                "baseline_hora_fin_estimada": _finish_time_label(window, base_item.get("horas_estimadas", 0)),
                "baseline_cobertura_pct": base_item.get("cobertura_pct", 0),
            }
        )

    ideal_total_capacity = sum(item["capacidad_equipo"] for item in resumen_almacenes)
    baseline_total_capacity = sum(item["baseline_capacidad"] for item in resumen_almacenes)
    demand_total = sum(item["bultos_turno"] for item in resumen_almacenes)
    operarios_asignados = sum(item["dotacion_sugerida"] for item in resumen_almacenes)
    resumen = {
        "scenario_id": scenario_id,
        "scenario_name": request.scenario_name or f"Escenario {window.label}",
        "turno": window.label,
        "turno_key": window.key,
        "rango_horario": window.display_range,
        "source_name": source_name,
        "operarios_elegibles": len(profiles),
        "operarios_asignados": operarios_asignados,
        "personas_necesarias_total": int(headcount_plan.get("total_required", 0)),
        "personas_disponibles_turno": int(headcount_plan.get("total_available", len(profiles))),
        "personas_planificadas_total": int(headcount_plan.get("total_suggested", operarios_asignados)),
        "brecha_personas": int(headcount_plan.get("total_shortage", 0)),
        "demanda_total_bultos": round(demand_total, 2),
        "capacidad_total_sugerida": round(ideal_total_capacity, 2),
        "capacidad_total_baseline": round(baseline_total_capacity, 2),
        "mejora_capacidad_pct": round(((ideal_total_capacity - baseline_total_capacity) / baseline_total_capacity) * 100, 1) if baseline_total_capacity > 0 else 0.0,
        "rows_used": metadata.get("rows_used", 0),
        "projection_basis": "La dotación necesaria se estima con bultos reales de jornadas comparables del mismo turno y almacén. Después se arma el mejor equipo posible con la gente que ya trabajó en ese turno.",
    }

    store_explanations = {item["almacen"]: item.get("explicacion") for item in (ia_payload or {}).get("almacenes", [])}
    operator_explanations = {item["operario_id"]: item.get("explicacion") for item in (ia_payload or {}).get("operarios", [])}
    suggested_assignments = []
    for item in ideal["assignments"]:
        suggested_assignments.append(
            {
                "operario_id": item["operario_id"],
                "operario_nombre": item["operario_nombre"],
                "almacen": item["almacen"],
                "score": item["score"],
                "capacidad_estimada": item["capacidad_estimada"],
                "penalizacion": item["penalizacion"],
                "motivo_principal": item["motivo_principal"],
                "explicacion_ia": operator_explanations.get(item["operario_id"]) or item["motivo_principal"],
            }
        )

    return {
        "summary": resumen,
        "almacenes": resumen_almacenes,
        "suggested_assignments": suggested_assignments,
        "baseline_assignments": baseline["assignments"],
        "explanations": {
            "summary": (ia_payload or {}).get("lectura_turno") or "La idea es decir cuánta gente hace falta y mostrar con quién conviene cubrir ese trabajo.",
            "accion_principal": (ia_payload or {}).get("accion_principal") or "Revisar la brecha del turno y cubrir primero el almacén que más gente necesita.",
            "alertas": (ia_payload or {}).get("alertas") or [
                "La necesidad de gente sale de jornadas comparables del mismo turno.",
                "Si falta gente, conviene cubrir primero el almacén con más trabajo cargado.",
            ],
            "almacenes": [
                {
                    "almacen": almacen,
                    "explicacion": store_explanations.get(almacen)
                    or f"En {almacen} se calcula cuánta gente hace falta según bultos reales de jornadas parecidas y después se arma el mejor equipo disponible.",
                }
                for almacen in ALMACENES_VALIDOS
            ],
            "operarios": [
                {
                    "operario_id": item["operario_id"],
                    "operario_nombre": item["operario_nombre"],
                    "explicacion": operator_explanations.get(item["operario_id"]) or item["motivo_principal"],
                }
                for item in suggested_assignments
            ],
            "what_if": (ia_payload or {}).get("what_if") or [
                "Probar qué pasa si entra más trabajo en SECTOR SECOS.",
                "Probar qué pasa si movés gente de un almacén al otro.",
            ],
        },
    }


async def _generate_ai_explanation(response_payload: dict[str, Any]) -> dict[str, Any]:
    provider = os.getenv("AI_PROVIDER", "claude").lower()
    if not PLANTEL_AI_ENABLED:
        return {
            "lectura_turno": "El cálculo estima cuánta gente hace falta en cada almacén y arma el mejor equipo posible con la gente que ya conoce ese turno.",
            "accion_principal": "Cubrir primero el almacén con más brecha entre gente necesaria y gente planificada.",
            "alertas": [
                "La necesidad sale de jornadas parecidas del mismo turno y almacén.",
                "Si falta gente, el riesgo no está solo en repartir mal sino en no llegar con la dotación.",
            ],
            "almacenes": [
                {
                    "almacen": item["almacen"],
                    "explicacion": f"En {item['almacen']} se calcula una necesidad de gente según bultos reales de jornadas parecidas y se arma el mejor plantel disponible."
                }
                for item in response_payload["almacenes"]
            ],
            "operarios": [
                {
                    "operario_id": item["operario_id"],
                    "explicacion": item["motivo_principal"],
                }
                for item in response_payload["suggested_assignments"][:10]
            ],
            "what_if": [
                "Probar qué pasa si entra más trabajo en VARIOS NO ALIMENTOS.",
                "Probar qué pasa si pasás gente de un almacén al otro.",
            ],
            "provider": "disabled",
            "model_used": "disabled-local",
        }
    prompt_payload = {
        "turno": response_payload["summary"]["turno"],
        "rango_horario": response_payload["summary"]["rango_horario"],
        "source_name": response_payload["summary"]["source_name"],
        "personas_necesarias_total": response_payload["summary"]["personas_necesarias_total"],
        "personas_disponibles_turno": response_payload["summary"]["personas_disponibles_turno"],
        "brecha_personas": response_payload["summary"]["brecha_personas"],
        "demanda_total_bultos": response_payload["summary"]["demanda_total_bultos"],
        "almacenes": response_payload["almacenes"],
        "suggested_assignments": response_payload["suggested_assignments"][:8],
    }
    try:
        raw_text, model_used = await asyncio.wait_for(
            _call_ai(
                provider,
                PLANTEL_AI_SYSTEM,
                [{"role": "user", "content": _serialize_json(prompt_payload)}],
            ),
            timeout=PLANTEL_AI_TIMEOUT_SEC,
        )
        parsed = json.loads(_extract_json(raw_text))
        parsed["provider"] = provider
        parsed["model_used"] = model_used
        return parsed
    except Exception as exc:
        logger.warning("[plantel] Fallback explicacion IA: %s", exc)
        return {
            "lectura_turno": "El cálculo estima cuánta gente hace falta en cada almacén y arma el mejor equipo posible con la gente que ya conoce ese turno.",
            "accion_principal": "Cubrir primero el almacén con más brecha entre gente necesaria y gente planificada.",
            "alertas": [
                "La necesidad sale de jornadas parecidas del mismo turno y almacén.",
                "Si falta gente, el riesgo no está solo en repartir mal sino en no llegar con la dotación.",
            ],
            "almacenes": [
                {
                    "almacen": item["almacen"],
                    "explicacion": f"En {item['almacen']} se calcula una necesidad de gente según bultos reales de jornadas parecidas y se arma el mejor plantel disponible."
                }
                for item in response_payload["almacenes"]
            ],
            "operarios": [
                {
                    "operario_id": item["operario_id"],
                    "explicacion": item["motivo_principal"],
                }
                for item in response_payload["suggested_assignments"][:10]
            ],
            "what_if": [
                "Probar qué pasa si entra más trabajo en VARIOS NO ALIMENTOS.",
                "Probar qué pasa si pasás gente de un almacén al otro.",
            ],
            "provider": provider,
            "model_used": "fallback-local",
        }


async def _persist_scenario(
    request: PlantelScenarioRequest,
    window: TurnWindow,
    source_name: str,
    response_payload: dict[str, Any],
    ia_payload: dict[str, Any],
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cursor = await db.execute(
            """
            INSERT INTO plantel_scenarios (
                nombre, turno_key, turno_label, hora_inicio, hora_fin, dotacion_total,
                source_name, request_json, result_json, ia_provider, ia_model,
                ia_prompt_version, ia_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                request.scenario_name or f"Escenario {window.label}",
                window.key,
                window.label,
                window.start_time.strftime("%H:%M"),
                window.end_time.strftime("%H:%M"),
                response_payload["summary"]["operarios_elegibles"],
                source_name,
                _serialize_json(request.model_dump()),
                _serialize_json(response_payload),
                ia_payload.get("provider"),
                ia_payload.get("model_used"),
                PLANTEL_AI_PROMPT_VERSION,
                _serialize_json(ia_payload),
            ),
        )
        scenario_id = cursor.lastrowid

        for item in response_payload["almacenes"]:
            await db.execute(
                """
                INSERT INTO plantel_scenario_almacen (
                    scenario_id, almacen, bultos_turno, lineas_turno, dotacion_sugerida,
                    capacidad_equipo, productividad_grupal, hora_fin_estimada, cobertura_pct,
                    riesgo, baseline_dotacion, baseline_capacidad, baseline_hora_fin,
                    baseline_cobertura_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
                    item["almacen"],
                    item["bultos_turno"],
                    item["lineas_turno"],
                    item["dotacion_sugerida"],
                    item["capacidad_equipo"],
                    item["productividad_grupal_hora"],
                    item["hora_fin_estimada"],
                    item["cobertura_pct"],
                    item["riesgo"],
                    item["baseline_dotacion"],
                    item["baseline_capacidad"],
                    item["baseline_hora_fin_estimada"],
                    item["baseline_cobertura_pct"],
                ),
            )

        for item in response_payload["suggested_assignments"]:
            await db.execute(
                """
                INSERT INTO plantel_scenario_asignacion (
                    scenario_id, operario_id, operario_nombre, tipo_asignacion, almacen,
                    score_total, capacidad_estimada, penalizacion, motivo_principal, detalle_json
                ) VALUES (?, ?, ?, 'ideal', ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
                    item["operario_id"],
                    item["operario_nombre"],
                    item["almacen"],
                    item["score"],
                    item["capacidad_estimada"],
                    item["penalizacion"],
                    item["motivo_principal"],
                    _serialize_json(item),
                ),
            )

        for item in response_payload["baseline_assignments"]:
            await db.execute(
                """
                INSERT INTO plantel_scenario_asignacion (
                    scenario_id, operario_id, operario_nombre, tipo_asignacion, almacen,
                    score_total, capacidad_estimada, penalizacion, motivo_principal, detalle_json
                ) VALUES (?, ?, ?, 'baseline', ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
                    item["operario_id"],
                    item["operario_nombre"],
                    item["almacen"],
                    item["score"],
                    item["capacidad_estimada"],
                    item["penalizacion"],
                    item["motivo_principal"],
                    _serialize_json(item),
                ),
            )

        for key, value in {
            "eligible_count": response_payload["summary"]["operarios_elegibles"],
            "personas_necesarias_total": response_payload["summary"]["personas_necesarias_total"],
            "personas_disponibles_turno": response_payload["summary"]["personas_disponibles_turno"],
            "brecha_personas": response_payload["summary"]["brecha_personas"],
            "demanda_total_bultos": response_payload["summary"]["demanda_total_bultos"],
            "capacidad_total_sugerida": response_payload["summary"]["capacidad_total_sugerida"],
            "capacidad_total_baseline": response_payload["summary"]["capacidad_total_baseline"],
            "mejora_capacidad_pct": response_payload["summary"]["mejora_capacidad_pct"],
        }.items():
            await db.execute(
                """
                INSERT INTO plantel_scenario_metrica (scenario_id, metrica_key, metrica_valor, detalle)
                VALUES (?, ?, ?, ?)
                """,
                (scenario_id, key, float(value), None),
            )
        await db.commit()
    return scenario_id


@router.get("/turnos")
async def get_turnos():
    return {"turnos": await _load_turns_from_db()}


@router.get("/escenarios")
async def list_escenarios(limit: int = 8):
    limit = max(1, min(int(limit), 50))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT scenario_id, nombre, turno_label, hora_inicio, hora_fin, created_at, result_json
            FROM plantel_scenarios
            ORDER BY scenario_id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()

    escenarios = []
    for row in rows:
        result_json = json.loads(row["result_json"]) if row["result_json"] else {}
        escenarios.append(
            {
                "scenario_id": row["scenario_id"],
                "nombre": row["nombre"],
                "turno_label": row["turno_label"],
                "hora_inicio": row["hora_inicio"],
                "hora_fin": row["hora_fin"],
                "created_at": row["created_at"],
                "summary": result_json.get("summary", {}),
            }
        )
    return {"escenarios": escenarios}


@router.post("/sugerencias")
async def generar_sugerencias(req: PlantelScenarioRequest):
    window = _turn_window(req.turno)
    demand = _demand_map(req.almacenes)
    if sum(item["bultos_turno"] for item in demand.values()) <= 0:
        raise HTTPException(status_code=400, detail="Debés cargar bultos > 0 para al menos un almacén.")

    profiles = []
    metadata = {}
    source_name = ""
    has_materialized_local = await _has_plantel_hist_data(window, req.history_days)

    if not req.force_refresh:
        cached = await _load_cached_profiles(window.key, req.history_days)
        if cached:
            profiles, metadata, source_name = cached
            if has_materialized_local and source_name != "sqlite_plantel_hist":
                logger.info(
                    "[plantel] Se descarta cache %s porque ya existe historico local materializado para turno=%s",
                    source_name,
                    window.label,
                )
                profiles = []
                metadata = {}
                source_name = ""
            else:
                logger.info(
                    "[plantel] Cache local reutilizada turno=%s source=%s elegibles=%s",
                    window.label,
                    source_name,
                    len(profiles),
                )

    if not profiles:
        rows, source_name = await _load_history(window, req.history_days)
        profiles, metadata = _build_operator_profiles(rows, window)
        if not profiles:
            raise HTTPException(status_code=400, detail=f"No se encontraron operarios elegibles para el turno {window.label}.")
        await _save_cached_profiles(window.key, req.history_days, source_name, profiles, metadata)

    weights = req.weights or ScenarioWeights()
    headcount_plan = _plan_headcounts(
        demand,
        total_available=len(profiles),
        store_projection=metadata.get("store_projection"),
        avg_turn_capacity=metadata.get("avg_turn_capacity", 0.0),
    )
    ideal = _build_assignment(
        profiles,
        demand,
        headcount_plan["suggested"],
        weights,
        mode="ideal",
        duration_hours=window.duration_hours,
        max_turn_capacity=metadata["max_turn_capacity"],
        avg_turn_capacity=metadata["avg_turn_capacity"],
        store_projection=metadata.get("store_projection"),
    )
    baseline = _build_assignment(
        sorted(profiles, key=lambda item: item["operario_id"]),
        demand,
        headcount_plan["suggested"],
        weights,
        mode="baseline",
        duration_hours=window.duration_hours,
        max_turn_capacity=metadata["max_turn_capacity"],
        avg_turn_capacity=metadata["avg_turn_capacity"],
        store_projection=metadata.get("store_projection"),
    )

    response_payload = _build_response_payload(
        scenario_id=None,
        request=req,
        window=window,
        source_name=source_name,
        profiles=profiles,
        headcount_plan=headcount_plan,
        ideal=ideal,
        baseline=baseline,
        metadata=metadata,
        ia_payload=None,
    )
    ia_payload = await _generate_ai_explanation(response_payload)
    response_payload = _build_response_payload(
        scenario_id=None,
        request=req,
        window=window,
        source_name=source_name,
        profiles=profiles,
        headcount_plan=headcount_plan,
        ideal=ideal,
        baseline=baseline,
        metadata=metadata,
        ia_payload=ia_payload,
    )
    scenario_id = await _persist_scenario(req, window, source_name, response_payload, ia_payload)
    response_payload["summary"]["scenario_id"] = scenario_id
    return response_payload
