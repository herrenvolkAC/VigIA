"""Piloto auditable de participación y variación de pagos de Armado."""
from collections import Counter
from html import escape

COLORS = ['#cbd5df','#7db59b','#70a8d3','#d9ba6c','#c98b79','#8068af']


def cases(report):
    result=[]
    for p in report['perfiles']:
        for person in p.get('piloto_legajos',[]):
            rows=person['dias']
            sums={k:sum(r[k] for r in rows) for k in ('actual','grupal','individual','polivalencia','grupal_potencial')}
            new=sum(sums[k] for k in ('grupal','individual','polivalencia'))
            result.append(dict(person,sector=p['sector'],perfil=p['id'],unidad=p['unidad'],historico=', '.join(p.get('operaciones_historicas', ['PICKING'])),**sums,nuevo=new,diferencia=new-sums['actual']))
    return result


def monetary_explanation(c,n):
    deficit=c['actual']-c['individual']
    complement=c['grupal']+c['polivalencia']
    if deficit>0:
        verb='solo compensan' if c['diferencia']<0 else 'compensan'
        return f'Individual nuevo: $ {n(deficit/100)} menos que el histórico; grupal + polivalencia {verb} $ {n(complement/100)}.'
    return f'Individual nuevo: $ {n(-deficit/100)} más que el histórico; grupal + polivalencia suman $ {n(complement/100)}.'


def payment_days(c):
    rows=c['dias']
    old={r['fecha'] for r in rows if r['actual']>0}
    individual={r['fecha'] for r in rows if r['individual']>0}
    group={r['fecha'] for r in rows if r['grupal']>0}
    poly={r['fecha'] for r in rows if r['polivalencia']>0}
    missed={r['fecha'] for r in rows if r['falta_grupal']}
    return old,individual,group,poly,missed


def explanation(c,n):
    old,individual,group,poly,missed=payment_days(c)
    if not old and group:
        return f'Antes no cobraba por esta operación; ahora cobra grupal en {len(group)} días e individual en {len(individual)}.'
    if c['diferencia']>0 and c['polivalencia']>max(c['grupal'],c['individual']):
        return f'Antes cobraba por esta operación en {len(old)} días; ahora suma polivalencia en {len(poly)}. Revisar histórico de otras tareas.'
    lost=len(old-individual)
    if c['diferencia']<0 and lost:
        return f'De {len(old)} días antes pagos, {lost} quedan sin individual nuevo. Cobra grupal en {len(group)}, pero no compensa la baja.'
    if c['diferencia']<0 and old and old<=individual:
        affected=len(old & individual & missed)
        if affected:
            return f'Conserva individual en los {len(old)} días antes pagos; en {affected} su turno no alcanza el grupal. La suma final baja.'
        return f'Conserva individual en los {len(old)} días antes pagos y cobra grupal en {len(group)}, pero la suma es menor al histórico.'
    if c['diferencia']>0 and c['individual']<c['actual']:
        return f'El individual baja; el grupal de {len(group)} días y la polivalencia de {len(poly)} lo compensan y cobra más.'
    if c['diferencia']>0:
        return f'Antes cobraba en {len(old)} días; ahora cobra individual en {len(individual)} y grupal en {len(group)}. La suma aumenta.'
    return f'Antes cobraba en {len(old)} días; ahora individual en {len(individual)} y grupal en {len(group)}. Ver importes por día.'


def day_comparison(c):
    old,individual,group,poly,missed=payment_days(c)
    return f'<h3>Cómo cambian los días de cobro</h3><p>Histórico de esta operación: {len(old)} días. Individual nuevo: {len(individual)}; conserva {len(old & individual)} de los días antes pagos, deja de cobrar individual en {len(old-individual)} y empieza a cobrarlo en {len(individual-old)} fechas adicionales. Grupal: {len(group)} días; polivalencia: {len(poly)} días.</p><p>En {len(individual & missed)} días cobra individual pero no alcanza el grupal por la meta de su turno; {len(old & individual & missed)} de ellos ya tenían pago histórico. Los componentes pueden coincidir: no se suman como días distintos. Estar sin individual nuevo no prueba por sí solo un cambio de umbral: puede deberse a elegibilidad o actividad; el detalle permite revisarlo.</p>'


