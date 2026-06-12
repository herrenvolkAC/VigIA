from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db.paths import ROOT_DIR, resolve_db_path


router = APIRouter(prefix="/api/simulador-operativo", tags=["simulador-operativo"])

SIMULADOR_DB_PATH = resolve_db_path("SIMULADOR_OPERATIVO_DB_PATH", "simulador_operativo.db", ROOT_DIR)
CLASES = ["<=25%", "25-50%", "50-80%", "80-99%", "100%+"]


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS simulador_operativo_demanda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    viaje TEXT,
    fecha_demanda DATE,
    sucursal TEXT,
    numero_pallet TEXT,
    tipo TEXT,
    tipo_trabajo TEXT,
    plu TEXT NOT NULL,
    descripcion TEXT,
    cantidad REAL NOT NULL,
    pedido TEXT,
    uxp REAL NOT NULL,
    pct_pallet REAL NOT NULL,
    clase_extraccion TEXT NOT NULL,
    es_pallet_completo INTEGER NOT NULL DEFAULT 0,
    faltante_para_pallet REAL NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS simulador_operativo_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_sim_op_fecha ON simulador_operativo_demanda(fecha_demanda);
CREATE INDEX IF NOT EXISTS idx_sim_op_sucursal ON simulador_operativo_demanda(sucursal);
CREATE INDEX IF NOT EXISTS idx_sim_op_plu ON simulador_operativo_demanda(plu);
CREATE INDEX IF NOT EXISTS idx_sim_op_clase ON simulador_operativo_demanda(clase_extraccion);
"""


class EscenarioRequest(BaseModel):
    redondeo_min_pct: float = 0
    redondeo_top: int = 0
    calendario_ventana: int = 3
    mini_pallet: float = 6
    mini_min_lineas: int = 3
    mini_cobertura_min: float = 35
    mini_tolerancia_extra_pct: float = 20


async def init_simulador_db() -> None:
    SIMULADOR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(SIMULADOR_DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _norm_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _norm_text(value).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


ALIASES = {
    "viaje": {"viaje", "nro_viaje", "numero_viaje"},
    "fecha_demanda": {"fecha_demanda", "fecha", "fecha_pedido", "fecha_preparacion", "demanda_fecha"},
    "sucursal": {"sucursal", "local", "tienda", "destino"},
    "numero_pallet": {"numerodepallet", "numero_pallet", "nro_pallet", "pallet"},
    "tipo": {"tipo"},
    "tipo_trabajo": {"tipo_de_trabajo", "tipo_trabajo", "trabajo"},
    "plu": {"plu", "sku", "articulo", "codigo_articulo", "cod_articulo"},
    "descripcion": {"descripcion", "descrip", "detalle", "articulo_descripcion"},
    "cantidad": {"cantidad", "cant", "unidades", "qty"},
    "pedido": {"pedido", "nro_pedido", "numero_pedido"},
    "uxp": {"uxp", "unidades_por_pallet", "unid_por_pallet", "unidad_logistica"},
}
CRITICAL = {"fecha_demanda", "sucursal", "plu", "descripcion", "cantidad", "uxp"}


def _column_map(headers: list[str]) -> dict[str, str]:
    normalized = {_norm_key(header): header for header in headers if header is not None}
    found: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                found[canonical] = normalized[alias]
                break
    return found


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    text = _norm_text(value)
    if not text:
        return None
    text = text.replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _norm_text(value)
    if not text:
        return None
    candidates = [text[:19], text[:10], text]
    formats = ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                pass
    return None


def _clase(pct: float) -> str:
    if pct <= 0.25:
        return "<=25%"
    if pct <= 0.50:
        return "25-50%"
    if pct <= 0.80:
        return "50-80%"
    if pct < 1:
        return "80-99%"
    return "100%+"


def _derived(cantidad: float, uxp: float) -> tuple[float, str, int, float]:
    pct = cantidad / uxp if uxp else 0
    rem = cantidad % uxp if uxp else 0
    completo = int(uxp > 0 and abs(rem) < 0.000001)
    faltante = 0.0 if completo or not uxp else uxp - rem
    return pct, _clase(pct), completo, faltante


def _decode_csv(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _parse_csv(raw: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text = _decode_csv(raw)
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    if not headers:
        raise HTTPException(status_code=400, detail="El CSV no tiene encabezados.")
    mapping = _column_map(headers)
    missing = sorted(CRITICAL - set(mapping))
    if missing:
        labels = ", ".join(missing)
        raise HTTPException(status_code=400, detail=f"Faltan columnas criticas: {labels}.")

    valid: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    total_rows = 0
    for raw_row in reader:
        if not any(_norm_text(value) for value in raw_row.values()):
            continue
        total_rows += 1
        row = {key: _norm_text(raw_row.get(header)) for key, header in mapping.items()}
        fecha = _parse_date(row.get("fecha_demanda"))
        cantidad = _parse_float(row.get("cantidad"))
        uxp = _parse_float(row.get("uxp"))
        reason = ""
        if not fecha:
            reason = "fecha invalida"
        elif not row.get("sucursal") or not row.get("plu") or not row.get("descripcion"):
            reason = "campos obligatorios vacios"
        elif cantidad is None or cantidad <= 0:
            reason = "cantidad invalida"
        elif uxp is None or uxp <= 0:
            reason = "uxp invalida"
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        pct, clase, completo, faltante = _derived(cantidad, uxp)
        row.update(
            {
                "fecha_demanda": fecha,
                "cantidad": cantidad,
                "uxp": uxp,
                "pct_pallet": pct,
                "clase_extraccion": clase,
                "es_pallet_completo": completo,
                "faltante_para_pallet": faltante,
            }
        )
        valid.append(row)
    return valid, {"total_rows": total_rows, "rejected": rejected, "delimiter": delimiter}


async def _meta(db: aiosqlite.Connection) -> dict[str, str]:
    db.row_factory = aiosqlite.Row
    async with db.execute("SELECT key, value FROM simulador_operativo_meta") as cur:
        return {row["key"]: row["value"] for row in await cur.fetchall()}


async def _fetch_all(sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    async with aiosqlite.connect(SIMULADOR_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, args) as cur:
            return [dict(row) for row in await cur.fetchall()]


def _sku_solution(row: dict[str, Any]) -> dict[str, str]:
    lineas = float(row.get("lineas") or 0)
    pct_le50 = float(row.get("pct_le50") or 0)
    ocupacion = float(row.get("ocupacion_promedio") or 0)
    sucursales = float(row.get("sucursales") or 0)
    viajes = float(row.get("viajes") or 0)
    if lineas >= 3 and pct_le50 >= 70 and viajes >= 2:
        return {
            "solucion_sugerida": "Calendarizacion",
            "motivo_solucion": "Muchas lineas fraccionadas y repetidas; conviene probar consolidacion temporal antes de sumar unidades.",
        }
    if pct_le50 >= 65 and ocupacion <= 45 and sucursales <= 3:
        return {
            "solucion_sugerida": "Mini-pallet por SKU",
            "motivo_solucion": "Demanda chica y relativamente concentrada; conviene calcular una unidad secundaria desde la cantidad mas frecuente del articulo.",
        }
    if ocupacion >= 70 and ocupacion < 100 and pct_le50 < 40:
        return {
            "solucion_sugerida": "Redondeo selectivo",
            "motivo_solucion": "Ya opera cerca de la unidad logistica; redondear casos seleccionados puede generar pallets completos con menor sobrestock.",
        }
    if lineas >= 5 and sucursales >= 5:
        return {
            "solucion_sugerida": "Isla de preparacion",
            "motivo_solucion": "Articulo muy disperso en locales; puede requerir layout/flujo dedicado mas que una regla de cantidad.",
        }
    if sucursales >= 4 and lineas / max(sucursales, 1) >= 2:
        return {
            "solucion_sugerida": "Palomeros",
            "motivo_solucion": "Hay acumulacion por local; puede ordenar consolidacion aunque no reduzca manipulaciones por si solo.",
        }
    return {
        "solucion_sugerida": "Analisis puntual",
        "motivo_solucion": "No hay una senal dominante; revisar demanda, espacio y criticidad comercial antes de elegir piloto.",
    }


def _filters(
    search: str = "",
    min_lineas: int = 1,
    clase: str = "",
    sucursal: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if search:
        clauses.append("(plu LIKE ? OR descripcion LIKE ?)")
        args += [f"%{search}%", f"%{search}%"]
    if clase:
        clauses.append("clase_extraccion = ?")
        args.append(clase)
    if sucursal:
        clauses.append("sucursal = ?")
        args.append(sucursal)
    if fecha_desde:
        clauses.append("fecha_demanda >= ?")
        args.append(fecha_desde)
    if fecha_hasta:
        clauses.append("fecha_demanda <= ?")
        args.append(fecha_hasta)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    having = "HAVING lineas >= ?" if min_lineas > 1 else ""
    if min_lineas > 1:
        args.append(min_lineas)
    return where, args + []


def _pct(n: float, d: float) -> float:
    return round((n / d * 100), 1) if d else 0.0


def _round1(value: float) -> float:
    return round(float(value or 0), 1)


def fmt_num(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if abs(number - round(number)) < 0.000001:
        return str(int(round(number)))
    return str(round(number, 1))


async def _summary_payload() -> dict[str, Any]:
    async with aiosqlite.connect(SIMULADOR_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        meta = await _meta(db)
        async with db.execute(
            """
            SELECT COUNT(*) lineas, COALESCE(SUM(cantidad),0) unidades,
                   COUNT(DISTINCT plu) skus, COUNT(DISTINCT sucursal) sucursales,
                   COUNT(DISTINCT viaje) viajes,
                   COALESCE(AVG(pct_pallet),0) ocupacion,
                   SUM(es_pallet_completo) completos,
                   SUM(CASE WHEN pct_pallet <= .25 THEN 1 ELSE 0 END) le25,
                   SUM(CASE WHEN pct_pallet <= .50 THEN 1 ELSE 0 END) le50,
                   MIN(fecha_demanda) fecha_min, MAX(fecha_demanda) fecha_max
            FROM simulador_operativo_demanda
            """
        ) as cur:
            row = dict(await cur.fetchone())
        async with db.execute(
            """
            SELECT clase_extraccion clase, COUNT(*) lineas
            FROM simulador_operativo_demanda
            GROUP BY clase_extraccion
            """
        ) as cur:
            dist_raw = {r["clase"]: r["lineas"] for r in await cur.fetchall()}
        lineas = row["lineas"] or 0
        fragmentacion50 = _pct(row["le50"] or 0, lineas)
        if not lineas:
            lectura = "Importa un CSV para iniciar el estudio operativo."
        elif fragmentacion50 >= 70:
            lectura = "Alta fragmentacion detectada: gran parte de las lineas no completa media unidad logistica."
        elif _pct(row["completos"] or 0, lineas) >= 45:
            lectura = "La demanda muestra una proporcion relevante de pallets completos, con oportunidades puntuales en lineas parciales."
        else:
            lectura = "Se observa fragmentacion moderada; conviene revisar SKU criticos antes de definir una regla general."
    return {
        "meta": meta,
        "kpis": {
            "lineas": lineas,
            "unidades": _round1(row["unidades"]),
            "skus": row["skus"] or 0,
            "sucursales": row["sucursales"] or 0,
            "viajes": row["viajes"] or 0,
            "pct_pallet_completo": _pct(row["completos"] or 0, lineas),
            "pct_le25": _pct(row["le25"] or 0, lineas),
            "pct_le50": fragmentacion50,
            "ocupacion_promedio": _round1((row["ocupacion"] or 0) * 100),
            "fecha_min": row["fecha_min"],
            "fecha_max": row["fecha_max"],
        },
        "distribucion": [{"clase": clase, "lineas": dist_raw.get(clase, 0)} for clase in CLASES],
        "lectura": lectura,
    }


@router.post("/importar")
async def importar(request: Request):
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="No se recibio ningun archivo CSV.")
    rows, info = _parse_csv(raw)
    if not rows:
        raise HTTPException(status_code=400, detail="No se encontraron filas validas para importar.")
    async with aiosqlite.connect(SIMULADOR_DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("DELETE FROM simulador_operativo_demanda")
        await db.execute("DELETE FROM simulador_operativo_meta")
        await db.executemany(
            """
            INSERT INTO simulador_operativo_demanda
                (viaje, fecha_demanda, sucursal, numero_pallet, tipo, tipo_trabajo, plu,
                 descripcion, cantidad, pedido, uxp, pct_pallet, clase_extraccion,
                 es_pallet_completo, faltante_para_pallet)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("viaje"),
                    row["fecha_demanda"],
                    row["sucursal"],
                    row.get("numero_pallet"),
                    row.get("tipo"),
                    row.get("tipo_trabajo"),
                    row["plu"],
                    row["descripcion"],
                    row["cantidad"],
                    row.get("pedido"),
                    row["uxp"],
                    row["pct_pallet"],
                    row["clase_extraccion"],
                    row["es_pallet_completo"],
                    row["faltante_para_pallet"],
                )
                for row in rows
            ],
        )
        meta = {
            "last_import_at": _now(),
            "source_filename": request.headers.get("x-filename", "estudio.csv"),
            "rows_imported": str(len(rows)),
            "rows_rejected": str(sum(info["rejected"].values())),
            "delimiter": info["delimiter"],
        }
        await db.executemany(
            "INSERT INTO simulador_operativo_meta (key, value) VALUES (?, ?)",
            list(meta.items()),
        )
        await db.commit()
    payload = await _summary_payload()
    payload["importacion"] = {
        "importadas": len(rows),
        "rechazadas": sum(info["rejected"].values()),
        "motivos_rechazo": info["rejected"],
        "filas_leidas": info["total_rows"],
    }
    return payload


