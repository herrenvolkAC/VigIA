"""Doce láminas ejecutivas, con evidencia completa en diálogos locales."""
from html import escape
from gerencial_umbrales_visual import cover
from gerencial_umbrales_layout import op_style, operation_title, people_bar
from gerencial_umbrales_infografia import access_level
import gerencial_umbrales_piloto as piloto


PAGES = [
    ('secos-armado', 'Secos · Armado', 'Zona 1 y Zona 2', [1, 5]),
    ('secos-clark', 'Secos · Clark', 'Zona 1 y Zona 2', [2, 6]),
    ('secos-carga', 'Secos · Carga', 'Palets operados', [3]),
    ('secos-recepcion', 'Secos · Recepción', 'Zona 1 y Zona 2', [4, 7]),
    ('noa-armado', 'NOA · Armado', 'Acceso al grupal y pago completo', [8]),
    ('noa-clark', 'NOA · Clark', 'Clark', [9]),
    ('noa-recepcion', 'NOA · Recepción', 'Recepción', [10]),
    ('refri-armado', 'Refrigerados · Armado · Otras cámaras', 'Otras cámaras', [11]),
    ('refri-armado-congelados', 'Refrigerados · Armado · Congelados', 'Congelados', [12]),
    ('refri-clark', 'Refrigerados · Clark · Otras cámaras', 'Otras cámaras', [13]),
    ('refri-clark-congelados', 'Refrigerados · Clark · Congelados', 'Congelados', [14]),
    ('refri-carga', 'Refrigerados · Carga', 'Carga', [15]),
    ('refri-recepcion', 'Refrigerados · Recepción', 'Recepción', [16]),
    ('control', 'Control · Secos y NOA', 'Controlador de stock · Medición en PLUs', [17]),
]


def budget(p, number):
    if not p['actual_centavos']:
        return 'Sin pago comparable'
    pct = (p['nuevo_centavos'] / p['actual_centavos'] - 1) * 100
    return ('+' if pct >= 0 else '') + number(pct, 1) + '%'


def suggestion(p, number):
    frequency = p['cumple'] / p['dias']
    ref = p['referencias'][1]['umbral']
    if not p['con_base']:
        return 'Validar la nómina antes de evaluar premios.'
    if p.get('inicial'):
        return 'Validar el pago histórico comparable antes de aprobar el escenario.'
    if p['menos'] and frequency < .5 and ref is not None and ref < p['objetivo']:
        return f'Evaluar {number(ref)} {p["unidad"]} y simular su impacto en pagos.'
    if p['menos'] and frequency >= .75:
        return 'Revisar el reparto entre grupal e individual, controlando el costo.'
    if p['menos']:
        return 'Revisar jornadas y niveles de los legajos que cobran menos.'
    return 'Mantener como referencia y validar el costo del escenario.'


def profile(p, number, single=False):
    pose, status, label = access_level(p['cumple'], p['dias'], bool(p['con_base']))
    pct = p['cumple'] / p['dias'] * 100
    ref = p['referencias'][1]
    ref_pct = ref['dias_logrados'] / p['dias'] * 100 if ref['umbral'] is not None else 0
    name = p['sector'] if not p['camara'] else p['camara']
    return f'''<article class="compact-profile {'solo-profile' if single else ''}" id="{p['id']}" style="{op_style(p)}" data-profile="{p['id']}">
      <header class="compact-profile-title"><div><h3>{escape(name)} <span>{escape(operation_title(p)) if not p['camara'] else ''}</span></h3><p>{escape(p['funcion'])}</p></div><div class="profile-actions"><button type="button" class="detail-button" data-open-profile="poly-summary-{p['id']}" aria-haspopup="dialog">Polivalencias</button><button type="button" class="detail-button" data-open-profile="{p['id']}" aria-haspopup="dialog">Ver detalle</button></div></header>
      <div class="compact-comparison">
        <div class="compact-character"><div class="worker-pose {pose}" data-access-level="{pose}" role="img" aria-label="{escape(label)}" title="{escape(label)}"></div><span>{status}</span></div>
        <div class="compact-access"><span class="metric-label">Umbral vigente <b>{number(p['objetivo'])} {p['unidad']}/op.</b></span><div class="access-figure"><strong>{p['cumple']}</strong><span>de {p['dias']} días<b>{number(pct,1)}%</b></span></div><div class="access-track" role="img" aria-label="Alcanza el grupal {p['cumple']} de {p['dias']} días"><i style="width:{pct:.5f}%"></i></div></div>
        <div class="compact-reference"><span class="metric-label">Alternativa para evaluar <b>Referencia ≈50%</b></span><div class="reference-figure"><strong>{number(ref['umbral']) if ref['umbral'] is not None else '—'}</strong><span>{p['unidad']}/op.<b>{ref['dias_logrados']} de {p['dias']} días · {number(ref_pct,1)}%</b></span></div><small>El pago de esta alternativa requiere simulación.</small></div>
      </div>
      <div class="compact-money"><div class="money-change"><span>Bolsa propuesta vigente</span><strong>{budget(p,number)}</strong></div><div class="compact-people">{people_bar(p)}</div><div class="money-values"><span>Actual <b>$ {number(p['actual_centavos']/100)}</b></span><span>Propuesto <b>$ {number(p['nuevo_centavos']/100)}</b></span></div></div>
      <div class="compact-advice"><span>Para evaluar</span><strong>{suggestion(p,number)}</strong></div>
    </article>'''


