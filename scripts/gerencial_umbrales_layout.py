"""Láminas gerenciales: perfiles, resúmenes paginados y criterios visuales."""
from html import escape
import math
from gerencial_umbrales_visual import embedded, recommendation
from gerencial_umbrales_infografia import story

OPERATIONS = {
    'ARMADO': ('Armado', '#d87521', '#fff5e9', -375),
    'CLARK': ('Clark', '#519127', '#f2f8ec', -200),
    'RECEPCION': ('Recepción', '#1674bb', '#edf6fd', -15),
    'PALETS OPERADOS': ('Carga + traslado', '#7056b4', '#f2eff9', -550),
    'CONTROL': ('Control', '#008b91', '#edf9f8', -735),
}


def sprite_css():
    # Una sola copia de la ilustración para todas las operaciones.
    return ':root{--operations-sprite:url("' + embedded('operaciones_referencia.png', 'image/png') + '")}'


def operation_title(p):
    return OPERATIONS[p['operacion']][0] + (' · ' + p['camara'] if p['camara'] else '')


def op_style(p):
    _, color, pale, x = OPERATIONS[p['operacion']]
    return f'--operation:{color};--operation-pale:{pale};--sprite-x:{x}px'


def people_bar(p):
    total = p['personas']
    if not total:
        return '<p class="no-roster">Sin legajos asociados.</p>'
    widths = [p['mas']/total*100, p['igual']/total*100, p['menos']/total*100]
    return f'''<div class="people-track" role="img" aria-label="{p['mas']} cobran más, {p['igual']} sin cambio y {p['menos']} cobran menos"><span class="more" style="width:{widths[0]:.5f}%"></span><span class="equal" style="width:{widths[1]:.5f}%"></span><span class="less" style="width:{widths[2]:.5f}%"></span></div><div class="people-labels"><span class="green"><strong>{p['mas']}</strong> cobran más</span><span><strong>{p['igual']}</strong> sin cambio</span><span class="red"><strong>{p['menos']}</strong> cobran menos</span></div>'''


