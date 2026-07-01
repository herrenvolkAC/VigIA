import json
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET


ROOT = Path(r"C:\Ingenieria\VigIA")
DB_PATH = ROOT / "datos" / "vigia.db"
MAP_PATH = Path(r"C:\Users\207189\Downloads\MAPA DE PLANIFICACIONES ACTUALIZADO (1).xlsx")
OUT_JSON = ROOT / ".codex_tmp" / "cargas_choferes" / "inputs.json"


GERENCIA_BY_BRANCH = {
    "deposito": "10930001",
    "staff": "10930004",
    "ingenieria": "10930003",
}


def safe_filename(value: str, max_len: int = 130) -> str:
    value = (value or "SIN UNIDAD").strip() or "SIN UNIDAD"
    value = re.sub(r'[<>:"/\\|?*]+', " ", value)
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    return value[:max_len].rstrip() or "SIN UNIDAD"


def norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value.upper()).strip()


def extract_map_codes() -> dict[str, dict[str, str]]:
    ns = {
        "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
    with ZipFile(MAP_PATH) as zf:
        root = ET.fromstring(zf.read("xl/drawings/drawing1.xml"))

    code_re = re.compile(r"(109\d{5})")
    codes: dict[str, dict[str, str]] = {}

    for anchor in root.findall("xdr:twoCellAnchor", ns):
        sp = anchor.find("xdr:sp", ns)
        if sp is None:
            continue
        text = " ".join(" ".join(t.text or "" for t in sp.findall(".//a:t", ns)).split())
        found = code_re.findall(text)
        if not found:
            continue

        from_node = anchor.find("xdr:from", ns)
        col = int(from_node.find("xdr:col", ns).text)
        row = int(from_node.find("xdr:row", ns).text)

        if col >= 41:
            branch = "ingenieria"
        elif col >= 28:
            branch = "staff"
        else:
            branch = "deposito"

        for code in found:
            codes[code] = {
                "idGerencia": GERENCIA_BY_BRANCH[branch],
                "branch": branch,
                "source_text": text,
                "shape_row": row + 1,
                "shape_col": col + 1,
            }

    return codes


def load_legajero() -> tuple[int, list[dict[str, str]]]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        latest = con.execute("SELECT MAX(batch_id) b FROM rrhh_legajero").fetchone()["b"]
        rows = [
            dict(row)
            for row in con.execute(
                """
                SELECT
                    TRIM(legajo) legajo,
                    TRIM(COALESCE(nombre, '')) nombre,
                    TRIM(COALESCE(unidad_organizativa, '')) unidad_codigo,
                    TRIM(COALESCE(desc_unidad_organizativa, '')) unidad
                FROM rrhh_legajero
                WHERE batch_id = ?
                  AND fecha_baja IS NULL
                  AND TRIM(COALESCE(legajo, '')) <> ''
                ORDER BY unidad, CAST(legajo AS INTEGER), legajo
                """,
                (latest,),
            )
        ]
        return int(latest), rows
    finally:
        con.close()


def main() -> None:
    map_codes = extract_map_codes()
    latest_batch, legajos = load_legajero()

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in legajos:
        unidad = row["unidad"] or "SIN UNIDAD"
        codigo = row["unidad_codigo"] or ""
        mapped = map_codes.get(codigo)
        grouped[unidad].append(
            {
                "legajo": row["legajo"],
                "idGerencia": mapped["idGerencia"] if mapped else "",
                "idUo": codigo,
                "unidadCodigoLegajero": codigo,
                "nombre": row["nombre"],
                "mapped": bool(mapped),
            }
        )

    units = []
    used_names: dict[str, int] = defaultdict(int)
    for unidad in sorted(grouped.keys(), key=norm_text):
        rows = grouped[unidad]
        has_any_gerencia = any(r["mapped"] for r in rows)
        base_name = safe_filename(unidad)
        filename_base = base_name if has_any_gerencia else f"Sin Gerencia - {base_name}"
        used_names[filename_base] += 1
        if used_names[filename_base] > 1:
            filename_base = f"{filename_base} ({used_names[filename_base]})"
        units.append(
            {
                "unidad": unidad,
                "filename": f"{filename_base}.xlsx",
                "rows": rows,
                "mappedRows": sum(1 for r in rows if r["mapped"]),
                "unmappedRows": sum(1 for r in rows if not r["mapped"]),
                "legajos": len(rows),
            }
        )

    payload = {
        "latestBatchId": latest_batch,
        "mapPath": str(MAP_PATH),
        "templatePath": r"C:\Users\207189\Downloads\cargas choferes.xlsx",
        "mapCodeCount": len(map_codes),
        "units": units,
        "summary": {
            "unitCount": len(units),
            "legajoCount": sum(u["legajos"] for u in units),
            "unitsWithoutGerencia": sum(1 for u in units if u["mappedRows"] == 0),
            "rowsWithoutGerencia": sum(u["unmappedRows"] for u in units),
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
