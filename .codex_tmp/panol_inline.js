
let ctx=null, articles=[], stockRows=[], movementRows=[], indicatorData={}, productionStockRows=[], productionMovementRows=[], productionIndicatorData={}, pedidoIndicatorData={}, requestCatalogRows=[], myPedidoRows=[], pendingPedidoRows=[], selectedPendingPedido=null;
const $=id=>document.getElementById(id);
function esc(v){return String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
function num(v){const n=Number(v||0);return Number.isFinite(n)?n:0}
function fmt(v){return num(v).toLocaleString('es-AR',{maximumFractionDigits:3})}
function shortDate(v){return v?String(v).replace('T',' ').slice(0,16):'-'}
function setStatus(t,e=false){$('status').textContent=t||'';$('status').classList.toggle('error',!!e)}
function emptyChart(text){return `<div class="empty-chart">${esc(text)}</div>`}
function renderSimpleBars(elId, rows, opts={}){
  const el=$(elId);
  if(!el)return;
  if(!rows.length){el.innerHTML=emptyChart(opts.empty||'Sin datos');return;}
  const max=Math.max(...rows.map(r=>Math.abs(num(r.value))),1);
  el.innerHTML=rows.map(r=>{
    const pct=Math.max(2,Math.min(100,Math.abs(num(r.value))/max*100));
    return `<div class="bar-row"><div class="bar-label" title="${esc(r.label)}">${esc(r.label)}</div><div class="bar-track"><div class="bar-fill ${r.cls||''}" style="width:${pct}%"></div></div><div class="bar-value">${r.display??fmt(r.value)}</div></div>`;
  }).join('');
}
function renderStackedStock(){
  const el=$('chart-stock-location');
  if(!el)return;
  const maxLabelLength='557340 - RESMA CARTA 75G 216X279 MM AUTOR PAC 500 UNI'.length;
  const rows=[...stockRows].filter(r=>num(r.stock_total)>0).sort((a,b)=>num(b.stock_total)-num(a.stock_total)).slice(0,10);
  if(!rows.length){el.innerHTML=emptyChart('Sin stock para graficar');return;}
  el.innerHTML=rows.map(r=>{
    const total=Math.max(num(r.stock_total),1);
    const cdQty=num(r.stock_cd), jaulaQty=num(r.stock_jaula), oficinaQty=num(r.stock_oficina);
    const cd=cdQty/total*100, jaula=jaulaQty/total*100, oficina=oficinaQty/total*100;
    const fullLabel=`${r.codigo} - ${r.descripcion||''}`;
    const label=fullLabel.length>maxLabelLength?`${fullLabel.slice(0,maxLabelLength-3)}...`:fullLabel;
    return `<div class="bar-row"><div class="bar-label" title="${esc(fullLabel)}">${esc(label)}</div><div class="bar-track"><div class="bar-fill stock-segment cd ${cdQty<=0?'is-empty':''}" style="width:${cd}%" title="CD: ${fmt(cdQty)}">${fmt(cdQty)}</div><div class="bar-fill stock-segment jaula ${jaulaQty<=0?'is-empty':''}" style="width:${jaula}%" title="Jaula: ${fmt(jaulaQty)}">${fmt(jaulaQty)}</div><div class="bar-fill stock-segment oficina ${oficinaQty<=0?'is-empty':''}" style="width:${oficina}%" title="Oficina: ${fmt(oficinaQty)}">${fmt(oficinaQty)}</div></div><div class="bar-value">${fmt(total)}</div></div>`;
  }).join('');
}
function renderDashboardCharts(){
  renderStackedStock();
  const low=stockRows.filter(r=>r.estado==='BAJO_MINIMO').sort((a,b)=>(num(b.stock_minimo)-num(b.stock_total))-(num(a.stock_minimo)-num(a.stock_total))).slice(0,8).map(r=>({label:r.codigo,value:Math.max(num(r.stock_minimo)-num(r.stock_total),0),display:`${fmt(r.stock_total)}/${fmt(r.stock_minimo)}`,cls:'bad'}));
  renderSimpleBars('chart-low-stock',low,{empty:'Sin articulos bajo minimo'});
  const coverage=stockRows.filter(r=>r.cobertura_dias!=null&&Number.isFinite(num(r.cobertura_dias))).sort((a,b)=>num(a.cobertura_dias)-num(b.cobertura_dias)).slice(0,8).map(r=>({label:r.codigo,value:num(r.cobertura_dias),display:fmt(r.cobertura_dias),cls:num(r.cobertura_dias)<7?'bad':'soft'}));
  renderSimpleBars('chart-coverage',coverage,{empty:'Sin consumos calculados'});
  const dayRows=(indicatorData.consumo_por_dia_logistico||[]).map(r=>({label:r.dia_logistico,value:num(r.consumo),cls:'oficina'}));
  renderSimpleBars('chart-turn-consumption',dayRows,{empty:'Sin consumo por dia logistico'});
  const recentEl=$('chart-recent-moves');
  if(recentEl){
    const recent=movementRows.slice(0,8);
    recentEl.innerHTML=recent.length?recent.map(r=>`<div class="activity-item"><strong>${esc(r.tipo)} - ${esc(r.codigo)} - ${fmt(r.cantidad)}</strong><span>${shortDate(r.fecha_hora)} - ${esc(r.origen_codigo||'-')} -> ${esc(r.destino_codigo||'-')} - ${esc(r.usuario||'')}</span></div>`).join(''):emptyChart('Sin movimientos recientes');
  }
}
const chartColors=['#0b5fae','#1f7a4d','#b25f00','#c8102e','#5c6773','#2f7f9f','#6a7b38','#8b5a2b'];
function renderPie(pieId,legendId,rows,empty){
  const pie=$(pieId), legend=$(legendId);
  if(!pie||!legend)return;
  const data=rows.filter(r=>num(r.value)>0);
  const total=data.reduce((s,r)=>s+num(r.value),0);
  if(!total){pie.style.background='#e9eeeb';legend.innerHTML=emptyChart(empty);return;}
  let acc=0;
  const stops=data.map((r,i)=>{
    const start=acc/total*100;
    acc+=num(r.value);
    const end=acc/total*100;
    return `${chartColors[i%chartColors.length]} ${start}% ${end}%`;
  });
  pie.style.background=`conic-gradient(${stops.join(',')})`;
  legend.innerHTML=data.map((r,i)=>`<span><i style="background:${chartColors[i%chartColors.length]}"></i>${esc(r.label)} - ${fmt(r.value)}</span>`).join('');
}
function renderVerticalBars(elId,rows,empty){
  const el=$(elId);
  if(!el)return;
  const data=rows.filter(r=>num(r.value)>0);
  if(!data.length){el.innerHTML=emptyChart(empty);return;}
  const max=Math.max(...data.map(r=>num(r.value)),1);
  el.innerHTML=data.slice(0,24).map(r=>{
    const h=Math.max(3,num(r.value)/max*100);
    return `<div class="vbar-item" title="${esc(r.label)}: ${fmt(r.value)}"><div class="vbar-value">${fmt(r.value)}</div><div class="vbar-track"><div class="vbar-fill" style="height:${h}%"></div></div><div class="vbar-label">${esc(r.label)}</div></div>`;
  }).join('');
}
function renderStackedVerticalBars(elId,rows,empty){
  const el=$(elId);
  if(!el)return;
  const byPlu={};
  rows.forEach(r=>{
    const value=num(r.cantidad);
    if(value<=0)return;
    const key=r.codigo;
    if(!byPlu[key])byPlu[key]={label:r.codigo,total:0,segments:[]};
    byPlu[key].total+=value;
    byPlu[key].segments.push({label:r.sector,value});
  });
  const data=Object.values(byPlu).sort((a,b)=>b.total-a.total);
  if(!data.length){el.innerHTML=emptyChart(empty);return;}
  const max=Math.max(...data.map(r=>r.total),1);
  el.innerHTML=data.slice(0,24).map(r=>{
    const trackHeight=Math.max(3,r.total/max*100);
    const segs=r.segments.sort((a,b)=>b.value-a.value).map((s,i)=>{
      const h=Math.max(3,s.value/r.total*100);
      return `<div class="stack-seg" style="height:${h}%;background:${chartColors[i%chartColors.length]}" title="${esc(s.label)}: ${fmt(s.value)}">${h>15?fmt(s.value):''}</div>`;
    }).join('');
    return `<div class="vbar-item" title="${esc(r.label)}: ${fmt(r.total)}"><div class="vbar-value">${fmt(r.total)}</div><div class="vbar-track" style="height:170px"><div style="height:${trackHeight}%;width:100%;display:flex;flex-direction:column-reverse">${segs}</div></div><div class="vbar-label">${esc(r.label)}</div></div>`;
  }).join('');
}
function renderProductionCharts(){
  const sectorRows=(productionIndicatorData.entregas_por_sector||[]).map(r=>({label:r.sector,value:num(r.cantidad)}));
  renderPie('chart-prod-sector-pie','legend-prod-sector',sectorRows,'Sin entregas registradas');
  renderVerticalBars('chart-prod-stock-bars',productionStockRows.map(r=>({label:r.codigo,value:num(r.stock_producido)})),'Sin stock producido');
  renderStackedVerticalBars('chart-prod-delivered-bars',productionIndicatorData.entregas_por_sector_plu||[],'Sin entregas registradas');
}
function renderPedidoIndicators(){
  const metrics=pedidoIndicatorData.metrics||{};
  $('o-total').textContent=fmt(metrics.total);
  $('o-pending').textContent=fmt(metrics.pendientes);
  $('o-confirmed').textContent=fmt(num(metrics.confirmados)+num(metrics.parciales));
  renderSimpleBars('chart-orders-sector',(pedidoIndicatorData.pedidos_por_sector||[]).map(r=>({label:r.sector,value:num(r.cantidad),display:`${fmt(r.cantidad)} / ${fmt(r.pedidos)} ped.`})),{empty:'Sin pedidos por sector'});
  renderSimpleBars('chart-orders-plu',(pedidoIndicatorData.pedidos_por_plu||[]).map(r=>({label:r.codigo,value:num(r.cantidad),display:fmt(r.cantidad)})),{empty:'Sin PLUs pedidos'});
  const recent=pedidoIndicatorData.recientes||[];
  $('chart-orders-recent').innerHTML=recent.length?recent.map(r=>`<div class="activity-item"><strong>#${esc(r.id)} - ${esc(statusLabel(r.estado))} - ${fmt(r.cantidad)}</strong><span>${shortDate(r.fecha_solicitud)} - ${esc(r.sector||'-')} - ${esc(r.usuario_solicita||'')} - ${fmt(r.lineas)} PLUs</span></div>`).join(''):emptyChart('Sin pedidos recientes');
}
function renderProductionTables(){
  $('production-stock-body').innerHTML=productionStockRows.map(r=>`<tr><td>${esc(r.codigo)}</td><td>${esc(r.descripcion)}</td><td class="right">${fmt(r.producido)}</td><td class="right">${fmt(r.entregado)}</td><td class="right">${fmt(r.stock_producido)}</td></tr>`).join('')||'<tr><td colspan="5">Sin stock producido.</td></tr>';
  const sectorRows=productionIndicatorData.entregas_por_sector_plu||[];
  const sectorBody=$('production-sector-body');
  if(sectorBody)sectorBody.innerHTML=sectorRows.map(r=>`<tr><td>${esc(r.sector)}</td><td>${esc(r.codigo)}</td><td>${esc(r.descripcion)}</td><td class="right">${fmt(r.cantidad)}</td></tr>`).join('')||'<tr><td colspan="4">Sin entregas por sector.</td></tr>';
  $('production-movements-body').innerHTML=productionMovementRows.map(r=>`<tr><td>${shortDate(r.fecha_hora)}</td><td>${esc(r.codigo)}</td><td>${esc(r.tipo)}</td><td>${esc(r.destino_codigo||'-')}</td><td>${esc(r.turno)}</td><td class="right">${fmt(r.cantidad)}</td><td>${esc(r.usuario||'')}</td><td>${esc(r.observacion||'')}</td></tr>`).join('')||'<tr><td colspan="8">Sin movimientos de produccion.</td></tr>';
}
function renderLogisticSummary(d){
  const range=`${shortDate(d.desde)} / ${shortDate(d.hasta)}`;
  $('logistic-produced-range').textContent=range;
  $('logistic-delivered-range').textContent=range;
  const produced=d.producido||[];
  const delivered=d.entregado||[];
  $('logistic-produced-list').innerHTML=produced.length?produced.map(r=>`<div class="summary-item"><div><b>${esc(r.codigo)}</b><small>${esc(r.descripcion||'')}</small></div><div class="qty">${fmt(r.cantidad)}</div></div>`).join(''):emptyChart('Sin produccion');
  $('logistic-delivered-list').innerHTML=delivered.length?delivered.map(r=>`<div class="summary-item"><div><b>${esc(r.codigo)}</b><small>${esc(r.destino_codigo||'-')} - ${esc(r.descripcion||'')}</small></div><div class="qty">${fmt(r.cantidad)}</div></div>`).join(''):emptyChart('Sin entregas');
}
function sortValue(text){
  const raw=String(text||'').trim();
  if(!raw||raw==='-')return '';
  const normalized=raw.replace(/\./g,'').replace(',', '.');
  if(/^[-+]?\d+(\.\d+)?$/.test(normalized))return Number(normalized);
  const date=Date.parse(raw.replace(' ', 'T'));
  if(!Number.isNaN(date)&&/\d{4}-\d{2}-\d{2}/.test(raw))return date;
  return raw.toLocaleLowerCase('es-AR');
}
function initSortableTables(){
  document.querySelectorAll('.table-wrap table').forEach(table=>{
    if(table.dataset.sortReady)return;
    table.dataset.sortReady='1';
    table.querySelectorAll('thead th').forEach((th,index)=>{
      th.title='Ordenar';
      th.addEventListener('click',()=>{
        const tbody=table.tBodies[0];
        if(!tbody)return;
        const dir=th.dataset.sortDir==='asc'?'desc':'asc';
        table.querySelectorAll('th').forEach(h=>{h.classList.remove('sorted');h.dataset.sortDir='';h.dataset.sortMark='';});
        th.classList.add('sorted');
        th.dataset.sortDir=dir;
        th.dataset.sortMark=dir==='asc'?'^':'v';
        const rows=[...tbody.rows];
        rows.sort((a,b)=>{
          const av=sortValue(a.cells[index]?.textContent);
          const bv=sortValue(b.cells[index]?.textContent);
          if(typeof av==='number'&&typeof bv==='number')return dir==='asc'?av-bv:bv-av;
          return dir==='asc'
            ? String(av).localeCompare(String(bv),'es-AR',{numeric:true,sensitivity:'base'})
            : String(bv).localeCompare(String(av),'es-AR',{numeric:true,sensitivity:'base'});
        });
        rows.forEach(row=>tbody.appendChild(row));
      });
    });
  });
}
window.addEventListener('error',ev=>setStatus(`Error de pantalla: ${ev.message}`,true));
window.addEventListener('unhandledrejection',ev=>setStatus(`Error de pantalla: ${ev.reason?.message||ev.reason||'promesa rechazada'}`,true));
async function api(path,opt={}){
  const controller=new AbortController();
  const {timeoutMs=15000,...fetchOpt}=opt;
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{
    const headers=fetchOpt.body instanceof ArrayBuffer?{}:{'Content-Type':'application/json',...(fetchOpt.headers||{})};
    const r=await fetch(path,{credentials:'same-origin',headers,signal:controller.signal,...fetchOpt});
    if(r.status===401){location.href='/login?next=/panol-insumos';return null}
    const d=await r.json().catch(()=>({}));
    if(!r.ok){
      if(r.status===403)throw new Error(d.detail||'Tu usuario no tiene habilitado Panol Insumos. Pedile a un admin que lo active en Admin > Accesos.');
      if(r.status===404)throw new Error('La API de Panol Insumos no esta disponible. Reinicia el backend de VigIA para cargar el router nuevo.');
      throw new Error(d.detail||`La operacion no pudo completarse. HTTP ${r.status}`);
    }
    return d;
  }catch(e){
    if(e.name==='AbortError')throw new Error(`La API no respondio a tiempo: ${path}`);
    throw e;
  }finally{
    clearTimeout(timer);
  }
}
function optionList(items,empty=''){return `${empty?`<option value="">${esc(empty)}</option>`:''}${items.map(x=>`<option value="${x.id}">${esc(x.codigo)} - ${esc(x.descripcion||'')}</option>`).join('')}`}
function productionDeliveryOptions(empty=''){const rows=productionStockRows.filter(r=>num(r.stock_producido)>0);return `${empty?`<option value="">${esc(empty)}</option>`:''}${rows.map(x=>`<option value="${x.articulo_id}">${esc(x.codigo)} - ${esc(x.descripcion||'')} (${fmt(x.stock_producido)})</option>`).join('')}`}
function locationOptions(empty=''){return `${empty?`<option value="">${esc(empty)}</option>`:''}${(ctx?.ubicaciones||[]).map(x=>`<option value="${x.id}">${esc(x.codigo)}</option>`).join('')}`}
function sortedLocations(){return [...(ctx?.ubicaciones||[])].sort((a,b)=>String(a.codigo||'').localeCompare(String(b.codigo||''),'es-AR',{numeric:true,sensitivity:'base'}))}
function destinationOptions(empty=''){return `${empty?`<option value="">${esc(empty)}</option>`:''}${sortedLocations().map(x=>`<option value="${x.id}">${esc(x.codigo)}</option>`).join('')}`}
function setDefaultLocation(selectId, code){const el=$(selectId);const item=(ctx?.ubicaciones||[]).find(x=>String(x.codigo).toUpperCase()===code);if(el&&item)el.value=String(item.id)}
function turnOptions(empty=''){return `${empty?`<option value="">${esc(empty)}</option>`:''}${(ctx?.turnos||[]).map(x=>`<option value="${esc(x.codigo)}">${esc(x.descripcion||x.codigo)}</option>`).join('')}`}
function usageOptions(value){return String(value||'').replace(/\r/g,'\n').replace(/[;,]/g,'\n').split('\n').map(x=>x.trim()).filter(Boolean)}
function canOperate(){return !!ctx?.user?.can_operate}
function localDateInputValue(date){
  const y=date.getFullYear();
  const m=String(date.getMonth()+1).padStart(2,'0');
  const d=String(date.getDate()).padStart(2,'0');
  return `${y}-${m}-${d}`;
}
function setDefaultIndicatorDates(){
  const today=new Date();
  const first=new Date(today.getFullYear(),today.getMonth(),1);
  if(!$('indicator-date-from').value)$('indicator-date-from').value=localDateInputValue(first);
  if(!$('indicator-date-to').value)$('indicator-date-to').value=localDateInputValue(today);
}
function indicatorQuery({dates=true,plu=true}={}){
  const p=new URLSearchParams();
  if(dates&&$('indicator-date-from')?.value)p.set('fecha_desde',$('indicator-date-from').value);
  if(dates&&$('indicator-date-to')?.value)p.set('fecha_hasta',$('indicator-date-to').value);
  if(plu&&$('indicator-plu')?.value)p.set('articulo_id',$('indicator-plu').value);
  return p;
}
async function refreshAllIndicators(){
  await loadStock();
  await loadIndicators();
  await loadMovements();
  await loadProduction();
  await loadPedidoIndicators();
  renderDashboardCharts();
  setStatus('Indicadores actualizados.');
}
function activateTab(tab){
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));
  const button=document.querySelector(`[data-tab="${tab}"]`);
  if(button)button.classList.add('active');
  $(`panel-${tab}`)?.classList.add('active');
  if(tab==='stock-insumos')activateStockView(document.querySelector('[data-stock-view].active')?.dataset.stockView||'stock');
}
function applyPanolPermissions(){
  const operate=canOperate();
  ['indicadores','stock-insumos','produccion','historial','importacion','articulos','pedidos-pendientes'].forEach(tab=>{
    const btn=document.querySelector(`[data-tab="${tab}"]`);
    if(btn)btn.classList.toggle('hidden',!operate);
  });
  if(!operate)activateTab('pedido-insumos');
}
async function loadContext(){setStatus('Validando sesion y permisos...');ctx=await api('/panol-insumos/api/context');if(!ctx)return;$('user-chip').textContent=`${ctx.user.display_name||ctx.user.username} - ${ctx.user.panol_profile}`;$('article-note').textContent=ctx.user.can_full?'Perfil completo: puede crear articulos e importar CD.':'Perfil operacion: no puede crear articulos ni importar CD.';$('save-article').disabled=false;$('pedido-sector').innerHTML=destinationOptions('Seleccionar sector');applyPanolPermissions();if(!canOperate())return;setDefaultIndicatorDates();$('inv-fecha').value=localDateInputValue(new Date());$('mov-origen').innerHTML=locationOptions('Sin origen');$('mov-destino').innerHTML=destinationOptions('Sin destino');$('deliv-destino').innerHTML=destinationOptions('Seleccionar destino');$('inv-ubicacion').innerHTML=locationOptions();$('hist-ubicacion').innerHTML=locationOptions('Todas');setDefaultLocation('inv-ubicacion','OFICINA_ADO');$('inv-turno').innerHTML=turnOptions();$('hist-turno').innerHTML=turnOptions('Todos');}
async function loadArticles(){const d=await api('/panol-insumos/api/articulos?include_inactive=1');articles=d.items||[];const active=articles.filter(a=>a.activo);$('mov-articulo').innerHTML=optionList(active);$('prod-articulo').innerHTML=optionList(active);$('deliv-articulo').innerHTML='<option value="">Sin PLU con stock producido</option>';$('hist-articulo').innerHTML=optionList(articles,'Todos');$('indicator-plu').innerHTML=optionList(active,'Todos');renderArticles();renderInventoryRows();}
function renderArticles(){$('articles-body').innerHTML=articles.map(a=>`<tr><td>${esc(a.codigo)}</td><td>${esc(a.descripcion)}</td><td>${esc(a.categoria||'')}</td><td>${esc(a.unidad||'UN')}</td><td>${esc(a.uso||'')}</td><td class="right">${fmt(a.stock_minimo)}</td><td>${a.activo?'Si':'No'}</td><td><button class="btn" data-edit-article="${a.id}">Editar</button></td></tr>`).join('')||'<tr><td colspan="8">Sin articulos.</td></tr>'}
function renderInventoryRows(){$('inventory-body').innerHTML=articles.filter(a=>a.activo).map(a=>`<tr><td>${esc(a.codigo)}</td><td>${esc(a.descripcion)}</td><td>${esc(a.unidad||'UN')}</td><td><input class="input right" type="number" step="0.001" min="0" data-inv-art="${a.id}" value="0"></td></tr>`).join('')||'<tr><td colspan="4">Crea articulos para cargar inventario.</td></tr>'}
async function loadStock(){const p=indicatorQuery({dates:false});const d=await api(`/panol-insumos/api/stock?${p}`);stockRows=d.items||[];const m=d.metrics||{};$('m-articulos').textContent=m.total_articulos||0;$('m-bajo').textContent=m.bajo_minimo||0;$('m-movs').textContent=m.movimientos_hoy||0;$('stock-body').innerHTML=stockRows.map(r=>`<tr><td>${esc(r.codigo)}</td><td>${esc(r.descripcion)}</td><td class="right">${fmt(r.stock_cd)}</td><td class="right">${fmt(r.stock_jaula)}</td><td class="right">${fmt(r.stock_oficina)}</td><td class="right">${fmt(r.stock_total)}</td><td class="right">${fmt(r.stock_minimo)}</td><td><span class="state ${r.estado==='BAJO_MINIMO'?'bad':''}">${r.estado==='BAJO_MINIMO'?'Bajo minimo':'OK'}</span></td><td class="right">${r.cobertura_dias==null?'-':fmt(r.cobertura_dias)}</td></tr>`).join('')||'<tr><td colspan="9">Sin stock para mostrar.</td></tr>'}
function statusLabel(estado){const e=String(estado||'');return e==='PENDIENTE'?'Pendiente':e==='CONFIRMADO'?'Confirmado':e==='CONFIRMADO_PARCIAL'?'Parcial':e==='CANCELADO'?'Cancelado':e}
function renderPedidoCatalog(){
  $('pedido-catalog-count').textContent=requestCatalogRows.length;
  $('pedido-catalog-body').innerHTML=requestCatalogRows.map(r=>`<tr><td>${esc(r.codigo)}</td><td>${esc(r.descripcion)}</td><td class="right">${fmt(r.stock_insumo)}</td><td class="right">${fmt(r.stock_produccion)}</td><td><input class="input right" type="number" step="0.001" min="0" max="${num(r.stock_insumo)}" data-pedido-insumo="${r.id}"></td><td><input class="input right" type="number" step="0.001" min="0" max="${num(r.stock_produccion)}" data-pedido-produccion="${r.id}"></td></tr>`).join('')||'<tr><td colspan="6">Sin PLUs con stock positivo.</td></tr>';
}
function renderMyPedidos(){
  $('my-pedidos-count').textContent=myPedidoRows.length;
  $('my-pedidos-list').innerHTML=myPedidoRows.map(p=>`<div class="request-item"><div class="status-line"><strong>#${p.id} - ${esc(statusLabel(p.estado))}</strong><span class="state ${p.estado==='PENDIENTE'?'warn':''}">${esc(p.sector_codigo)}</span></div><span>${shortDate(p.fecha_solicitud)} - ${esc(p.observacion_solicitud||'Sin observacion')}</span><span>${(p.items||[]).map(i=>`${esc(i.codigo)} I:${fmt(i.cantidad_insumo_solicitada)} P:${fmt(i.cantidad_produccion_solicitada)}`).join(' | ')}</span></div>`).join('')||'<div class="detail-empty">Sin pedidos anteriores.</div>';
}
function renderPendingPedidos(){
  const badge=$('pending-badge');
  badge.textContent=pendingPedidoRows.length;
  badge.classList.toggle('hidden',pendingPedidoRows.length<=0);
  $('pending-pedidos-list').innerHTML=pendingPedidoRows.map(p=>`<button class="request-item ${selectedPendingPedido?.id===p.id?'active':''}" data-open-pedido="${p.id}"><strong>#${p.id} - ${esc(p.sector_codigo)}</strong><span>${shortDate(p.fecha_solicitud)} - ${esc(p.usuario_solicita||'')}</span><span>${(p.items||[]).length} PLUs - ${esc(p.observacion_solicitud||'Sin observacion')}</span></button>`).join('')||'<div class="detail-empty">No hay pedidos pendientes.</div>';
}
function renderPendingDetail(p){
  if(!p){$('pending-detail').innerHTML='<div class="detail-empty">Selecciona un pedido pendiente.</div>';return;}
  const originOptions=locationOptions();
  const rows=(p.items||[]).map(i=>{
    const usages=usageOptions(i.uso);
    const usageCell=usages.length
      ? `<select data-confirm-uso="${i.id}"><option value="">Seleccionar uso</option>${usages.map(u=>`<option value="${esc(u)}">${esc(u)}</option>`).join('')}</select>`
      : '<span class="muted">-</span>';
    return `<tr><td>${esc(i.codigo)}</td><td>${esc(i.descripcion)}</td><td class="right">${fmt(i.cantidad_insumo_solicitada)}</td><td class="right">${fmt(i.cantidad_produccion_solicitada)}</td><td><input class="input right" type="number" step="0.001" min="0" max="${num(i.cantidad_insumo_solicitada)}" value="${num(i.cantidad_insumo_solicitada)}" data-confirm-insumo="${i.id}"></td><td><input class="input right" type="number" step="0.001" min="0" max="${num(i.cantidad_produccion_solicitada)}" value="${num(i.cantidad_produccion_solicitada)}" data-confirm-produccion="${i.id}"></td><td>${usageCell}</td></tr>`;
  }).join('');
  $('pending-detail').innerHTML=`<div class="request-head"><div><strong>Pedido #${p.id}</strong><div class="muted">${esc(p.sector_codigo)} - ${shortDate(p.fecha_solicitud)} - ${esc(p.usuario_solicita||'')}</div></div><span class="state warn">Pendiente</span></div><div class="request-body"><label class="field"><span class="label">Origen insumo</span><select id="confirm-origin">${originOptions}</select></label><div class="table-wrap" style="margin-top:12px"><table class="request-table"><thead><tr><th>Codigo</th><th>Descripcion</th><th class="right">Sol. insumo</th><th class="right">Sol. prod.</th><th class="right">Conf. insumo</th><th class="right">Conf. prod.</th><th>Uso</th></tr></thead><tbody>${rows}</tbody></table></div><div class="field" style="margin-top:12px"><label class="label">Observacion cierre</label><textarea id="confirm-obs"></textarea></div><div class="actions" style="margin-top:12px"><button class="btn primary" id="confirm-pedido">Confirmar entrega</button><button class="btn danger" id="cancel-pedido">Cancelar pedido</button></div></div>`;
  setDefaultLocation('confirm-origin','OFICINA_ADO');
  $('confirm-pedido').onclick=()=>confirmPedido(p.id).catch(e=>setStatus(e.message,true));
  $('cancel-pedido').onclick=()=>cancelPedido(p.id).catch(e=>setStatus(e.message,true));
}
async function loadPedidoCatalog(){const d=await api('/panol-insumos/api/pedidos/catalogo')||{};requestCatalogRows=d.items||[];renderPedidoCatalog();}
async function loadMyPedidos(){const d=await api('/panol-insumos/api/pedidos/mios')||{};myPedidoRows=d.items||[];renderMyPedidos();}
async function loadPendingPedidos(){if(!canOperate())return;const d=await api('/panol-insumos/api/pedidos/pendientes')||{};pendingPedidoRows=d.items||[];if(selectedPendingPedido&&!pendingPedidoRows.some(p=>p.id===selectedPendingPedido.id))selectedPendingPedido=null;renderPendingPedidos();renderPendingDetail(selectedPendingPedido);}
async function loadPedidoIndicators(){if(!canOperate())return;const q=indicatorQuery().toString();pedidoIndicatorData=await api(`/panol-insumos/api/pedidos/indicadores${q?`?${q}`:''}`)||{};renderPedidoIndicators();}
async function savePedido(ev){
  ev.preventDefault();
  const items=requestCatalogRows.map(r=>({articulo_id:Number(r.id),cantidad_insumo:Number(document.querySelector(`[data-pedido-insumo="${r.id}"]`)?.value||0),cantidad_produccion:Number(document.querySelector(`[data-pedido-produccion="${r.id}"]`)?.value||0)})).filter(i=>i.cantidad_insumo>0||i.cantidad_produccion>0);
  if(!$('pedido-sector').value)throw new Error('Selecciona un sector.');
  if(!items.length)throw new Error('Carga al menos una cantidad a pedir.');
  const byId=Object.fromEntries(requestCatalogRows.map(r=>[String(r.id),r]));
  for(const item of items){const row=byId[String(item.articulo_id)];if(item.cantidad_insumo>num(row.stock_insumo)||item.cantidad_produccion>num(row.stock_produccion))throw new Error('Hay cantidades que superan el stock disponible.');}
  await api('/panol-insumos/api/pedidos',{method:'POST',body:JSON.stringify({sector_id:Number($('pedido-sector').value),observacion:$('pedido-obs').value,items})});
  $('pedido-obs').value='';document.querySelectorAll('[data-pedido-insumo],[data-pedido-produccion]').forEach(i=>i.value='');
  await loadPedidoCatalog();await loadMyPedidos();await loadPendingPedidos();setStatus('Solicitud enviada.');
}
async function confirmPedido(id){
  const origin=Number($('confirm-origin').value);
  const itemIds=[...document.querySelectorAll('[data-confirm-insumo]')].map(i=>i.dataset.confirmInsumo);
  const items=itemIds.map(itemId=>({item_id:Number(itemId),ubicacion_origen_insumo_id:origin,cantidad_insumo_confirmada:Number(document.querySelector(`[data-confirm-insumo="${itemId}"]`)?.value||0),cantidad_produccion_confirmada:Number(document.querySelector(`[data-confirm-produccion="${itemId}"]`)?.value||0),uso_entrega:document.querySelector(`[data-confirm-uso="${itemId}"]`)?.value||''}));
  await api(`/panol-insumos/api/pedidos/${id}/confirmar`,{method:'POST',body:JSON.stringify({observacion:$('confirm-obs').value,items})});
  selectedPendingPedido=null;await loadPendingPedidos();await loadPedidoCatalog();await loadMyPedidos();if(canOperate()){await loadStock();await loadProduction();await loadPedidoIndicators();renderDashboardCharts();}setStatus('Pedido confirmado.');
}
async function cancelPedido(id){await api(`/panol-insumos/api/pedidos/${id}/cancelar`,{method:'POST',body:JSON.stringify({observacion:$('confirm-obs')?.value||'',items:[]})});selectedPendingPedido=null;await loadPendingPedidos();await loadPedidoIndicators();setStatus('Pedido cancelado.');}
async function loadIndicators(){const q=indicatorQuery().toString();indicatorData=await api(`/panol-insumos/api/indicadores${q?`?${q}`:''}`)||{}}
async function loadMovements(){const q=indicatorQuery().toString();const d=await api(`/panol-insumos/api/movimientos${q?`?${q}`:''}`);movementRows=d.items||[];$('movements-body').innerHTML=movementRows.map(r=>`<tr><td>${shortDate(r.fecha_hora)}</td><td>${esc(r.codigo)}</td><td>${esc(r.tipo)}</td><td>${esc(r.origen_codigo||'-')}</td><td>${esc(r.destino_codigo||'-')}</td><td class="right">${fmt(r.cantidad)}</td><td>${esc(r.usuario||'')}</td><td>${esc(r.observacion||'')}</td></tr>`).join('')||'<tr><td colspan="8">Sin movimientos.</td></tr>'}
function productionIndicatorQuery(){return indicatorQuery().toString()}
function exportProductionIndicators(){const q=productionIndicatorQuery();window.location.href=`/panol-insumos/api/produccion/indicadores/exportar${q?`?${q}`:''}`}
async function loadProduction(){
  const stockQuery=indicatorQuery({dates:false}).toString();
  const stock=await api(`/panol-insumos/api/produccion/stock${stockQuery?`?${stockQuery}`:''}`)||{};
  productionStockRows=stock.items||[];
  const metrics=stock.metrics||{};
  $('p-produced-today').textContent=fmt(metrics.producido_hoy);
  $('p-delivered-today').textContent=fmt(metrics.entregado_hoy);
  $('p-stock-total').textContent=fmt(metrics.stock_total_producido);
  $('deliv-articulo').innerHTML=productionDeliveryOptions('Seleccionar PLU');
  renderLogisticSummary(await api('/panol-insumos/api/produccion/dia-logistico')||{});
  const indQuery=productionIndicatorQuery();
  productionIndicatorData=await api(`/panol-insumos/api/produccion/indicadores${indQuery?`?${indQuery}`:''}`)||{};
  const movesQuery=indicatorQuery().toString();
  const moves=await api(`/panol-insumos/api/produccion/movimientos${movesQuery?`?${movesQuery}`:''}`)||{};
  productionMovementRows=moves.items||[];
  renderProductionCharts();
  renderProductionTables();
  initSortableTables();
}
async function loadInventoryHistory(){const p=new URLSearchParams();if($('hist-fecha').value)p.set('fecha',$('hist-fecha').value);if($('hist-ubicacion').value)p.set('ubicacion_id',$('hist-ubicacion').value);if($('hist-turno').value)p.set('turno',$('hist-turno').value);if($('hist-articulo').value)p.set('articulo_id',$('hist-articulo').value);const d=await api(`/panol-insumos/api/inventario-turno?${p}`);$('inventory-history-body').innerHTML=(d.items||[]).map(r=>`<tr><td>${shortDate(r.fecha_hora)}</td><td>${esc(r.fecha)}</td><td>${esc(r.ubicacion_codigo||'OFICINA_ADO')}</td><td>${esc(r.turno)}</td><td>${esc(r.codigo)}</td><td class="right">${r.stock_inicial==null?'-':fmt(r.stock_inicial)}</td><td class="right">${r.ingresos_turno==null?'-':fmt(r.ingresos_turno)}</td><td class="right">${fmt(r.stock_fisico)}</td><td class="right">${r.consumo_calculado==null?'-':fmt(r.consumo_calculado)}</td><td>${esc(r.usuario||'')}</td></tr>`).join('')||'<tr><td colspan="10">Sin inventarios.</td></tr>'}
function resetArticle(){$('article-id').value='';$('article-code').value='';$('article-desc').value='';$('article-cat').value='';$('article-unit').value='UN';$('article-usage').value='';$('article-min').value='0';$('article-active').value='1'}
async function saveArticle(ev){ev.preventDefault();const id=$('article-id').value;const body={codigo:$('article-code').value,descripcion:$('article-desc').value,categoria:$('article-cat').value,unidad:$('article-unit').value,uso:$('article-usage').value,stock_minimo:Number($('article-min').value||0),activo:$('article-active').value==='1'};await api(id?`/panol-insumos/api/articulos/${id}`:'/panol-insumos/api/articulos',{method:id?'PUT':'POST',body:JSON.stringify(body)});resetArticle();await loadArticles();await loadPedidoCatalog();await loadPendingPedidos();await loadProduction();await loadStock();renderDashboardCharts();setStatus('Articulo guardado.')}
async function saveMovement(ev){ev.preventDefault();const body={articulo_id:Number($('mov-articulo').value),tipo:$('mov-tipo').value,ubicacion_origen_id:$('mov-origen').value?Number($('mov-origen').value):null,ubicacion_destino_id:$('mov-destino').value?Number($('mov-destino').value):null,cantidad:Number($('mov-cantidad').value),motivo:$('mov-motivo').value,observacion:$('mov-obs').value};await api('/panol-insumos/api/movimientos',{method:'POST',body:JSON.stringify(body)});$('movement-form').reset();$('mov-origen').innerHTML=locationOptions('Sin origen');$('mov-destino').innerHTML=destinationOptions('Sin destino');await loadMovements();await loadStock();await loadPedidoCatalog();renderDashboardCharts();setStatus('Movimiento registrado.')}
async function saveProduction(ev){ev.preventDefault();const body={articulo_id:Number($('prod-articulo').value),cantidad:Number($('prod-cantidad').value),observacion:$('prod-obs').value};const d=await api('/panol-insumos/api/produccion',{method:'POST',body:JSON.stringify(body)});$('production-form').reset();await loadProduction();await loadPedidoCatalog();setStatus(`Produccion registrada. Turno: ${esc(d.turno||'')}`)}
async function saveProductionDelivery(ev){ev.preventDefault();if(!$('deliv-articulo').value)throw new Error('No hay PLU con stock producido disponible para entregar.');const body={articulo_id:Number($('deliv-articulo').value),ubicacion_destino_id:Number($('deliv-destino').value),cantidad:Number($('deliv-cantidad').value),observacion:$('deliv-obs').value};const d=await api('/panol-insumos/api/produccion/entregas',{method:'POST',body:JSON.stringify(body)});$('delivery-form').reset();$('deliv-destino').innerHTML=destinationOptions('Seleccionar destino');await loadProduction();await loadPedidoCatalog();setStatus(`Entrega registrada. Turno: ${esc(d.turno||'')}`)}
async function saveInventory(){const items=[...document.querySelectorAll('[data-inv-art]')].map(i=>({articulo_id:Number(i.dataset.invArt),stock_fisico:Number(i.value||0)}));const body={fecha:$('inv-fecha').value,turno:$('inv-turno').value,ubicacion_id:Number($('inv-ubicacion').value),observacion:$('inv-obs').value,items};const d=await api('/panol-insumos/api/inventario-turno',{method:'POST',body:JSON.stringify(body)});await loadIndicators();await loadMovements();await loadInventoryHistory();await loadStock();await loadPedidoCatalog();renderDashboardCharts();setStatus(`Inventario guardado. Ubicacion: ${esc((d.items||[])[0]?.ubicacion||'')}. Lineas: ${(d.items||[]).length}`)}
async function sendCd(preview){const file=$('cd-file').files[0];if(!file)throw new Error('Selecciona un archivo.');const p=new URLSearchParams({filename:file.name,preview:String(preview)});const body=await file.arrayBuffer();const d=await api(`/panol-insumos/api/importar-stock-cd?${p}`,{method:'POST',body});$('cd-preview-body').innerHTML=(d.matched||[]).map(r=>`<tr><td>${esc(r.codigo)}</td><td class="right">${fmt(r.stock_cd)}</td></tr>`).join('')||'<tr><td colspan="2">Sin codigos coincidentes.</td></tr>';setStatus(`${preview?'Preview':'Importacion'}: ${d.matched_count||0} codigos propios, ${d.ignored||0} ignorados.`);if(!preview){await loadStock();renderDashboardCharts();}}
async function syncCdOracle(force=false){
  const p=new URLSearchParams({force:String(force)});
  const d=await api(`/panol-insumos/api/stock-cd/oracle/sincronizar?${p}`,{method:'POST',timeoutMs:180000});
  if(d.skipped&&!force&&confirm('El stock CD de Oracle ya fue sincronizado hoy. Deseas forzar una nueva carga?'))return syncCdOracle(true);
  $('cd-preview-body').innerHTML=(d.matched||[]).map(r=>`<tr><td>${esc(r.codigo)}</td><td class="right">${fmt(r.stock_cd)}</td></tr>`).join('')||`<tr><td colspan="2">${d.skipped?'Sincronizacion ya realizada hoy.':'Sin codigos coincidentes.'}</td></tr>`;
  await loadStock();
  await loadPedidoCatalog();
  renderDashboardCharts();
  setStatus(d.skipped?`Oracle diario: ya sincronizado ${shortDate(d.fecha_importacion)}.`:`Oracle diario: ${d.matched_count||0} PLUs propios actualizados, ${d.zeroed||0} sin stock CD, ${d.ignored||0} ignorados.`);
}
async function resetOperationalData(){const clave=prompt('Clave para depurar datos operativos');if(!clave)return;if(!confirm('Se borraran stock CD, movimientos, inventarios, consumos, produccion y pedidos. Los PLUs se conservan.'))return;const d=await api('/panol-insumos/api/admin/reset-operativo',{method:'POST',body:JSON.stringify({clave})});$('cd-preview-body').innerHTML=Object.entries(d.deleted||{}).map(([tabla,cantidad])=>`<tr><td>${esc(tabla)}</td><td class="right">${fmt(cantidad)}</td></tr>`).join('')||'<tr><td colspan="2">Depuracion ejecutada.</td></tr>';await loadStock();await loadIndicators();await loadMovements();await loadProduction();await loadInventoryHistory();await loadPedidoCatalog();await loadMyPedidos();await loadPendingPedidos();await loadPedidoIndicators();renderDashboardCharts();setStatus('Datos operativos depurados. PLUs conservados.')}
function activateStockView(view){
  document.querySelectorAll('[data-stock-view]').forEach(x=>x.classList.toggle('active',x.dataset.stockView===view));
  document.querySelectorAll('.stock-view').forEach(x=>x.classList.remove('active'));
  const target=$(`stock-view-${view}`);
  if(target)target.classList.add('active');
}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>activateTab(b.dataset.tab));

