"""Exporta un informe autónomo de umbrales y pagos desde el snapshot local.

Lectura exclusiva de SQLite. No recalcula ni modifica parámetros o caches.
Los turnos se consolidan por sector/función/operación y fecha, ponderando
producción por nómina computable después del factor de ausentismo.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
import json
import math
from pathlib import Path
import sqlite3
from gerencial_umbrales_visual import cover as visual_cover
from gerencial_umbrales_layout import profile as visual_profile, thresholds_overview, impact_overview, method_slide, sprite_css
from gerencial_umbrales_infografia import assets_css
from gerencial_umbrales_compacto import slides as compact_slides, dialogs as compact_dialogs

ROOT = Path(__file__).resolve().parents[1]
EQUIVALENTES = {
    'ARMADO': {'PICKING'},
    'CLARK': {'CLARK'},
    'CONTROL': {'CONTROL', 'CONTROL PROCESOS MANUAL', 'CONTROL DE PROCESOS CHP + CBF'},
    'RECEPCION': {'RECEPCION', 'RECEPCION NOA', 'RECEPCION SECOS',
                  'RECEPCION IMPORTADO DE NOA', 'REFRIGERADOS | RECEPCION'},
    'PALETS OPERADOS': {'CARGA', 'CARRETEO', 'REFRIGERADOS | CARGA'},
}
LABEL = {'ARMADO': 'Armado', 'CLARK': 'Clark', 'CONTROL': 'Control',
         'RECEPCION': 'Recepción', 'PALETS OPERADOS': 'Carga + traslado'}
UNIT = {'BULTO': 'bultos', 'PALET': 'palets', 'PLU': 'PLUs'}


def number(value, decimals=0):
    return f'{value:,.{decimals}f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def key(row, op_field='operacion'):
    return (row['sector'], row['funcion_legajero'], row[op_field], row.get('division_madre') or '')


def load(desde, hasta):
    dbpath = ROOT / 'datos/laboratorio_premios.db'
    db = sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('BEGIN')  # una única fotografía coherente durante toda la lectura
    fd, fh = desde.replace('-', ''), hasta.replace('-', '')
    cache = db.execute('SELECT * FROM lab_calculo_grupal_cache WHERE fecha_desde=? AND fecha_hasta=?', (fd, fh)).fetchone()
    if not cache:
        raise ValueError('Falta el cache grupal del período solicitado.')
    params = [dict(r) for r in db.execute('SELECT * FROM lab_parametro_grupal WHERE activo=1')]
    scales = [dict(r) for r in db.execute('SELECT * FROM lab_escala_individual_grupal WHERE activo=1')]
    meta = db.execute('SELECT * FROM lab_pago_actual_meta ORDER BY capturado DESC LIMIT 1').fetchone()
    if not meta:
        raise ValueError('Falta el snapshot de pagos actuales.')
    payroll = [dict(r) for r in db.execute('''SELECT CAST(legajo AS TEXT) legajo,fecha,
        UPPER(TRIM(operacion)) operacion,SUM(pago_centavos) pago
        FROM lab_pago_actual_operacion WHERE snapshot=? AND fecha BETWEEN ? AND ?
        GROUP BY CAST(legajo AS TEXT),fecha,UPPER(TRIM(operacion))''', (meta['snapshot'], fd, fh))]
    db.close()
    return dict(cache), params, scales, dict(meta), payroll


def analyze(desde, hasta):
    cache, params, scales, meta, payroll = load(desde, hasta)
    calendar = []
    day = datetime.fromisoformat(desde)
    while day <= datetime.fromisoformat(hasta):
        if day.weekday() < 5:
            calendar.append(day.strftime('%Y%m%d'))
        day += timedelta(days=1)
    days = set(calendar)
    pmap = {(key(p, 'operacion_medible'), str(p['turno'])): p for p in params}
    smap = defaultdict(list)
    for s in scales:
        smap[(key(s, 'operacion_medible'), str(s['turno']))].append(s)
    profiles = {key(p, 'operacion_medible'): [] for p in params}
    roster = json.loads(cache['nivel_3_json'])
    daily = json.loads(cache['nivel_2_json'])
    seen = set()
    for row in roster:
        identity = (str(row['legajo']), row['fecha'])
        if identity in seen:
            raise ValueError(f'Legajo/día repetido en cache: {identity}')
        seen.add(identity)
    for row in daily:
        if row['fecha'] in days and key(row) in profiles:
            profiles[key(row)].append(row)
    actual = defaultdict(int)
    for p in payroll:
        if p['fecha'] in days:
            actual[(p['legajo'], p['fecha'], p['operacion'])] += int(p['pago'] or 0)
    money = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    evidence = defaultdict(lambda: defaultdict(list))
    daymap = {(key(r), str(r['turno']), r['fecha']): r for r in daily}
    for row in roster:
        k = key(row)
        if row['fecha'] not in days or k not in profiles:
            continue
        par = pmap[(k, str(row['turno']))]
        totals = money[k][str(row['legajo'])]
        before = list(totals)
        totals[0] += sum(actual[(str(row['legajo']), row['fecha'], op)] for op in EQUIVALENTES[k[2]])
        # El resumen por legajo vigente usa el premio grupal del cache.
        if row.get('cobra'):
            totals[1] += int(round(float(row.get('premio_grupal') or 0) * 100))
        if row.get('es_polivalencia') and row.get('asistencia') == 'Presente':
            totals[3] += int(round(float(par['premio_grupal'] or 0) * 100))
        if row.get('aplica_grupo') and row.get('asistencia') == 'Presente':
            uc = float(row.get('uc_brutas') or 0)
            eligible = [float(s['premio'] or 0) for s in smap[(k, str(row['turno']))]
                        if uc >= float(s['desde_uc'] or 0) and
                        (float(s['hasta_uc'] or 0) <= 0 or uc < float(s['hasta_uc']))]
            totals[2] += int(round(max(eligible, default=0) * 100))
        if k[2] in EQUIVALENTES:
            amounts = [a-b for a,b in zip(totals,before)]
            ds = daymap.get((k,str(row['turno']),row['fecha']), {})
            applicable = bool(row.get('aplica_grupo') and row.get('asistencia') == 'Presente')
            levels = [int(s['nivel']) for s in smap[(k,str(row['turno']))] if applicable and float(row.get('uc_brutas') or 0) >= float(s['desde_uc'] or 0) and (float(s['hasta_uc'] or 0)<=0 or float(row.get('uc_brutas') or 0)<float(s['hasta_uc']))]
            missed = bool(row.get('beneficiario') and not row.get('es_polivalencia') and ds.get('evaluable') and not ds.get('cumple') and not row.get('cobra'))
            evidence[k][str(row['legajo'])].append({'fecha':row['fecha'],'turno':str(row['turno']), 'uc':float(row.get('uc_brutas') or 0), 'nivel':max(levels,default=0), 'evaluado':applicable,'actual':amounts[0], 'grupal':amounts[1], 'individual':amounts[2], 'polivalencia':amounts[3], 'falta_grupal':missed, 'grupal_potencial':int(round(float(par['premio_grupal'] or 0)*100)) if missed else 0,'estado':ds.get('estado','Sin base'),'asistencia':row.get('asistencia','')})
    output = []
    order = {'CD-SECOS - ZONA 1': 0, 'CD-SECOS - ZONA 2': 1, 'CD-NOA': 2,
             'CD-REFRIGERADOS': 3, 'CD-ADMINISTRACION': 4}
    for k, source in sorted(profiles.items(), key=lambda kv: (order.get(kv[0][0], 5), kv[0][2], kv[0][1])):
        settings = [p for p in params if key(p, 'operacion_medible') == k]
        objectives = {float(p['uc_por_operario']) for p in settings}
        factors = {float(p['factor_ausentismo']) for p in settings}
        group_awards = {float(p['premio_grupal']) for p in settings}
        if len(objectives) != 1 or len(factors) != 1:
            raise ValueError(f'El bloque tiene parámetros diferentes entre turnos: {k}')
        if len(group_awards) != 1:
            raise ValueError(f'El bloque tiene premios grupales diferentes entre turnos: {k}')
        objective = objectives.pop()
        factor = factors.pop()
        group_award = group_awards.pop()
        scale_rows = [s for s in scales if key(s, 'operacion_medible') == k]
        scale_summary = []
        for level in range(1, 6):
            level_rows = [s for s in scale_rows if int(s['nivel']) == level]
            signatures = {(float(s['desde_uc']), float(s['hasta_uc']), float(s['premio'])) for s in level_rows}
            if len(signatures) != 1:
                raise ValueError(f'Escala individual distinta entre turnos: {k}, nivel {level}')
            desde_uc, hasta_uc, award = signatures.pop()
            scale_summary.append({'nivel': level, 'desde_uc': desde_uc,
                                  'hasta_uc': hasta_uc, 'premio': award})
        by_date = defaultdict(list)
        for row in source:
            # Rechaza caches que ya no reflejan los umbrales vigentes.
            if abs(float(row['objetivo_por_operario']) - objective) > 1e-6:
                raise ValueError(f'Cache desactualizado: {k}')
            by_date[row['fecha']].append(row)
        data = []
        for fecha in calendar:
            valid = [r for r in by_date[fecha] if r.get('evaluable') and float(r.get('nomina_computable') or 0) > 0]
            divisor = sum(float(r['nomina_computable']) * (1 - float(r['factor_ausentismo']) / 100) for r in valid)
            production = sum(float(r.get('uc_computables') or 0) for r in valid)
            # Es una simulación del sector como un bloque. El motor vigente
            # liquida por turno; no se atribuye esta consolidación a pagos reales.
            data.append({'fecha': fecha, 'base': divisor, 'produccion': production,
                         'uc': production / divisor if divisor > 0 else None,
                         'cumple': bool(divisor > 0 and production > objective * divisor)})
        values = sorted((r['uc'] for r in data if r['uc'] is not None), reverse=True)
        refs = []
        for pct in (25, 50, 75):
            target = math.ceil(len(calendar) * pct / 100)
            # El motor exige producción > meta. El mayor entero admisible
            # debe quedar estrictamente debajo del valor de la jornada límite.
            suggested = math.ceil(values[target - 1]) - 1 if target <= len(values) else None
            if suggested is not None and suggested <= 0:
                suggested = None
            achieved = sum(1 for r in data if r['base'] > 0 and r['produccion'] > (suggested or 0) * r['base']) if suggested else 0
            refs.append({'pct': pct, 'dias_objetivo': target, 'umbral': suggested, 'dias_logrados': achieved})
        persons = money[k]
        more = sum(sum(v[1:]) > v[0] for v in persons.values())
        less = sum(sum(v[1:]) < v[0] for v in persons.values())
        equal = len(persons) - more - less
        old = sum(v[0] for v in persons.values())
        new = sum(sum(v[1:]) for v in persons.values())
        chamber = 'Congelados' if k[1] in {'ARMADOR T06', 'CLARK CONGELADOS'} else ('Otras cámaras' if k[0] == 'CD-REFRIGERADOS' and k[2] in {'ARMADO', 'CLARK'} else '')
        output.append({'id': f'perfil-{len(output)+1}', 'sector': k[0], 'funcion': k[1], 'operacion': k[2],
                       'division': k[3], 'camara': chamber, 'unidad': UNIT.get(source[0].get('unidad_medida'), 'UC') if source else UNIT.get({'ARMADO':'BULTO','CONTROL':'PLU'}.get(k[2], 'PALET')),
                       'objetivo': objective, 'factor': factor, 'dias': len(calendar),
                       'premio_grupal': group_award, 'escala_individual': scale_summary,
                       'con_base': len(values), 'cumple': sum(r['cumple'] for r in data),
                       'referencias': refs, 'valores': values, 'diario': data,
                       'personas': len(persons), 'mas': more, 'menos': less, 'igual': equal,
                       'actual_centavos': old, 'nuevo_centavos': new,
                       'operaciones_historicas': sorted(EQUIVALENTES[k[2]]),
                       'piloto_legajos': [{'legajo':leg,'dias':rows} for leg,rows in sorted(evidence[k].items())] if k in evidence else [],
                       'inicial': any(str(s.get('origen', '')).startswith('escenario-inicial') for s in scales if key(s, 'operacion_medible') == k)})
    return {'desde': desde, 'hasta': hasta, 'dias': len(calendar), 'cache_grupal': cache['calculado_at'],
            'snapshot_pagos': meta['snapshot'], 'generado': datetime.now(timezone(timedelta(hours=-3))).isoformat(),
            'perfiles': output}


def attach_polivalency_summaries(report):
    """Adds period summaries from the existing group cache, using read-only SQLite."""
    dbpath = ROOT / 'datos/laboratorio_premios.db'
    if not dbpath.exists():
        raise FileNotFoundError(f'No se encuentra el cache local: {dbpath}')
    db = sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True)
    try:
        fd, fh = report['desde'].replace('-', ''), report['hasta'].replace('-', '')
        cache = db.execute('''SELECT calculado_at,nivel_3_json FROM lab_calculo_grupal_cache
            WHERE fecha_desde=? AND fecha_hasta=? AND calculado_at=? LIMIT 1''',
            (fd, fh, report['cache_grupal'])).fetchone()
        if not cache:
            raise ValueError('El cache de polivalencias no coincide con la fecha del informe; no se genera un resumen potencialmente desactualizado.')
        roster = json.loads(cache[1])
    finally:
        db.close()

    def row_key(row):
        return (row.get('sector'), row.get('funcion_legajero', row.get('funcion')),
                row.get('operacion'), str(row.get('division_madre', row.get('division')) or ''))

    start, end = datetime.fromisoformat(report['desde']), datetime.fromisoformat(report['hasta'])
    valid_dates = set()
    day = start
    while day <= end:
        if day.weekday() < 5:
            valid_dates.add(day.strftime('%Y%m%d'))
        day += timedelta(days=1)
    grouped = defaultdict(list)
    for row in roster:
        if (row.get('es_polivalencia') and row.get('asistencia') == 'Presente'
                and row.get('fecha') in valid_dates):
            grouped[row_key(row)].append(row)

    for profile in report['perfiles']:
        poly_rows = grouped.get(row_key(profile), [])
        event_keys = {(str(row.get('legajo')), row.get('fecha')) for row in poly_rows}
        origins, reasons = Counter(), Counter()
        for row in poly_rows:
            row_origins = row.get('polivalencia_operaciones') or ['Origen no clasificado']
            origins.update(set(str(value) for value in row_origins))
            row_reasons = row.get('polivalencia_motivos') or ['Motivo no clasificado']
            reasons.update(set(str(value) for value in row_reasons))
        paid = sum(day_row['polivalencia'] for person in profile.get('piloto_legajos', [])
                   for day_row in person.get('dias', []))
        profile['polivalencia_resumen'] = {
            'pago_centavos': paid,
            'legajo_dias': len(event_keys),
            'legajos': len({legajo for legajo, _ in event_keys}),
            'fechas': len({fecha for _, fecha in event_keys}),
            'origenes': [{'nombre': name, 'eventos': count} for name, count in origins.most_common(6)],
            'motivos': [{'nombre': name, 'eventos': count} for name, count in reasons.most_common(4)],
            '_eventos': sorted(event_keys),
        }


def chart(p):
    w, h, left, right, top, bottom = 1120, 552, 88, 1075, 76, 438
    values, n = p['valores'], p['dias']
    highest = max([p['objetivo'], *values], default=1)
    ymax = math.ceil(highest * 1.15 / 10) * 10 or 10
    xx = lambda pct: left + (right-left)*pct/100
    yy = lambda uc: bottom - (bottom-top)*uc/ymax
    svg = [f'<svg class="threshold-chart" data-profile="{p["id"]}" data-ymax="{ymax}" viewBox="0 0 {w} {h}" role="img" aria-label="Curva de umbrales de {escape(p["sector"])} {escape(LABEL[p["operacion"]])}">',
           f'<defs><linearGradient id="fill-{p["id"]}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2688a5" stop-opacity=".25"/><stop offset="1" stop-color="#2688a5" stop-opacity=".025"/></linearGradient></defs>',
           f'<text x="{left}" y="24" class="chart-title">{escape(p["sector"])} — {escape(LABEL[p["operacion"]])}{(" · " + escape(p["camara"])) if p["camara"] else ""}</text>',
           f'<text x="{left}" y="47" class="chart-sub">Umbral por operario · {escape(p["unidad"])} · Vigente: {p["cumple"]} de {p["dias"]} días ({number(p["cumple"]/p["dias"]*100,1)}%)</text>']
    for i in range(6):
        v = ymax*i/5
        svg += [f'<line x1="{left}" y1="{yy(v):.1f}" x2="{right}" y2="{yy(v):.1f}" class="grid"/>', f'<text x="{left-14}" y="{yy(v)+5:.1f}" text-anchor="end" class="tick">{number(v)}</text>']
    for pct in (0, 10, 25, 50, 75, 90, 100):
        svg += [f'<line x1="{xx(pct):.1f}" y1="{top}" x2="{xx(pct):.1f}" y2="{bottom}" class="grid"/>',
                f'<text x="{xx(pct):.1f}" y="{bottom+26}" text-anchor="middle" class="tick">{pct}%</text>']
    if values:
        points = [(xx((i+1)/n*100), yy(v)) for i, v in enumerate(values)]
        points.insert(0, (xx(0), yy(values[0])))
        path = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x,y in points)
        svg += [f'<path class="chart-area" d="{path} L{points[-1][0]:.1f},{bottom} L{left},{bottom} Z" fill="url(#fill-{p["id"]})"/>',
                f'<path class="chart-curve" d="{path}" fill="none" stroke="#13748b" stroke-width="3.5" stroke-linejoin="round"/>']
        if len(values) < n:
            start = xx(len(values)/n*100)
            svg.append(f'<rect x="{start:.1f}" y="{top}" width="{right-start:.1f}" height="{bottom-top}" fill="#f0f3f6" opacity=".8"/>')
            svg.append(f'<text x="{right-12}" y="{bottom-18}" text-anchor="end" class="chart-sub">{n-len(values)} días sin base</text>')
    active_y = yy(p['objetivo'])
    svg += [f'<g class="active-threshold"><line x1="{left}" x2="{right}" y1="{active_y:.1f}" y2="{active_y:.1f}" stroke="#c23f43" stroke-width="2" stroke-dasharray="8 6"/>',
            f'<rect x="{left+12}" y="{max(top,active_y-34):.1f}" width="250" height="27" rx="5" fill="#fff4f3"/>',
            f'<text x="{left+22}" y="{max(top,active_y-34)+18:.1f}" fill="#a53035" font-size="13" font-weight="700">Vigente: {number(p["objetivo"])} {escape(p["unidad"])}</text></g>']
    for ref in p['referencias']:
        if ref['umbral'] is None:
            continue
        x,y = xx(ref['dias_objetivo']/n*100), yy(ref['umbral'])
        svg.append(f'<circle class="chart-reference" cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="white" stroke="#13748b" stroke-width="2.5"><title>{ref["pct"]}%: {ref["umbral"]} {p["unidad"]}; {ref["dias_logrados"]} días alcanzados</title></circle>')
    svg += [f'<text x="{(left+right)/2}" y="{bottom+55}" text-anchor="middle" class="axis-title">Porcentaje del período en que se alcanza el premio grupal</text>', '</svg>']
    labels = []
    for r in p['referencias']:
        amount = f'{number(r["umbral"])} <small>{escape(p["unidad"])}</small>' if r['umbral'] is not None else '<small>No estimable</small>'
        desc = f'{r["dias_logrados"]} días al aplicar ese umbral' if r['umbral'] is not None else 'Sin base suficiente para ese objetivo'
        labels.append(f'<div class="ref"><span>OBJETIVO {r["pct"]}% · {r["dias_objetivo"]} DÍAS</span><strong>{amount}</strong><em>{desc}</em></div>')
    return '<div class="figure"><div class="inside-refs">'+''.join(labels)+'</div>'+''.join(svg)+'</div>'


STYLE = '''
:root{--ink:#142f42;--muted:#5b7180;--teal:#13748b;--line:#dce5e9;--red:#ad393e}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#edf2f5;color:var(--ink);font:15px/1.55 "Segoe UI",Arial,sans-serif}a{color:inherit}main{max-width:1240px;margin:30px auto}.sheet{background:white;border:1px solid var(--line);border-radius:16px;margin:24px 0;padding:40px;box-shadow:0 5px 25px #17344806}.eyebrow{font-size:11px;letter-spacing:2px;font-weight:700;color:var(--teal);text-transform:uppercase}.hero{border-top:6px solid var(--teal);padding:48px 44px}h1{font-size:40px;line-height:1.14;letter-spacing:-1.1px;max-width:850px;margin:16px 0}h2{font-size:27px;line-height:1.2;letter-spacing:-.4px;margin:10px 0}h3{font-size:19px;margin:0}p{margin:12px 0}.lead{font-size:19px;color:var(--muted);max-width:880px}.meta{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0}.pill{font-size:12px;border:1px solid var(--line);padding:6px 12px;border-radius:30px;background:#f7fafb}.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin-top:26px}.tile{background:#f2f7f8;border-radius:10px;padding:18px}.tile strong{display:block;font-size:29px;line-height:1.2}.tile span{font-size:12px;color:var(--muted)}.note{border-left:3px solid var(--teal);padding:12px 16px;background:#f3f8fa;color:var(--muted);font-size:13px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:right;font-size:10px;letter-spacing:.7px;text-transform:uppercase;color:var(--muted);padding:14px 9px;border-bottom:2px solid var(--line);white-space:nowrap}th:first-child,td:first-child{text-align:left}td{text-align:right;padding:13px 9px;border-bottom:1px solid #e9eff2;font-variant-numeric:tabular-nums}td:first-child{min-width:230px}td small{display:block;color:var(--muted);font-size:11px}.status{display:inline-block;padding:3px 8px;border-radius:5px;background:#edf6f5;color:#196d66;font-size:11px;font-weight:600}.status.low{background:#fff0ed;color:#a33a33}.status.mid{background:#fff6e5;color:#8b6216}.profile-head{display:flex;justify-content:space-between;align-items:start;gap:25px}.big-stat{text-align:right;flex-shrink:0}.big-stat strong{font-size:35px;line-height:1.1;display:block}.big-stat span{font-size:12px;color:var(--muted)}.profile-sub{color:var(--muted);font-size:13px;margin:8px 0 22px}.figure{border:1px solid var(--line);border-radius:12px;padding:22px 14px 0;overflow:hidden;background:#fff}.inside-refs{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:0 26px 22px}.ref{border-top:3px solid #13748b;background:#f0f7f8;padding:12px 14px}.ref span{font-size:10px;letter-spacing:.7px;color:var(--muted);display:block}.ref strong{font-size:26px;display:block;line-height:1.6}.ref small{font-size:13px;font-weight:400}.ref em{font-style:normal;font-size:11px;color:var(--muted)}svg{width:100%;height:auto;display:block;font-family:"Segoe UI",Arial,sans-serif}.chart-title{font-size:19px;font-weight:700;fill:var(--ink)}.chart-sub{font-size:12px;fill:var(--muted)}.grid{stroke:#e7eef2;stroke-width:1}.tick{font-size:12px;fill:var(--muted)}.axis-title{font-size:13px;fill:var(--muted)}.interpretation{font-size:16px;margin:20px 0 12px;padding:0 2px}.payment-strip{display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap;background:#f5f7f9;border-radius:8px;padding:14px 18px;font-size:13px}.payment-strip b{font-size:16px}.green{color:#116c62}.red{color:#a3363b}.foot{font-size:11px;color:var(--muted);margin-top:15px}.toolbar{display:flex;justify-content:space-between;gap:15px;font-size:12px;color:var(--muted);align-items:center}.button{background:var(--ink);color:white;border:0;border-radius:6px;padding:10px 18px;cursor:pointer;font:inherit}.methods{display:grid;grid-template-columns:1fr 1fr;gap:28px}.methods p{font-size:13px;color:var(--muted)}footer{text-align:center;color:var(--muted);padding:10px 20px 30px;font-size:12px}@media(max-width:800px){main{margin:10px}.sheet{padding:22px}.hero{padding:28px}h1{font-size:30px}.tiles{grid-template-columns:repeat(2,1fr)}.inside-refs{margin:0 0 15px;gap:6px}.ref{padding:10px}.ref strong{font-size:20px}.ref span,.ref em{font-size:9px}.methods{grid-template-columns:1fr}.profile-head{gap:12px}.big-stat strong{font-size:28px}}@media print{@page{size:A4 landscape;margin:10mm}body{background:white;font-size:12px}main{max-width:none;margin:0}.toolbar,.no-print{display:none}.sheet{border:0;box-shadow:none;border-radius:0;padding:12px 22px;margin:0 0 15px;break-before:page;break-inside:avoid}.hero{break-before:auto;padding:30px}.profile{height:auto}h1{font-size:34px}.figure{padding-top:12px}.inside-refs{margin-bottom:8px}.figure svg{max-height:113mm}.ref{padding:6px 12px}.ref strong{font-size:22px}.profile-sub{margin-bottom:10px}.interpretation{margin:12px 0 8px}.payment-strip{padding:8px 14px}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
'''


def render(report, compact=True):
    style_names = ('gerencial_umbrales_motion.css', 'gerencial_umbrales_visual.css',
                   'gerencial_umbrales_fit.css', 'gerencial_umbrales_layout.css', 'gerencial_umbrales_infografia.css')
    styles = STYLE + ''.join(Path(__file__).with_name(name).read_text(encoding='utf-8') for name in style_names) + sprite_css() + assets_css()
    script = Path(__file__).with_name('gerencial_umbrales_motion.js').read_text(encoding='utf-8')
    if compact:
        styles += Path(__file__).with_name('gerencial_umbrales_compacto.css').read_text(encoding='utf-8')
        script += '\n' + Path(__file__).with_name('gerencial_umbrales_compacto.js').read_text(encoding='utf-8')
    toolbar = '<div class="toolbar report-toolbar"><span class="brand">VigIA <small>· Premios por productividad</small></span><div class="toolbar-actions"><div class="mode-switch" role="group" aria-label="Vista del informe"><button type="button" id="report-mode" aria-pressed="true">Informe completo</button><button type="button" id="presentation-mode" aria-pressed="false">Presentación</button></div><button type="button" class="control-button" id="motion-toggle" aria-pressed="true">Animaciones: activadas</button><button type="button" class="control-button fullscreen-button" id="fullscreen-toggle">Pantalla completa</button><button type="button" class="button" id="print-report">Imprimir / PDF</button></div></div>'
    navigation = '<nav class="presentation-nav" aria-label="Navegación de presentación" hidden><button type="button" id="previous-slide" class="control-button" aria-label="Lámina anterior">← Anterior</button><div class="slide-location"><label for="slide-select" class="sr-only">Ir a una lámina</label><select id="slide-select"></select><span id="slide-count" role="status" aria-live="polite"></span></div><button type="button" id="next-slide" class="control-button" aria-label="Lámina siguiente">Siguiente →</button><div class="deck-progress"><div id="deck-progress-value"></div></div></nav>'
    out = ['<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Premio grupal · Acceso al incentivo y umbrales</title><style>',
           styles, '</style></head><body><main>', toolbar]
    if compact:
        out.append(compact_slides(report, chart, number))
    else:
        out.extend([visual_cover(report, number), thresholds_overview(report, number)])
        out.extend(visual_profile(p, chart, number) for p in report['perfiles'])
        out.extend([impact_overview(report, number), method_slide(report)])
    public_report = dict(report, perfiles=[{k:v for k,v in p.items() if k != 'polivalencia_resumen' or not isinstance(v,dict)} | {
        'polivalencia_resumen': {k:v for k,v in p['polivalencia_resumen'].items() if k != '_eventos'}
    } if isinstance(p.get('polivalencia_resumen'), dict) else dict(p) for p in report['perfiles']])
    out.extend([
                '<footer>VigIA · Estudio de productividad · Documento de trabajo para validación gerencial</footer></main>',
                navigation, compact_dialogs(report, chart, number) if compact else '', '<div class="chart-tooltip" id="chart-tooltip" role="status" hidden></div>',
                '<script id="report-data" type="application/json">', json.dumps(public_report, ensure_ascii=False).replace('<', '\\u003c'),
                '</script><script>', script, '</script></body></html>'])
    return ''.join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--desde', default='2026-08-01')
    parser.add_argument('--hasta', default='2026-09-30')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/informe_gerencial_umbrales_20261016.html')
    parser.add_argument('--snapshot', type=Path, help='Reutiliza la fotografía JSON ya exportada, sin leer la base.')
    parser.add_argument('--completo', action='store_true', help='Genera las 35 hojas de la versión detallada anterior.')
    args = parser.parse_args()
    report = json.loads(args.snapshot.read_text(encoding='utf-8')) if args.snapshot else analyze(args.desde, args.hasta)
    attach_polivalency_summaries(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(report, compact=not args.completo), encoding='utf-8')
    args.output.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'html': str(args.output), 'perfiles': len(report['perfiles']), 'dias':report['dias'],
                      'sin_base':[(p['sector'],p['operacion']) for p in report['perfiles'] if p['con_base']==0]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