def method(report):
    return f'''<section class="sheet compact-sheet compact-method" id="metodo-visual"><div class="compact-heading"><div><span class="eyebrow">Método de cálculo</span><h2>Cómo se compone el premio</h2></div><span class="compact-period">{report['dias']} días · Agosto y septiembre 2026</span></div>
      <div class="method-parts"><article><div class="method-art clark-art"></div><span>Premio grupal</span><h3>El equipo supera la meta</h3><p>Producción computable frente a la nómina computable, el objetivo por operario y el factor de ausentismo.</p></article><article><div class="method-art armado-art"></div><span>Premio individual</span><h3>Cada persona alcanza un nivel</h3><div class="level-strip"><b>N1</b><b>N2</b><b>N3</b><b>N4</b><b>N5</b></div><p>La producción real determina el nivel y el importe individual configurado.</p></article><article><div class="method-art recepcion-art"></div><span>Polivalencia</span><h3>Una marca por jornada</h3><p>Se activa por cambio de función o cruce de almacén (1/6 ↔ 2/4). Paga el mismo importe que el premio grupal configurado para el perfil y turno; ese día no cobra grupal. Puede sumar individual si alcanza un nivel.</p></article></div>
      <div class="method-total"><strong>Pago nuevo</strong><span>Premio grupal o polivalencia —al mismo valor grupal—, más premio individual cuando corresponda.</span></div>
      <div class="method-readings"><div><b>Acceso al grupal</b><span>Comparamos el sector como un bloque, con todos los turnos consolidados.</span></div><div><b>Comparación económica</b><span>Usamos el pago vigente calculado por turno frente al histórico de operaciones equivalentes.</span></div></div>
      <p class="compact-footnote">Los gestos muestran frecuencia de acceso al grupal. El impacto económico se informa por separado.</p>
    </section>'''


def conclusion(report, number):
    profiles = report['perfiles']
    low = [p for p in profiles if p['con_base'] and p['cumple']/p['dias'] < .5]
    total = sum(p['actual_centavos'] for p in profiles)
    proposed = sum(p['nuevo_centavos'] for p in profiles)
    losers = sum(p['menos'] for p in profiles)
    comparable = [p for p in profiles if p['con_base']]
    centered = [p for p in comparable if .70 <= p['cumple']/p['dias'] <= .80]
    furthest = max(comparable, key=lambda p: abs(p['cumple']/p['dias']-.75))
    most_losers = max(comparable, key=lambda p: p['menos'])
    return f'''<section class="sheet compact-sheet compact-conclusion" id="decisiones"><div class="compact-heading"><div><span class="eyebrow">Conclusiones</span><h2>Dónde concentrar la revisión</h2></div><span class="compact-period">Escenario vigente · {report['dias']} días</span></div>
      <div class="closing-summary"><div><span>Variación de la bolsa</span><strong>{'+' if proposed>=total else '−'}{number(abs(proposed/total-1)*100,1)}%</strong></div><div><span>Legajos con menor pago</span><strong>{losers}</strong></div><div><span>Perfiles entre 70% y 80% de las jornadas</span><strong>{len(centered)} de {len(comparable)}</strong></div></div>
      <div class="closing-findings"><article class="compact-finding"><span>Mayor desvío del 75%</span><h3>{escape(furthest['sector'])} · {escape(operation_title(furthest))}</h3><strong>{number(furthest['cumple']/furthest['dias']*100,1)}%</strong><p>El 75% es una referencia aproximada. Los umbrales se redondearon y Secos Armado comparte un único valor entre ambas zonas.</p><button class="detail-button" data-open-profile="{furthest['id']}">Ver el caso</button></article><article class="compact-finding"><span>Mayor cantidad de bajas</span><h3>{escape(most_losers['sector'])} · {escape(operation_title(most_losers))}</h3><strong>{most_losers['menos']} de {most_losers['personas']} cobran menos</strong><p>Revisar estos casos junto con el aumento total de la bolsa antes de cerrar los importes.</p><button class="detail-button" data-open-profile="{most_losers['id']}">Ver el caso</button></article><article class="compact-finding"><span>Base pendiente</span><h3>Recepción Secos Zona 1</h3><strong>Sin nómina asociada</strong><p>La falta de base se mantiene visible y no se interpreta como cumplimiento ni como incumplimiento.</p><button class="detail-button" data-open-profile="perfil-4">Ver el caso</button></article></div>
      <aside class="closing-decision"><strong>Una bolsa mayor puede coexistir con personas que cobran menos.</strong><span>Cada ajuste de umbral o reparto necesita una nueva simulación por legajo antes de aprobarse.</span></aside>
    </section>'''


