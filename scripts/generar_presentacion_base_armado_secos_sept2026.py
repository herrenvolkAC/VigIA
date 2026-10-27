"""Build an auditable operational baseline presentation for September 2026 Armado Secos."""
from __future__ import annotations

import csv
import base64
import datetime as dt
import html
import json
import math
import re
import statistics
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generar_informe_gerencial_umbrales as impact_renderer
import gerencial_umbrales_compacto as compact_renderer
import gerencial_umbrales_piloto as pilot_renderer

DB = ROOT / "datos" / "laboratorio_premios.db"
OUT = ROOT / "outputs"
HTML_OUT = OUT / "presentacion_base_productividad_armado_secos_agosto_septiembre_2026.html"
JSON_OUT = OUT / "presentacion_base_productividad_armado_secos_agosto_septiembre_2026.json"
CSV_OUT = OUT / "detalle_diario_armado_secos_agosto_septiembre_2026.csv"
PREVIOUS_IMPACT_HTML = OUT / "informe_gerencial_secos_armado_bolsa_actual_20261023.html"
PREVIOUS_IMPACT_JSON = OUT / "informe_gerencial_secos_armado_bolsa_actual_20261023.json"
SECTORS = ("CD-SECOS - ZONA 1", "CD-SECOS - ZONA 2")
FUNCION = "ARMADOR"
OPERACION = "ARMADO"
DIVISION_WMS = "1"
STANDARD_HOURS = 6.5
WEEKDAYS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def fmt_int(value: float | int) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


def fmt_dec(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def september_impact_report() -> tuple[dict, str, dict[str, list[dict]]]:
    """Render the economic slide from the unified August–September period."""
    report = impact_renderer.analyze("2026-08-01", "2026-09-30")
    profiles = [p for p in report["perfiles"]
                if p.get("sector") in SECTORS
                and p.get("funcion") == FUNCION
                and p.get("operacion") == OPERACION]
    if len(profiles) != 2:
        raise SystemExit(f"Se esperaban dos perfiles de Armado Secos para agosto-septiembre, se encontraron {len(profiles)}")
    report["perfiles"] = profiles
    impact_renderer.attach_polivalency_summaries(report)
    payroll = impact_renderer.attach_payroll_activity(report)
    saved_pages = compact_renderer.PAGES
    compact_renderer.PAGES = [("secos-armado", "Secos · Armado", "Zona 1 y Zona 2", [1, 5])]
    try:
        rendered = impact_renderer.render(report, compact=True, payroll_details=payroll)
    finally:
        compact_renderer.PAGES = saved_pages
    return report, rendered, payroll


def safe_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace(" ", "T"))


def interval_seconds(start: str | None, end: str | None) -> tuple[float, bool]:
    if not start or not end:
        return 0.0, False
    a, b = safe_iso(start), safe_iso(end)
    seconds = (b - a).total_seconds()
    if seconds < 0:
        adjusted = seconds + 86400
        if 0 <= adjusted <= 43200:
            seconds = adjusted
        else:
            return 0.0, False
    if seconds > 43200:
        return 0.0, False
    return seconds, True


def union_seconds(intervals: list[tuple[dt.datetime, dt.datetime]]) -> tuple[float, float]:
    if not intervals:
        return 0.0, 0.0
    intervals.sort()
    total = sum((end - start).total_seconds() for start, end in intervals)
    merged: list[tuple[dt.datetime, dt.datetime]] = []
    start, end = intervals[0]
    for next_start, next_end in intervals[1:]:
        if next_start <= end:
            if next_end > end:
                end = next_end
        else:
            merged.append((start, end))
            start, end = next_start, next_end
    merged.append((start, end))
    unique = sum((b - a).total_seconds() for a, b in merged)
    return total, unique


