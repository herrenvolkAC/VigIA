"""Simula montos de premios para operaciones no Armado, sin modificar la configuración.

Usa el último cálculo grupal Agosto-Septiembre y el último snapshot de pagos actuales.
Genera un CSV auditable con dos escenarios: distribución 60/40 y pago actual +3 %.
"""
import csv, json, sqlite3
from collections import defaultdict, Counter
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / 'datos' / 'laboratorio_premios.db'
OUT = Path(__file__).resolve().parents[1] / 'outputs' / 'escenarios_no_armado_20261015.csv'
OPERACIONES = {'CLARK', 'RECEPCION', 'CONTROL', 'PALETS OPERADOS'}
PESOS = (1.00, 1.30, 1.75, 2.40, 3.30)  # creciente; incentiva niveles altos
EQUIVALENCIAS = {
    'CLARK': {'CLARK'},
    'RECEPCION': {'RECEPCION', 'RECEPCION NOA', 'RECEPCION SECOS',
                  'RECEPCION IMPORTADO DE NOA', 'REFRIGERADOS | RECEPCION'},
    'CONTROL': {'CONTROL', 'CONTROL PROCESOS MANUAL', 'CONTROL DE PROCESOS CHP + CBF'},
    'PALETS OPERADOS': {'CARGA', 'CARRETEO', 'REFRIGERADOS | CARGA'},
}

def redondear_100(valor):
    return int(round(valor / 100.0) * 100) if valor > 0 else 0

def nivel(uc, tramos):
    for tramo in sorted(tramos, key=lambda x: x['nivel'], reverse=True):
        if uc >= tramo['desde'] and (tramo['hasta'] <= 0 or uc < tramo['hasta']):
            return tramo['nivel']
    return 0

def main():
    db=sqlite3.connect(DB); db.row_factory=sqlite3.Row
    calc=db.execute("""select nivel_3_json from lab_calculo_grupal_cache
        where fecha_desde='20260801' and fecha_hasta='20260930'""").fetchone()
    if not calc:
        raise SystemExit('No existe cálculo grupal Agosto-Septiembre.')
    rows=json.loads(calc['nivel_3_json'])
    parametros={}
    for r in db.execute("""select sector,funcion_legajero,turno,upper(trim(operacion_medible)) op,
      coalesce(division_madre,'') division,premio_grupal from lab_parametro_grupal where activo=1"""):
        parametros[(r['sector'],r['funcion_legajero'],str(r['turno']),r['op'],r['division'])]=float(r['premio_grupal'] or 0)
    escalas=defaultdict(list)
    for r in db.execute("""select sector,funcion_legajero,turno,upper(trim(operacion_medible)) op,
      coalesce(division_madre,'') division,nivel,desde_uc,hasta_uc from lab_escala_individual_grupal where activo=1"""):
        escalas[(r['sector'],r['funcion_legajero'],str(r['turno']),r['op'],r['division'])].append({
          'nivel':int(r['nivel']),'desde':float(r['desde_uc'] or 0),'hasta':float(r['hasta_uc'] or 0)})
    snap=db.execute("select snapshot from lab_pago_actual_meta order by capturado desc limit 1").fetchone()
    pagos=defaultdict(int)
    if snap:
        for r in db.execute("""select legajo,fecha,upper(trim(operacion)) op,sum(pago_centavos) pago
          from lab_pago_actual_operacion where snapshot=? and fecha between '20260801' and '20260930'
          group by legajo,fecha,upper(trim(operacion))""",(snap['snapshot'],)):
            pagos[(str(r['legajo']),str(r['fecha']),r['op'])] += int(r['pago'] or 0)
    grupos=defaultdict(lambda:{'eventos':[], 'actual':defaultdict(int), 'grupo':0, 'poliv':0})
    for r in rows:
        op=str(r.get('operacion') or '').upper()
        if op not in OPERACIONES: continue
        clave=(r.get('sector') or '',r.get('funcion_legajero') or '',str(r.get('turno') or r.get('turno_fijo') or ''),op,str(r.get('division_madre') or ''))
        if clave not in escalas: continue
        g=grupos[clave]
        leg=str(r.get('legajo') or ''); fecha=str(r.get('fecha') or '')
        actual=sum(pagos[(leg,fecha,x)] for x in EQUIVALENCIAS[op])
        g['actual'][(leg,fecha)] += actual
        presente=r.get('asistencia')=='Presente'
        aplica=bool(r.get('aplica_grupo'))
        if r.get('cobra'): g['grupo'] += int(round(float(r.get('premio_grupal') or 0)*100))
        if r.get('es_polivalencia') and presente: g['poliv'] += int(round(parametros.get(clave,0)*100))
        if presente and aplica:
            n=nivel(float(r.get('uc_brutas') or 0),escalas[clave])
            g['eventos'].append((leg,fecha,n))
    salida=[]
    for clave,g in sorted(grupos.items()):
        hist=sum(g['actual'].values())
        niveles=Counter(n for _,_,n in g['eventos'] if n>0)
        base=sum(niveles[n]*PESOS[n-1] for n in range(1,6))
        if base==0: continue
        fijo=g['grupo']+g['poliv']
        objetivos={'60_40':g['grupo']*(2/3), 'actual_mas_3':max(0,hist*1.03-fijo)}
        for nombre,obj in objetivos.items():
            escala_base=obj/base
            montos=[redondear_100(escala_base*p) for p in PESOS]
            individual=sum(niveles[n]*montos[n-1] for n in range(1,6))
            total=fijo+individual
            # Comparación por legajo en este perfil; el pago actual comparable se prorratea naturalmente por día.
            nuevo_por_leg=defaultdict(int); actual_por_leg=defaultdict(int)
            for leg,fecha,n in g['eventos']:
                actual_por_leg[leg]+=g['actual'][(leg,fecha)]
                if n: nuevo_por_leg[leg]+=montos[n-1]
            # grupal/poliv no se prorratea aquí; medida de riesgo conserva comparación individual mínima.
            # Reportamos eventos que no alcanzan nivel y perfiles sin evento alcanzado.
            salida.append({
              'escenario':nombre,'sector':clave[0],'funcion':clave[1],'turno':clave[2],'operacion':clave[3],'division':clave[4],
              'eventos_evaluados':len(g['eventos']),'n1':niveles[1],'n2':niveles[2],'n3':niveles[3],'n4':niveles[4],'n5':niveles[5],
              'monto_n1':montos[0],'monto_n2':montos[1],'monto_n3':montos[2],'monto_n4':montos[3],'monto_n5':montos[4],
              'actual':round(hist/100,2),'grupal':round(g['grupo']/100,2),'polivalencia':round(g['poliv']/100,2),
              'individual':round(individual/100,2),'nuevo_total':round(total/100,2),
              'variacion_pct':round((total/hist-1)*100,1) if hist else None,
              'participacion_grupal_pct':round(g['grupo']/(g['grupo']+individual)*100,1) if g['grupo']+individual else None,
              'sin_nivel':sum(1 for _,_,n in g['eventos'] if n==0),
            })
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(salida[0]) if salida else [])
        w.writeheader();w.writerows(salida)
    print(OUT)
    for s in salida:
        print(s['escenario'],s['operacion'],s['sector'],s['funcion'],s['turno'], 'actual',s['actual'],'nuevo',s['nuevo_total'],'var',s['variacion_pct'],'60%',s['participacion_grupal_pct'],'N', [s[f'monto_n{i}'] for i in range(1,6)])
if __name__=='__main__':main()
