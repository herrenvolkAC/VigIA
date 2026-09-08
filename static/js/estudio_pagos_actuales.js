/* Tres niveles sobre el mismo período. Pagos Oracle: cache local capturada. */
const hierarchy={source:null,legajo:null,dia:null,funcion:null,actual:null,tab:'simulacion',
 sort:{legajos:['legajo',1],dias:['fecha',1],funciones:['desc_funcion',1],actual:['operacion',1]}};
const actualDetails=new Map();
function hierarchySort(rows,grid){
 const [key,dir]=hierarchy.sort[grid];
 return [...rows].sort((a,b)=>{const x=a[key],y=b[key];if(x==null)return y==null?0:1;if(y==null)return -1;return dir*(typeof x==='number'&&typeof y==='number'?x-y:String(x).localeCompare(String(y),'es',{numeric:true,sensitivity:'base'}));});
}
const moneyActual=v=>v==null?'Sin información':(v/100).toLocaleString('es-AR',{style:'currency',currency:'ARS'});
function paymentHierarchy(rows,actualRows,restricted){
 const days=new Map(),legs=new Map();
 const key=(l,d)=>JSON.stringify([String(l??''),String(d??'')]);
 const ensure=(l,d)=>{const k=key(l,d);if(!days.has(k))days.set(k,{legajo:String(l??''),fecha:String(d??''),total:null,pago_actual:null,actual:null});return days.get(k);};
 for(const r of rows){const d=ensure(r.legajo,r.fecha);if(r.premio_nuevo!=null)d.total=(d.total??0)+Math.round(Number(r.premio_nuevo)*100);}
 const simLegs=new Set([...days.values()].map(d=>d.legajo));
 for(const r of actualRows){if(restricted&&!simLegs.has(String(r.legajo)))continue;const d=ensure(r.legajo,r.fecha);d.actual=r;d.pago_actual=r.pago_centavos;}
 for(const d of days.values()){
  if(!legs.has(d.legajo))legs.set(d.legajo,{legajo:d.legajo,total:null,pago_actual:null,faltantes:0});
  const l=legs.get(d.legajo);
  if(d.total!=null)l.total=(l.total??0)+d.total;
  if(d.pago_actual!=null)l.pago_actual=(l.pago_actual??0)+d.pago_actual;else l.faltantes++;
 }
 for(const r of [...days.values(),...legs.values()])r.diferencia=r.total==null||r.pago_actual==null?null:r.total-r.pago_actual;
 return {days:[...days.values()],legs:[...legs.values()]};
}
function renderResumen(){
 const rows=model.hierarchy_rows||[];
 if(hierarchy.source!==rows){hierarchy.source=rows;hierarchy.legajo=null;hierarchy.dia=null;hierarchy.funcion=null;hierarchy.actual=null;}
 const restricted=!!(model.query_filters?.desc_funcion||model.query_filters?.grupo_productivo);
 const data=paymentHierarchy(rows,model.actual_data?.rows||[],restricted);
 const paint=yes=>yes?' class="hierarchy-selected" aria-selected="true"':' aria-selected="false"';
 $('jerarquia-legajos').innerHTML=hierarchySort(data.legs,'legajos').map(r=>`<tr tabindex="0" data-pick="${esc(r.legajo)}"${paint(r.legajo===hierarchy.legajo)}><td>${esc(r.legajo)}</td><td>${moneyActual(r.pago_actual)}${r.faltantes&&r.pago_actual!=null?' (parcial)':''}</td><td>${moneyActual(r.total)}</td><td>${moneyActual(r.diferencia)}${r.faltantes&&r.diferencia!=null?' (parcial)':''}</td></tr>`).join('');
 const days=data.days.filter(d=>d.legajo===hierarchy.legajo);
 $('jerarquia-dias').innerHTML=hierarchySort(days,'dias').map(r=>`<tr tabindex="0" data-pick="${esc(r.fecha)}"${paint(r.fecha===hierarchy.dia)}><td>${esc(r.legajo)}</td><td>${esc(r.fecha)}</td><td>${moneyActual(r.pago_actual)}</td><td>${moneyActual(r.total)}</td><td>${moneyActual(r.diferencia)}${r.faltantes&&r.diferencia!=null?' (parcial)':''}</td></tr>`).join('');
 const funcs=hierarchy.dia===null?[]:rows.map((r,index)=>({...r,index})).filter(r=>String(r.legajo??'')===hierarchy.legajo&&String(r.fecha??'')===hierarchy.dia);
 $('jerarquia-funciones').innerHTML=hierarchySort(funcs,'funciones').map(r=>`<tr tabindex="0" data-pick="${r.index}"${paint(r.index===hierarchy.funcion)}><td>${esc(r.desc_funcion||'Sin función')}</td><td>${esc(r.operacion_premio)}</td><td>${esc(r.grupo_productivo)}</td><td>${esc(r.unidades_evaluadas??'—')}</td><td>${esc(r.nivel_nuevo??'—')}</td><td>${moneyActual(r.premio_nuevo==null?null:Math.round(r.premio_nuevo*100))}</td></tr>`).join('');
 $('jerarquia-legajo-label').textContent=hierarchy.legajo===null?'Seleccioná un legajo':'Legajo '+hierarchy.legajo;
 $('jerarquia-dia-label').textContent=hierarchy.dia===null?'Seleccioná un día':'Legajo '+hierarchy.legajo+' · '+hierarchy.dia;
 $('pago-actual-nota').textContent='Pago actual: total de Productividad/Oracle por jornada. Simulación parcial: Carga + Traslados.'+(restricted?' Función/grupo filtran la simulación; el pago actual conserva todas las operaciones del legajo.':'')+' Captura: '+(model.actual_data?.capturado||'Sin información');
 for(const grid of ['legajos','dias','funciones']){
  $('jerarquia-'+grid).querySelectorAll('[data-pick]').forEach(tr=>{
   const select=()=>{const k=tr.dataset.pick;if(grid==='legajos'){hierarchy.legajo=hierarchy.legajo===k?null:k;hierarchy.dia=null;hierarchy.funcion=null;hierarchy.actual=null;}
    else if(grid==='dias'){hierarchy.dia=hierarchy.dia===k?null:k;hierarchy.funcion=null;hierarchy.actual=null;}
    else hierarchy.funcion=hierarchy.funcion===Number(k)?null:Number(k);renderResumen();};
   tr.onclick=select;tr.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};
  });
 }
 $('nivel3-simulacion').hidden=hierarchy.tab!=='simulacion';$('nivel3-actual').hidden=hierarchy.tab!=='actual';
 document.querySelectorAll('[data-paytab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.paytab===hierarchy.tab)));
 renderActual(days.find(d=>d.fecha===hierarchy.dia));
 updateHierarchyArrows();
}
function updateHierarchyArrows(){document.querySelectorAll('[data-hkey]').forEach(th=>{const [key,dir]=hierarchy.sort[th.dataset.hgrid];th.classList.toggle('sorted',key===th.dataset.hkey);th.dataset.arrow=dir===1?'↑':'↓';});}
function actualKey(){return JSON.stringify([model.actual_data?.snapshot,hierarchy.legajo,hierarchy.dia]);}
function renderActual(day){
 const target=$('jerarquia-actual'),status=$('actual-conciliacion');target.innerHTML='';status.textContent='';
 if(!day)return;
 if(!day.actual){status.textContent='Sin información de Productividad/Oracle para esta jornada.';return;}
 const a=day.actual;
 status.textContent='Total jornada: '+moneyActual(a.pago_centavos)+' · Suma operaciones: '+moneyActual(a.detalle_centavos)+' · Diferencia por conciliar: '+moneyActual(a.diferencia_centavos);
 if(hierarchy.tab!=='actual')return;
 const key=actualKey(),cached=actualDetails.get(key);
 if(!cached){
  actualDetails.set(key,{loading:true});status.textContent+=' · Cargando operaciones…';
  const query=qs({snapshot:model.actual_data.snapshot,fecha:hierarchy.dia,legajo:hierarchy.legajo});
  fetch('/api/estudio-premios-productividad/pagos-actuales/detalle?'+query,{credentials:'same-origin'})
   .then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.detail||'No se pudo leer el pago actual.');actualDetails.set(key,{rows:d.rows});})
   .catch(e=>actualDetails.set(key,{error:e.message}))
   .finally(()=>{if(key===actualKey())renderActual(day);});return;
 }
 if(cached.loading){status.textContent+=' · Cargando operaciones…';return;}
 if(cached.error){status.textContent+=' · '+cached.error;return;}
 target.innerHTML=hierarchySort(cached.rows,'actual').map(r=>`<tr tabindex="0" data-pick="${esc(r.id)}"${hierarchy.actual===r.id?' class="hierarchy-selected"':''}><td>${esc(r.operacion)}</td><td>${esc(r.grupo)}</td><td>${esc(r.unidad)}</td><td>${esc(r.produccion??'—')}</td><td>${esc(r.tiempo??'—')}</td><td>${esc(r.nivel??'—')}</td><td>${moneyActual(r.proporcion==null?null:Math.round(r.proporcion*100))}</td><td>${moneyActual(r.excedente==null?null:Math.round(r.excedente*100))}</td><td>${moneyActual(r.pago_centavos)}</td></tr>`).join('');
 target.querySelectorAll('[data-pick]').forEach(tr=>{const select=()=>{hierarchy.actual=hierarchy.actual===tr.dataset.pick?null:tr.dataset.pick;renderActual(day);};tr.onclick=select;tr.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};});
}
document.querySelectorAll('[data-hkey]').forEach(th=>th.onclick=()=>{const grid=th.dataset.hgrid,key=th.dataset.hkey,previous=hierarchy.sort[grid];hierarchy.sort[grid]=[key,previous[0]===key?-previous[1]:1];renderResumen();});
document.querySelectorAll('[data-paytab]').forEach(b=>b.onclick=()=>{hierarchy.tab=b.dataset.paytab;renderResumen();});