def main() -> None:
    OUT.mkdir(exist_ok=True)
    impact_data, previous_impact_html, payroll_details = september_impact_report()
    # The renderer's generic closing slide refers to a reception profile that
    # is intentionally absent from this one-function presentation.
    previous_impact_html = re.sub(
        r'<button[^>]*data-open-profile="perfil-4"[^>]*>.*?</button>',
        '<span class="detail-button" aria-disabled="true">Fuera del alcance de esta hoja</span>',
        previous_impact_html, count=1, flags=re.S)
    impact_profiles = impact_data["perfiles"]
    zone_days = sum(int(p["dias"]) for p in impact_profiles)
    group_days = sum(int(p["cumple"]) for p in impact_profiles)
    group_rate = 100 * group_days / zone_days if zone_days else 0
    pooled_daily_values = [float(value) for p in impact_profiles for value in p.get("valores", [])]
    pooled_median = round(statistics.median(pooled_daily_values)) if pooled_daily_values else 0
    event_days = int(impact_data.get("dias") or max(int(p["dias"]) for p in impact_profiles))
    event_roster = sum(int(p["personas"]) for p in impact_profiles)
    total_events = event_days * event_roster
    activity_rows = [day for p in impact_profiles for person in p.get("piloto_legajos", [])
                     for day in person.get("dias", [])]
    validated_events = len(activity_rows)
    if total_events != validated_events:
        raise SystemExit(f"El universo de eventos no concilia: {event_days} días × {event_roster} legajos = {total_events}, validación = {validated_events}")
    section_start = previous_impact_html.index('<section class="sheet compact-sheet integrated-sheet" id="secos-armado">')
    previous_impact_html = previous_impact_html.replace('Septiembre 2026', 'Agosto–septiembre 2026')
    previous_impact_html = previous_impact_html.replace('22 días hábiles', '43 días hábiles')
    group_start = previous_impact_html.index('<div class="integrated-group-panel">', section_start)
    participation_start = previous_impact_html.index('<div class="integrated-participation">', group_start)
    unified_group_panel = f'''<div class="integrated-group-panel"><h3>Acceso al grupal · Secos · Armado</h3><div class="integrated-access"><b>CD-SECOS · ARMADO</b><div class="group-zone-metrics unified-group-metrics"><span>Umbral común<strong>1.100 bultos por operario</strong></span><span>Cumplimiento consolidado<strong>{group_days}/{zone_days} sector-días · {fmt_dec(group_rate)}%</strong></span></div><p class="group-modal-note">Denominador: 43 días hábiles × 2 zonas = {zone_days} sector-días. El acceso se resume junto; el grupal se liquida por zona.</p><div class="integrated-actions split-controls"><button class="detail-button" data-open-profile="nomina-resumen-secos-armado" aria-haspopup="dialog">Nómina y actividad · ambas zonas</button><button class="detail-button" data-open-profile="curva-consolidada-secos-armado" aria-haspopup="dialog">Curvas y días</button><button class="detail-button" data-open-profile="escala-consolidada-secos-armado" aria-haspopup="dialog">Escalas y montos</button></div></div></div>'''
    previous_impact_html = previous_impact_html[:group_start] + unified_group_panel + previous_impact_html[participation_start:]
    participation_start = previous_impact_html.index('<div class="integrated-participation">', group_start)
    # Show the evaluated universe as a bar, and normalize the peer bars to the same scale.
    chart_start = previous_impact_html.index('<div class="pilot-bars">', participation_start)
    chart_end = previous_impact_html.index('<p', chart_start)
    chart_markup = previous_impact_html[chart_start:chart_end]
    bar_pattern = re.compile(r'<div class="pilot-bar"(?P<attrs>[^>]*)>(?P<body>.*?)</div>', re.S)
    # Keep room above each bar for the value label without colliding with the
    # participation heading in the fixed-height presentation frame.
    max_bar_height = 84

    def rescale_bar(match: re.Match[str]) -> str:
        body = match.group("body")
        value_match = re.search(r"<b>([\d.]+)</b>", body)
        if not value_match:
            return match.group(0)
        value = int(value_match.group(1).replace(".", ""))
        height = max(2, round(max_bar_height * value / total_events, 1))
        body = re.sub(r"height:[\d.]+px", f"height:{height}px", body, count=1)
        return f'<div class="pilot-bar"{match.group("attrs")}>{body}</div>'

    chart_markup, chart_bars = bar_pattern.subn(rescale_bar, chart_markup)
    if chart_bars < 6:
        raise SystemExit(f"No se pudieron normalizar las barras de participación: {chart_bars}")
    total_bar = f'<div class="pilot-bar total-events" title="Eventos totales: {event_days} días × {event_roster} legajos"><b>{fmt_int(total_events)}</b><i style="height:{max_bar_height}px;background:#15384c"></i><span>Total eventos</span></div>'
    chart_markup = chart_markup.replace('<div class="pilot-bars">', '<div class="pilot-bars">' + total_bar, 1)
    previous_impact_html = previous_impact_html[:chart_start] + chart_markup + previous_impact_html[chart_end:]
    evaluated_rows = [row for row in activity_rows if row.get("evaluado")]
    level_counts = Counter(int(row.get("nivel") or 0) for row in evaluated_rows)
    exact_levels = [level_counts.get(level, 0) for level in range(6)]
    cumulative_levels = [sum(level_counts.get(level, 0) for level in range(n, 6)) for n in range(1, 6)]
    group_events = sum(int(row.get("grupal") or 0) > 0 for row in evaluated_rows)
    poly_events = sum(int(row.get("polivalencia") or 0) > 0 for row in activity_rows)
    no_prize_events = sum(not any(int(row.get(k) or 0) > 0 for k in ("grupal", "individual", "polivalencia"))
                           for row in evaluated_rows)
    if sum(exact_levels) != len(evaluated_rows) or len(activity_rows) != total_events:
        raise SystemExit("La distribución exclusiva de niveles no concilia con el universo de eventos")
    validation_dialog = f'''<dialog class="profile-dialog participation-validation-dialog" id="detalle-validacion-participacion"><div class="dialog-heading"><div><span>Control de consistencia · Agosto–septiembre 2026</span><h2>Cómo leer y validar la participación</h2></div><button type="button" class="control-button" data-close-profile>Cerrar ×</button></div><div class="dialog-body"><p>El <b>total de eventos</b> es el denominador: {event_roster} legajos × {event_days} días hábiles = <b>{fmt_int(total_events)} legajo-días</b>. No se obtiene sumando las barras, porque varias barras cuentan el mismo evento desde perspectivas distintas.</p><div class="participation-check"><b>Conciliación aditiva</b><span>{fmt_int(total_events)} eventos = {fmt_int(len(evaluated_rows))} evaluables + {fmt_int(total_events-len(evaluated_rows))} sin evaluación.</span><span>{fmt_int(len(evaluated_rows))} evaluables = {fmt_int(exact_levels[0])} sin nivel individual + {" + ".join(fmt_int(v) for v in exact_levels[1:])} niveles exactos (N1 a N5).</span><strong>Las dos sumas cierran.</strong></div><div class="participation-overlap"><h3>Barras superpuestas</h3><ul><li><b>Grupal:</b> {fmt_int(group_events)} jornadas; puede coincidir con un nivel individual y/o polivalencia.</li><li><b>Polivalencia:</b> {fmt_int(poly_events)} jornadas; también puede coincidir con otras barras.</li><li><b>0 · Sin premio:</b> {fmt_int(no_prize_events)} jornadas evaluables sin pago grupal, individual ni polivalencia; es parte de “sin nivel individual”.</li><li><b>N1–N5:</b> acumulados, no exclusivos. N1={fmt_int(cumulative_levels[0])}; N2={fmt_int(cumulative_levels[1])}; N3={fmt_int(cumulative_levels[2])}; N4={fmt_int(cumulative_levels[3])}; N5={fmt_int(cumulative_levels[4])}.</li></ul><p>Para comprobar los acumulados, sumar los niveles exactos desde ese nivel hasta N5. Por ejemplo, N2 = N2 exacto + N3 exacto + N4 exacto + N5 exacto.</p></div></div></dialog>'''
    note_markup = '<p class="pilot-note participation-note">El total es el universo de legajo-días; grupal, polivalencia y niveles individuales pueden superponerse. N1–N5 son acumulados. <button type="button" class="detail-button" data-open-profile="validacion-participacion">Validar consistencia</button></p>'
    participation_start = previous_impact_html.index('<div class="integrated-participation">', group_start)
    chart_start = previous_impact_html.index('<div class="pilot-bars">', participation_start)
    chart_end = previous_impact_html.index('</div><p', chart_start) + len('</div>')
    paragraph_start = previous_impact_html.index('<p', chart_end)
    paragraph_end = previous_impact_html.index('</p>', paragraph_start) + len('</p>')
    previous_impact_html = previous_impact_html[:paragraph_start] + note_markup + previous_impact_html[paragraph_end:]

    # Replace the wide two-column legajo lists with two compact launch buttons.
    ranking_start = previous_impact_html.index('<div class="integrated-rankings">', section_start)
    ranking_end = previous_impact_html.index('</section><p class="pilot-note">', ranking_start)
    gainers, losers = pilot_renderer.selected(impact_data)
    impact_launchers = f'''<div class="impact-modal-launchers"><button type="button" data-open-profile="impacto-mas-secos-armado"><span>Mayores aumentos</span><b>{len(gainers)} legajos</b><small>Ver comparación y explicación</small></button><button type="button" data-open-profile="impacto-menos-secos-armado"><span>Mayores disminuciones</span><b>{len(losers)} legajos</b><small>Ver comparación y explicación</small></button></div>'''
    previous_impact_html = previous_impact_html[:ranking_start] + impact_launchers + previous_impact_html[ranking_end:]

    def impact_dialog(dialog_id: str, title: str, cases: list[dict]) -> str:
        cards = []
        for case in cases:
            delta = case["diferencia"] / 100
            sign = "+" if delta >= 0 else "−"
            explanation = pilot_renderer.explanation(case, impact_renderer.number)
            cards.append(f'''<button type="button" class="impact-person-row" data-open-profile="caso-{html.escape(case['perfil'])}-{html.escape(str(case['legajo']))}"><b>Legajo {html.escape(str(case['legajo']))}</b><strong>{sign}$ {fmt_int(abs(delta))}</strong><span>{html.escape(explanation)}</span><small>Ver desglose diario ↗</small></button>''')
        return f'''<dialog class="profile-dialog impact-list-dialog" id="detalle-{dialog_id}"><div class="dialog-heading"><div><span>Impacto individual · Agosto–septiembre 2026</span><h2>{title}</h2></div><button type="button" class="control-button" data-close-profile>Cerrar ×</button></div><div class="dialog-body impact-list-body">{''.join(cards) or '<p>No hay legajos en esta condición.</p>'}</div></dialog>'''

    # Pool both zones by day, weighting the production ratio by effective roster.
    # This yields one transparent sector-wide curve rather than two side-by-side plots.
    by_zone_date = [{str(row["fecha"]): row for row in p.get("diario", [])} for p in impact_profiles]
    combined_daily = []
    for date in sorted(set().union(*(set(rows) for rows in by_zone_date))):
        rows = [zone.get(date, {}) for zone in by_zone_date]
        divisor = sum(float(row.get("base") or 0) for row in rows)
        production = sum(float(row.get("produccion") or 0) for row in rows)
        combined_daily.append({"fecha": date, "base": divisor, "produccion": production,
                              "uc": production / divisor if divisor > 0 else None,
                              "cumple": bool(divisor > 0 and production > float(impact_profiles[0]["objetivo"]) * divisor)})
    combined_values = sorted((row["uc"] for row in combined_daily if row["uc"] is not None), reverse=True)
    combined_profile = dict(impact_profiles[0])
    combined_profile.update({"id": "curva-combinada-secos-armado", "sector": "CD-SECOS · ZONA 1 + ZONA 2",
                             "dias": len(combined_daily), "valores": combined_values,
                             "diario": combined_daily, "cumple": sum(row["cumple"] for row in combined_daily)})
    combined_refs = []
    for pct in (25, 50, 75):
        target_days = math.ceil(len(combined_daily) * pct / 100)
        suggested = math.ceil(combined_values[target_days - 1]) - 1 if target_days <= len(combined_values) else None
        if suggested is not None and suggested <= 0:
            suggested = None
        achieved = sum(1 for row in combined_daily if row["base"] > 0 and suggested is not None
                       and row["produccion"] > suggested * row["base"])
        combined_refs.append({"pct": pct, "dias_objetivo": target_days, "umbral": suggested,
                              "dias_logrados": achieved})
    combined_profile["referencias"] = combined_refs
    pooled_curve = impact_renderer.chart(combined_profile)
    curve_dialog = f'''<dialog class="profile-dialog combined-detail-dialog" id="detalle-curva-consolidada-secos-armado"><div class="dialog-heading"><div><span>Secos · Armado · Agosto–septiembre 2026</span><h2>Curva de cumplimiento y días · ambas zonas</h2></div><button type="button" class="control-button" data-close-profile>Cerrar ×</button></div><div class="dialog-body combined-curves"><p class="curve-caption">Cada punto muestra el promedio diario por persona, sumando las dos zonas. La línea punteada marca el umbral actual; los círculos y tarjetas muestran el umbral para alcanzar el grupal en 25%, 50% y 75% de los días. El pago se evalúa por zona.</p>{pooled_curve}</div></dialog>'''

    # Recover the current scale directly from the same TablaActual.xlsx table
    # retained in the previous managerial report; keep the current and proposed
    # schedules side by side as in that report.
    old_scale_dialog = re.search(
        r'<dialog[^>]*id="detalle-escala-perfil-1"[^>]*>(.*?)</dialog>',
        previous_impact_html, flags=re.S)
    old_current_section = re.search(
        r'<section class="scale-comparison-panel current">.*?</section>',
        old_scale_dialog.group(1) if old_scale_dialog else "", flags=re.S)
    if not old_current_section:
        reference_path = OUT / "informe_gerencial_bolsa_mas10_20261021.html"
        reference_html = reference_path.read_text(encoding="utf-8") if reference_path.exists() else ""
        old_scale_dialog = re.search(
            r'<dialog[^>]*id="detalle-escala-perfil-1"[^>]*>(.*?)</dialog>',
            reference_html, flags=re.S)
        old_current_section = re.search(
            r'<section class="scale-comparison-panel current">.*?</section>',
            old_scale_dialog.group(1) if old_scale_dialog else "", flags=re.S)
    if not old_current_section:
        raise SystemExit("No se encontró la tabla actual de Armado en el informe de referencia")
    current_section_html = old_current_section.group(0).replace(
        "Escala actual · TablaActual.xlsx", "Escala actual")
    current_section_html = re.sub(
        r'(<h3>Escala actual</h3>\s*)<div class="scale-source"><h4>(.*?)</h4>',
        r'\1<h4 class="scale-source-label">\2</h4><div class="scale-source">',
        current_section_html, count=1, flags=re.S)
    proposed_rows = [f'<tr><td>Grupal</td><td>{fmt_int(impact_profiles[0]["objetivo"])} bultos</td><td>$ {fmt_dec(impact_profiles[0]["premio_grupal"], 2)}</td></tr>']
    proposed_rows += [f'<tr><td>N{scale["nivel"]}</td><td>{fmt_int(scale["desde_uc"])} bultos</td><td>$ {fmt_dec(scale["premio"], 2)}</td></tr>' for scale in impact_profiles[0]["escala_individual"]]
    current_label_match = re.search(r'<h4 class="scale-source-label">.*?</h4>', current_section_html, flags=re.S)
    proposed_label_html = '<h4 class="scale-source-label">Aplicación: Zona 1 + Zona 2</h4>'
    proposed_rows_html = ''.join(proposed_rows)
    scale_dialog = f'''<dialog class="profile-dialog combined-detail-dialog" id="detalle-escala-consolidada-secos-armado"><div class="dialog-heading"><div><span>Secos · Armado · Agosto–septiembre 2026</span><h2>Escala actual y propuesta</h2></div><button type="button" class="control-button" data-close-profile>Cerrar ×</button></div><div class="dialog-body"><div class="scale-comparison">{current_section_html}<section class="scale-comparison-panel proposed"><h3>Escala propuesta</h3>{proposed_label_html}<table><thead><tr><th>Nivel</th><th>Desde</th><th>Premio diario</th></tr></thead><tbody>{proposed_rows_html}</tbody></table></section></div><p class="dialog-criteria">La tabla actual reproduce los rangos y premios de Picking · Secos + NOA. La propuesta muestra los umbrales y premios configurados para Armado Secos; las dos zonas comparten esta escala. Son esquemas distintos y deben leerse según sus criterios propios.</p></div></dialog>'''

    custom_dialogs = (validation_dialog + impact_dialog("impacto-mas-secos-armado", "Mayores aumentos", gainers)
                      + impact_dialog("impacto-menos-secos-armado", "Mayores disminuciones", losers)
                      + curve_dialog + scale_dialog)
    dialog_anchor = '<script id="report-data"'
    if dialog_anchor not in previous_impact_html:
        raise SystemExit("No se encontró el punto de inserción de diálogos en el informe agosto-septiembre")
    previous_impact_html = previous_impact_html.replace(dialog_anchor, custom_dialogs + dialog_anchor, 1)
    # Move modal controls onto the label line in the two cards to conserve vertical space.
    previous_impact_html = re.sub(
        r'<span>Legajos más / menos\s*<b>(.*?)</b>(<button type="button" class="poly-summary-button roster-summary-button".*?</button>)</span>',
        lambda m: f'<span><span class="metric-title">Legajos más / menos{m.group(2).replace("Ver nómina del legajero", "Nómina")}</span><b>{m.group(1)}</b></span>',
        previous_impact_html,
        count=1,
        flags=re.S,
    )
    previous_impact_html = re.sub(
        r'<span>Polivalencia\s*<b>(.*?)</b>(<small>.*?)</small>(<button type="button" class="poly-summary-button".*?</button>)</span>',
        lambda m: f'<span><span class="metric-title">Polivalencia{m.group(3)}</span><b>{m.group(1)}</b><small>{m.group(2)[7:]}</small></span>',
        previous_impact_html,
        count=1,
        flags=re.S,
    )
    legacy_styles = '''<style>
.compact-heading h2{font-size:36px!important;line-height:1.08!important}
.compact-heading .eyebrow{font-size:12px!important}
.compact-heading{border-left:6px solid #138a87!important;padding-left:16px!important}
.integrated-sheet .band-title{border-left:5px solid #138a87!important;padding-left:10px!important}
.integrated-band .band-title{font-size:16px!important}
.integrated-totals>span{font-size:14px!important;padding:14px 16px!important;min-height:92px}
.integrated-totals b{font-size:27px!important;margin-top:7px!important}
.integrated-totals .metric-title{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:14px!important}
.integrated-totals .metric-title button{display:inline-flex!important;align-items:center;margin:0!important;padding:4px 8px!important;white-space:nowrap;font-size:11px!important}
.integrated-group-panel>h3,.integrated-participation>h3{font-size:18px!important}
.integrated-access>b{font-size:16px!important}
.integrated-access span{font-size:13px!important}
.integrated-access strong{font-size:20px!important}
.integrated-access button{font-size:10px!important;padding:4px 6px!important}
.integrated-actions.split-controls{display:flex;flex-wrap:wrap;gap:5px!important}
.integrated-actions.split-controls .detail-button{margin:3px 0 0!important}
.group-zone-metrics{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 14px!important;margin:10px 0!important}
.group-zone-metrics span{padding:7px 9px;background:#fff;border:1px solid #e0e9ee;border-radius:6px}
.group-zone-metrics strong{font-size:16px!important;margin-top:3px}
.group-modal-note{font-size:11px;color:#587286;margin:8px 0}
.integrated-participation h3{margin-bottom:0!important}
.integrated-participation .pilot-bars{height:184px!important;margin:19px 0 0!important;padding-top:7px}
.integrated-participation .pilot-bar.total-events i{background:#15384c!important}
.integrated-participation .pilot-bar b{font-size:13px!important}
.integrated-participation .pilot-bar span{font-size:11px!important;line-height:1.15}
.integrated-participation .participation-note{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:11px!important;line-height:1.3!important;margin:6px 0!important}
.participation-note .detail-button{white-space:nowrap;margin:0!important}
.impact-modal-launchers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:10px 0}
.impact-modal-launchers>button{display:flex;flex-direction:column;align-items:flex-start;gap:4px;padding:16px 18px;border:1px solid #d8e4e8;border-left:5px solid #69a88e;border-radius:8px;background:#f5faf8;color:#15384c;text-align:left;cursor:pointer}
.impact-modal-launchers>button:last-child{border-left-color:#c98b79;background:#fff8f5}
.impact-modal-launchers span{font-weight:800;font-size:15px}
.impact-modal-launchers b{font-size:20px}
.impact-modal-launchers small{font-size:11px;color:#587286}
.impact-list-body{display:grid;gap:9px}
.impact-person-row{display:grid;grid-template-columns:130px 150px 1fr;gap:5px 12px;align-items:center;padding:11px 13px;border:1px solid #dbe6ec;border-radius:7px;background:#f7fafb;color:#15384c;text-align:left;cursor:pointer}
.impact-person-row strong{font-variant-numeric:tabular-nums}
.impact-person-row span{font-size:12px;line-height:1.35;color:#456276}
.impact-person-row small{grid-column:3;font-size:10px;color:#16817c}
.combined-curves{display:block;min-width:0;overflow-x:hidden}
.combined-curves .figure{padding:2px 0 0;border:0;background:transparent}.combined-curves .inside-refs{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:0 0 12px!important}.combined-curves .ref{border-top:4px solid #138a87;border-radius:7px;background:#eff7f8;padding:12px 16px}.combined-curves .ref:nth-child(2){border-color:#d4a542;background:#fbf7ec}.combined-curves .ref:nth-child(3){border-color:#4389a8;background:#edf5f8}.combined-curves .ref span{font-size:11px;letter-spacing:.04em;font-weight:800}.combined-curves .ref strong{font-size:22px;line-height:1.25;margin:5px 0}.combined-curves .ref em{font-size:12px;line-height:1.3}
.combined-curves .inside-refs{gap:8px;margin:0 0 10px}
.combined-curves .ref{padding:8px 10px}
.combined-curves .ref strong{font-size:20px;line-height:1.25}
.combined-curves .ref em{font-size:11px}
.combined-curves .threshold-chart{display:block;width:100%;height:auto;max-height:none;overflow:visible}
.curve-axis-label{fill:#587286;font:13px sans-serif}.curve-axis-title{fill:#334f61;font:14px sans-serif}.curve-legend{fill:#334f61;font:14px sans-serif;font-weight:700}.curve-threshold{fill:#a43d48;font:13px sans-serif;font-weight:700}
.curve-caption{margin:8px 0 0;color:#587286;font-size:12px;line-height:1.4}
.combined-scale-wrap{overflow:auto}
.scale-comparison{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;align-items:start}
.scale-comparison-panel{min-width:0}
.scale-comparison-panel h3{min-height:26px;margin:0 0 5px;font-size:19px;line-height:1.25}
.scale-comparison-panel h4.scale-source-label{min-height:24px;margin:0 0 7px;font-size:15px;line-height:1.3;color:#587286}
.scale-comparison-panel table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:13px}
.scale-comparison-panel th,.scale-comparison-panel td{padding:8px 9px;border-bottom:1px solid #dbe6ec;text-align:left;vertical-align:top}
.scale-comparison-panel thead th{background:#edf5f8}
.participation-validation-dialog .dialog-body{display:grid;gap:14px}
.participation-check,.participation-overlap{padding:14px 16px;border:1px solid #dbe6ec;border-radius:8px;background:#f6fafb}
.participation-check{display:grid;gap:8px;border-left:4px solid #168b83}
.participation-check strong{color:#16816c}
.participation-overlap h3{margin:0 0 8px}
.participation-overlap ul{margin:0;padding-left:20px;display:grid;gap:7px}
.participation-overlap p{font-size:12px;line-height:1.4;color:#587286}
@media(max-width:800px){.impact-person-row{grid-template-columns:1fr auto}.impact-person-row span,.impact-person-row small{grid-column:1/-1}.impact-modal-launchers,.scale-comparison{grid-template-columns:1fr}}
</style>'''
    if "</head>" not in previous_impact_html:
        raise SystemExit("No se encontró el cierre del encabezado HTML de la lámina de premios")
    previous_impact_html = previous_impact_html.replace("</head>", legacy_styles + "</head>", 1)
    previous_impact_b64 = base64.b64encode(previous_impact_html.encode("utf-8")).decode("ascii")
    db = sqlite3.connect(DB, timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    db.row_factory = sqlite3.Row
    period = db.execute(
        """SELECT nivel_3_json, calculado_at FROM lab_calculo_grupal_cache
           WHERE fecha_desde='20260801' AND fecha_hasta='20260930'
           ORDER BY calculado_at DESC LIMIT 1"""
    ).fetchone()
    if not period:
        raise SystemExit("No existe la cache consolidada agosto-septiembre 2026")
    cached_detail = json.loads(period["nivel_3_json"])
    roster_rows = [
        row for row in cached_detail
        if row["fecha"][:6] in {"202608", "202609"}
        and row["sector"] in SECTORS
        and row["funcion_legajero"] == FUNCION
        and row["operacion"] == OPERACION
    ]
    roster_ids = sorted({str(row["legajo"]) for row in roster_rows})
    if not roster_ids:
        raise SystemExit("No se encontró la nómina Armador de Secos en la cache")
    zones_by_person: dict[str, set[str]] = defaultdict(set)
    names_by_person: dict[str, str] = {}
    for row in roster_rows:
        legajo = str(row["legajo"])
        zones_by_person[legajo].add(row["sector"])
        names_by_person[legajo] = row.get("nombre") or ""
    roster_conflicts = {key: sorted(value) for key, value in zones_by_person.items() if len(value) != 1}
    if roster_conflicts:
        raise SystemExit(f"La nómina cambia de sector durante el período: {roster_conflicts}")
    zone_by_person = {legajo: next(iter(zones_by_person[legajo])) for legajo in roster_ids}
    placeholders = ",".join("?" for _ in roster_ids)

    workdays = [
        dt.date(2026, month, day)
        for month in (8, 9)
        for day in range(1, 32 if month == 8 else 31)
        if dt.date(2026, month, day).weekday() < 5
    ]
    day_keys = [day.strftime("%Y%m%d") for day in workdays]
    daily_cache_rows: dict[str, list[dict]] = defaultdict(list)
    for row in roster_rows:
        if row["fecha"] in day_keys:
            daily_cache_rows[row["fecha"]].append(dict(row))

    batch_rows = {
        row["fecha"]: dict(row)
        for row in db.execute(
            "SELECT fecha,run_id,estado,filas,legajos FROM lab_cache_wms_batch "
            "WHERE fecha BETWEEN '20260801' AND '20260930'"
        )
    }
    calendar_keys = [day.strftime("%Y%m%d") for day in workdays]
    # Agosto tiene detalle horario cargado, aunque no conserve un manifiesto de
    # lote en lab_cache_wms_batch. Recuperamos el run_id desde el propio detalle
    # y exigimos un solo run completo por jornada hábil.
    raw_runs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for row in db.execute(
        f"""SELECT fecha,run_id,COUNT(*) AS filas FROM lab_etapa_detalle_raw
            WHERE fecha IN ({','.join('?' for _ in calendar_keys)})
            GROUP BY fecha,run_id""",
        calendar_keys,
    ):
        raw_runs[row["fecha"]].append((row["run_id"], int(row["filas"] or 0)))
    for day in calendar_keys:
        manifest = batch_rows.get(day, {})
        runs = raw_runs.get(day, [])
        if manifest.get("estado") == "OK" and manifest.get("run_id"):
            continue
        if len(runs) == 1 and runs[0][1] > 0:
            batch_rows[day] = {"fecha": day, "run_id": runs[0][0], "estado": "RAW_OK",
                               "filas": runs[0][1], "legajos": None}
    batch_ok = sum(batch_rows.get(day, {}).get("estado") in {"OK", "RAW_OK"} for day in calendar_keys)
    if batch_ok != len(workdays):
        missing = [day for day in calendar_keys if batch_rows.get(day, {}).get("estado") not in {"OK", "RAW_OK"}]
        raise SystemExit(f"No hay detalle horario completo y unívoco para los días hábiles de agosto-septiembre: {batch_ok}/{len(workdays)}; faltan o tienen múltiples lotes {missing}")

    pv_snapshot_row = db.execute(
        """SELECT snapshot FROM lab_fuente_lote
           WHERE fuente='oracle.PV_DIA_LABORAL' AND segmento BETWEEN '20260801' AND '20260930'
           ORDER BY capturado DESC LIMIT 1"""
    ).fetchone()
    if not pv_snapshot_row:
        raise SystemExit("No hay snapshot de PV_DIA_LABORAL para agosto-septiembre de 2026")
    pv_snapshot = pv_snapshot_row["snapshot"]
    pv_attendance: dict[tuple[str, str], dict] = {}
    for source_row in db.execute(
        """SELECT payload FROM lab_fuente_registro
           WHERE snapshot=? AND fuente='oracle.PV_DIA_LABORAL'
             AND segmento BETWEEN '20260801' AND '20260930'""",
        [pv_snapshot],
    ):
        record = json.loads(source_row["payload"])
        key = (str(record.get("FECHA") or ""), str(record.get("LEGAJO") or "").strip())
        if key[0] and key[1] in roster_ids:
            pv_attendance[key] = record

    daily: list[dict] = []
    absence_cases: list[dict] = []
    absence_summary: Counter[str] = Counter()
    present_without_time: list[dict] = []
    activity_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for activity in db.execute(
        f"""SELECT fecha,CAST(legajo AS TEXT) legajo,desc_funcion,division,sector,
                   palets,plus,cantidad
            FROM lab_cache_agrupado WHERE fecha BETWEEN '20260801' AND '20260930'
              AND legajo IN ({placeholders})""",
        roster_ids,
    ):
        key = (str(activity["fecha"]), str(activity["legajo"]).strip())
        if key[0] in day_keys:
            activity_by_key[key].append(dict(activity))
    absence_activity_count = 0
    invalid_stage_count = 0
    missing_time_stage_count = 0
    stage_count = 0
    raw_line_count = 0
    raw_timed_line_count = 0
    total_overlap_seconds = 0.0
    cache_vs_raw_seconds_diff = 0.0
    raw_vs_cached_units_diff = 0.0
    total_operation_seconds = 0.0

    for date in workdays:
        day = date.strftime("%Y%m%d")
        source = batch_rows[day]
        run_id = source["run_id"]
        stage_query = f"""
            SELECT CAST(legajo AS TEXT) AS legajo, id_etapa,
                   MIN(fyhini) AS inicio, MAX(fyhfin) AS fin,
                   COUNT(*) AS lineas,
                   SUM(CASE WHEN fyhini IS NOT NULL AND fyhfin IS NOT NULL THEN 1 ELSE 0 END) AS lineas_con_horario,
                   SUM(COALESCE(cantidad,0)) AS bultos
            FROM lab_etapa_detalle_raw
            WHERE run_id=? AND legajo IN ({placeholders})
              AND UPPER(TRIM(COALESCE(desc_funcion,'')))='PICKIN'
              AND TRIM(COALESCE(division,''))=?
            GROUP BY CAST(legajo AS TEXT), id_etapa
        """
        stages = [dict(row) for row in db.execute(stage_query, [run_id, *roster_ids, DIVISION_WMS])]
        intervals: dict[str, list[tuple[dt.datetime, dt.datetime]]] = defaultdict(list)
        active_people: set[str] = set()
        day_hours_raw = 0.0
        day_bultos_raw = 0.0
        day_invalid = 0
        for stage in stages:
            stage_count += 1
            raw_line_count += stage["lineas"]
            raw_timed_line_count += stage["lineas_con_horario"]
            day_bultos_raw += stage["bultos"] or 0
            if stage["lineas_con_horario"] != stage["lineas"]:
                missing_time_stage_count += 1
            seconds, valid = interval_seconds(stage["inicio"], stage["fin"])
            if not valid:
                invalid_stage_count += 1
                day_invalid += 1
                continue
            day_hours_raw += seconds / 3600
            active_people.add(stage["legajo"])
            intervals[stage["legajo"]].append((safe_iso(stage["inicio"]), safe_iso(stage["fin"])))

        day_union_seconds = 0.0
        day_overlap = 0.0
        for person_intervals in intervals.values():
            summed, unique = union_seconds(person_intervals)
            day_union_seconds += unique
            day_overlap += summed - unique
        total_overlap_seconds += day_overlap
        day_hours = day_union_seconds / 3600
        total_operation_seconds += day_union_seconds

        # Reconcile against the materialized local duration cache, restricted to these 64 people.
        cache_seconds = db.execute(
            f"""SELECT COALESCE(SUM(segundos_validos),0) FROM lab_actividad_duracion_cache
                WHERE fecha=? AND operacion='ARMADO' AND division=? AND legajo IN ({placeholders})""",
            [day, DIVISION_WMS, *roster_ids],
        ).fetchone()[0]
        cache_vs_raw_seconds_diff += float(cache_seconds or 0) - day_hours_raw * 3600

        employees = daily_cache_rows.get(day, [])
        if len(employees) != len(roster_ids):
            raise SystemExit(f"Universo diario inesperado en {day}: {len(employees)} filas para {len(roster_ids)} legajos")
        by_id = {str(row["legajo"]): row for row in employees}
        pv_by_person = {person: pv_attendance.get((day, person)) for person in roster_ids}
        pv_present_people = {person for person, record in pv_by_person.items()
                             if record and str(record.get("SITUACION") or "").strip().upper() == "PRESENTE"}
        pv_absent_people = {person for person, record in pv_by_person.items()
                            if record and str(record.get("SITUACION") or "").strip().upper() != "PRESENTE"}
        pv_missing_people = {person for person, record in pv_by_person.items() if not record}
        if len(pv_present_people | pv_absent_people | pv_missing_people) != len(roster_ids):
            other = sorted(set(roster_ids) - pv_present_people - pv_absent_people - pv_missing_people)
            raise SystemExit(f"SITUACION de PV_DIA_LABORAL requiere revisión en {day}: {other}")
        gross_cached = sum(float(row.get("uc_brutas") or 0) for row in employees)
        gross_present = sum(
            float(row.get("uc_brutas") or 0)
            for row in employees
            if str(row["legajo"]) in pv_present_people
        )
        gross_computable = sum(float(row.get("uc_computables") or 0) for row in employees)
        raw_vs_cached_units_diff += day_bultos_raw - gross_cached
        positive_units_people = {str(row["legajo"]) for row in employees if float(row.get("uc_brutas") or 0) > 0}
        time_people_absent = {person for person in active_people if person in pv_absent_people}
        present_people_without_time = [
            row for row in employees
            if str(row["legajo"]) in pv_present_people and str(row["legajo"]) not in active_people
        ]
        for row in present_people_without_time:
            person = str(row["legajo"])
            attendance = pv_by_person[person] or {}
            present_without_time.append({
                "fecha": day,
                "dia": WEEKDAYS[date.weekday()],
                "legajo": person,
                "nombre": ((row.get("nombre") or "") if "�" not in (row.get("nombre") or "") else "Nombre con carácter ilegible en cache"),
                "sector": row["sector"],
                "situacion_pv": attendance.get("SITUACION", ""),
                "bultos": float(row.get("uc_brutas") or 0),
                "horas_armado": 0.0,
            })
        for person in sorted(pv_absent_people):
            row = by_id[person]
            attendance = pv_by_person[person] or {}
            activities = activity_by_key.get((day, person), [])
            code = str(attendance.get("COD_AUSENTISMO") or "").strip()
            reason = str(attendance.get("DES_AUSENTISMO") or "").strip()
            if not reason:
                reason = f"Código {code}" if code else "Motivo no informado"
            if activities or float(row.get("uc_brutas") or 0) > 0:
                absence_activity_count += 1
            activity_text = "; ".join(
                f"{a.get('desc_funcion') or 'Actividad'} (div. {a.get('division') or '—'}): "
                f"{fmt_int(a.get('palets') or 0)} palets, {fmt_int(a.get('plus') or 0)} PLUs, "
                f"{fmt_int(a.get('cantidad') or 0)} unidades"
                for a in activities
            ) or "Sin actividad registrada en la cache WMS"
            absence_cases.append({
                "fecha": day,
                "dia": WEEKDAYS[date.weekday()],
                "legajo": person,
                "nombre": ((row.get("nombre") or "") if "�" not in (row.get("nombre") or "") else "Nombre con carácter ilegible en cache"),
                "sector": row["sector"],
                "situacion_pv": attendance.get("SITUACION", ""),
                "codigo_ausentismo_pv": code,
                "descripcion_ausentismo_pv": attendance.get("DES_AUSENTISMO", ""),
                "observacion_pv": attendance.get("OBSERVACION", ""),
                "motivo": reason,
                "bultos": float(row.get("uc_brutas") or 0),
                "horas_armado": round(sum((b-a).total_seconds() for a,b in intervals.get(person, []))/3600, 2),
                "actividad": activity_text,
            })
            absence_summary[reason] += 1
        if time_people_absent - positive_units_people:
            raise SystemExit(f"Hay tiempo con ausencia pero sin bultos en {day}; revisar antes de cerrar")
        if positive_units_people != active_people:
            # Keep the mismatch visible rather than silently equating a stage and a unit record.
            pass
        daily.append({
            "fecha": day,
            "fecha_corta": date.strftime("%d/%m"),
            "dia": WEEKDAYS[date.weekday()],
            "dotacion": len(roster_ids),
            "presentes": len(pv_present_people),
            "ausentes": len(pv_absent_people),
            "sin_registro": len(pv_missing_people),
            "actividad_armado": len(active_people),
            "presentes_sin_tiempo": len(present_people_without_time),
            "bultos_brutos": round(gross_cached),
            "bultos_presentes": round(gross_present),
            "bultos_brutos_fuente": round(day_bultos_raw),
            "bultos_computables_referencia_no_usar": round(gross_computable),
            "horas_armado": round(day_hours, 2),
            "fte": round(day_hours / STANDARD_HOURS, 2),
            "intervalos_invalidos": day_invalid,
            "etapas": len(stages),
        })

    totals = {
        "periodo": "Agosto–septiembre 2026",
        "dias_habiles": len(workdays),
        "dias_cache_cargados": batch_ok,
        "fecha_calculo": period["calculado_at"],
        "dotacion": len(roster_ids),
        "dotacion_zona_1": sum(zone_by_person[x] == SECTORS[0] for x in roster_ids),
        "dotacion_zona_2": sum(zone_by_person[x] == SECTORS[1] for x in roster_ids),
        "promedio_diario_dotacion": round(sum(row["dotacion"] for row in daily) / len(workdays), 2),
        "jornadas_asignadas": sum(row["dotacion"] for row in daily),
        "presentes": sum(row["presentes"] for row in daily),
        "presentes_situacion_pv": sum(row["presentes"] for row in daily),
        "ausentes": sum(row["ausentes"] for row in daily),
        "sin_registro_asistencia": sum(row["sin_registro"] for row in daily),
        "legajo_dias_con_tiempo_armado": sum(row["actividad_armado"] for row in daily),
        "legajo_dias_presentes_sin_tiempo_armado": len(present_without_time),
        "legajo_dias_ausencia_con_actividad": absence_activity_count,
        "snapshot_pv_dia_laboral": pv_snapshot,
        "bultos_brutos": sum(row["bultos_brutos"] for row in daily),
        "bultos_presentes": sum(row["bultos_presentes"] for row in daily),
        "bultos_presentes_sin_tiempo": round(sum(row["bultos"] for row in present_without_time)),
        "jornadas_presentes_sin_tiempo_con_bultos": sum(row["bultos"] > 0 for row in present_without_time),
        "bultos_brutos_fuente": sum(row["bultos_brutos_fuente"] for row in daily),
        "bultos_computables_referencia_no_usar": sum(row["bultos_computables_referencia_no_usar"] for row in daily),
        "horas_armado": round(total_operation_seconds / 3600, 2),
        "horas_estandar": STANDARD_HOURS,
        "fte": round(total_operation_seconds / 3600 / STANDARD_HOURS, 2),
        "fte_promedio_diario": round(total_operation_seconds / 3600 / STANDARD_HOURS / len(workdays), 2),
        "bultos_promedio_diario": round(sum(row["bultos_brutos"] for row in daily) / len(workdays)),
        "bultos_por_jornada_asignada": round(sum(row["bultos_brutos"] for row in daily) / sum(row["dotacion"] for row in daily), 2),
        "bultos_por_presencia": round(sum(row["bultos_presentes"] for row in daily) / sum(row["presentes"] for row in daily), 2),
        "bultos_por_fte": round(sum(row["bultos_brutos"] for row in daily) / (total_operation_seconds / 3600 / STANDARD_HOURS), 2),
        "horas_promedio_por_legajo_dia_con_tiempo": round(total_operation_seconds / 3600 / sum(row["actividad_armado"] for row in daily), 2),
        "etapas": stage_count,
        "filas_detalle_origen": raw_line_count,
        "filas_detalle_con_horario": raw_timed_line_count,
        "etapas_con_horario_incompleto": missing_time_stage_count,
        "etapas_intervalo_invalido": invalid_stage_count,
        "segundos_superpuestos": round(total_overlap_seconds, 2),
        "diferencia_cache_segundos_vs_fuente": round(cache_vs_raw_seconds_diff, 2),
        "diferencia_bultos_cache_vs_fuente": round(raw_vs_cached_units_diff, 2),
    }
    zone_data = []
    for sector in SECTORS:
        people = [person for person in roster_ids if zone_by_person[person] == sector]
        zone_days = [row for row in daily_cache_rows.values() for row in row if row["sector"] == sector and row["fecha"] in day_keys]
        zone_attendance = [
            pv_attendance.get((day, person))
            for day in day_keys
            for person in people
        ]
        hours = db.execute(
            f"""SELECT COALESCE(SUM(segundos_validos),0) FROM lab_actividad_duracion_cache
                WHERE fecha BETWEEN '20260801' AND '20260930' AND operacion='ARMADO' AND division=?
                  AND fecha IN ({','.join('?' for _ in day_keys)}) AND legajo IN ({','.join('?' for _ in people)})""",
            [DIVISION_WMS, *day_keys, *people],
        ).fetchone()[0] / 3600
        gross = sum(float(row.get("uc_brutas") or 0) for row in zone_days)
        zone_data.append({
            "sector": sector,
            "label": "Zona 1" if sector == SECTORS[0] else "Zona 2",
            "dotacion": len(people),
            "jornadas_asignadas": len(people) * len(workdays),
            "presentes": sum(bool(row) and str(row.get("SITUACION") or "").strip().upper() == "PRESENTE" for row in zone_attendance),
            "ausentes": sum(bool(row) and str(row.get("SITUACION") or "").strip().upper() != "PRESENTE" for row in zone_attendance),
            "sin_registro": sum(row is None for row in zone_attendance),
            "legajo_dias_con_bultos": sum(float(row.get("uc_brutas") or 0) > 0 for row in zone_days),
            "bultos_brutos": round(gross),
            "horas_armado": round(hours, 2),
            "fte": round(hours / STANDARD_HOURS, 2),
            "bultos_por_fte": round(gross / (hours / STANDARD_HOURS), 2) if hours else 0,
        })

    if totals["jornadas_asignadas"] != totals["presentes"] + totals["ausentes"] + totals["sin_registro_asistencia"]:
        raise SystemExit("No concilia dotación asignada contra estados de asistencia")
    # August grouped cache and timed detail do not fully reconcile for gross
    # units. Keep the cache as the displayed production basis and expose the
    # discrepancy in the card instead of silently choosing one side.
    if totals["diferencia_cache_segundos_vs_fuente"] != 0 or totals["etapas_con_horario_incompleto"]:
        raise SystemExit(f"La cache de horas no concilia o hay horarios incompletos: diferencia={totals['diferencia_cache_segundos_vs_fuente']} segundos, incompletos={totals['etapas_con_horario_incompleto']}")
    if totals["segundos_superpuestos"] != 0:
        raise SystemExit("Hay tiempos superpuestos; el FTE requiere revisión antes de publicar")

    data = {
        "title": "Productividad Armado Secos",
        "subtitle": "Base operativa para validar con la operación",
        "source": "Cache interno del sistema de Productividad (PV_ETAPA_CAB/DET). No se consultó el WMS crudo.",
        "source_caveat": "La extracción y las transformaciones upstream que alimentan las tablas PV no fueron auditadas en este análisis.",
        "formula": "FTE = horas registradas en etapas PICKIN de división 1 ÷ 6,5 horas estándar.",
        "period": totals["periodo"] + " · lunes a viernes · Zonas 1 y 2 unificadas",
        "totals": totals,
        "zones": zone_data,
        "daily": daily,
        "present_without_armado_time": present_without_time,
        "absence_summary": [{"motivo": reason, "cantidad": count} for reason, count in absence_summary.most_common()],
        "absence_cases": absence_cases,
    }
    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(daily[0].keys()))
        writer.writeheader()
        writer.writerows(daily)

    template = r'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Secos · Productividad operativa · Agosto–septiembre 2026</title>