def economic_summary(report, number):
    rows = []
    for p in report['perfiles']:
        old, new = p['actual_centavos'], p['nuevo_centavos']
        pct = (new / old - 1) * 100 if old else None
        label = operation_title(p) + (f' · {p["camara"]}' if p.get('camara') else '')
        rows.append(f'''<tr><td>{escape(p['sector'])}<small>{escape(p['funcion'])}</small></td><td>{escape(label)}</td><td>$ {number(old/100)}</td><td>$ {number(new/100)}</td><td class="{'positive' if new>=old else 'negative'}">{'+' if new>=old else '−'}$ {number(abs(new-old)/100)}</td><td>{('+' if pct is not None and pct>=0 else '')+number(pct,1)+'%' if pct is not None else 'Sin base'}</td></tr>''')
    old_total = sum(p['actual_centavos'] for p in report['perfiles'])
    new_total = sum(p['nuevo_centavos'] for p in report['perfiles'])
    pct_total = (new_total / old_total - 1) * 100 if old_total else 0
    return f'''<section class="sheet compact-sheet economic-summary" id="resumen-economico"><div class="compact-heading"><div><span class="eyebrow">Comparación económica</span><h2>Pago actual y propuesta por perfil</h2></div><span class="compact-period">Agosto–septiembre 2026</span></div><div class="economic-table"><table><thead><tr><th>División / función</th><th>Operación</th><th>Pago actual</th><th>Pago nuevo</th><th>Diferencia</th><th>Variación</th></tr></thead><tbody>{''.join(rows)}</tbody><tfoot><tr><td colspan="2">Total</td><td>$ {number(old_total/100)}</td><td>$ {number(new_total/100)}</td><td>{'+' if new_total>=old_total else '−'}$ {number(abs(new_total-old_total)/100)}</td><td>{'+' if pct_total>=0 else ''}{number(pct_total,1)}%</td></tr></tfoot></table></div><p class="compact-footnote">El pago actual reúne las operaciones históricas equivalentes. El pago nuevo suma los componentes aplicables del escenario recalculado.</p></section>'''


def scale_dialog(p, number):
    rows = [f'<tr><td>Grupal</td><td>{number(p["objetivo"])} {escape(p["unidad"])}</td><td>$ {number(p["premio_grupal"])}</td></tr>']
    rows += [f'<tr><td>N{s["nivel"]}</td><td>{number(s["desde_uc"])} {escape(p["unidad"])}</td><td>$ {number(s["premio"])}</td></tr>' for s in p['escala_individual']]
    return f'''<dialog class="profile-dialog scale-dialog" id="detalle-escala-{p['id']}"><div class="dialog-heading"><div><span>{escape(p['sector'])} · {escape(p['funcion'])}</span><h2>{escape(operation_title(p))} · Escala vigente</h2></div><button type="button" class="control-button" data-close-profile>Cerrar ×</button></div><div class="dialog-body"><table><thead><tr><th>Nivel</th><th>Desde</th><th>Premio diario</th></tr></thead><tbody>{''.join(rows)}</tbody></table><p class="dialog-criteria">Los cinco niveles individuales fueron recalculados desde el umbral grupal: +10%, luego +5%, +10%, +15% y +20% respecto del nivel anterior. Los importes son los vigentes en la aplicación.</p></div></dialog>'''


