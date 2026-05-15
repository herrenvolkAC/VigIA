"""
VigIA - Novedades CD / RRHH.

Importa archivos fuente del proceso RRHH y expone reportes operativos.
RRHH solo deja los Excels; VigIA normaliza, guarda y filtra por permisos.
"""
from __future__ import annotations

import json
import hashlib
import re
import shutil
import sqlite3
import subprocess
import tempfile
import asyncio
import csv
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from db.schema import DB_PATH
from routers.auth_local import current_auth

try:
    from openpyxl import load_workbook
except Exception:  # pragma: no cover
    load_workbook = None

try:
    import xlrd
except Exception:  # pragma: no cover
    xlrd = None


router = APIRouter(prefix="/api/rrhh", tags=["rrhh-novedades"])

SOURCE_ROOT = Path(__file__).parent.parent / "Docs" / "Panel_Choferes" / "PROCESADOS"
FULL_ACCESS_ROLES = {"admin", "rrhh"}
IMPORT_ROLES = {"admin", "rrhh"}


class ImportFolderRequest(BaseModel):
    folder_path: str | None = None
    batch_key: str | None = None
    force: bool = False


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_legajo(value: Any) -> str:
    text = _norm(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+(?:\.0)?", text):
        text = text.split(".", 1)[0]
    stripped = text.lstrip("0")
    return stripped or "0"


def _norm_codigo(value: Any) -> str:
    text = _norm(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+(?:\.0)?", text):
        text = text.split(".", 1)[0]
    stripped = text.lstrip("0")
    return stripped or "0"


def _norm_key(value: Any) -> str:
    value = _norm(value).lower()
    value = (
        value.replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
        .replace("ä", "a")
    )
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = _norm(value).replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _to_hours(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, datetime):
        return value.hour + value.minute / 60 + value.second / 3600
    if isinstance(value, time):
        return value.hour + value.minute / 60 + value.second / 3600
    if isinstance(value, (int, float)):
        return float(value)
    text = _norm(value).replace(",", ".")
    if not text:
        return 0.0
    match = re.match(r"^(-?\d{1,4}):(\d{2})(?::(\d{2}))?$", text)
    if match:
        sign = -1 if match.group(1).startswith("-") else 1
        hours = abs(int(match.group(1)))
        minutes = int(match.group(2))
        seconds = int(match.group(3) or 0)
        return sign * (hours + minutes / 60 + seconds / 3600)
    return _to_float(text)


def _pick_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def _to_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _norm(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return text


def _to_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, time()).strftime("%Y-%m-%d %H:%M:%S")
    text = _norm(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return text


def _to_time_text(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.strftime("%H:%M:%S")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    text = _norm(value)
    return text or None


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return value


def _raw_json(headers: list[str], row: list[Any]) -> str:
    return json.dumps(
        {headers[i]: _json_value(row[i]) if i < len(row) else None for i in range(len(headers))},
        ensure_ascii=False,
    )


def _unique_headers(values: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for idx, value in enumerate(values):
        key = _norm_key(value) or f"col_{idx + 1}"
        count = seen.get(key, 0)
        seen[key] = count + 1
        out.append(key if count == 0 else f"{key}_{count + 1}")
    return out


def _is_gerencia(row: dict[str, Any]) -> int:
    haystack = " ".join(
        _norm(row.get(key))
        for key in (
            "desc_funcion",
            "desc_posicion",
            "desc_unidad_organizativa",
            "desc_sector_generico",
            "grupo_profesional",
        )
    ).upper()
    return 1 if any(token in haystack for token in ("GEREN", "JEF", "JEFE", "JEFAT")) else 0


PERSONA_MASTER_FIELDS = (
    "legajo", "nombre", "empresa", "division_personal", "sucursal",
    "unidad_organizativa", "desc_unidad_organizativa", "sector_generico",
    "desc_sector_generico", "clave_funcion", "desc_funcion", "posicion",
    "desc_posicion", "grupo_personal", "desc_grupo_personal", "area_personal",
    "desc_area_personal", "area_nomina", "clase_contrato", "desc_tipo_contrato",
    "regla_plan_horario", "jubilado", "centro_coste", "fecha_ingreso",
    "fecha_baja", "antiguedad_anios", "antiguedad_meses", "antiguedad_dias",
    "proveedor", "razon_social", "es_gerencia", "raw_json",
)


def _persona_hash(item: dict[str, Any]) -> str:
    data = {key: item.get(key) for key in PERSONA_MASTER_FIELDS if key != "raw_json"}
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_xlsx(path: Path, sheet: str | None = None) -> list[list[Any]]:
    if load_workbook is None:
        raise RuntimeError("openpyxl no esta disponible para leer archivos .xlsx.")
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        return [list(row) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _read_zipped_excel_with_legacy_extension(path: Path, sheet: str | None = None) -> list[list[Any]]:
    with tempfile.TemporaryDirectory() as tmp:
        copied = Path(tmp) / f"{path.stem}.xlsx"
        shutil.copy2(path, copied)
        return _read_xlsx(copied, sheet)


def _read_xls(path: Path, sheet: str | None = None) -> list[list[Any]]:
    with open(path, "rb") as fh:
        sample = fh.read(512)
        if sample[:2] == b"PK":
            return _read_zipped_excel_with_legacy_extension(path, sheet)

    if xlrd is not None:
        try:
            book = xlrd.open_workbook(str(path))
            ws = book.sheet_by_name(sheet) if sheet else book.sheet_by_index(0)
            rows: list[list[Any]] = []
            for r in range(ws.nrows):
                out = []
                for c in range(ws.ncols):
                    cell = ws.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        out.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                    else:
                        out.append(cell.value)
                rows.append(out)
            return rows
        except Exception:
            if b"\t" in sample or b";" in sample:
                return _read_delimited_legacy_xls(path, sample)
            raise

    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if converter:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [converter, "--headless", "--convert-to", "xlsx", "--outdir", tmp, str(path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            converted = Path(tmp) / f"{path.stem}.xlsx"
            if not converted.exists():
                raise RuntimeError(f"No se pudo convertir {path.name} a .xlsx.")
            return _read_xlsx(converted, sheet)

    raise RuntimeError(
        f"{path.name} es .xls legado. Instala xlrd>=2.0.1 o LibreOffice para importarlo."
    )


def _read_delimited_legacy_xls(path: Path, sample: bytes | None = None) -> list[list[Any]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin1", errors="replace")
    delimiter = "\t" if (sample or raw[:512]).count(b"\t") >= (sample or raw[:512]).count(b";") else ";"
    return [row for row in csv.reader(text.splitlines(), delimiter=delimiter)]


def _read_workbook_rows(path: Path, sheet: str | None = None) -> list[list[Any]]:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        return _read_xls(path, sheet)
    return _read_xlsx(path, sheet)


def _find_latest_folder() -> Path:
    if not SOURCE_ROOT.exists():
        raise RuntimeError(f"No existe la carpeta {SOURCE_ROOT}.")
    folders = [p for p in SOURCE_ROOT.iterdir() if p.is_dir()]
    if not folders:
        raise RuntimeError(f"No hay carpetas mensuales en {SOURCE_ROOT}.")
    return max(folders, key=lambda p: p.stat().st_mtime)


def _pick_files(folder: Path, patterns: list[str], exclude: list[str] | None = None) -> list[Path]:
    exclude = [item.lower() for item in (exclude or [])]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(folder.glob(pattern))
    unique = {
        p.resolve(): p for p in candidates
        if p.is_file()
        and p.suffix.lower() in {".xlsx", ".xls"}
        and not any(token in p.name.lower() for token in exclude)
    }
    return sorted(unique.values(), key=lambda p: (p.stat().st_mtime, p.name.lower()))


def _pick_file(folder: Path, patterns: list[str], exclude: list[str] | None = None) -> Path | None:
    candidates = _pick_files(folder, patterns, exclude)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _stringify_files(files: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in files.items():
        if isinstance(value, list):
            if value:
                out[key] = [str(item) for item in value]
        elif value is not None:
            out[key] = str(value)
    return out


def _as_paths(files: dict[str, Any], key: str) -> list[Path]:
    value = files.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return [Path(item) for item in value]
    return [Path(value)]


def _detect_files(folder: Path) -> dict[str, Any]:
    files = {
        "actividad": _pick_file(folder, ["*Actividad*.xlsx", "*ACTIVIDAD*.XLS", "*ACTIVIDAD*.xls"], ["full_base"]),
        "actividad_files": _pick_files(folder, ["*Actividad*.xlsx", "*ACTIVIDAD*.XLS", "*ACTIVIDAD*.xls"], ["full_base"]),
        "fichadas": _pick_file(folder, ["*Fichadas*.xlsx", "*FICHADAS*.XLS", "*FICHADAS*.xls"]),
        "legajero": _pick_file(folder, ["*Legajero*.xlsx", "*LEGAJERO*.XLS", "*LEGAJERO*.xls"]),
        "sanciones": _pick_file(folder, ["*SANCIONES*.xlsx", "*SANCIONES*.XLS", "*Sanciones*.xls"]),
        "sanciones_files": _pick_files(folder, ["*SANCIONES*.xlsx", "*SANCIONES*.XLS", "*Sanciones*.xls"]),
        "codigos_ausentismo": _pick_file(folder, ["*Codigos_Ausentismo*.xlsx", "*Codigos_Ausentismo*.xls"]),
    }
    required = ["actividad", "legajero"]
    missing = [key for key in required if files[key] is None]
    if missing:
        raise RuntimeError(f"Faltan archivos requeridos en {folder}: {', '.join(missing)}.")
    return _stringify_files(files)


def _row_dict(headers: list[str], row: list[Any]) -> dict[str, Any]:
    return {headers[i]: row[i] if i < len(row) else None for i in range(len(headers))}


def _sync_personas_master(cur: sqlite3.Cursor, batch_id: int, items: list[dict[str, Any]]) -> dict[str, int]:
    now = _now()
    stats = {"altas": 0, "modificaciones": 0, "bajas": 0, "reactivaciones": 0, "sin_cambios": 0}
    current_by_legajo = {item["legajo"]: item for item in items}
    seen_legajos = set(current_by_legajo)

    cur.execute("SELECT * FROM rrhh_personas")
    existing = {row["legajo"]: dict(row) for row in cur.fetchall()}

    for legajo, item in current_by_legajo.items():
        item_hash = _persona_hash(item)
        row = existing.get(legajo)
        if row is None:
            cur.execute(
                """
                INSERT INTO rrhh_personas (
                    legajo, nombre, empresa, division_personal, sucursal,
                    unidad_organizativa, desc_unidad_organizativa, sector_generico,
                    desc_sector_generico, clave_funcion, desc_funcion, posicion,
                    desc_posicion, grupo_personal, desc_grupo_personal, area_personal,
                    desc_area_personal, area_nomina, clase_contrato, desc_tipo_contrato,
                    regla_plan_horario, jubilado, centro_coste, fecha_ingreso, fecha_baja,
                    antiguedad_anios, antiguedad_meses, antiguedad_dias, proveedor,
                    razon_social, es_gerencia, active, first_seen_batch_id,
                    last_seen_batch_id, last_changed_batch_id, first_seen_at,
                    last_seen_at, data_hash, change_count, raw_json, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 1, ?, ?
                )
                """,
                tuple(item.get(key) for key in PERSONA_MASTER_FIELDS[:-1])
                + (batch_id, batch_id, batch_id, now, now, item_hash, item["raw_json"], now),
            )
            cur.execute(
                """
                INSERT INTO rrhh_personas_changes (batch_id, legajo, change_type, old_json, new_json)
                VALUES (?, ?, 'alta', NULL, ?)
                """,
                (batch_id, legajo, item["raw_json"]),
            )
            stats["altas"] += 1
            continue

        if row.get("data_hash") == item_hash and int(row.get("active") or 0) == 1:
            cur.execute(
                "UPDATE rrhh_personas SET last_seen_batch_id = ?, last_seen_at = ?, updated_at = ? WHERE legajo = ?",
                (batch_id, now, now, legajo),
            )
            stats["sin_cambios"] += 1
            continue

        change_type = "reactivacion" if int(row.get("active") or 0) == 0 else "modificacion"
        cur.execute(
            """
            UPDATE rrhh_personas
            SET nombre = ?, empresa = ?, division_personal = ?, sucursal = ?,
                unidad_organizativa = ?, desc_unidad_organizativa = ?, sector_generico = ?,
                desc_sector_generico = ?, clave_funcion = ?, desc_funcion = ?, posicion = ?,
                desc_posicion = ?, grupo_personal = ?, desc_grupo_personal = ?, area_personal = ?,
                desc_area_personal = ?, area_nomina = ?, clase_contrato = ?, desc_tipo_contrato = ?,
                regla_plan_horario = ?, jubilado = ?, centro_coste = ?, fecha_ingreso = ?,
                fecha_baja = ?, antiguedad_anios = ?, antiguedad_meses = ?, antiguedad_dias = ?,
                proveedor = ?, razon_social = ?, es_gerencia = ?, active = 1,
                last_seen_batch_id = ?, last_changed_batch_id = ?, last_seen_at = ?,
                deactivated_at = NULL, data_hash = ?, change_count = change_count + 1,
                raw_json = ?, updated_at = ?
            WHERE legajo = ?
            """,
            tuple(item.get(key) for key in PERSONA_MASTER_FIELDS[1:])
            + (batch_id, batch_id, now, item_hash, item["raw_json"], now, legajo),
        )
        cur.execute(
            """
            INSERT INTO rrhh_personas_changes (batch_id, legajo, change_type, old_json, new_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (batch_id, legajo, change_type, row.get("raw_json"), item["raw_json"]),
        )
        stats["reactivaciones" if change_type == "reactivacion" else "modificaciones"] += 1

    for legajo, row in existing.items():
        if legajo in seen_legajos or int(row.get("active") or 0) == 0:
            continue
        cur.execute(
            """
            UPDATE rrhh_personas
            SET active = 0, last_changed_batch_id = ?, deactivated_at = ?, updated_at = ?,
                change_count = change_count + 1
            WHERE legajo = ?
            """,
            (batch_id, now, now, legajo),
        )
        cur.execute(
            """
            INSERT INTO rrhh_personas_changes (batch_id, legajo, change_type, old_json, new_json)
            VALUES (?, ?, 'baja', ?, NULL)
            """,
            (batch_id, legajo, row.get("raw_json")),
        )
        stats["bajas"] += 1

    return stats


def _import_legajero(cur: sqlite3.Cursor, batch_id: int, path: Path) -> dict[str, int]:
    rows = _read_workbook_rows(path)
    headers = _unique_headers(rows[0])
    inserted = 0
    gerencia_by_legajo: dict[str, int] = {}
    payload = []
    master_items: list[dict[str, Any]] = []
    for row in rows[1:]:
        data = _row_dict(headers, row)
        legajo = _norm_legajo(data.get("legajo"))
        if not legajo:
            continue
        item = {
            "legajo": legajo,
            "nombre": _norm(data.get("nombre_del_empleado_o_candidato")),
            "empresa": _norm(data.get("empresa")),
            "division_personal": _norm(data.get("division_de_personal")),
            "sucursal": _norm(data.get("suc")),
            "unidad_organizativa": _norm(data.get("unidad_organizativa")),
            "desc_unidad_organizativa": _norm(data.get("desc_unid_organiz")),
            "sector_generico": _norm(data.get("sector_generico")),
            "desc_sector_generico": _norm(data.get("descrip_sector_generico")),
            "clave_funcion": _norm(data.get("clave_de_funcion")),
            "desc_funcion": _norm(data.get("desc_funcion")),
            "posicion": _norm(data.get("posicion")),
            "desc_posicion": _norm(data.get("desc_posicion")),
            "grupo_personal": _norm(data.get("grupo_de_personal")),
            "desc_grupo_personal": _norm(data.get("desc_grupo_de_personal")),
            "area_personal": _norm(data.get("area_de_personal")),
            "desc_area_personal": _norm(data.get("desc_area_de_personal")),
            "area_nomina": _norm(data.get("area_nomina")),
            "clase_contrato": _norm(data.get("clase_contrato")),
            "desc_tipo_contrato": _norm(data.get("desc_tipo_contrato")),
            "regla_plan_horario": _norm(data.get("regla_plan_hor_trab")),
            "jubilado": _norm(data.get("jubilado")),
            "centro_coste": _norm(data.get("centro_de_coste")),
            "fecha_ingreso": _to_date(data.get("fecha_de_ingreso")),
            "fecha_baja": _to_date(data.get("fecha_de_baja")),
            "antiguedad_anios": _to_float(data.get("antiguedad_anos")),
            "antiguedad_meses": _to_float(data.get("antiguedad_meses")),
            "antiguedad_dias": _to_float(data.get("antiguedad_dias")),
            "proveedor": _norm(data.get("proveedor")),
            "razon_social": _norm(data.get("razon_social")),
            "raw_json": _raw_json(headers, row),
        }
        es_gerencia = _is_gerencia(item)
        item["es_gerencia"] = es_gerencia
        gerencia_by_legajo[legajo] = es_gerencia
        master_items.append(item)
        payload.append((
            batch_id, item["legajo"], item["nombre"], item["empresa"], item["division_personal"],
            item["sucursal"], item["unidad_organizativa"], item["desc_unidad_organizativa"],
            item["sector_generico"], item["desc_sector_generico"], item["clave_funcion"],
            item["desc_funcion"], item["posicion"], item["desc_posicion"], item["grupo_personal"],
            item["desc_grupo_personal"], item["area_personal"], item["desc_area_personal"],
            item["fecha_ingreso"], item["fecha_baja"], item["proveedor"], item["razon_social"],
            item["raw_json"], es_gerencia,
        ))
        inserted += 1
    cur.executemany(
        """
        INSERT OR REPLACE INTO rrhh_legajero (
            batch_id, legajo, nombre, empresa, division_personal, sucursal,
            unidad_organizativa, desc_unidad_organizativa, sector_generico,
            desc_sector_generico, clave_funcion, desc_funcion, posicion,
            desc_posicion, grupo_personal, desc_grupo_personal, area_personal,
            desc_area_personal, fecha_ingreso, fecha_baja, proveedor, razon_social,
            raw_json, es_gerencia
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    master_stats = _sync_personas_master(cur, batch_id, master_items)
    return {"inserted": inserted, "gerencia_map": gerencia_by_legajo, **master_stats}


def _import_actividad(
    cur: sqlite3.Cursor,
    batch_id: int,
    path: Path,
    gerencia: dict[str, int],
    uo_sector_map: dict[str, str] | None = None,
    seen: set[tuple[str, str]] | None = None,
    codes: dict[str, dict[str, str]] | None = None,
    no_count_patterns: list[str] | None = None,
) -> int:
    rows = _read_workbook_rows(path)
    headers = _unique_headers(rows[0])
    payload = []
    seen = seen if seen is not None else set()
    uo_sector_map = uo_sector_map or {}
    codes = codes or {}
    no_count_patterns = no_count_patterns or []
    for row in rows[1:]:
        data = _row_dict(headers, row)
        legajo = _norm_legajo(data.get("legajo"))
        fecha = _to_date(data.get("fecha"))
        if not legajo or not fecha:
            continue
        dedupe_key = (legajo, fecha)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        sector = _norm(data.get("sector"))
        aus_pres = _norm(data.get("aus_pres"))
        motivo = _norm(data.get("motivo"))
        horario = _norm(data.get("horario"))
        aus_info = _classify_ausentismo(aus_pres, motivo, horario, codes, no_count_patterns)
        payload.append((
            batch_id, legajo, _norm(data.get("empleado")), fecha,
            _norm(data.get("division")), _norm(data.get("subdivision")), uo_sector_map.get(sector, sector),
            _norm(data.get("grupo_profesional")), _norm(data.get("area_de_personal")),
            _norm(data.get("dia")), _norm(data.get("pausa")), horario,
            aus_pres, aus_info["codigo_norm"], aus_info["tratamiento"], aus_info["tipo"],
            aus_info["clasificacion"], aus_info["contabiliza"], aus_info["regla"],
            motivo, _norm(data.get("comida")),
            _to_time_text(data.get("entrada")), _to_time_text(data.get("p1_ini")),
            _to_time_text(data.get("p1_fin")), _norm(data.get("mas")), _to_time_text(data.get("salida")),
            _to_hours(data.get("hs_trab")), _to_hours(_pick_value(data, "hs_ext_realiz", "hs_50")),
            _to_hours(_pick_value(data, "hs_50_autorizadas", "hs_extras_autoriz")),
            _to_hours(data.get("hs_100")),
            _to_hours(data.get("recargo_50")), _to_hours(data.get("recargo_100")),
            _to_hours(data.get("rec_noct")), _to_hours(data.get("hs_fer")),
            _to_hours(data.get("tarde")), _to_float(data.get("viajes_equiv")),
            gerencia.get(legajo, 0), _raw_json(headers, row),
        ))
    cur.executemany(
        """
        INSERT INTO rrhh_actividad_diaria (
            batch_id, legajo, empleado, fecha, division, subdivision, sector,
            grupo_profesional, area_personal, dia, pausa, horario, aus_pres_codigo,
            aus_pres_codigo_norm, ausentismo_tratamiento, ausentismo_tipo,
            ausentismo_clasificacion, ausentismo_contabiliza, ausentismo_regla,
            motivo, comida, entrada, p1_ini, p1_fin, mas, salida, hs_trab,
            hs_ext_realiz, hs_50_autorizadas, hs_100, recargo_50, recargo_100,
            rec_noct, hs_fer, tarde, viajes_equiv, es_gerencia, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)


def _unidad_sector_map(cur: sqlite3.Cursor, batch_id: int) -> dict[str, str]:
    cur.execute(
        """
        SELECT unidad_organizativa, desc_sector_generico, COUNT(*) c
        FROM rrhh_legajero
        WHERE batch_id = ?
          AND TRIM(COALESCE(unidad_organizativa,'')) <> ''
          AND TRIM(COALESCE(desc_sector_generico,'')) <> ''
        GROUP BY unidad_organizativa, desc_sector_generico
        ORDER BY unidad_organizativa, c DESC
        """,
        (batch_id,),
    )
    out: dict[str, str] = {}
    for row in cur.fetchall():
        out.setdefault(row["unidad_organizativa"], row["desc_sector_generico"])
    return out


def _load_ausentismo_classifier(cur: sqlite3.Cursor, batch_id: int) -> tuple[dict[str, dict[str, str]], list[str]]:
    cur.execute(
        """
        SELECT codigo_normalizado, descripcion, tratamiento, tipo_ausentismo
        FROM rrhh_codigos_ausentismo_maestro
        WHERE active = 1
        """
    )
    codes = {
        row["codigo_normalizado"]: {
            "descripcion": row["descripcion"] or "",
            "tratamiento": row["tratamiento"] or "",
            "tipo": row["tipo_ausentismo"] or "",
        }
        for row in cur.fetchall()
        if row["codigo_normalizado"]
    }
    if not codes:
        cur.execute(
            """
            SELECT codigo_normalizado, descripcion, tratamiento, tipo_ausentismo
            FROM rrhh_codigos_ausentismo
            WHERE batch_id = ?
            """,
            (batch_id,),
        )
        codes = {
            row["codigo_normalizado"]: {
                "descripcion": row["descripcion"] or "",
                "tratamiento": row["tratamiento"] or "",
                "tipo": row["tipo_ausentismo"] or "",
            }
            for row in cur.fetchall()
            if row["codigo_normalizado"]
        }
    cur.execute(
        """
        SELECT patron
        FROM rrhh_ausentismo_reglas
        WHERE (batch_id = ? OR batch_id IS NULL)
          AND active = 1
          AND clasificacion = 'NO CONSIDERAR'
        """,
        (batch_id,),
    )
    patterns = [row["patron"].upper() for row in cur.fetchall() if row["patron"]]
    for pattern in ("VACACION", "VACAC", "FRANCO", "DESCANSO", "LIBRE", "FERIADO NO", "NO CONVOCADO"):
        if pattern not in patterns:
            patterns.append(pattern)
    return codes, patterns


def _classify_ausentismo(codigo: Any, motivo: Any, horario: Any, codes: dict[str, dict[str, str]], no_count_patterns: list[str]) -> dict[str, Any]:
    codigo_text = _norm(codigo)
    codigo_norm = _norm_codigo(codigo_text)
    motivo_text = _norm(motivo)
    haystack = f"{motivo_text} {_norm(horario)}".upper()
    if not codigo_norm or codigo_norm == "0":
        return {
            "codigo_norm": codigo_norm,
            "tratamiento": "",
            "tipo": "",
            "clasificacion": "SIN NOVEDAD",
            "contabiliza": 0,
            "regla": "",
        }
    if codigo_norm == "666" or any(pattern and pattern in haystack for pattern in no_count_patterns):
        return {
            "codigo_norm": codigo_norm,
            "tratamiento": "",
            "tipo": "",
            "clasificacion": "NO CONSIDERAR",
            "contabiliza": 0,
            "regla": "codigo_666" if codigo_norm == "666" else "patron_no_considerar",
        }
    info = codes.get(codigo_norm)
    if info:
        tipo = info["tipo"] or "SIN TIPO"
        return {
            "codigo_norm": codigo_norm,
            "tratamiento": info["tratamiento"],
            "tipo": tipo,
            "clasificacion": tipo,
            "contabiliza": 1 if tipo in {"CONTROLADO", "NO CONTROLADO"} else 0,
            "regla": "codigo_maestro",
        }
    return {
        "codigo_norm": codigo_norm,
        "tratamiento": "",
        "tipo": "",
        "clasificacion": "SIN CLASIFICAR",
        "contabiliza": 0,
        "regla": "codigo_no_maestro",
    }


def _import_actividad_files(cur: sqlite3.Cursor, batch_id: int, paths: list[Path], gerencia: dict[str, int]) -> int:
    seen: set[tuple[str, str]] = set()
    uo_sector_map = _unidad_sector_map(cur, batch_id)
    codes, no_count_patterns = _load_ausentismo_classifier(cur, batch_id)
    total = 0
    for path in paths:
        total += _import_actividad(cur, batch_id, path, gerencia, uo_sector_map, seen, codes, no_count_patterns)
    return total


def _parse_legajo_nombre(value: Any) -> tuple[str, str]:
    text = _norm(value)
    if " - " in text:
        legajo, nombre = text.split(" - ", 1)
        return _norm_legajo(legajo), _norm(nombre)
    return _norm_legajo(text), ""


def _import_fichadas(cur: sqlite3.Cursor, batch_id: int, path: Path, gerencia: dict[str, int]) -> int:
    rows = _read_workbook_rows(path)
    header_idx = 1 if rows and _norm_key(rows[0][0] if rows[0] else "") != "ubicacion" else 0
    headers = _unique_headers(rows[header_idx])
    payload = []
    for row in rows[header_idx + 1:]:
        data = _row_dict(headers, row)
        legajo, nombre = _parse_legajo_nombre(data.get("legajo_apellido_y_nombre"))
        fh = _to_datetime(data.get("fecha_fichada"))
        fecha = _to_date(data.get("fecha_fichada"))
        if not legajo or not fh or not fecha:
            continue
        payload.append((
            batch_id, legajo, nombre, fh, fecha, fh[11:19],
            _norm(data.get("sentido")), _norm(data.get("ubicacion")),
            _norm(data.get("origen")), _norm(data.get("destino")),
            _norm(data.get("tipo_lectura")), gerencia.get(legajo, 0), _raw_json(headers, row),
        ))
    cur.executemany(
        """
        INSERT INTO rrhh_fichadas (
            batch_id, legajo, empleado, fecha_fichada, fecha, hora, sentido,
            ubicacion, origen, destino, tipo_lectura, es_gerencia, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)


def _merge_sancion_detalle(left: Any, right: Any) -> str:
    first = _norm(left)
    second = _norm(right)
    if not first:
        merged = second
    elif not second:
        merged = first
    elif re.search(r"\d$", first) and re.match(r"^\d{1,2}:", second):
        merged = first + second
    elif re.search(r"[A-ZÁÉÍÓÚÑ]{1,4}$", first) and re.match(r"^[A-ZÁÉÍÓÚÑ]{2,}", second):
        merged = first + second
    elif re.search(r"[-/([{]$", first):
        merged = first + second
    else:
        merged = f"{first} {second}"
    merged = re.sub(r"(\d{1,2}:\d{2})([A-ZÁÉÍÓÚÑ])", r"\1 \2", merged)
    merged = re.sub(r"\bCO\s+MUNICO\b", "COMUNICO", merged, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", merged).strip()


def _import_sanciones(
    cur: sqlite3.Cursor,
    batch_id: int,
    path: Path,
    gerencia: dict[str, int],
    seen: set[tuple[str, str | None, str | None, str, str, str]] | None = None,
) -> int:
    rows = _read_workbook_rows(path)
    headers = _unique_headers(rows[0])
    payload = []
    seen = seen if seen is not None else set()
    for row in rows[1:]:
        data = _row_dict(headers, row)
        legajo = _norm_legajo(data.get("legajo"))
        if not legajo:
            continue
        detalle = _merge_sancion_detalle(data.get("detalle"), data.get("detalle_2"))
        inicio = _to_date(data.get("inicio"))
        fin = _to_date(data.get("fin"))
        cod = _norm(data.get("cod"))
        creacion = _to_date(data.get("creacion"))
        descripcion = _norm(data.get("descripcion"))
        dedupe_key = (legajo, inicio, fin, cod, creacion or "", descripcion)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        payload.append((
            batch_id, legajo, _norm(data.get("apellido_y_nombre")),
            inicio, fin, cod,
            creacion, descripcion, detalle,
            _norm(data.get("ausentismo")), _norm(data.get("desc_ausentismo")),
            _norm(data.get("causa_sancion")), _norm(data.get("descripcion_causa")),
            _norm(data.get("u_o_sancion")), _norm(data.get("descripcion_u_o_san")),
            gerencia.get(legajo, 0), _raw_json(headers, row),
        ))
    cur.executemany(
        """
        INSERT INTO rrhh_sanciones (
            batch_id, legajo, nombre, inicio, fin, cod, creacion, descripcion,
            detalle, ausentismo, desc_ausentismo, causa_sancion, descripcion_causa,
            unidad_organizativa, desc_unidad_organizativa, es_gerencia, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)


def _import_sanciones_files(cur: sqlite3.Cursor, batch_id: int, paths: list[Path], gerencia: dict[str, int]) -> int:
    seen: set[tuple[str, str | None, str | None, str, str, str]] = set()
    total = 0
    for path in paths:
        total += _import_sanciones(cur, batch_id, path, gerencia, seen)
    return total


def _import_codigos(cur: sqlite3.Cursor, batch_id: int, path: Path) -> dict[str, int]:
    total = 0
    reglas = 0
    seen_codes: set[str] = set()
    for sheet in ("No Controlado", "Controlado"):
        rows = _read_workbook_rows(path, sheet)
        headers = _unique_headers(rows[0])
        payload = []
        master_payload = []
        for row in rows[1:]:
            data = _row_dict(headers, row)
            codigo = _norm(data.get("cod_ausentismo"))
            codigo_norm = _norm_codigo(codigo)
            if not codigo_norm:
                continue
            seen_codes.add(codigo_norm)
            descripcion = _norm(data.get("descripcion"))
            tratamiento = _norm(data.get("tratamiento"))
            tipo = _norm(data.get("tipo_ausentismo"))
            raw = _raw_json(headers, row)
            payload.append((
                batch_id, codigo, codigo_norm, descripcion, tratamiento, tipo, sheet, raw,
            ))
            master_payload.append((
                codigo_norm, codigo, descripcion, tratamiento, tipo, sheet,
                batch_id, batch_id, _now(), raw,
            ))
        cur.executemany(
            """
            INSERT OR REPLACE INTO rrhh_codigos_ausentismo (
                batch_id, codigo, codigo_normalizado, descripcion, tratamiento,
                tipo_ausentismo, source_sheet, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        cur.executemany(
            """
            INSERT INTO rrhh_codigos_ausentismo_maestro (
                codigo_normalizado, codigo_original, descripcion, tratamiento,
                tipo_ausentismo, source_sheet, first_seen_batch_id,
                last_seen_batch_id, updated_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(codigo_normalizado) DO UPDATE SET
                codigo_original = excluded.codigo_original,
                descripcion = excluded.descripcion,
                tratamiento = excluded.tratamiento,
                tipo_ausentismo = excluded.tipo_ausentismo,
                source_sheet = excluded.source_sheet,
                active = 1,
                last_seen_batch_id = excluded.last_seen_batch_id,
                updated_at = excluded.updated_at,
                raw_json = excluded.raw_json
            """,
            master_payload,
        )
        total += len(payload)
    if seen_codes:
        placeholders = ", ".join("?" for _ in seen_codes)
        cur.execute(
            f"UPDATE rrhh_codigos_ausentismo_maestro SET active = 0, updated_at = ? WHERE codigo_normalizado NOT IN ({placeholders})",
            (_now(), *seen_codes),
        )

    try:
        rows = _read_workbook_rows(path, "Notas")
    except Exception:
        rows = []
    if rows:
        headers = _unique_headers(rows[0])
        payload = []
        for row in rows[1:]:
            data = _row_dict(headers, row)
            raw_values = [_norm(value) for value in row if _norm(value)]
            if not raw_values:
                continue
            patron = _norm(data.get("tipo_ausentismo")) or (raw_values[1] if len(raw_values) > 1 else raw_values[0])
            if not patron:
                continue
            payload.append((
                batch_id, "MOTIVO_CONTIENE", patron.upper(), "NO CONSIDERAR",
                0, "Notas", _raw_json(headers, row),
            ))
        cur.executemany(
            """
            INSERT OR REPLACE INTO rrhh_ausentismo_reglas (
                batch_id, regla_tipo, patron, clasificacion, contabiliza, source_sheet, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        reglas += len(payload)
    macro_payload = [
        (batch_id, "MOTIVO_CONTIENE", pattern, "NO CONSIDERAR", 0, "macro_default", "{}")
        for pattern in ("VACACION", "VACAC", "FRANCO", "DESCANSO", "LIBRE", "FERIADO NO", "NO CONVOCADO")
    ]
    macro_payload.append((batch_id, "CODIGO_IGUAL", "666", "NO CONSIDERAR", 0, "macro_default", "{}"))
    cur.executemany(
        """
        INSERT OR REPLACE INTO rrhh_ausentismo_reglas (
            batch_id, regla_tipo, patron, clasificacion, contabiliza, source_sheet, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        macro_payload,
    )
    reglas += len(macro_payload)
    return {"codigos": total, "reglas": reglas}


def _cleanup_rrhh_orphans(cur: sqlite3.Cursor) -> None:
    for table in (
        "rrhh_legajero",
        "rrhh_actividad_diaria",
        "rrhh_fichadas",
        "rrhh_sanciones",
        "rrhh_codigos_ausentismo",
        "rrhh_ausentismo_reglas",
        "rrhh_personas_changes",
    ):
        cur.execute(
            f"DELETE FROM {table} WHERE batch_id NOT IN (SELECT batch_id FROM rrhh_import_batches)"
        )


def _delete_rrhh_batch_children(cur: sqlite3.Cursor, batch_id: int) -> None:
    for column in ("first_seen_batch_id", "last_seen_batch_id", "last_changed_batch_id"):
        cur.execute(
            f"UPDATE rrhh_personas SET {column} = NULL WHERE {column} = ?",
            (batch_id,),
        )
    for column in ("first_seen_batch_id", "last_seen_batch_id"):
        cur.execute(
            f"UPDATE rrhh_codigos_ausentismo_maestro SET {column} = NULL WHERE {column} = ?",
            (batch_id,),
        )
    for table in (
        "rrhh_legajero",
        "rrhh_actividad_diaria",
        "rrhh_fichadas",
        "rrhh_sanciones",
        "rrhh_codigos_ausentismo",
        "rrhh_ausentismo_reglas",
        "rrhh_personas_changes",
    ):
        cur.execute(f"DELETE FROM {table} WHERE batch_id = ?", (batch_id,))


def _import_folder_sync(folder: Path, batch_key: str, imported_by: str, force: bool) -> dict[str, Any]:
    files = _detect_files(folder)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    try:
        _cleanup_rrhh_orphans(cur)
        cur.execute("SELECT batch_id FROM rrhh_import_batches WHERE batch_key = ?", (batch_key,))
        existing = cur.fetchone()
        if existing and not force:
            raise RuntimeError(f"El lote {batch_key} ya existe. Usar force=true para reimportar.")
        if existing:
            _delete_rrhh_batch_children(cur, int(existing["batch_id"]))
            cur.execute("DELETE FROM rrhh_import_batches WHERE batch_id = ?", (existing["batch_id"],))
        cur.execute(
            """
            INSERT INTO rrhh_import_batches (batch_key, source_dir, imported_by, status, files_json)
            VALUES (?, ?, ?, 'running', ?)
            """,
            (batch_key, str(folder), imported_by, json.dumps(files, ensure_ascii=False)),
        )
        batch_id = int(cur.lastrowid)
        legajero_info = _import_legajero(cur, batch_id, Path(files["legajero"]))
        gerencia_map = legajero_info["gerencia_map"]
        codigos_info = _import_codigos(cur, batch_id, Path(files["codigos_ausentismo"])) if files.get("codigos_ausentismo") else {"codigos": 0, "reglas": 0}
        summary = {
            "legajero": legajero_info["inserted"],
            "legajero_altas": legajero_info["altas"],
            "legajero_modificaciones": legajero_info["modificaciones"],
            "legajero_bajas": legajero_info["bajas"],
            "legajero_reactivaciones": legajero_info["reactivaciones"],
            "legajero_sin_cambios": legajero_info["sin_cambios"],
            "codigos_ausentismo": codigos_info["codigos"],
            "reglas_ausentismo": codigos_info["reglas"],
            "actividad": _import_actividad_files(cur, batch_id, _as_paths(files, "actividad_files"), gerencia_map),
            "actividad_archivos": len(_as_paths(files, "actividad_files")),
            "fichadas": 0,
            "fichadas_omitidas": bool(files.get("fichadas")),
            "sanciones": _import_sanciones_files(cur, batch_id, _as_paths(files, "sanciones_files"), gerencia_map) if files.get("sanciones") else 0,
            "sanciones_archivos": len(_as_paths(files, "sanciones_files")),
            "gerencia_legajos": sum(1 for value in gerencia_map.values() if value),
        }
        cur.execute(
            """
            UPDATE rrhh_import_batches
            SET status = 'complete', summary_json = ?, error = NULL
            WHERE batch_id = ?
            """,
            (json.dumps(summary, ensure_ascii=False), batch_id),
        )
        conn.commit()
        return {"batch_id": batch_id, "batch_key": batch_key, "files": files, "summary": summary}
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(str(exc)) from exc
    finally:
        conn.close()


async def _require_auth(request: Request) -> dict[str, Any]:
    auth = await current_auth(request)
    if not auth or auth.get("device_status") != "approved":
        raise HTTPException(status_code=401, detail="No autenticado.")
    return auth


def _can_see_all(auth: dict[str, Any]) -> bool:
    return auth.get("role") in FULL_ACCESS_ROLES


def _require_import_role(auth: dict[str, Any]) -> None:
    if auth.get("role") not in IMPORT_ROLES:
        raise HTTPException(status_code=403, detail="Requiere perfil admin o RRHH.")


async def _latest_batch_id() -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT batch_id FROM rrhh_import_batches WHERE status = 'complete' ORDER BY imported_at DESC, batch_id DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
    return int(row[0]) if row else None


async def _resolve_batch_id(batch_id: int | None) -> int:
    if batch_id:
        return batch_id
    latest = await _latest_batch_id()
    if not latest:
        raise HTTPException(status_code=404, detail="Todavia no hay lotes RRHH importados.")
    return latest


def _visibility_sql(auth: dict[str, Any], alias: str = "") -> str:
    if _can_see_all(auth):
        return "1=1"
    prefix = f"{alias}." if alias else ""
    return f"COALESCE({prefix}es_gerencia, 0) = 0"


def _append_persona_filter(
    where: list[str],
    params: list[Any],
    search: str,
    *,
    record_alias: str,
    legajero_alias: str = "l",
    name_columns: tuple[str, ...],
) -> None:
    text = _norm(search)
    if not text:
        return
    numeric = _norm_legajo(text)
    like = f"%{text.upper()}%"
    clauses = [
        f"{record_alias}.legajo = ?",
        f"LTRIM({record_alias}.legajo, '0') = ?",
        f"UPPER(COALESCE({legajero_alias}.nombre, '')) LIKE ?",
    ]
    params.extend([numeric, numeric, like])
    for column in name_columns:
        clauses.append(f"UPPER(COALESCE({column}, '')) LIKE ?")
        params.append(like)
    where.append(f"({' OR '.join(clauses)})")


def _multi_query_values(request: Request, key: str, fallback: str = "ALL") -> list[str]:
    values = request.query_params.getlist(key) or ([fallback] if fallback else [])
    out: list[str] = []
    for value in values:
        for part in str(value).split("|"):
            item = _norm(part)
            if item and item != "ALL" and item not in out:
                out.append(item)
    return out


def _append_multi_filter(where: list[str], params: list[Any], expression: str, values: list[str]) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    where.append(f"{expression} IN ({placeholders})")
    params.extend(values)


@router.get("/config")
async def get_config(request: Request):
    auth = await _require_auth(request)
    latest_folder = None
    if SOURCE_ROOT.exists():
        try:
            latest_folder = str(_find_latest_folder())
        except Exception:
            latest_folder = None
    return {
        "role": auth.get("role"),
        "can_import": auth.get("role") in IMPORT_ROLES,
        "can_see_gerencia": _can_see_all(auth),
        "source_root": str(SOURCE_ROOT),
        "latest_folder": latest_folder,
    }


@router.get("/batches")
async def list_batches(request: Request):
    await _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT batch_id, batch_key, source_dir, imported_by, imported_at, status,
                   files_json, summary_json, error
            FROM rrhh_import_batches
            ORDER BY imported_at DESC, batch_id DESC
            LIMIT 20
            """
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    for row in rows:
        row["files"] = json.loads(row.pop("files_json") or "{}")
        row["summary"] = json.loads(row.pop("summary_json") or "{}")
    return {"batches": rows}


@router.post("/import/latest")
async def import_latest(req: ImportFolderRequest, request: Request):
    auth = await _require_auth(request)
    _require_import_role(auth)
    folder = _find_latest_folder()
    batch_key = req.batch_key or folder.name
    try:
        result = await asyncio.to_thread(_import_folder_sync, folder, batch_key, auth.get("username", ""), req.force)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/import/folder")
async def import_folder(req: ImportFolderRequest, request: Request):
    auth = await _require_auth(request)
    _require_import_role(auth)
    folder = Path(req.folder_path or "").expanduser()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail="La carpeta indicada no existe.")
    batch_key = req.batch_key or folder.name
    try:
        result = await asyncio.to_thread(_import_folder_sync, folder, batch_key, auth.get("username", ""), req.force)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.get("/resumen")
async def get_resumen(request: Request, batch_id: int | None = None):
    auth = await _require_auth(request)
    batch_id = await _resolve_batch_id(batch_id)
    vis = _visibility_sql(auth)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        queries = {
            "empleados": f"SELECT COUNT(DISTINCT legajo) v FROM rrhh_legajero WHERE batch_id = ? AND {vis}",
            "actividad": f"SELECT COUNT(*) v FROM rrhh_actividad_diaria WHERE batch_id = ? AND {vis}",
            "ausencias": f"SELECT COUNT(*) v FROM rrhh_actividad_diaria WHERE batch_id = ? AND {vis} AND COALESCE(ausentismo_contabiliza,0) = 1",
            "horas_trabajadas": f"SELECT COALESCE(SUM(hs_trab),0) v FROM rrhh_actividad_diaria WHERE batch_id = ? AND {vis}",
            "horas_extra": f"SELECT COALESCE(SUM(hs_ext_realiz + hs_50_autorizadas + hs_100),0) v FROM rrhh_actividad_diaria WHERE batch_id = ? AND {vis}",
            "llegadas_tarde": f"SELECT COUNT(*) v FROM rrhh_actividad_diaria WHERE batch_id = ? AND {vis} AND tarde > 0",
            "fichadas": f"SELECT COUNT(*) v FROM rrhh_fichadas WHERE batch_id = ? AND {vis}",
            "sanciones": f"SELECT COUNT(*) v FROM rrhh_sanciones WHERE batch_id = ? AND {vis}",
        }
        metrics = {}
        for key, sql in queries.items():
            async with db.execute(sql, (batch_id,)) as cur:
                metrics[key] = (await cur.fetchone())["v"]
        async with db.execute(
            f"""
            SELECT COALESCE(l.desc_sector_generico, a.sector, 'Sin sector') sector,
                   COUNT(DISTINCT a.legajo) empleados,
                   SUM(CASE WHEN COALESCE(a.ausentismo_contabiliza,0) = 1 THEN 1 ELSE 0 END) ausencias,
                   ROUND(SUM(a.hs_trab), 1) horas_trabajadas,
                   ROUND(SUM(a.hs_ext_realiz + a.hs_50_autorizadas + a.hs_100), 1) horas_extra,
                   SUM(CASE WHEN a.tarde > 0 THEN 1 ELSE 0 END) llegadas_tarde
            FROM rrhh_actividad_diaria a
            LEFT JOIN rrhh_legajero l ON l.batch_id = a.batch_id AND l.legajo = a.legajo
            WHERE a.batch_id = ? AND {_visibility_sql(auth, 'a')}
            GROUP BY sector
            ORDER BY ausencias DESC, empleados DESC
            LIMIT 20
            """,
            (batch_id,),
        ) as cur:
            sectores = [dict(row) for row in await cur.fetchall()]
        async with db.execute(
            "SELECT * FROM rrhh_import_batches WHERE batch_id = ?",
            (batch_id,),
        ) as cur:
            batch = dict(await cur.fetchone())
    batch["files"] = json.loads(batch.pop("files_json") or "{}")
    batch["summary"] = json.loads(batch.pop("summary_json") or "{}")
    return {"batch": batch, "metrics": metrics, "sectores": sectores, "restricted": not _can_see_all(auth)}


@router.get("/indicadores")
async def get_indicadores(
    request: Request,
    batch_id: int | None = None,
    fecha_desde: str = "",
    fecha_hasta: str = "",
    sector: str = "ALL",
    cargo: str = "ALL",
    grupo: str = "ALL",
    motivo: str = "ALL",
    persona: str = "",
):
    auth = await _require_auth(request)
    batch_id = await _resolve_batch_id(batch_id)
    sectores_sel = _multi_query_values(request, "sector", sector)
    cargos_sel = _multi_query_values(request, "cargo", cargo)
    grupos_sel = _multi_query_values(request, "grupo", grupo)
    motivos_sel = _multi_query_values(request, "motivo", motivo)

    where = ["a.batch_id = ?", _visibility_sql(auth, "a")]
    params: list[Any] = [batch_id]
    if fecha_desde:
        where.append("a.fecha >= ?")
        params.append(fecha_desde)
    if fecha_hasta:
        where.append("a.fecha <= ?")
        params.append(fecha_hasta)
    _append_multi_filter(where, params, "COALESCE(l.desc_sector_generico, a.sector)", sectores_sel)
    _append_multi_filter(where, params, "COALESCE(l.desc_funcion, '')", cargos_sel)
    _append_multi_filter(where, params, "COALESCE(l.desc_grupo_personal, '')", grupos_sel)
    _append_multi_filter(where, params, "COALESCE(NULLIF(TRIM(a.motivo), ''), 'Sin motivo')", motivos_sel)
    _append_persona_filter(where, params, persona, record_alias="a", name_columns=("a.empleado",))
    where_sql = " AND ".join(where)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            f"""
            SELECT
                COUNT(DISTINCT a.legajo) empleados,
                COUNT(*) registros,
                SUM(CASE WHEN COALESCE(a.ausentismo_contabiliza,0) = 1 THEN 1 ELSE 0 END) ausencias,
                SUM(CASE WHEN a.ausentismo_clasificacion = 'CONTROLADO' THEN 1 ELSE 0 END) ausencias_controladas,
                SUM(CASE WHEN a.ausentismo_clasificacion = 'NO CONTROLADO' THEN 1 ELSE 0 END) ausencias_no_controladas,
                SUM(CASE WHEN a.ausentismo_clasificacion = 'NO CONSIDERAR' THEN 1 ELSE 0 END) ausencias_no_considerar,
                SUM(CASE WHEN a.ausentismo_clasificacion = 'SIN CLASIFICAR' THEN 1 ELSE 0 END) ausencias_sin_clasificar,
                SUM(CASE WHEN a.tarde > 0 THEN 1 ELSE 0 END) llegadas_tarde,
                ROUND(COALESCE(SUM(a.hs_trab),0), 1) horas_trabajadas,
                ROUND(COALESCE(SUM(a.hs_ext_realiz + a.hs_50_autorizadas + a.hs_100),0), 1) horas_extra,
                ROUND(
                    SUM(CASE WHEN COALESCE(a.ausentismo_contabiliza,0) = 1 THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0),
                    1
                ) ausentismo_pct
            FROM rrhh_actividad_diaria a
            LEFT JOIN rrhh_legajero l ON l.batch_id = a.batch_id AND l.legajo = a.legajo
            WHERE {where_sql}
            """,
            tuple(params),
        ) as cur:
            kpis = dict(await cur.fetchone())

        async with db.execute(
            f"""
            SELECT MIN(a.fecha) fecha_desde, MAX(a.fecha) fecha_hasta
            FROM rrhh_actividad_diaria a
            LEFT JOIN rrhh_legajero l ON l.batch_id = a.batch_id AND l.legajo = a.legajo
            WHERE a.batch_id = ? AND {_visibility_sql(auth, "a")}
            """,
            (batch_id,),
        ) as cur:
            data_range = dict(await cur.fetchone())

        async with db.execute(
            f"""
            SELECT a.fecha label,
                   COUNT(*) registros,
                   SUM(CASE WHEN COALESCE(a.ausentismo_contabiliza,0) = 1 THEN 1 ELSE 0 END) ausencias,
                   SUM(CASE WHEN a.tarde > 0 THEN 1 ELSE 0 END) llegadas_tarde,
                   ROUND(SUM(a.hs_ext_realiz + a.hs_50_autorizadas + a.hs_100), 1) horas_extra
            FROM rrhh_actividad_diaria a
            LEFT JOIN rrhh_legajero l ON l.batch_id = a.batch_id AND l.legajo = a.legajo
            WHERE {where_sql}
            GROUP BY a.fecha
            ORDER BY a.fecha
            """,
            tuple(params),
        ) as cur:
            diario = [dict(row) for row in await cur.fetchall()]

        async with db.execute(
            f"""
            SELECT COALESCE(l.desc_sector_generico, a.sector, 'Sin sector') label,
                   COUNT(*) registros,
                   COUNT(DISTINCT a.legajo) empleados,
                   SUM(CASE WHEN COALESCE(a.ausentismo_contabiliza,0) = 1 THEN 1 ELSE 0 END) ausencias,
                   ROUND(SUM(a.hs_trab), 1) horas_trabajadas,
                   ROUND(SUM(a.hs_ext_realiz + a.hs_50_autorizadas + a.hs_100), 1) horas_extra,
                   SUM(CASE WHEN a.tarde > 0 THEN 1 ELSE 0 END) llegadas_tarde
            FROM rrhh_actividad_diaria a
            LEFT JOIN rrhh_legajero l ON l.batch_id = a.batch_id AND l.legajo = a.legajo
            WHERE {where_sql}
            GROUP BY label
            ORDER BY ausencias DESC, horas_extra DESC
            LIMIT 12
            """,
            tuple(params),
        ) as cur:
            por_sector = [dict(row) for row in await cur.fetchall()]

        async with db.execute(
            f"""
            SELECT COALESCE(l.desc_sector_generico, a.sector, 'Sin sector') || ' / ' ||
                   COALESCE(NULLIF(TRIM(l.desc_funcion), ''), 'Sin cargo') label,
                   COUNT(*) registros,
                   COUNT(DISTINCT a.legajo) empleados,
                   SUM(CASE WHEN COALESCE(a.ausentismo_contabiliza,0) = 1 THEN 1 ELSE 0 END) ausencias,
                   ROUND(SUM(a.hs_trab), 1) horas_trabajadas,
                   ROUND(SUM(a.hs_ext_realiz + a.hs_50_autorizadas + a.hs_100), 1) horas_extra,
                   SUM(CASE WHEN a.tarde > 0 THEN 1 ELSE 0 END) llegadas_tarde
            FROM rrhh_actividad_diaria a
            LEFT JOIN rrhh_legajero l ON l.batch_id = a.batch_id AND l.legajo = a.legajo
            WHERE {where_sql}
            GROUP BY label
            ORDER BY ausencias DESC, horas_extra DESC
            LIMIT 18
            """,
            tuple(params),
        ) as cur:
            por_sector_cargo = [dict(row) for row in await cur.fetchall()]

        async with db.execute(
            f"""
            SELECT TRIM(a.motivo) label,
                   COUNT(*) eventos
            FROM rrhh_actividad_diaria a
            LEFT JOIN rrhh_legajero l ON l.batch_id = a.batch_id AND l.legajo = a.legajo
            WHERE {where_sql}
            GROUP BY label
            HAVING TRIM(COALESCE(label, '')) <> '' AND eventos > 0
            ORDER BY eventos DESC
            LIMIT 10
            """,
            tuple(params),
        ) as cur:
            motivos = [dict(row) for row in await cur.fetchall()]

        ranking_sancion_filters = ["s.batch_id = ?", _visibility_sql(auth, "s")]
        ranking_sancion_params: list[Any] = [batch_id]
        if fecha_desde:
            ranking_sancion_filters.append("COALESCE(s.creacion, s.inicio) >= ?")
            ranking_sancion_params.append(fecha_desde)
        if fecha_hasta:
            ranking_sancion_filters.append("COALESCE(s.creacion, s.inicio) <= ?")
            ranking_sancion_params.append(fecha_hasta)
        async with db.execute(
            f"""
            WITH actividad_filtrada AS (
                SELECT a.*, COALESCE(l.desc_sector_generico, a.sector, 'Sin sector') unidad,
                       COALESCE(NULLIF(TRIM(l.desc_funcion), ''), 'Sin cargo') funcion,
                       COALESCE(NULLIF(TRIM(l.desc_grupo_personal), ''), '') grupo_personal,
                       COALESCE(NULLIF(TRIM(l.desc_area_personal), ''), '') area_personal
                FROM rrhh_actividad_diaria a
                LEFT JOIN rrhh_legajero l ON l.batch_id = a.batch_id AND l.legajo = a.legajo
                WHERE {where_sql}
            ),
            motivos_aus AS (
                SELECT legajo, GROUP_CONCAT(label, ', ') motivos_aus
                FROM (
                    SELECT legajo, TRIM(motivo) || '(' || COUNT(*) || ')' label
                    FROM actividad_filtrada
                    WHERE COALESCE(ausentismo_contabiliza,0) = 1
                      AND TRIM(COALESCE(motivo,'')) <> ''
                    GROUP BY legajo, TRIM(motivo)
                    ORDER BY COUNT(*) DESC, TRIM(motivo)
                )
                GROUP BY legajo
            ),
            otros_motivos AS (
                SELECT legajo, GROUP_CONCAT(label, ', ') otros_motivos
                FROM (
                    SELECT legajo, TRIM(motivo) || '(' || COUNT(*) || ')' label
                    FROM actividad_filtrada
                    WHERE COALESCE(ausentismo_contabiliza,0) = 0
                      AND ausentismo_clasificacion <> 'SIN NOVEDAD'
                      AND TRIM(COALESCE(motivo,'')) <> ''
                    GROUP BY legajo, TRIM(motivo)
                    ORDER BY COUNT(*) DESC, TRIM(motivo)
                )
                GROUP BY legajo
            ),
            sanciones_legajo AS (
                SELECT legajo, SUM(c) c_sanc, GROUP_CONCAT(label, ', ') tipo_sancion
                FROM (
                    SELECT s.legajo, COALESCE(NULLIF(TRIM(s.descripcion), ''), 'Sin descripcion') label, COUNT(*) c
                    FROM rrhh_sanciones s
                    WHERE {" AND ".join(ranking_sancion_filters)}
                    GROUP BY s.legajo, label
                    ORDER BY COUNT(*) DESC, label
                )
                GROUP BY legajo
            )
            SELECT af.legajo,
                   COALESCE(MAX(NULLIF(TRIM(af.empleado), '')), '') empleado,
                   MAX(af.funcion) funcion,
                   MAX(af.unidad) unidad,
                   COUNT(DISTINCT af.fecha) dias_reg,
                   SUM(CASE WHEN COALESCE(af.ausentismo_contabiliza,0) = 1 THEN 1 ELSE 0 END) dias_aus,
                   ROUND(SUM(CASE WHEN COALESCE(af.ausentismo_contabiliza,0) = 1 THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(DISTINCT af.fecha), 0), 1) pct_aus,
                   SUM(CASE WHEN af.ausentismo_clasificacion = 'CONTROLADO' THEN 1 ELSE 0 END) ctrl,
                   SUM(CASE WHEN af.ausentismo_clasificacion = 'NO CONTROLADO' THEN 1 ELSE 0 END) no_ctrl,
                   COALESCE(MAX(ma.motivos_aus), '') motivos_aus,
                   COALESCE(MAX(om.otros_motivos), '') otros_motivos,
                   ROUND(SUM(af.hs_trab), 1) hs_trab,
                   SUM(CASE WHEN (af.hs_ext_realiz + af.hs_50_autorizadas + af.hs_100) > 0 THEN 1 ELSE 0 END) dias_che,
                   SUM(CASE WHEN af.hs_50_autorizadas > 0 THEN 1 ELSE 0 END) dias_he_50,
                   SUM(CASE WHEN af.hs_100 > 0 THEN 1 ELSE 0 END) dias_he_100,
                   ROUND(SUM(af.hs_50_autorizadas), 1) hs_50,
                   ROUND(SUM(af.hs_100), 1) hs_100,
                   ROUND(SUM(af.hs_ext_realiz + af.hs_50_autorizadas + af.hs_100), 1) hs_extra,
                   ROUND(SUM(af.hs_fer), 1) hs_fer,
                   ROUND(SUM(af.rec_noct), 1) rec_noct,
                   SUM(CASE WHEN af.tarde > 0 THEN 1 ELSE 0 END) c_tarde,
                   ROUND(SUM(af.tarde), 1) min_tarde,
                   0 paus_30,
                   COALESCE(MAX(sl.c_sanc), 0) c_sanc,
                   COALESCE(MAX(sl.tipo_sancion), '') tipo_sancion,
                   MAX(af.grupo_personal) grupo_personal,
                   MAX(af.area_personal) area_personal
            FROM actividad_filtrada af
            LEFT JOIN motivos_aus ma ON ma.legajo = af.legajo
            LEFT JOIN otros_motivos om ON om.legajo = af.legajo
            LEFT JOIN sanciones_legajo sl ON sl.legajo = af.legajo
            GROUP BY af.legajo
            ORDER BY pct_aus DESC, dias_aus DESC, c_tarde DESC, hs_extra DESC
            LIMIT 1000
            """,
            tuple(params + ranking_sancion_params),
        ) as cur:
            ranking = [dict(row) for row in await cur.fetchall()]

        s_where = ["s.batch_id = ?", _visibility_sql(auth, "s")]
        s_params: list[Any] = [batch_id]
        if fecha_desde:
            s_where.append("COALESCE(s.creacion, s.inicio) >= ?")
            s_params.append(fecha_desde)
        if fecha_hasta:
            s_where.append("COALESCE(s.creacion, s.inicio) <= ?")
            s_params.append(fecha_hasta)
        _append_multi_filter(s_where, s_params, "COALESCE(l.desc_sector_generico, s.desc_unidad_organizativa, '')", sectores_sel)
        _append_multi_filter(s_where, s_params, "COALESCE(l.desc_funcion, '')", cargos_sel)
        _append_multi_filter(s_where, s_params, "COALESCE(l.desc_grupo_personal, '')", grupos_sel)
        _append_persona_filter(s_where, s_params, persona, record_alias="s", name_columns=("s.nombre",))
        async with db.execute(
            f"""
            SELECT COALESCE(NULLIF(TRIM(s.descripcion), ''), 'Sin descripcion') label,
                   COUNT(*) eventos
            FROM rrhh_sanciones s
            LEFT JOIN rrhh_legajero l ON l.batch_id = s.batch_id AND l.legajo = s.legajo
            WHERE {" AND ".join(s_where)}
            GROUP BY label
            ORDER BY eventos DESC
            LIMIT 10
            """,
            tuple(s_params),
        ) as cur:
            sanciones = [dict(row) for row in await cur.fetchall()]
        async with db.execute(
            f"""
            SELECT COUNT(*) sanciones
            FROM rrhh_sanciones s
            LEFT JOIN rrhh_legajero l ON l.batch_id = s.batch_id AND l.legajo = s.legajo
            WHERE {" AND ".join(s_where)}
            """,
            tuple(s_params),
        ) as cur:
            kpis["sanciones"] = (await cur.fetchone())["sanciones"]

        f_where = ["batch_id = ?", _visibility_sql(auth)]
        f_params: list[Any] = [batch_id]
        if fecha_desde:
            f_where.append("fecha >= ?")
            f_params.append(fecha_desde)
        if fecha_hasta:
            f_where.append("fecha <= ?")
            f_params.append(fecha_hasta)
        async with db.execute(
            f"SELECT COUNT(*) fichadas, COUNT(DISTINCT legajo) legajos_con_fichada FROM rrhh_fichadas WHERE {' AND '.join(f_where)}",
            tuple(f_params),
        ) as cur:
            kpis.update(dict(await cur.fetchone()))

        filter_vis = _visibility_sql(auth, "l")
        async with db.execute(
            f"""
            SELECT DISTINCT desc_sector_generico value
            FROM rrhh_legajero l
            WHERE batch_id = ? AND {filter_vis} AND TRIM(COALESCE(desc_sector_generico,'')) <> ''
            ORDER BY value
            """,
            (batch_id,),
        ) as cur:
            sectores = [row["value"] for row in await cur.fetchall()]
        cargo_where = ["l.batch_id = ?", filter_vis, "TRIM(COALESCE(l.desc_funcion,'')) <> ''"]
        cargo_params: list[Any] = [batch_id]
        _append_multi_filter(cargo_where, cargo_params, "l.desc_sector_generico", sectores_sel)
        async with db.execute(
            f"""
            SELECT DISTINCT desc_funcion value
            FROM rrhh_legajero l
            WHERE {" AND ".join(cargo_where)}
            ORDER BY value
            """,
            tuple(cargo_params),
        ) as cur:
            cargos = [row["value"] for row in await cur.fetchall()]
        async with db.execute(
            f"""
            SELECT DISTINCT desc_grupo_personal value
            FROM rrhh_legajero l
            WHERE batch_id = ? AND {filter_vis} AND TRIM(COALESCE(desc_grupo_personal,'')) <> ''
            ORDER BY value
            """,
            (batch_id,),
        ) as cur:
            grupos = [row["value"] for row in await cur.fetchall()]
        async with db.execute(
            f"""
            SELECT DISTINCT TRIM(a.motivo) value
            FROM rrhh_actividad_diaria a
            WHERE batch_id = ? AND {_visibility_sql(auth, "a")}
              AND COALESCE(a.ausentismo_contabiliza,0) = 1
              AND TRIM(COALESCE(a.motivo,'')) <> ''
            ORDER BY value
            """,
            (batch_id,),
        ) as cur:
            motivos_filter = [row["value"] for row in await cur.fetchall()]

    return {
        "restricted": not _can_see_all(auth),
        "kpis": kpis,
        "data_range": data_range,
        "filters": {
            "sectores": sectores,
            "cargos": cargos,
            "grupos": grupos,
            "motivos": motivos_filter,
        },
        "series": {
            "diario": diario,
            "por_sector": por_sector,
            "por_sector_cargo": por_sector_cargo,
            "motivos": motivos,
            "sanciones": sanciones,
            "ranking": ranking,
        },
    }


async def _query_rows(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            return [dict(row) for row in await cur.fetchall()]


@router.get("/actividad")
async def get_actividad(
    request: Request,
    batch_id: int | None = None,
    fecha_desde: str = "",
    fecha_hasta: str = "",
    sector: str = "ALL",
    cargo: str = "ALL",
    motivo: str = "ALL",
    persona: str = "",
    limit: int = Query(200, ge=1, le=1000),
):
    auth = await _require_auth(request)
    batch_id = await _resolve_batch_id(batch_id)
    sectores_sel = _multi_query_values(request, "sector", sector)
    cargos_sel = _multi_query_values(request, "cargo", cargo)
    motivos_sel = _multi_query_values(request, "motivo", motivo)
    where = [f"a.batch_id = ?", _visibility_sql(auth, "a")]
    params: list[Any] = [batch_id]
    if fecha_desde:
        where.append("a.fecha >= ?")
        params.append(fecha_desde)
    if fecha_hasta:
        where.append("a.fecha <= ?")
        params.append(fecha_hasta)
    _append_multi_filter(where, params, "COALESCE(l.desc_sector_generico, a.sector)", sectores_sel)
    _append_multi_filter(where, params, "COALESCE(l.desc_funcion, '')", cargos_sel)
    _append_multi_filter(where, params, "COALESCE(NULLIF(TRIM(a.motivo), ''), 'Sin motivo')", motivos_sel)
    _append_persona_filter(where, params, persona, record_alias="a", name_columns=("a.empleado",))
    params.append(limit)
    rows = await _query_rows(
        f"""
        SELECT a.fecha, a.legajo, a.empleado, COALESCE(l.desc_sector_generico, a.sector) sector,
               a.horario, a.entrada, a.salida, a.motivo, a.aus_pres_codigo,
               a.ausentismo_clasificacion, a.ausentismo_tratamiento,
               a.hs_trab, a.hs_ext_realiz, a.hs_50_autorizadas, a.hs_100, a.tarde
        FROM rrhh_actividad_diaria a
        LEFT JOIN rrhh_legajero l ON l.batch_id = a.batch_id AND l.legajo = a.legajo
        WHERE {' AND '.join(where)}
        ORDER BY a.fecha DESC, a.legajo
        LIMIT ?
        """,
        tuple(params),
    )
    return {"rows": rows, "restricted": not _can_see_all(auth)}


@router.get("/fichadas")
async def get_fichadas(
    request: Request,
    batch_id: int | None = None,
    fecha_desde: str = "",
    fecha_hasta: str = "",
    sector: str = "ALL",
    cargo: str = "ALL",
    legajo: str = "",
    persona: str = "",
    limit: int = Query(200, ge=1, le=1000),
):
    auth = await _require_auth(request)
    batch_id = await _resolve_batch_id(batch_id)
    sectores_sel = _multi_query_values(request, "sector", sector)
    cargos_sel = _multi_query_values(request, "cargo", cargo)
    where = ["f.batch_id = ?", _visibility_sql(auth, "f")]
    params: list[Any] = [batch_id]
    if fecha_desde:
        where.append("f.fecha >= ?")
        params.append(fecha_desde)
    if fecha_hasta:
        where.append("f.fecha <= ?")
        params.append(fecha_hasta)
    _append_multi_filter(where, params, "COALESCE(l.desc_sector_generico, '')", sectores_sel)
    _append_multi_filter(where, params, "COALESCE(l.desc_funcion, '')", cargos_sel)
    if legajo:
        where.append("f.legajo = ?")
        params.append(_norm_legajo(legajo))
    _append_persona_filter(where, params, persona, record_alias="f", name_columns=("f.empleado",))
    params.append(limit)
    rows = await _query_rows(
        f"""
        SELECT f.fecha_fichada, f.legajo, f.empleado, COALESCE(l.desc_sector_generico, '') sector,
               COALESCE(l.desc_funcion, '') cargo, f.sentido, f.ubicacion, f.origen, f.destino, f.tipo_lectura
        FROM rrhh_fichadas f
        LEFT JOIN rrhh_legajero l ON l.batch_id = f.batch_id AND l.legajo = f.legajo
        WHERE {' AND '.join(where)}
        ORDER BY f.fecha_fichada DESC
        LIMIT ?
        """,
        tuple(params),
    )
    return {"rows": rows, "restricted": not _can_see_all(auth)}


@router.get("/sanciones")
async def get_sanciones(
    request: Request,
    batch_id: int | None = None,
    fecha_desde: str = "",
    fecha_hasta: str = "",
    sector: str = "ALL",
    cargo: str = "ALL",
    motivo: str = "ALL",
    persona: str = "",
    limit: int = Query(200, ge=1, le=1000),
):
    auth = await _require_auth(request)
    batch_id = await _resolve_batch_id(batch_id)
    sectores_sel = _multi_query_values(request, "sector", sector)
    cargos_sel = _multi_query_values(request, "cargo", cargo)
    motivos_sel = _multi_query_values(request, "motivo", motivo)
    where = ["s.batch_id = ?", _visibility_sql(auth, "s")]
    params: list[Any] = [batch_id]
    if fecha_desde:
        where.append("COALESCE(s.creacion, s.inicio) >= ?")
        params.append(fecha_desde)
    if fecha_hasta:
        where.append("COALESCE(s.creacion, s.inicio) <= ?")
        params.append(fecha_hasta)
    _append_multi_filter(where, params, "COALESCE(l.desc_sector_generico, s.desc_unidad_organizativa, '')", sectores_sel)
    _append_multi_filter(where, params, "COALESCE(l.desc_funcion, '')", cargos_sel)
    if motivos_sel:
        placeholders = ", ".join("?" for _ in motivos_sel)
        where.append(f"(COALESCE(NULLIF(TRIM(s.descripcion), ''), 'Sin motivo') IN ({placeholders}) OR COALESCE(NULLIF(TRIM(s.descripcion_causa), ''), 'Sin motivo') IN ({placeholders}))")
        params.extend(motivos_sel)
        params.extend(motivos_sel)
    _append_persona_filter(where, params, persona, record_alias="s", name_columns=("s.nombre",))
    params.append(limit)
    rows = await _query_rows(
        f"""
        SELECT s.legajo, s.nombre, COALESCE(l.desc_sector_generico, s.desc_unidad_organizativa, '') sector,
               COALESCE(l.desc_funcion, '') cargo, s.inicio, s.creacion, s.cod, s.descripcion,
               s.causa_sancion, s.descripcion_causa
        FROM rrhh_sanciones s
        LEFT JOIN rrhh_legajero l ON l.batch_id = s.batch_id AND l.legajo = s.legajo
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(s.creacion, s.inicio) DESC, s.legajo
        LIMIT ?
        """,
        tuple(params),
    )
    return {"rows": rows, "restricted": not _can_see_all(auth)}