document.querySelectorAll('[data-stock-view]').forEach(b=>b.onclick=()=>{activateTab('stock-insumos');activateStockView(b.dataset.stockView)});

document.querySelectorAll('[data-prod-view]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-prod-view]').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.prod-view').forEach(x=>x.classList.remove('active'));b.classList.add('active');$(`prod-view-${b.dataset.prodView}`).classList.add('active')});
$('logout-btn').onclick=async()=>{await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});location.href='/login'};
$('refresh-indicators').onclick=()=>refreshAllIndicators().catch(e=>setStatus(e.message,true));
$('article-form').onsubmit=e=>saveArticle(e).catch(err=>setStatus(err.message,true));
$('new-article').onclick=resetArticle;
$('articles-body').onclick=ev=>{const b=ev.target.closest('[data-edit-article]');if(!b)return;const a=articles.find(x=>String(x.id)===String(b.dataset.editArticle));if(!a)return;$('article-id').value=a.id;$('article-code').value=a.codigo;$('article-desc').value=a.descripcion;$('article-cat').value=a.categoria||'';$('article-unit').value=a.unidad||'UN';$('article-usage').value=a.uso||'';$('article-min').value=a.stock_minimo||0;$('article-active').value=a.activo?'1':'0'};
$('movement-form').onsubmit=e=>saveMovement(e).catch(err=>setStatus(err.message,true));
$('production-form').onsubmit=e=>saveProduction(e).catch(err=>setStatus(err.message,true));
$('delivery-form').onsubmit=e=>saveProductionDelivery(e).catch(err=>setStatus(err.message,true));
$('export-prod-indicators').onclick=exportProductionIndicators;
$('save-inventory').onclick=()=>saveInventory().catch(e=>setStatus(e.message,true));
$('inventory-body').addEventListener('keydown',ev=>{
  if(ev.key!=='Enter')return;
  const input=ev.target.closest('[data-inv-art]');
  if(!input)return;
  ev.preventDefault();
  const inputs=[...document.querySelectorAll('[data-inv-art]')];
  const next=inputs[inputs.indexOf(input)+1];
  if(next){next.focus();next.select();}
  else{$('save-inventory').focus();}
});
$('refresh-history').onclick=()=>loadInventoryHistory().catch(e=>setStatus(e.message,true));
$('preview-cd').onclick=()=>sendCd(true).catch(e=>setStatus(e.message,true));
$('import-cd').onclick=()=>sendCd(false).catch(e=>setStatus(e.message,true));
$('sync-cd-oracle').onclick=()=>syncCdOracle(false).catch(e=>setStatus(e.message,true));
$('reset-operational').onclick=()=>resetOperationalData().catch(e=>setStatus(e.message,true));
$('supply-order-form').onsubmit=e=>savePedido(e).catch(err=>setStatus(err.message,true));
$('refresh-pending').onclick=()=>loadPendingPedidos().catch(e=>setStatus(e.message,true));
$('pending-pedidos-list').onclick=ev=>{const b=ev.target.closest('[data-open-pedido]');if(!b)return;selectedPendingPedido=pendingPedidoRows.find(p=>String(p.id)===String(b.dataset.openPedido));renderPendingPedidos();renderPendingDetail(selectedPendingPedido)};
(async()=>{try{initSortableTables();setStatus('Validando sesion y permisos...');await loadContext();setStatus('Cargando pedidos...');await loadPedidoCatalog();await loadMyPedidos();await loadPendingPedidos();if(canOperate()){setStatus('Cargando articulos...');await loadArticles();setStatus('Calculando stock...');await loadStock();setStatus('Cargando indicadores...');await loadIndicators();setStatus('Cargando movimientos...');await loadMovements();setStatus('Cargando produccion...');await loadProduction();setStatus('Cargando pedidos...');await loadPedidoIndicators();setStatus('Cargando inventarios...');await loadInventoryHistory();renderDashboardCharts();}initSortableTables();setStatus('Listo.')}catch(e){setStatus(e.message,true)}})();