def profiles_dialog(report):
    rows = ''.join(f'<tr><td>{escape(p["sector"])}</td><td>{escape(p["funcion"])}</td><td>{escape(operation_title(p))}</td><td>{escape(p.get("camara") or p.get("division") or "—")}</td></tr>' for p in report['perfiles'])
    return f'''<dialog class="profile-dialog" id="detalle-perfiles-analizados"><div class="dialog-heading"><div><span>Alcance del estudio</span><h2>17 perfiles analizados</h2></div><button type="button" class="control-button" data-close-profile>Cerrar ×</button></div><div class="dialog-body"><p>Un perfil combina sector, función de legajero, operación medible y, cuando corresponde, división o cámara. Los turnos comparten parámetros y se consolidan en la presentación.</p><table><thead><tr><th>Sector</th><th>Función</th><th>Operación</th><th>División / cámara</th></tr></thead><tbody>{rows}</tbody></table></div></dialog>'''


def dialog(p, chart, number, report):
    refs = ''.join(f'<div><span>Acceso {r["pct"]}%</span><strong>{number(r["umbral"]) if r["umbral"] is not None else "—"} {p["unidad"]}</strong><small>{str(r["dias_logrados"])+" días" if r["umbral"] is not None else "Sin base"}</small></div>' for r in p['referencias'])
    return f'''<dialog class="profile-dialog" id="detalle-{p['id']}" aria-labelledby="titulo-{p['id']}"><div class="dialog-heading"><div><span>{escape(p['sector'])} · {escape(p['funcion'])}</span><h2 id="titulo-{p['id']}">{escape(operation_title(p))}</h2></div><button type="button" class="control-button" data-close-profile aria-label="Cerrar detalle">Cerrar ×</button></div><div class="dialog-body">{chart(p)}<div class="dialog-refs">{refs}</div><div class="dialog-pay"><h3>Pago propuesto vigente</h3><p>Actual: $ {number(p['actual_centavos']/100)} · Propuesto: $ {number(p['nuevo_centavos']/100)} · Variación: {budget(p,number)}</p>{people_bar(p)}</div><h3>Calendario diario del umbral vigente</h3><div class="dialog-calendar">{''.join(f'<span class="{"hit" if d["cumple"] else ""}"><b>{d["fecha"][6:8]}/{d["fecha"][4:6]}</b>{"Alcanza" if d["cumple"] else ("Sin base" if not d["base"] else "No alcanza")}</span>' for d in p['diario'])}</div><div class="dialog-criteria"><h3>Alcance y criterios</h3><p>Umbral diario = producción computable / [nómina computable × (1 − factor de ausentismo)]. Factor de este perfil: {number(p['factor'])}%. Se exige superar estrictamente la meta. Las referencias enteras y los empates pueden producir más días que el porcentaje objetivo.</p><p>Calendario común de {report['dias']} días de lunes a viernes, sin excluir feriados. Los días sin base permanecen visibles. La curva consolida turnos. El pago comparado incluye grupal, individual y polivalencia con la liquidación vigente por turno. La referencia del 50% no tiene pagos recalculados.</p><p>Los perfiles y la nómina son actuales. No se reconstruyen transferencias históricas. Cache grupal: {escape(report['cache_grupal'])} UTC. Snapshot de pagos: {escape(report['snapshot_pagos'])}.</p></div></div></dialog>'''


def slides(report, chart, number):
    profiles = {p['id']: p for p in report['perfiles']}
    output = [cover(report,number), method(report)]
    for ident, title, subtitle, ids in PAGES:
        selected = [profiles[f'perfil-{i}'] for i in ids]
        if any(p.get('piloto_legajos') for p in selected):
            output.append(piloto.integrated(report,selected,ident,title,number))
            continue
        note = '<div class="compact-pending"><b>Recepción Zona 1:</b> sin nómina asociada. <button type="button" data-open-profile="perfil-4">Ver pendiente</button></div>' if ident == 'secos-carga-recepcion' else ''
        output.append(f'''<section class="sheet compact-sheet {'single-sheet' if len(ids)==1 else ''}" id="{ident}"><div class="compact-heading"><div><span class="eyebrow">{escape(subtitle)}</span><h2>{escape(title)}</h2></div><span class="compact-period">{report['dias']} días · Agosto y septiembre 2026</span></div><div class="compact-profiles">{''.join(profile(p,number,len(ids)==1) for p in selected)}</div>{note}<p class="compact-footnote">Acceso: sector consolidado. Pagos: escenario vigente por turno. La alternativa del 50% requiere simulación económica.</p></section>''')
    output.append(economic_summary(report,number))
    output.append(conclusion(report,number))
    return ''.join(output)


def dialogs(report, chart, number):
    return (''.join(dialog(p,chart,number,report) for p in report['perfiles'])
            + ''.join(scale_dialog(p,number) for p in report['perfiles'])
            + profiles_dialog(report) + piloto.dialogs(report,number))