@router.get("/resumen")
async def resumen():
    return await _summary_payload()


@router.get("/ranking-sku")
async def ranking_sku(
    search: str = "",
    min_lineas: int = 1,
    clase: str = "",
    sucursal: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
    limit: int = 100,
):
    min_lineas = max(1, int(min_lineas or 1))
    limit = min(1000, max(1, int(limit or 100)))
    where, args = _filters(search, min_lineas, clase, sucursal, fecha_desde, fecha_hasta)
    having = "HAVING lineas >= ?" if min_lineas > 1 else ""
    query_args = args[:-1] if min_lineas > 1 else args
    if min_lineas > 1:
        query_args.append(min_lineas)
    query_args.append(limit)
    rows = await _fetch_all(
        f"""
        SELECT plu, MAX(descripcion) descripcion, COUNT(*) lineas, SUM(cantidad) unidades,
               ROUND(AVG(uxp),1) uxp, COUNT(DISTINCT sucursal) sucursales,
               COUNT(DISTINCT viaje) viajes, ROUND(AVG(pct_pallet)*100,1) ocupacion_promedio,
               ROUND(SUM(CASE WHEN pct_pallet <= .25 THEN 1 ELSE 0 END) * 100.0 / COUNT(*),1) pct_le25,
               ROUND(SUM(CASE WHEN pct_pallet <= .50 THEN 1 ELSE 0 END) * 100.0 / COUNT(*),1) pct_le50,
               ROUND((COUNT(*) * 1.8) + (COUNT(DISTINCT sucursal) * 1.2) +
                     (SUM(CASE WHEN pct_pallet <= .50 THEN 1 ELSE 0 END) * 1.6) +
                     (COUNT(DISTINCT viaje) * .6) - (AVG(pct_pallet) * 10),1) score_criticidad
        FROM simulador_operativo_demanda
        {where}
        GROUP BY plu
        {having}
        ORDER BY score_criticidad DESC, lineas DESC
        LIMIT ?
        """,
        tuple(query_args),
    )
    for row in rows:
        row.update(_sku_solution(row))
    resumen_soluciones: dict[str, int] = {}
    for row in rows:
        key = row.get("solucion_sugerida") or "Analisis puntual"
        resumen_soluciones[key] = resumen_soluciones.get(key, 0) + 1
    return {
        "rows": rows,
        "resumen_soluciones": [
            {"solucion": key, "skus": value}
            for key, value in sorted(resumen_soluciones.items(), key=lambda item: item[1], reverse=True)
        ],
    }


