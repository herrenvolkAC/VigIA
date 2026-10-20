"""Composiciones visuales del informe; usan datos del mismo snapshot exportado."""
from base64 import b64encode
from html import escape
from pathlib import Path

ASSETS = Path(__file__).with_name('assets') / 'gerencial'


def recommendation(p, number):
    """Sugerencias de simulación; no prometen cambios de pago no recalculados."""
    frequency = p['cumple'] / p['dias'] if p['dias'] else 0
    median = p['referencias'][1]['umbral']
    if not p['con_base']:
        title = 'Completar la base'
        text = 'Validar la nómina asociada antes de evaluar el umbral o modificar premios.'
    elif p.get('inicial'):
        title = 'Validar el escenario inicial'
        text = 'Confirmar la base de pagos comparables antes de aprobar los montos propuestos.'
    elif p['menos'] and frequency < .5 and median and median < p['objetivo']:
        title = 'Ampliar el acceso al grupal'
        text = f"Simular {number(median)} {p['unidad']} frente a {number(p['objetivo'])} vigentes. Evaluar el costo y cuántos legajos dejan de perder."
    elif p['menos'] and frequency >= .75:
        title = 'Revisar la distribución del premio'
        text = 'Mantener el umbral como referencia y simular trasladar parte de N4/N5 al grupal, controlando la bolsa total.'
    elif p['menos']:
        title = 'Revisar los casos con menor pago'
        text = 'Analizar jornadas y niveles de quienes pierden. Simular un reparto que modere las bajas sin concentrar las ganancias.'
    else:
        title = 'Mantener como referencia'
        text = 'El perfil no presenta legajos con menor pago en este período. Validar la estabilidad al incorporar nuevas fechas.'
    return f'<aside class="management-note"><span>SUGERENCIA · {escape(title)}</span><p>{escape(text)}</p><small>Escenario a evaluar; no modifica la configuración.</small></aside>'


def embedded(name, mime):
    return 'data:' + mime + ';base64,' + b64encode((ASSETS/name).read_bytes()).decode('ascii')


def cover(report, number):
    profiles = report['perfiles']
    more = sum(p['mas'] for p in profiles)
    less = sum(p['menos'] for p in profiles)
    equal = sum(p['igual'] for p in profiles)
    people = more + less + equal
    photo = embedded('centro_distribucion.jpg', 'image/jpeg')
    return f'''<section class="sheet hero visual-cover" id="portada-visual">
      <div class="cover-main"><div class="cover-copy">
        <div class="eyebrow">Propuesta de premios · Estudio gerencial</div>
        <h1>Productividad<br>y acceso al<br><span>premio grupal</span></h1>
        <p class="cover-deck">El objetivo elegido define cuántos días<br>el equipo alcanza el incentivo.</p>
        <div class="cover-period">AGOSTO + SEPTIEMBRE 2026 <span>Todos los turnos, un bloque por sector</span></div>
      </div><div class="cover-photo"><img src="{photo}" alt="Vista aérea del centro de distribución Coto, fotografía de la presentación de referencia"><div class="cover-photo-caption">Centro de distribución</div></div></div>
      <div class="cover-process" aria-label="Método de análisis">
        <div><span class="step-number">1</span><div><strong>Producción real</strong><small>Actividad computable del equipo</small></div></div>
        <span class="process-link" aria-hidden="true">›</span>
        <div><span class="step-number">2</span><div><strong>Objetivo grupal</strong><small>Umbral vigente y alternativas</small></div></div>
        <span class="process-link" aria-hidden="true">›</span>
        <div><span class="step-number">3</span><div><strong>Impacto en personas</strong><small>Grupal + individual + polivalencia</small></div></div>
      </div>
      <div class="cover-summary"><button type="button" data-open-profile="perfiles-analizados"><strong>{len(profiles)}</strong><span>perfiles analizados</span><small>Ver alcance</small></button><div><strong>{people}</strong><span>legajos evaluados</span></div><div class="green"><strong>{more} · {number(more/people*100,1)}%</strong><span>legajos cobran más</span></div><div class="red"><strong>{less} · {number(less/people*100,1)}%</strong><span>legajos cobran menos</span></div><div><strong>{equal} · {number(equal/people*100,1)}%</strong><span>sin variación</span></div></div>
      <details class="visual-details"><summary>Alcance del análisis</summary><p>Las curvas consolidan los turnos por sector y función. La comparación monetaria usa la liquidación propuesta vigente, que calcula por turno. La frecuencia de acceso al grupal y la variación del pago total son indicadores distintos. Los datos corresponden al snapshot del informe original.</p></details>
    </section>'''

