const assert=require('node:assert/strict');
const {build,scaleOrder}=require('../static/js/historia_niveles.js');
const scale=(op,code,lower)=>({ID_DE_GRUPO_DE_FUNCIONES:op,ID_DE_GRUPO_PRODUCTIVO:1,NIVEL:code,DESDE:lower});
let id=0;
const row=(op,date,level,time=3600,extra={})=>({ID:++id,ID_PV_DIA_LABORAL:id,FECHA:date,ID_PV_GRUPO_DE_FUNCIONES:op,ID_PV_GRUPO_PRODUCTIVO:1,ID_PV_UNIDAD_DE_PRODUCCION:'PALLET',OPERACION:op===1?'CARGA':'CARRETEO',OBJETIVO_NIVEL_ALCANZADO:level,TIEMPO_DURANTE_PH_EN_SEGUNDOS:time,OBJETIVO_UMBRAL_PARA_8HS:level===2?20:10,...extra});
const scales=[scale(1,1,10),scale(1,2,20),scale(1,301,30),scale(1,4,40),scale(2,1,10),scale(2,2,20)];
const fixture={desde:'2026-01-01',hasta:'2026-03-31',dias:[],escalas:scales,pagos:[row(1,20260101,2),row(1,20260102,301),row(1,20260301,1),row(2,20260101,1),row(2,20260201,2)]};
const model=build(fixture),cargo=model.series.find(s=>s.name==='CARGA'),carreteo=model.series.find(s=>s.name==='CARRETEO');
assert.deepEqual(cargo.scale.order.map(x=>[x.code,x.ordinal]),[[1,1],[2,2],[301,3],[4,4]]);
assert.equal(cargo.points[0].value,2.5);assert.equal(cargo.points[0].n,2);assert.equal(cargo.points[1].value,null);assert.equal(cargo.points[2].value,1);
assert.equal(carreteo.points[0].value,1);assert.equal(carreteo.points[1].value,2);
// A day shared by two operations contributes once to each independent line.
assert.equal(cargo.points[0].days[0].date,carreteo.points[0].days[0].date);
const a=row(1,20260103,1,3600),b=row(1,20260103,301,10800);
let r=build({...fixture,pagos:[a,b,a]}).series[0].points[0];
assert.equal(r.n,1);assert.equal(r.value,2.5);assert.equal(r.days[0].records.length,2);
r=build({...fixture,pagos:[{...a,TIEMPO_DURANTE_PH_EN_SEGUNDOS:null},b]}).series[0].points[0];
assert.equal(r.value,null);assert.equal(r.excluded.length,1);
r=build({...fixture,pagos:[a,b],dias:[{ID:a.ID_PV_DIA_LABORAL,AUSENTE:'SI'}]}).series[0].points[0];assert.equal(r.n,0);
const zero=row(1,20260104,0,3600,{ACCEDE_AL_PREMIO:'NO',PRODUCCION_TOTAL:4,OBJETIVO_PRODUCCION_8HS:5});
r=build({...fixture,pagos:[zero]}).series[0].points[0];assert.equal(r.value,0);assert.equal(r.n,1);
r=build({...fixture,pagos:[{...zero,PRODUCCION_TOTAL:0}]}).series[0].points[0];assert.equal(r.value,null);
assert.equal(scaleOrder([scale(1,0,0)]).valid,false);
assert.equal(scaleOrder([scale(1,1,10),scale(1,1,30),scale(1,2,20)]).valid,false);
r=build({...fixture,desde:'2026-01-15',hasta:'2026-03-15',pagos:[row(1,20260120,2),row(1,20260302,2,3600,{OBJETIVO_UMBRAL_PARA_8HS:25})]}).series[0];
assert.equal(r.points[0].partial,true);assert.equal(r.points[2].partial,true);assert.equal(r.points[2].changes.length,1);
// Query only achieved tier 301, but rank must use every catalog tier.
r=build({...fixture,pagos:[row(1,20260101,301)]}).series[0].points[0];assert.equal(r.value,3);
console.log('OK: índice mensual, ordinales 301, meses vacíos, dos operaciones, días únicos, pesos, exclusiones, ceros, escalas y meses parciales');
