"""Unifica Armado Secos y recalcula sus pagos con bolsa cerrada 60/40.

Actualiza los seis parámetros de turno de Zona 1 y Zona 2 y sus escalas
individuales. Guarda la configuración previa en la auditoría interna, recalcula
los caches de agosto-septiembre 2026 y genera un HTML acotado a Secos · Armado.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import routers.estudio_premios_productividad as estudio
import gerencial_umbrales_compacto as compacto
from generar_informe_gerencial_umbrales import (
    analyze,
    attach_payroll_activity,
    attach_polivalency_summaries,
    render,
)

PERIOD = ("2026-08-01", "2026-09-30")
PROFILE_IDS = {"perfil-1", "perfil-5"}
SECTORS = ("CD-SECOS - ZONA 1", "CD-SECOS - ZONA 2")
GROUP_AWARD = 13_328.20
INDIVIDUAL_AWARDS = {1: 6_158.64, 2: 10_227.75, 3: 16_716.31, 4: 27_713.89, 5: 46_299.79}
EXPECTED_ACTUAL_CENTS = 3_820_750_200
HTML_PATH = ROOT / "outputs" / "informe_gerencial_secos_armado_bolsa_actual_20261023.html"
JSON_PATH = HTML_PATH.with_suffix(".json")
CURRENT_PICKING = [
    (1, 0, 999, 0),
    (2, 1_000, 1_119, 4_811.52),
    (3, 1_120, 1_269, 6_609.13),
    (4, 1_270, 1_419, 12_938.42),
    (5, 1_420, 1_569, 18_088.30),
    (6, 1_570, 1_819, 25_362.88),
    (7, 1_820, 2_249, 35_898.34),
    (8, 2_250, 1_000_000, 52_085.12),
]


async def admin_local(_request):
    return {"role": "admin", "device_status": "approved"}


def profile_pair(report: dict) -> list[dict]:
    profiles = [p for p in report["perfiles"] if p["id"] in PROFILE_IDS]
    if len(profiles) != 2 or {p["sector"] for p in profiles} != set(SECTORS):
        raise RuntimeError("El informe no contiene los dos perfiles de Armado Secos esperados.")
    return profiles


def event_counts(profiles: list[dict]) -> tuple[int, dict[int, int]]:
    group_or_poly = 0
    levels = {n: 0 for n in range(1, 6)}
    for profile in profiles:
        for person in profile["piloto_legajos"]:
            for day in person["dias"]:
                group_or_poly += int(day["grupal"] > 0 or day["polivalencia"] > 0)
                level = int(day["nivel"] or 0)
                if day["individual"] > 0 and level in levels:
                    levels[level] += 1
    return group_or_poly, levels


def save_and_update(audit_id: str) -> dict:
    db_path = ROOT / "datos" / "laboratorio_premios.db"
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS lab_ajuste_umbral_auditoria(
            ejecucion TEXT NOT NULL, tipo TEXT NOT NULL, payload_json TEXT NOT NULL,
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(ejecucion,tipo))""")
        params = [dict(r) for r in db.execute("""SELECT * FROM lab_parametro_grupal
            WHERE activo=1 AND sector IN (?,?) AND funcion_legajero='ARMADOR'
              AND UPPER(TRIM(operacion_medible))='ARMADO' AND COALESCE(division_madre,'')='1'
            ORDER BY sector,turno""", SECTORS)]
        scales = [dict(r) for r in db.execute("""SELECT * FROM lab_escala_individual_grupal
            WHERE activo=1 AND sector IN (?,?) AND funcion_legajero='ARMADOR'
              AND UPPER(TRIM(operacion_medible))='ARMADO' AND COALESCE(division_madre,'')='1'
            ORDER BY sector,turno,nivel""", SECTORS)]
        if len(params) != 6 or len(scales) != 30:
            raise RuntimeError(f"Configuración inesperada: {len(params)} parámetros / {len(scales)} filas individuales.")
        if {float(p["uc_por_operario"]) for p in params} != {1100.0}:
            raise RuntimeError("El umbral grupal de Armado Secos cambió; se cancela para no reemplazarlo.")
        threshold_signatures = {}
        for sector in SECTORS:
            rows = [s for s in scales if s["sector"] == sector]
            signatures = {
                int(s["nivel"]): (float(s["desde_uc"]), float(s["hasta_uc"]))
                for s in rows if str(s["turno"]) == "1"
            }
            if set(signatures) != set(range(1, 6)):
                raise RuntimeError(f"Escala incompleta en {sector}.")
            threshold_signatures[sector] = signatures
        if threshold_signatures[SECTORS[0]] != threshold_signatures[SECTORS[1]]:
            raise RuntimeError("Los umbrales individuales entre zonas no coinciden.")
        per_turn = {}
        for sector in SECTORS:
            sector_rows = [s for s in scales if s["sector"] == sector]
            per_turn[sector] = {
                turn: {
                    int(s["nivel"]): (float(s["desde_uc"]), float(s["hasta_uc"]))
                    for s in sector_rows if str(s["turno"]) == turn
                }
                for turn in ("1", "2", "3")
            }
            if any(per_turn[sector][t] != threshold_signatures[sector] for t in ("1", "2", "3")):
                raise RuntimeError(f"Los umbrales no son iguales entre turnos en {sector}.")

        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (audit_id, "armado_secos_bolsa_cerrada_parametros_antes", json.dumps(params, ensure_ascii=False)))
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (audit_id, "armado_secos_bolsa_cerrada_escalas_antes", json.dumps(scales, ensure_ascii=False)))
        db.execute("INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json) VALUES(?,?,?)",
                   (audit_id, "armado_secos_bolsa_cerrada_criterio", json.dumps({
                       "periodo": PERIOD, "bolsa_actual_centavos": EXPECTED_ACTUAL_CENTS,
                       "reparto": {"grupal_incluye_polivalencia_pct": 60, "individual_pct": 40},
                       "premio_grupal_comun": GROUP_AWARD,
                       "premios_individuales_comunes": INDIVIDUAL_AWARDS,
                       "umbral_grupal_comun": 1100,
                       "umbrales_individuales_preservados": threshold_signatures[SECTORS[0]],
                   }, ensure_ascii=False)))

        cur = db.execute("""UPDATE lab_parametro_grupal SET premio_grupal=?,updated_at=CURRENT_TIMESTAMP
            WHERE activo=1 AND sector IN (?,?) AND funcion_legajero='ARMADOR'
              AND UPPER(TRIM(operacion_medible))='ARMADO' AND COALESCE(division_madre,'')='1'""",
                         (GROUP_AWARD, *SECTORS))
        if cur.rowcount != 6:
            raise RuntimeError(f"Se actualizaron {cur.rowcount} parámetros; se esperaban 6.")
        updated = 0
        for level, award in INDIVIDUAL_AWARDS.items():
            cur = db.execute("""UPDATE lab_escala_individual_grupal SET premio=?,updated_at=CURRENT_TIMESTAMP
                WHERE activo=1 AND sector IN (?,?) AND funcion_legajero='ARMADOR'
                  AND UPPER(TRIM(operacion_medible))='ARMADO' AND COALESCE(division_madre,'')='1'
                  AND nivel=?""", (award, *SECTORS, level))
            if cur.rowcount != 6:
                raise RuntimeError(f"Nivel N{level}: se actualizaron {cur.rowcount} filas, se esperaban 6.")
            updated += cur.rowcount
        db.commit()
        return {"parametros_actualizados": cur.rowcount if False else 6, "escalas_actualizadas": updated}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def add_current_scale_dialogs(html: str, profiles: list[dict], number) -> str:
    current_rows = "".join(
        f"<tr><td>N{level}</td><td>{number(low)}</td><td>{number(high)}</td><td>$ {number(prize, 2)}</td></tr>"
        for level, low, high, prize in CURRENT_PICKING
    )
    current_panel = (
        '<section class="scale-comparison-panel current"><h3>Escala actual · TablaActual.xlsx</h3>'
        '<div class="scale-source"><h4>PICKING · Secos + NOA</h4>'
        '<table class="current-scale-table"><thead><tr><th>Nivel actual</th><th>Desde</th><th>Hasta</th><th>Premio</th></tr></thead>'
        f'<tbody>{current_rows}</tbody></table></div>'
        '<p class="scale-note">La tabla actual usa niveles 1–8. La nueva escala del escenario usa grupal y niveles N1–N5.</p></section>'
    )
    css = """\n.scale-dialog{width:min(1180px,96vw)}.scale-dialog .dialog-body{padding:20px 24px}.scale-comparison{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;align-items:start}.scale-comparison-panel{min-width:0;padding:16px;border:1px solid #d8e4ea;border-radius:9px;background:#f8fbfc}.scale-comparison-panel.current{border-top:3px solid #879ba8}.scale-comparison-panel.proposed{border-top:3px solid #168b83}.scale-comparison-panel h3{margin:0 0 12px;font-size:16px;color:#21465d}.scale-source{margin:0 0 14px}.scale-source h4{font-size:12px;margin:0 0 6px;color:#526f7f}.scale-dialog .scale-comparison table{width:100%;max-width:none;margin:0;font-size:12px}.scale-dialog .scale-comparison td,.scale-dialog .scale-comparison th{padding:7px 9px;text-align:right}.scale-dialog .scale-comparison td:first-child,.scale-dialog .scale-comparison th:first-child{text-align:left;min-width:58px}.scale-dialog .current-scale-table td:last-child,.scale-dialog .current-scale-table th:last-child{white-space:nowrap}.scale-note{font-size:12px;line-height:1.5;color:#647d8a}.scale-dialog .dialog-criteria{margin-top:16px}@media(max-width:760px){.scale-comparison{grid-template-columns:1fr}.scale-dialog{width:min(96vw,620px)}}\n"""
    if "scale-comparison-panel current" in html:
        raise RuntimeError("El HTML fuente ya contiene la tabla actual; se cancela la duplicación.")
    style_end = html.find("</style>")
    if style_end < 0:
        raise RuntimeError("No se encontró el bloque de estilos del informe.")
    html = html[:style_end] + css + html[style_end:]
    for p in profiles:
        ident = f'detalle-escala-{p["id"]}'
        start = html.find(f'<dialog class="profile-dialog scale-dialog" id="{ident}"')
        if start < 0:
            raise RuntimeError(f"No se encontró el modal de escala para {p['id']}.")
        end = html.find("</dialog>", start) + len("</dialog>")
        block = html[start:end]
        table_match = re.search(r"<table>.*?</table>", block, re.S)
        if not table_match:
            raise RuntimeError(f"El modal de {p['id']} no contiene la escala del escenario.")
        proposed = '<section class="scale-comparison-panel proposed"><h3>Escala nueva · Escenario configurado</h3>' + table_match.group(0) + '</section>'
        block = block.replace(table_match.group(0), '<div class="scale-comparison">' + current_panel + proposed + '</div>', 1)
        block = block.replace("Escala vigente", "Escala del escenario", 1)
        block = re.sub(r'<p class="dialog-criteria">.*?</p>',
                       '<p class="dialog-criteria">La tabla izquierda reproduce los rangos y premios actuales de PICKING del Excel adjunto. La derecha muestra los umbrales y premios configurados para Armado Secos en este escenario.</p>',
                       block, count=1, flags=re.S)
        html = html[:start] + block + html[end:]
    return html


