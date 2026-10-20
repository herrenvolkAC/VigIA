"""Simula bajas de umbral con bolsa +15%; sólo lectura."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'outputs' / 'escenario_75_balanceado_resultado.json'
DB = ROOT / 'datos' / 'laboratorio_premios.db'
FAMILIES = {
    'ARMADO': {'perfil-1','perfil-5','perfil-8','perfil-11','perfil-12'},
    'CLARK': {'perfil-2','perfil-6','perfil-9','perfil-13','perfil-14'},
    'RECEPCION': {'perfil-4','perfil-7','perfil-10','perfil-16'},
    'CARGA': {'perfil-3','perfil-15'},
    'CONTROL': {'perfil-17'},
}


def key(row, op='operacion'):
    return (row['sector'], row['funcion_legajero'], str(row[op]).upper(), row.get('division_madre') or '')


def tramos(base):
    value=float(base); out=[]
    for pct in (10,5,10,15,20):
        value *= 1+pct/100
        out.append(int(math.ceil(value-1e-9)))
    return out


def rounded100(v):
    return int(round(v/100)*100)


def main():
    report=json.loads(REPORT.read_text(encoding='utf-8'))
    profiles={p['id']:p for p in report['perfiles']}
    bykey={(p['sector'],p['funcion'],p['operacion'],p['division']):p for p in report['perfiles']}
    actual={}
    for p in report['perfiles']:
        for person in p['piloto_legajos']:
            actual[(p['id'],str(person['legajo']))]=sum(r['actual'] for r in person['dias'])
    db=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True); db.row_factory=sqlite3.Row
    cache=db.execute('SELECT nivel_2_json,nivel_3_json FROM lab_calculo_grupal_cache ORDER BY calculado_at DESC LIMIT 1').fetchone()
    daily=json.loads(cache['nivel_2_json']); roster=json.loads(cache['nivel_3_json']); db.close()
    daily_map={(key(r),str(r['turno']),r['fecha']):r for r in daily}
    results=[]
    for reduction in (0,.05,.10,.15,.20):
        events=defaultdict(lambda:defaultdict(lambda:{'actual':0,'group':0,'poly':0,'levels':defaultdict(int)}))
        objectives={pid:max(1,int(round(p['objetivo']*(1-reduction)/5)*5)) for pid,p in profiles.items()}
        # Secos Armado conserva un único valor entre zonas.
        shared=objectives['perfil-1']; objectives['perfil-5']=shared
        for (pid,leg),value in actual.items(): events[pid][leg]['actual']=value
        for row in roster:
            if datetime.strptime(row['fecha'],'%Y%m%d').weekday()>=5: continue
            p=bykey.get(key(row))
            if not p: continue
            pid=p['id']; leg=str(row['legajo']); ev=events[pid][leg]
            day=daily_map.get((key(row),str(row['turno']),row['fecha']),{})
            objective=objectives[pid]
            target=float(day.get('nomina_computable') or 0)*objective*(1-float(day.get('factor_ausentismo') or 0)/100)
            meets=bool(day.get('evaluable') and float(day.get('uc_computables') or 0)>target)
            if meets and row.get('beneficiario'): ev['group']+=1
            if row.get('es_polivalencia') and row.get('asistencia')=='Presente': ev['poly']+=1
            if row.get('aplica_grupo') and row.get('asistencia')=='Presente':
                uc=float(row.get('uc_brutas') or 0); starts=tramos(objective)
                level=max((i for i,start in enumerate(starts,1) if uc>=start),default=0)
                if level: ev['levels'][level]+=1
        family_results={}; all_people=[]
        fixed_people=[]
        for pid,population in events.items():
            p=profiles[pid]; awards={s['nivel']:s['premio'] for s in p['escala_individual']}
            for ev in population.values():
                new=(ev['group']+ev['poly'])*p['premio_grupal']*100+sum(ev['levels'][lv]*awards[lv]*100 for lv in range(1,6))
                fixed_people.append((ev['actual'],new))
        for family,ids in FAMILIES.items():
            population=[]; A=G=I=0
            for pid in ids:
                p=profiles[pid]; awards={s['nivel']:s['premio'] for s in p['escala_individual']}
                for leg,ev in events[pid].items():
                    population.append((pid,leg,ev)); A+=ev['actual']; G+=(ev['group']+ev['poly'])*p['premio_grupal']*100
                    I+=sum(ev['levels'][lv]*awards[lv]*100 for lv in range(1,6))
            candidates=[]
            for step in range(30,201):
                gf=step/100; inf=(A*1.15-G*gf)/I if I else 0
                if not(.30<=inf<=2 and .5<=gf/inf<=2): continue
                diffs=[]
                for pid,_,ev in population:
                    p=profiles[pid]; awards={s['nivel']:s['premio'] for s in p['escala_individual']}
                    new=(ev['group']+ev['poly'])*p['premio_grupal']*100*gf+sum(ev['levels'][lv]*awards[lv]*100*inf for lv in range(1,6))
                    diffs.append(new-ev['actual'])
                more=sum(v>.5 for v in diffs); less=sum(v<-.5 for v in diffs)
                candidates.append((less,-more,abs(gf-inf),gf,inf))
            _,_,_,gf,inf=min(candidates)
            settings={pid:{'group':rounded100(profiles[pid]['premio_grupal']*gf),
                           'levels':{s['nivel']:rounded100(s['premio']*inf) for s in profiles[pid]['escala_individual']}}
                      for pid in ids}
            family_people=[]
            for pid,leg,ev in population:
                st=settings[pid]; new=(ev['group']+ev['poly'])*st['group']*100+sum(ev['levels'][lv]*st['levels'][lv]*100 for lv in range(1,6))
                family_people.append((ev['actual'],new)); all_people.append((ev['actual'],new))
            family_results[family]={'actual':sum(x[0] for x in family_people)/100,'nuevo':sum(x[1] for x in family_people)/100,
                'mas':sum(n>a for a,n in family_people),'menos':sum(n<a for a,n in family_people),'igual':sum(n==a for a,n in family_people),
                'factor_grupal':gf,'factor_individual':inf,'montos':settings}
        A=sum(x[0] for x in all_people);N=sum(x[1] for x in all_people)
        FA=sum(x[0] for x in fixed_people); FN=sum(x[1] for x in fixed_people)
        results.append({'reduccion_umbral_pct':reduction*100,'objetivos':objectives,'familias':family_results,
                        'montos_actuales':{'actual':FA/100,'nuevo':FN/100,'variacion_pct':(FN/FA-1)*100,
                                          'mas':sum(n>a for a,n in fixed_people),'menos':sum(n<a for a,n in fixed_people),'igual':sum(n==a for a,n in fixed_people)},
                        'total':{'actual':A/100,'nuevo':N/100,'variacion_pct':(N/A-1)*100,
                                 'mas':sum(n>a for a,n in all_people),'menos':sum(n<a for a,n in all_people),'igual':sum(n==a for a,n in all_people)}})
    path=ROOT/'outputs'/'simulacion_baja_umbrales_sin_cambios.json'
    path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'reduccion':r['reduccion_umbral_pct'],**r['total']} for r in results],ensure_ascii=False,indent=2))


if __name__=='__main__': main()
