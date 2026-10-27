/* El detalle se abre fuera del lienzo: no agrega hojas ni reduce la lámina. */
document.querySelectorAll('[data-open-profile]').forEach(button => {
  button.addEventListener('click', () => {
    const dialog = document.getElementById('detalle-' + button.dataset.openProfile);
    if (dialog) { dialog.appendChild(document.getElementById('chart-tooltip')); dialog.showModal(); dialog.scrollTop = 0; }
  });
});
document.querySelectorAll('.profile-dialog').forEach(dialog => {
  dialog.querySelector('[data-close-profile]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('keydown', event => {if (event.key === 'Escape') {event.preventDefault();event.stopPropagation();dialog.close();}});
  dialog.addEventListener('click', event => {if (event.target === dialog) {const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  dialog.addEventListener('close', () => {const tooltip=document.getElementById('chart-tooltip');tooltip.hidden=true;document.body.appendChild(tooltip);});
});

// La nómina se carga dentro de cada perfil bajo demanda; las actividades se
// expanden solo al abrir la fila de una persona y una fecha.
let payrollPayload=null;
const payrollEscape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const payrollNumber=value=>Number(value||0).toLocaleString('es-AR',{maximumFractionDigits:2});
function moneyLabel(cents){return (Number(cents||0)/100).toLocaleString('es-AR',{style:'currency',currency:'ARS',maximumFractionDigits:2});}
async function ensurePayrollPayload(){
  if(payrollPayload)return payrollPayload;
  const node=document.getElementById('payroll-report-data');
  if(!node)throw new Error('Este informe no incluye el archivo de detalle de nómina.');
  if(!('DecompressionStream' in window))throw new Error('El navegador no admite la lectura comprimida del detalle. Abrí el informe en una versión reciente de Edge o Chrome.');
  const binary=atob(node.textContent.trim()),bytes=new Uint8Array(binary.length);
  for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  payrollPayload=JSON.parse(await new Response(stream).text());
  return payrollPayload;
}
function activityMarkup(items){
  if(!items?.length)return '<p class="payroll-no-activity">No hay actividades asociadas a este legajo y fecha en el cache.</p>';
  return `<div class="table-wrap"><table class="payroll-activity-table"><thead><tr><th>Función registrada (PV)</th><th>División</th><th>Sector</th><th>Etapas</th><th>Líneas</th><th>Cantidad</th><th>Palets</th><th>PLUs</th><th>Peso</th></tr></thead><tbody>${items.map(a=>`<tr><td>${payrollEscape(a.funcion)}${a.codigo?` <small>${payrollEscape(a.codigo)}</small>`:''}</td><td>${payrollEscape(a.division||'—')}</td><td>${payrollEscape(a.sector||'—')}</td><td>${payrollNumber(a.etapas)}</td><td>${payrollNumber(a.lineas)}</td><td>${payrollNumber(a.cantidad)}</td><td>${payrollNumber(a.palets)}</td><td>${payrollNumber(a.plus)}</td><td>${payrollNumber(a.peso)}</td></tr>`).join('')}</tbody></table></div>`;
}
function renderPayroll(profileId){
  if(!payrollPayload){const node=document.getElementById('payroll-report-data');payrollPayload=node?JSON.parse(node.textContent||'{}'):{};}
  const dialog=document.getElementById('nomina-'+profileId),target=dialog?.querySelector(`[data-payroll-profile="${profileId}"]`);
  if(!target||target.dataset.loaded==='1')return;
  const entries=payrollPayload[profileId]||[];
  if(!entries.length){target.innerHTML='<p class="payroll-no-activity">No hay filas de nómina para este perfil en el período consultado.</p>';target.dataset.loaded='1';return;}
  const groups=new Map();
  entries.forEach((row,index)=>{const k=`${row.fecha}|${row.turno}`;if(!groups.has(k))groups.set(k,[]);groups.get(k).push({...row,_index:index});});
  const fmtDate=raw=>{const s=String(raw||'');if(s.length!==8)return payrollEscape(s);const date=new Date(`${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}T12:00:00`);return `${date.toLocaleDateString('es-AR',{weekday:'long'})} ${s.slice(6,8)}/${s.slice(4,6)}/${s.slice(0,4)}`;};
  target.innerHTML=[...groups.entries()].map(([key,rows])=>{
    const g=rows[0].grupo||{},first=rows[0],cumple=g.evaluable?(g.cumple?'Supera la meta':'No alcanza la meta'):'Sin evaluación';
    return `<section class="payroll-day"><header><h3>${fmtDate(first.fecha)} <span>Turno ${payrollEscape(first.turno)}</span></h3><strong class="${g.cumple?'payroll-hit':'payroll-miss'}">${cumple}</strong></header><div class="payroll-day-kpis"><span>Producción equipo <b>${payrollNumber(g.produccion)} ${payrollEscape(first.unidad)}</b></span><span>Meta aplicada <b>${payrollNumber(g.meta)} ${payrollEscape(first.unidad)}</b></span><span>Nómina computable <b>${payrollNumber(g.nomina_computable)}</b></span><span>Presentes <b>${payrollNumber(g.presentes)}</b></span><span>Ausencias permitidas <b>${payrollNumber(g.ausentes_permitidos)}</b></span><span>Polivalentes <b>${payrollNumber(g.polivalentes)}</b></span><span>Premio por beneficiario <b>${moneyLabel(g.premio_beneficiario_centavos)}</b></span></div><div class="table-wrap"><table class="payroll-table"><thead><tr><th>Legajo</th><th>Asistencia / inclusión</th><th>Producción individual</th><th>Computa para grupo</th><th>Pago grupal</th><th>Nivel indiv.</th><th>Pago individual</th><th>Polivalencia</th><th>Actividad</th></tr></thead><tbody>${rows.map(r=>`<tr><td><b>${payrollEscape(r.legajo)}</b><small>${payrollEscape(r.nombre)}</small></td><td>${payrollEscape(r.asistencia)}${r.inclusion&&r.inclusion!=='Incluido'?`<small>${payrollEscape(r.inclusion)}</small>`:''}${r.polivalente?'<small>Polivalencia</small>':''}</td><td>${payrollNumber(r.produccion)} ${payrollEscape(r.unidad)}</td><td>${r.aplica_grupo?'Sí':'No'}</td><td>${moneyLabel(r.pago_grupal_centavos)}</td><td>${r.nivel_individual?`N${r.nivel_individual}`:'—'}</td><td>${moneyLabel(r.pago_individual_centavos)}</td><td>${moneyLabel(r.pago_polivalencia_centavos)}</td><td><button class="payroll-activity-toggle" type="button" data-activity-index="${r._index}">Ver ${payrollNumber(r.actividades?.length||0)} actividades</button></td></tr><tr class="payroll-activity-row" data-activity-row="${r._index}" hidden><td colspan="9"></td></tr>`).join('')}</tbody></table></div></section>`;
  }).join('');
  target.dataset.loaded='1';
}
document.querySelectorAll('[data-open-payroll]').forEach(button=>button.addEventListener('click',async()=>{
  const id=button.dataset.openPayroll,dialog=document.getElementById('nomina-'+id);
  if(!dialog)return;
  const tooltip=document.getElementById('chart-tooltip');if(tooltip)dialog.appendChild(tooltip);
  dialog.showModal();dialog.scrollTop=0;
  const target=dialog.querySelector(`[data-payroll-profile="${id}"]`);
  if(target&&target.dataset.loaded!=='1')target.innerHTML='<p>Cargando nómina y actividad del cache…</p>';
  try{await ensurePayrollPayload();renderPayroll(id);}
  catch(error){if(target)target.innerHTML=`<p class="payroll-no-activity">${payrollEscape(error.message||'No se pudo cargar el detalle.')}</p>`;}
}));
document.querySelectorAll('.payroll-dialog').forEach(dialog=>dialog.addEventListener('click',event=>{
  const button=event.target.closest('[data-activity-index]');if(!button)return;
  const index=button.dataset.activityIndex,row=dialog.querySelector(`[data-activity-row="${index}"]`);
  if(!row)return;
  if(row.hidden){const profileId=dialog.id.replace('nomina-','');const items=payrollPayload?.[profileId]?.[Number(index)]?.actividades||[];row.cells[0].innerHTML=activityMarkup(items);row.hidden=false;button.textContent='Ocultar actividad';}
  else{row.hidden=true;button.textContent=`Ver ${payrollNumber((payrollPayload?.[dialog.id.replace('nomina-','')]||[])[Number(index)]?.actividades?.length||0)} actividades`;}
}));
