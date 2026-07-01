import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET


ROOT = Path(r"C:\Ingenieria\VigIA")
DB_PATH = ROOT / "datos" / "vigia.db"
MAP_PATH = Path(r"C:\Users\207189\Downloads\MAPA DE PLANIFICACIONES ACTUALIZADO (1).xlsx")
TEMPLATE_PATH = Path(r"\\redcoto.com.ar\patagonia\CD_Automatizaciones\Carga PHDT\ExcelBase\Ingenieria.xlsx")
OUT_JSON = ROOT / ".codex_tmp" / "cargas_choferes" / "unified_inputs.json"

GERENCIA_CODES = {
    "DEPOSITO": "10930001",
    "STAFF": "10930004",
    "INGENIERIA - PLANEAMIENTO Y TRAFICO": "10930003",
}
ROOT_NAMES = set(GERENCIA_CODES)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value.upper()).strip()


def safe_filename(value: str, max_len: int = 180) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', " ", value or "")
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    return (value[:max_len].rstrip() or "SIN NOMBRE")


def root_for_position(shape: dict) -> str:
    # The map has three visual lanes: deposito, staff, and ingenieria.
    col = shape["pos"][1] if shape.get("pos") else 0
    if col >= 42:
        return "INGENIERIA - PLANEAMIENTO Y TRAFICO"
    if col >= 29:
        return "STAFF"
    return "DEPOSITO"