def daily_explanation(c,n):
    buckets={label:[] for label in ('Con grupal','Sin grupal por meta del turno','Con polivalencia','Otras jornadas')}
    for r in c['dias']:
        label=('Con grupal' if r['grupal']>0 else 'Con polivalencia' if r['polivalencia']>0 else 'Sin grupal por meta del turno' if r['falta_grupal'] else 'Otras jornadas')
        buckets[label].append(r)
    body=[]
    for label,rows in buckets.items():
        if not rows:continue
        old=sum(r['actual'] for r in rows)
        new=sum(r['individual']+r['grupal']+r['polivalencia'] for r in rows)
        body.append(f'<tr><td>{label}</td><td>{len(rows)}</td><td>$ {n(old/100)}</td><td>$ {n(new/100)}</td><td>$ {n((new-old)/100)}</td></tr>')
    return '<h3>Dónde se produce la diferencia</h3><p>Comparación de las mismas jornadas. Las categorías no se superponen y sus diferencias suman la variación total. Una baja en jornadas con grupal indica que los nuevos importes no compensan el histórico, aun cobrando ese componente. Las otras jornadas requieren revisar su detalle; no se atribuyen automáticamente a actividad excluida.</p><table><thead><tr><th>Jornadas</th><th>Días</th><th>Histórico</th><th>Nuevo completo</th><th>Diferencia</th></tr></thead><tbody>'+''.join(body)+'</tbody></table>'


def selected(report):
    allcases=cases(report)
    return (sorted((c for c in allcases if c['diferencia']>0),key=lambda c:(-c['diferencia'],c['legajo']))[:5],sorted((c for c in allcases if c['diferencia']<0),key=lambda c:(c['diferencia'],c['legajo']))[:5])


