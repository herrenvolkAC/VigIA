const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const elements = new Map();
function el(id) {
  if (!elements.has(id)) elements.set(id, {value:'',textContent:'',innerHTML:'',dataset:{},classList:{toggle(){}},setAttribute(){},addEventListener(event,fn){this[event]=fn;},querySelector(){return el(id+'child');}});
  return elements.get(id);
}
const data = [
 {fecha:'2026-09-01',legajo:'10',empleado:'Diez',usuario:'acucci',updated_at:'2026-09-15 18:28:08',horas:10,estado:'pendiente',observacion:''},
 {fecha:'2026-09-02',legajo:'2',empleado:'Dos',horas:2,estado:'pendiente',observacion:''}
];
let saved;
const ctx = {console, Intl, Set, URLSearchParams, Date, Number, String, setTimeout, $:el, esc:v=>String(v??''), nowLocal:()=> '2026-09-15T12:00', confirm:()=>true,
 document:{querySelector:el,querySelectorAll:()=>[]}, window:{addEventListener(){}},
 api:async (url,opt)=>{if(opt){saved=JSON.parse(opt.body).rows; return {guardadas:saved.length};} return {rows:structuredClone(data)};}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('static/js/herramientas_horas.js','utf8'),ctx);
(async()=> {
 el('he-sector').value='Secos';
 await el('he-form').submit({preventDefault(){}});
 assert.ok(el('he-body').innerHTML.includes('15:28:08 (Argentina)'));
 const sort = key => el('he-head').click({target:{closest:()=>({dataset:{sort:key}})}});
 sort('legajo');
 assert.ok(el('he-body').innerHTML.indexOf('Dos') < el('he-body').innerHTML.indexOf('Diez'));
 el('he-body').change({target:{dataset:{selectRow:'1'},checked:true}});
 sort('horas'); sort('horas');
 el('he-aprobar').onclick();
 await el('he-guardar').onclick();
 assert.equal(saved.length,1); assert.equal(saved[0].legajo,'2'); assert.equal(saved[0].estado,'autorizada');
 const change = (field,value) => el('he-body').input({target:{dataset:{field},value,closest:()=>({dataset:{heRow:'1'}})}});
 change('estado','parcial');
 assert.ok(el('he-body').innerHTML.includes('data-field="horas_autorizadas"'));
 change('horas_autorizadas','3');await el('he-guardar').onclick();
 assert.match(el('he-message').textContent,/menores/);
 change('horas_autorizadas','1.5');await el('he-guardar').onclick();
 assert.equal(saved[0].estado,'parcial');assert.equal(saved[0].horas_autorizadas,1.5);
 el('he-select-all').change({target:{checked:true}});
 el('he-rechazar').onclick();
 assert.match(el('he-message').textContent,/motivo/);
 el('he-motivo').value='Sin autorización previa'; el('he-rechazar').onclick();
 await el('he-guardar').onclick();
 assert.equal(saved.length,2); assert.ok(saved.every(r=>r.estado==='rechazada' && r.observacion==='Sin autorización previa'));
 console.log('OK: numeric sorting, selection identity after sorting, bulk approval, required rejection reason, bulk rejection');
})().catch(e=>{console.error(e);process.exitCode=1;});