def parse_map():
    ns = {
        "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
    code_re = re.compile(r"109\d{5}")
    with ZipFile(MAP_PATH) as zf:
        root = ET.fromstring(zf.read("xl/drawings/drawing1.xml"))

    shapes = {}
    parent = {}
    for anchor in root.findall("xdr:twoCellAnchor", ns):
        sp = anchor.find("xdr:sp", ns)
        cxn = anchor.find("xdr:cxnSp", ns)
        if sp is not None:
            c_nv_pr = sp.find(".//xdr:cNvPr", ns)
            if c_nv_pr is None:
                continue
            shape_id = int(c_nv_pr.attrib["id"])
            text = " ".join(" ".join(t.text or "" for t in sp.findall(".//a:t", ns)).split())
            if not text:
                continue
            from_node = anchor.find("xdr:from", ns)
            to_node = anchor.find("xdr:to", ns)
            pos = None
            if from_node is not None and to_node is not None:
                pos = (
                    int(from_node.find("xdr:row", ns).text) + 1,
                    int(from_node.find("xdr:col", ns).text) + 1,
                    int(to_node.find("xdr:row", ns).text) + 1,
                    int(to_node.find("xdr:col", ns).text) + 1,
                )
            shapes[shape_id] = {
                "id": shape_id,
                "text": text,
                "norm": normalize(text),
                "codes": list(dict.fromkeys(code_re.findall(text))),
                "pos": pos,
            }
        if cxn is not None:
            st = cxn.find(".//a:stCxn", ns)
            en = cxn.find(".//a:endCxn", ns)
            if st is not None and en is not None:
                parent[int(en.attrib["id"])] = int(st.attrib["id"])

    return shapes, parent


def path_for(shape_id: int, shapes: dict, parent: dict) -> list[str]:
    ids = []
    seen = set()
    current = shape_id
    while current in shapes and current not in seen:
        seen.add(current)
        ids.append(current)
        current = parent.get(current)
        if current is None:
            break
    ids.reverse()

    branch = [shapes[i]["text"] for i in ids[:-1] if i in shapes]
    root_name = next((name for name in branch if normalize(name) in ROOT_NAMES), None)
    if not root_name:
        root_name = root_for_position(shapes[shape_id])
        branch.insert(0, root_name)

    deduped = []
    for part in branch:
        if normalize(part) not in [normalize(x) for x in deduped]:
            deduped.append(part)
    return deduped


def load_legajero():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        latest = con.execute("SELECT MAX(batch_id) FROM rrhh_legajero").fetchone()[0]
        rows = [
            dict(row)
            for row in con.execute(
                """
                SELECT
                    TRIM(legajo) AS legajo,
                    TRIM(COALESCE(unidad_organizativa, '')) AS code,
                    TRIM(COALESCE(desc_unidad_organizativa, '')) AS name
                FROM rrhh_legajero
                WHERE batch_id = ?
                  AND fecha_baja IS NULL
                  AND TRIM(COALESCE(legajo, '')) <> ''
                ORDER BY code, CAST(legajo AS INTEGER), legajo
                """,
                (latest,),
            )
        ]
    finally:
        con.close()
    return latest, rows


def main():
    shapes, parent = parse_map()
    latest, legajos = load_legajero()

    legajos_by_code = defaultdict(list)
    names_by_code = Counter()
    for row in legajos:
        legajos_by_code[row["code"]].append(row)
        if row["name"]:
            names_by_code[(row["code"], row["name"])] += 1

    def code_name(code: str) -> str:
        names = [(name, count) for (c, name), count in names_by_code.items() if c == code]
        if not names:
            return code or "SIN UNIDAD"
        return sorted(names, key=lambda item: (-item[1], item[0]))[0][0]

    units = []
    mapped_codes = set()
    used_names = Counter()

    for shape_id, shape in sorted(shapes.items(), key=lambda item: (item[1].get("pos") or (999, 999, 999, 999))):
        if not shape["codes"]:
            continue
        present_codes = [code for code in shape["codes"] if legajos_by_code.get(code) and code not in mapped_codes]
        if not present_codes:
            continue

        branch = path_for(shape_id, shapes, parent)
        root = next((part for part in branch if normalize(part) in ROOT_NAMES), root_for_position(shape))
        gerencia = GERENCIA_CODES[root]
        names = [code_name(code) for code in present_codes]

        filename_parts = branch[:]
        if len(present_codes) == 1:
            filename_parts.append(names[0])
        else:
            filename_parts.append(" + ".join(names[:3]) + (f" + {len(names) - 3} mas" if len(names) > 3 else ""))

        filename_base = safe_filename(" - ".join(filename_parts))
        used_names[filename_base] += 1
        if used_names[filename_base] > 1:
            filename_base = safe_filename(f"{filename_base} ({used_names[filename_base]})")

        rows = []
        for code in present_codes:
            mapped_codes.add(code)
            for legajo in legajos_by_code[code]:
                rows.append({"legajo": legajo["legajo"], "idGerencia": gerencia, "idUo": code})

        units.append(
            {
                "filename": f"{filename_base}.xlsx",
                "branch": branch,
                "shapeId": shape_id,
                "codes": present_codes,
                "rows": rows,
                "legajos": len(rows),
            }
        )

    for code in sorted(code for code in legajos_by_code if code and code not in mapped_codes):
        name = code_name(code)
        filename_base = safe_filename(f"Sin Codigo - {name}")
        used_names[filename_base] += 1
        if used_names[filename_base] > 1:
            filename_base = safe_filename(f"{filename_base} ({used_names[filename_base]})")
        units.append(
            {
                "filename": f"{filename_base}.xlsx",
                "branch": ["Sin Codigo"],
                "shapeId": None,
                "codes": [code],
                "rows": [{"legajo": row["legajo"], "idGerencia": "", "idUo": code} for row in legajos_by_code[code]],
                "legajos": len(legajos_by_code[code]),
            }
        )

    payload = {
        "latestBatchId": latest,
        "mapPath": str(MAP_PATH),
        "templatePath": str(TEMPLATE_PATH),
        "units": units,
        "summary": {
            "files": len(units),
            "legajos": sum(unit["legajos"] for unit in units),
            "mapFiles": sum(1 for unit in units if unit["shapeId"] is not None),
            "sinCodigoFiles": sum(1 for unit in units if unit["shapeId"] is None),
            "multiCodeFiles": sum(1 for unit in units if len(unit["codes"]) > 1),
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