def integrated(report, profiles, ident, title, n, include_payroll=False, payroll_details=None):
    scoped=dict(report,perfiles=profiles)
    all_rows=[r for p in profiles for c in p.get('piloto_legajos',[]) for r in c['dias']]
    rows=[r for r in all_rows if r['evaluado']]
    poly_events=sum(r['polivalencia']>0 for r in all_rows)
    zero_events=sum(r['grupal']==0 and r['individual']==0 and r['polivalencia']==0 for r in rows)
    group_events=sum(r['grupal']>0 for r in rows)
    level_events=[sum(r['nivel']>=i for r in rows) for i in range(1,6)]
    labels=['Polivalencia','0 · Sin premio','Grupal','N1','N2','N3','N4','N5']
    counts=[poly_events,zero_events,group_events]+level_events
    colors=['#168b83','#b6c2cb',COLORS[0],*COLORS[1:]]
    peak=max(counts,default=0) or 1
    bar_max=112
    bars=''.join(f'<div class="pilot-bar" title="{labels[i]}: {n(v)} jornadas"><b>{n(v)}</b><i style="height:{v/peak*bar_max}px;background:{colors[i]}"></i><span>{labels[i]}</span></div>' for i,v in enumerate(counts))
    metrics=[]
    for p in profiles:
        ref=p['referencias'][1]
        if not p['con_base']:
            payroll_button = f'<button class="detail-button payroll-open" data-open-payroll="{p["id"]}" aria-haspopup="dialog">Nómina y actividad</button>' if include_payroll else ''
            metrics.append(f'<div class="integrated-access"><b>{escape(p["sector"])}</b><p>Sin nómina asociada / sin base evaluable.</p><div class="integrated-actions">{payroll_button}<button class="detail-button" data-open-profile="{p["id"]}">Ver pendiente</button></div></div>')
            continue
        payroll_button = f'<button class="detail-button payroll-open" data-open-payroll="{p["id"]}" aria-haspopup="dialog">Nómina y actividad</button>' if include_payroll else ''
        metrics.append(f'<div class="integrated-access"><b>{escape(p["sector"])}{(" · "+escape(p["camara"])) if p.get("camara") else ""}</b><div><span>Umbral <strong>{n(p["objetivo"])} {escape(p["unidad"])}</strong></span><span>Cobra el grupo <strong>{p["cumple"]}/{p["dias"]} días · {n(100*p["cumple"]/p["dias"],1)}%</strong></span><span>Referencia 50% <strong>{n(ref["umbral"]) if ref["umbral"] is not None else "—"} {escape(p["unidad"])}</strong></span></div><div class="integrated-actions">{payroll_button}<button class="detail-button" data-open-profile="{p["id"]}">Curva y detalle</button><button class="detail-button" data-open-profile="escala-{p["id"]}">Escala y montos</button></div></div>')
    old=sum(p['actual_centavos'] for p in profiles);new=sum(p['nuevo_centavos'] for p in profiles)
    group=sum(r['grupal'] for p in profiles for person in p.get('piloto_legajos',[]) for r in person.get('dias',[]))
    individual=sum(r['individual'] for p in profiles for person in p.get('piloto_legajos',[]) for r in person.get('dias',[]))
    poly=sum(r['polivalencia'] for p in profiles for person in p.get('piloto_legajos',[]) for r in person.get('dias',[]))
    group_share=100*group/new if new else 0
    individual_share=100*individual/new if new else 0
    poly_share=100*poly/new if new else 0
    roster_button = f'<button type="button" class="poly-summary-button roster-summary-button" data-open-profile="nomina-resumen-{ident}" aria-haspopup="dialog">Ver nómina del legajero</button>' if payroll_details is not None else ''
    totals=f'<div class="integrated-totals"><span>Actual de la operación <b>$ {n(old/100)}</b></span><span>Nuevo completo <b>$ {n(new/100)}</b></span><span>Diferencia <b>{"+" if new>=old else "−"}$ {n(abs(new-old)/100)}</b></span><span>Legajos más / menos <b>{sum(p["mas"] for p in profiles)} / {sum(p["menos"] for p in profiles)}</b>{roster_button}</span><span><span class="metric-title">Pago grupal</span><b>$ {n(group/100)}</b><small>{n(group_share,1)}% del pago nuevo total · ARS · agosto–septiembre</small></span><span><span class="metric-title">Pago individual</span><b>$ {n(individual/100)}</b><small>{n(individual_share,1)}% del pago nuevo total · ARS · agosto–septiembre</small></span><span><span class="metric-title">Polivalencia</span><b>$ {n(poly/100)}</b><small>{n(poly_share,1)}% del pago nuevo total · ARS · agosto–septiembre</small><button type="button" class="poly-summary-button" data-open-profile="poly-summary-{ident}" aria-haspopup="dialog">Ver resumen</button></span></div>'
    columns=[]
    for heading,items in zip(('Mayores aumentos','Mayores disminuciones'),selected(scoped)):
        cards=[]
        for c in items:
            reason=explanation(c,n)
            cards.append(f'<button class="integrated-case" data-open-profile="caso-{c["perfil"]}-{c["legajo"]}" aria-label="Ver explicación del legajo {c["legajo"]}"><div><b>{c["legajo"]}</b><strong>{"+" if c["diferencia"]>0 else "−"}$ {n(abs(c["diferencia"])/100)}</strong></div><p>{reason}</p></button>')
        columns.append(f'<div><h3>{heading}</h3>{"".join(cards) or "<p>No hay legajos en esta condición.</p>"}</div>')
    return f'<section class="sheet compact-sheet integrated-sheet" id="{ident}"><div class="compact-heading"><div><span class="eyebrow">Agosto–septiembre 2026 · Lunes a viernes</span><h2>{escape(title)}</h2></div></div><section class="integrated-band band-economic"><h3 class="band-title">01 <span>Impacto económico</span></h3>{totals}</section><section class="integrated-band band-access"><h3 class="band-title">02 <span>Cómo se alcanza el premio</span></h3><div class="integrated-top"><div class="integrated-group-panel"><h3>Acceso al grupal</h3>{"".join(metrics)}</div><div class="integrated-participation"><h3>Participación · jornadas por nivel</h3><div class="pilot-bars">{bars}</div><p>Polivalencia = jornadas con pago de polivalencia; puede coincidir con N1–N5. N1–N5 son acumulados: N5 también cuenta en los anteriores. “0 · Sin premio” = presentes evaluables sin pago grupal, individual ni polivalencia. Ausencias y jornadas sin base no cuentan.</p></div></div></section><section class="integrated-band band-impact"><h3 class="band-title">03 <span>Impacto en las personas</span><small>Seleccioná un legajo para ver importes y explicación completa</small></h3><div class="integrated-rankings">{"".join(columns)}</div></section><p class="pilot-note">Acceso: sector consolidado. Pagos: por turno. Actual: operaciones equivalentes; nuevo: grupal + individual + polivalencia.</p></section>'


