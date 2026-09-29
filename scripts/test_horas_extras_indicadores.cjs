const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const panel = {innerHTML:''};
const window = {};
vm.runInNewContext(fs.readFileSync('static/js/horas_extras_indicadores.js','utf8'), {
  window, document:{getElementById:()=>panel}, URLSearchParams, Date
});
const row = (estado,h,authorized=0,legajo=1) => ({estado,horas_extras_detectadas:h,horas_autorizadas:authorized,legajo,fecha:'2026-09-29',sector:'Sector <A>',empleado:'Persona <A>'});
const rows = [row('detectada',2),row('pre_autorizada',3,1),row('aprobada_gerente',4,2),row('rechazada_jefe',1),row('ajuste_solicitado',2),row('cargada_sap',2,2),row('ajuste_aprobado',1,1)];
const totals = window.HEIndicators.aggregate(rows);
for(const [value,expected] of [[8.1,'08:06'],[0.5,'00:30'],[1.75,'01:45'],[0,'00:00'],[25.5,'25:30'],[1.999,'02:00']]) {
  assert.equal(window.HEIndicators.duration(value),expected);
}
assert.equal(totals.total,15);
assert.equal(totals.approved,5);
assert.equal(totals.pending,7);
assert.equal(totals.denied,3);
assert.equal(totals.total,totals.approved+totals.pending+totals.denied);
assert.equal(totals.people.size,1);
assert.equal(totals.stages[0].length,1);
assert.equal(totals.stages[1].length,1);
assert.equal(totals.stages[2].length,1);
assert.equal(window.HEIndicators.aggregate(Array.from({length:1001},()=>row('detectada',1))).total,1001);
const params = new URLSearchParams({desde:'2026-09-01',hasta:'2026-09-30'});
window.HEIndicators.capture(rows,params,'');
assert.ok(panel.innerHTML.includes('Sector &lt;A&gt;'));
assert.ok(!panel.innerHTML.includes('NaN'));
const snapshot = panel.innerHTML;
rows[0].horas_extras_detectadas=100;
assert.equal(panel.innerHTML,snapshot);
window.HEIndicators.capture(rows,params,'rechazada_jefe');
assert.ok(panel.innerHTML.includes('1 registros'));
window.HEIndicators.capture([],params,'');
assert.ok(panel.innerHTML.includes('Sin registros'));
assert.ok(!panel.innerHTML.includes('NaN'));
console.log('OK: parciales, etapas, totales completos, filtros, snapshot y consulta vacia');