@router.get("/repeticion-local-sku")
async def repeticion_local_sku(
    search: str = "",
    min_lineas: int = 1,
    clase: str = "",
    sucursal: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
    limit: int = 200,
):
    min_lineas = max(1, int(min_lineas or 1))
    limit = min(1000, max(1, int(limit or 200)))
    where, args = _filters(search, min_lineas, clase, sucursal, fecha_desde, fecha_hasta)
    having = "HAVING lineas >= ?" if min_lineas > 1 else ""
    query_args = args[:-1] if min_lineas > 1 else args
    if min_lineas > 1:
        query_args.append(min_lineas)
    query_args.append(limit)
    rows = await _fetch_all(
        f"""
        SELECT sucursal, plu, MAX(descripcion) descripcion, COUNT(DISTINCT fecha_demanda) dias_demanda,
               COUNT(*) lineas, ROUND(SUM(cantidad),1) unidades, ROUND(AVG(uxp),1) uxp,
               ROUND(SUM(cantidad) * 1.0 / COUNT(DISTINCT fecha_demanda),1) promedio_diario,
               ROUND(MAX(cantidad),1) maximo_diario, COUNT(DISTINCT viaje) viajes,
               MIN(fecha_demanda) primera_fecha, MAX(fecha_demanda) ultima_fecha
        FROM simulador_operativo_demanda
        {where}
        GROUP BY sucursal, plu
        {having}
        ORDER BY lineas DESC, dias_demanda DESC, unidades DESC
        LIMIT ?
        """,
        tuple(query_args),
    )
    return {"rows": rows}


