from __future__ import annotations

import math
import base64
import csv
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite
from openpyxl import Workbook
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db.schema import DB_PATH
from routers.auth_local import current_auth


router = APIRouter(prefix="/api/herramientas", tags=["herramientas"])
logger = logging.getLogger("vigia.herramientas")

ROOT_DIR = Path(__file__).resolve().parent.parent
JAVA_HELPER_SRC = ROOT_DIR / "scripts" / "OracleProductividadQuery.java"
JAVA_BUILD_DIR = ROOT_DIR / ".codex_tmp" / "java_build"


DESTINOS_KM = [
    {"id": "cd_mar_de_ajo", "nombre": "CD a Mar de Ajo", "km": 720},
    {"id": "cd_mar_de_ajo_madariaga", "nombre": "CD a Mar de Ajo - Madariaga", "km": 800},
    {"id": "cd_mar_del_plata", "nombre": "CD a Mar de Plata", "km": 850},
    {"id": "cd_mar_del_tuyu", "nombre": "CD a Mar del Tuyu", "km": 720},
    {"id": "cd_mar_del_tuyu_mdq", "nombre": "CD a Mar del Tuyu - MDQ", "km": 967},
    {"id": "cd_parana", "nombre": "CD a Parana", "km": 1100},
    {"id": "cd_rosario", "nombre": "CD a Rosario", "km": 680},
    {"id": "cd_santa_fe", "nombre": "CD a Santa Fe", "km": 1060},
    {"id": "cd_madariaga", "nombre": "CD Madariaga", "km": 750},
    {"id": "famaba_madariaga", "nombre": "Famaba - Madariaga", "km": 780},
    {"id": "famaba_mar_de_ajo", "nombre": "Famaba - Mar de Ajo", "km": 750},
    {"id": "famaba_mar_de_ajo_madariaga", "nombre": "Famaba - Mar de Ajo - Madariaga", "km": 810},
    {"id": "famaba_mar_del_plata_madariaga", "nombre": "Famaba - Mar del Plata - Madariaga", "km": 920},
    {"id": "famaba_parana", "nombre": "Famaba - Parana", "km": 1100},
    {"id": "famaba_rosario", "nombre": "Famaba - Rosario", "km": 720},
    {"id": "famaba_santa_fe", "nombre": "Famaba - Santa Fe", "km": 1060},
    {"id": "famaba_santa_fe_parana", "nombre": "Famaba - Sante Fe - Parana", "km": 1150},
    {"id": "rosario_santa_fe_parana", "nombre": "Rosario - Santa Fe - Parana", "km": 1150},
    {"id": "santa_fe_parana", "nombre": "Sanfe - Parana", "km": 1150},
]


FERIADOS_BASE = [
    {"fecha": "2026-01-01", "dia": "Jueves", "motivo": "Ano Nuevo", "tipo": "Feriado inamovible"},
    {"fecha": "2026-02-16", "dia": "Lunes", "motivo": "Carnaval", "tipo": "Feriado inamovible"},
    {"fecha": "2026-02-17", "dia": "Martes", "motivo": "Carnaval", "tipo": "Feriado inamovible"},
    {"fecha": "2026-03-23", "dia": "Lunes", "motivo": "Dia no laborable con fines turisticos", "tipo": "Turistico"},
    {"fecha": "2026-03-24", "dia": "Martes", "motivo": "Dia Nacional de la Memoria por la Verdad y la Justicia", "tipo": "Feriado inamovible"},
    {"fecha": "2026-04-02", "dia": "Jueves", "motivo": "Dia del Veterano y de los Caidos en la Guerra de Malvinas", "tipo": "Feriado inamovible"},
    {"fecha": "2026-04-03", "dia": "Viernes", "motivo": "Viernes Santo", "tipo": "Feriado inamovible"},
    {"fecha": "2026-05-01", "dia": "Viernes", "motivo": "Dia del Trabajador", "tipo": "Feriado inamovible"},
    {"fecha": "2026-05-25", "dia": "Lunes", "motivo": "Dia de la Revolucion de Mayo", "tipo": "Feriado inamovible"},
    {"fecha": "2026-06-15", "dia": "Lunes", "motivo": "Paso a la Inmortalidad del Gral. Martin Miguel de Guemes", "tipo": "Feriado trasladable"},
    {"fecha": "2026-06-20", "dia": "Sabado", "motivo": "Paso a la Inmortalidad del Gral. Manuel Belgrano", "tipo": "Feriado inamovible"},
    {"fecha": "2026-07-09", "dia": "Jueves", "motivo": "Dia de la Independencia", "tipo": "Feriado inamovible"},
    {"fecha": "2026-07-10", "dia": "Viernes", "motivo": "Dia no laborable con fines turisticos", "tipo": "Turistico"},
    {"fecha": "2026-08-17", "dia": "Lunes", "motivo": "Paso a la Inmortalidad del Gral. Jose de San Martin", "tipo": "Feriado trasladable"},
    {"fecha": "2026-10-12", "dia": "Lunes", "motivo": "Dia del Respeto a la Diversidad Cultural", "tipo": "Feriado trasladable"},
    {"fecha": "2026-11-23", "dia": "Lunes", "motivo": "Dia de la Soberania Nacional", "tipo": "Feriado trasladable"},
    {"fecha": "2026-12-07", "dia": "Lunes", "motivo": "Dia no laborable con fines turisticos", "tipo": "Turistico"},
    {"fecha": "2026-12-08", "dia": "Martes", "motivo": "Inmaculada Concepcion de Maria", "tipo": "Feriado inamovible"},
    {"fecha": "2026-12-25", "dia": "Viernes", "motivo": "Navidad", "tipo": "Feriado inamovible"},
]


class ProrrateoKmRequest(BaseModel):
    destino_id: str = Field(..., min_length=1)
    fecha_inicio: datetime
    fecha_fin: datetime
    km_override: float | None = Field(default=None, ge=0)
    demora_sucursal_horas: float = Field(default=0, ge=0)
    feriados_extra: list[date] = Field(default_factory=list)


class HojasRutaBuscarRequest(BaseModel):
    hojas_ruta: list[str] = Field(default_factory=list)
    feriados_extra: list[date] = Field(default_factory=list)


class HojaRutaEditable(BaseModel):
    hojaruta: str
    destino: str = ""
    distanciadirecta: float | None = Field(default=None, ge=0)
    fesalida: datetime | None = None
    fevuelta: datetime | None = None
    legajo: str = ""
    nombre: str = ""
    nrodoc: str = ""
    demora_sucursal_horas: float = Field(default=0, ge=0)
    estado: str = ""


class FeriadoRequest(BaseModel):
    fecha: date
    motivo: str = Field(..., min_length=1, max_length=200)
    tipo: str = Field(default="Manual", min_length=1, max_length=80)
    activo: bool = True


class HojasRutaCalcularRequest(BaseModel):
    rows: list[HojaRutaEditable] = Field(default_factory=list)
    feriados_extra: list[date] = Field(default_factory=list)


class ExcelConsultaRequest(BaseModel):
    filename: str = "modelo.xlsx"
    content_b64: str = Field(..., min_length=1)


class ExcelExportRequest(ExcelConsultaRequest):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class ExcelRecalcularRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class ViajeMarcaRequest(BaseModel):
    viaje_id: int | None = None
    hoja_fisica_presente: bool | None = None
    estado_manual: str | None = None
    observacion: str = ""


def _destino(destino_id: str) -> dict[str, Any] | None:
    return next((item for item in DESTINOS_KM if item["id"] == destino_id), None)


def _holiday_lookup(extra: list[date], configured: list[dict[str, Any]] | None = None) -> dict[date, dict[str, str]]:
    source = configured if configured is not None else FERIADOS_BASE
    holidays = {date.fromisoformat(str(item["fecha"])): item for item in source}
    for value in extra:
        holidays.setdefault(
            value,
            {"fecha": value.isoformat(), "dia": "", "motivo": "Feriado agregado manualmente", "tipo": "Manual"},
        )
    return holidays


