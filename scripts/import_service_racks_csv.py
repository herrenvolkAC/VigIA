from __future__ import annotations

import argparse
import asyncio
import csv
import difflib
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.casos import init_cases_db  # noqa: E402
from db.schema import DB_PATH  # noqa: E402
from routers.casos import (  # noqa: E402
    _as_list,
    _attach_forms_files,
    CASES_TZ,
    _connect_operational_db,
    _evento,
    _fetch_all,
    _fetch_one,
    _historial,
    _match_key,
    _now,
    _tipo_id,
    _upsert_forms_payload,
    _validate_pasillo,
    _validate_ubicaciones,
)


HEADER_ROW_INDEX = 6
SOURCE = "microsoft_forms_csv"
FORM = "service_racks_historico"
IMPORT_USER = "forms_csv_import"

COL = {
    "service": 0,
    "zona": 1,
    "pasillo": 2,
    "cara": 3,
    "huecos": 4,
    "sector": 5,
    "response_id": 6,
    "motivo": 7,
    "adjunto": 8,
    "criticidad": 9,
    "tipo_rack": 10,
    "zona2": 13,
    "pasillo2": 14,
    "cara2": 15,
    "hueco_start": 16,
    "hueco_end": 20,
    "nivel_start": 20,
    "nivel_end": 26,
    "motivo2": 40,
    "control_mapa": 41,
    "analista_mapa": 42,
    "estado_service": 43,
    "fecha_cierre": 44,
    "usuario": 45,
    "comentario": 46,
}

DESCRIPCION_ALIASES = {
    "LARGUERO SUELTO": "TRAVESAÑO SUELTO",
    "LARGUERO ROTO": "TRAVESAÑO ROTO",
    "PARANTE GOLPEADO": "PUNTAL ROTO/DOBLADO",
    "PUNTAL ROTO": "PUNTAL ROTO/DOBLADO",
}

TIPO_RACK_ALIASES = {
    "PUSH BACK": "PUSH_BACK",
    "DRIVE IN": "DRIVE_IN",
}

ALL_LEVELS = ["1", "A", "B", "C", "D", "E", "F", "G"]
VALID_LEVELS = set(ALL_LEVELS)


class Resolver:
    def __init__(self) -> None:
        self.tipo_id = 0
        self.params: dict[str, list[dict[str, Any]]] = {}
        self.criticidades: list[dict[str, Any]] = []

    async def load(self, db) -> None:
        self.tipo_id = await _tipo_id(db)
        for table in ("rack_cara", "rack_sector", "rack_tipo", "rack_descripcion", "rack_nivel"):
            self.params[table] = await _fetch_all(
                db,
                f"SELECT id, codigo, nombre FROM {table} WHERE activo=1 ORDER BY orden, id",
            )
        self.criticidades = await _fetch_all(
            db,
            "SELECT id, codigo, nombre, sla_horas FROM ticket_criticidad WHERE tipo_id=? AND activo=1 ORDER BY sla_horas, id",
            (self.tipo_id,),
        )

    def param_id(self, table: str, value: Any) -> int | None:
        text = clean(value)
        if not text:
            return None
        target = _match_key(text)
        for row in self.params.get(table, []):
            candidates = {_match_key(row.get("codigo")), _match_key(row.get("nombre"))}
            if target in candidates:
                return int(row["id"])
            if len(target) >= 8 and any(difflib.SequenceMatcher(None, target, candidate).ratio() >= 0.9 for candidate in candidates):
                return int(row["id"])
        return None

    def criticidad_id(self, value: Any) -> int | None:
        text = clean(value)
        aliases = {
            "URGENTE": ["CRITICA", "ALTA"],
            "CRITICO": ["CRITICA", "ALTA"],
            "CRITICA": ["CRITICA"],
            "ALTA": ["ALTA"],
            "MEDIA": ["MEDIA"],
            "NORMAL": ["MEDIA", "BAJA"],
            "BAJA": ["BAJA"],
        }
        candidates = aliases.get(text, [text])
        candidate_set = {item.upper() for item in candidates}
        for row in self.criticidades:
            if str(row.get("codigo") or "").upper() in candidate_set or str(row.get("nombre") or "").upper() in candidate_set:
                return int(row["id"])
        if self.criticidades:
            return int(max(self.criticidades, key=lambda row: int(row.get("sla_horas") or 0))["id"])
        return None


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").strip().upper().split())