async def _all_rows() -> list[dict[str, Any]]:
    return await _fetch_all("SELECT * FROM simulador_operativo_demanda ORDER BY fecha_demanda, sucursal, plu")


def _base_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    lineas = len(rows)
    unidades = sum(float(r["cantidad"] or 0) for r in rows)
    pallets = sum(float(r["cantidad"] or 0) / float(r["uxp"] or 1) for r in rows)
    ocupacion = sum(float(r["pct_pallet"] or 0) for r in rows) / lineas * 100 if lineas else 0
    viajes = len({r.get("viaje") for r in rows if r.get("viaje")})
    parciales = sum(1 for r in rows if float(r["pct_pallet"] or 0) < 1)
    le50 = sum(1 for r in rows if float(r["pct_pallet"] or 0) <= .5)
    completos = sum(1 for r in rows if int(r.get("es_pallet_completo") or 0))
    repeticiones = max(0, lineas - len({(r.get("sucursal"), r.get("plu")) for r in rows}))
    return {
        "lineas": lineas,
        "unidades": unidades,
        "pallets": pallets,
        "ocupacion": ocupacion,
        "viajes": viajes,
        "parciales": parciales,
        "le50": le50,
        "completos": completos,
        "repeticiones": repeticiones,
    }


def _level_score(value: str) -> int:
    return {"Base": 0, "Bajo": 1, "Medio": 2, "Alto": 3}.get(value, 2)


def _level_from_pct(value: float, low: float, high: float) -> str:
    if value >= high:
        return "Alto"
    if value >= low:
        return "Medio"
    return "Bajo"