def _overlap_minutes(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> float:
    overlap_start = max(start, window_start)
    overlap_end = min(end, window_end)
    if overlap_end <= overlap_start:
        return 0.0
    return (overlap_end - overlap_start).total_seconds() / 60


def _merge_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not windows:
        return []
    ordered = sorted(windows, key=lambda item: (item["desde"], item["hasta"]))
    merged = [ordered[0].copy()]
    for item in ordered[1:]:
        current = merged[-1]
        if item["desde"] <= current["hasta"]:
            if item["hasta"] > current["hasta"]:
                current["hasta"] = item["hasta"]
            if item["motivo"] not in current["motivo"]:
                current["motivo"] = f"{current['motivo']} + {item['motivo']}"
        else:
            merged.append(item.copy())
    return merged


def _premium_windows(start: datetime, end: datetime, holidays: dict[date, dict[str, str]]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    first_day = start.date() - timedelta(days=2)
    last_day = end.date() + timedelta(days=1)
    day_count = (last_day - first_day).days + 1
    for offset in range(day_count):
        current = first_day + timedelta(days=offset)
        if current.weekday() == 5:
            windows.append(
                {
                    "desde": datetime.combine(current, time(13, 0)),
                    "hasta": datetime.combine(current + timedelta(days=2), time(0, 0)),
                    "motivo": "Fin de semana desde sabado 13:00",
                    "tipo": "fin_semana",
                }
            )
        holiday = holidays.get(current)
        if holiday:
            windows.append(
                {
                    "desde": datetime.combine(current, time.min),
                    "hasta": datetime.combine(current + timedelta(days=1), time.min),
                    "motivo": holiday["motivo"],
                    "tipo": "feriado",
                }
            )
    return _merge_windows(windows)


def _round_pay_percent(value: float) -> int:
    if value <= 0:
        return 0
    # Evita que errores de precisión (por ejemplo 5,0009%) salten al
    # siguiente bloque de pago. La regla comercial trabaja con centésimas.
    normalized = round(float(value), 2)
    return min(100, int(math.ceil(normalized / 5) * 5))


def _calculate_prorrateo(
    km_tramo: float,
    fecha_inicio: datetime,
    fecha_fin: datetime,
    feriados_extra: list[date],
    demora_sucursal_horas: float = 0,
    configured_holidays: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if fecha_fin <= fecha_inicio:
        raise ValueError("El fin del viaje debe ser posterior al inicio.")
    duration_minutes = (fecha_fin - fecha_inicio).total_seconds() / 60
    if duration_minutes > 62 * 24 * 60:
        raise ValueError("El rango maximo inicial es de 62 dias.")
    holidays = _holiday_lookup(feriados_extra, configured_holidays)
    windows = _premium_windows(fecha_inicio, fecha_fin, holidays)
    velocidad_km_h = km_tramo / (duration_minutes / 60) if duration_minutes else 0
    detail = []
    premium_minutes = 0.0
    for window in windows:
        minutes = _overlap_minutes(fecha_inicio, fecha_fin, window["desde"], window["hasta"])
        if minutes <= 0:
            continue
        km = velocidad_km_h * (minutes / 60)
        premium_minutes += minutes
        detail.append(
            {
                "desde": max(fecha_inicio, window["desde"]).isoformat(timespec="minutes"),
                "hasta": min(fecha_fin, window["hasta"]).isoformat(timespec="minutes"),
                "tipo": window["tipo"],
                "motivo": window["motivo"],
                "minutos": minutes,
                "km": km,
                "extra_pct": 100,
            }
        )
    km_100_real = min(km_tramo, velocidad_km_h * (premium_minutes / 60))
    porcentaje_real = (km_100_real * 100 / km_tramo) if km_tramo else 0
    porcentaje_a_pagar = _round_pay_percent(porcentaje_real)
    km_a_pagar = km_tramo * porcentaje_a_pagar / 100
    km_normal = max(0.0, km_tramo - km_100_real)
    conceptos: list[dict[str, Any]] = []
    if duration_minutes >= 24 * 60:
        conceptos.append({"concepto": "Pernocte", "motivo": "El viaje dura 24 horas o más."})
    if demora_sucursal_horas > 2:
        conceptos.append({"concepto": "Torito por demora", "motivo": "La demora en sucursal supera las 2 horas."})
    return {
        "total": km_tramo,
        "normal": km_normal,
        "extra_50": 0.0,
        "extra_100_real": km_100_real,
        "extra_100": km_a_pagar,
        "porcentaje_real_100": porcentaje_real,
        "porcentaje_a_pagar": porcentaje_a_pagar,
        "duracion_minutos": duration_minutes,
        "velocidad_km_h": velocidad_km_h,
        "detalle": detail,
        "conceptos": conceptos,
    }


def _productive_db_local_only_enabled() -> bool:
    return os.getenv("PRODUCTIVE_DB_LOCAL_ONLY", "0").strip().lower() in {"1", "true", "yes", "si"}


async def _auth_username(request: Request | None) -> str:
    if request is None:
        return ""
    auth = await current_auth(request)
    return str((auth or {}).get("username") or "").strip()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _parse_date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    for pattern, length in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10), ("%d-%m-%Y", 10)):
        try:
            return datetime.strptime(text[:length], pattern).date().isoformat()
        except ValueError:
            continue
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else ""


async def _ensure_viajes_tables(db: aiosqlite.Connection | None = None) -> None:
    own_connection = db is None
    if own_connection:
        db = await aiosqlite.connect(DB_PATH)
    assert db is not None
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS herramientas_viajes_importaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archivo_nombre TEXT NOT NULL,
                archivo_hash TEXT NOT NULL,
                fecha_importacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                usuario_importacion TEXT NOT NULL DEFAULT '',
                cantidad_filas INTEGER NOT NULL DEFAULT 0,
                estado TEXT NOT NULL DEFAULT 'procesado',
                observacion TEXT NOT NULL DEFAULT ''
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS herramientas_viajes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                importacion_id INTEGER,
                hoja_ruta TEXT NOT NULL,
                fecha_viaje TEXT NOT NULL,
                hora_viaje TEXT NOT NULL DEFAULT '',
                legajo_excel TEXT NOT NULL DEFAULT '',
                legajo_oracle TEXT NOT NULL DEFAULT '',
                nombre_chofer TEXT NOT NULL DEFAULT '',
                dni TEXT NOT NULL DEFAULT '',
                km_excel REAL,
                km_oracle_ida REAL,
                km_oracle_regreso REAL,
                fecha_salida_oracle TEXT NOT NULL DEFAULT '',
                fecha_regreso_oracle TEXT NOT NULL DEFAULT '',
                horas_totales REAL,
                km_al_100 REAL,
                pernocte INTEGER NOT NULL DEFAULT 0,
                torito INTEGER NOT NULL DEFAULT 0,
                estado_calculo TEXT NOT NULL DEFAULT '',
                estado_viaje TEXT NOT NULL DEFAULT '',
                detalle_calculo_json TEXT NOT NULL DEFAULT '{}',
                sucursales_json TEXT NOT NULL DEFAULT '[]',
                excel_row INTEGER,
                original_json TEXT NOT NULL DEFAULT '[]',
                creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                actualizado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(hoja_ruta, legajo_excel, fecha_viaje)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS herramientas_viajes_marcas (
                viaje_id INTEGER PRIMARY KEY,
                hoja_fisica_presente INTEGER NOT NULL DEFAULT 0,
                estado_manual TEXT NOT NULL DEFAULT '',
                observacion TEXT NOT NULL DEFAULT '',
                usuario_modificacion TEXT NOT NULL DEFAULT '',
                fecha_modificacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS herramientas_viajes_historial (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                viaje_id INTEGER NOT NULL,
                campo TEXT NOT NULL,
                valor_anterior TEXT,
                valor_nuevo TEXT,
                usuario TEXT NOT NULL DEFAULT '',
                fecha_hora DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hv_fecha ON herramientas_viajes(fecha_viaje)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hv_hoja ON herramientas_viajes(hoja_ruta)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hv_importacion ON herramientas_viajes(importacion_id)")
        await db.commit()
    finally:
        if own_connection:
            await db.close()


def _travel_db_values(row: dict[str, Any]) -> dict[str, Any]:
    tramos = row.get("km_tramos") or []
    km_ida = next((t.get("km_oracle") for t in tramos if t.get("tramo") == "Ida"), None)
    km_regreso = next((t.get("km_oracle") for t in tramos if t.get("tramo") == "Regreso"), None)
    return {
        "hoja_ruta": str(row.get("hojaruta") or "").strip(),
        "fecha_viaje": _parse_date_text(row.get("fecha_viaje")),
        "hora_viaje": str(row.get("hora_viaje") or "").strip(),
        "legajo_excel": str(row.get("excel_legajo") or "").strip(),
        "legajo_oracle": str(row.get("legajo") or "").strip(),
        "nombre_chofer": str(row.get("nombre") or "").strip(),
        "dni": str(row.get("nrodoc") or "").strip(),
        "km_excel": row.get("cantidad"),
        "km_oracle_ida": km_ida,
        "km_oracle_regreso": km_regreso,
        "fecha_salida_oracle": str(row.get("fesalida") or ""),
        "fecha_regreso_oracle": str(row.get("fevuelta") or ""),
        "horas_totales": row.get("horas_totales_viaje"),
        "km_al_100": row.get("km_al_100"),
        "pernocte": 1 if row.get("pernocte") else 0,
        "torito": 1 if row.get("torito") else 0,
        "estado_calculo": str(row.get("km_revision") or row.get("estado") or ""),
        "estado_viaje": str(row.get("estado") or ""),
        "detalle_calculo_json": _json_dumps({
            "km_revision": row.get("km_revision") or "",
            "km_tramos": tramos,
            "km_oracle_al_100": row.get("km_oracle_al_100"),
            "km_oracle_total": row.get("km_oracle_total"),
            "porcentaje_global_100": row.get("porcentaje_global_100"),
            "km_base_liquidacion": row.get("km_base_liquidacion") or "excel",
        }),
        "sucursales_json": _json_dumps(row.get("sucursales") or []),
        "excel_row": row.get("excel_row"),
        "original_json": _json_dumps(row.get("original") or []),
    }


async def _store_viajes_importacion(
    filename: str,
    content: bytes,
    rows: list[dict[str, Any]],
    username: str,
) -> tuple[int, list[dict[str, Any]]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_viajes_tables(db)
        digest = hashlib.sha256(content).hexdigest()
        cur = await db.execute(
            """
            INSERT INTO herramientas_viajes_importaciones
                (archivo_nombre, archivo_hash, usuario_importacion, cantidad_filas)
            VALUES (?, ?, ?, ?)
            """,
            (filename or "modelo.xlsx", digest, username, len(rows)),
        )
        import_id = int(cur.lastrowid)
        stored: list[dict[str, Any]] = []
        for row in rows:
            values = _travel_db_values(row)
            if not values["hoja_ruta"] or not values["fecha_viaje"]:
                stored.append(row)
                continue
            await db.execute(
                """
                INSERT INTO herramientas_viajes (
                    importacion_id, hoja_ruta, fecha_viaje, hora_viaje, legajo_excel, legajo_oracle,
                    nombre_chofer, dni, km_excel, km_oracle_ida, km_oracle_regreso, fecha_salida_oracle,
                    fecha_regreso_oracle, horas_totales, km_al_100, pernocte, torito, estado_calculo,
                    estado_viaje, detalle_calculo_json, sucursales_json, excel_row, original_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(hoja_ruta, legajo_excel, fecha_viaje) DO UPDATE SET
                    importacion_id=excluded.importacion_id,
                    hora_viaje=excluded.hora_viaje,
                    legajo_oracle=excluded.legajo_oracle,
                    nombre_chofer=excluded.nombre_chofer,
                    dni=excluded.dni,
                    km_excel=excluded.km_excel,
                    km_oracle_ida=excluded.km_oracle_ida,
                    km_oracle_regreso=excluded.km_oracle_regreso,
                    fecha_salida_oracle=excluded.fecha_salida_oracle,
                    fecha_regreso_oracle=excluded.fecha_regreso_oracle,
                    horas_totales=excluded.horas_totales,
                    km_al_100=excluded.km_al_100,
                    pernocte=excluded.pernocte,
                    torito=excluded.torito,
                    estado_calculo=excluded.estado_calculo,
                    estado_viaje=excluded.estado_viaje,
                    detalle_calculo_json=excluded.detalle_calculo_json,
                    sucursales_json=excluded.sucursales_json,
                    excel_row=excluded.excel_row,
                    original_json=excluded.original_json,
                    actualizado_en=CURRENT_TIMESTAMP
                """,
                (
                    import_id,
                    values["hoja_ruta"],
                    values["fecha_viaje"],
                    values["hora_viaje"],
                    values["legajo_excel"],
                    values["legajo_oracle"],
                    values["nombre_chofer"],
                    values["dni"],
                    values["km_excel"],
                    values["km_oracle_ida"],
                    values["km_oracle_regreso"],
                    values["fecha_salida_oracle"],
                    values["fecha_regreso_oracle"],
                    values["horas_totales"],
                    values["km_al_100"],
                    values["pernocte"],
                    values["torito"],
                    values["estado_calculo"],
                    values["estado_viaje"],
                    values["detalle_calculo_json"],
                    values["sucursales_json"],
                    values["excel_row"],
                    values["original_json"],
                ),
            )
            async with db.execute(
                """
                SELECT v.id, COALESCE(m.hoja_fisica_presente, 0) AS hoja_fisica_presente,
                       COALESCE(m.estado_manual, '') AS estado_manual,
                       COALESCE(m.observacion, '') AS observacion,
                       COALESCE(m.usuario_modificacion, '') AS usuario_modificacion,
                       COALESCE(m.fecha_modificacion, '') AS fecha_modificacion
                FROM herramientas_viajes v
                LEFT JOIN herramientas_viajes_marcas m ON m.viaje_id = v.id
                WHERE v.hoja_ruta = ? AND v.legajo_excel = ? AND v.fecha_viaje = ?
                """,
                (values["hoja_ruta"], values["legajo_excel"], values["fecha_viaje"]),
            ) as cur2:
                mark = await cur2.fetchone()
            enriched = dict(row)
            if mark:
                enriched.update(
                    {
                        "viaje_id": mark["id"],
                        "importacion_id": import_id,
                        "hoja_fisica_presente": bool(mark["hoja_fisica_presente"]),
                        "estado_manual": mark["estado_manual"],
                        "observacion": mark["observacion"],
                        "usuario_modificacion": mark["usuario_modificacion"],
                        "fecha_modificacion": mark["fecha_modificacion"],
                    }
                )
            stored.append(enriched)
        await db.commit()
        return import_id, stored


def _viaje_row_from_db(row: aiosqlite.Row) -> dict[str, Any]:
    detalle = json.loads(row["detalle_calculo_json"] or "{}")
    return {
        "viaje_id": row["id"],
        "importacion_id": row["importacion_id"],
        "fecha_viaje": row["fecha_viaje"],
        "hora_viaje": row["hora_viaje"],
        "excel_legajo": row["legajo_excel"],
        "hojaruta": row["hoja_ruta"],
        "cantidad": row["km_excel"],
        "fesalida": row["fecha_salida_oracle"],
        "fevuelta": row["fecha_regreso_oracle"],
        "horas_totales_viaje": row["horas_totales"],
        "legajo": row["legajo_oracle"],
        "nombre": row["nombre_chofer"],
        "nrodoc": row["dni"],
        "km_al_100": row["km_al_100"],
        "pernocte": bool(row["pernocte"]),
        "torito": bool(row["torito"]),
        "estado": row["estado_viaje"],
        "km_revision": detalle.get("km_revision") or "",
        "km_tramos": detalle.get("km_tramos") or [],
        "km_oracle_al_100": detalle.get("km_oracle_al_100"),
        "km_oracle_total": detalle.get("km_oracle_total"),
        "porcentaje_global_100": detalle.get("porcentaje_global_100"),
        "km_base_liquidacion": detalle.get("km_base_liquidacion") or "excel",
        "sucursales": json.loads(row["sucursales_json"] or "[]"),
        "hoja_fisica_presente": bool(row["hoja_fisica_presente"] or 0),
        "estado_manual": row["estado_manual"] or "",
        "observacion": row["observacion"] or "",
        "usuario_modificacion": row["usuario_modificacion"] or "",
        "fecha_modificacion": row["fecha_modificacion"] or "",
        "archivo_nombre": row["archivo_nombre"] or "",
        "fecha_importacion": row["fecha_importacion"] or "",
    }


def _normalize_legajo_filter(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


async def _query_viajes_guardados(desde: date, hasta: date, legajo: str = "") -> list[dict[str, Any]]:
    await _ensure_viajes_tables()
    legajo_filter = _normalize_legajo_filter(legajo)
    where = ["v.fecha_viaje BETWEEN ? AND ?"]
    params: list[Any] = [desde.isoformat(), hasta.isoformat()]
    if legajo_filter:
        where.append("(v.legajo_excel = ? OR v.legajo_oracle = ?)")
        params.extend([legajo_filter, legajo_filter])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT v.*, i.archivo_nombre, i.fecha_importacion,
                   COALESCE(m.hoja_fisica_presente, 0) AS hoja_fisica_presente,
                   COALESCE(m.estado_manual, '') AS estado_manual,
                   COALESCE(m.observacion, '') AS observacion,
                   COALESCE(m.usuario_modificacion, '') AS usuario_modificacion,
                   COALESCE(m.fecha_modificacion, '') AS fecha_modificacion
            FROM herramientas_viajes v
            LEFT JOIN herramientas_viajes_importaciones i ON i.id = v.importacion_id
            LEFT JOIN herramientas_viajes_marcas m ON m.viaje_id = v.id
            WHERE {' AND '.join(where)}
            ORDER BY v.fecha_viaje, v.hora_viaje, CAST(v.hoja_ruta AS INTEGER), v.hoja_ruta
            """,
            params,
        ) as cur:
            return [_viaje_row_from_db(row) for row in await cur.fetchall()]


async def _update_viajes_guardados(rows: list[dict[str, Any]]) -> None:
    rows = [row for row in rows if row.get("viaje_id")]
    if not rows:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_viajes_tables(db)
        for row in rows:
            values = _travel_db_values(row)
            await db.execute(
                """
                UPDATE herramientas_viajes SET
                    hoja_ruta = ?,
                    fecha_viaje = ?,
                    hora_viaje = ?,
                    legajo_excel = ?,
                    legajo_oracle = ?,
                    nombre_chofer = ?,
                    dni = ?,
                    km_excel = ?,
                    km_oracle_ida = ?,
                    km_oracle_regreso = ?,
                    fecha_salida_oracle = ?,
                    fecha_regreso_oracle = ?,
                    horas_totales = ?,
                    km_al_100 = ?,
                    pernocte = ?,
                    torito = ?,
                    estado_calculo = ?,
                    estado_viaje = ?,
                    detalle_calculo_json = ?,
                    sucursales_json = ?,
                    excel_row = ?,
                    original_json = ?,
                    actualizado_en = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    values["hoja_ruta"],
                    values["fecha_viaje"],
                    values["hora_viaje"],
                    values["legajo_excel"],
                    values["legajo_oracle"],
                    values["nombre_chofer"],
                    values["dni"],
                    values["km_excel"],
                    values["km_oracle_ida"],
                    values["km_oracle_regreso"],
                    values["fecha_salida_oracle"],
                    values["fecha_regreso_oracle"],
                    values["horas_totales"],
                    values["km_al_100"],
                    values["pernocte"],
                    values["torito"],
                    values["estado_calculo"],
                    values["estado_viaje"],
                    values["detalle_calculo_json"],
                    values["sucursales_json"],
                    values["excel_row"],
                    values["original_json"],
                    row["viaje_id"],
                ),
            )
        await db.commit()


async def _save_viaje_marca(viaje_id: int, payload: ViajeMarcaRequest, username: str) -> dict[str, Any]:
    await _ensure_viajes_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id FROM herramientas_viajes WHERE id = ?", (viaje_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Viaje no encontrado.")
        async with db.execute(
            "SELECT hoja_fisica_presente, estado_manual, observacion FROM herramientas_viajes_marcas WHERE viaje_id = ?",
            (viaje_id,),
        ) as cur:
            previous = await cur.fetchone()
        prev = dict(previous) if previous else {"hoja_fisica_presente": 0, "estado_manual": "", "observacion": ""}
        hoja = int(payload.hoja_fisica_presente) if payload.hoja_fisica_presente is not None else int(prev["hoja_fisica_presente"])
        estado = (payload.estado_manual if payload.estado_manual is not None else prev["estado_manual"]) or ""
        observacion = payload.observacion if payload.observacion is not None else (prev["observacion"] or "")
        await db.execute(
            """
            INSERT INTO herramientas_viajes_marcas
                (viaje_id, hoja_fisica_presente, estado_manual, observacion, usuario_modificacion)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(viaje_id) DO UPDATE SET
                hoja_fisica_presente=excluded.hoja_fisica_presente,
                estado_manual=excluded.estado_manual,
                observacion=excluded.observacion,
                usuario_modificacion=excluded.usuario_modificacion,
                fecha_modificacion=CURRENT_TIMESTAMP
            """,
            (viaje_id, hoja, estado, observacion, username),
        )
        for field, old, new in (
            ("hoja_fisica_presente", str(prev["hoja_fisica_presente"]), str(hoja)),
            ("estado_manual", str(prev["estado_manual"] or ""), estado),
            ("observacion", str(prev["observacion"] or ""), observacion),
        ):
            if old != new:
                await db.execute(
                    """
                    INSERT INTO herramientas_viajes_historial
                        (viaje_id, campo, valor_anterior, valor_nuevo, usuario)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (viaje_id, field, old, new, username),
                )
        await db.commit()
        async with db.execute(
            """
            SELECT hoja_fisica_presente, estado_manual, observacion, usuario_modificacion, fecha_modificacion
            FROM herramientas_viajes_marcas WHERE viaje_id = ?
            """,
            (viaje_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else {}


async def _load_holidays() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS herramientas_feriados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL UNIQUE,
                motivo TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'Manual',
                activo INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        async with db.execute("SELECT COUNT(*) FROM herramientas_feriados") as cur:
            count = (await cur.fetchone())[0]
        if not count:
            await db.executemany(
                "INSERT OR IGNORE INTO herramientas_feriados (fecha, motivo, tipo) VALUES (?, ?, ?)",
                [(item["fecha"], item["motivo"], item["tipo"]) for item in FERIADOS_BASE],
            )
            await db.commit()
        async with db.execute(
            "SELECT id, fecha, motivo, tipo, activo FROM herramientas_feriados WHERE activo = 1 ORDER BY fecha"
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def _ensure_holiday_table() -> None:
    await _load_holidays()


def _ensure_java_helper_compiled() -> None:
    javac_bin = os.getenv(
        "PRODUCTIVE_DB_JAVAC_BIN",
        r"C:\Program Files\Android\openjdk\jdk-21.0.8\bin\javac.exe",
    ).strip()
    if not Path(javac_bin).exists():
        raise RuntimeError(f"No se encontro javac para consultar Oracle: {javac_bin}")
    if not JAVA_HELPER_SRC.exists():
        raise RuntimeError(f"No se encontro el helper JDBC de Oracle: {JAVA_HELPER_SRC}")

    JAVA_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    class_file = JAVA_BUILD_DIR / "OracleProductividadQuery.class"
    if class_file.exists() and class_file.stat().st_mtime >= JAVA_HELPER_SRC.stat().st_mtime:
        return
    result = subprocess.run(
        [javac_bin, "-d", str(JAVA_BUILD_DIR), str(JAVA_HELPER_SRC)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"No se pudo compilar el helper JDBC de Oracle. STDERR: {result.stderr.strip() or result.stdout.strip()}")


def _query_oracle_raw_sql(sql: str) -> list[dict[str, Any]]:
    if _productive_db_local_only_enabled():
        raise RuntimeError("La BD productiva Oracle esta temporalmente bloqueada por configuracion.")

    user = os.getenv("PRODUCTIVE_DB_USER", "").strip()
    password = os.getenv("PRODUCTIVE_DB_PASSWORD", "").strip()
    host = os.getenv("PRODUCTIVE_DB_HOST", "").strip()
    port = os.getenv("PRODUCTIVE_DB_PORT", "1521").strip()
    service_name = os.getenv("PRODUCTIVE_DB_SERVICE_NAME", "").strip()
    java_bin = os.getenv(
        "PRODUCTIVE_DB_JAVA_BIN",
        r"C:\Users\207189\AppData\Local\DBeaver\jre\bin\java.exe",
    ).strip()
    ojdbc_jar = os.getenv(
        "PRODUCTIVE_DB_OJDBC_JAR",
        r"C:\Users\207189\AppData\Roaming\DBeaverData\drivers\maven\maven-central\com.oracle.database.jdbc\ojdbc11-23.2.0.0.jar",
    ).strip()

    if not all([user, password, host, service_name]):
        raise RuntimeError("Faltan variables JDBC PRODUCTIVE_DB_USER, PRODUCTIVE_DB_PASSWORD, PRODUCTIVE_DB_HOST o PRODUCTIVE_DB_SERVICE_NAME.")
    if not Path(java_bin).exists():
        raise RuntimeError(f"No se encontro Java para consultar Oracle: {java_bin}")
    if not Path(ojdbc_jar).exists():
        raise RuntimeError(f"No se encontro el driver JDBC Oracle: {ojdbc_jar}")

    _ensure_java_helper_compiled()
    jdbc_url = f"jdbc:oracle:thin:@//{host}:{port}/{service_name}"
    classpath = os.pathsep.join([str(JAVA_BUILD_DIR), ojdbc_jar])
    env = os.environ.copy()
    env["VIGIA_ORACLE_SQL_B64"] = base64.b64encode(sql.encode("utf-8")).decode("ascii")
    command = [
        java_bin,
        "-cp",
        classpath,
        "OracleProductividadQuery",
        jdbc_url,
        user,
        password,
        "2000-01-01 00:00:00",
        "2000-01-01 00:00:00",
        "raw_sql_env",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=int(os.getenv("PRODUCTIVE_DB_JDBC_TIMEOUT_SECONDS", "300")),
    )
    if result.returncode != 0:
        raise RuntimeError(f"No se pudo consultar Oracle via JDBC. STDERR: {result.stderr.strip() or result.stdout.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"La respuesta JDBC no fue JSON valido. Salida: {result.stdout[:300]}") from exc
    return data if isinstance(data, list) else []


def _clean_hojas_ruta(values: list[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        found.extend(re.findall(r"\d+", str(value or "")))
    unique = list(dict.fromkeys(item.lstrip("0") or "0" for item in found))
    if len(unique) > 200:
        raise HTTPException(status_code=400, detail="El maximo por consulta es 200 hojas de ruta.")
    return unique


def _build_hojas_ruta_sql(hojas_ruta: list[str]) -> str:
    in_list = ", ".join(hojas_ruta)
    return f"""
        WITH F810VIAJ_SOURCE AS (
            SELECT HOJARUTA, FESALIDA, FEVUELTA, DDNICOND
            FROM F810VIAJ
            UNION
            SELECT HOJARUTA, FESALIDA, FEVUELTA, DDNICOND
            FROM F810VIAJ_HIST
        )
        SELECT
            TO_CHAR(A.CODIGO) AS HOJARUTA,
            MAX(B.DISTANCIADIRECTA) AS DISTANCIADIRECTA,
            MIN(C.FESALIDA) AS FESALIDA,
            MAX(C.FEVUELTA) AS FEVUELTA,
            MAX(D.LEGAJO) AS LEGAJO,
            MAX(D.NOMBRE) AS NOMBRE,
            MAX(D.NRODOC) AS NRODOC,
            MAX(E.DESCRIPCION) AS DESTINO
        FROM TR_VIAJE A
        JOIN TR_TIEMPO_DE_VIAJE B
          ON (
            (A.CODIGODESITIODESTINO = B.CODIGODESITIO1 AND B.CODIGODESITIO2 = 93)
            OR
            (A.CODIGODESITIODESTINO = B.CODIGODESITIO2 AND B.CODIGODESITIO1 = 93)
          )
        JOIN F810VIAJ_SOURCE C
          ON C.HOJARUTA = TO_CHAR(A.CODIGO)
        LEFT JOIN ACTIVE_EMPLOYEE D
          ON D.NRODOC = C.DDNICOND
        JOIN TR_SITIO E
          ON E.CODIGO = A.CODIGODESITIODESTINO
        WHERE A.CODIGO IN ({in_list})
        GROUP BY TO_CHAR(A.CODIGO)
        ORDER BY TO_NUMBER(TO_CHAR(A.CODIGO))
    """


def _build_excel_hojas_ruta_sql(hojas_ruta: list[str]) -> str:
    in_list = ", ".join(f"'{item}'" for item in hojas_ruta)
    return f"""
        WITH F922_SOURCE AS (
            SELECT HOJARUTA, CLUGENTR, FESALIDA, FEVUELTA, DDNICOND, HORLLEGA, HORASALI
            FROM F922TRAF
            WHERE HOJARUTA IN ({in_list})
            UNION
            SELECT HOJARUTA, CLUGENTR, FESALIDA, FEVUELTA, DDNICOND, HORLLEGA, HORASALI
            FROM F922TRAF_HIST
            WHERE HOJARUTA IN ({in_list})
        )
        SELECT
            TO_CHAR(C.HOJARUTA) AS HOJARUTA,
            C.CLUGENTR AS SUCURSAL,
            C.FESALIDA AS FESALIDA,
            C.FEVUELTA AS FEVUELTA,
            NULL AS LEGAJO,
            D.NOMBRE AS NOMBRE,
            D.NRODOC AS NRODOC,
            C.HORLLEGA AS LLEGADA_SUCURSAL,
            C.HORASALI AS SALIDA_SUCURSAL,
            (SELECT CASE WHEN MIN(B.DISTANCIADIRECTA)=MAX(B.DISTANCIADIRECTA) THEN MIN(B.DISTANCIADIRECTA) END
             FROM TR_TIEMPO_DE_VIAJE B WHERE B.CODIGODESITIO1=93 AND TO_CHAR(B.CODIGODESITIO2)=TRIM(C.CLUGENTR)) AS KM_IDA,
            (SELECT CASE WHEN MIN(B.DISTANCIADIRECTA)=MAX(B.DISTANCIADIRECTA) THEN MIN(B.DISTANCIADIRECTA) END
             FROM TR_TIEMPO_DE_VIAJE B WHERE TO_CHAR(B.CODIGODESITIO1)=TRIM(C.CLUGENTR) AND B.CODIGODESITIO2=93) AS KM_REGRESO
        FROM F922_SOURCE C
        LEFT JOIN ACTIVE_EMPLOYEE D ON D.NRODOC = C.DDNICOND
        ORDER BY TO_NUMBER(C.HOJARUTA), C.HORLLEGA
    """


def _excel_cell_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.time() == time.min:
            return value.date().isoformat()
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="seconds")
    return value


def _read_excel_rows(content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    workbook = load_workbook(io.BytesIO(content), data_only=False)
    sheet = workbook.worksheets[0]
    headers = [str(cell.value or "") for cell in sheet[1]]
    required = {"Fecha viaj", "Legajo", "Cantidad", "Num.Hoj.Ru"}
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(f"Faltan columnas obligatorias: {', '.join(missing)}")
    positions = {name: index for index, name in enumerate(headers)}
    rows = []
    for row_number, cells in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not any(value not in (None, "") for value in cells):
            continue
        route = str(cells[positions["Num.Hoj.Ru"]] or "").strip()
        if not route:
            continue
        rows.append({
            "excel_row": row_number,
            "fecha_viaje": _excel_cell_value(cells[positions["Fecha viaj"]]),
            "hora_viaje": _excel_cell_value(cells[positions.get("Hora viaje", 1)]),
            "excel_legajo": str(cells[positions["Legajo"]] or "").strip(),
            "cantidad": float(cells[positions["Cantidad"]] or 0),
            "hojaruta": route,
            "original": [_excel_cell_value(value) for value in cells],
        })
    return headers, rows


def _oracle_duration_minutes(start: Any, end: Any, reference: datetime | None = None) -> float:
    parsed_start = _parse_oracle_datetime(start)
    parsed_end = _parse_oracle_datetime(end)
    if parsed_start and parsed_end:
        if parsed_end < parsed_start:
            parsed_end += timedelta(days=1)
        return max(0.0, (parsed_end - parsed_start).total_seconds() / 60)
    def parse_clock(value: Any) -> time | None:
        if isinstance(value, time):
            return value
        text = str(value or "").strip()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(text[:8], fmt).time()
            except ValueError:
                pass
        return None
    clock_start, clock_end = parse_clock(start), parse_clock(end)
    if not clock_start or not clock_end:
        return 0.0
    base = reference or datetime.combine(date.today(), time.min)
    left = datetime.combine(base.date(), clock_start)
    right = datetime.combine(base.date(), clock_end)
    if right < left:
        right += timedelta(days=1)
    return (right - left).total_seconds() / 60


def _parse_edit_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return _parse_oracle_datetime(value)


def _calculate_route_payment(stops, start, end, holidays, arrival_override=None, departure_override=None):
    def review(message):
        return {'km_al_100': None, 'km_revision': message, 'km_tramos': [], 'km_oracle_al_100': None, 'km_oracle_total': None, 'porcentaje_global_100': None}
    if not start or not end or end <= start:
        return review('Faltan horarios válidos de salida o regreso al CD.')
    if (end-start).days > 62:
        return review('Duración de viaje fuera de rango.')
    if not stops:
        return review('Faltan sucursales y distancias de Oracle. Consulte nuevamente.')
    if len(stops)>1 and (arrival_override or departure_override):
        return review('La edición manual de horarios de local requiere identificar cada sucursal.')
    arrivals = [_parse_oracle_datetime(r.get('llegada_sucursal')) for r in stops]
    departures = [_parse_oracle_datetime(r.get('salida_sucursal')) for r in stops]
    invalid_stops = [
        str(stop.get('sucursal') or 'sin código')
        for stop, arrival_at, departure_at in zip(stops, arrivals, departures)
        if not arrival_at or not departure_at or not start <= arrival_at <= departure_at <= end
    ]
    if invalid_stops:
        labels = ', '.join(dict.fromkeys(invalid_stops))
        return review(f'Complete llegada y salida válidas para la sucursal {labels}.')
    first = min(range(len(stops)), key=lambda i: arrivals[i])
    last = max(range(len(stops)), key=lambda i: departures[i])
    arrival = arrival_override or arrivals[first]
    departure = departure_override or departures[last]
    if not start < arrival <= departure < end:
        return review('Los extremos de ida y regreso no forman tramos válidos.')
    # No holiday-specific endpoint rule has been agreed yet: do not invent a payout.
    holiday_dates = _holiday_lookup([], holidays)
    segments = [('Ida', start, arrival, stops[first], 'km_ida'),
                ('Regreso', departure, end, stops[last], 'km_regreso')]
    detail = []
    for label, left, right, stop, field in segments:
        if any(_overlap_minutes(left,right,datetime.combine(day,time.min),datetime.combine(day+timedelta(days=1),time.min))>0 for day in holiday_dates):
            return review('Tramo en feriado: falta definir el criterio de pago.')
        premium = 0.0
        for offset in range((right.date()-left.date()).days+3):
            day = left.date()-timedelta(days=1)+timedelta(days=offset)
            if label == 'Ida' and day.weekday()==5 and left.date()==day:
                premium += _overlap_minutes(left,right,datetime.combine(day,time(13)),datetime.combine(day+timedelta(days=2),time.min))
            elif label == 'Ida' and day.weekday()==6:
                premium += _overlap_minutes(left,right,datetime.combine(day,time.min),datetime.combine(day+timedelta(days=1),time.min))
            elif label == 'Regreso' and day.weekday()==5:
                premium += _overlap_minutes(left,right,datetime.combine(day,time(13)),datetime.combine(day+timedelta(days=2),time.min))
        km = stop.get(field)
        if premium and (km is None or not math.isfinite(float(km)) or float(km)<=0):
            return review('Falta una distancia Oracle única y positiva para ' + label.lower() + '.')
        duration_minutes = (right-left).total_seconds()/60
        premium = min(premium, duration_minutes)
        ratio = 100*premium/duration_minutes if duration_minutes else 0
        percent = _round_pay_percent(ratio)
        amount = float(km or 0)*percent/100
        detail.append({'tramo':label,'sucursal':stop.get('sucursal'), 'desde':left.isoformat(),
                       'hasta':right.isoformat(),'km_oracle':km,'porcentaje_real':round(ratio,4),
                       'porcentaje_pago':percent,'km_al_100':round(amount,2)})
    oracle_total = sum(float(r.get('km_oracle') or 0) for r in detail)
    oracle_100 = sum(r['km_al_100'] for r in detail)
    global_percent = _round_pay_percent((oracle_100 * 100 / oracle_total) if oracle_total else 0)
    return {
        'km_al_100': round(oracle_100, 2),
        'km_revision': '',
        'km_tramos': detail,
        'km_oracle_al_100': round(oracle_100, 2),
        'km_oracle_total': round(oracle_total, 2),
        'porcentaje_global_100': global_percent,
    }


def _apply_excel_km_payment(row: dict[str, Any], payment: dict[str, Any]) -> dict[str, Any]:
    result = dict(payment)
    if result.get('km_al_100') is None:
        return result
    try:
        excel_km = float(row.get('cantidad') or 0)
    except (TypeError, ValueError):
        excel_km = 0.0
    oracle_total = float(result.get('km_oracle_total') or 0)
    oracle_100 = float(result.get('km_oracle_al_100') or result.get('km_al_100') or 0)
    percent = _round_pay_percent((oracle_100 * 100 / oracle_total) if oracle_total else 0)
    result['porcentaje_global_100'] = percent
    if percent >= 100:
        result['km_al_100'] = round(excel_km, 2)
        result['km_base_liquidacion'] = 'excel'
    else:
        result['km_al_100'] = round(oracle_100, 2)
        result['km_base_liquidacion'] = 'oracle_tramos'
    return result


async def _consolidate_excel_rows(excel_rows: list[dict[str, Any]], oracle_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_route: dict[str, list[dict[str, Any]]] = {}
    for row in oracle_rows:
        by_route.setdefault(str(_row_value(row, "HOJARUTA") or "").strip(), []).append(row)
    configured = await _load_holidays()
    result = []
    for route, source_rows in _group_excel_routes(excel_rows).items():
        source = source_rows[0]
        raw = by_route.get(route, [])
        normalized = [_normalize_oracle_excel_row(row) for row in raw]
        salida = min((row["fesalida"] for row in normalized if row["fesalida"]), default=None)
        vuelta = max((row["fevuelta"] for row in normalized if row["fevuelta"]), default=None)
        chosen = next((row for row in normalized if row["legajo"] or row["nombre"] or row["nrodoc"]), {})
        delay = max((row["demora_minutos"] for row in normalized), default=0.0)
        pernocte = bool(salida and vuelta and (vuelta - salida).total_seconds() >= 24 * 3600)
        payment = _apply_excel_km_payment(source, _calculate_route_payment(normalized, salida, vuelta, configured))
        complete = bool(raw and salida and vuelta and chosen.get("nombre") and chosen.get("nrodoc"))
        result.append({
            **source,
            "fesalida": salida.isoformat(timespec="minutes") if salida else "",
            "fevuelta": vuelta.isoformat(timespec="minutes") if vuelta else "",
            "horas_totales_viaje": round((vuelta - salida).total_seconds() / 3600, 2) if salida and vuelta else 0,
            "legajo": chosen.get("legajo") or source.get("excel_legajo", ""),
            "nombre": chosen.get("nombre", ""),
            "nrodoc": chosen.get("nrodoc", ""),
            "torito": delay > 120,
            "demora_max_minutos": round(delay, 2),
            "demora_horas": round(delay / 60, 2),
            "llegada_local": "",
            "salida_local": "",
            "sucursales": normalized,
            "pernocte": pernocte,
            **payment,
            "estado": ("Requiere revisión: " + payment['km_revision']) if payment['km_revision'] else ("Validado" if complete else "Incompleto"),
        })
    return result


def _group_excel_routes(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["hojaruta"], []).append(row)
    return grouped


def _normalize_oracle_excel_row(row: dict[str, Any]) -> dict[str, Any]:
    salida = _parse_oracle_datetime(_row_value(row, "FESALIDA"))
    vuelta = _parse_oracle_datetime(_row_value(row, "FEVUELTA"))
    reference = salida or datetime.now()
    return {
        "km_ida": _row_value(row, "KM_IDA"),
        "km_regreso": _row_value(row, "KM_REGRESO"),
        "sucursal": str(_row_value(row, "SUCURSAL") or "").strip(),
        "fesalida": salida,
        "fevuelta": vuelta,
        "legajo": str(_row_value(row, "LEGAJO") or "").strip(),
        "nombre": str(_row_value(row, "NOMBRE") or "").strip(),
        "nrodoc": str(_row_value(row, "NRODOC") or "").strip(),
        "demora_minutos": _oracle_duration_minutes(_row_value(row, "LLEGADA_SUCURSAL"), _row_value(row, "SALIDA_SUCURSAL"), reference),
        "demora_horas": round(_oracle_duration_minutes(_row_value(row, "LLEGADA_SUCURSAL"), _row_value(row, "SALIDA_SUCURSAL"), reference) / 60, 2),
        "llegada_sucursal": str(_row_value(row, "LLEGADA_SUCURSAL") or "").strip(),
        "salida_sucursal": str(_row_value(row, "SALIDA_SUCURSAL") or "").strip(),
    }


def _row_value(row: dict[str, Any], key: str) -> Any:
    return row.get(key) if key in row else row.get(key.lower())


def _parse_oracle_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _normalize_hoja_row(row: dict[str, Any]) -> dict[str, Any]:
    salida = _parse_oracle_datetime(_row_value(row, "FESALIDA"))
    vuelta = _parse_oracle_datetime(_row_value(row, "FEVUELTA"))
    return {
        "hojaruta": str(_row_value(row, "HOJARUTA") or "").strip(),
        "destino": str(_row_value(row, "DESTINO") or "").strip(),
        "distanciadirecta": float(_row_value(row, "DISTANCIADIRECTA") or 0),
        "fesalida": salida.isoformat(timespec="minutes") if salida else "",
        "fevuelta": vuelta.isoformat(timespec="minutes") if vuelta else "",
        "legajo": str(_row_value(row, "LEGAJO") or "").strip(),
        "nombre": str(_row_value(row, "NOMBRE") or "").strip(),
        "nrodoc": str(_row_value(row, "NRODOC") or "").strip(),
        "demora_sucursal_horas": 0,
        "estado": "Datos encontrados.",
    }


async def _calculate_hoja_editable(row: HojaRutaEditable, feriados_extra: list[date]) -> dict[str, Any]:
    base = {
        "hojaruta": row.hojaruta,
        "destino": row.destino,
        "distanciadirecta": row.distanciadirecta,
        "fesalida": row.fesalida.isoformat(timespec="minutes") if row.fesalida else "",
        "fevuelta": row.fevuelta.isoformat(timespec="minutes") if row.fevuelta else "",
        "legajo": row.legajo,
        "nombre": row.nombre,
        "nrodoc": row.nrodoc,
        "demora_sucursal_horas": row.demora_sucursal_horas,
        "estado": row.estado or "",
        "totales": {},
        "detalle": [],
        "conceptos": [],
    }
    if not row.distanciadirecta or not row.fesalida or not row.fevuelta:
        base["estado"] = row.estado or "Faltan datos para calcular."
        return base
    try:
        result = _calculate_prorrateo(
            float(row.distanciadirecta),
            row.fesalida,
            row.fevuelta,
            feriados_extra,
            row.demora_sucursal_horas,
            await _load_holidays(),
        )
    except ValueError as exc:
        base["estado"] = str(exc)
        return base
    base["totales"] = {key: value for key, value in result.items() if key not in {"detalle", "conceptos"}}
    base["detalle"] = result["detalle"]
    base["conceptos"] = result["conceptos"]
    base["estado"] = "Calculado."
    return base


@router.get("/km/destinos")
async def list_km_destinos():
    return {"destinos": DESTINOS_KM, "feriados": await _load_holidays()}


@router.post("/excel/consultar")
async def consultar_excel(req: ExcelConsultaRequest, request: Request):
    try:
        content = base64.b64decode(req.content_b64)
        _headers, excel_rows = _read_excel_rows(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el Excel: {exc}") from exc
    routes = sorted({row["hojaruta"] for row in excel_rows}, key=lambda value: int(value) if value.isdigit() else value)
    sql = _build_excel_hojas_ruta_sql(routes)
    try:
        oracle_rows = _query_oracle_raw_sql(sql)
        consolidated = await _consolidate_excel_rows(excel_rows, oracle_rows)
        import_id, consolidated = await _store_viajes_importacion(
            req.filename,
            content,
            consolidated,
            await _auth_username(request),
        )
    except Exception as exc:
        logger.exception("No se pudo consultar el Excel contra Oracle.")
        raise HTTPException(status_code=502, detail=f"No se pudo consultar Oracle: {exc}") from exc
    return {"filename": req.filename, "importacion_id": import_id, "rows": consolidated, "total": len(consolidated)}


@router.post("/excel/leer")
async def leer_excel(req: ExcelConsultaRequest):
    try:
        content = base64.b64decode(req.content_b64)
        headers, excel_rows = _read_excel_rows(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el Excel: {exc}") from exc
    rows = []
    for row in _group_excel_routes(excel_rows).values():
        item = dict(row[0])
        item.update({
            "fesalida": "",
            "fevuelta": "",
            "legajo": item.get("excel_legajo", ""),
            "nombre": "",
            "nrodoc": "",
            "torito": False,
            "llegada_local": "",
            "salida_local": "",
            "demora_horas": 0,
            "pernocte": False,
            "km_al_100": 0,
            "estado": "Pendiente de consulta Oracle.",
        })
        rows.append(item)
    return {"filename": req.filename, "headers": headers, "rows": rows, "total": len(rows)}


@router.post("/excel/recalcular")
async def recalcular_excel(req: ExcelRecalcularRequest):
    holidays = await _load_holidays()
    recalculated = []
    for row in req.rows:
        item = dict(row)
        start = _parse_oracle_datetime(item.get("fesalida"))
        end = _parse_oracle_datetime(item.get("fevuelta"))
        stops = [dict(stop) for stop in (item.get('sucursales') or []) if isinstance(stop, dict)]
        # Compatibilidad con ediciones anteriores: esos dos campos siempre
        # representaron la única sucursal de la hoja de ruta.
        llegada_local = _parse_edit_datetime(item.get("llegada_local"))
        salida_local = _parse_edit_datetime(item.get("salida_local"))
        if len(stops) == 1 and (llegada_local or salida_local):
            stops[0]["llegada_sucursal"] = llegada_local.isoformat(timespec="minutes") if llegada_local else ""
            stops[0]["salida_sucursal"] = salida_local.isoformat(timespec="minutes") if salida_local else ""
        delays = []
        for stop in stops:
            arrival_at = _parse_edit_datetime(stop.get("llegada_sucursal"))
            departure_at = _parse_edit_datetime(stop.get("salida_sucursal"))
            minutes = _oracle_duration_minutes(arrival_at, departure_at) if arrival_at and departure_at else 0.0
            stop["demora_minutos"] = round(minutes, 2)
            stop["demora_horas"] = round(minutes / 60, 2)
            delays.append(minutes)
        demora_minutos = max(delays, default=0.0)
        item["torito"] = demora_minutos > 120
        item["demora_horas"] = round(demora_minutos / 60, 2)
        item["demora_max_minutos"] = round(demora_minutos, 2)
        item["sucursales"] = stops
        if start and end and end > start:
            payment = _apply_excel_km_payment(item, _calculate_route_payment(stops, start, end, holidays))
            item.update(payment)
            item["pernocte"] = (end - start).total_seconds() >= 24 * 3600
            item["horas_totales_viaje"] = round((end - start).total_seconds() / 3600, 2)
            item["estado"] = "Validado manualmente." if item.get("nombre") and item.get("nrodoc") else "Datos incompletos; completar manualmente."
        else:
            item["km_al_100"] = None
            item["km_revision"] = "Faltan horarios válidos de salida o regreso al CD."
            item["pernocte"] = False
            item["horas_totales_viaje"] = 0
            item["estado"] = "Datos incompletos; completar manualmente."
        if item.get('km_revision'):
            item['estado'] = 'Requiere revisión: ' + item['km_revision']
        recalculated.append(item)
    await _update_viajes_guardados(recalculated)
    return {"rows": recalculated, "total": len(recalculated)}


VIAJE_DIAS = ('Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo')


def viaje_calendar(value, holidays):
    if isinstance(value, datetime):
        day = value.date()
    elif isinstance(value, date):
        day = value
    else:
        day = None
        for pattern, length in (('%Y-%m-%d', 10), ('%d/%m/%Y', 10), ('%d-%m-%Y', 10)):
            try:
                day = datetime.strptime(str(value or '')[:length], pattern).date()
                break
            except ValueError:
                continue
    if day is None:
        return '', 'FFFFFF'
    holiday = any(str(h.get('fecha'))[:10] == day.isoformat() and h.get('activo', 1) for h in holidays)
    color = 'FCE4D6' if holiday else {4:'FFFF00', 5:'FFC000', 6:'92D050'}.get(day.weekday(), 'FFFFFF')
    return VIAJE_DIAS[day.weekday()], color


@router.post("/excel/exportar.xlsx")
async def exportar_excel(req: ExcelExportRequest):
    holidays = await _load_holidays()
    await _update_viajes_guardados(req.rows)
    try:
        content = base64.b64decode(req.content_b64)
        workbook = load_workbook(io.BytesIO(content))
        sheet = workbook.worksheets[0]
        headers = [str(cell.value or "") for cell in sheet[1]]
        positions = {name: index + 1 for index, name in enumerate(headers)}
        route_col = positions.get("Num.Hoj.Ru")
        if not route_col:
            raise ValueError("No existe la columna Num.Hoj.Ru")
        extra_headers = ["KM al 100", "Pernocte", "Torito", "DNI", "Nombre del chofer", "Día Viaje", "Hoja Física Presente", "Estado cálculo KM 100", "KM Oracle ida", "KM Oracle regreso", "% global 100", "KM Oracle al 100", "KM Oracle total"]
        start_col = sheet.max_column + 1
        for offset, header in enumerate(extra_headers):
            sheet.cell(row=1, column=start_col + offset, value=header)
        by_route = {str(row.get("hojaruta") or "").strip(): row for row in req.rows}
        for row_number in range(2, sheet.max_row + 1):
            route = str(sheet.cell(row=row_number, column=route_col).value or "").strip()
            if not route:
                continue
            row = by_route.get(route, {})
            sheet.cell(row=row_number, column=start_col, value=row.get("km_al_100", ""))
            sheet.cell(row=row_number, column=start_col + 1, value=1 if row.get("pernocte") else "")
            sheet.cell(row=row_number, column=start_col + 2, value=1 if row.get("torito") else "")
            sheet.cell(row=row_number, column=start_col + 3, value=row.get("nrodoc", ""))
            sheet.cell(row=row_number, column=start_col + 4, value=row.get("nombre", ""))
            fecha_col = positions.get('Fecha viaj')
            original_fecha = sheet.cell(row_number, fecha_col).value if fecha_col else None
            fecha = row.get('fecha_viaje', original_fecha)
            day_name, color = viaje_calendar(fecha, holidays)
            if fecha_col and row.get('fecha_viaje'):
                sheet.cell(row_number, fecha_col, value=fecha)
            sheet.cell(row_number, start_col + 5, value=day_name)
            sheet.cell(row_number, start_col + 6, value="Sí" if row.get("hoja_fisica_presente") is True else "No")
            sheet.cell(row_number, start_col + 7, value=row.get('km_revision') or row.get('estado', ''))
            for offset, label in ((8,'Ida'),(9,'Regreso')):
                tramo = next((t for t in row.get('km_tramos',[]) if t.get('tramo')==label),{})
                sheet.cell(row_number,start_col+offset,value=tramo.get('km_oracle'))
            sheet.cell(row_number, start_col + 10, value=row.get('porcentaje_global_100'))
            sheet.cell(row_number, start_col + 11, value=row.get('km_oracle_al_100'))
            sheet.cell(row_number, start_col + 12, value=row.get('km_oracle_total'))
            for cell in sheet[row_number]:
                cell.fill = PatternFill('solid', fgColor=color)
        output = io.BytesIO()
        workbook.save(output)
        output.seek(0)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo exportar el Excel: {exc}") from exc
    source_name = Path((req.filename or 'archivo.xlsx').replace('\\', '/')).stem
    source_name = unicodedata.normalize('NFKD', source_name).encode('ascii', 'ignore').decode()
    source_name = re.sub(r'[^A-Za-z0-9_-]+', '_', source_name).strip('_')[:80] or 'archivo'
    timestamp = datetime.now(timezone(timedelta(hours=-3))).strftime('%Y-%m-%d_%H-%M-%S')
    filename = f'Viajes_Larga_Distancia_{source_name}_validado_{timestamp}.xlsx'
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/viajes/{viaje_id}/marca")
async def update_viaje_marca(viaje_id: int, req: ViajeMarcaRequest, request: Request):
    result = await _save_viaje_marca(viaje_id, req, await _auth_username(request))
    return {"ok": True, "marca": result}


@router.get("/viajes")
async def list_viajes(desde: date, hasta: date, legajo: str = ""):
    if hasta < desde:
        raise HTTPException(status_code=400, detail="La fecha hasta debe ser igual o posterior a desde.")
    if (hasta - desde).days > 366:
        raise HTTPException(status_code=400, detail="El rango maximo es de 366 dias.")
    rows = await _query_viajes_guardados(desde, hasta, legajo)
    return {"rows": rows, "total": len(rows)}


def _historico_filename(desde: date, hasta: date, legajo: str = "") -> str:
    legajo_filter = _normalize_legajo_filter(legajo)
    suffix = f"_legajo_{legajo_filter}" if legajo_filter else ""
    return f"Reporte_Viajes_Larga_Distancia_{desde.isoformat()}_a_{hasta.isoformat()}{suffix}.xlsx"


@router.get("/viajes/exportar.xlsx")
async def exportar_viajes_guardados(desde: date, hasta: date, legajo: str = ""):
    if hasta < desde:
        raise HTTPException(status_code=400, detail="La fecha hasta debe ser igual o posterior a desde.")
    rows = await _query_viajes_guardados(desde, hasta, legajo)
    holidays = await _load_holidays()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Viajes"
    headers = [
        "Fecha viaje",
        "Día viaje",
        "Hora viaje",
        "Legajo Excel",
        "Legajo Oracle",
        "Nombre chofer",
        "DNI",
        "Hoja ruta",
        "Hoja Física Presente",
        "KM Excel",
        "KM Oracle ida",
        "KM Oracle regreso",
        "% global 100",
        "KM Oracle al 100",
        "KM Oracle total",
        "Salida Oracle",
        "Regreso Oracle",
        "Horas totales",
        "KM al 100",
        "Pernocte",
        "Torito",
        "Estado cálculo",
        "Observación",
        "Usuario modificación",
        "Fecha modificación",
        "Archivo origen",
        "Fecha importación",
    ]
    sheet.append(headers)
    for item in rows:
        day_name, color = viaje_calendar(item.get("fecha_viaje"), holidays)
        tramos = item.get("km_tramos") or []
        row_values = [
            item.get("fecha_viaje", ""),
            day_name,
            item.get("hora_viaje", ""),
            item.get("excel_legajo", ""),
            item.get("legajo", ""),
            item.get("nombre", ""),
            item.get("nrodoc", ""),
            item.get("hojaruta", ""),
            "Sí" if item.get("hoja_fisica_presente") else "No",
            item.get("cantidad"),
            next((t.get("km_oracle") for t in tramos if t.get("tramo") == "Ida"), None),
            next((t.get("km_oracle") for t in tramos if t.get("tramo") == "Regreso"), None),
            item.get("porcentaje_global_100"),
            item.get("km_oracle_al_100"),
            item.get("km_oracle_total"),
            item.get("fesalida", ""),
            item.get("fevuelta", ""),
            item.get("horas_totales_viaje"),
            item.get("km_al_100"),
            "Sí" if item.get("pernocte") else "",
            "Sí" if item.get("torito") else "",
            item.get("km_revision") or item.get("estado", ""),
            item.get("observacion", ""),
            item.get("usuario_modificacion", ""),
            item.get("fecha_modificacion", ""),
            item.get("archivo_nombre", ""),
            item.get("fecha_importacion", ""),
        ]
        sheet.append(row_values)
        for cell in sheet[sheet.max_row]:
            cell.fill = PatternFill("solid", fgColor=color)
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{_historico_filename(desde, hasta, legajo)}"'},
    )


@router.get("/km/feriados")
async def list_feriados():
    return {"feriados": await _load_holidays()}


@router.post("/km/feriados")
async def create_feriado(req: FeriadoRequest):
    await _ensure_holiday_table()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO herramientas_feriados (fecha, motivo, tipo, activo) VALUES (?, ?, ?, ?)",
                (req.fecha.isoformat(), req.motivo.strip(), req.tipo.strip(), int(req.activo)),
            )
            await db.commit()
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Ya existe un feriado para esa fecha.") from exc
    return {"feriados": await _load_holidays()}


@router.put("/km/feriados/{feriado_id}")
async def update_feriado(feriado_id: int, req: FeriadoRequest):
    await _ensure_holiday_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE herramientas_feriados SET fecha = ?, motivo = ?, tipo = ?, activo = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (req.fecha.isoformat(), req.motivo.strip(), req.tipo.strip(), int(req.activo), feriado_id),
        )
        await db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Feriado no encontrado.")
    return {"feriados": await _load_holidays()}


@router.delete("/km/feriados/{feriado_id}")
async def delete_feriado(feriado_id: int):
    await _ensure_holiday_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM herramientas_feriados WHERE id = ?", (feriado_id,))
        await db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Feriado no encontrado.")
    return {"feriados": await _load_holidays()}


@router.post("/km/prorratear")
async def prorratear_km(req: ProrrateoKmRequest):
    destino = _destino(req.destino_id)
    if not destino:
        raise HTTPException(status_code=400, detail="Destino no configurado.")
    km_tramo = float(req.km_override if req.km_override is not None else float(destino["km"]) / 2)
    try:
        calculated = _calculate_prorrateo(
            km_tramo,
            req.fecha_inicio,
            req.fecha_fin,
            req.feriados_extra,
            req.demora_sucursal_horas,
            await _load_holidays(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    totals = {key: value for key, value in calculated.items() if key not in {"detalle", "conceptos"}}
    return {
        "destino": destino,
        "km_tramo": km_tramo,
        "fecha_inicio": req.fecha_inicio.isoformat(timespec="minutes"),
        "fecha_fin": req.fecha_fin.isoformat(timespec="minutes"),
        "dias": len({req.fecha_inicio.date() + timedelta(days=offset) for offset in range((req.fecha_fin.date() - req.fecha_inicio.date()).days + 1)}),
        "totales": totals,
        "detalle": calculated["detalle"],
        "criterio": "Version inicial segun Excel: se calcula la proporcion del tramo que cae en ventanas al 100%. Fin de semana desde sabado 13:00 hasta lunes 00:00 y feriados completos al 100%. El 50% queda fuera.",
        "conceptos": calculated["conceptos"],
    }


@router.post("/km/hojas-ruta/buscar")
async def buscar_hojas_ruta(req: HojasRutaBuscarRequest):
    hojas = _clean_hojas_ruta(req.hojas_ruta)
    if not hojas:
        raise HTTPException(status_code=400, detail="Pegue al menos una hoja de ruta.")
    sql = _build_hojas_ruta_sql(hojas)
    try:
        oracle_rows = _query_oracle_raw_sql(sql)
    except Exception as exc:
        logger.exception("No se pudieron consultar hojas de ruta en Oracle.")
        raise HTTPException(status_code=502, detail=f"No se pudo consultar Oracle: {exc}") from exc

    by_hoja = {_normalize_hoja_row(row)["hojaruta"]: _normalize_hoja_row(row) for row in oracle_rows}
    rows: list[dict[str, Any]] = []
    for hoja in hojas:
        item = by_hoja.get(hoja)
        if not item:
            rows.append(
                {
                    "hojaruta": hoja,
                    "distanciadirecta": None,
                    "fesalida": "",
                    "fevuelta": "",
                    "legajo": "",
                    "nombre": "",
                    "nrodoc": "",
                    "demora_sucursal_horas": 0,
                    "estado": "No encontrada en Oracle.",
                    "totales": {},
                    "detalle": [],
                    "conceptos": [],
                }
            )
            continue
        editable = HojaRutaEditable(**item)
        rows.append(await _calculate_hoja_editable(editable, req.feriados_extra))
    return {"rows": rows, "encontradas": sum(1 for row in rows if row["estado"] == "Calculado."), "total": len(rows)}


@router.post("/km/hojas-ruta/calcular")
async def calcular_hojas_ruta(req: HojasRutaCalcularRequest):
    rows = [await _calculate_hoja_editable(row, req.feriados_extra) for row in req.rows]
    return {"rows": rows, "total": len(rows)}


@router.post("/km/hojas-ruta/exportar.csv")
async def exportar_hojas_ruta(req: HojasRutaCalcularRequest):
    rows = [await _calculate_hoja_editable(row, req.feriados_extra) for row in req.rows]
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", lineterminator="\n")
    writer.writerow(
        [
            "Hoja de ruta",
            "Destino",
            "KM tramo",
            "Salida",
            "Vuelta",
            "Legajo",
            "Nombre",
            "Documento",
            "% real 100",
            "% pago 100",
            "KM paga 100",
            "KM normal",
            "Demora sucursal (h)",
            "Conceptos",
            "Estado",
        ]
    )
    for row in rows:
        totals = row.get("totales") or {}
        writer.writerow(
            [
                row.get("hojaruta", ""),
                row.get("destino", ""),
                row.get("distanciadirecta", ""),
                row.get("fesalida", ""),
                row.get("fevuelta", ""),
                row.get("legajo", ""),
                row.get("nombre", ""),
                row.get("nrodoc", ""),
                round(float(totals.get("porcentaje_real_100") or 0), 2),
                int(totals.get("porcentaje_a_pagar") or 0),
                round(float(totals.get("extra_100") or 0), 2),
                round(float(totals.get("normal") or 0), 2),
                row.get("demora_sucursal_horas", 0),
                ", ".join(item.get("concepto", "") for item in row.get("conceptos", [])),
                row.get("estado", ""),
            ]
        )
    filename = f"prorrateador_km_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


from routers.herramientas_horas import router as horas_router
router.include_router(horas_router)