def slides(report,n):
    profiles=[p for p in report['perfiles'] if p.get('piloto_legajos')]
    if not profiles:return ''
    charts=[]
    for p in profiles:
        rows=[r for c in p['piloto_legajos'] for r in c['dias'] if r['evaluado']]
        counts=[sum(r['nivel']==i for r in rows) for i in range(6)]
        bars=''.join(f'<div class="pilot-bar"><b>{v}</b><i style="height:{v/max(counts or [1],default=1)*170 if max(counts,default=0) else 0}px;background:{COLORS[i]}"></i><span>{"Sin nivel" if i==0 else "N"+str(i)}</span></div>' for i,v in enumerate(counts))
        charts.append(f'<article class="pilot-chart"><h3>{escape(p["sector"])}{(" · "+escape(p["camara"])) if p.get("camara") else ""}</h3><div class="pilot-bars">{bars}</div><p>{len(rows)} jornadas evaluadas · {sum(r["grupal"]>0 for r in rows)} con grupal</p></article>')
    distribution=f'<section class="sheet compact-sheet" id="piloto-distribucion"><div class="compact-heading"><div><span class="eyebrow">Piloto · Armado Secos y NOA</span><h2>Qué nivel alcanza cada jornada</h2></div></div><div class="pilot-charts">{"".join(charts)}</div><p class="pilot-note">Cada legajo-día cuenta una vez, en su nivel máximo. Presentes aplicables con escala. El grupal puede coincidir con cualquier nivel individual.</p><p class="pilot-note">Agosto–septiembre 2026 · Lunes a viernes · Todos los turnos. Esta distribución es exclusiva; la pantalla Participación individual muestra niveles acumulados.</p></section>'
    columns=[]
    for title,items in zip(('5 mayores aumentos','5 mayores disminuciones'),selected(report)):
        cards=[]
        for c in items:
            cards.append(f'<button class="pilot-case" data-open-profile="caso-{c["perfil"]}-{c["legajo"]}"><header><b>Legajo {c["legajo"]}</b><strong>{"+" if c["diferencia"]>0 else "−"}$ {n(abs(c["diferencia"])/100)}</strong></header><small>{escape(c["sector"])}</small><div>Actual $ {n(c["actual"]/100)} → Nuevo $ {n(c["nuevo"]/100)}</div><p>{explanation(c,n)}</p></button>')
        columns.append(f'<div class="pilot-ranking"><h3>{title}</h3>{"".join(cards)}</div>')
    ranking=f'<section class="sheet compact-sheet" id="piloto-impacto"><div class="compact-heading"><div><span class="eyebrow">Piloto · Armado Secos y NOA · Diferencia en pesos sobre la base del informe</span><h2>Por qué cambia el pago</h2></div></div><div class="pilot-columns">{"".join(columns)}</div><p class="pilot-note">43 días hábiles. Actual: histórico PICKING. Nuevo: grupal + individual + polivalencia. No compara la liquidación completa de otras tareas. Clic para auditar.</p></section>'
    return distribution+ranking