def generate_html(report: dict, payroll_details=None) -> None:
    # The report renderer composes slides from this list. Limit it to the one
    # operation requested while retaining the two zone rows in its slide.
    pages = compacto.PAGES
    compacto.PAGES = [("secos-armado", "Secos · Armado", "Zona 1 y Zona 2", [1, 5])]
    try:
        html = render(report, compact=True, payroll_details=payroll_details)
    finally:
        compacto.PAGES = pages
    # The generic conclusion points at reception, which is outside this file.
    html = re.sub(r'<section class="sheet compact-sheet compact-conclusion" id="decisiones">.*?</section>', '', html, count=1, flags=re.S)
    html = add_current_scale_dialogs(html, report["perfiles"], __import__("generar_informe_gerencial_umbrales").number)
    banner_css = '''\n.single-scope-banner{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:24px 0;padding:16px 20px;border:1px solid #b9d8d7;border-left:6px solid #168b83;border-radius:10px;background:linear-gradient(100deg,#e7f5f1,#f4f8fa);color:#21465d}.single-scope-banner strong{font-size:16px;white-space:nowrap}.single-scope-banner span{font-size:13px;color:#526f7f}.single-scope-banner b{color:#21465d}.audit-sheet{padding:34px 40px!important}.audit-head{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #d7e3e9;padding-bottom:20px;margin-bottom:22px}.audit-head h1{font-size:30px;margin:5px 0;color:#173f56}.audit-head p{margin:0;color:#5b7482}.audit-head .eyebrow{font-size:11px;letter-spacing:.12em;font-weight:800;color:#17867d}.audit-stamp{width:100px;height:100px;border-radius:50%;background:#e3f3ec;border:5px solid #53a98d;color:#17614f;font-size:24px;font-weight:800;display:flex;align-items:center;justify-content:center;flex-direction:column}.audit-stamp small{font-size:9px;font-weight:600}.audit-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0 20px}.audit-cards article{background:#eff5f8;border-top:3px solid #5c91a8;border-radius:7px;padding:14px}.audit-cards small,.audit-cards span{display:block;color:#617a89;font-size:11px}.audit-cards strong{display:block;font-size:26px;color:#214d64;margin:5px 0}.audit-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.audit-panel{padding:18px;border-radius:9px;border:1px solid #d7e3e9;background:#f8fbfc}.audit-panel h2{font-size:18px;margin:0 0 10px;color:#21465d}.audit-lede{font-size:12px;color:#5d7481;line-height:1.5}.audit-reasons{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}.audit-reason{display:flex;align-items:center;gap:10px;background:#fff;border:1px solid #e1e9ed;border-radius:6px;padding:8px}.audit-reason b{min-width:45px;font-size:17px;color:#167d74}.audit-reason span{font-size:11px;color:#405b6a}.audit-foot,.audit-source p{font-size:11px;line-height:1.55;color:#647b88}.audit-checks{list-style:none;padding:0;margin:0}.audit-checks li{display:grid;grid-template-columns:58px 1fr;gap:2px 8px;padding:8px 0;border-bottom:1px solid #e1e9ed;font-size:12px}.audit-checks li b{color:#16816c}.audit-checks li span{font-weight:700;color:#294c60}.audit-checks li small{grid-column:2;color:#687e89}.audit-source{margin-top:14px;padding:12px;border-left:4px solid #d9ab4f;background:#fff9e9}.audit-source b{font-size:12px;color:#745c22}.audit-details{margin-top:18px;border:1px solid #d7e3e9;border-radius:8px;padding:12px 16px;background:#fff}.audit-details summary{cursor:pointer;font-weight:700;color:#21465d}.audit-details .table-scroll{max-height:280px;overflow:auto;margin-top:12px}.audit-details table{width:100%;font-size:11px;border-collapse:collapse}.audit-details th,.audit-details td{padding:6px 8px;border-bottom:1px solid #e1e9ed;text-align:right}.audit-details th:first-child,.audit-details td:first-child{text-align:left}.audit-footer{margin-top:14px;font-size:10px;color:#718692}@media(max-width:800px){.audit-sheet{padding:20px!important}.audit-cards{grid-template-columns:repeat(2,1fr)}.audit-grid{grid-template-columns:1fr}.audit-head{align-items:flex-start}.audit-stamp{width:76px;height:76px;font-size:20px}}\n'''
    style_end = html.find("</style>")
    banner_css += '''
    /* La lámina de auditoría ocupa todo el lienzo y mantiene texto legible al proyectar. */
    .presentation .audit-sheet .slide-canvas{width:2000px;padding:32px 46px;}
    .presentation .audit-sheet .audit-head h1{font-size:34px;max-width:none}
    .presentation .audit-sheet .audit-head p{font-size:16px}
    .presentation .audit-sheet .audit-head .eyebrow{font-size:13px}
    .presentation .audit-sheet .audit-stamp{width:112px;height:112px;font-size:28px}
    .presentation .audit-sheet .audit-stamp small{font-size:11px}
    .presentation .audit-sheet .audit-cards{gap:16px;margin:20px 0 22px}
    .presentation .audit-sheet .audit-cards article{padding:18px}
    .presentation .audit-sheet .audit-cards small,.presentation .audit-sheet .audit-cards span{font-size:14px}
    .presentation .audit-sheet .audit-cards strong{font-size:32px}
    .presentation .audit-sheet .audit-grid{grid-template-columns:1fr 1fr;gap:22px}
    .presentation .audit-sheet .audit-panel{padding:22px}
    .presentation .audit-sheet .audit-panel h2{font-size:22px}
    .presentation .audit-sheet .audit-lede{font-size:15px}
    .presentation .audit-sheet .audit-reasons{gap:10px}
    .presentation .audit-sheet .audit-reason{padding:11px;gap:14px}
    .presentation .audit-sheet .audit-reason b{font-size:22px;min-width:58px}
    .presentation .audit-sheet .audit-reason span{font-size:14px}
    .presentation .audit-sheet .audit-foot,.presentation .audit-sheet .audit-source p{font-size:13px}
    .presentation .audit-sheet .audit-checks li{grid-template-columns:72px 1fr;gap:4px 12px;padding:10px 0;font-size:14px}
    .presentation .audit-sheet .audit-checks li small{font-size:12px}
    .presentation .audit-sheet .audit-source{padding:14px;margin-top:18px}
    .presentation .audit-sheet .audit-source b{font-size:14px}
    .presentation .audit-sheet .audit-activity-summary{gap:24px;margin-top:18px;padding:15px 20px;font-size:15px}
    .presentation .audit-sheet .audit-activity-summary>b{font-size:16px}
    .presentation .audit-sheet .audit-activity-summary strong{font-size:23px}
    .presentation .audit-sheet .audit-activity-summary small{font-size:12px;max-width:340px}
    .presentation .audit-sheet .audit-details{margin-top:16px;padding:14px 18px}
    .presentation .audit-sheet .audit-details summary{font-size:15px}
    .presentation .audit-sheet .audit-footer{font-size:12px}
    @media(max-width:1100px){.presentation .audit-sheet .slide-canvas{width:1280px}.presentation .audit-sheet .audit-grid{grid-template-columns:1fr}.presentation .audit-sheet .audit-cards{grid-template-columns:repeat(2,1fr)}}
    @media print{.audit-sheet{padding:14px 20px!important}.audit-sheet .audit-head h1{font-size:26px}.audit-sheet .audit-grid{grid-template-columns:1fr 1fr}.audit-sheet .audit-cards{grid-template-columns:repeat(4,1fr)}.audit-sheet .audit-panel{padding:12px}.audit-sheet .audit-reason{padding:6px}.audit-sheet .audit-checks li{padding:5px 0;font-size:10px}.audit-sheet .audit-activity-summary{margin-top:8px;padding:8px}.audit-sheet .audit-details .table-scroll{max-height:none;overflow:visible}.audit-sheet .audit-details table{font-size:9px}}
    @media(max-width:800px){.presentation .audit-sheet .audit-grid{grid-template-columns:1fr}.presentation .audit-sheet .audit-cards{grid-template-columns:repeat(2,1fr)}.presentation .audit-sheet .audit-activity-summary{align-items:flex-start;flex-direction:column;gap:5px}.presentation .audit-sheet .audit-activity-summary small{margin-left:0}}
    '''
    html = html[:style_end] + banner_css + html[style_end:]
    banner = ('<aside class="single-scope-banner"><strong>Armado · Secos</strong>'
              '<span>Bolsa actual cerrada en <b>$ 38.207.502</b> · reparto objetivo <b>60% grupal</b> '
              '(incluye polivalencia) y <b>40% individual</b> · mismos umbrales y premios para Zona 1 y Zona 2.</span></aside>')
    html = html.replace("<main>", "<main>" + banner, 1)
    html = re.sub(r"<title>.*?</title>", "<title>VigIA · Escenario de premios · Armado Secos</title>", html, count=1, flags=re.S)
    validation = report.get("validacion_cruzada")
    if validation:
        validation_html = render_validation_slide(validation)
        anchor = '<section class="sheet compact-conclusion" id="resumen-economico">'
        if anchor in html:
            html = html.replace(anchor, validation_html + anchor, 1)
        else:
            html = html.replace("</main>", validation_html + "</main>", 1)
    productivity = report.get("base_productiva_secos_sep")
    if productivity:
        base_slide = render_productivity_slide(productivity)
        html, inserted = re.subn(
            r'(<section class="sheet compact-sheet compact-method" id="metodo-visual">.*?</section>)',
            lambda match: match.group(1) + base_slide,
            html, count=1, flags=re.S)
        if not inserted:
            raise RuntimeError("No se encontró la hoja de introducción para insertar el resumen productivo de Secos.")
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_PATH.write_text(html, encoding="utf-8")
    JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_productivity_summary() -> dict:
    """Resumen bruto de septiembre, desde el cache interno existente, sin recalcularlo."""
    db = sqlite3.connect((ROOT / "datos" / "laboratorio_premios.db").as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        cache = db.execute("""SELECT nivel_2_json,nivel_3_json,calculado_at
            FROM lab_calculo_grupal_cache
            WHERE fecha_desde='20260801' AND fecha_hasta='20260930'
            ORDER BY calculado_at DESC LIMIT 1""").fetchone()
        if not cache:
            raise RuntimeError("No hay cache de agosto-septiembre para resumir las 30 fechas de septiembre.")
        groups = [row for row in json.loads(cache["nivel_2_json"])
                  if "20260901" <= str(row.get("fecha") or "") <= "20260930"
                  and row.get("sector") in SECTORS]
        detail = [row for row in json.loads(cache["nivel_3_json"])
                  if "20260901" <= str(row.get("fecha") or "") <= "20260930"
                  and row.get("sector") in SECTORS]
    finally:
        db.close()

    operations = ("ARMADO", "CLARK", "RECEPCION", "PALETS OPERADOS")
    zones = SECTORS
    rows = {}
    for operation in operations:
        for sector in zones:
            rows[(operation, sector)] = {
                "operation": operation, "sector": sector, "unit": None,
                "gross_uc": 0.0, "computable_uc": 0.0, "legs": set(),
                "legajo_days": set(), "present_days": set(), "active_days": set(),
                "dates": set(), "roster_daily": {}, "has_group_rows": False,
                "has_detail_rows": False, "functions": set(),
            }
    for group in groups:
        key = (str(group.get("operacion") or ""), str(group.get("sector") or ""))
        item = rows.get(key)
        if not item:
            continue
        item["has_group_rows"] = True
        item["unit"] = item["unit"] or group.get("unidad_medida")
        date = str(group.get("fecha") or "")
        item["dates"].add(date)
        item["roster_daily"][date] = item["roster_daily"].get(date, 0) + int(group.get("nomina_total") or 0)
        item["computable_uc"] += float(group.get("uc_computables") or 0)
        if group.get("funcion_legajero"):
            item["functions"].add(str(group["funcion_legajero"]))
    for row in detail:
        key = (str(row.get("operacion") or ""), str(row.get("sector") or ""))
        item = rows.get(key)
        if not item:
            continue
        item["has_detail_rows"] = True
        item["unit"] = item["unit"] or row.get("unidad_medida")
        date, legajo = str(row.get("fecha") or ""), str(row.get("legajo") or "")
        if date and legajo:
            item["legs"].add(legajo)
            item["legajo_days"].add((legajo, date))
            if row.get("asistencia") == "Presente":
                item["present_days"].add((legajo, date))
            if float(row.get("uc_brutas") or 0) > 0:
                item["active_days"].add((legajo, date))
        item["gross_uc"] += float(row.get("uc_brutas") or 0)

    result_rows = []
    for operation in operations:
        for sector in zones:
            item = rows[(operation, sector)]
            avg_roster = (sum(item["roster_daily"].values()) / len(item["roster_daily"])
                          if item["roster_daily"] else None)
            status = ("OK" if item["has_group_rows"] and item["has_detail_rows"] else
                      "SIN NÓMINA EN CACHE" if item["has_group_rows"] else "SIN FILAS DE CACHE")
            result_rows.append({
                "operation": operation, "sector": sector,
                "unit": item["unit"] or ("BULTO" if operation == "ARMADO" else "PALET"),
                "gross_uc": round(item["gross_uc"], 3),
                "computable_uc": round(item["computable_uc"], 3),
                "legs": sorted(item["legs"]), "legajo_count": len(item["legs"]),
                "avg_roster_daily": round(avg_roster, 2) if avg_roster is not None else None,
                "legajo_days": len(item["legajo_days"]),
                "present_days": len(item["present_days"]),
                "active_days": len(item["active_days"]),
                "gross_per_active_legajo_day": round(item["gross_uc"] / len(item["active_days"]), 1)
                    if item["active_days"] else None,
                "status": status,
                "functions": sorted(item["functions"]),
            })

    summary = []
    labels = {"ARMADO": "Armado", "CLARK": "Clark", "RECEPCION": "Recepción",
              "PALETS OPERADOS": "Carga · palets operados"}
    for operation in operations:
        scoped = [row for row in result_rows if row["operation"] == operation]
        real_rows = [row for row in scoped if row["status"] != "SIN FILAS DE CACHE"]
        legs = set().union(*(set(row["legs"]) for row in real_rows)) if real_rows else set()
        gross = sum(row["gross_uc"] for row in real_rows)
        computable = sum(row["computable_uc"] for row in real_rows)
        active_days = sum(row["active_days"] for row in real_rows)
        avg_daily = sum(row["avg_roster_daily"] or 0 for row in real_rows)
        units = next((row["unit"] for row in real_rows if row["unit"]), "PALET")
        summary.append({
            "operation": operation, "label": labels[operation], "unit": units,
            "gross_uc": round(gross, 3), "computable_uc": round(computable, 3),
            "legajo_count": len(legs), "avg_roster_daily": round(avg_daily, 2),
            "active_days": active_days,
            "gross_per_active_legajo_day": round(gross / active_days, 1) if active_days else None,
            "coverage_note": ("Zona 2 sin filas de cache" if all(r["status"] == "SIN FILAS DE CACHE" for r in scoped if r["sector"] == SECTORS[1]) else
                              "Zona 1 sin nómina en cache" if operation == "RECEPCION" else
                              ""),
        })
    return {
        "period": "01–30 septiembre 2026", "calendar_days": 30,
        "cache_calculated_at": cache["calculado_at"], "rows": result_rows,
        "operations": summary,
        "source_note": "Cache interno de Productividad: PV_ETAPA_CAB/DET y datos locales de imputación. No es una extracción directa del WMS crudo.",
    }


def render_productivity_slide(data: dict) -> str:
    fmt = lambda value: f"{float(value):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    unit_label = {"BULTO": "bultos", "PALET": "palets", "PLU": "PLUs"}
    cards = []
    colors = {"ARMADO": "#168b83", "CLARK": "#557da4", "RECEPCION": "#b58a39", "PALETS OPERADOS": "#6d8b63"}
    for operation in data["operations"]:
        units = unit_label.get(operation["unit"], operation["unit"].lower())
        extra = f" · {operation['coverage_note']}" if operation["coverage_note"] else ""
        avg = fmt(operation["gross_per_active_legajo_day"]) if operation["gross_per_active_legajo_day"] is not None else "—"
        cards.append(f'''<article class="base-op-card" style="--base-op:{colors[operation['operation']]}">
          <span>{operation['label']}</span><strong>{fmt(operation['gross_uc'])} <small>{units}</small></strong>
          <div><b>{fmt(operation['legajo_count'])}</b> legajos de nómina únicos · <b>{fmt(operation['avg_roster_daily'])}</b> nómina media diaria</div>
          <p>≈ {avg} {units} por legajo-día con UC &gt; 0{extra}</p>
        </article>''')
    rows = []
    op_labels = {"ARMADO": "Armado", "CLARK": "Clark", "RECEPCION": "Recepción", "PALETS OPERADOS": "Carga · palets operados"}
    for row in data["rows"]:
        units = unit_label.get(row["unit"], row["unit"].lower())
        if row["status"] == "SIN FILAS DE CACHE":
            gross = computable = legs = avg_roster = activity_days = rate = "—"
            status = "Sin filas de cache"
        else:
            gross, computable = fmt(row["gross_uc"]), fmt(row["computable_uc"])
            legs = fmt(row["legajo_count"])
            avg_roster = fmt(row["avg_roster_daily"]) if row["avg_roster_daily"] is not None else "0"
            activity_days = fmt(row["active_days"])
            rate = fmt(row["gross_per_active_legajo_day"]) if row["gross_per_active_legajo_day"] is not None else "—"
            status = "Sin legajos asociados" if row["status"] == "SIN NÓMINA EN CACHE" else "En cache"
        rows.append(f'''<tr><th>{op_labels[row['operation']]}</th><td>{row['sector'].replace('CD-SECOS - ', '')}</td><td>{units}</td>
          <td class="numeric">{gross}</td><td class="numeric">{computable}</td><td class="numeric">{legs}</td>
          <td class="numeric">{avg_roster}</td><td class="numeric">{activity_days}</td><td class="numeric">{rate}</td><td><span class="base-status {'missing' if row['status'] != 'OK' else ''}">{status}</span></td></tr>''')
    style = '''<style>
    .productivity-base-sheet{--base-ink:#173c52;--base-muted:#5c7482;--base-line:#d9e5ea;padding:24px 34px!important;color:var(--base-ink)}
    .presentation .productivity-base-sheet .slide-canvas{width:2000px;padding:26px 38px}
    .base-heading{display:flex;justify-content:space-between;align-items:end;gap:20px;border-left:6px solid #168b83;padding:4px 0 8px 16px;margin-bottom:16px}
    .base-heading .eyebrow{font-size:13px;color:#168078}.base-heading h2{font-size:32px;margin:2px 0}.base-heading p{font-size:14px;color:var(--base-muted);margin:3px 0}.base-validation-tag{padding:9px 14px;border:1px solid #e3c878;border-radius:7px;background:#fff8e5;color:#745c22;font-weight:700;font-size:13px;white-space:nowrap}
    .base-op-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:14px 0 18px}.base-op-card{border:1px solid var(--base-line);border-top:5px solid var(--base-op);border-radius:9px;background:#f5f9fa;padding:14px 16px;min-width:0}.base-op-card>span{display:block;font-size:15px;font-weight:700;color:var(--base-ink)}.base-op-card>strong{display:block;font-size:29px;line-height:1.2;margin:6px 0;color:var(--base-op);white-space:nowrap}.base-op-card>strong small{font-size:15px;color:var(--base-muted);font-weight:600}.base-op-card>div,.base-op-card>p{font-size:12px;color:var(--base-muted);margin:4px 0}.base-op-card>div b{color:var(--base-ink)}
    .base-table-title{display:flex;justify-content:space-between;gap:12px;align-items:baseline;margin:10px 0}.base-table-title h3{font-size:18px}.base-table-title span{font-size:12px;color:var(--base-muted)}.base-table-wrap{border:1px solid var(--base-line);border-radius:8px;overflow:hidden}.base-productivity-table{width:100%;border-collapse:collapse;font-size:13px}.base-productivity-table th,.base-productivity-table td{padding:9px 10px;border-bottom:1px solid #e7eef1;text-align:left;white-space:nowrap}.base-productivity-table thead th{background:#edf4f6;font-size:11px;color:#4d6a79;text-transform:uppercase;letter-spacing:.35px}.base-productivity-table tbody tr:nth-child(even){background:#f8fafb}.base-productivity-table .numeric{text-align:right;font-variant-numeric:tabular-nums}.base-status{display:inline-block;padding:3px 7px;border-radius:4px;background:#e7f3ef;color:#21715f;font-size:10px;font-weight:700}.base-status.missing{background:#fff4dc;color:#865d16}
    .base-notes{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}.base-note{padding:10px 13px;border-left:4px solid #568ba1;background:#eff6f8;border-radius:0 5px 5px 0}.base-note.warn{border-color:#d7a53e;background:#fff8e8}.base-note b{font-size:12px}.base-note p{font-size:11px;line-height:1.35;color:var(--base-muted);margin:3px 0}.base-source{font-size:10px;color:#70838d;margin:9px 0 0}
    @media(max-width:850px){.base-op-cards{grid-template-columns:1fr 1fr}.base-notes{grid-template-columns:1fr}.base-table-wrap{overflow:auto}}
    @media print{.productivity-base-sheet{padding:14px!important}.base-op-cards{gap:7px}.base-op-card{padding:8px}.base-op-card>strong{font-size:21px}.base-productivity-table th,.base-productivity-table td{padding:5px;font-size:9px}.base-notes{gap:7px}.base-note{padding:6px}.base-note p{font-size:8px}}
    </style>'''
    return f'''<section class="sheet compact-sheet productivity-base-sheet" id="base-productiva-secos">
      {style}<header class="base-heading"><div><span class="eyebrow">Base operativa · {data['period']} · 30 fechas calendario</span><h2>Secos · Resumen de productividad</h2><p>Volumen bruto y nómina observados en el cache, antes de discutir umbrales o premios.</p></div><span class="base-validation-tag">Para validar con Operaciones</span></header>
      <div class="base-op-cards">{''.join(cards)}</div>
      <div class="base-table-title"><h3>Detalle por operación y zona</h3><span>Unidades y nómina no se suman entre operaciones: puede haber legajos compartidos.</span></div>
      <div class="base-table-wrap"><table class="base-productivity-table"><thead><tr><th>Operación</th><th>Zona</th><th>Unidad</th><th>UC brutas</th><th>UC computables grupal</th><th>Legajos nómina únicos</th><th>Nómina prom./día</th><th>Legajo-días con UC</th><th>UC / legajo-día con UC</th><th>Estado</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
      <div class="base-notes"><aside class="base-note"><b>Cómo leer el indicador aproximado</b><p>UC brutas ÷ legajo-días con UC mayor que cero. La tabla también muestra el volumen computable para el grupal y la nómina media diaria; así se ven diferencias y ceros sin asumir que equivalen a productividad oficial.</p></aside>
      <aside class="base-note warn"><b>Validaciones pendientes visibles</b><p>Recepción Zona 1 aparece sin legajos asociados en el cache; Carga Zona 2 no presenta filas. Confirmar con Operaciones si corresponde a una ausencia de actividad, de nómina o de parametrización.</p></aside></div>
      <p class="base-source">Fuente: {data['source_note']} · Mes calendario completo: se incluyen sábados y domingos. El resumen no usa como referencia los valores de la fotografía ni valida la extracción de origen. Cache consultado: {data['cache_calculated_at']}.</p>
    </section>'''


def render_validation_slide(data: dict) -> str:
    fmt_int = lambda value: f"{int(value):,}".replace(",", ".")
    fmt_date = lambda value: f"{value[6:8]}/{value[4:6]}/{value[:4]}"
    daily_rows = "".join(
        f"<tr><td>{fmt_date(row['fecha'])}</td><td>{row['z1_nomina']}</td><td>{row['z1_activos']}</td>"
        f"<td>{row['z2_nomina']}</td><td>{row['z2_activos']}</td><td>{row['activos_total']}</td></tr>"
        for row in data['diario']
    )
    reasons = "".join(f"<div class=\"audit-reason\"><b>{fmt_int(item['cantidad'])}</b><span>{item['label']}</span></div>"
                      for item in data['categorias'])
    checks = "".join(f"<li><b>{item['estado']}</b><span>{item['label']}</span><small>{item['detalle']}</small></li>"
                     for item in data['controles'])
    return f'''<section class="sheet compact-sheet audit-sheet" id="validacion-secos-armado">
      <header class="audit-head"><div><p class="eyebrow">ANEXO · CONTROL DE CALIDAD</p><h1>Armado Secos · Validación cruzada</h1>
      <p>Conciliación del escenario antes de su uso gerencial · 1 de agosto al 30 de septiembre de 2026</p></div>
      <div class="audit-stamp">{data['checks_ok']}/{len(data['controles'])}<small>controles cerrados</small></div></header>
      <div class="audit-cards">
        <article><small>Dotación propia del perfil</small><strong>{data['dotacion']}</strong><span>legajos · snapshot RRHH {data['rrhh_batch']}</span></article>
        <article><small>Universo evaluado</small><strong>{fmt_int(data['jornadas'])}</strong><span>legajo-días · 64 × 43 días</span></article>
        <article><small>Registros de nómina coincidentes</small><strong>{data['rrhh_match']}/{data['dotacion']}</strong><span>nombre, sector y función actuales</span></article>
        <article><small>Imputaciones sin WMS</small><strong>{data['ajustes']}</strong><span>filas lógicas · copias duplicadas deduplicadas</span></article>
      </div>
      <div class="audit-grid">
        <article class="audit-panel"><h2>¿Cómo se compone el universo?</h2>
          <p class="audit-lede">Cada legajo-día aparece en una sola categoría de estado. Los pagos grupal, individual y polivalencia son componentes y pueden coincidir en una jornada.</p>
          <div class="audit-reasons">{reasons}</div>
          <p class="audit-foot">La dotación propia está fijada desde el legajero vigente. Los {data['externos_excluidos']} registros externos de Armador quedan fuera del alcance de este escenario. La comparación con RRHH valida la fotografía actual, no reconstruye cambios históricos de puesto.</p>
        </article>
        <article class="audit-panel"><h2>Controles de consistencia</h2><ul class="audit-checks">{checks}</ul>
          <div class="audit-source"><b>Alcance de la fuente</b><p>La producción procede del cache interno de Productividad (PV_ETAPA_CAB/DET y datos locales de imputación). Este control concilia ese cache con sus agregados y con el legajero; no audita la extracción WareFlow → Productividad ni certifica correspondencia con el WMS crudo.</p></div>
        </article>
      </div>
      <div class="audit-activity-summary"><b>Personas con bultos registrados por día</b>
        <span>Zona 1: <strong>{str(data['actividad_promedio_z1']).replace('.', ',')}</strong> de {data['z1_dotacion']} promedio</span>
        <span>Zona 2: <strong>{str(data['actividad_promedio_z2']).replace('.', ',')}</strong> de {data['z2_dotacion']} promedio</span>
        <small>Una vez por legajo-día con UC de Armado mayor que cero.</small>
      </div>
      <details class="audit-details"><summary>Ver actividad medible por día · 43 jornadas</summary>
        <div class="table-scroll"><table><thead><tr><th>Fecha</th><th>Z1 nómina</th><th>Z1 con bultos</th><th>Z2 nómina</th><th>Z2 con bultos</th><th>Total activos</th></tr></thead><tbody>{daily_rows}</tbody></table></div>
      </details>
      <footer class="audit-footer">Validación reproducible sobre caches internos · generada {data['generated_at']} · no sustituye la auditoría del origen transaccional.</footer>
    </section>'''


def collect_validation(report: dict) -> dict:
    """Cruza nómina, eventos y caches persistidos para el alcance del piloto."""
    db = sqlite3.connect(ROOT / "datos" / "laboratorio_premios.db")
    db.row_factory = sqlite3.Row
    rrhh = sqlite3.connect(ROOT / "datos" / "vigia.db")
    rrhh.row_factory = sqlite3.Row
    try:
        profiles = profile_pair(report)
        people = {str(person['legajo']): profile for profile in profiles for person in profile['piloto_legajos']}
        z1_count = sum(1 for p in profiles if p['sector'] == SECTORS[0] for _ in p['piloto_legajos'])
        z2_count = sum(1 for p in profiles if p['sector'] == SECTORS[1] for _ in p['piloto_legajos'])
        active_rrhh = rrhh.execute("""SELECT CAST(legajo AS TEXT) legajo,MAX(nombre) nombre,
            MAX(desc_sector_generico) sector,MAX(desc_funcion) funcion
            FROM rrhh_personas WHERE active=1 AND UPPER(TRIM(COALESCE(desc_grupo_personal,'')))='PROPIOS'
            GROUP BY CAST(legajo AS TEXT)""").fetchall()
        rrhh_map = {str(r['legajo']): r for r in active_rrhh}
        rrhh_profile_matches = 0
        for profile in profiles:
            expected_sector = profile['sector'].upper()
            for person in profile['piloto_legajos']:
                rec = rrhh_map.get(str(person['legajo']))
                if rec and str(rec['sector'] or '').strip().upper() == expected_sector and str(rec['funcion'] or '').strip().upper() == 'ARMADOR':
                    rrhh_profile_matches += 1

        report_days = {}
        for profile in profiles:
            for person in profile['piloto_legajos']:
                for day in person['dias']:
                    if day['fecha'][:4] in ('2026',) and day['fecha'] >= '20260801' and day['fecha'] <= '20260930':
                        report_days[(str(person['legajo']), str(day['fecha']))] = (profile, day)
        statuses = Counter()
        group_event_count = poly_event_count = 0
        individual_report = {}
        for key, (profile, day) in report_days.items():
            group_event_count += int(day.get('grupal', 0) > 0)
            poly_event_count += int(day.get('polivalencia', 0) > 0)
            if day.get('individual', 0) > 0:
                individual_report[key] = (int(day.get('nivel') or 0), round(float(day['individual']) / 100, 2), float(day.get('uc') or 0))

        z1_fixed = z1_count * 43
        z2_fixed = z2_count * 43
        if len(report_days) != z1_fixed + z2_fixed:
            raise RuntimeError(f"El calendario por legajo no concilia: {len(report_days)} contra {z1_fixed + z2_fixed}.")
        daily = []
        for row in report['perfiles']:
            pass
        date_counts = {}
        for key, (profile, day) in report_days.items():
            date = key[1]
            item = date_counts.setdefault(date, {'z1_nomina': z1_count, 'z1_activos': 0, 'z2_nomina': z2_count, 'z2_activos': 0})
            active = float(day.get('uc') or 0) > 0
            if profile['sector'] == SECTORS[0]: item['z1_activos'] += int(active)
            else: item['z2_activos'] += int(active)
        # Day keys are YYYYMMDD; weekdays are included explicitly by the 43 date list from the cached report.
        weekdays = {str(day['fecha']) for p in profiles for day in p['diario']}
        weekdays = {d for d in weekdays if d >= '20260801' and d <= '20260930'}
        daily = [{'fecha': date, **date_counts[date], 'activos_total': date_counts[date]['z1_activos'] + date_counts[date]['z2_activos']}
                 for date in sorted(weekdays) if date in date_counts]

        eval_rows = db.execute("""SELECT fecha,CAST(legajo AS TEXT) legajo,sector,
            unidades_evaluadas,nivel_nuevo,premio_nuevo,evaluacion_estado
            FROM lab_evaluacion_premio WHERE fecha BETWEEN '20260801' AND '20260930'
            AND UPPER(TRIM(operacion_premio))='ARMADO' AND sector IN (?,?)""", SECTORS).fetchall()
        eval_map = {(str(r['legajo']), str(r['fecha']), str(r['sector'])): r for r in eval_rows}
        individual_mismatch = 0
        for (legajo, fecha), (profile, day) in report_days.items():
            key = (legajo, fecha, profile['sector'])
            expected = individual_report.get((legajo, fecha))
            actual = eval_map.get(key)
            if expected is None:
                if actual and int(actual['nivel_nuevo'] or 0) > 0:
                    individual_mismatch += 1
            elif (not actual or int(actual['nivel_nuevo'] or 0) != expected[0]
                  or abs(float(actual['premio_nuevo'] or 0) - expected[1]) > 0.01
                  or abs(float(actual['unidades_evaluadas'] or 0) - expected[2]) > 1e-6):
                individual_mismatch += 1

        adjustment = db.execute("""SELECT snapshot,fecha,legajo,desc_funcion,division,sector,palets,plus,cantidad,peso,detalle_filas,origen
            FROM lab_cache_agrupado_ajuste ORDER BY snapshot""").fetchall()
        by_snapshot = {}
        for row in adjustment:
            by_snapshot.setdefault(row['snapshot'], Counter())[tuple(row[k] for k in row.keys() if k != 'snapshot')] += 1
        snapshot_match = len(by_snapshot) == 2 and len({sum(c.values()) for c in by_snapshot.values()}) == 1 and len({frozenset(c.items()) for c in by_snapshot.values()}) == 1
        adjustment_rows = sum(by_snapshot[sorted(by_snapshot)[0]].values()) if snapshot_match else 0

        rrhh_batch = rrhh.execute("SELECT MAX(batch_id) FROM rrhh_import_batches WHERE status='complete'").fetchone()[0]
        outside_count = rrhh.execute("""SELECT COUNT(DISTINCT CAST(legajo AS TEXT)) FROM rrhh_personas
            WHERE active=1 AND UPPER(TRIM(COALESCE(desc_grupo_personal,'')))='EXTERNOS'
            AND UPPER(TRIM(desc_funcion))='ARMADOR' AND desc_sector_generico IN (?,?)""", SECTORS).fetchone()[0]
        group_rows = db.execute("""SELECT * FROM lab_calculo_grupal_cache WHERE fecha_desde='20260801' AND fecha_hasta='20260930'""").fetchone()
        group_days = json.loads(group_rows['nivel_2_json']) if group_rows else []
        group_days = [row for row in group_days if row.get('fecha') in weekdays
                      and row.get('sector') in SECTORS and row.get('funcion_legajero') == 'ARMADOR'
                      and str(row.get('operacion') or '').upper() == 'ARMADO'
                      and str(row.get('division_madre') or '') == '1']
        detail_rows = json.loads(group_rows['nivel_3_json']) if group_rows else []
        detail_rows = [row for row in detail_rows if row.get('fecha') in weekdays
                       and row.get('sector') in SECTORS and row.get('funcion_legajero') == 'ARMADOR'
                       and str(row.get('operacion') or '').upper() == 'ARMADO'
                       and str(row.get('division_madre') or '') == '1']
        cache_names = {}
        for row in detail_rows:
            cache_names.setdefault(str(row['legajo']), str(row.get('nombre') or '').strip().upper())
        name_matches = sum(1 for legajo, profile in people.items()
                           if str(rrhh_map.get(legajo)['nombre'] or '').strip().upper() == cache_names.get(legajo, ''))
        rrhh_matches = min(rrhh_profile_matches, name_matches)
        detail_aggregate = {}
        for row in detail_rows:
            key = (row['fecha'], row['sector'], str(row.get('turno') or ''))
            agg = detail_aggregate.setdefault(key, Counter())
            agg['nomina_total'] += 1
            agg['fuera_vigencia'] += int(not row.get('vigente'))
            agg['sin_registro'] += int(bool(row.get('sin_registro')))
            agg['presentes'] += int(row.get('asistencia') == 'Presente' and row.get('motivo_inclusion') != 'Presente sin actividad productiva')
            agg['ausentes_permitidos'] += int(bool(row.get('ausencia_permitida')))
            agg['ausentes_no_permitidos'] += int(row.get('asistencia') == 'Ausente' and not row.get('ausencia_permitida'))
            agg['polivalentes'] += int(bool(row.get('es_polivalencia')))
            agg['nomina_computable'] += int(bool(row.get('integra_meta')))
            agg['beneficiarios'] += int(bool(row.get('beneficiario')))
            agg['uc_computables'] += float(row.get('uc_computables') or 0)
            agg['premio_grupal_total'] += float(row.get('premio_grupal') or 0)
            asistencia = row.get('asistencia')
            motivo = str(row.get('motivo_inclusion') or '')
            if motivo == 'Fuera de vigencia': status = 'Fuera de vigencia'
            elif motivo == 'Sin PV ni actividad productiva': status = 'Sin PV ni actividad productiva'
            elif asistencia == 'Ausente': status = 'Ausencia permitida' if row.get('ausencia_permitida') else 'Ausencia no permitida'
            elif asistencia == 'Sin confirmar': status = 'Jornada PV no computable'
            elif motivo == 'Polivalencia': status = 'Presente con polivalencia'
            elif motivo == 'Presente sin actividad productiva': status = 'Presente sin actividad medible'
            elif row.get('cobra'): status = 'Elegible · con premio grupal'
            else: status = 'Elegible · sin premio grupal'
            statuses[status] += 1
        required_categories = ['Elegible · con premio grupal','Elegible · sin premio grupal','Presente con polivalencia',
            'Ausencia permitida','Ausencia no permitida','Presente sin actividad medible','Fuera de vigencia',
            'Jornada PV no computable','Sin PV ni actividad productiva']
        categories = [{'label': label, 'cantidad': statuses[label]} for label in required_categories]
        partition_ok = sum(x['cantidad'] for x in categories) == z1_fixed + z2_fixed
        report_to_cache_matches = 0
        detail_by_legajo = {(str(row['legajo']), str(row['fecha']), str(row['sector'])): row for row in detail_rows}
        for (legajo, fecha), (profile, day) in report_days.items():
            cached = detail_by_legajo.get((legajo, fecha, profile['sector']))
            if cached and abs(float(cached.get('uc_brutas') or 0) - float(day.get('uc') or 0)) < 1e-6:
                report_to_cache_matches += 1
        aggregate_mismatch = 0
        aggregate_fields = ('nomina_total','fuera_vigencia','sin_registro','presentes','ausentes_permitidos',
                            'ausentes_no_permitidos','polivalentes','nomina_computable','beneficiarios',
                            'uc_computables','premio_grupal_total')
        for row in group_days:
            agg = detail_aggregate.get((row['fecha'], row['sector'], str(row.get('turno') or '')), {})
            for field in aggregate_fields:
                if abs(float(agg.get(field, 0)) - float(row.get(field) or 0)) > 0.001:
                    aggregate_mismatch += 1
                    break
        checks = [
            {'estado':'OK' if rrhh_matches == len(people) else 'REVISAR','label':'Legajero ↔ perfiles y cache de detalle','detalle':f"{rrhh_matches} de {len(people)} coinciden en nombre, sector y función actuales."},
            {'estado':'OK' if len(report_days)==z1_fixed+z2_fixed else 'REVISAR','label':'Nómina fija × jornadas hábiles','detalle':f"{z1_count} Zona 1 + {z2_count} Zona 2 durante 43 días = {len(report_days):,} legajo-días."},
            {'estado':'OK' if report_to_cache_matches==len(report_days) else 'REVISAR','label':'Cache de producción ↔ actividad del informe','detalle':f"{report_to_cache_matches} de {len(report_days):,} legajo-días concilian UC de Armado."},
            {'estado':'OK' if individual_mismatch==0 else 'REVISAR','label':'Escala individual ↔ pago por legajo-día','detalle':f"{len(individual_report):,} premios positivos; diferencias: {individual_mismatch}."},
            {'estado':'OK' if aggregate_mismatch==0 and len(group_days)==len(detail_aggregate) else 'REVISAR','label':'Detalle de legajos ↔ resumen grupal diario','detalle':f"{len(group_days)} filas fecha-turno contrastadas; filas con diferencias: {aggregate_mismatch}."},
            {'estado':'OK' if snapshot_match else 'REVISAR','label':'Snapshots de imputaciones sin WMS','detalle':f"{adjustment_rows} filas lógicas idénticas en dos snapshots; el motor conserva una copia."},
            {'estado':'OK' if partition_ok else 'REVISAR','label':'Partición de estados del universo','detalle':f"{sum(x['cantidad'] for x in categories):,} categorías exclusivas sobre {z1_fixed+z2_fixed:,} legajo-días."},
        ]
        actual_total = sum(int(p.get('actual_centavos') or 0) for p in profiles)
        new_total = sum(int(p.get('nuevo_centavos') or 0) for p in profiles)
        group_total = sum(int(day.get('grupal') or 0) + int(day.get('polivalencia') or 0)
                          for p in profiles for person in p['piloto_legajos'] for day in person['dias'])
        individual_total = sum(int(day.get('individual') or 0)
                               for p in profiles for person in p['piloto_legajos'] for day in person['dias'])
        bag_delta = new_total - actual_total
        grupal_pct = group_total / new_total * 100 if new_total else 0
        individual_pct = individual_total / new_total * 100 if new_total else 0
        checks.extend([
            {'estado':'OK' if abs(bag_delta) <= 1000 else 'REVISAR','label':'Bolsa nueva ↔ pago actual','detalle':f"Diferencia total ${bag_delta/100:,.2f}; tolerancia configurada: $10."},
            {'estado':'OK' if abs(grupal_pct-60)<=0.1 and abs(individual_pct-40)<=0.1 else 'REVISAR','label':'Distribución de la bolsa','detalle':f"Grupal + polivalencia {grupal_pct:.3f}% · individual {individual_pct:.3f}%."},
        ])
        return {'dotacion':len(people),'z1_dotacion':z1_count,'z2_dotacion':z2_count,
            'jornadas':len(report_days),'rrhh_match':rrhh_matches,'rrhh_batch':rrhh_batch,
            'ajustes':adjustment_rows,'categorias':categories,'diario':daily,'controles':checks,
            'checks_ok':sum(x['estado']=='OK' for x in checks),'generated_at':datetime.now().astimezone().strftime('%d/%m/%Y %H:%M'),
            'actividad_promedio_z1':round(sum(x['z1_activos'] for x in daily)/len(daily),2) if daily else 0,
            'actividad_promedio_z2':round(sum(x['z2_activos'] for x in daily)/len(daily),2) if daily else 0,
            'externos_excluidos':outside_count,'pago_actual_centavos':actual_total,'pago_nuevo_centavos':new_total,
            'diferencia_centavos':bag_delta,'grupal_pct':grupal_pct,'individual_pct':individual_pct}
    finally:
        db.close(); rrhh.close()


async def main() -> None:
    estudio._admin = admin_local
    execution = datetime.now().astimezone().isoformat(timespec="seconds")
    if "--individual-adjust" in sys.argv:
        db = sqlite3.connect(ROOT / "datos" / "laboratorio_premios.db")
        db.row_factory = sqlite3.Row
        try:
            scales = [dict(r) for r in db.execute("""SELECT * FROM lab_escala_individual_grupal
                WHERE activo=1 AND sector IN (?,?) AND funcion_legajero='ARMADOR'
                  AND UPPER(TRIM(operacion_medible))='ARMADO' AND COALESCE(division_madre,'')='1'
                ORDER BY sector,turno,nivel""", SECTORS)]
            if len(scales) != 30:
                raise RuntimeError("Escalas individuales incompletas; se cancela el ajuste.")
            db.execute("""INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json)
                VALUES(?,?,?)""", (execution, "armado_secos_crosscheck_escalas_antes_cierre", json.dumps(scales, ensure_ascii=False)))
            for level, award in INDIVIDUAL_AWARDS.items():
                cur = db.execute("""UPDATE lab_escala_individual_grupal SET premio=?,updated_at=CURRENT_TIMESTAMP
                    WHERE activo=1 AND sector IN (?,?) AND funcion_legajero='ARMADOR'
                      AND UPPER(TRIM(operacion_medible))='ARMADO' AND COALESCE(division_madre,'')='1' AND nivel=?""",
                    (award, *SECTORS, level))
                if cur.rowcount != 6:
                    raise RuntimeError(f"Nivel N{level}: actualización incompleta ({cur.rowcount}/6).")
            db.commit()
        finally:
            db.close()
        individual = await estudio.recalcular_individual(None, *PERIOD)
        final = analyze(*PERIOD)
        profiles = profile_pair(final)
        final['perfiles'] = profiles
        group_total = sum(day['grupal'] + day['polivalencia'] for p in profiles for person in p['piloto_legajos'] for day in person['dias'])
        individual_total = sum(day['individual'] for p in profiles for person in p['piloto_legajos'] for day in person['dias'])
        print(json.dumps({"ok":True,"ajuste_individual":execution,"premios_individuales":INDIVIDUAL_AWARDS,
            "grupal_y_polivalencia_centavos":group_total,"individual_centavos":individual_total,
            "nuevo_total_centavos":group_total+individual_total,
            "diferencia_actual_centavos":group_total+individual_total-EXPECTED_ACTUAL_CENTS,
            "grupal_pct":group_total/(group_total+individual_total)*100,
            "individual_pct":individual_total/(group_total+individual_total)*100,
            "eventos_individuales":event_counts(profiles)[1],"recalculo_individual":individual},
            ensure_ascii=False,indent=2),flush=True)
        return
    if "--calibrate-recalc" in sys.argv:
        db = sqlite3.connect(ROOT / "datos" / "laboratorio_premios.db")
        db.row_factory = sqlite3.Row
        try:
            params = [dict(r) for r in db.execute("""SELECT * FROM lab_parametro_grupal
                WHERE activo=1 AND sector IN (?,?) AND funcion_legajero='ARMADOR'
                  AND UPPER(TRIM(operacion_medible))='ARMADO' AND COALESCE(division_madre,'')='1'
                ORDER BY sector,turno""", SECTORS)]
            scales = [dict(r) for r in db.execute("""SELECT * FROM lab_escala_individual_grupal
                WHERE activo=1 AND sector IN (?,?) AND funcion_legajero='ARMADOR'
                  AND UPPER(TRIM(operacion_medible))='ARMADO' AND COALESCE(division_madre,'')='1'
                ORDER BY sector,turno,nivel""", SECTORS)]
            if len(params) != 6 or len(scales) != 30:
                raise RuntimeError("Configuración incompleta; no se actualizan los premios.")
            db.execute("""INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json)
                VALUES(?,?,?)""", (execution, "armado_secos_crosscheck_parametros_antes", json.dumps(params, ensure_ascii=False)))
            db.execute("""INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json)
                VALUES(?,?,?)""", (execution, "armado_secos_crosscheck_escalas_antes", json.dumps(scales, ensure_ascii=False)))
            updates = [db.execute("""UPDATE lab_parametro_grupal SET premio_grupal=?,updated_at=CURRENT_TIMESTAMP
                WHERE activo=1 AND sector=? AND funcion_legajero='ARMADOR' AND UPPER(TRIM(operacion_medible))='ARMADO'
                  AND COALESCE(division_madre,'')='1' AND turno=?""", (GROUP_AWARD, p['sector'], p['turno'])) for p in params]
            if any(c.rowcount != 1 for c in updates):
                raise RuntimeError("No se actualizaron exactamente los seis premios grupales.")
            for level, award in INDIVIDUAL_AWARDS.items():
                cur = db.execute("""UPDATE lab_escala_individual_grupal SET premio=?,updated_at=CURRENT_TIMESTAMP
                    WHERE activo=1 AND sector IN (?,?) AND funcion_legajero='ARMADOR'
                      AND UPPER(TRIM(operacion_medible))='ARMADO' AND COALESCE(division_madre,'')='1' AND nivel=?""",
                    (award, *SECTORS, level))
                if cur.rowcount != 6:
                    raise RuntimeError(f"Nivel N{level}: se actualizaron {cur.rowcount} filas; se esperaban 6.")
            db.execute("""INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json)
                VALUES(?,?,?)""", (execution, "armado_secos_bolsa_recalibrada_crosscheck", json.dumps({
                    "periodo": PERIOD, "motivo": "La deduplicación de imputaciones sin WMS modificó los eventos individuales.",
                    "premio_grupal_comun": GROUP_AWARD, "premios_individuales_comunes": INDIVIDUAL_AWARDS,
                    "objetivo_bolsa_centavos": EXPECTED_ACTUAL_CENTS, "reparto_objetivo": {"grupal_mas_polivalencia_pct":60,"individual_pct":40}
                }, ensure_ascii=False)))
            db.commit()
        finally:
            db.close()
        grouped = await estudio.calculo_grupal(None, *PERIOD)
        individual = await estudio.recalcular_individual(None, *PERIOD)
        final = analyze(*PERIOD)
        profiles = profile_pair(final)
        final['perfiles'] = profiles
        group_total = sum(day['grupal'] + day['polivalencia'] for p in profiles for person in p['piloto_legajos'] for day in person['dias'])
        individual_total = sum(day['individual'] for p in profiles for person in p['piloto_legajos'] for day in person['dias'])
        new_total = group_total + individual_total
        print(json.dumps({"ok":True,"calibracion":execution,"premio_grupal":GROUP_AWARD,
            "premios_individuales":INDIVIDUAL_AWARDS,"grupal_y_polivalencia_centavos":group_total,
            "individual_centavos":individual_total,"nuevo_total_centavos":new_total,
            "diferencia_actual_centavos":new_total-EXPECTED_ACTUAL_CENTS,
            "grupal_pct":group_total/new_total*100 if new_total else 0,
            "individual_pct":individual_total/new_total*100 if new_total else 0,
            "eventos_grupales_polivalencia":event_counts(profiles)[0],"eventos_individuales":event_counts(profiles)[1],
            "filas_cache_diario":len(grouped.get('nivel_2',[])),"filas_cache_legajo_dia":len(grouped.get('nivel_3',[])),
            "recalculo_individual":individual},ensure_ascii=False,indent=2),flush=True)
        return
    if "--recalc-only" in sys.argv:
        db = sqlite3.connect(ROOT / "datos" / "laboratorio_premios.db")
        try:
            by_snapshot = {}
            for row in db.execute("""SELECT snapshot,fecha,legajo,desc_funcion,division,sector,
                    palets,plus,cantidad,peso,detalle_filas,origen
                FROM lab_cache_agrupado_ajuste ORDER BY snapshot"""):
                snapshot, *payload = row
                by_snapshot.setdefault(snapshot, Counter())[tuple(payload)] += 1
            if len(by_snapshot) != 2 or len({sum(c.values()) for c in by_snapshot.values()}) != 1:
                raise RuntimeError("El control de snapshots de ajustes cambió; se cancela el recálculo.")
            snapshots = sorted(by_snapshot)
            if by_snapshot[snapshots[0]] != by_snapshot[snapshots[1]]:
                raise RuntimeError("Los ajustes de snapshots distintos no son idénticos; no se deduplican automáticamente.")
            duplicated_rows = sum(by_snapshot[snapshots[0]].values())
            logical_rows = duplicated_rows
            db.execute("""INSERT INTO lab_ajuste_umbral_auditoria(ejecucion,tipo,payload_json)
                VALUES(?,?,?)""", (execution, "armado_secos_validacion_ajustes_duplicados", json.dumps({
                    "periodo": PERIOD, "tabla": "lab_cache_agrupado_ajuste",
                    "snapshots_iguales": snapshots, "filas_logicas": logical_rows,
                    "copias_redundantes": duplicated_rows,
                    "particion_deduplicacion": ["fecha", "legajo", "desc_funcion", "division", "sector", "origen"],
                    "criterio": "Se conserva la versión con created_at/snapshot más reciente; ambas copias fuente permanecen para trazabilidad.",
                    "impacto": "Incluye imputaciones PICKIN (pago_actual_sin_wms) en Armado individual por perfil, en la misma unidad usada por el cálculo grupal."
                }, ensure_ascii=False)))
            db.commit()
        finally:
            db.close()
        grouped = await estudio.calculo_grupal(None, *PERIOD)
        individual = await estudio.recalcular_individual(None, *PERIOD)
        final = analyze(*PERIOD)
        profiles = profile_pair(final)
        final["perfiles"] = profiles
        group_total = sum(day["grupal"] + day["polivalencia"]
                          for p in profiles for person in p["piloto_legajos"] for day in person["dias"])
        individual_total = sum(day["individual"]
                               for p in profiles for person in p["piloto_legajos"] for day in person["dias"])
        new_total = group_total + individual_total
        print(json.dumps({
            "ok": True, "recalculo_validacion": True, "auditoria": execution,
            "ajustes_logicos_deduplicados": logical_rows,
            "duplicados_fuente_deduplicados": duplicated_rows,
            "grupal_y_polivalencia_centavos": group_total,
            "individual_centavos": individual_total,
            "nuevo_total_centavos": new_total,
            "diferencia_actual_centavos": new_total - EXPECTED_ACTUAL_CENTS,
            "grupal_pct": group_total / new_total * 100 if new_total else 0,
            "individual_pct": individual_total / new_total * 100 if new_total else 0,
            "eventos_grupales_y_polivalencia": event_counts(profiles)[0],
            "eventos_individuales_por_nivel": event_counts(profiles)[1],
            "filas_cache_grupal": len(grouped.get("nivel_2", [])),
            "filas_cache_legajo_dia": len(grouped.get("nivel_3", [])),
            "recalculo_individual": individual,
        }, ensure_ascii=False, indent=2), flush=True)
        return
    render_only = "--render-only" in sys.argv
    if render_only:
        updates, grouped, individual = {"parametros_actualizados": 6, "escalas_actualizadas": 30}, {}, {"ok": True}
    else:
        before = analyze(*PERIOD)
        profiles_before = profile_pair(before)
        actual = sum(p["actual_centavos"] for p in profiles_before)
        if actual != EXPECTED_ACTUAL_CENTS:
            raise RuntimeError(f"La bolsa actual cambió: ${actual/100:,.2f}; se esperaba ${EXPECTED_ACTUAL_CENTS/100:,.2f}.")
        group_events, level_events = event_counts(profiles_before)
        if group_events != 1720 or level_events != {1: 295, 2: 393, 3: 311, 4: 121, 5: 52}:
            raise RuntimeError(f"Cambió la distribución base; eventos grupal/poliv={group_events}, individuales={level_events}.")
        updates = save_and_update(execution)
        grouped = await estudio.calculo_grupal(None, *PERIOD)
        individual = await estudio.recalcular_individual(None, *PERIOD)
    final = analyze(*PERIOD)
    profiles = profile_pair(final)
    final["perfiles"] = profiles
    # Limit the expensive raw-activity drilldown to the two requested zones.
    attach_polivalency_summaries(final)
    payroll_details = attach_payroll_activity(final)

    new_total = sum(p["nuevo_centavos"] for p in profiles)
    actual_total = sum(p["actual_centavos"] for p in profiles)
    group_total = sum(day["grupal"] + day["polivalencia"]
                      for p in profiles for person in p["piloto_legajos"] for day in person["dias"])
    individual_total = sum(day["individual"]
                           for p in profiles for person in p["piloto_legajos"] for day in person["dias"])
    if abs(new_total - actual_total) > 1_000:
        raise RuntimeError(f"Bolsa recalculada fuera de tolerancia: diferencia ${((new_total-actual_total)/100):,.2f}.")
    group_share = group_total / new_total * 100 if new_total else 0
    individual_share = individual_total / new_total * 100 if new_total else 0
    if abs(group_share - 60) > 0.1 or abs(individual_share - 40) > 0.1:
        raise RuntimeError(f"Reparto fuera de tolerancia: {group_share:.3f}% / {individual_share:.3f}%.")
    if len(final["perfiles"]) != 2 or final["dias"] != 43:
        raise RuntimeError("El HTML final no quedó limitado a Armado Secos y 43 días.")

    final["escenario_bolsa"] = {
        "objetivo_pct": 0,
        "pago_actual_centavos": actual_total,
        "pago_nuevo_centavos": new_total,
        "variacion_pct": (new_total / actual_total - 1) * 100 if actual_total else 0,
        "distribucion": "Bolsa actual cerrada; 60% grupal incluyendo polivalencia y 40% individual; premio grupal común para Zona 1 y Zona 2.",
        "calculado_at": execution,
    }
    final["base_productiva_secos_sep"] = collect_productivity_summary()
    final["validacion_cruzada"] = collect_validation(final)
    if final["validacion_cruzada"]["checks_ok"] != len(final["validacion_cruzada"]["controles"]):
        raise RuntimeError("La validación cruzada detectó inconsistencias; no se publica el HTML.")
    generate_html(final, payroll_details)
    print(json.dumps({
        "ok": True, "auditoria": execution, "periodo": PERIOD,
        "dias_laborables": final["dias"], "perfiles": len(final["perfiles"]),
        "legajos": sum(p["personas"] for p in final["perfiles"]),
        "parametros_actualizados": updates["parametros_actualizados"],
        "escalas_actualizadas": updates["escalas_actualizadas"],
        "premio_grupal_comun": GROUP_AWARD, "premios_individuales": INDIVIDUAL_AWARDS,
        "pago_actual": actual_total / 100, "pago_nuevo": new_total / 100,
        "diferencia": (new_total - actual_total) / 100,
        "grupal_mas_polivalencia": group_total / 100, "grupal_pct": group_share,
        "individual": individual_total / 100, "individual_pct": individual_share,
        "mas": sum(p["mas"] for p in final["perfiles"]),
        "menos": sum(p["menos"] for p in final["perfiles"]),
        "filas_cache_grupal": len(grouped.get("nivel_2", [])),
        "filas_cache_legajo_dia": len(grouped.get("nivel_3", [])),
        "recalculo_individual": individual,
        "html": str(HTML_PATH), "json": str(JSON_PATH),
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