def _finalize_scenario(base: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    lineas_actuales = float(base["lineas"] or 0)
    unidades_actuales = float(base["unidades"] or 0)
    lineas_simuladas = float(scenario.get("lineas_simuladas") or 0)
    unidades_simuladas = float(scenario.get("unidades_simuladas") or 0)
    reduccion_lineas = max(0.0, lineas_actuales - lineas_simuladas)
    unidades_adicionales = max(0.0, unidades_simuladas - unidades_actuales)
    reduccion_parciales = max(0.0, float(scenario.get("reduccion_extracciones_parciales") or 0))
    reduccion_lineas_pct = _pct(reduccion_lineas, lineas_actuales)
    incremento_unidades_pct = _pct(unidades_adicionales, unidades_actuales)
    reduccion_parciales_pct = _pct(reduccion_parciales, base.get("parciales") or lineas_actuales)
    mejora_ocupacion_pp = _round1(float(scenario.get("ocupacion_promedio") or 0) - float(base.get("ocupacion") or 0))
    beneficio = reduccion_lineas_pct * 1.25 + reduccion_parciales_pct * .9 + max(0, mejora_ocupacion_pp) * .35
    costo = incremento_unidades_pct * 1.25 + _level_score(str(scenario.get("complejidad"))) * 8 + _level_score(str(scenario.get("riesgo"))) * 9
    if scenario.get("escenario") == "Situacion actual":
        indice = 0.0
    else:
        indice = max(0.0, min(100.0, 50 + beneficio - costo))
    if indice >= 70 and incremento_unidades_pct <= 12:
        recomendacion = "Candidato a piloto"
    elif incremento_unidades_pct > 25:
        recomendacion = "Alto costo de inventario"
    elif reduccion_lineas_pct >= 15 or reduccion_parciales_pct >= 20:
        recomendacion = "Aplicar a SKU seleccionados"
    elif scenario.get("escenario") == "Situacion actual":
        recomendacion = "Base comparativa"
    else:
        recomendacion = "Requiere mas datos"
    scenario.update(
        {
            "variacion_lineas": _round1(lineas_simuladas - lineas_actuales),
            "reduccion_lineas": _round1(reduccion_lineas),
            "reduccion_lineas_pct": reduccion_lineas_pct,
            "unidades_adicionales": _round1(unidades_adicionales),
            "pct_incremento_unidades": incremento_unidades_pct,
            "reduccion_extracciones_parciales": _round1(reduccion_parciales),
            "reduccion_parciales_pct": reduccion_parciales_pct,
            "mejora_ocupacion_pp": mejora_ocupacion_pp,
            "indice_conveniencia": _round1(indice),
            "recomendacion": recomendacion,
        }
    )
    scenario["explicacion"] = {
        "resumen": scenario.get("lectura_operativa") or "",
        "formulas": [
            {
                "indicador": "Reduce lineas",
                "formula": "(lineas actuales - lineas simuladas) / lineas actuales",
                "calculo": f"({fmt_num(lineas_actuales)} - {fmt_num(lineas_simuladas)}) / {fmt_num(lineas_actuales)} = {reduccion_lineas_pct}%",
            },
            {
                "indicador": "Reduce parciales",
                "formula": "extracciones parciales reducidas / extracciones parciales actuales",
                "calculo": f"{fmt_num(reduccion_parciales)} / {fmt_num(base.get('parciales') or 0)} = {reduccion_parciales_pct}%",
            },
            {
                "indicador": "Unidades extra",
                "formula": "(unidades simuladas - unidades actuales) / unidades actuales",
                "calculo": f"({fmt_num(unidades_simuladas)} - {fmt_num(unidades_actuales)}) / {fmt_num(unidades_actuales)} = {incremento_unidades_pct}%",
            },
            {
                "indicador": "Indice",
                "formula": "50 + beneficio - costo; beneficio pondera reduccion de lineas, parciales y ocupacion; costo pondera unidades extra, complejidad y riesgo",
                "calculo": f"Indice = {scenario.get('indice_conveniencia')} | beneficio: lineas {reduccion_lineas_pct}%, parciales {reduccion_parciales_pct}%, ocupacion {mejora_ocupacion_pp} pp | costo: unidades extra {incremento_unidades_pct}%, complejidad {scenario.get('complejidad')}, riesgo {scenario.get('riesgo')}",
            },
        ],
        "datos_base": {
            "lineas_actuales": _round1(lineas_actuales),
            "lineas_simuladas": _round1(lineas_simuladas),
            "unidades_actuales": _round1(unidades_actuales),
            "unidades_simuladas": _round1(unidades_simuladas),
            "extracciones_parciales_actuales": base.get("parciales") or 0,
            "extracciones_parciales_reducidas": _round1(reduccion_parciales),
            "ocupacion_actual": _round1(base.get("ocupacion") or 0),
            "ocupacion_simulada": scenario.get("ocupacion_promedio"),
        },
    }
    return scenario


def _top_plus(rows: list[dict[str, Any]], top: int) -> set[str]:
    if top <= 0:
        return set()
    scores: dict[str, int] = {}
    for row in rows:
        scores[row["plu"]] = scores.get(row["plu"], 0) + 1
    return {plu for plu, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top]}


def _redondeo(rows: list[dict[str, Any]], min_pct: float, top: int) -> dict[str, Any]:
    selected = _top_plus(rows, top)
    afectadas = 0
    simuladas = 0.0
    completos = 0
    for row in rows:
        cantidad = float(row["cantidad"])
        uxp = float(row["uxp"])
        pct = float(row["pct_pallet"])
        applies = (pct * 100) >= min_pct and (not selected or row["plu"] in selected)
        if applies and cantidad % uxp:
            cantidad = math.ceil(cantidad / uxp) * uxp
            afectadas += 1
        if applies and cantidad % uxp == 0:
            completos += 1
        simuladas += cantidad
    base = _base_metrics(rows)
    adicionales = simuladas - base["unidades"]
    affected_pct = _pct(afectadas, base["lineas"])
    increment_pct = _pct(adicionales, base["unidades"])
    risk = "Alto" if increment_pct > 20 else "Medio" if increment_pct > 8 else "Bajo"
    scenario = {
        "escenario": "Redondeo a unidad logistica",
        "lineas_actuales": base["lineas"],
        "lineas_simuladas": base["lineas"],
        "unidades_actuales": _round1(base["unidades"]),
        "unidades_simuladas": _round1(simuladas),
        "ocupacion_promedio": _round1(base["ocupacion"]),
        "lineas_afectadas": afectadas,
        "pallets_completos_generados": completos,
        "reduccion_extracciones_parciales": afectadas,
        "impacto": _level_from_pct(affected_pct, 10, 25),
        "complejidad": "Bajo",
        "riesgo": risk,
        "lectura_operativa": (
            "Este cambio apunta a dejar de preparar fracciones cuando el pedido esta cerca de la unidad logistica: "
            f"se enviaria el pallet completo o multiplo de UxP. Afecta {afectadas} lineas y agrega {_round1(adicionales)} unidades, "
            "por lo que debe validarse con abastecimiento/comercial para evitar sobrestock en sucursal."
        ),
    }
    return _finalize_scenario(base, scenario)