def profile(p, chart, number):
    if (p['sector'], p['operacion']) in {('CD-REFRIGERADOS', 'PALETS OPERADOS'), ('CD-NOA', 'CLARK')}:
        return story(p, chart, number, operation_title(p), op_style(p))
    pct = p['cumple']/p['dias']*100
    dots = []
    for day in p['diario']:
        cls = 'won' if day['cumple'] else ('no-base' if not day['base'] else '')
        date = f"{day['fecha'][6:8]}/{day['fecha'][4:6]}"
        label = f"{date}: {'alcanza' if day['cumple'] else ('sin base' if not day['base'] else 'no alcanza')} el objetivo del bloque"
        dots.append(f'<span class="day-square {cls}" title="{label}" aria-label="{label}"></span>')
    refs = []
    for ref in p['referencias']:
        value = number(ref['umbral']) if ref['umbral'] is not None else '—'
        days = f"{ref['dias_logrados']} de {p['dias']} días" if ref['umbral'] is not None else 'Sin base suficiente'
        refs.append(f'''<div class="alternative" data-percent="{ref['pct']}"><span>ACCESO {ref['pct']}%</span><strong>{value}<small>{p['unidad'] if ref['umbral'] is not None else ''}</small></strong><em>{days}</em></div>''')
    change = (p['nuevo_centavos']/p['actual_centavos']-1)*100 if p['actual_centavos'] else None
    ref50 = p['referencias'][1]
    graphic = chart(p).replace('viewBox="0 0 1120 552"', 'viewBox="40 65 1080 455"')
    if not p['con_base']:
        access = '<div class="access-number no-base-number"><strong>Sin base</strong><span>Perfil sin nómina asociada</span></div>'
        takeaway = 'Completar nómina y base computable'
        graph_class = ' no-data-curve'
    else:
        access = f'<div class="access-number"><strong>{p["cumple"]}</strong><span>de {p["dias"]} días</span><b>{number(pct,1)}%</b></div>'
        takeaway = 'Acceso poco frecuente' if pct < 25 else ('Acceso parcial' if pct < 75 else 'Acceso frecuente')
        graph_class = ''
    conclusion = (f'<strong>{number(ref50["umbral"])} {p["unidad"]}</strong> permiten alcanzar el objetivo en <strong>{ref50["dias_logrados"]} días</strong>.'
                  if ref50['umbral'] is not None else 'Se requiere base computable para estimar una referencia de acceso.')
    price = f'Bolsa {"+" if change >= 0 else ""}{number(change,1)}%' if change is not None else 'Sin pago comparable'
    no_base_overlay = '<div class="no-data-message"><strong>Sin base de cálculo</strong><span>Validar la nómina asociada al sector.</span></div>' if not p['con_base'] else ''
    return f'''<section class="sheet profile visual-profile" id="{p['id']}" style="{op_style(p)}">
      <div class="visual-profile-header"><div class="operation-title"><div class="operation-art" aria-hidden="true"></div><div><div class="eyebrow">{escape(p['sector'])}</div><h2>{escape(operation_title(p))}</h2><p>{p['unidad'].capitalize()} por operario · {escape(p['funcion'])}</p></div></div><div class="profile-context"><span>SECTOR CONSOLIDADO</span><strong>{p['dias']} días</strong><small>Agosto + septiembre 2026</small></div></div>
      <div class="visual-analysis"><div class="access-panel"><div class="eyebrow">Con el umbral vigente</div><div class="threshold-value">{number(p['objetivo'])}<span>{p['unidad']} / operario</span></div>{access}<div class="day-matrix" role="group" aria-label="{p['cumple']} de {p['dias']} días alcanzan el objetivo, en orden cronológico">{''.join(dots)}</div><div class="day-key"><span><i class="won"></i>Alcanza</span><span><i></i>No alcanza</span></div><div class="access-takeaway"><strong>{takeaway}</strong><span>{p['con_base']} jornadas con base computable.</span></div></div>
      <div class="visual-curve{graph_class}"><div class="visual-chart-label">Qué umbral permite acceder más días</div>{graphic}{no_base_overlay}<div class="visual-alternatives">{''.join(refs)}</div></div></div>
      <div class="visual-conclusion"><span>REFERENCIA 50%</span><p>{conclusion}</p><small>Umbral alternativo orientativo</small></div>
      <div class="visual-impact"><div class="impact-heading"><span class="eyebrow">Pago propuesto vigente</span><span>{p['personas']} legajos <b>{price}</b></span></div>{people_bar(p)}</div>
      {recommendation(p, number)}
      <details class="visual-details"><summary>Ver criterios y alcance</summary><p>Factor de ausentismo: {number(p['factor'])}%. Los casilleros muestran las fechas en orden cronológico. Las referencias del 25%, 50% y 75% indican frecuencias objetivo; los umbrales enteros y los empates pueden producir más días. La comparación monetaria incluye grupal, individual y polivalencia según la liquidación vigente por turno. La curva simula el sector como un bloque. Cambiar el umbral requiere una nueva simulación de pagos.</p></details>
    </section>'''


def grouped_pages(profiles, maximum=4):
    # Divide por cantidad de filas, conservando el tamaño de lectura.
    sectors = dict.fromkeys(p['sector'] for p in profiles)
    for sector in sectors:
        items = [p for p in profiles if p['sector'] == sector]
        page_count = math.ceil(len(items) / maximum)
        size = math.ceil(len(items) / page_count)
        for i in range(0, len(items), size):
            yield sector, items[i:i+size], i//size + 1, page_count


def thresholds_overview(report, number):
    output = []
    for page, (sector, profiles, part, parts) in enumerate(grouped_pages(report['perfiles']), 1):
        suffix = f' · {part}/{parts}' if parts > 1 else ''
        rows = []
        for p in profiles:
            pct = p['cumple']/p['dias']*100
            access = f'<strong>{number(pct,1)}%</strong><small>{p["cumple"]} de {p["dias"]} días</small>' if p['con_base'] else '<strong>Sin base</strong><small>Sin nómina asociada</small>'
            ref_cells = ''.join(f'<div class="threshold-cell"><strong>{number(r["umbral"]) if r["umbral"] is not None else "—"}</strong><small>{p["unidad"]}</small></div>' for r in p['referencias'])
            rows.append(f'''<div class="threshold-row" style="{op_style(p)}"><a class="operation-label" href="#{p['id']}"><i></i><span>{escape(operation_title(p))}<small>{p['unidad']} / operario</small></span></a><div class="access-cell">{access}</div><div class="threshold-cell current"><strong>{number(p['objetivo'])}</strong><small>vigente</small></div>{ref_cells}</div>''')
        output.append(f'''<section class="sheet executive-summary threshold-summary" id="umbrales-resumen-{page}"><div class="eyebrow">Umbrales grupales · Resumen por sector</div><h2>{escape(sector)}{suffix}</h2><p class="summary-intro">Un mismo calendario de {report['dias']} días. Todos los turnos consolidados.</p><div class="threshold-heading"><span>Operación</span><span>Acceso vigente</span><span>Umbral vigente</span><span>Para 25%</span><span>Para 50%</span><span>Para 75%</span></div>{''.join(rows)}<div class="summary-caption"><strong>Cómo leerlo</strong><span>Menor umbral amplía la frecuencia de acceso. Las referencias no modifican la configuración.</span></div></section>''')
    return ''.join(output)