def dialogs(report,n,payroll_details=None):
    out=[]
    groups=[]
    from gerencial_umbrales_compacto import PAGES
    for _,_,_,ids in PAGES:
        scoped=dict(report,perfiles=[p for p in report['perfiles'] if p['id'] in {f'perfil-{i}' for i in ids}])
        groups.extend(selected(scoped))
    for group in groups:
        for c in group:
            rows=''.join('<tr>'+''.join(f'<td>{escape(str(v))}</td>' for v in [r['fecha'],r['turno'],n(r['uc']),r['nivel'],n(r['actual']/100),n(r['grupal']/100),n(r['individual']/100),n(r['polivalencia']/100),n((r['grupal']+r['individual']+r['polivalencia']-r['actual'])/100),r['estado'] if r['falta_grupal'] else r['asistencia']])+'</tr>' for r in c['dias'])
            gap=c['grupal_potencial']
            other=c['diferencia']+gap
            out.append(f'<dialog class="profile-dialog" id="detalle-caso-{c["perfil"]}-{c["legajo"]}"><div class="dialog-heading"><h2>Legajo {c["legajo"]} · {escape(c["sector"])}</h2><button data-close-profile class="control-button">Cerrar ×</button></div><div class="dialog-body"><h3>{explanation(c,n)}</h3><p>Pago anterior $ {n(c["actual"]/100)} → Propuesta $ {n(c["nuevo"]/100)}. Diferencia: $ {n(c["diferencia"]/100)}.</p><p>{monetary_explanation(c,n)}</p>{day_comparison(c)}{daily_explanation(c,n)}<h3>Cuánto pesa el acceso al grupal</h3><p>En {sum(r["falta_grupal"] for r in c["dias"])} jornadas era beneficiario, pero su turno no superó la meta. El grupal adicional si esos días hubieran cumplido sería $ {n(gap/100)}.</p><p>Descomposición: cambio con ese grupal hipotético ($ {n(other/100)}) − grupal no alcanzado ($ {n(gap/100)}) = diferencia observada ($ {n(c["diferencia"]/100)}). Es una sensibilidad, no un pago adeudado ni una atribución causal del total.</p><p>Grupal: $ {n(c["grupal"]/100)} · Individual: $ {n(c["individual"]/100)} · Polivalencia: $ {n(c["polivalencia"]/100)}. El pago anterior corresponde a {escape(c["historico"])}; no se infiere su nivel histórico a partir del importe. La liquidación grupal es por turno, aunque los gráficos generales consolidan el sector.</p><table><thead><tr>{"".join("<th>"+s+"</th>" for s in ["Fecha","Turno",c["unidad"],"Nivel nuevo","Actual $","Grupal $","Individual $","Poliv. $","Diferencia $","Situación"])}</tr></thead><tbody>{rows}</tbody></table></div></dialog>')
    from gerencial_umbrales_compacto import PAGES
    by_id = {p['id']: p for p in report['perfiles']}
    for p in report['perfiles']:
        out.append(poly_summary_dialog([p], f'poly-summary-{p["id"]}',
                                       f'{p["sector"]} · {p["funcion"]} · {p["operacion"]}' + (f' · {p["camara"]}' if p.get('camara') else ''), n))
    for ident, title, _, ids in PAGES:
        profiles = [by_id[f'perfil-{i}'] for i in ids if f'perfil-{i}' in by_id]
        if profiles:
            out.append(poly_summary_dialog(profiles, f'poly-summary-{ident}', title, n))
            if payroll_details is not None and any(p.get('piloto_legajos') for p in profiles):
                out.append(roster_summary_dialog(profiles, ident, title, payroll_details, n))
    return ''.join(out)


def roster_summary_dialog(profiles, ident, title, payroll_details, n):
    """Nómina de legajero con días que tienen actividad PV observada."""
    people = {}
    payments = {}
    for profile in profiles:
        for person in profile.get('piloto_legajos', []):
            legajo = str(person.get('legajo') or '').strip()
            if not legajo:
                continue
            totals = payments.setdefault(legajo, {'actual': 0, 'nuevo': 0})
            for day in person.get('dias', []):
                totals['actual'] += day.get('actual', 0)
                totals['nuevo'] += day.get('grupal', 0) + day.get('individual', 0) + day.get('polivalencia', 0)
    for profile in profiles:
        for row in (payroll_details or {}).get(profile['id'], []):
            legajo = str(row.get('legajo') or '').strip()
            if not legajo:
                continue
            item = people.setdefault(legajo, {
                'nombre': row.get('nombre') or '', 'sectores': set(), 'dias': {}, 'turnos': Counter()
            })
            if row.get('nombre'):
                item['nombre'] = row['nombre']
            item['sectores'].add(profile['sector'])
            fecha = str(row.get('fecha') or '')
            if not fecha:
                continue
            day = item['dias'].setdefault(fecha, {'actividad': False, 'turnos': set()})
            day['actividad'] = day['actividad'] or bool(row.get('actividades'))
            turno = str(row.get('turno') or '').strip()
            if turno:
                day['turnos'].add(turno)
    body = []
    for legajo, item in sorted(people.items(), key=lambda pair: (int(pair[0]) if pair[0].isdigit() else 0, pair[0])):
        for day in item['dias'].values():
            for turno in day['turnos']:
                item['turnos'][turno] += 1
        active = sum(day['actividad'] for day in item['dias'].values())
        inactive = len(item['dias']) - active
        shifts = ' · '.join(f'T{escape(turno)} ({n(count)} días)' for turno, count in sorted(item['turnos'].items())) or '—'
        pay = payments.get(legajo)
        if pay is None:
            result = '<span class="pay-result pay-unavailable"><b aria-hidden="true">·</b><span>Sin comparación</span></span>'
        else:
            difference = pay['nuevo'] - pay['actual']
            if difference > 0:
                result = f'<span class="pay-result pay-more" aria-label="Cobra más: aumento de {n(difference/100)} pesos"><b aria-hidden="true">↑</b><span>Cobra más</span><small>+$ {n(difference/100)}</small></span>'
            elif difference < 0:
                result = f'<span class="pay-result pay-less" aria-label="Cobra menos: disminución de {n(abs(difference)/100)} pesos"><b aria-hidden="true">↓</b><span>Cobra menos</span><small>−$ {n(abs(difference)/100)}</small></span>'
            else:
                result = '<span class="pay-result pay-same" aria-label="Sin variación de pago"><b aria-hidden="true">=</b><span>Sin variación</span><small>$ 0</small></span>'
        body.append(f'<tr><td>{escape(legajo)}</td><td>{escape(item["nombre"] or "—")}</td><td>{shifts}</td><td>{n(active)}</td><td>{n(inactive)}</td><td>{result}</td></tr>')
    total = len(people)
    return f'''<dialog class="profile-dialog roster-summary-dialog" id="detalle-nomina-resumen-{ident}" aria-labelledby="titulo-nomina-resumen-{ident}">
      <div class="dialog-heading"><div><span>Nómina vigente del legajero · Agosto–septiembre 2026</span><h2 id="titulo-nomina-resumen-{ident}">{escape(title)} · Nómina y actividad</h2></div><button type="button" class="control-button" data-close-profile aria-label="Cerrar nómina">Cerrar ×</button></div>
      <div class="dialog-body"><div class="roster-summary-kpis"><span>Legajos del alcance <b>{n(total)}</b></span><span>Días del período <b>{n(len(next(iter(people.values()))['dias']) if people else 0)}</b></span></div>
        <p class="roster-summary-note">La nómina corresponde al legajero vigente. “Con actividad” y “sin actividad” cuentan jornadas del período. El resultado compara el pago nuevo completo con el actual; flecha verde: cobra más, flecha roja: cobra menos, gris: sin variación.</p>
        <div class="table-wrap roster-summary-table-wrap"><table><thead><tr><th>Legajo</th><th>Nombre</th><th>Turno(s) observados</th><th>Días con actividad</th><th>Días sin actividad</th><th>Resultado · nuevo método</th></tr></thead><tbody>{''.join(body) or '<tr><td colspan="6">Sin filas de nómina disponibles para este alcance.</td></tr>'}</tbody></table></div>
      </div></dialog>'''