def _calendarizacion(rows: list[dict[str, Any]], ventana: int) -> dict[str, Any]:
    grupos: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        try:
            fecha = datetime.strptime(row["fecha_demanda"], "%Y-%m-%d").date()
            bucket = fecha.toordinal() // max(1, ventana)
        except Exception:
            bucket = 0
        key = (row["sucursal"], row["plu"], bucket)
        item = grupos.setdefault(key, {"cantidad": 0.0, "uxp": float(row["uxp"] or 1), "sucursal": row["sucursal"], "plu": row["plu"]})
        item["cantidad"] += float(row["cantidad"] or 0)
    completas = sum(1 for item in grupos.values() if item["cantidad"] % item["uxp"] == 0 or item["cantidad"] >= item["uxp"])
    ocupacion = sum(item["cantidad"] / item["uxp"] for item in grupos.values()) / len(grupos) * 100 if grupos else 0
    base = _base_metrics(rows)
    lineas_sim = len(grupos)
    reduction_pct = _pct(base["lineas"] - lineas_sim, base["lineas"])
    scenario = {
        "escenario": f"Calendarizacion {ventana} dias",
        "lineas_actuales": base["lineas"],
        "lineas_simuladas": lineas_sim,
        "unidades_actuales": _round1(base["unidades"]),
        "unidades_simuladas": _round1(base["unidades"]),
        "ocupacion_promedio": _round1(ocupacion),
        "casos_pallet_completo": completas,
        "reduccion_extracciones_parciales": base["lineas"] - lineas_sim,
        "impacto": _level_from_pct(reduction_pct, 10, 25),
        "complejidad": "Medio",
        "riesgo": "Medio",
        "lectura_operativa": (
            f"Este cambio no significa preparar con frecuencia fija cada {ventana} dias: significa agrupar la demanda del mismo local y articulo "
            f"dentro de bloques de {ventana} dias y tratar cada bloque como una sola preparacion. "
            f"Consolida la operacion en {lineas_sim} grupos y reduce {base['lineas'] - lineas_sim} lineas sin agregar unidades, "
            "pero puede exigir ajustar la frecuencia de reposicion o aceptar mas stock promedio en sucursal."
        ),
    }
    return _finalize_scenario(base, scenario)


def _mini_pallet(rows: list[dict[str, Any]], min_lineas: int, cobertura_min: float, tolerancia_extra_pct: float) -> dict[str, Any]:
    lineas = len(rows)
    by_plu: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_plu[str(row.get("plu") or "")].append(row)

    propuestas: list[dict[str, Any]] = []
    lineas_exactas = 0
    lineas_toleradas = 0
    unidades_simuladas = 0.0
    unidades_cubiertas_actuales = 0.0
    ocupaciones: list[float] = []

    for plu, plu_rows in by_plu.items():
        cantidades = [float(row.get("cantidad") or 0) for row in plu_rows if float(row.get("cantidad") or 0) > 0]
        if len(cantidades) < max(1, min_lineas):
            continue
        rounded = [round(cantidad, 3) for cantidad in cantidades]
        counts = Counter(rounded)
        moda, moda_count = counts.most_common(1)[0]
        exactas = 0
        toleradas = 0
        extra = 0.0
        cubiertas_actuales = 0.0
        for cantidad in cantidades:
            if abs(cantidad - moda) < 0.0001:
                exactas += 1
                toleradas += 1
                cubiertas_actuales += cantidad
                continue
            if cantidad < moda:
                extra_pct = (moda - cantidad) / cantidad * 100 if cantidad else 999
                if extra_pct <= tolerancia_extra_pct:
                    toleradas += 1
                    extra += moda - cantidad
                    cubiertas_actuales += cantidad
        cobertura_exacta = _pct(exactas, len(cantidades))
        cobertura_tolerada = _pct(toleradas, len(cantidades))
        if cobertura_exacta < cobertura_min and cobertura_tolerada < cobertura_min:
            continue
        lineas_exactas += exactas
        lineas_toleradas += toleradas
        unidades_cubiertas_actuales += cubiertas_actuales
        unidades_simuladas += cubiertas_actuales + extra
        ocupaciones.append(cobertura_tolerada)
        propuestas.append(
            {
                "plu": plu,
                "descripcion": plu_rows[0].get("descripcion"),
                "mini_pallet": moda,
                "lineas": len(cantidades),
                "lineas_exactas": exactas,
                "lineas_con_tolerancia": toleradas,
                "cobertura_exacta": cobertura_exacta,
                "cobertura_con_tolerancia": cobertura_tolerada,
                "unidades_extra": _round1(extra),
                "pct_extra_sobre_cubiertas": _pct(extra, cubiertas_actuales),
            }
        )

    base = _base_metrics(rows)
    propuestas = sorted(
        propuestas,
        key=lambda item: (item["cobertura_con_tolerancia"], item["lineas_con_tolerancia"], -item["pct_extra_sobre_cubiertas"]),
        reverse=True,
    )
    extra_total = max(0.0, unidades_simuladas - unidades_cubiertas_actuales)
    potencial = _pct(lineas_toleradas, lineas)
    ocupacion = sum(ocupaciones) / len(ocupaciones) if ocupaciones else base["ocupacion"]
    scenario = {
        "escenario": "Pallet secundario dinamico",
        "lineas_actuales": base["lineas"],
        "lineas_simuladas": base["lineas"],
        "unidades_actuales": _round1(base["unidades"]),
        "unidades_simuladas": _round1(base["unidades"] + extra_total),
        "ocupacion_promedio": _round1(ocupacion),
        "skus_con_propuesta": len(propuestas),
        "lineas_coinciden": lineas_exactas,
        "lineas_con_tolerancia": lineas_toleradas,
        "unidades_extra_mini_pallet": _round1(extra_total),
        "reduccion_potencial_manipulacion": potencial,
        "reduccion_extracciones_parciales": lineas_toleradas,
        "propuestas_top": propuestas[:10],
        "impacto": _level_from_pct(potencial, 20, 45),
        "complejidad": "Alto",
        "riesgo": "Alto" if _pct(extra_total, base["unidades"]) > 15 else "Medio",
        "lectura_operativa": (
            "Propone mini-pallets por articulo segun la cantidad mas frecuente que piden los locales. "
            f"Encuentra {len(propuestas)} SKU con patron repetible y cubre {lineas_toleradas} lineas exactas o cercanas, "
            f"agregando {_round1(extra_total)} unidades por tolerancia."
        ),
    }
    scenario = _finalize_scenario(base, scenario)
    if scenario.get("explicacion"):
        scenario["explicacion"]["resumen"] = (
            "Este cambio operativo apunta a prearmar mini-pallets especificos por articulo, no un tamano unico. "
            "Para cada PLU se busca la cantidad mas probable que piden los locales. Si un local pide un poco menos, "
            "se puede enviar el mini-pallet completo siempre que el sobreenvio quede dentro de la tolerancia definida."
        )
        scenario["explicacion"]["formulas"].insert(
            0,
            {
                "indicador": "Tamano propuesto por SKU",
                "formula": "moda de cantidad pedida por PLU",
                "calculo": (
                    f"Se consideran SKU con al menos {min_lineas} lineas. "
                    f"Se acepta el patron si la cobertura exacta o con tolerancia supera {cobertura_min}%. "
                    f"Tolerancia maxima de sobreenvio por linea: {tolerancia_extra_pct}%."
                ),
            },
        )
        scenario["explicacion"]["datos_base"]["skus_con_propuesta"] = len(propuestas)
        scenario["explicacion"]["datos_base"]["lineas_exactas_moda"] = lineas_exactas
        scenario["explicacion"]["datos_base"]["lineas_cubiertas_con_tolerancia"] = lineas_toleradas
        scenario["explicacion"]["datos_base"]["unidades_extra_por_tolerancia"] = _round1(extra_total)
        scenario["explicacion"]["propuestas_top"] = propuestas[:10]
    return scenario


