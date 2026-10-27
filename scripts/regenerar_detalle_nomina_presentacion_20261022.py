"""Regenera el HTML vigente con nómina grupal diaria y actividad desplegable."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from generar_informe_gerencial_umbrales import (
    analyze, attach_polivalency_summaries, attach_payroll_activity, render,
)

PERIOD = ('2026-08-01','2026-09-30')
HTML = ROOT / 'outputs' / 'informe_gerencial_bolsa_mas10_20261021.html'


def main():
    report = analyze(*PERIOD)
    attach_polivalency_summaries(report)
    payroll = attach_payroll_activity(report)
    rows = sum(map(len,payroll.values()))
    activities = sum(len(day['actividades']) for profile in payroll.values() for day in profile)
    actual = sum(p['actual_centavos'] for p in report['perfiles'])
    proposed = sum(p['nuevo_centavos'] for p in report['perfiles'])
    variance = (proposed/actual-1)*100 if actual else 0
    if len(report['perfiles']) != 17 or rows < 10000 or not activities:
        raise RuntimeError(f'Validación de detalle fallida: perfiles={len(report["perfiles"])}, filas={rows}, actividades={activities}')
    if not 9.5 <= variance <= 10.5:
        raise RuntimeError(f'El escenario vigente ya no está aproximadamente a +10%: {variance:.2f}%')
    report['escenario_bolsa'] = {
        'objetivo_pct':10,'pago_actual_centavos':actual,'pago_nuevo_centavos':proposed,
        'variacion_pct':variance,
        'distribucion':'Factor proporcional común a premios grupales e individuales; polivalencia conserva el valor grupal.',
    }
    report['detalle_nomina'] = {
        'filas_nomina_dia':rows,'grupos_perfil_turno_dia':sum(
            len({(x['fecha'],x['turno']) for x in items}) for items in payroll.values()),
        'grupos_actividad_funcion_division':activities,
        'fuente':'cache grupal interno + detalle local derivado de PV_ETAPA_CAB/DET; sin consulta al WMS vivo',
    }
    html = render(report, payroll_details=payroll)
    banner = (f'<div class="scenario-banner"><strong>Escenario de distribución de bolsa</strong>'
              f'<span>Pago nuevo: +{variance:.1f}% frente al actual · Premios grupales e individuales escalados proporcionalmente; '
              f'polivalencia conserva el importe grupal.</span></div>')
    html = html.replace('<main>', '<main>'+banner, 1)
    html = html.replace('</style>', '.scenario-banner{max-width:1240px;margin:10px auto 0;padding:12px 18px;border-left:5px solid #13748b;background:#e5f2f4;color:#142f42;display:flex;gap:14px;align-items:center;font:14px/1.4 Segoe UI,Arial,sans-serif}.scenario-banner strong{white-space:nowrap}.scenario-banner span{color:#405b69}@media print{.scenario-banner{margin:0 auto 8px;max-width:none}}\n</style>', 1)
    if html.count('data-open-payroll=') < 17 or html.count('class="profile-dialog payroll-dialog"') != 17:
        raise RuntimeError('No quedaron disponibles los detalles de nómina en los 17 perfiles.')
    HTML.write_text(html,encoding='utf-8')
    HTML.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'html':str(HTML),'cache_grupal':report['cache_grupal'],
        'perfiles':len(report['perfiles']),'nomina_dia':rows,'actividad_agrupada':activities,
        'pago_actual':actual/100,'pago_nuevo':proposed/100,'variacion_pct':variance,
        'html_bytes':HTML.stat().st_size},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