def impact_overview(report, number):
    output = []
    for page, (sector, profiles, part, parts) in enumerate(grouped_pages(report['perfiles'], maximum=2), 1):
        suffix = f' · {part}/{parts}' if parts > 1 else ''
        rows = []
        for p in profiles:
            diff = (p['nuevo_centavos']/p['actual_centavos']-1)*100 if p['actual_centavos'] else None
            change = f'{"+" if diff >= 0 else ""}{number(diff,1)}%' if diff is not None else 'Sin comparación'
            rows.append(f'''<div class="impact-row" style="{op_style(p)}"><div class="impact-row-title"><a href="#{p['id']}" class="operation-label"><i></i><span>{escape(operation_title(p))}</span></a><span class="affected-count"><b>{p['personas']}</b> legajos</span><span class="budget-diff">Bolsa <b>{change}</b></span></div>{people_bar(p)}<div class="payment-values"><span>Actual <strong>$ {number(p['actual_centavos']/100)}</strong></span><span>Propuesto <strong>$ {number(p['nuevo_centavos']/100)}</strong></span><small>{'Escenario inicial por validar' if p.get('inicial') else 'Grupal + individual + polivalencia'}</small></div></div>''')
        output.append(f'''<section class="sheet executive-summary impact-summary" id="impacto-resumen-{page}"><div class="eyebrow">Impacto en personas · Pago propuesto vigente</div><h2>{escape(sector)}{suffix}</h2><p class="summary-intro">Más o menos pago respecto de las operaciones históricas equivalentes.</p>{''.join(rows)}<div class="summary-caption"><strong>Mismo período</strong><span>{report['dias']} días de lunes a viernes. La comparación monetaria conserva la liquidación por turno.</span></div></section>''')
    return ''.join(output)


def method_slide(report):
    return f'''<section class="sheet executive-summary method-summary" id="criterios-informe"><div class="eyebrow">Alcance del informe</div><h2>Qué estamos comparando</h2><div class="method-grid"><div><span>01</span><h3>Producción del sector</h3><p>Se suman producción y nómina computable de todos los turnos por fecha.</p></div><div><span>02</span><h3>Acceso al grupal</h3><p>Un calendario común de {report['dias']} días de lunes a viernes. Los días sin base permanecen visibles.</p></div><div><span>03</span><h3>Premio completo</h3><p>Grupal + individual + polivalencia, frente al pago histórico de las operaciones equivalentes.</p></div><div><span>04</span><h3>Escenarios para evaluar</h3><p>Las sugerencias orientan nuevas simulaciones. No cambian parámetros ni garantizan mejoras individuales.</p></div></div><div class="summary-caption"><strong>Dos lecturas</strong><span>La curva consolida el sector; la comparación de pagos usa la liquidación vigente por turno.</span></div><details class="visual-details"><summary>Fuentes y criterios técnicos</summary><p>Umbral diario = producción computable / [nómina computable × (1 − factor de ausentismo)]. El motor exige superar estrictamente la meta. Se usan los mayores umbrales enteros que permiten alcanzar las frecuencias objetivo, con días adicionales cuando hay empates. No se excluyen feriados. La nómina y los perfiles son actuales; no se reconstruyen transferencias históricas. Los datos son los aceptados para el estudio, sin una nueva consulta a Oracle vivo.</p><p>Cache grupal: {escape(report['cache_grupal'])} UTC. Snapshot de pagos: {escape(report['snapshot_pagos'])}. Generado: {escape(report['generado'][:19])}, Argentina.</p></details></section>'''