def _qualitative(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    base = _base_metrics(rows)
    sucursales = len({r["sucursal"] for r in rows})
    skus = len({r["plu"] for r in rows})
    lineas_por_sucursal = base["lineas"] / sucursales if sucursales else 0
    if name == "Palomeros":
        reduccion = min(base["repeticiones"], round(base["lineas"] * .12))
        complejidad = "Medio"
        riesgo = "Medio"
        lectura = (
            "Este cambio apunta a ordenar fisicamente la acumulacion por local: extraccion y consolidacion quedan desacopladas. "
            "Sirve para control visual y armado multi-SKU, aunque por si solo no baja la cantidad de fracciones preparadas."
        )
    else:
        reduccion = min(base["le50"], round(base["lineas"] * .18))
        complejidad = "Alto"
        riesgo = "Medio"
        lectura = (
            "Este cambio apunta a separar una zona de preparacion para articulos criticos o voluminosos. "
            "Puede bajar recorridos y mejorar ergonomia si pocos SKU concentran el problema, pero requiere espacio y abastecimiento ordenado a la isla."
        )
    scenario = {
        "escenario": name,
        "lineas_actuales": base["lineas"],
        "lineas_simuladas": base["lineas"],
        "unidades_actuales": _round1(base["unidades"]),
        "unidades_simuladas": _round1(base["unidades"]),
        "ocupacion_promedio": _round1(base["ocupacion"]),
        "reduccion_extracciones_parciales": reduccion,
        "indicadores": {"sucursales": sucursales, "skus": skus, "lineas_por_sucursal": _round1(lineas_por_sucursal)},
        "impacto": "Medio",
        "complejidad": complejidad,
        "riesgo": riesgo,
        "lectura_operativa": lectura,
    }
    return _finalize_scenario(base, scenario)


def _lectura_critica(summary: dict[str, Any], scenarios: list[dict[str, Any]]) -> list[str]:
    kpis = summary["kpis"]
    texts: list[str] = []
    if kpis["pct_le50"] > 70:
        texts.append("Se observa alta fragmentacion de demanda. Antes de invertir en cambios fisicos, conviene evaluar consolidacion temporal o redondeos acotados.")
    top_reduction = max((abs(s.get("variacion_lineas", 0)) for s in scenarios if "Calendarizacion" in s["escenario"]), default=0)
    if kpis["lineas"] and top_reduction / kpis["lineas"] > .25:
        texts.append("La consolidacion temporal aparece como alternativa de bajo costo relativo, aunque debe validarse contra stock y frecuencia de reposicion en sucursal.")
    red = next((s for s in scenarios if s["escenario"].startswith("Redondeo")), None)
    if red and red.get("pct_incremento_unidades", 0) > 20:
        texts.append("El redondeo mejora la operacion, pero el costo de inventario adicional puede ser elevado y no deberia aplicarse como regla general.")
    if kpis["skus"] and kpis["lineas"] / max(kpis["skus"], 1) > 3:
        texts.append("Existe concentracion del problema en articulos repetidos. Se recomienda analizar soluciones por SKU o familia antes de generalizar.")
    if not texts:
        texts.append("El estudio no muestra una senal dominante. Conviene validar con operacion, abastecimiento y datos de layout antes de elegir un piloto.")
    return texts


def _scenario_charts(scenarios: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    candidates = [s for s in scenarios if s.get("escenario") != "Situacion actual"]
    return {
        "reduccion_lineas": [{"escenario": s["escenario"], "valor": s.get("reduccion_lineas_pct", 0)} for s in candidates],
        "unidades_extra": [{"escenario": s["escenario"], "valor": s.get("pct_incremento_unidades", 0)} for s in candidates],
        "reduccion_parciales": [{"escenario": s["escenario"], "valor": s.get("reduccion_parciales_pct", 0)} for s in candidates],
        "conveniencia": [{"escenario": s["escenario"], "valor": s.get("indice_conveniencia", 0)} for s in candidates],
    }


def _recommendation(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [s for s in scenarios if s.get("escenario") != "Situacion actual"]
    if not candidates:
        return {"escenario": "Sin datos", "motivo": "Importa demanda para comparar escenarios.", "indice": 0}
    best = max(candidates, key=lambda s: float(s.get("indice_conveniencia") or 0))
    blockers = []
    if best.get("pct_incremento_unidades", 0) > 15:
        blockers.append("inventario adicional relevante")
    if best.get("complejidad") == "Alto":
        blockers.append("implementacion fisica compleja")
    if best.get("reduccion_lineas_pct", 0) < 5 and best.get("reduccion_parciales_pct", 0) < 15:
        blockers.append("beneficio cuantitativo bajo")
    motivo = (
        f"Mayor indice de conveniencia ({best.get('indice_conveniencia', 0)}), "
        f"con {best.get('reduccion_lineas_pct', 0)}% de reduccion de lineas y "
        f"{best.get('pct_incremento_unidades', 0)}% de unidades adicionales."
    )
    if blockers:
        motivo += " Validar antes de piloto: " + ", ".join(blockers) + "."
    return {"escenario": best["escenario"], "motivo": motivo, "indice": best.get("indice_conveniencia", 0), "recomendacion": best.get("recomendacion")}


@router.post("/escenarios")
async def escenarios(req: EscenarioRequest):
    rows = await _all_rows()
    base = _base_metrics(rows)
    actual = _finalize_scenario(
        base,
        {
            "escenario": "Situacion actual",
            "lineas_actuales": base["lineas"],
            "lineas_simuladas": base["lineas"],
            "unidades_actuales": _round1(base["unidades"]),
            "unidades_simuladas": _round1(base["unidades"]),
            "pallets_teoricos": _round1(base["pallets"]),
            "ocupacion_promedio": _round1(base["ocupacion"]),
            "viajes_actuales": base["viajes"],
            "impacto": "Base",
            "complejidad": "Base",
            "riesgo": "Base",
            "lectura_operativa": "Situacion actual sin cambios operativos.",
        },
    )
    scenarios = [
        actual,
        _redondeo(rows, req.redondeo_min_pct, req.redondeo_top),
        _calendarizacion(rows, req.calendario_ventana),
        _mini_pallet(rows, req.mini_min_lineas, req.mini_cobertura_min, req.mini_tolerancia_extra_pct),
        _qualitative(rows, "Palomeros"),
        _qualitative(rows, "Islas de preparacion"),
    ]
    summary = await _summary_payload()
    return {
        "escenarios": scenarios,
        "graficos": _scenario_charts(scenarios),
        "recomendacion_principal": _recommendation(scenarios),
        "lectura_critica": _lectura_critica(summary, scenarios),
    }


@router.delete("/estudio")
async def borrar_estudio():
    async with aiosqlite.connect(SIMULADOR_DB_PATH) as db:
        await db.execute("DELETE FROM simulador_operativo_demanda")
        await db.execute("DELETE FROM simulador_operativo_meta")
        await db.commit()
    return {"ok": True}


def _csv_response(filename: str, rows: list[dict[str, Any]]) -> StreamingResponse:
    output = io.StringIO()
    if rows:
        fieldnames: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)
        writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write("sin_datos\n")
    data = output.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export")
async def export(tipo: str = Query("resumen", pattern="^(resumen|ranking|comparador)$")):
    if tipo == "ranking":
        data = await ranking_sku(limit=1000)
        return _csv_response("simulador_operativo_ranking_sku.csv", data["rows"])
    if tipo == "comparador":
        data = await escenarios(EscenarioRequest())
        rows = [
            {
                key: value
                for key, value in scenario.items()
                if key not in {"explicacion", "propuestas_top", "indicadores"}
            }
            for scenario in data["escenarios"]
        ]
        return _csv_response("simulador_operativo_comparador.csv", rows)
    summary = await _summary_payload()
    rows = [{"indicador": key, "valor": value} for key, value in summary["kpis"].items()]
    rows += [{"indicador": f"clase_{item['clase']}", "valor": item["lineas"]} for item in summary["distribucion"]]
    rows.append({"indicador": "lectura", "valor": summary["lectura"]})
    return _csv_response("simulador_operativo_resumen.csv", rows)
