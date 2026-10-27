"""Build a read-only interactive deck with gross productivity and budget-neutral award impact.

The scenario preserves the current historical pool per function, keeps current
thresholds, and proportionally redistributes the pool to group+polivalency and
individual payments. No parameters or internal caches are written.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from html import escape
import base64
import gzip
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generar_informe_gerencial_umbrales as impact_renderer
import gerencial_umbrales_compacto as compact_renderer
import gerencial_umbrales_piloto as pilot_renderer

OUT = ROOT / "outputs"
HTML_OUT = OUT / "presentacion_productividad_y_premio_secos_armado_piloto_20261027.html"
JSON_OUT = HTML_OUT.with_suffix(".json")
PAYROLL_SOURCE = OUT / "presentacion_productividad_y_premio_por_funcion_agosto_septiembre_2026.html"
BASELINE_SOURCE = OUT / "presentacion_base_productividad_armado_secos_agosto_septiembre_2026.json"
GROUP_TARGET = 0.60  # incluye polivalencia


def allocate_proportionally(entries: list[tuple[dict, str, int]], target: int) -> list[int]:
    """Allocate integer centavos proportionally, preserving the exact target."""
    total = sum(max(value, 0) for _, _, value in entries)
    if target <= 0 or total <= 0:
        return [0] * len(entries)
    exact = [max(value, 0) * target / total for _, _, value in entries]
    result = [int(value) for value in exact]
    remainder = target - sum(result)
    order = sorted(range(len(entries)), key=lambda i: (exact[i] - result[i], -i), reverse=True)
    for i in order[:remainder]:
        result[i] += 1
    return result


def apply_budget_neutral_scenario(report: dict) -> list[dict]:
    by_id = {profile["id"]: profile for profile in report["perfiles"]}
    summaries = []
    for ident, title, _subtitle, profile_numbers in compact_renderer.PAGES:
        profiles = [by_id[f"perfil-{number}"] for number in profile_numbers]
        people_days = [(profile, person, day) for profile in profiles
                       for person in profile.get("piloto_legajos", [])
                       for day in person.get("dias", [])]
        actual_pool = sum(profile["actual_centavos"] for profile in profiles)
        current_group_entries = [(day, "grupal", int(day.get("grupal") or 0))
                                 for _, _, day in people_days]
        current_poly_entries = [(day, "polivalencia", int(day.get("polivalencia") or 0))
                                for _, _, day in people_days]
        current_ind_entries = [(day, "individual", int(day.get("individual") or 0))
                               for _, _, day in people_days]
        group_entries = [entry for entry in current_group_entries + current_poly_entries if entry[2] > 0]
        individual_entries = [entry for entry in current_ind_entries if entry[2] > 0]
        current_group = sum(entry[2] for entry in group_entries)
        current_individual = sum(entry[2] for entry in individual_entries)

        target_group = round(actual_pool * GROUP_TARGET)
        target_individual = actual_pool - target_group
        exception = ""
        # Do not invent a group award on days where the current threshold was
        # not achieved. If one payment component has no eligible events, move
        # the full pool to the component that does have events and disclose it.
        if target_group and not group_entries and individual_entries:
            target_group, target_individual = 0, actual_pool
            exception = "Reparto 60/40 no alcanzable: con el umbral vigente no hay jornadas con pago grupal. Se mantiene la bolsa en el componente individual; no se crean pagos grupales." 
        elif target_individual and not individual_entries and group_entries:
            target_group, target_individual = actual_pool, 0
            exception = "Reparto 60/40 no alcanzable: con la escala vigente no hay jornadas con pago individual. Se mantiene la bolsa en el componente grupal/polivalencia; no se crean pagos individuales." 
        elif actual_pool and not group_entries and not individual_entries:
            exception = "No hay pagos nuevos observados para redistribuir desde la base actual; el impacto no es estimable con estos datos." 

        group_targets = allocate_proportionally(group_entries, target_group)
        individual_targets = allocate_proportionally(individual_entries, target_individual)
        for (row, field, _), amount in zip(group_entries, group_targets):
            row[field] = amount
        for (row, field, _), amount in zip(individual_entries, individual_targets):
            row[field] = amount
        # Remove values from zero-valued entries too, for deterministic JSON.
        for _, _, day in people_days:
            if day.get("grupal", 0) == 0:
                day["grupal"] = 0
            if day.get("individual", 0) == 0:
                day["individual"] = 0
            if day.get("polivalencia", 0) == 0:
                day["polivalencia"] = 0

        group_factor = target_group / current_group if current_group else 0
        individual_factor = target_individual / current_individual if current_individual else 0
        for profile in profiles:
            profile["premio_grupal"] = round(profile["premio_grupal"] * group_factor, 2)
            profile["escala_individual"] = [dict(scale, premio=round(scale["premio"] * individual_factor, 2))
                                           for scale in profile["escala_individual"]]
            new_values = []
            for person in profile.get("piloto_legajos", []):
                for day in person.get("dias", []):
                    day["grupal_potencial"] = int(round(day.get("grupal_potencial", 0) * group_factor))
                    new_values.append(day["grupal"] + day["individual"] + day["polivalencia"])
            profile["nuevo_centavos"] = sum(new_values)
            deltas = []
            for person in profile.get("piloto_legajos", []):
                actual = sum(day["actual"] for day in person.get("dias", []))
                proposed = sum(day["grupal"] + day["individual"] + day["polivalencia"]
                               for day in person.get("dias", []))
                deltas.append(proposed - actual)
            profile["mas"] = sum(value > 0 for value in deltas)
            profile["menos"] = sum(value < 0 for value in deltas)
            profile["igual"] = sum(value == 0 for value in deltas)
            profile["personas"] = len(deltas)

        new_pool = sum(profile["nuevo_centavos"] for profile in profiles)
        paid_group = sum(day.get("grupal", 0) for _, _, day in people_days)
        paid_poly = sum(day.get("polivalencia", 0) for _, _, day in people_days)
        paid_individual = sum(day.get("individual", 0) for _, _, day in people_days)
        if new_pool != actual_pool:
            raise ValueError(f"La bolsa de {title} no concilia: actual={actual_pool}, propuesta={new_pool}")
        summaries.append({
            "id": ident, "title": title, "actual_centavos": actual_pool,
            "propuesto_centavos": new_pool, "grupal_centavos": paid_group,
            "polivalencia_centavos": paid_poly, "individual_centavos": paid_individual,
            "grupal_mas_polivalencia_pct": 100 * (paid_group + paid_poly) / new_pool if new_pool else 0,
            "individual_pct": 100 * paid_individual / new_pool if new_pool else 0,
            "excepcion": exception,
        })
    return summaries


def productivity_data(profiles: list[dict], days: int) -> dict:
    rows = [(profile, person, day) for profile in profiles
            for person in profile.get("piloto_legajos", []) for day in person.get("dias", [])]
    dates = sorted({day["fecha"] for _, _, day in rows})
    legajos = {str(person["legajo"]) for profile in profiles for person in profile.get("piloto_legajos", [])}
    present_rows = [(profile, person, day) for profile, person, day in rows
                    if str(day.get("asistencia", "")).strip().casefold() == "presente"]
    nonpresent_units = [(profile, person, day) for profile, person, day in rows
                        if str(day.get("asistencia", "")).strip().casefold() != "presente"
                        and float(day.get("uc") or 0) > 0]
    gross_units = sum(float(day.get("uc") or 0) for _, _, day in rows)
    present_units = sum(float(day.get("uc") or 0) for _, _, day in present_rows)
    daily_units = defaultdict(float)
    daily_people = defaultdict(set)
    daily_present = defaultdict(set)
    for _, person, day in rows:
        daily_units[day["fecha"]] += float(day.get("uc") or 0)
        daily_people[day["fecha"]].add(str(person["legajo"]))
        if str(day.get("asistencia", "")).strip().casefold() == "presente":
            daily_present[day["fecha"]].add(str(person["legajo"]))
    return {
        "rows": rows, "dates": dates, "legajos": len(legajos), "jornadas": len(rows),
        "presentes": len(present_rows), "no_presentes": len(rows) - len(present_rows),
        "brutos": gross_units, "unidades_presentes": present_units,
        "presentes_sin_unidad": sum(float(day.get("uc") or 0) <= 0 for _, _, day in present_rows),
        "unidades_no_presente": sum(float(day.get("uc") or 0) for _, _, day in nonpresent_units),
        "jornadas_no_presente_con_unidad": len(nonpresent_units),
        "produccion_diaria": [daily_units[date] for date in dates],
        "personas_diarias": [len(daily_people[date]) for date in dates],
        "presentes_diarios": [len(daily_present[date]) for date in dates],
        "dias_calendario": days,
    }


def verified_armado_fte(report: dict, data: dict) -> dict | None:
    """Reuse the previously reconciled Armado Secos FTE basis if it matches."""
    if not BASELINE_SOURCE.exists():
        return None
    baseline = json.loads(BASELINE_SOURCE.read_text(encoding="utf-8"))
    totals = baseline.get("totals", {})
    same_snapshot = totals.get("fecha_calculo") == report.get("cache_grupal")
    same_scope = (int(totals.get("dotacion", -1)) == data["legajos"]
                  and int(totals.get("jornadas_asignadas", -1)) == data["jornadas"]
                  and int(totals.get("dias_habiles", -1)) == report["dias"])
    same_production = abs(float(totals.get("bultos_brutos", 0)) - data["brutos"]) < 1
    if not (same_snapshot and same_scope and same_production):
        return None
    return totals


def fmt(value: float, decimals=0) -> str:
    return impact_renderer.number(value, decimals)


def base_sheet(report: dict, ident: str, title: str, subtitle: str,
               profiles: list[dict]) -> str:
    data = productivity_data(profiles, report["dias"])
    fte = verified_armado_fte(report, data) if ident == "secos-armado" else None
    if fte:
        # The attendance denominator is sourced from the PV_DIA_LABORAL
        # reconciliation in the validated Armado Secos base sheet.
        data["presentes"] = int(fte["presentes_situacion_pv"])
        data["unidades_presentes"] = float(fte["bultos_presentes"])
        data["presentes_sin_tiempo"] = int(fte["legajo_dias_presentes_sin_tiempo_armado"])
        # Attendance status in the reconciled baseline is authoritative here;
        # don't surface cache-level status mismatches as absence conflicts.
        data["jornadas_no_presente_con_unidad"] = int(fte["legajo_dias_ausencia_con_actividad"])
        data["unidades_no_presente"] = 0.0
    unit = profiles[0]["unidad"] if profiles else "unidades"
    if any(profile["unidad"] != unit for profile in profiles):
        raise ValueError(f"Unidades diferentes dentro de {title}; no se consolidan automáticamente.")
    average_roster = data["jornadas"] / report["dias"] if report["dias"] else 0
    gross_per_roster = data["brutos"] / data["jornadas"] if data["jornadas"] else 0
    net_per_present = data["unidades_presentes"] / data["presentes"] if data["presentes"] else 0
    peak = max(data["produccion_diaria"], default=0) or 1
    bars = "".join(
        f'<div class="gross-day" title="{escape(date[6:8]+"/"+date[4:6])}: {fmt(amount,1)} {escape(unit)}; '
        f'{data["personas_diarias"][index]} legajos asignados">'
        f'<b>{fmt(amount,0)}</b><i style="height:{max(2,round(amount/peak*100))}%;"></i>'
        f'<span>{date[6:8]}</span></div>'
        for index, (date, amount) in enumerate(zip(data["dates"], data["produccion_diaria"]))
    )
    slices = (f'<section class="gross-breakdown"><h3>Composición consolidada · Secos · Armado · Zona 1 + Zona 2</h3><div class="table-wrap"><table>'
              f'<thead><tr><th>Alcance</th><th>Legajos</th><th>Jornadas-persona</th>'
              f'<th>Bultos brutos</th><th>Bultos / jornada</th></tr></thead><tbody>'
              f'<tr><td>Función unificada</td><td>{fmt(data["legajos"])}</td><td>{fmt(data["jornadas"])}</td>'
              f'<td>{fmt(fte["bultos_brutos"] if fte else data["brutos"],0)}</td>'
              f'<td>{fmt(fte["bultos_por_jornada_asignada"] if fte else gross_per_roster,1)}</td></tr>'
              f'</tbody></table></div></section>') if len(profiles) > 1 else ""
    missing_base = [p for p in profiles if not p.get("piloto_legajos")]
    gap_note = (" No hay filas de nómina/producción en cache para: " + ", ".join(escape(p["sector"]) for p in missing_base) + ".") if missing_base else ""
    out_of_presence_note = (f'<p class="gross-reconcile">Hay {fmt(data["jornadas_no_presente_con_unidad"])} jornadas con unidades registradas y situación distinta de Presente; '
                            f'suman {fmt(data["unidades_no_presente"],0)} {escape(unit)}. Se muestran en Bruta y no entran en Neta · Presencia.</p>') if data["jornadas_no_presente_con_unidad"] else ""
    if fte:
        kpis = f'''<article class="gross-kpi"><span>Días hábiles</span><strong>{fmt(report["dias"])}</strong><small>Agosto–septiembre · lunes a viernes</small></article>
        <article class="gross-kpi"><span>Dotación</span><strong>{fmt(data["legajos"])}</strong><small>Legajos asignados en el período</small></article>
        <article class="gross-kpi"><span>Jornadas-persona</span><strong>{fmt(data["jornadas"])}</strong><small>Dotación asignada × días hábiles</small></article>
        <article class="gross-kpi gross-volume"><span>Bultos brutos</span><strong>{fmt(fte["bultos_brutos"])}</strong><small>Promedio diario {fmt(fte["bultos_promedio_diario"])}</small></article>
        <article class="gross-kpi gross-hours"><span>Horas de armado</span><strong>{fmt(fte["horas_armado"],0)} h</strong><small>{fmt(fte["etapas_intervalo_invalido"])} intervalos inválidos excluidos</small></article>
        <article class="gross-kpi gross-fte"><span>FTE operativo</span><strong>{fmt(fte["fte_promedio_diario"],1)}</strong><small>Promedio diario · Total período: {fmt(fte["fte"],1)} FTE</small></article>
        '''
        rates = f'''<section class="gross-rates gross-rates-three"><div><span>Bruta · Dotación</span><strong>{fmt(fte["bultos_por_jornada_asignada"],0)} <small>bultos por jornada-persona</small></strong><p>{fmt(fte["bultos_brutos"])} bultos ÷ {fmt(data["jornadas"])} jornadas-persona asignadas.</p></div>
        <div><span>Neta · Presencia</span><strong>{fmt(fte["bultos_por_presencia"],0)} <small>bultos por jornada presente</small></strong><p>{fmt(fte["bultos_presentes"])} bultos Presente ÷ {fmt(fte["presentes_situacion_pv"])} jornadas-persona Presente.</p></div>
        <div><span>Producción por FTE</span><strong>{fmt(fte["bultos_por_fte"],0)} <small>bultos por FTE del período</small></strong><p>{fmt(fte["bultos_brutos"])} bultos ÷ {fmt(fte["fte"],1)} FTE.</p></div>
        </section>'''
        source_note = f'Las horas corresponden a etapas PICKIN de división 1. Se excluyeron {fmt(fte["etapas_intervalo_invalido"])} intervalos inválidos; total de horas y FTE conciliado con el cache de duración. FTE = horas registradas ÷ {fmt(fte["horas_estandar"],1)} horas estándar.'
    else:
        kpis = f'''<article class="gross-kpi"><span>Dotación del legajero</span><strong>{fmt(data["legajos"])}</strong><small>Legajos actuales asociados a la función</small></article>
        <article class="gross-kpi"><span>Jornadas-persona</span><strong>{fmt(data["jornadas"])}</strong><small>{fmt(average_roster,1)} legajos por día en promedio</small></article>
        <article class="gross-kpi gross-volume"><span>Unidades brutas</span><strong>{fmt(data["brutos"],0)}</strong><small>{escape(unit)} sumadas en el período · promedio diario {fmt(data["brutos"]/report["dias"],0)}</small></article>
        <article class="gross-kpi gross-attendance"><span>Presencias en PV</span><strong>{fmt(data["presentes"])}</strong><small>{fmt(data["presentes"]/report["dias"],1)} presentes por día en promedio</small></article>'''
        rates = f'''<section class="gross-rates"><div><span>Bruta · Dotación</span><strong>{fmt(gross_per_roster,1)} <small>{escape(unit)} por jornada-persona asignada</small></strong><p>{fmt(data["brutos"],0)} {escape(unit)} ÷ {fmt(data["jornadas"])} jornadas-persona del legajero.</p></div>
        <div><span>Neta · Presencia</span><strong>{fmt(net_per_present,1)} <small>{escape(unit)} por jornada presente</small></strong><p>{fmt(data["unidades_presentes"],0)} {escape(unit)} en registros Presente ÷ {fmt(data["presentes"])} jornadas-persona Presente.</p></div></section>'''
        source_note = 'Horas/FTE no disponibles para esta función en el alcance de esta hoja.'
    return f'''<section class="sheet compact-sheet gross-sheet {'productivity-base-sheet' if fte else ''}" id="base-{escape(ident)}">
      <div class="compact-heading"><div><span class="eyebrow">Productividad bruta · {escape(subtitle)}</span><h2>{escape(title)}</h2></div><span class="compact-period">Agosto–septiembre 2026 · {report["dias"]} días hábiles</span></div>
      <div class="gross-kpis {'gross-kpis-six' if fte else ''}">{kpis}</div>
      {rates}
      {out_of_presence_note}
      <section class="gross-chart"><header><div><span>Producción por día</span><small>Unidades brutas atribuidas a la función en el cache PV</small></div><b>{data["dates"][0][6:8]+"/"+data["dates"][0][4:6] if data["dates"] else "—"} — {data["dates"][-1][6:8]+"/"+data["dates"][-1][4:6] if data["dates"] else "—"}</b></header><div class="gross-bars">{bars or '<p>Sin registros de nómina para este alcance.</p>'}</div></section>
      {slices}
      <aside class="gross-note"><b>Cómo leer esta hoja</b><span>Bruta suma las unidades registradas en todos los legajo-días del alcance. Neta · Presencia divide las unidades de legajos con situación Presente por sus jornadas-persona Presente; no aplica premios ni polivalencia. La asignación de legajo a función sigue el legajero vigente. {escape(source_note)}{gap_note}</span></aside>
      <p class="compact-footnote">Fuente de producción: cache PV del sistema interno de Productividad. Esta hoja resume unidades; no valida la extracción upstream ni consulta el WMS crudo.</p>
    </section>'''


def custom_slides(report: dict, payroll_details: dict | None = None) -> str:
    by_id = {profile["id"]: profile for profile in report["perfiles"]}
    cover = compact_renderer.cover(report, fmt)
    cover = cover.replace('<strong>2</strong><span>perfiles analizados</span><small>Ver alcance</small>',
                          '<strong>1</strong><span>función · 2 zonas</span><small>Ver alcance</small>')
    out = [cover]
    for ident, title, subtitle, profile_numbers in compact_renderer.PAGES:
        profiles = [by_id[f"perfil-{number}"] for number in profile_numbers]
        out.append(base_sheet(report, ident, title, subtitle, profiles))
        impact = pilot_renderer.integrated(report, profiles, ident, title, fmt,
                                           include_payroll=payroll_details is not None,
                                           payroll_details=payroll_details)
        summary = next(item for item in report["escenarios_bolsa"] if item["id"] == ident)
        if summary["excepcion"]:
            note = f'<aside class="scenario-note scenario-exception"><b>Distribución condicionada</b><span>{escape(summary["excepcion"])}</span></aside>'
        else:
            note = '<aside class="scenario-note"><b>Escenario presupuestariamente neutro</b><span>Conserva la bolsa histórica de esta función, mantiene los umbrales vigentes y reparte 60% entre grupal + polivalencia y 40% individual. Importes diarios redistribuidos proporcionalmente; simulación, no aplicada.</span></aside>'
        impact = impact.replace('<section class="integrated-band band-economic">', note + '<section class="integrated-band band-economic">', 1)
        out.append(impact)
    return "".join(out)


def cached_payroll_payload() -> dict | None:
    """Reuse the compressed detail from a prior output when only layout changes."""
    if not PAYROLL_SOURCE.exists():
        return None
    match = re.search(
        r'<script id="payroll-report-data" type="application/x-gzip-base64">\s*(.*?)\s*</script>',
        PAYROLL_SOURCE.read_text(encoding="utf-8"), flags=re.S)
    if not match:
        return None
    return json.loads(gzip.decompress(base64.b64decode(match.group(1))).decode("utf-8"))


def main() -> None:
    OUT.mkdir(exist_ok=True)
    report = impact_renderer.analyze("2026-08-01", "2026-09-30")
    all_pages = compact_renderer.PAGES
    compact_renderer.PAGES = [all_pages[0]]  # pilot only: Secos · Armado, both zones
    report["perfiles"] = [profile for profile in report["perfiles"]
                          if profile["id"] in {"perfil-1", "perfil-5"}]
    report["escenarios_bolsa"] = apply_budget_neutral_scenario(report)
    impact_renderer.attach_polivalency_summaries(report)

    # render() imports compact.slides under a module-level alias, so replace
    # that binding while composing this one-off deck.
    original_slides = impact_renderer.compact_slides
    payroll = cached_payroll_payload()
    if payroll is not None:
        payroll = {key: value for key, value in payroll.items() if key in {"perfil-1", "perfil-5"}}
    impact_renderer.compact_slides = lambda *_args, **_kwargs: custom_slides(report, payroll)
    try:
        if payroll is None:
            payroll = impact_renderer.attach_payroll_activity(report)
        impact_renderer.compact_slides = lambda *_args, **_kwargs: custom_slides(report, payroll)
        html = impact_renderer.render(report, compact=True, payroll_details=payroll)
    finally:
        impact_renderer.compact_slides = original_slides
        compact_renderer.PAGES = all_pages

    # The fitted presentation canvas is 2000px wide by default. Use a 1600px
    # logical canvas for this one impact slide so it fills the viewport and its
    # larger typography remains legible after fitting.
    html = html.replace(
        "const logicalWidth = (slide.classList.contains('integrated-sheet') || slide.classList.contains('audit-sheet') || slide.classList.contains('productivity-base-sheet')) ? 2000 : 1280;",
        "const logicalWidth = slide.classList.contains('integrated-sheet') ? 1600 : ((slide.classList.contains('audit-sheet') || slide.classList.contains('productivity-base-sheet')) ? 2000 : 1280);",
        1,
    )
    html = html.replace(
        "const scale = Math.min((width - 2) / logicalWidth, (height - 2) / naturalHeight);\n      canvas.style.height = `${naturalHeight}px`;\n      canvas.style.transform = `scale(${scale})`;\n      canvas.style.left = `${Math.max(0, (width - logicalWidth * scale) / 2)}px`;\n      canvas.style.top = `${Math.max(0, (height - naturalHeight * scale) / 2)}px`;",
        "const widthScale = (width - 2) / logicalWidth;\n      const impactPilot = !paper && slide.classList.contains('integrated-sheet');\n      const scale = impactPilot ? widthScale : Math.min(widthScale, (height - 2) / naturalHeight);\n      canvas.style.height = `${naturalHeight}px`;\n      canvas.style.transform = `scale(${scale})`;\n      canvas.style.left = `${Math.max(0, (width - logicalWidth * scale) / 2)}px`;\n      canvas.style.top = impactPilot ? '0px' : `${Math.max(0, (height - naturalHeight * scale) / 2)}px`;",
        1,
    )

    css = r'''
.gross-sheet{display:flex;flex-direction:column;gap:16px;min-height:calc(100dvh - 120px);border-top:6px solid #168b83}
main{width:calc(100% - 40px);max-width:1800px;margin-left:auto;margin-right:auto}
/* Keep the impact slide within the fitted canvas, including Presentation mode. */
.integrated-sheet{width:100%!important;max-width:none!important;margin:0!important}
body.presentation .integrated-sheet{width:100%!important;height:100%!important;margin:0!important;overflow-x:hidden!important;overflow-y:auto!important;scrollbar-width:thin}
.gross-sheet .compact-heading{margin-bottom:0}
.gross-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.gross-kpi{display:flex;flex-direction:column;justify-content:center;min-height:108px;padding:14px 17px;border-radius:9px;border-top:4px solid #4389a8;background:#eff5f8}
.gross-kpi>span,.gross-rates>div>span{font-size:12px;color:#587286;font-weight:700;letter-spacing:.03em}
.gross-kpi strong{font-size:31px;line-height:1.1;margin:5px 0;color:#173d54;font-variant-numeric:tabular-nums}
.gross-kpi small{font-size:11px;color:#60798a;line-height:1.3}
.gross-kpi.gross-volume{border-color:#138a87;background:#edf7f5}.gross-kpi.gross-volume strong{color:#138a87}
.gross-kpi.gross-attendance{border-color:#d3a13c;background:#fbf7ec}
.gross-kpis-six{grid-template-columns:repeat(6,minmax(0,1fr))}
.gross-hours{border-color:#d3a13c;background:#fbf7ec}.gross-fte{border-color:#138a87;background:#edf7f5}.gross-fte strong{font-size:38px;color:#138a87}
.gross-rates{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.gross-rates-three{grid-template-columns:repeat(3,minmax(0,1fr))}
.gross-rates>div{padding:14px 18px;border-radius:9px;background:#f6f9fa;border:1px solid #dce7eb;border-left:5px solid #4389a8}
.gross-rates>div:nth-child(2){border-left-color:#138a87}
.gross-rates strong{display:block;margin:4px 0;font-size:26px;color:#173d54}
.gross-rates strong small{font-size:14px;font-weight:600;color:#60798a}
.gross-rates p{margin:0;font-size:12px;color:#60798a}
.gross-chart{padding:12px 16px 9px;border:1px solid #dce7eb;border-radius:9px;background:#f7fafb}
.gross-chart>header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px}
.gross-chart>header span{display:block;font-weight:800;font-size:14px}.gross-chart>header small{font-size:11px;color:#60798a}.gross-chart>header>b{font-size:11px;color:#60798a}
.gross-bars{height:142px;display:flex;align-items:end;gap:3px;overflow:hidden;border-bottom:1px solid #becdd5;padding:4px 1px 0}
.gross-day{height:100%;flex:1;min-width:3px;display:flex;flex-direction:column;align-items:center;justify-content:end;position:relative}
.gross-day>b{font-size:8px;line-height:1;white-space:nowrap;color:#456276;opacity:0;position:absolute;top:0;z-index:1;background:#fff;padding:2px;border-radius:3px}
.gross-day:hover>b{opacity:1}.gross-day>i{width:min(100%,16px);min-height:2px;background:#168b83;border-radius:3px 3px 0 0}
.gross-day:nth-child(3n)>i{background:#4389a8}.gross-day:nth-child(5n)>i{background:#d3a13c}
.gross-day>span{font-size:8px;color:#60798a;line-height:14px}
.gross-breakdown{padding:8px 13px;border:1px solid #dce7eb;border-radius:9px;background:white}
.gross-breakdown h3{font-size:13px;margin:0 0 5px}.gross-breakdown table{font-size:11px}.gross-breakdown th,.gross-breakdown td{padding:5px 8px}
.gross-reconcile{margin:0;padding:8px 11px;border-left:4px solid #d3a13c;background:#fbf7ec;color:#67532c;font-size:11px}
.gross-note{display:flex;gap:12px;padding:10px 13px;background:#eef6f6;border-left:4px solid #168b83;border-radius:5px;font-size:11px;color:#456276;line-height:1.4}
.gross-note b{flex:0 0 auto;color:#173d54}
.gross-sheet .compact-footnote{margin:0;font-size:10px}
.scenario-note{display:flex;gap:12px;align-items:center;margin:-7px 0 12px;padding:10px 14px;border-radius:7px;background:#eaf5f2;border-left:4px solid #3c9478;color:#33586a;font-size:12px;line-height:1.35}
.scenario-note b{flex:0 0 auto;color:#176b60}.scenario-exception{background:#fff6e9;border-left-color:#d3a13c}.scenario-exception b{color:#8b6216}
.integrated-sheet .scenario-note{margin-top:-4px}
.integrated-sheet .compact-heading h2{font-size:30px!important;line-height:1.2}
.integrated-sheet .compact-heading .eyebrow{font-size:11px!important}
.integrated-sheet .scenario-note{font-size:12px!important;padding:10px 14px;margin:0 0 12px}
.integrated-sheet .scenario-note b{font-size:12px!important}
.integrated-sheet .band-title{font-size:12px!important}
.integrated-sheet .band-title>span{font-size:16px!important}
.integrated-sheet .integrated-totals{grid-template-columns:repeat(7,minmax(0,1fr));gap:10px}
.integrated-sheet .integrated-totals>span{font-size:12px!important;padding:10px 14px;min-height:80px}
.integrated-sheet .integrated-totals b{font-size:21px!important;line-height:1.2}
.integrated-sheet .integrated-totals .metric-title{font-size:12px!important;line-height:1.3}
.integrated-sheet .integrated-group-panel,.integrated-sheet .integrated-participation{padding:14px 18px}
.integrated-sheet .integrated-group-panel>h3,.integrated-sheet .integrated-participation>h3{font-size:16px!important;margin-bottom:10px}
.integrated-sheet .integrated-access{padding:7px 0}
.integrated-sheet .integrated-access>b{font-size:14px!important}
.integrated-sheet .integrated-access span{font-size:11px!important}
.integrated-sheet .integrated-access strong{font-size:17px!important;line-height:1.2}
.integrated-sheet .integrated-access button{font-size:10px!important;padding:4px 7px}
.integrated-sheet .integrated-participation .pilot-bars{height:155px}
.integrated-sheet .integrated-participation .pilot-bar b{font-size:11px!important}
.integrated-sheet .integrated-participation .pilot-bar span{font-size:10px!important;min-height:24px}
.integrated-sheet .integrated-participation p{font-size:11px!important;line-height:1.35}
.integrated-sheet .integrated-rankings{gap:26px}
.integrated-sheet .integrated-rankings h3{font-size:14px!important;margin-bottom:8px}
.integrated-sheet .integrated-case{grid-template-columns:58px minmax(0,1fr) 100px;gap:8px;padding:10px 0 10px 10px}
.integrated-sheet .integrated-case b,.integrated-sheet .integrated-case strong{font-size:13px!important}
.integrated-sheet .integrated-case p{font-size:12px!important;line-height:1.25}
.integrated-sheet .pilot-note{font-size:10px}
@media(max-width:1100px){.gross-kpis-seven{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:900px){.gross-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.gross-bars{gap:1px}.gross-kpi{min-height:90px}}
@media(max-width:600px){.gross-rates{grid-template-columns:1fr}.gross-kpi strong{font-size:24px}.gross-sheet{min-height:0}.gross-chart{padding:8px}.gross-day>b{display:none}}
@media print{.gross-sheet{min-height:0;break-inside:avoid}.scenario-note{break-inside:avoid}}
'''
    html = html.replace("</style>", css + "</style>", 1)
    html = html.replace("<title>Premio grupal · Acceso al incentivo y umbrales</title>",
                        "<title>Productividad bruta e impacto del premio · Agosto–septiembre 2026</title>")
    html = html.replace("<div class=\"eyebrow\">Propuesta de premios · Estudio gerencial</div>",
                        "<div class=\"eyebrow\">Base productiva e impacto económico · Estudio para validación gerencial</div>")
    html = html.replace("<h1>Productividad<br>y acceso al<br><span>premio grupal</span></h1>",
                        "<h1>Productividad bruta<br>y distribución<br><span>del premio</span></h1>")
    html = html.replace("<p class=\"cover-deck\">El objetivo elegido define cuántos días<br>el equipo alcanza el incentivo.</p>",
                        "<p class=\"cover-deck\">Una base de unidades por función y el impacto<br>de redistribuir la bolsa sin cambiar umbrales.</p>")
    html = html.replace("<span>Umbral vigente y alternativas</span>", "<span>Umbral vigente, sin modificaciones</span>")
    html = html.replace("<span>Grupal + individual + polivalencia</span>", "<span>Bolsa actual con reparto simulado</span>")
    html = html.replace("<h2>17 perfiles analizados</h2>", "<h2>1 función · 2 zonas</h2>")
    html = html.replace("<small>El 75% es una referencia", "<small>El 75% es una referencia")

    # The generic cover's exploratory note is replaced with precise scenario limits.
    html = re.sub(r'<details class="visual-details">.*?</details>',
                  '<details class="visual-details"><summary>Supuestos del escenario</summary><p>Período agosto–septiembre 2026, de lunes a viernes. Se conservan los umbrales vigentes por función y se redistribuye, sin modificar la base de datos, la bolsa histórica comparable de cada función: objetivo 60% grupal más polivalencia y 40% individual. Si no hay eventos de pago de un componente con los umbrales actuales, la mezcla se declara no alcanzable y no se fabrican jornadas elegibles. Los importes simulados no se aplicaron a parámetros ni caches.</p></details>',
                  html, count=1, flags=re.S)

    HTML_OUT.write_text(html, encoding="utf-8")
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "html": str(HTML_OUT), "json": str(JSON_OUT), "functions": 1,
        "sheets": 3,
        "pool_actual_centavos": sum(s["actual_centavos"] for s in report["escenarios_bolsa"]),
        "pool_proposed_centavos": sum(s["propuesto_centavos"] for s in report["escenarios_bolsa"]),
        "exceptions": [{"function": s["title"], "note": s["excepcion"]}
                       for s in report["escenarios_bolsa"] if s["excepcion"]],
        "cache": report["cache_grupal"],
        "snapshot_pagos": report["snapshot_pagos"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
