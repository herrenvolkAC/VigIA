(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const state = {meta:null,catalog:{},rows:[],history:[],historySort:'fecha',historyDir:-1,selected:new Set(),dirty:new Map(),view:'pre',pendingOnly:false,sort:'fecha',dir:-1,busy:false,config:null,openingMail:false};
  const collator = new Intl.Collator('es', {numeric:true, sensitivity:'base'});
  const labels = {
    detectada:'Detectada',pre_autorizada:'Pre autorizada',rechazada_jefe:'Rechazada jefe',
    aprobada_gerente:'Aprobada gerente',rechazada_gerente:'Rechazada gerente',
    ajuste_solicitado:'Ajuste solicitado',ajuste_aprobado:'Ajuste aprobado',cargada_sap:'Cargada SAP'
  };
  const viewTitles = {pre:'Pre autorizacion jefe',gerencia:'Aprobacion gerente',ajustes:'RRHH',config:'Configuracion'};
  const viewStates = {
    pre:new Set(['detectada','rechazada_jefe','pre_autorizada']),
    gerencia:new Set(['pre_autorizada','aprobada_gerente','rechazada_gerente']),
    ajustes:new Set(['detectada','pre_autorizada','rechazada_jefe','aprobada_gerente','rechazada_gerente','ajuste_solicitado','ajuste_aprobado','cargada_sap'])
  };
  const DISPLAY_LIMIT = 800;
  const MAX_BULK_DECISIONS = 500;
  const drafts = new Map();
  const editedDrafts = new Set();
  const rowErrors = new Map();
  function draftFor(row){
    const key = `${row.legajo}|${row.fecha}`;
    if(!drafts.has(key)) drafts.set(key,{
      quantity:hours(row.horas_preautorizadas ?? (row.horas_autorizadas || Math.floor(Number(row.horas_extras_detectadas)*60)/60)),
      managerQuantity:hours(row.horas_preautorizadas ?? row.horas_autorizadas ?? 0),
      justificacion:row.justificacion || '',
      adjustmentQuantity:hours(row.horas_autorizadas || 0),
      adjustmentReason:row.ajuste_motivo || ''
    });
    return drafts.get(key);
  }
  function msg(text, error=false){$('message').textContent=text;$('message').classList.toggle('error',error);}
  function localDate(offset=0){const d=new Date();d.setDate(d.getDate()+offset);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
  async function api(path, options={}){
    const res = await fetch(path, {credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
    if(res.status===401){location.replace('/login?next=/horas-extras.html');return null}
    const data = await res.json().catch(()=>({}));
    if(!res.ok) throw new Error(data.detail || 'No se pudo completar la operacion.');
    return data;
  }
  function setBusy(value){
    state.busy=value;
    document.querySelectorAll('#filters button, #filters input, #filters select, #filters textarea, #history-filters button, #history-filters input, #history-filters select, #history-filters textarea, #bulk-bar button, #bulk-bar input, #rows-body .row-quantity, #rows-body [data-edit="justificacion"], #rows-body [data-edit="adjustment-quantity"], #rows-body [data-edit="adjustment-reason"], #rows-body [data-edit="manager-quantity"], #responsable-form button, #responsable-form input, #responsable-form select, #responsable-form textarea, #mail-form button, #mail-form input, #mail-form select, #save-btn, #export-btn, #history-export').forEach(el=>{el.disabled=value});
    renderSelection();
    $('history-export').disabled=value || !state.history.length;
  }
  const hours = HEIndicators.duration;
  function selectedFunctions(){
    return [...document.querySelectorAll('[name="funcion"]:checked')].map(el=>el.value);
  }
  function sectorFunctions(){
    const sector = $('sector-filter').value;
    return sector ? (state.catalog[sector] || []) : [...new Set(Object.values(state.catalog).flat())].sort((a,b)=>collator.compare(a,b));
  }
  function renderFunctions(){
    const search = ($('funcion-search').value||'').toLowerCase();
    const current = new Set(selectedFunctions());
    const funcs = sectorFunctions();
    $('funciones-checks').innerHTML = funcs.filter(f=>f.toLowerCase().includes(search)).map(f => {
      const checked = !current.size || current.has(f);
      return `<label><input type="checkbox" name="funcion" value="${esc(f)}" ${checked?'checked':''}>${esc(f)}</label>`;
    }).join('') || '<div class="eyebrow">Sin funciones</div>';
    updateFunctionSummary();
  }
  function updateFunctionSummary(){
    const total = sectorFunctions().length;
    const count = selectedFunctions().length;
    const label = !total || count===total ? 'Todas las funciones' : `${count} funciones`;
    $('funciones-summary').textContent = label;
    $('funciones-trigger').textContent = label;
  }
  function rowStageVisible(row){
    const stateOk = viewStates[state.view]?.has(row.estado) || false;
    const selectedState = $('estado-filter').value;
    if(!stateOk) return false;
    if(state.pendingOnly && !isPendingForView(row,state.view)) return false;
    return !selectedState || row.estado === selectedState;
  }
  function isPendingForView(row,view){
    if(view==='pre') return ['detectada','rechazada_jefe'].includes(row.estado);
    if(view==='gerencia') return row.estado==='pre_autorizada';
    if(view==='ajustes') return row.estado==='aprobada_gerente' && !row.cargado_sap;
    return false;
  }
  function renderPendingBadges(){
    const countPending=(view)=>state.rows.filter(row=>{
      const key=`${row.legajo}|${row.fecha}`;
      const dirty=state.dirty.get(key);
      if(!dirty?.previousState) return isPendingForView(row,view);
      return isPendingForView({...row,estado:dirty.previousState,cargado_sap:dirty.previousSap??row.cargado_sap},view);
    }).length;
    const counts={
      pre:countPending('pre'),
      gerencia:countPending('gerencia'),
      ajustes:countPending('ajustes'),
    };
    document.querySelectorAll('[data-pending-badge]').forEach(badge=>{
      const count=counts[badge.dataset.pendingBadge]||0;
      badge.textContent=count;
      badge.hidden=count===0;
      badge.title=`${count} pendientes en el rango consultado`;
    });
  }
  function visibleRows(){
    return state.rows.filter(rowStageVisible).sort((a,b)=>{
      const av=a[state.sort], bv=b[state.sort];
      const diff = typeof av === 'number' || typeof bv === 'number'
        ? Number(av||0)-Number(bv||0)
        : collator.compare(String(av||''), String(bv||''));
      return state.dir*diff;
    });
  }
  function stateTone(value){
    if(['aprobada_gerente','cargada_sap','pre_autorizada'].includes(value)) return 'ok';
    if(['rechazada_jefe','rechazada_gerente'].includes(value)) return 'bad';
    if(['ajuste_solicitado'].includes(value)) return 'warn';
    return 'info';
  }
  function renderRows(){
    const rows = visibleRows();
    const displayedRows = rows.slice(0, DISPLAY_LIMIT);
    const overflow = rows.length > DISPLAY_LIMIT
      ? `<tr class="table-note"><td colspan="10">Se muestran ${DISPLAY_LIMIT} de ${rows.length} registros. Acote sector, funcion o fechas para trabajar con mayor fluidez.</td></tr>`
      : '';
    $('table-title').textContent = viewTitles[state.view];
    const totalHours=rows.reduce((sum,row)=>sum+Number(row.horas_extras_detectadas||0),0);
    $('queue-summary').textContent=`${rows.length} ${state.pendingOnly?'pendientes':'registros'} · ${hours(totalHours)} hs detectadas`;
    $('rows-body').innerHTML = displayedRows.map(row=>{
      const key = `${row.legajo}|${row.fecha}`;
      const draft = draftFor(row);
      return `<tr data-key="${esc(key)}" class="${row.sensible?'sensitive':''}">
        <td data-label="Seleccionar"><input class="row-check" data-check="${esc(key)}" type="checkbox" ${state.view==='gerencia'&&row.estado!=='pre_autorizada'?'disabled':''} ${state.selected.has(key)?'checked':''}></td>
        <td data-label="Fecha" class="mono">${esc(row.fecha)}</td>
        <td data-label="Empleado" class="employee-cell"><button class="link-row" data-detail="${esc(key)}" type="button">${esc(row.empleado)}</button><small>Legajo ${esc(row.legajo)}</small></td>
        <td data-label="Sector / funcion" class="sector-cell"><strong>${esc(row.sector)}</strong><small>${esc(row.funcion)}</small></td>
        <td data-label="Jornada" class="shift-cell"><small>PH ${esc(row.ph||'-')}</small><strong>${esc(row.inicio_real||'-')} - ${esc(row.fin_real||'-')}</strong></td>
        <td data-label="Horas extra" class="mono hours-cell">${hours(row.horas_extras_detectadas)}</td>
        <td data-label="Cantidad / preautorizadas" class="quantity-cell">${state.view==='pre'?`<input class="row-quantity mono" data-edit="quantity" data-row="${esc(key)}" aria-label="Cantidad a autorizar para ${esc(row.empleado)} (HH:MM)" value="${esc(draft.quantity)}" placeholder="HH:MM"><small class="partial-label">${Number(draft.quantity.split(':')[0])*60+Number(draft.quantity.split(':')[1]) < Math.round(row.horas_extras_detectadas*60)?'Parcial':''}</small>`:state.view==='gerencia'?`<input class="row-quantity mono" data-edit="manager-quantity" data-row="${esc(key)}" aria-label="Cantidad a aprobar para ${esc(row.empleado)} (HH:MM)" value="${esc(draft.managerQuantity)}" placeholder="HH:MM"><small class="partial-label">${minutesFromHours(draft.managerQuantity)<Math.round(Number(row.horas_preautorizadas ?? row.horas_autorizadas ?? 0)*60)?'Parcial':''}</small>`:state.view==='ajustes'?`<input class="row-quantity mono" data-edit="adjustment-quantity" data-row="${esc(key)}" aria-label="Horas autorizadas para ${esc(row.empleado)} (HH:MM)" value="${esc(draft.adjustmentQuantity)}" placeholder="HH:MM">`:`<span class="mono">${hours(row.horas_preautorizadas ?? row.horas_autorizadas)}</span>`}<small class="row-error" role="status">${state.view==='gerencia'?esc(rowErrors.get(key)||''):''}</small></td>
        <td data-label="Justificacion" class="justification-cell">${state.view==='pre'?`<textarea data-edit="justificacion" data-row="${esc(key)}" maxlength="800" rows="2" aria-label="Justificacion para ${esc(row.empleado)}">${esc(draft.justificacion)}</textarea>`:state.view==='ajustes'?`<textarea data-edit="adjustment-reason" data-row="${esc(key)}" maxlength="800" rows="2" aria-label="Motivo del ajuste para ${esc(row.empleado)}">${esc(draft.adjustmentReason)}</textarea>`:esc(row.justificacion || 'Sin justificacion registrada')}<small class="row-error" role="status">${state.view==='gerencia'?'':esc(rowErrors.get(key)||'')}</small></td>
        <td data-label="Estado"><span class="state ${stateTone(row.estado)}">${esc(labels[row.estado]||row.estado)}</span>${row.horas_autorizadas && row.horas_autorizadas < row.horas_extras_detectadas ? `<div class="mono">${hours(row.horas_autorizadas)} hs aut.</div>` : ''}</td>
        <td data-label="SAP">${row.cargado_sap?'<span class="sap">Si</span>':'-'}</td>
      </tr>`;
    }).join('') + overflow || '<tr class="empty-row"><td colspan="10">No hay registros para esta vista o filtros.</td></tr>';
    document.querySelector('[data-bulk="aprobada_gerente"]').hidden = state.view!=='gerencia';
    document.querySelector('[data-bulk="cargada_sap"]').hidden = state.view!=='ajustes';
    renderPendingBadges();
    renderSelection();
  }
  function renderSelection(){
    document.querySelectorAll('#rows-body input[data-check]').forEach(check=>{
      const row=state.rows.find(item=>`${item.legajo}|${item.fecha}`===check.dataset.check);
      const selectable=state.view!=='gerencia'||row?.estado==='pre_autorizada';
      if(check.checked && selectable) state.selected.add(check.dataset.check);
      else state.selected.delete(check.dataset.check);
    });
    const count = state.selected.size;
    $('bulk-bar').classList.toggle('visible', count>0 || state.dirty.size>0 || (state.view==='gerencia' && editedDrafts.size>0));
    $('selected-count').textContent = count>MAX_BULK_DECISIONS
      ? `${count} seleccionadas · limite ${MAX_BULK_DECISIONS} por accion`
      : `${count} seleccionadas`;
    const selectableRows=visibleRows().filter(row=>state.view!=='gerencia'||row.estado==='pre_autorizada');
    document.querySelectorAll('#rows-body input[data-check]').forEach(check=>{
      const row=state.rows.find(item=>`${item.legajo}|${item.fecha}`===check.dataset.check);
      check.disabled=state.busy || (state.view==='gerencia'&&row?.estado!=='pre_autorizada');
    });
    $('select-all').disabled=state.busy || !selectableRows.length;
    $('select-all').checked = selectableRows.length>0 && selectableRows.every(r=>state.selected.has(`${r.legajo}|${r.fecha}`));
    $('select-all').indeterminate = selectableRows.some(r=>state.selected.has(`${r.legajo}|${r.fecha}`)) && !$('select-all').checked;
    $('save-btn').hidden = state.view==='gerencia';
    const saveCount=state.view==='pre'?count:state.dirty.size;
    $('save-btn').disabled = state.busy || !saveCount || saveCount>MAX_BULK_DECISIONS;
    $('save-btn').textContent = state.view==='pre'?'Guardar decisiones':state.view==='ajustes'?'Guardar ajustes':'Guardar';
    $('export-btn').disabled = state.busy || !state.rows.length;
    document.querySelectorAll('[data-bulk]').forEach(button=>{
      const available = button.dataset.bulk==='aprobada_gerente' ? state.view==='gerencia' : button.dataset.bulk==='rechazada_jefe' ? ['pre','gerencia'].includes(state.view) : button.dataset.bulk==='cargada_sap' ? state.view==='ajustes' : state.view==='pre';
      button.hidden=!available;
      const eligibleCount=state.view==='gerencia'
        ? [...state.selected].filter(key=>state.rows.some(row=>`${row.legajo}|${row.fecha}`===key&&row.estado==='pre_autorizada')).length
        : count;
      button.disabled=state.busy || !eligibleCount || eligibleCount>MAX_BULK_DECISIONS;
    });
  }
  async function loadMeta(){
    const meta = await api('/api/horas-extras/meta');
    if(!meta) return;
    state.meta = meta;
    $('user-label').textContent = meta.user.display_name || meta.user.username;
    $('profile-label').textContent = `${meta.access.profile || meta.user.role || 'consulta'} · ${meta.access.scope || 'modulo'}`;
    const canConfig = ['admin','rrhh'].includes(meta.user.role) || String(meta.access.profile || '').toUpperCase() === 'RRHH';
    $('config-tab').hidden = !canConfig;
    $('rrhh-tab').hidden = !canConfig;
  }
  async function loadFilters(){
    const selectedSector = $('sector-filter').value;
    const data = await api('/api/horas-extras/filtros');
    if(!data) return;
    state.catalog = data.sectores || {};
    const sectors = Object.keys(state.catalog).sort((a,b)=>collator.compare(a,b));
    const keepSelected = selectedSector && sectors.includes(selectedSector);
    $('sector-filter').innerHTML = '<option value="">Todos</option>' + sectors.map(s=>`<option value="${esc(s)}" ${keepSelected && s===selectedSector?'selected':''}>${esc(s)}</option>`).join('');
    const historySector=$('history-sector').value;
    $('history-sector').innerHTML = '<option value="">Todos</option>' + sectors.map(s=>`<option value="${esc(s)}" ${s===historySector?'selected':''}>${esc(s)}</option>`).join('');
    renderFunctions();
  }
  function queryParams(){
    ensureOperationalDates();
    if($('fecha-desde').value>$('fecha-hasta').value) throw new Error('Revise el rango de fechas.');
    const p = new URLSearchParams({desde:$('fecha-desde').value,hasta:$('fecha-hasta').value});
    if($('sector-filter').value) p.set('sector',$('sector-filter').value);
    const funcs = selectedFunctions();
    const all = sectorFunctions();
    if(funcs.length && funcs.length !== all.length) funcs.forEach(f=>p.append('funcion',f));
    return p;
  }
  function ensureOperationalDates(force=false){
    if(force || !$('fecha-hasta').value)$('fecha-hasta').value=localDate();
    if(force || !$('fecha-desde').value)$('fecha-desde').value=localDate(-7);
  }
  async function loadRows(){
    if((editedDrafts.size || state.dirty.size) && !confirm('Descartar las decisiones sin guardar y consultar nuevamente?')) return;
    setBusy(true);msg('Consultando Actividad Diaria y decisiones...');
    try{
      const params = queryParams();
      const selectedState = $('estado-filter').value;
      const data = await api('/api/horas-extras/registros?' + params.toString());
      if(!data) return;
      state.rows = data.rows || [];
      drafts.clear();editedDrafts.clear();rowErrors.clear();
      HEIndicators.capture(state.rows, params, selectedState);
      $('indicadores-tab').hidden = false;
      state.selected.clear();state.dirty.clear();
      renderRows();
      msg(data.quality?.message || `${state.rows.length} registros cargados.`);
    }catch(e){msg(e.message,true)}finally{setBusy(false)}
  }
  function historyParams(){
    ensureHistoryDates();
    if(!$('history-desde').value || !$('history-hasta').value) throw new Error('Seleccione el rango del historial.');
    if($('history-desde').value>$('history-hasta').value) throw new Error('Revise el rango de fechas del historial.');
    const params=new URLSearchParams({desde:$('history-desde').value,hasta:$('history-hasta').value});
    if($('history-sector').value)params.set('sector',$('history-sector').value);
    if($('history-legajo').value.trim())params.set('legajo',$('history-legajo').value.trim());
    if($('history-estado').value)params.set('estado',$('history-estado').value);
    return params;
  }
  function ensureHistoryDates(force=false){
    if(force || !$('history-hasta').value)$('history-hasta').value=localDate();
    if(force || !$('history-desde').value)$('history-desde').value=localDate(-7);
  }
  function renderHistory(){
    const rows=[...state.history].sort((a,b)=>{
      const av=a[state.historySort],bv=b[state.historySort];
      const diff=typeof av==='number'||typeof bv==='number'||typeof av==='boolean'||typeof bv==='boolean' ? Number(av||0)-Number(bv||0) : collator.compare(String(av||''),String(bv||''));
      return state.historyDir*diff;
    });
    $('history-body').innerHTML=rows.map(row=>`<tr><td class="mono">${esc(row.fecha)}</td><td class="mono">${esc(row.legajo)}</td><td>${esc(row.empleado)}</td><td>${esc(row.sector)}</td><td class="mono">${hours(row.horas_extras_detectadas)}</td><td class="mono">${hours(row.horas_preautorizadas)}</td><td class="mono">${hours(row.horas_autorizadas)}</td><td><span class="state ${stateTone(row.estado)}">${esc(labels[row.estado]||row.estado)}</span></td><td>${esc(row.justificacion||'Sin justificacion registrada')}</td><td>${row.cargado_sap?'<span class="sap">Si</span>':'-'}</td><td class="mono">${esc(row.fecha_cambio||'-')}</td></tr>`).join('')||'<tr><td colspan="11">No hay decisiones guardadas para estos filtros.</td></tr>';
    const total=rows.reduce((sum,row)=>sum+Number(row.horas_autorizadas||0),0);
    $('history-summary').textContent=`${rows.length} registros | ${hours(total)} aprobadas`;
    $('history-export').disabled=!rows.length;
  }
  async function loadHistory(){
    setBusy(true);$('history-summary').textContent='Consultando historial...';
    try{const data=await api('/api/horas-extras/historial?'+historyParams().toString());if(!data)return;state.history=data.rows||[];renderHistory();if(data.limit_reached)$('history-summary').textContent+=' | Se alcanzaron los primeros 5.000 registros.';}catch(error){$('history-summary').textContent=error.message;msg(error.message,true)}finally{setBusy(false)}
  }
  async function exportHistory(){
    try{const response=await fetch('/api/horas-extras/historial/exportar.xlsx?'+historyParams().toString(),{credentials:'same-origin'});if(!response.ok)throw new Error('No se pudo exportar el historial.');const blob=await response.blob();const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`historial_horas_extras_${$('history-desde').value}_${$('history-hasta').value}.xlsx`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),30000);}catch(error){msg(error.message,true)}
  }
  function applyBulk(nextState){
    if(!state.selected.size) return;
    if(nextState==='rechazada_jefe' && state.view==='gerencia') nextState='rechazada_gerente';
    const note = $('bulk-note').value.trim();
    for(const key of state.selected){
      const row = state.rows.find(r=>`${r.legajo}|${r.fecha}`===key);
      if(!row) continue;
      if(nextState==='aprobada_gerente' && row.estado!=='pre_autorizada') continue;
      const previousState=row.estado;
      const previousSap=row.cargado_sap;
      row.estado = nextState;
      row.observacion = note;
      if(nextState==='aprobada_gerente') row.horas_autorizadas = row.horas_preautorizadas ?? row.horas_autorizadas;
      state.dirty.set(key, {...row, nextState, note, previousState, previousSap});
    }
    ensureOperationalDates();
    renderRows();
    msg(`${state.dirty.size} cambios preparados. Presione Guardar.`);
  }
  function applySaved(pending,result){
    pending.forEach(saved=>{
      const key = `${saved.legajo}|${saved.fecha}`;
      const row = state.rows.find(r=>`${r.legajo}|${r.fecha}`===key);
      if(!row) return;
      Object.assign(row,saved);
      if(saved.estado==='cargada_sap') row.cargado_sap=true;
      if(saved.estado==='pre_autorizada') row.horas_preautorizadas=saved.horas_autorizadas;
      state.dirty.delete(key);state.selected.delete(key);drafts.delete(key);editedDrafts.delete(key);
    });
    renderRows();
    if(result.mail){
      const url=`mailto:${encodeURIComponent(result.mail.to)}?subject=${encodeURIComponent(result.mail.subject)}&body=${encodeURIComponent(result.mail.body)}`;
      state.openingMail=true;
      window.location.href=url;
      window.setTimeout(()=>{state.openingMail=false;},1500);
      msg(`${result.guardadas} decisiones guardadas. Correo preparado para los legajos configurados.`);
    }else msg(`${result.guardadas} decisiones guardadas.${state.view==='gerencia'?' No hay legajos destinatarios configurados.':''}`);
  }
  function minutesFromHours(value){
    if(!/^\d{2,}:[0-5]\d$/.test(String(value||''))) return NaN;
    const [hh,mm]=value.split(':').map(Number);
    return hh*60+mm;
  }
  async function commitGerencia(nextState){
    if(state.busy) return;
    const note=$('bulk-note').value.trim();
    const pending=[];
    rowErrors.clear();
    for(const key of state.selected){
      const row=state.rows.find(item=>`${item.legajo}|${item.fecha}`===key);
      if(row?.estado!=='pre_autorizada') continue;
      let amount=0;
      if(nextState==='aprobada_gerente'){
        const draft=draftFor(row);
        const minutes=minutesFromHours(draft.managerQuantity);
        const maximum=Math.round(Number(row.horas_preautorizadas ?? row.horas_autorizadas ?? 0)*60);
        if(!Number.isFinite(minutes)||minutes<=0||minutes>maximum){
          rowErrors.set(key,`Use HH:MM, mayor a 00:00 y hasta ${hours(row.horas_preautorizadas ?? row.horas_autorizadas)}.`);
          continue;
        }
        amount=minutes/60;
      }
      pending.push({...row,estado:nextState,horas_autorizadas:amount,observacion:note});
    }
    if(rowErrors.size){renderRows();msg('Revise las cantidades a aprobar en las filas marcadas.',true);return;}
    if(!pending.length){msg('Seleccione registros preautorizados para decidir.',true);return;}
    setBusy(true);msg(nextState==='aprobada_gerente'?'Aprobando decisiones...':'Rechazando decisiones...');
    try{
      const result=await api('/api/horas-extras/decisiones',{method:'POST',body:JSON.stringify({rows:pending.map(row=>({legajo:row.legajo,fecha:row.fecha,etapa:'gerencia',estado:row.estado,horas_autorizadas:row.horas_autorizadas,observacion:row.observacion||'',justificacion:row.justificacion||''}))})});
      if(result) applySaved(pending,result);
    }catch(error){msg(error.message,true)}finally{setBusy(false)}
  }
  function etapaFor(estado){
    if(estado === 'pre_autorizada' || estado === 'rechazada_jefe') return 'pre_autorizacion';
    if(estado === 'aprobada_gerente' || estado === 'rechazada_gerente') return 'gerencia';
    if(estado === 'cargada_sap') return 'sap';
    return 'ajuste';
  }
  async function saveAdjustments(){
    const edits=[...state.dirty.entries()];
    if(!edits.length) return;
    if(edits.length>MAX_BULK_DECISIONS){msg(`Seleccione hasta ${MAX_BULK_DECISIONS} ajustes por guardado.`,true);return;}
    if(edits.some(([,row])=>row.nextState)){
      if(edits.some(([,row])=>row.nextState!=='cargada_sap')){msg('Guarde por separado los ajustes y el marcado SAP.',true);return;}
      const pending=edits.map(([,row])=>row);
      setBusy(true);msg('Actualizando estado SAP...');
      try{
        const result=await api('/api/horas-extras/decisiones',{method:'POST',body:JSON.stringify({rows:pending.map(row=>({legajo:row.legajo,fecha:row.fecha,etapa:'sap',estado:'cargada_sap',horas_autorizadas:row.horas_autorizadas,observacion:row.note||'',justificacion:row.justificacion||''}))})});
        if(result) applySaved(pending,result);
      }catch(error){msg(error.message,true)}finally{setBusy(false)}
      return;
    }
    rowErrors.clear();
    const pending=[];
    for(const [key,edit] of edits){
      const row=state.rows.find(item=>`${item.legajo}|${item.fecha}`===key);
      const raw=String(edit.horas_autorizadas||'').trim();
      const [hh,mm]=raw.split(':').map(Number);
      const amount=hh+mm/60;
      const error=!/^\d{2,}:[0-5]\d$/.test(raw)||!Number.isFinite(amount)||amount<0||amount>Number(row?.horas_extras_detectadas||0)
        ? 'Ingrese horas validas, entre 00:00 y las HE detectadas.'
        : !String(edit.motivo||'').trim() ? 'Indique el motivo del ajuste.' : '';
      if(error) rowErrors.set(key,error);
      else pending.push({legajo:edit.legajo,fecha:edit.fecha,horas_autorizadas:amount,motivo:String(edit.motivo).trim()});
    }
    if(rowErrors.size){renderRows();msg('Revise los ajustes marcados. No se guardo ningun cambio.',true);return;}
    setBusy(true);msg('Guardando ajustes de RRHH...');
    try{
      const result=await api('/api/horas-extras/ajustes',{method:'POST',body:JSON.stringify({rows:pending})});
      if(!result)return;
      for(const saved of result.rows||[]){
        const key=`${saved.legajo}|${saved.fecha}`;
        const row=state.rows.find(item=>`${item.legajo}|${item.fecha}`===key);
        if(row) Object.assign(row,saved);
        const draft=row&&draftFor(row);
        if(draft){draft.adjustmentQuantity=hours(saved.horas_autorizadas);draft.adjustmentReason=saved.ajuste_motivo||'';}
        state.dirty.delete(key);state.selected.delete(key);editedDrafts.delete(key);
      }
      renderRows();msg(`${result.guardadas} ajustes guardados y registrados en el historial.`);
    }catch(error){msg(error.message,true)}finally{setBusy(false)}
  }
  async function save(){
    if(state.busy) return;
    if(state.view==='ajustes'){await saveAdjustments();return;}
    let pending = [...state.dirty.values()];
    if(state.view==='pre'){
      rowErrors.clear();
      pending = [];
      for(const key of state.selected){
        const row = state.rows.find(r=>`${r.legajo}|${r.fecha}`===key);
        if(!row || !viewStates.pre.has(row.estado)) continue;
        if(state.dirty.get(key)?.estado==='rechazada_jefe'){pending.push(state.dirty.get(key));continue;}
        const draft = draftFor(row);
        const [hh,mm] = draft.quantity.split(':').map(Number);
        const quantity = hh+mm/60;
        const error = !/^\d{2,}:[0-5]\d$/.test(draft.quantity)||!Number.isFinite(quantity)||quantity<=0||quantity>row.horas_extras_detectadas
          ? 'Ingrese una cantidad HH:MM mayor a cero y no superior a las HE.'
          : !draft.justificacion.trim() ? 'Ingrese la justificacion de la hora extra.' : '';
        if(error){rowErrors.set(key,error);continue;}
        pending.push({...row,estado:'pre_autorizada',horas_autorizadas:quantity,justificacion:draft.justificacion.trim()});
      }
      if(rowErrors.size){renderRows();msg('Revise las filas marcadas. No se guardo ninguna decision.',true);return;}
    }
    if(!pending.length) return;
    if(pending.length>500){msg('Seleccione hasta 500 registros por guardado.',true);return;}
    setBusy(true);msg('Guardando decisiones...');
    try{
      const rows = pending.map(row=>({
        legajo:row.legajo,fecha:row.fecha,etapa:etapaFor(row.estado),estado:row.estado,
        horas_autorizadas:row.horas_autorizadas,observacion:row.observacion || row.note || '',justificacion:row.justificacion || ''
      }));
      const result = await api('/api/horas-extras/decisiones',{method:'POST',body:JSON.stringify({rows})});
      if(!result) return;
      applySaved(pending,result);
    }catch(e){msg(e.message,true)}finally{setBusy(false)}
  }
  function openDetail(key){
    const row = state.rows.find(r=>`${r.legajo}|${r.fecha}`===key);
    if(!row) return;
    $('drawer-title').textContent = `${row.empleado} · ${row.fecha}`;
    const fields = [
      ['Legajo',row.legajo],['Sector',row.sector],['Funcion',row.funcion],['Area personal',row.desc_area_personal||'-'],
      ['PH',row.ph||'-'],['Inicio real',row.inicio_real||'-'],['Fin real',row.fin_real||'-'],['Horas trabajadas',hours(row.horas_trabajadas)],
      ['HE detectadas',hours(row.horas_extras_detectadas)],['Estado',labels[row.estado]||row.estado],['SAP',row.cargado_sap?'Si':'No'],['Observacion',row.observacion||'-'],['Ultimo ajuste RRHH',row.ajuste_motivo||'-']
    ];
    $('drawer-detail').innerHTML = fields.map(([k,v])=>`<div class="detail-item"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');
    $('drawer-detail').insertAdjacentHTML('beforeend',`<div class="detail-item"><span>Justificacion</span><strong>${esc(row.justificacion||'Sin justificacion registrada')}</strong></div>`);
    $('drawer-detail').insertAdjacentHTML('beforeend',`<button class="ghost-btn" id="open-employee-history" type="button">Ver historial del empleado</button>`);
    $('open-employee-history').onclick=()=>{
      $('history-legajo').value=row.legajo;
      state.history=[];
      document.querySelector('[data-view="historial"]').click();
      $('drawer-close').click();
    };
    $('drawer-trace').textContent = row.usuario_cambio ? `${row.usuario_cambio} · ${row.fecha_cambio}` : 'Sin movimientos guardados en esta vista.';
    $('drawer').classList.add('open');$('drawer').setAttribute('aria-hidden','false');
  }
  async function exportExcel(){
    try{
      const url = '/api/horas-extras/exportar.xlsx?' + queryParams().toString();
      const res = await fetch(url,{credentials:'same-origin'});
      if(!res.ok) throw new Error('No se pudo exportar.');
      const blob = await res.blob();
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `horas_extras_${$('fecha-desde').value}_${$('fecha-hasta').value}.xlsx`;
      document.body.appendChild(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(link.href),30000);
      msg('Excel exportado.');
    }catch(e){msg(e.message,true)}
  }
  function personLabel(person){
    const sector = person.sector ? ` - ${person.sector}` : '';
    return `${person.nombre || person.legajo} (${person.legajo})${sector}`;
  }
  function personOptions(items, selected){
    const current = String(selected || '');
    return '<option value="">Sin asignar</option>' + (items||[]).map(p=>{
      const legajo = String(p.legajo || '');
      return `<option value="${esc(legajo)}" ${legajo===current?'selected':''}>${esc(personLabel(p))}</option>`;
    }).join('');
  }
  async function loadConfig(){
    const data = await api('/api/horas-extras/config/responsables');
    if(!data) return;
    const sectorSelected = $('cfg-sector').value;
    const jefeSelected = $('cfg-jefe').value;
    const gerenteSelected = $('cfg-gerente').value;
    state.config = data;
    $('cfg-sector').innerHTML = '<option value="">Seleccione sector</option>' + (data.sectores||[]).map(s=>`<option value="${esc(s)}" ${s===sectorSelected?'selected':''}>${esc(s)}</option>`).join('');
    $('cfg-jefe').innerHTML = personOptions(data.jefes, jefeSelected);
    $('cfg-gerente').innerHTML = personOptions(data.gerentes, gerenteSelected);
    renderResponsables();
    syncSectorManager();
    await loadMail();
    msg(`Configuracion cargada: ${(data.sectores||[]).length} sectores, ${(data.jefes||[]).length} jefes, ${(data.gerentes||[]).length} gerentes.`);
  }
  function renderResponsables(){
    const rows = state.config?.rows || [];
    const personMap = new Map([...(state.config?.jefes || []), ...(state.config?.gerentes || [])].map(p=>[String(p.legajo), personLabel(p)]));
    const sectors = new Map();
    rows.forEach(row=>{const name=row.sector || 'Sin sector';if(!sectors.has(name))sectors.set(name,[]);sectors.get(name).push(row);});
    const personName = username => personMap.get(String(username || '')) || username || 'Sin asignar';
    $('responsables-body').innerHTML = [...sectors].sort(([a],[b])=>collator.compare(a,b)).map(([sector,items])=>{
      const managers = new Map();
      items.forEach(row=>{
        const key = String(row.gerente_username || '');
        if(!managers.has(key)) managers.set(key,[]);
        managers.get(key).push(row);
      });
      return `
      <details class="sector-branch" open>
        <summary><strong>${esc(sector)}</strong><span>${items.length} ${items.length===1?'asociacion':'asociaciones'}</span></summary>
        <ul class="responsibility-branches">${[...managers].sort(([a],[b])=>collator.compare(personName(a),personName(b))).map(([manager,assignments])=>`
          <li class="responsibility-association">
            <details open>
              <summary><span>Gerente</span> <strong>${esc(personName(manager))}</strong></summary>
              <ul class="responsibility-people">${assignments.sort((a,b)=>collator.compare(personName(a.jefe_username),personName(b.jefe_username))).map(row=>`<li><span>Jefe</span><strong>${esc(personName(row.jefe_username))}</strong>
            <div class="association-meta"><span class="state ${row.activo?'ok':'bad'}">${row.activo?'Activo':'Inactivo'}</span><span>Vigencia: ${esc(row.vigencia_desde || 'Sin inicio')} / ${esc(row.vigencia_hasta || 'Sin fin')}</span><button class="ghost-btn" data-delete-resp="${esc(row.responsable_id)}" type="button" aria-label="Borrar asociacion de ${esc(sector)}">Borrar</button></div>
              </li>`).join('')}</ul>
            </details>
          </li>`).join('')}</ul>
      </details>`;}).join('') || '<p class="insight-empty">Sin responsables configurados.</p>';
  }
  async function loadMail(){
    const data=await api('/api/horas-extras/config/correos');if(!data)return;
    $('mail-recipients').innerHTML=data.rows.map(r=>`<div class="association-meta"><strong>${esc(r.nombre)} (${esc(r.legajo)})</strong><button class="ghost-btn" type="button" data-delete-mail="${esc(r.legajo)}">Quitar</button></div>`).join('') || 'Sin destinatarios configurados.';
  }
  $('mail-form').addEventListener('submit',async e=>{
    e.preventDefault();const button=e.submitter;button.disabled=true;
    try{
      await api('/api/horas-extras/config/correos',{method:'POST',body:JSON.stringify({legajo:$('mail-legajo').value.trim()})});
      $('mail-form').reset();await loadMail();msg('Destinatario guardado.');
    }catch(error){msg(error.message,true)}finally{button.disabled=false;}
  });
  $('mail-recipients').addEventListener('click',async e=>{
    const button=e.target.closest('[data-delete-mail]');if(!button)return;
    button.disabled=true;
    try{await api('/api/horas-extras/config/correos/'+encodeURIComponent(button.dataset.deleteMail),{method:'DELETE'});await loadMail();}catch(error){msg(error.message,true);button.disabled=false;}
  });
  function syncSectorManager(){
    const sector = $('cfg-sector').value;
    const managers = [...new Set((state.config?.rows || []).filter(r=>r.sector===sector && r.activo && r.gerente_username).map(r=>String(r.gerente_username)))];
    const select = $('cfg-gerente');
    if(managers.length === 1){
      if(![...select.options].some(o=>o.value===managers[0])) select.add(new Option(managers[0],managers[0]));
      select.value = managers[0];
    }else select.value = '';
  }
  $('cfg-sector').addEventListener('change',syncSectorManager);
  async function saveResponsable(event){
    event.preventDefault();
    if(state.busy) return;
    const body = {
      sector:$('cfg-sector').value.trim(),
      jefe_username:$('cfg-jefe').value,
      gerente_username:$('cfg-gerente').value,
      activo:$('cfg-activo').checked,
      vigencia_desde:$('cfg-desde').value || null,
      vigencia_hasta:$('cfg-hasta').value || null,
    };
    setBusy(true);
    try{
      const result = await api('/api/horas-extras/config/responsables',{method:'POST',body:JSON.stringify(body)});
      if(!result) return;
      $('cfg-jefe').value = '';
      try{
        await loadConfig();
        msg('Responsable guardado. Arbol de responsables actualizado.');
      }catch(error){msg(`Responsable guardado, pero no se pudo actualizar el arbol: ${error.message}. Presione Consultar.`,true);}
    }finally{setBusy(false);}
  }
  document.addEventListener('click', e=>{
    const btn = e.target.closest('#workflow-nav [data-view], #module-nav [data-view]'); if(!btn) return;
    const pendingBadge=e.target.closest('[data-pending-badge]');
    if(state.view!==btn.dataset.view || pendingBadge) state.selected.clear();
    state.view = btn.dataset.view;
    state.pendingOnly=Boolean(pendingBadge);
    if(state.pendingOnly) $('estado-filter').value='';
    document.querySelectorAll('#workflow-nav [data-view], #module-nav [data-view]').forEach(b=>{
      const active=b.dataset.view===state.view;
      b.classList.toggle('active',active);
      if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
    });
    const config = state.view === 'config';
    const indicators = state.view === 'indicadores';
    const history = state.view === 'historial';
    $('filters').hidden = config || history;
    $('config-panel').hidden = !config;
    $('indicadores-panel').hidden = !indicators;
    $('history-panel').hidden = !history;
    $('grid-panel').hidden = config || indicators || history;
    $('workflow-nav').hidden = config || indicators;
    if(indicators) return;
    if(history){ensureHistoryDates();if(!state.history.length)loadHistory();return;}
    if(config){loadConfig().catch(err=>msg(err.message,true));return}
    ensureOperationalDates();
    renderRows();
  });
  $('filters').addEventListener('submit', e=>{
    e.preventDefault();
    (state.view === 'config' ? loadConfig() : state.view==='historial' ? loadHistory() : loadRows()).catch(err=>msg(err.message,true));
  });
  $('history-filters').addEventListener('submit',event=>{event.preventDefault();loadHistory();});
  $('history-export').onclick=exportHistory;
  document.querySelector('#history-panel thead')?.addEventListener('click',event=>{const button=event.target.closest('[data-history-sort]');if(!button)return;if(state.historySort===button.dataset.historySort)state.historyDir*=-1;else{state.historySort=button.dataset.historySort;state.historyDir=1}renderHistory();});
  $('sector-filter').addEventListener('change',()=>{renderFunctions();});
  $('filters').addEventListener('change',()=>HEIndicators.markFilters());
  $('funcion-search').addEventListener('input',()=>HEIndicators.markFilters());
  $('funciones-trigger').onclick=()=>{
    const open=$('funciones-menu').classList.toggle('open');
    $('funciones-trigger').setAttribute('aria-expanded',String(open));
  };
  $('funcion-search').addEventListener('input',renderFunctions);
  $('funciones-checks').addEventListener('change',updateFunctionSummary);
  document.addEventListener('click', e=>{if(!$('funciones-menu').contains(e.target)){$('funciones-menu').classList.remove('open');$('funciones-trigger').setAttribute('aria-expanded','false');}});
  $('rows-body').addEventListener('click', e=>{
    const detail = e.target.closest('[data-detail]'); if(detail) openDetail(detail.dataset.detail);
  });
  function syncRowCheckbox(check){
    if(!check.isConnected)return;
    const row=state.rows.find(item=>`${item.legajo}|${item.fecha}`===check.dataset.check);
    if(state.view==='gerencia'&&row?.estado!=='pre_autorizada') state.selected.delete(check.dataset.check);
    else if(check.checked) state.selected.add(check.dataset.check);
    else state.selected.delete(check.dataset.check);
    renderSelection();
  }
  document.addEventListener('change', e=>{
    const check=e.target.closest?.('#rows-body input[data-check]');
    if(check) syncRowCheckbox(check);
  }, true);
  document.addEventListener('click', e=>{
    const check=e.target.closest('input[data-check]');
    if(check) window.setTimeout(()=>syncRowCheckbox(check),0);
  }, true);
  $('rows-body').addEventListener('input', e=>{
    const field=e.target.closest('[data-edit]');if(!field) return;
    const row=state.rows.find(r=>`${r.legajo}|${r.fecha}`===field.dataset.row);
    if(!row) return;
    const draft=draftFor(row);
    const fieldName=field.dataset.edit;
    if(fieldName==='adjustment-quantity') draft.adjustmentQuantity=field.value;
    else if(fieldName==='adjustment-reason') draft.adjustmentReason=field.value;
    else draft[fieldName]=field.value;
    editedDrafts.add(field.dataset.row);
    rowErrors.delete(field.dataset.row);
    const errorTarget=field.closest('tr').querySelector(state.view==='gerencia'?'.quantity-cell .row-error':'.justification-cell .row-error');
    if(errorTarget) errorTarget.textContent='';
    if(state.view==='ajustes'){
      state.dirty.set(field.dataset.row,{legajo:row.legajo,fecha:row.fecha,horas_autorizadas:draft.adjustmentQuantity,motivo:draft.adjustmentReason});
    }
    if(fieldName==='quantity' || fieldName==='manager-quantity'){
      const amount=fieldName==='manager-quantity'?minutesFromHours(draft.managerQuantity):minutesFromHours(draft.quantity);
      const maximum=fieldName==='manager-quantity'
        ? Math.round(Number(row.horas_preautorizadas ?? row.horas_autorizadas ?? 0)*60)
        : Math.round(Number(row.horas_extras_detectadas||0)*60);
      const partial=field.closest('tr').querySelector('.partial-label');
      if(partial) partial.textContent=Number.isFinite(amount)&&amount<maximum?'Parcial':'';
    }
    renderSelection();
  });
  document.querySelector('#grid-panel thead').addEventListener('click', e=>{
    const btn = e.target.closest('[data-sort]'); if(!btn) return;
    if(state.sort===btn.dataset.sort) state.dir *= -1; else {state.sort=btn.dataset.sort;state.dir=1}
    renderRows();
  });
  function syncSelectAll(checked){
    const rows=visibleRows().filter(r=>state.view!=='gerencia'||r.estado==='pre_autorizada');
    rows.forEach(row=>{
      const key=`${row.legajo}|${row.fecha}`;
      checked?state.selected.add(key):state.selected.delete(key);
    });
    const keys=new Set(rows.map(row=>`${row.legajo}|${row.fecha}`));
    document.querySelectorAll('#rows-body input[data-check]').forEach(check=>{
      if(keys.has(check.dataset.check)) check.checked=checked;
    });
    renderSelection();
  }
  $('select-all').addEventListener('change',e=>syncSelectAll(e.target.checked));
  $('select-all').addEventListener('click',e=>{
    const checkbox=e.currentTarget;
    window.setTimeout(()=>syncSelectAll(checkbox.checked),0);
  });
  $('bulk-bar').addEventListener('click', e=>{const btn=e.target.closest('[data-bulk]');if(!btn)return;if(state.view==='gerencia'&&['aprobada_gerente','rechazada_jefe'].includes(btn.dataset.bulk)){commitGerencia(btn.dataset.bulk==='rechazada_jefe'?'rechazada_gerente':'aprobada_gerente');return}applyBulk(btn.dataset.bulk);});
  $('responsable-form').addEventListener('submit', e=>saveResponsable(e).catch(err=>msg(err.message,true)));
  $('responsables-body').addEventListener('click', e=>{
    const btn = e.target.closest('[data-delete-resp]');
    if(!btn || !confirm('Borrar este responsable?')) return;
    api(`/api/horas-extras/config/responsables/${btn.dataset.deleteResp}`,{method:'DELETE'}).then(()=>{
      if(state.config?.rows) state.config.rows = state.config.rows.filter(row=>String(row.responsable_id)!==String(btn.dataset.deleteResp));
      renderResponsables();
      msg('Responsable borrado.');
    }).catch(err=>msg(err.message,true));
  });
  $('save-btn').onclick=save;
  window.addEventListener('beforeunload',event=>{
    if(state.openingMail) return;
    if(!editedDrafts.size && !state.dirty.size) return;
    event.preventDefault();event.returnValue='';
  });
  $('export-btn').onclick=exportExcel;
  $('drawer-close').onclick=()=>{$('drawer').classList.remove('open');$('drawer').setAttribute('aria-hidden','true');};
  $('logout-btn').onclick=async()=>{await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});location.replace('/login')};
  ensureOperationalDates(true);
  ensureHistoryDates(true);
  window.addEventListener('pageshow',()=>window.setTimeout(()=>{ensureOperationalDates(true);ensureHistoryDates(true);},0));
  $('sync-chip').textContent = 'Consulta manual';
  renderFunctions();
  renderRows();
  (async()=>{
    try{
      await loadMeta();
      await loadFilters();
      $('sync-chip').textContent = 'Manual';
      msg('Seleccione filtros y presione Consultar.');
    }catch(e){
      msg(e.message,true);
    }
  })();
})();