def poly_summary_dialog(profiles, ident, title, n):
    summaries = [p.get('polivalencia_resumen', {}) for p in profiles]
    events = {(str(legajo), str(fecha)) for s in summaries for legajo, fecha in s.get('_eventos', [])}
    origins, reasons = Counter(), Counter()
    for s in summaries:
        origins.update({row['nombre']: row['eventos'] for row in s.get('origenes', [])})
        reasons.update({row['nombre']: row['eventos'] for row in s.get('motivos', [])})
    paid = sum(s.get('pago_centavos', 0) for s in summaries)
    n_days = len({fecha for _, fecha in events})
    kpis = ''.join([
        f'<div><span>Pago de polivalencia</span><b>$ {n(paid/100)}</b></div>',
        f'<div><span>Legajo-días con polivalencia</span><b>{n(len(events))}</b></div>',
        f'<div><span>Legajos distintos</span><b>{n(len({legajo for legajo, _ in events}))}</b></div>',
        f'<div><span>Días con al menos un caso</span><b>{n(n_days)}</b></div>',
    ])
    def list_rows(counter):
        top = counter.most_common(6)
        peak = max((count for _, count in top), default=1)
        return ''.join(f'<li><span>{escape(label)}</span><b>{n(count)}</b><i><em style="width:{count/peak*100:.1f}%"></em></i></li>' for label, count in top) or '<li class="poly-empty">Sin casos clasificados en el período.</li>'
    note = 'Los orígenes y motivos pueden coexistir en un mismo legajo-día; sus cantidades no se suman para obtener el total de eventos.'
    return f'''<dialog class="profile-dialog poly-summary-dialog" id="detalle-{ident}" aria-labelledby="titulo-{ident}"><div class="dialog-heading"><div><span>Agosto–septiembre 2026 · lunes a viernes</span><h2 id="titulo-{ident}">Resumen de polivalencias</h2><p>{escape(title)}</p></div><button type="button" class="control-button" data-close-profile aria-label="Cerrar resumen">Cerrar ×</button></div><div class="dialog-body"><div class="poly-summary-kpis">{kpis}</div><div class="poly-summary-lists"><section><h3>Operaciones o divisiones de origen</h3><ul>{list_rows(origins)}</ul></section><section><h3>Motivos detectados</h3><ul>{list_rows(reasons)}</ul></section></div><p class="poly-summary-note">{note}</p></div></dialog>'''
