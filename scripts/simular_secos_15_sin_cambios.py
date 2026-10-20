"""Redistribución teórica de Secos a +15%; no modifica la aplicación."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
data=json.loads((ROOT/'outputs'/'informe_gerencial_umbrales_75_balanceado_20261019.json').read_text(encoding='utf-8'))
profiles={p['id']:p for p in data['perfiles']}
groups={
    'ARMADO SECOS':{'perfil-1','perfil-5'},
    'CLARK SECOS':{'perfil-2','perfil-6'},
    'CARGA SECOS':{'perfil-3'},
    'RECEPCION SECOS':{'perfil-7'},
}

def people(p):
    return [(z['legajo'],[sum(r[k] for r in z['dias']) for k in ('actual','grupal','individual','polivalencia')]) for z in p['piloto_legajos']]

result={}; all_people=[]
for name,ids in groups.items():
    pop=[]
    for pid in ids:
        pop += [(pid,leg,vals) for leg,vals in people(profiles[pid])]
    A=sum(v[0] for _,_,v in pop); G=sum(v[1]+v[3] for _,_,v in pop); I=sum(v[2] for _,_,v in pop)
    candidates=[]
    for step in range(20,401):
        gf=step/100; inf=(A*1.15-G*gf)/I if I else 0
        if not .2<=inf<=4: continue
        dif=[(v[1]+v[3])*gf+v[2]*inf-v[0] for _,_,v in pop]
        more=sum(x>.5 for x in dif);less=sum(x<-.5 for x in dif)
        candidates.append((less,-more,abs(gf-inf),abs(gf-1)+abs(inf-1),gf,inf))
    *_,gf,inf=min(candidates)
    rows=[]
    for pid,leg,v in pop:
        new=(v[1]+v[3])*gf+v[2]*inf
        rows.append((v[0],new)); all_people.append((v[0],new))
    result[name]={'factor_grupal':gf,'factor_individual':inf,'actual':A/100,'nuevo':sum(n for _,n in rows)/100,
                  'variacion_pct':(sum(n for _,n in rows)/A-1)*100,
                  'mas':sum(n>a for a,n in rows),'menos':sum(n<a for a,n in rows),'igual':sum(n==a for a,n in rows),
                  'montos':{pid:{'grupal':round(profiles[pid]['premio_grupal']*gf/100)*100,
                                  'individual':[round(s['premio']*inf/100)*100 for s in profiles[pid]['escala_individual']]}
                            for pid in sorted(ids)}}
A=sum(a for a,_ in all_people);N=sum(n for _,n in all_people)
result['TOTAL']={'actual':A/100,'nuevo':N/100,'variacion_pct':(N/A-1)*100,
                 'mas':sum(n>a for a,n in all_people),'menos':sum(n<a for a,n in all_people),'igual':sum(n==a for a,n in all_people)}
path=ROOT/'outputs'/'simulacion_secos_15_sin_cambios.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