<style>
:root{--ink:#15384c;--func-armado:#138a87;--func-clark:#4389a8;--func-recepcion:#c49324;--func-carga:#c66d55;--func-control:#7965a8;--muted:#587286;--teal:#158a87;--teal2:#dff2ef;--blue:#4389a8;--blue2:#edf5f8;--gold:#d4a542;--gold2:#fbf4e4;--coral:#c66d55;--coral2:#faeee9;--line:#d8e4e8;--paper:#e8f0f3;--white:#fff;--shadow:0 18px 55px rgba(22,54,73,.11);font-family:Inter,"Segoe UI",Arial,sans-serif;color:var(--ink)}*{box-sizing:border-box}body{margin:0;background:var(--paper);font-size:15px}.toolbar{height:58px;background:#f8fbfc;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 24px;position:sticky;top:0;z-index:10}.brand{font-size:15px;font-weight:800;letter-spacing:.02em}.brand small{font-weight:500;color:var(--muted)}.actions{display:flex;gap:8px;align-items:center}.button{font:inherit;border:1px solid #c8d9df;background:white;color:var(--ink);padding:9px 14px;border-radius:8px;cursor:pointer}.button.primary{background:var(--ink);color:white;border-color:var(--ink)}.button[aria-pressed=true]{background:var(--teal2);border-color:#91c9c0}.deck{max-width:1580px;margin:24px auto;padding:0 24px}.slide{display:block;background:white;border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);margin:0 0 26px;padding:44px;min-height:690px;overflow:hidden}.cover{position:relative;min-height:730px;display:flex;align-items:center;background:linear-gradient(112deg,#fff 0 60%,#edf6f6 60% 100%)}.cover-content{position:relative;z-index:1;max-width:940px}.eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:12px;font-weight:800;color:var(--teal)}h1{font-size:clamp(44px,5vw,72px);line-height:1.02;letter-spacing:-.045em;margin:18px 0;color:var(--ink)}h2{font-size:clamp(34px,3.5vw,52px);line-height:1.05;letter-spacing:-.035em;margin:8px 0 12px}h3{font-size:19px;margin:0 0 14px}.lead{font-size:23px;line-height:1.42;color:var(--muted);max-width:820px}.period{display:inline-flex;gap:10px;align-items:center;margin-top:22px;padding:11px 15px;background:var(--ink);color:white;border-radius:7px;font-size:14px;font-weight:650}.cover-number{display:flex;gap:28px;align-items:baseline;margin-top:54px}.cover-number strong{font-size:52px;letter-spacing:-.04em}.cover-number span{font-size:17px;color:var(--muted)}.section-bar{display:flex;align-items:center;gap:12px;background:var(--blue2);border-left:4px solid var(--blue);padding:11px 15px;margin:22px 0 15px;font-size:16px;font-weight:800}.section-bar.warm{background:var(--gold2);border-color:var(--gold)}.section-bar.green{background:#eaf5f0;border-color:var(--teal)}.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}.kpi{background:#f1f6f8;border-top:3px solid var(--blue);padding:14px 15px 13px;min-height:105px;border-radius:3px 3px 9px 9px}.kpi.teal{border-color:var(--teal);background:#eef8f6}.kpi.gold{border-color:var(--gold);background:#fbf7ec}.kpi.coral{border-color:var(--coral);background:#fbf3f0}.kpi-label{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700}.kpi-value{font-size:28px;font-weight:800;line-height:1.1;margin-top:11px;letter-spacing:-.025em}.kpi-sub{font-size:11px;color:var(--muted);margin-top:7px}.cols{display:grid;grid-template-columns:1.04fr .96fr;gap:18px}.panel{border:1px solid var(--line);background:#fbfdfe;border-radius:11px;padding:20px}.universe{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:12px;align-items:center;margin:8px 0 16px}.universe-cell{background:#f2f7f8;padding:13px 15px;border-radius:8px}.universe-cell b{display:block;font-size:24px;margin-bottom:4px}.universe-cell span{font-size:12px;color:var(--muted)}.operator{font-size:26px;font-weight:700;color:#9ab0ba}.note{font-size:12px;line-height:1.45;color:var(--muted)}.callout{padding:13px 15px;border-left:4px solid var(--gold);background:var(--gold2);border-radius:0 8px 8px 0;font-size:13px;line-height:1.45}.callout.alert{border-color:var(--coral);background:var(--coral2)}.zone-table,.daily-table,.case-table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}.zone-table th,.zone-table td,.daily-table th,.daily-table td,.case-table th,.case-table td{padding:10px 11px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}.zone-table th,.daily-table th,.case-table th{text-transform:uppercase;font-size:10px;letter-spacing:.06em;color:var(--muted);background:#f2f7f8}.zone-table th:first-child,.zone-table td:first-child,.daily-table th:first-child,.daily-table td:first-child,.case-table th:first-child,.case-table td:first-child{text-align:left}.zone-table td:first-child{font-weight:750}.zone-table tfoot td{font-weight:800;background:#f3f8f9}.productivity{display:grid;grid-template-columns:repeat(3,1fr);gap:11px;margin-top:14px}.product-card{padding:15px;border-radius:8px;background:var(--blue2);border-bottom:3px solid var(--blue)}.product-card:nth-child(2){background:#eef8f6;border-color:var(--teal)}.product-card:nth-child(3){background:#fbf7ec;border-color:var(--gold)}.product-card b{display:block;font-size:27px;margin:7px 0}.product-card span{font-size:12px;color:var(--muted);line-height:1.35}.chart{height:158px;width:100%;display:block;margin:10px 0}.chart-grid{stroke:#dbe7eb;stroke-width:1}.chart-bar{fill:#4c9ab3}.chart-bar:nth-of-type(3n){fill:#15958d}.chart-label{font-size:10px;fill:#587286}.chart-value{font-size:10px;fill:#244a5d;font-weight:700}.chart-axis{font-size:10px;fill:#728997}.daily-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.daily-table-wrap{max-height:54vh;overflow:auto;border:1px solid var(--line);border-radius:8px}.daily-table{font-size:12px}.daily-table td:first-child{font-weight:700}.daily-table .bad{color:#ad4937;font-weight:800}.daily-table .good{color:#148278;font-weight:750}.daily-table tfoot td{font-weight:800;background:#f3f8f9}.table-foot{display:flex;justify-content:space-between;gap:20px;margin-top:10px}.detail-button{margin-top:10px}.footer-note{font-size:11px;line-height:1.5;color:var(--muted);border-top:1px solid var(--line);padding-top:13px;margin-top:18px}.quality-row{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}.quality-tag{font-size:12px;padding:8px 11px;background:#eef6f4;border-radius:5px;color:#23675e}.quality-tag.warn{background:var(--coral2);color:#904b3b}.nav{display:none}.modal{position:fixed;inset:0;background:rgba(11,33,46,.65);z-index:30;display:none;align-items:center;justify-content:center;padding:22px}.modal.open{display:flex}.modal-card{background:white;width:min(1440px,97vw);max-height:92vh;border-radius:14px;box-shadow:0 24px 80px #051b2a55;display:flex;flex-direction:column;overflow:hidden}.modal-head{display:flex;justify-content:space-between;align-items:center;padding:18px 23px;border-bottom:1px solid var(--line)}.modal-head h3{margin:0}.modal-tabs{display:flex;gap:8px;padding:12px 22px 0}.modal-body{padding:14px 22px 22px;overflow:auto}.modal-body[hidden]{display:none}.case-list{max-height:62vh;overflow:auto;border:1px solid var(--line);border-radius:8px}.case-table{font-size:12px}.case-table td:first-child{font-weight:700}.case-table td:nth-child(4){text-align:left}.small{font-size:11px;color:var(--muted)}.report-only{display:block}.presentation .toolbar{position:fixed;left:0;right:0;top:0}.presentation .deck{max-width:none;margin:0;padding:68px 24px 78px;height:100dvh}.presentation .slide{display:none;margin:0 auto;padding:clamp(24px,3vw,48px);width:min(1600px,calc(100vw - 48px));height:calc(100dvh - 146px);min-height:540px;overflow:auto;border-radius:14px}.presentation .slide.active{display:block}.presentation .slide.cover.active{display:flex}.presentation .nav{position:fixed;bottom:0;left:0;right:0;display:flex;align-items:center;justify-content:space-between;background:#f7fafb;border-top:1px solid var(--line);padding:10px 18px;z-index:15}.nav-center{display:flex;align-items:center;gap:12px}.nav select{font:inherit;min-width:310px;padding:10px;border:1px solid var(--line);border-radius:7px;color:var(--ink);background:white}.nav-count{font-variant-numeric:tabular-nums;color:var(--muted);min-width:60px}.presentation .kpi{min-height:91px;padding:11px 13px}.presentation .kpi-value{font-size:clamp(22px,1.8vw,31px);margin-top:8px}.presentation .panel{padding:17px}.presentation .daily-table{font-size:11px}.presentation .section-bar{margin-top:15px}.presentation .cover{min-height:0}.presentation .chart{height:140px}.presentation .daily-table-wrap{max-height:34vh}.fullscreen .toolbar{display:none}.fullscreen .deck{padding-top:12px;height:100dvh}.fullscreen .slide{height:calc(100dvh - 88px)}.fullscreen .nav{padding:8px 18px}dialog{border:0;padding:0;background:transparent;max-width:none;max-height:none}button:focus-visible,select:focus-visible{outline:3px solid #59b8b1;outline-offset:2px}@media(max-width:1000px){.kpis{grid-template-columns:repeat(3,1fr)}.cols{grid-template-columns:1fr}.slide{padding:26px}.presentation .slide{width:calc(100vw - 22px);padding:24px 20px}.universe{grid-template-columns:1fr auto 1fr auto 1fr}.zone-table th,.zone-table td{padding:7px 6px;font-size:11px}}@media(max-width:680px){.toolbar{padding:0 10px}.actions .button:not(.primary){display:none}.deck{padding:12px}.slide{padding:20px}.kpis{grid-template-columns:repeat(2,1fr)}.universe{grid-template-columns:1fr}.operator{display:none}.productivity{grid-template-columns:1fr}.nav select{min-width:0;width:46vw}.nav .button{padding:8px}.presentation .slide{height:calc(100dvh - 126px)}.zone-table{font-size:10px}.zone-table th,.zone-table td{padding:5px 4px}.cover-number strong{font-size:40px}}
@media print{body{background:white}.toolbar,.nav,.modal{display:none!important}.deck{margin:0;padding:0;max-width:none}.slide{display:block!important;box-shadow:none;border:0;border-radius:0;margin:0;padding:18mm;min-height:0;page-break-after:always}.cover{min-height:250mm}.daily-table-wrap{max-height:none;overflow:visible}.daily-table{font-size:9px}.daily-table th,.daily-table td{padding:5px}.footer-note{font-size:9px}}
</style><style>
html,body{max-width:100%;overflow-x:hidden}.analysis-slide{max-width:100%;overflow:hidden}.analysis-heading{display:flex;align-items:center;justify-content:space-between;gap:20px}.analysis-heading h2{font-size:36px;margin:4px 0}.analysis-heading .lead{font-size:14px;margin:0;color:var(--muted)}.period-chip{flex:none;padding:9px 13px;border-radius:999px;background:var(--teal2);color:#176d69;font-size:12px;font-weight:800}.analysis-slide .section-bar{margin:12px 0 9px;padding:8px 12px;font-size:13px}.analysis-slide .kpis{grid-template-columns:repeat(6,minmax(0,1fr));gap:9px}.analysis-slide .kpi{min-width:0;min-height:78px;padding:10px 12px}.analysis-slide .kpi-label{font-size:10px}.analysis-slide .kpi-value{font-size:25px;margin-top:7px;white-space:nowrap}.analysis-slide .kpi-sub{font-size:10px;margin-top:4px;line-height:1.2}.analysis-slide .kpi.fte .kpi-value{font-size:36px;color:var(--teal);line-height:1}.base-line{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:10px 0;padding:10px 13px;border:1px solid var(--line);border-radius:9px;background:#f8fbfc;white-space:nowrap}.base-line strong{font-size:11px;color:var(--muted);font-weight:650}.base-line b{font-size:18px}.base-line>span{color:#9ab0ba;font-size:18px}.productivity-panel{padding:12px 16px!important}.productivity-heading{display:flex;justify-content:space-between;align-items:center;gap:20px}.productivity-heading h3{margin:0 0 3px}.productivity-heading .note{margin:0}.unit-tag{font-size:10px;color:var(--muted);background:var(--blue2);border-radius:999px;padding:7px 10px;white-space:nowrap}.analysis-slide .productivity{grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:9px}.analysis-slide .product-card{min-width:0;padding:10px 14px}.analysis-slide .product-card b{font-size:clamp(32px,3vw,46px);line-height:1;margin:5px 0;color:var(--ink)}.analysis-slide .product-card span{font-size:11px;line-height:1.2}.reconcile-panel{display:grid;grid-template-columns:minmax(220px,1fr) auto;align-items:center;gap:14px 22px;margin-top:11px;padding:12px 15px;border:1px solid #eddacb;border-left:4px solid var(--coral);border-radius:9px;background:#fffaf7}.reconcile-heading{display:flex;align-items:center;justify-content:space-between;gap:14px}.reconcile-heading .eyebrow{font-size:9px}.reconcile-heading h3{margin:2px 0 3px;font-size:16px}.reconcile-heading .note{margin:0;font-size:11px}.issue-cards{display:flex;gap:9px}.issue-card{display:flex;align-items:center;gap:8px;min-width:185px;padding:8px 10px;border-radius:7px}.issue-card.coral{background:var(--coral2)}.issue-card.gold{background:var(--gold2)}.issue-card b{font-size:23px}.issue-card span{font-size:10px;line-height:1.2;color:var(--muted)}.analysis-slide>.footer-note{font-size:9px;line-height:1.3;margin-top:auto;padding-top:7px}.modal-card{width:min(1240px,96vw);max-height:92dvh}.reconcile-body{overflow-x:hidden;overflow-y:auto}.reconcile-body>.callout{font-size:12px;padding:9px 12px;margin:5px 0}.case-list{max-height:32vh;overflow-x:hidden;overflow-y:auto;margin:8px 0 14px;border-radius:7px}.case-table{table-layout:fixed;width:100%;font-size:11px}.case-table th,.case-table td{white-space:normal;overflow-wrap:anywhere;text-align:left;padding:7px 8px}.case-table th:nth-child(1){width:11%}.case-table th:nth-child(2){width:9%}.case-table th:nth-child(3){width:27%}.case-table th:nth-child(4){width:19%}.case-table th:nth-child(5){width:12%}.case-table th:nth-child(6),.case-table th:nth-child(7){width:11%}.reconcile-body .case-list:last-of-type .case-table th:nth-child(3){width:36%}.reconcile-body .case-list:last-of-type .case-table th:nth-child(4){width:14%}.reconcile-body .case-list:last-of-type .case-table th:nth-child(5),.reconcile-body .case-list:last-of-type .case-table th:nth-child(6){width:17%}.presentation .analysis-slide{display:none;height:calc(100dvh - 146px);min-height:0;overflow:hidden;padding:clamp(18px,2.1vw,32px);gap:0}.presentation .analysis-slide.active{display:flex;flex-direction:column}.presentation .analysis-slide .section-bar{flex:none}.presentation .analysis-slide .kpis{flex:none}.presentation .analysis-slide .kpi{min-height:70px;padding:8px 10px}.presentation .analysis-slide .kpi-value{font-size:clamp(19px,1.6vw,26px)}.presentation .analysis-slide .kpi.fte .kpi-value{font-size:clamp(29px,2.5vw,38px)}.presentation .analysis-slide .base-line{flex:none;margin:8px 0;padding:7px 11px}.presentation .analysis-slide .base-line b{font-size:16px}.presentation .analysis-slide .productivity-panel{flex:none}.presentation .analysis-slide .product-card{padding:8px 12px}.presentation .analysis-slide .product-card b{font-size:clamp(30px,2.6vw,42px)}.presentation .analysis-slide .reconcile-panel{flex:none}.presentation .analysis-slide>.footer-note{flex:none}.presentation .cover.active{height:calc(100dvh - 146px);min-height:0;overflow:hidden}.presentation .cover-content{max-width:880px}.presentation .cover h1{font-size:clamp(42px,5vw,66px)}.presentation .cover .lead{font-size:clamp(17px,2vw,22px)}
@media(max-height:820px) and (min-width:1001px){.presentation .analysis-heading h2{font-size:30px}.presentation .analysis-heading .lead{font-size:12px}.presentation .analysis-slide .section-bar{margin:8px 0 6px;padding:6px 10px}.presentation .analysis-slide .kpi{min-height:62px;padding:6px 9px}.presentation .analysis-slide .kpi-sub{font-size:9px}.presentation .analysis-slide .base-line{margin:6px 0;padding:5px 9px}.presentation .analysis-slide .productivity-panel{padding:8px 12px!important}.presentation .analysis-slide .product-card{padding:6px 10px}.presentation .analysis-slide .product-card b{font-size:32px}.presentation .analysis-slide .reconcile-panel{margin-top:7px;padding:8px 11px}.presentation .analysis-slide>.footer-note{font-size:8px;padding-top:4px}}
@media(max-width:1000px){.analysis-slide .kpis{grid-template-columns:repeat(3,minmax(0,1fr))}.base-line{flex-wrap:wrap;justify-content:center;white-space:normal}.reconcile-panel{grid-template-columns:1fr}.issue-cards{width:100%}.issue-card{flex:1;min-width:0}.presentation .analysis-slide{height:calc(100dvh - 126px);overflow-y:auto}.analysis-slide{overflow-y:visible}.modal-card{width:98vw}.case-list{max-height:30vh}}
@media(max-width:680px){.analysis-heading{align-items:flex-start}.analysis-heading h2{font-size:28px}.period-chip{font-size:10px}.analysis-slide .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.analysis-slide .productivity{grid-template-columns:1fr}.analysis-slide .product-card{display:grid;grid-template-columns:1fr auto;gap:3px 10px}.analysis-slide .product-card b{grid-column:2;grid-row:1/3;font-size:31px}.analysis-slide .product-card span{grid-column:1}.productivity-heading{align-items:flex-start}.unit-tag{display:none}.issue-cards{flex-direction:column}.base-line{gap:7px}.case-table{font-size:10px}.case-table th,.case-table td{padding:5px 4px}}
.analysis-slide .kpi{border-radius:9px;box-shadow:0 2px 8px rgba(22,54,73,.08)}.analysis-slide .kpi-value{font-size:clamp(28px,2.1vw,36px);line-height:1;font-weight:800;color:var(--blue)}.analysis-slide .kpi.teal .kpi-value{color:var(--teal)}.analysis-slide .kpi.gold .kpi-value{color:var(--gold)}.analysis-slide .kpi.coral .kpi-value{color:var(--coral)}.analysis-slide .kpi.fte .kpi-value{font-size:clamp(28px,2.1vw,36px);line-height:1;color:var(--teal)}
.presentation .analysis-slide .kpi-value{font-size:clamp(28px,2.1vw,36px)}.presentation .analysis-slide .kpi.fte .kpi-value{font-size:clamp(28px,2.1vw,36px)}
.absence-summary-panel{margin-top:9px;padding:9px 12px;border-radius:9px;background:#f3f8f9;border:1px solid var(--line)}.absence-summary-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:6px}.absence-summary-head h3{font-size:13px;margin:0}.absence-summary-head span{font-size:10px;color:var(--muted)}.absence-summary-items{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:5px}.absence-type{display:flex;justify-content:space-between;align-items:center;gap:6px;padding:5px 8px;border-radius:6px;background:white;border-left:3px solid var(--gold);font-size:10px;line-height:1.1;min-width:0}.absence-type span{overflow-wrap:anywhere}.absence-type b{font-size:13px;flex:none;color:var(--ink)}.presentation .absence-summary-panel{margin-top:7px;padding:7px 10px}.presentation .absence-summary-items{gap:4px}.presentation .absence-type{padding:4px 7px;font-size:9px}.presentation .absence-type b{font-size:12px}.case-table.present-table th:nth-child(1){width:12%}.case-table.present-table th:nth-child(2){width:10%}.case-table.present-table th:nth-child(3){width:30%}.case-table.present-table th:nth-child(4){width:20%}.case-table.present-table th:nth-child(5){width:14%}.case-table.present-table th:nth-child(6){width:14%}.case-table.absence-table th:nth-child(1){width:9%}.case-table.absence-table th:nth-child(2){width:8%}.case-table.absence-table th:nth-child(3){width:18%}.case-table.absence-table th:nth-child(4){width:16%}.case-table.absence-table th:nth-child(5){width:15%}.case-table.absence-table th:nth-child(6){width:9%}.case-table.absence-table th:nth-child(7){width:9%}.case-table.absence-table th:nth-child(8){width:16%}
.absence-summary-panel{margin-top:8px;padding:10px 13px;border-radius:9px;background:#f8fafb;border:1px solid var(--line)}.absence-summary-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:7px}.absence-summary-head h3{font-size:16px;margin:0}.absence-summary-head span{font-size:12px;color:var(--muted)}.absence-chart{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 20px}.absence-row{min-width:0}.absence-row-head{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:12px;line-height:1.2}.absence-row-head span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.absence-row-head b{font-size:13px;flex:none;color:var(--ink)}.absence-track{height:6px;margin-top:4px;border-radius:9px;background:#e7edf0;overflow:hidden}.absence-track i{display:block;height:100%;border-radius:9px;background:var(--function-accent,var(--teal))}.presentation .absence-summary-panel{margin-top:6px;padding:8px 11px}.presentation .absence-chart{grid-template-columns:repeat(3,minmax(0,1fr));gap:4px 16px}.presentation .absence-row-head{font-size:11px}.presentation .absence-track{height:5px;margin-top:3px}
.scope-steps{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin-top:38px;max-width:1300px}.scope-step{--func-color:#8ba0aa;--func-soft:#f4f7f8;padding:22px 19px;border-radius:12px;border:1px solid var(--line);border-top:6px solid var(--func-color);background:var(--func-soft);display:flex;flex-direction:column;gap:8px;min-width:0;min-height:150px}.scope-step[data-function="armado"]{--func-color:var(--func-armado);--func-soft:#e9f6f3}.scope-step[data-function="clark"]{--func-color:var(--func-clark);--func-soft:#edf5f8}.scope-step[data-function="recepcion"]{--func-color:var(--func-recepcion);--func-soft:#fbf5e7}.scope-step[data-function="carga"]{--func-color:var(--func-carga);--func-soft:#fbefeb}.scope-step[data-function="control"]{--func-color:var(--func-control);--func-soft:#f2eff8}.scope-step.active{box-shadow:0 7px 20px rgba(22,54,73,.1)}.scope-step>span{font-size:13px;letter-spacing:.1em;font-weight:850;color:var(--func-color)}.scope-step>b{font-size:23px;line-height:1.1;color:var(--ink)}.scope-step>small{font-size:13px;line-height:1.35;color:var(--muted)}.analysis-slide[data-function="armado"]{--function-accent:var(--func-armado);--function-soft:#e9f6f3}.analysis-slide[data-function="clark"]{--function-accent:var(--func-clark);--function-soft:#edf5f8}.analysis-slide[data-function="recepcion"]{--function-accent:var(--func-recepcion);--function-soft:#fbf5e7}.analysis-slide[data-function="carga"]{--function-accent:var(--func-carga);--function-soft:#fbefeb}.analysis-slide[data-function="control"]{--function-accent:var(--func-control);--function-soft:#f2eff8}.analysis-slide[data-function] .analysis-heading .eyebrow{color:var(--function-accent)}.analysis-slide[data-function] .section-bar{border-color:var(--function-accent);background:var(--function-soft)}.cover .cover-content{max-width:1300px}.cover .lead{max-width:1050px}.legacy-economic-slide{padding:0!important;min-height:0!important;height:calc(100dvh - 146px)!important;overflow:hidden!important;min-width:0!important}.legacy-economic-frame{display:block;width:100%;max-width:100%;height:100%;min-height:0;border:0;border-radius:16px;background:white}.presentation .legacy-economic-slide{height:calc(100dvh - 146px)!important;min-height:0!important;padding:0!important;overflow:hidden!important;min-width:0!important}.presentation .legacy-economic-frame{width:100%;max-width:100%;height:100%;min-height:0;border-radius:0}@media(max-width:900px){.scope-steps{grid-template-columns:repeat(2,minmax(0,1fr));margin-top:22px}.scope-step{min-height:120px;padding:17px}.scope-step:first-child{grid-column:1/-1}.legacy-economic-frame{height:100%;min-height:0}}
</style></head><body>
<header class="toolbar"><div class="brand">VigIA <small>· Productividad operativa</small></div><div class="actions"><button class="button" id="report-mode" aria-pressed="true">Informe completo</button><button class="button" id="presentation-mode" aria-pressed="false">Presentación</button><button class="button" id="fullscreen-toggle">Pantalla completa</button><button class="button primary" id="print-button">Imprimir / PDF</button></div></header>
<main class="deck" id="deck">
<section class="slide cover active" data-title="Productividad del sector Secos">
 <div class="cover-content"><div class="eyebrow">Validación operativa · sector Secos</div><h1>Productividad<br>del sector Secos</h1><p class="lead">Una revisión función por función de producción, dotación y tiempo registrado, para acordar una base común antes de evaluar objetivos y premios.</p><div class="period">Primera etapa <span>·</span> Armado <span>·</span> Zonas 1 y 2 unificadas</div><div class="scope-steps" aria-label="Funciones incluidas en el análisis"><div class="scope-step active" data-function="armado"><span>01 · EN ANÁLISIS</span><b>Armado</b><small>Base agosto–septiembre y escenario económico</small></div><div class="scope-step" data-function="clark"><span>02 · SIGUIENTE</span><b>Clark</b><small>Base por función</small></div><div class="scope-step" data-function="recepcion"><span>03 · SIGUIENTE</span><b>Recepción</b><small>Base por función</small></div><div class="scope-step" data-function="carga"><span>04 · SIGUIENTE</span><b>Carga</b><small>Base por función</small></div><div class="scope-step" data-function="control"><span>05 · SIGUIENTE</span><b>Control</b><small>Base por función</small></div></div><p class="footer-note">Cada función se incorporará después de revisar sus registros con Operaciones. Esta primera etapa presenta Armado Secos; todavía no consolida resultados de todo el sector.</p></div>
</section>
<section class="slide analysis-slide" data-function="armado" data-title="Armado · Secos · Base de cálculo">
 <div class="analysis-heading"><div><div class="eyebrow">Agosto–septiembre 2026 · lunes a viernes · Zona 1 + Zona 2</div><h2>Armado · Secos</h2><p class="lead">Base de producción y dedicación registrada, antes de reglas de pago.</p></div><div class="period-chip">43 días hábiles</div></div>
 <div class="section-bar">Volumen, dotación y dedicación</div><div class="kpis" id="kpis"></div>
 <div class="productivity-panel panel"><div class="productivity-heading"><div><h3>Productividad</h3><p class="note"><b>Bultos brutos</b> es el total producido en el período, antes de dividirlo por personas o tiempo. Los tres indicadores muestran ese total desde distintas perspectivas.</p></div><div class="unit-tag">bultos por jornada o FTE</div></div><div class="productivity" id="productivity"></div></div>
 <div class="reconcile-panel"><div class="reconcile-heading"><div><div class="eyebrow">Validación de registros fuente</div><h3>Registros para conciliar</h3><p class="note">Abrí el detalle para revisar presencia sin tiempo y ausencias con actividad cacheada.</p></div><button class="button primary" id="open-details">Ver registros y actividad</button></div><div class="issue-cards"><div class="issue-card coral"><b id="present-no-time-count"></b><span>presentes sin tiempo de Armado</span></div><div class="issue-card gold"><b id="absent-activity-count"></b><span>ausencias con bultos o actividad registrados</span></div></div></div>
 <div class="absence-summary-panel"><div class="absence-summary-head"><h3>Ausencias por motivo</h3><span id="absence-total"></span></div><div class="absence-chart" id="absence-chart" role="img" aria-label="Jornadas de ausencia por motivo"></div></div>
</section>
<section class="slide legacy-economic-slide" data-title="Armado · Nuevo escenario de premio"><iframe class="legacy-economic-frame" id="legacy-economic-frame" title="Armado Secos · impacto económico y participación" loading="eager"></iframe></section>
</main>
<nav class="nav" id="nav"><button class="button" id="prev">← Anterior</button><div class="nav-center"><select id="slide-select" aria-label="Seleccionar lámina"></select><span class="nav-count" id="nav-count"></span></div><button class="button primary" id="next">Siguiente →</button></nav>
<div class="modal" id="details-modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-card"><div class="modal-head"><div><h3 id="modal-title">Asistencia y actividad · Armado Secos</h3><div class="small">Agosto–septiembre 2026 · clasificado por SITUACION de PV_DIA_LABORAL</div></div><button class="button" id="close-modal">Cerrar ✕</button></div><div class="modal-body reconcile-body"><div class="callout alert"><b>Presentes sin tiempo de Armado</b> · figuran como PRESENTE en PV, pero no tienen etapa PICKIN con horario para ese legajo-día.</div><div class="case-list"><table class="case-table present-table"><thead><tr><th>Fecha</th><th>Legajo</th><th>Nombre</th><th>Sector / zona</th><th>Bultos Armado</th><th>Horas Armado</th></tr></thead><tbody id="present-no-time-body"></tbody></table></div><div class="callout alert"><b>Ausentes · motivo y actividad</b> · se consideran ausentes las filas cuya SITUACION no es PRESENTE. Se muestra el motivo PV y cualquier actividad encontrada en la cache WMS.</div><div class="case-list"><table class="case-table absence-table"><thead><tr><th>Fecha</th><th>Legajo</th><th>Nombre</th><th>Motivo de ausencia</th><th>Observación PV</th><th>Bultos Armado</th><th>Horas Armado</th><th>Actividad WMS en cache</th></tr></thead><tbody id="absence-body"></tbody></table></div><p class="small">La lista permite cotejar legajo y jornada con PV_DIA_LABORAL y la actividad disponible en la cache local.</p></div></div></div>
<script type="application/json" id="deck-data">__DATA__</script>
<script type="application/octet-stream" id="legacy-report-html">__LEGACY_REPORT_B64__</script>
<script>
const D=JSON.parse(document.getElementById('deck-data').textContent),T=D.totals,slides=[...document.querySelectorAll('.slide')];let index=0,presenting=false;
const fmt=n=>new Intl.NumberFormat('es-AR',{maximumFractionDigits:0}).format(n),dec=(n,d=1)=>new Intl.NumberFormat('es-AR',{minimumFractionDigits:d,maximumFractionDigits:d}).format(n),money=n=>'$ '+fmt(n),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kpis=[['Días hábiles',fmt(T.dias_habiles),'Agosto–septiembre · lunes a viernes',''],['Dotación',fmt(T.dotacion),'Legajos asignados en el período',''],['Jornadas-persona',fmt(T.jornadas_asignadas),'Dotación asignada por cada día hábil',''],['Bultos brutos',fmt(T.bultos_brutos),'Total de bultos producidos durante el período','teal'],['Horas de Armado',fmt(T.horas_armado)+' h',T.etapas_intervalo_invalido?`${fmt(T.etapas_intervalo_invalido)} intervalos inválidos excluidos`:'Tiempo registrado en Armado','gold'],['FTE Operativo',dec(T.fte_promedio_diario),`Promedio diario del período · Total: ${dec(T.fte)} FTE`,'teal fte']];
document.getElementById('kpis').innerHTML=kpis.map(x=>`<div class="kpi ${x[3]}"><div class="kpi-label">${x[0]}</div><div class="kpi-value">${x[1]}</div><div class="kpi-sub">${x[2]}</div></div>`).join('');
const productivity=[['Bruta · Dotación',T.bultos_por_jornada_asignada,`${fmt(T.bultos_brutos)} bultos producidos ÷ ${fmt(T.jornadas_asignadas)} jornadas asignadas = ${fmt(T.bultos_por_jornada_asignada)} bultos por jornada asignada.`],['Neta · Dotación',T.bultos_por_presencia,`${fmt(T.bultos_presentes)} bultos producidos ÷ ${fmt(T.presentes_situacion_pv)} jornadas presentes = ${fmt(T.bultos_por_presencia)} bultos por jornada presente. Incluye ${fmt(T.bultos_presentes_sin_tiempo)} bultos registrados en ${fmt(T.jornadas_presentes_sin_tiempo_con_bultos)} jornadas presentes sin tiempo de Armado.`],['Por FTE operativo',T.bultos_por_fte,`${fmt(T.bultos_brutos)} bultos producidos ÷ ${dec(T.fte)} FTE acumulados = ${fmt(T.bultos_por_fte)} bultos por FTE. Un FTE equivale a 6,5 horas registradas.`]];
document.getElementById('productivity').innerHTML=productivity.map(p=>`<div class="product-card"><span>${p[0]}</span><b>${fmt(p[1])}</b><span>${p[2]}</span></div>`).join('');
document.getElementById('present-no-time-count').textContent=fmt(T.legajo_dias_presentes_sin_tiempo_armado);document.getElementById('absent-activity-count').textContent=fmt(T.legajo_dias_ausencia_con_actividad);
document.getElementById('absence-total').textContent=`${fmt(T.ausentes)} jornadas de ausencia`;
const maxAbsence=Math.max(1,...D.absence_summary.map(x=>x.cantidad));document.getElementById('absence-chart').innerHTML=D.absence_summary.map(x=>`<div class="absence-row"><div class="absence-row-head"><span>${esc(x.motivo)}</span><b>${fmt(x.cantidad)}</b></div><div class="absence-track"><i style="width:${100*x.cantidad/maxAbsence}%"></i></div></div>`).join('');
document.getElementById('present-no-time-body').innerHTML=D.present_without_armado_time.map(x=>`<tr><td>${x.fecha.slice(6,8)}/${x.fecha.slice(4,6)}/2026</td><td>${esc(x.legajo)}</td><td>${esc(x.nombre)}</td><td>${esc(x.sector)}</td><td>${fmt(x.bultos)}</td><td>${dec(x.horas_armado,2)}</td></tr>`).join('');
document.getElementById('absence-body').innerHTML=D.absence_cases.map(x=>`<tr><td>${x.fecha.slice(6,8)}/${x.fecha.slice(4,6)}/2026</td><td>${esc(x.legajo)}</td><td>${esc(x.nombre)}</td><td>${esc(x.motivo)}${x.codigo_ausentismo_pv?` (${esc(x.codigo_ausentismo_pv)})`:''}</td><td>${esc(x.observacion_pv)}</td><td>${fmt(x.bultos)}</td><td>${dec(x.horas_armado,2)}</td><td>${esc(x.actividad)}</td></tr>`).join('');
function setMode(value){presenting=value;document.body.classList.toggle('presentation',value);slides.forEach((s,i)=>s.classList.toggle('active',!value||i===index));document.getElementById('nav').style.display=value?'flex':'none';document.getElementById('report-mode').setAttribute('aria-pressed',String(!value));document.getElementById('presentation-mode').setAttribute('aria-pressed',String(value));if(value){window.scrollTo(0,0);requestAnimationFrame(()=>{slides[index].scrollTop=0;});}}
function go(n){index=Math.max(0,Math.min(slides.length-1,n));slides.forEach((s,i)=>s.classList.toggle('active',i===index));document.getElementById('slide-select').value=String(index);document.getElementById('nav-count').textContent=`${index+1} / ${slides.length}`;document.getElementById('prev').disabled=index===0;document.getElementById('next').disabled=index===slides.length-1;}
document.getElementById('slide-select').innerHTML=slides.map((s,i)=>`<option value="${i}">${esc(s.dataset.title)}</option>`).join('');document.getElementById('slide-select').onchange=e=>go(Number(e.target.value));document.getElementById('prev').onclick=()=>go(index-1);document.getElementById('next').onclick=()=>go(index+1);document.getElementById('report-mode').onclick=()=>setMode(false);document.getElementById('presentation-mode').onclick=()=>setMode(true);document.getElementById('fullscreen-toggle').onclick=()=>document.body.classList.toggle('fullscreen');document.getElementById('print-button').onclick=()=>window.print();go(0);
document.addEventListener('keydown',e=>{if(document.getElementById('details-modal').classList.contains('open')){if(e.key==='Escape')closeModal();return}if(e.key==='ArrowRight'&&presenting)go(index+1);if(e.key==='ArrowLeft'&&presenting)go(index-1);if(e.key==='Escape'&&presenting)setMode(false)});
function closeModal(){document.getElementById('details-modal').classList.remove('open')}document.getElementById('open-details').onclick=()=>document.getElementById('details-modal').classList.add('open');document.getElementById('close-modal').onclick=closeModal;document.getElementById('details-modal').onclick=e=>{if(e.target.id==='details-modal')closeModal()};
document.querySelectorAll('.tab-button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab-button').forEach(x=>x.setAttribute('aria-pressed','false'));b.setAttribute('aria-pressed','true');document.querySelectorAll('.modal-body').forEach(x=>x.hidden=x.id!==b.dataset.tab)});
const legacyEncoded=document.getElementById('legacy-report-html').textContent.trim(),legacyBytes=Uint8Array.from(atob(legacyEncoded),c=>c.charCodeAt(0)),legacyHtml=new TextDecoder('utf-8').decode(legacyBytes),legacyFrame=document.getElementById('legacy-economic-frame');
legacyFrame.addEventListener('load',()=>{const d=legacyFrame.contentDocument,target=d?.getElementById('secos-armado');if(!d||!target)return;const style=d.createElement('style');style.textContent='html,body{width:100%!important;height:100%!important;min-height:0!important;overflow:hidden!important;background:#fff!important}*,*:before,*:after{box-sizing:border-box!important}body{margin:0!important} .single-scope-banner,.report-toolbar,.presentation-nav,.deck-progress{display:none!important}main{display:block!important;width:100%!important;height:100%!important;margin:0!important;padding:0!important;max-width:none!important;overflow:hidden!important}main>.sheet:not(#secos-armado){display:none!important}#secos-armado{display:flex!important;flex-direction:column!important;position:relative!important;width:100%!important;max-width:none!important;height:100%!important;min-height:0!important;margin:0!important;padding:12px 18px 8px!important;border:0!important;border-radius:0!important;box-shadow:none!important;overflow:hidden!important}#secos-armado .compact-heading{flex:none!important;margin-bottom:6px!important}#secos-armado .integrated-band{flex:none!important;margin:0 0 6px!important}#secos-armado .integrated-totals{display:grid!important;grid-template-columns:repeat(7,minmax(0,1fr))!important;flex:none!important;gap:9px!important;margin:0 0 7px!important}#secos-armado .integrated-totals>span{min-height:64px!important;padding:7px 10px!important}#secos-armado .integrated-totals b{font-size:21px!important;margin-top:3px!important}#secos-armado .integrated-top{display:grid!important;grid-template-columns:minmax(0,1fr) minmax(0,1fr)!important;gap:12px!important;flex:0 0 auto!important;height:clamp(210px,32vh,248px)!important;min-height:0!important;margin:0 0 7px!important}#secos-armado .integrated-group-panel,#secos-armado .integrated-participation{min-width:0!important;min-height:0!important;padding:10px!important}#secos-armado .integrated-group-panel>h3,#secos-armado .integrated-participation>h3{margin:0 0 6px!important}#secos-armado .integrated-access>b{display:none!important}#secos-armado .group-zone-metrics{gap:3px 6px!important;margin:4px 0!important}#secos-armado .group-zone-metrics span{padding:3px 5px!important;font-size:11px!important}#secos-armado .group-zone-metrics strong{font-size:13px!important;margin-top:2px!important}#secos-armado .group-modal-note{display:block!important;margin:4px 0!important;font-size:10px!important;line-height:1.2!important}#secos-armado .integrated-participation .pilot-bars{height:142px!important;margin:12px 0 0!important}#secos-armado .integrated-participation .pilot-bar b{margin:3px 0!important}#secos-armado .integrated-participation .pilot-bar span{margin:3px 0!important}#secos-armado .integrated-participation .participation-note{margin:3px 0 0!important;font-size:10px!important}#secos-armado .integrated-band.band-impact{flex:0 0 auto!important;min-height:0!important}#secos-armado .integrated-band.band-impact .band-title{margin-bottom:3px!important}#secos-armado .impact-modal-launchers{flex:0 0 auto!important;min-height:64px!important;align-items:stretch!important;margin:3px 0!important;gap:10px!important}#secos-armado .impact-modal-launchers>button{justify-content:center!important;padding:7px 12px!important}#secos-armado .impact-modal-launchers span{font-size:13px!important}#secos-armado .impact-modal-launchers b{font-size:17px!important}#secos-armado .pilot-note{flex:none!important;margin:3px 0 0!important;font-size:9px!important;line-height:1.1!important}#secos-armado{overflow-x:hidden!important}@media(max-width:1100px){#secos-armado .integrated-totals{grid-template-columns:repeat(3,minmax(0,1fr))!important}}@media(max-width:650px){#secos-armado .integrated-totals{grid-template-columns:repeat(2,minmax(0,1fr))!important}}@media(max-height:700px){#secos-armado .integrated-top{height:clamp(196px,34vh,225px)!important}#secos-armado .integrated-participation .pilot-bars{height:135px!important;margin-top:10px!important}#secos-armado .integrated-totals>span{min-height:58px!important;padding:5px 8px!important}#secos-armado .integrated-band{margin-bottom:4px!important}#secos-armado .impact-modal-launchers{min-height:54px!important}}';d.head.appendChild(style);target.scrollTop=0;});legacyFrame.srcdoc=legacyHtml;
</script></body></html>'''
    html_text = template.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    html_text = html_text.replace("__LEGACY_REPORT_B64__", previous_impact_b64)
    HTML_OUT.write_text(html_text, encoding="utf-8")
    print(json.dumps({"html": str(HTML_OUT), "json": str(JSON_OUT), "csv": str(CSV_OUT), "totals": totals, "zones": zone_data, "absence_summary": data["absence_summary"], "absence_with_activity": absence_activity_count, "present_without_time": len(present_without_time)}, ensure_ascii=False, indent=2))
    db.close()


if __name__ == "__main__":
    main()
