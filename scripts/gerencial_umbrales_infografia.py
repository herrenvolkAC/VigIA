"""Pilotos de comparación visual: Carga Refri y Clark NOA, misma fotografía de datos."""
from html import escape
from gerencial_umbrales_visual import embedded


def assets_css():
    return ':root{--worker-poses:url("' + embedded('operarios_gestos_niveles.png', 'image/png') + '")}'


def access_level(reached, days, has_base=True):
    """El gesto describe el acceso al grupal, no la variación del pago."""
    if not has_base or not days:
        return 'neutral', 'Sin base para evaluar', 'Expresión neutral: sin base para evaluar'
    pct = reached / days * 100
    if pct < 25:
        return 'concerned', 'Acceso muy poco frecuente', 'Gesto preocupado: menos del 25% de los días'
    if pct < 50:
        return 'serious', 'Acceso poco frecuente', 'Gesto serio: del 25% a menos del 50% de los días'
    if pct < 75:
        return 'satisfied', 'Acceso intermedio', 'Sonrisa moderada: del 50% a menos del 75% de los días'
    return 'confident', 'Acceso frecuente', 'Gesto satisfecho: desde el 75% de los días'


def calendar(p, threshold):
    cells = []
    reached = 0
    for day in p['diario']:
        hit = bool(day['base'] and day['produccion'] > threshold * day['base'])
        reached += hit
        date = f"{day['fecha'][6:8]}/{day['fecha'][4:6]}"
        text = f"{date}: {'alcanza' if hit else 'no alcanza'} el objetivo con {threshold:g} {p['unidad']}"
        cells.append(f'<span class="calendar-day {"reached" if hit else ""}" title="{escape(text)}" aria-label="{escape(text)}"></span>')
    return f'<div class="story-calendar" role="group" aria-label="{reached} de {p["dias"]} jornadas alcanzan el objetivo">{"".join(cells)}</div>', reached


def story(p, chart, number, title, style):
    ref = p['referencias'][1]
    if ref['umbral'] is None:
        raise ValueError('El piloto requiere una referencia del 50% válida.')
    current_calendar, count = calendar(p, p['objetivo'])
    ref_calendar, ref_count = calendar(p, ref['umbral'])
    assert count == p['cumple'] and ref_count == ref['dias_logrados']
    current_pct = count/p['dias']*100
    ref_pct = ref_count/p['dias']*100
    has_base = any(day['base'] > 0 for day in p['diario'])
    left_pose, current_status, left_label = access_level(count, p['dias'], has_base)
    right_pose, target_status, right_label = access_level(ref_count, p['dias'], has_base)
    expands = ref_count > count
    if expands:
        message = f'Evaluar {number(ref["umbral"])} {p["unidad"]} para ampliar el acceso al grupal.'
        qualification = 'Simular el costo y el pago por legajo antes de decidir.'
    else:
        message = 'El grupo ya alcanza el objetivo todos los días del período.' if count == p['dias'] else 'El umbral vigente permite mayor o igual acceso que la referencia.'
        qualification = 'Priorizar la distribución del premio. Bajar el umbral no amplía el acceso.' if count == p['dias'] else 'Evaluar la distribución del premio antes de modificar el umbral.'
    cash_change = (p['nuevo_centavos']/p['actual_centavos']-1)*100 if p['actual_centavos'] else 0
    return f'''<section class="sheet profile story-profile" id="{p['id']}" style="{style}">
      <div class="story-heading"><div><div class="eyebrow">{escape(p['sector'])} · {escape(title)}</div><h2>¿Cuántos días alcanza el premio el equipo?</h2></div><div class="story-period"><strong>{p['dias']}</strong><span>jornadas evaluadas<br>Agosto + septiembre 2026</span></div></div>
      <div class="story-scenes">
        <article class="story-scene current-scene"><div class="scene-heading"><span>UMBRAL VIGENTE</span><b>{current_status}</b></div><div class="scene-body"><div class="worker-pose {left_pose}" data-access-level="{left_pose}" role="img" aria-label="{escape(left_label)}" title="{escape(left_label)}"></div><div class="scene-facts"><div class="scene-threshold"><strong>{number(p['objetivo'])}</strong><span>{p['unidad']} / operario</span></div><div class="scene-days"><strong>{count}</strong><span>de {p['dias']} días</span><b>{number(current_pct,1)}%</b></div>{current_calendar}<div class="calendar-key"><i></i>Día que alcanza el objetivo</div></div></div></article>
        <article class="story-scene reference-scene {'expands-access' if expands else 'comparison-only'}"><div class="scene-heading"><span>REFERENCIA ≈50%</span><b>{target_status}</b></div><div class="scene-body"><div class="worker-pose {right_pose}" data-access-level="{right_pose}" role="img" aria-label="{escape(right_label)}" title="{escape(right_label)}"></div><div class="scene-facts"><div class="scene-threshold"><strong>{number(ref['umbral'])}</strong><span>{p['unidad']} / operario</span></div><div class="scene-days"><strong>{ref_count}</strong><span>de {p['dias']} días</span><b>{number(ref_pct,1)}%</b></div>{ref_calendar}<div class="calendar-key"><i></i>Día que alcanza el objetivo</div></div></div></article>
      </div>
      <aside class="story-reading"><span>SUGERENCIA PARA EVALUAR</span><strong>{message}</strong><p>{qualification}</p></aside>
      <div class="story-payments"><span>Pago propuesto vigente<br><small>{p['personas']} legajos · Bolsa {"+" if cash_change >= 0 else ""}{number(cash_change,1)}%</small></span><span class="green"><strong>{p['mas']}</strong> cobran más</span><span><strong>{p['igual']}</strong> sin cambio</span><span class="red"><strong>{p['menos']}</strong> cobran menos</span></div>
      <p class="story-caption">El calendario compara el sector como un bloque. Los pagos corresponden al escenario vigente, no al cambio de umbral ilustrado.</p>
      <details class="story-detail"><summary>Ver curva y datos completos</summary>{chart(p)}<p>La meta debe superarse estrictamente. Los umbrales enteros y los empates pueden dar más días que el 50% objetivo. Grupal + individual + polivalencia se comparan con operaciones históricas equivalentes. La liquidación vigente conserva el cálculo por turno. Los gestos representan la frecuencia de acceso al grupal: preocupado por debajo del 25%, serio entre 25% y menos de 50%, sonrisa moderada entre 50% y menos de 75%, satisfecho desde el 75%. No representan la variación del pago individual.</p></details>
    </section>'''