def cell(row: list[str], name: str) -> str:
    idx = COL[name]
    return row[idx] if idx < len(row) else ""


def split_tokens(value: Any) -> list[str]:
    return [part for part in re.split(r"[\s,;\-/]+", clean(value)) if part]


def dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def read_csv(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin1", errors="replace")
    return list(csv.reader(text.splitlines(), delimiter=";"))


def is_useful_row(row: list[str]) -> bool:
    return any(str(value or "").strip() for value in row[:47])


def looks_mal_cargado(row: list[str]) -> bool:
    values = [
        cell(row, "service"),
        cell(row, "estado_service"),
        cell(row, "control_mapa"),
        cell(row, "sector"),
        cell(row, "motivo"),
        cell(row, "motivo2"),
        cell(row, "comentario"),
    ]
    return any(clean(value) == "MAL CARGADO" or clean(value).startswith("MAL CARGADO") for value in values)


def canonical_description(row: list[str]) -> str:
    value = clean(cell(row, "motivo"))
    if not value:
        value = clean(cell(row, "motivo2")) if clean(cell(row, "motivo2")) not in {"#¡REF!", "#﹕EF!"} else ""
    return DESCRIPCION_ALIASES.get(value, value)


def canonical_tipo_rack(row: list[str]) -> str:
    value = clean(cell(row, "tipo_rack"))
    return TIPO_RACK_ALIASES.get(value, value)


def extract_huecos(row: list[str]) -> tuple[list[str], list[str]]:
    raw_tokens: list[str] = []
    for idx in range(COL["hueco_start"], COL["hueco_end"]):
        if idx < len(row) and clean(row[idx]):
            raw_tokens.extend(split_tokens(row[idx]))
    if not raw_tokens:
        raw_tokens = split_tokens(cell(row, "huecos"))

    values: list[str] = []
    invalid: list[str] = []
    for token in raw_tokens:
        if token.isdigit():
            values.append(token)
        elif token in {"A", "AL", "HASTA", "Y"}:
            continue
        else:
            invalid.append(token)

    if not values:
        zona = clean(cell(row, "zona"))
        pasillo = clean(cell(row, "pasillo"))
        cara = clean(cell(row, "cara"))
        prefix = re.sub(r"[^A-Z0-9]+", "", zona + pasillo + cara)
        compact = re.sub(r"[^A-Z0-9]+", "", clean(cell(row, "huecos")))
        if prefix and compact.startswith(prefix):
            match = re.match(r"(\d+)", compact[len(prefix):])
            if match:
                values.append(match.group(1))
                invalid = []

    return dedupe(values), dedupe(invalid)


def extract_levels(row: list[str]) -> tuple[list[str], list[str]]:
    tokens: list[str] = []
    for idx in range(COL["nivel_start"], COL["nivel_end"]):
        if idx < len(row) and clean(row[idx]):
            tokens.extend(split_tokens(row[idx]))
    if not tokens:
        tokens.extend(split_tokens(row[12] if len(row) > 12 else ""))

    if "TODOS" in tokens or "NIVELES" in tokens:
        return ALL_LEVELS[:], []

    values: list[str] = []
    invalid: list[str] = []
    for token in tokens:
        if token in VALID_LEVELS:
            values.append(token)
        else:
            invalid.append(token)
    return dedupe(values), dedupe(invalid)


def attachment_items(value: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in re.split(r"\s*;\s*", str(value or "").strip()):
        raw = raw.strip()
        if not raw:
            continue
        parsed = urllib.parse.urlparse(raw)
        name = urllib.parse.unquote(Path(parsed.path).name) if parsed.scheme else Path(raw).name
        if not name:
            name = "Adjunto Forms"
        items.append({"name": name, "link": raw})
    return items


def response_id_for(row: list[str], row_number: int) -> str:
    raw = clean(cell(row, "response_id"))
    service = clean(cell(row, "service"))
    if raw:
        return f"legacy-csv-{raw}"
    if service:
        return f"legacy-csv-service-{service}"
    return f"legacy-csv-row-{row_number}"


def parse_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d 00:00:00")
        except ValueError:
            pass
    return ""


def target_state(row: list[str]) -> str:
    estado = clean(cell(row, "estado_service"))
    control = clean(cell(row, "control_mapa"))
    if estado == "CERRADO" or control == "HABILITADAS":
        return "CERRADO"
    if control == "BLOQUEADAS":
        return "POSICION_BLOQUEADA"
    if control == "EN PROCESO":
        return "PENDIENTE_TRASPASOS"
    return "PENDIENTE_VALIDACION"


def should_attach_files(args: argparse.Namespace, row: list[str]) -> bool:
    if not args.attach_files:
        return False
    return args.attach_closed_files or target_state(row) != "CERRADO"


def build_payload(row: list[str], row_number: int, source_file: str) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    huecos, invalid_huecos = extract_huecos(row)
    levels, invalid_levels = extract_levels(row)
    if invalid_huecos:
        warnings.append(f"Huecos no numericos ignorados: {', '.join(invalid_huecos)}")
    if invalid_levels:
        warnings.append(f"Niveles invalidos ignorados: {', '.join(invalid_levels)}")

    comentario_parts = [
        str(cell(row, "comentario") or "").strip(),
        f"Service externo historico: {clean(cell(row, 'service'))}" if clean(cell(row, "service")) else "",
        f"Control MAPA historico: {clean(cell(row, 'control_mapa'))}" if clean(cell(row, "control_mapa")) else "",
        f"Analista MAPA historico: {str(cell(row, 'analista_mapa') or '').strip()}" if str(cell(row, "analista_mapa") or "").strip() else "",
    ]
    comentario = "\n".join(part for part in comentario_parts if part)
    payload = {
        "source": SOURCE,
        "form": FORM,
        "response_id": response_id_for(row, row_number),
        "received_at": "",
        "responder": "",
        "source_file": source_file,
        "raw_response": {
            "zona": clean(cell(row, "zona") or cell(row, "zona2")),
            "pasillo": clean(cell(row, "pasillo") or cell(row, "pasillo2")),
            "cara": clean(cell(row, "cara") or cell(row, "cara2")),
            "ubicaciones": "-".join(huecos),
            "niveles": levels,
            "sector": clean(cell(row, "sector")),
            "tipo_rack": canonical_tipo_rack(row),
            "descripcion_rotura": canonical_description(row),
            "criticidad": clean(cell(row, "criticidad")) or "MEDIA",
            "comentario": comentario,
            "adjuntos": attachment_items(cell(row, "adjunto")),
            "legacy": {
                "row_number": row_number,
                "service_externo": clean(cell(row, "service")),
                "estado_service": clean(cell(row, "estado_service")),
                "control_mapa": clean(cell(row, "control_mapa")),
                "fecha_cierre": str(cell(row, "fecha_cierre") or "").strip(),
                "usuario": str(cell(row, "usuario") or "").strip(),
            },
        },
    }
    return payload, warnings


async def payload_to_case_data(resolver: Resolver, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    raw = payload.get("raw_response") or {}
    errors: list[str] = []
    tipo_id = resolver.tipo_id
    zona = clean(raw.get("zona"))
    pasillo = clean(raw.get("pasillo"))
    ubicaciones = clean(raw.get("ubicaciones"))

    if not zona:
        errors.append("Falta zona.")
    try:
        pasillo = _validate_pasillo(pasillo)
    except HTTPException as exc:
        errors.append(str(exc.detail))
    try:
        ubicaciones = _validate_ubicaciones(ubicaciones)
    except HTTPException as exc:
        errors.append(str(exc.detail))

    cara_id = resolver.param_id("rack_cara", raw.get("cara"))
    sector_id = resolver.param_id("rack_sector", raw.get("sector"))
    tipo_rack_id = resolver.param_id("rack_tipo", raw.get("tipo_rack"))
    descripcion_id = resolver.param_id("rack_descripcion", raw.get("descripcion_rotura"))
    criticidad_id = resolver.criticidad_id(raw.get("criticidad"))
    for label, value in [
        ("cara", cara_id),
        ("sector", sector_id),
        ("tipo de rack", tipo_rack_id),
        ("descripcion de rotura", descripcion_id),
        ("criticidad", criticidad_id),
    ]:
        if not value:
            errors.append(f"No se pudo mapear {label}.")

    niveles: list[int] = []
    for nivel in _as_list(raw.get("niveles")):
        nivel_id = resolver.param_id("rack_nivel", nivel)
        if nivel_id:
            niveles.append(nivel_id)
        else:
            errors.append(f"Nivel invalido: {nivel}.")
    niveles = dedupe(niveles)
    if not niveles:
        errors.append("Falta nivel.")

    if errors:
        return None, errors
    return {
        "tipo_id": tipo_id,
        "zona_text": zona,
        "pasillo": pasillo,
        "cara_id": cara_id,
        "ubicaciones": ubicaciones,
        "niveles": niveles,
        "sector_rack_id": sector_id,
        "descripcion_rack_id": descripcion_id,
        "criticidad_id": criticidad_id,
        "tipo_rack_id": tipo_rack_id,
        "comentario_operativo": str(raw.get("comentario") or "").strip(),
    }, []


async def apply_legacy_state(db, ticket_id: int, row: list[str], payload: dict[str, Any]) -> None:
    state_code = target_state(row)
    tipo_id = await _tipo_id(db)
    state = await _fetch_one(db, "SELECT * FROM ticket_estado WHERE tipo_id=? AND codigo=? AND activo=1", (tipo_id, state_code))
    if not state:
        return
    now = _now()
    fecha_cierre = parse_date(cell(row, "fecha_cierre")) if state_code == "CERRADO" else ""
    service = clean(cell(row, "service"))
    update_date = fecha_cierre or now
    await db.execute(
        """
        UPDATE ticket
        SET estado_id=?, perfil_asignado=?, sector_asignado=?, fecha_ultima_actualizacion=?, fecha_cierre=?
        WHERE id=?
        """,
        (
            int(state["id"]),
            state.get("perfil_asignado") or "",
            state.get("perfil_asignado") or "",
            update_date,
            fecha_cierre or None,
            ticket_id,
        ),
    )

    detail_updates: dict[str, Any] = {
        "service_externo_id": service or None,
        "service_externo_usuario": IMPORT_USER if service else None,
        "service_externo_fecha": now if service else None,
    }
    if state_code in {"TRASPASOS_ASIGNADOS", "POSICION_BLOQUEADA", "EN_REPARACION", "REPARADO", "PENDIENTE_HABILITACION", "CERRADO"}:
        detail_updates.update({"traspasos_wms": "Importado historico desde CSV", "traspasos_usuario": IMPORT_USER, "traspasos_fecha": now})
    if state_code in {"POSICION_BLOQUEADA", "EN_REPARACION", "REPARADO", "PENDIENTE_HABILITACION", "CERRADO"}:
        detail_updates.update({"vaciado_confirmado": 1, "vaciado_usuario": IMPORT_USER, "vaciado_fecha": now})
        detail_updates.update({"inutilizacion_wms_confirmada": 1, "inutilizacion_usuario": IMPORT_USER, "inutilizacion_fecha": now})
    if state_code in {"REPARADO", "PENDIENTE_HABILITACION", "CERRADO"}:
        detail_updates.update({"mantenimiento_finalizado": 1, "mantenimiento_usuario": IMPORT_USER, "mantenimiento_fecha": now})
    if state_code == "CERRADO":
        detail_updates.update({"rehabilitacion_wms_confirmada": 1, "rehabilitacion_usuario": IMPORT_USER, "rehabilitacion_fecha": fecha_cierre or now})

    columns = ", ".join(f"{key}=?" for key in detail_updates)
    await db.execute(
        f"UPDATE ticket_rack_detalle SET {columns} WHERE ticket_id=?",
        (*detail_updates.values(), ticket_id),
    )
    legacy = payload["raw_response"].get("legacy") or {}
    comentario = (
        f"Importacion CSV historica. Estado CSV={legacy.get('estado_service') or '-'}; "
        f"Control MAPA={legacy.get('control_mapa') or '-'}; "
        f"Service={legacy.get('service_externo') or '-'}; "
        f"Fecha cierre={legacy.get('fecha_cierre') or '-'}."
    )
    await _historial(db, ticket_id, {"username": IMPORT_USER}, "ADMIN", "IMPORTACION_CSV", comentario, None, int(state["id"]))


async def create_rack_case_from_csv(
    db,
    case_data: dict[str, Any],
    payload: dict[str, Any],
    source_file: str,
    *,
    attach_files: bool,
) -> tuple[int, str]:
    tipo_id = int(case_data["tipo_id"])
    criticidad = await _fetch_one(db, "SELECT * FROM ticket_criticidad WHERE id=? AND tipo_id=? AND activo=1", (case_data["criticidad_id"], tipo_id))
    estado = await _fetch_one(db, "SELECT * FROM ticket_estado WHERE tipo_id=? AND es_inicial=1 AND activo=1", (tipo_id,))
    if not criticidad or not estado:
        raise RuntimeError("Faltan parametros base para crear el caso.")
    fecha_actual = _now()
    sla_vencimiento = (datetime.now(CASES_TZ) + timedelta(hours=int(criticidad["sla_horas"]))).strftime("%Y-%m-%d %H:%M:%S")
    titulo = f"Reparacion de rack Z{case_data['zona_text']} P{case_data['pasillo']} U{case_data['ubicaciones']}"
    creador = os.getenv("VIGIA_FORMS_RACKS_USER", IMPORT_USER).strip() or IMPORT_USER
    cur = await db.execute(
        """
        INSERT INTO ticket
            (tipo_id, estado_id, criticidad_id, titulo, descripcion, usuario_creacion_id,
             sector_creacion_id, perfil_asignado, sector_asignado, fecha_creacion,
             fecha_ultima_actualizacion, sla_vencimiento)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tipo_id,
            estado["id"],
            case_data["criticidad_id"],
            titulo,
            case_data["comentario_operativo"],
            creador,
            "FORMS_CSV",
            estado.get("perfil_asignado") or "ADO",
            estado.get("perfil_asignado") or "ADO",
            fecha_actual,
            fecha_actual,
            sla_vencimiento,
        ),
    )
    ticket_id = int(cur.lastrowid)
    codigo_visible = f"RCK-{ticket_id:06d}"
    await db.execute("UPDATE ticket SET codigo_visible=? WHERE id=?", (codigo_visible, ticket_id))
    await db.execute(
        """
        INSERT INTO ticket_rack_detalle
            (ticket_id, zona_text, pasillo, cara_id, ubicaciones, niveles, sector_rack_id,
             descripcion_rack_id, tipo_rack_id, comentario_operativo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            case_data["zona_text"],
            case_data["pasillo"],
            case_data["cara_id"],
            case_data["ubicaciones"],
            json.dumps(case_data["niveles"]),
            case_data["sector_rack_id"],
            case_data["descripcion_rack_id"],
            case_data["tipo_rack_id"],
            case_data["comentario_operativo"],
        ),
    )
    auth = {"username": creador}
    await _historial(db, ticket_id, auth, "FORMS", "CREACION_FORMS_CSV", f"Importado desde CSV Forms response_id={payload.get('response_id')}")
    if attach_files:
        await _attach_forms_files(db, ticket_id, codigo_visible, auth, payload, source_file)
    await _evento(db, ticket_id, "ticket_creado_forms_csv", {"response_id": payload.get("response_id")})
    return ticket_id, codigo_visible


async def import_csv(args: argparse.Namespace) -> int:
    path = Path(args.csv).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"No existe el CSV: {path}")
    await init_cases_db()
    rows = read_csv(path)
    data_rows = rows[HEADER_ROW_INDEX + 1 :]
    report_rows: list[dict[str, Any]] = []
    counters = {"read": 0, "valid": 0, "imported": 0, "existing": 0, "skipped": 0, "errors": 0}

    db = await _connect_operational_db()
    try:
        resolver = Resolver()
        await resolver.load(db)
        for offset, row in enumerate(data_rows, HEADER_ROW_INDEX + 2):
            if args.limit and counters["read"] >= args.limit:
                break
            if not is_useful_row(row):
                continue
            counters["read"] += 1
            service = clean(cell(row, "service"))
            estado_csv = clean(cell(row, "estado_service"))
            control = clean(cell(row, "control_mapa"))
            response_id = response_id_for(row, offset)
            base_report = {
                "row": offset,
                "response_id": response_id,
                "service": service,
                "estado_csv": estado_csv,
                "control_mapa": control,
                "ticket": "",
                "action": "",
                "errors": "",
                "warnings": "",
            }
            if looks_mal_cargado(row):
                counters["skipped"] += 1
                report_rows.append({**base_report, "action": "SKIP_MAL_CARGADO"})
                continue
            if args.skip_closed and target_state(row) == "CERRADO":
                counters["skipped"] += 1
                report_rows.append({**base_report, "action": "SKIP_CERRADO"})
                continue

            payload, warnings = build_payload(row, offset, str(path))
            case_data, errors = await payload_to_case_data(resolver, payload)
            if errors or not case_data:
                counters["errors"] += 1
                report_rows.append({**base_report, "action": "ERROR_VALIDACION", "errors": " ".join(errors), "warnings": " | ".join(warnings)})
                continue
            counters["valid"] += 1
            if args.dry_run:
                report_rows.append({**base_report, "action": f"DRY_RUN_{target_state(row)}", "warnings": " | ".join(warnings)})
                continue

            ingreso_id, inserted = await _upsert_forms_payload(db, payload, str(path))
            existing = await _fetch_one(db, "SELECT ticket_id FROM ticket_forms_ingreso WHERE id=?", (ingreso_id,))
            if existing and existing.get("ticket_id") and not args.reprocess_existing:
                counters["existing"] += 1
                report_rows.append({**base_report, "action": "EXISTING", "ticket": existing.get("ticket_id"), "warnings": " | ".join(warnings)})
                continue
            if existing and existing.get("ticket_id") and args.reprocess_existing:
                counters["existing"] += 1
                report_rows.append({**base_report, "action": "EXISTING_REPROCESS_SKIPPED", "ticket": existing.get("ticket_id"), "warnings": " | ".join(warnings)})
                continue

            try:
                ticket_id, codigo_visible = await create_rack_case_from_csv(db, case_data, payload, str(path), attach_files=should_attach_files(args, row))
                await apply_legacy_state(db, ticket_id, row, payload)
                await db.execute(
                    "UPDATE ticket_forms_ingreso SET estado_importacion='IMPORTADO', motivo_error=NULL, ticket_id=?, updated_at=? WHERE id=?",
                    (ticket_id, _now(), ingreso_id),
                )
                counters["imported"] += 1
                report_rows.append({**base_report, "action": f"IMPORTADO_{target_state(row)}", "ticket": codigo_visible, "warnings": " | ".join(warnings)})
            except Exception as exc:
                counters["errors"] += 1
                await db.execute(
                    "UPDATE ticket_forms_ingreso SET estado_importacion='ERROR_TECNICO', motivo_error=?, updated_at=? WHERE id=?",
                    (str(exc), _now(), ingreso_id),
                )
                report_rows.append({**base_report, "action": "ERROR_TECNICO", "errors": str(exc), "warnings": " | ".join(warnings)})

        if args.dry_run:
            await db.rollback()
        else:
            await db.commit()
    finally:
        await db.close()

    report_path = Path(args.report).expanduser().resolve() if args.report else ROOT / "outputs" / "service_racks_csv_import_report.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["row", "response_id", "service", "estado_csv", "control_mapa", "ticket", "action", "errors", "warnings"])
        writer.writeheader()
        writer.writerows(report_rows)

    print(json.dumps({"db": str(DB_PATH), "csv": str(path), "report": str(report_path), "dry_run": args.dry_run, **counters}, ensure_ascii=False, indent=2))
    return 0 if counters["errors"] == 0 else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Importa historico Service Racks desde CSV exportado de Forms.")
    parser.add_argument("csv", help="Ruta al CSV exportado.")
    parser.add_argument("--apply", action="store_true", help="Escribe en la base. Sin este flag corre en dry-run.")
    parser.add_argument("--skip-closed", action="store_true", help="No importa casos cerrados.")
    parser.add_argument("--limit", type=int, default=0, help="Procesa solo N filas utiles.")
    parser.add_argument("--report", default="", help="Ruta de salida del reporte CSV.")
    parser.add_argument("--attach-files", action="store_true", help="Busca y adjunta fotos locales solo para tickets activos. Es mas lento en carpetas OneDrive grandes.")
    parser.add_argument("--attach-closed-files", action="store_true", help="Con --attach-files, tambien adjunta fotos de tickets cerrados.")
    parser.add_argument("--reprocess-existing", action="store_true", help="Reservado: no recrea tickets existentes por seguridad.")
    args = parser.parse_args()
    args.dry_run = not args.apply
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(import_csv(parse_args())))
