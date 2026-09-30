(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const state = {meta:null,catalog:{},rows:[],selected:new Set(),dirty:new Map(),view:'pre',sort:'fecha',dir:-1,busy:false,detailKey:'',config:null};
  const collator = new Intl.Collator('es', {numeric:true, sensitivity:'base'});
  const labels = {
    detectada:'Detectada',pre_autorizada:'Pre autorizada',rechazada_jefe:'Rechazada jefe',
    aprobada_gerente:'Aprobada gerente',rechazada_gerente:'Rechazada gerente',
    ajuste_solicitado:'Ajuste solicitado',ajuste_aprobado:'Ajuste aprobado',cargada_sap:'Cargada SAP'
  };
  const viewTitles = {pre:'Pre autorizacion jefe',gerencia:'Aprobacion gerente',ajustes:'Ajustes y seguimiento',config:'Configuracion'};
  const viewStates = {
    pre:new Set(['detectada','rechazada_jefe','pre_autorizada']),
    gerencia:new Set(['pre_autorizada','aprobada_gerente','rechazada_gerente']),
    ajustes:new Set(['aprobada_gerente','ajuste_solicitado','ajuste_aprobado','cargada_sap'])
  };
  const DISPLAY_LIMIT = 800;
  function msg(text, error=false){$('message').textContent=text;$('message').classList.toggle('error',error);}
  function localDate(offset=0){const d=new Date();d.setDate(d.getDate()+offset);return d.toISOString().slice(0,10);}
  async function api(path, options={}){
    const res = await fetch(path, {credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
    if(res.status===401){location.replace('/login?next=/horas-extras.html');return null}
    const data = await res.json().catch(()=>({}));
    if(!res.ok) throw new Error(data.detail || 'No se pudo completar la operacion.');
    return data;
  }
  function setBusy(value){state.busy=value;document.querySelectorAll('button,input,select').forEach(el=>{if(el.id!=='drawer-close')el.disabled=value});$('save-btn').disabled=value||!state.dirty.size;$('export-btn').disabled=value||!state.rows.length;}
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
    $('funciones-summary').textContent = !total || count===total ? 'Todas las funciones' : `${count} funciones`;
  }
  function rowStageVisible(row){
    const stateOk = viewStates[state.view]?.has(row.estado) || false;
    const selectedState = $('estado-filter').value;
    return stateOk && (!selectedState || row.estado === selectedState);
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
  function renderKpis(){
    const totals = {
      Detectadas: state.rows.length,
      Pendientes: state.rows.filter(r=>r.estado==='detectada').length,
      Jefatura: state.rows.filter(r=>r.estado==='pre_autorizada').length,
      Gerencia: state.rows.filter(r=>r.estado==='aprobada_gerente').length,
      Rechazadas: state.rows.filter(r=>r.estado.includes('rechazada')).length,
      SAP: state.rows.filter(r=>r.cargado_sap).length,
    };
    const tones = ['blue','','violet','green','red','amber'];
    $('kpi-grid').innerHTML = Object.entries(totals).map(([label,value],i)=>`
      <article class="kpi ${tones[i]||''}"><span>${label}</span><strong>${value}</strong><small>${hours(state.rows.filter(r=>label==='SAP'?r.cargado_sap:true).reduce((a,r)=>a+Number(r.horas_extras_detectadas||0),0))} hs detectadas</small></article>
    `).join('');
  }
  function renderRows(){
    const rows = visibleRows();
    const displayedRows = rows.slice(0, DISPLAY_LIMIT);
    const overflow = rows.length > DISPLAY_LIMIT
      ? `<tr><td colspan="12">Se muestran ${DISPLAY_LIMIT} de ${rows.length} registros. Acote sector, funcion o fechas para trabajar con mayor fluidez.</td></tr>`
      : '';
    $('table-title').textContent = viewTitles[state.view];
    $('rows-body').innerHTML = displayedRows.map(row=>{
      const key = `${row.legajo}|${row.fecha}`;
      return `<tr data-key="${esc(key)}" class="${row.sensible?'sensitive':''}">
        <td><input class="row-check" data-check="${esc(key)}" type="checkbox" ${state.selected.has(key)?'checked':''}></td>
        <td class="mono">${esc(row.fecha)}</td><td class="mono">${esc(row.legajo)}</td>
        <td><button class="link-row" data-detail="${esc(key)}" type="button">${esc(row.empleado)}</button></td>
        <td>${esc(row.sector)}</td><td>${esc(row.funcion)}</td><td class="mono">${esc(row.ph||'-')}</td>
        <td class="mono">${esc(row.inicio_real||'-')}</td><td class="mono">${esc(row.fin_real||'-')}</td>
        <td class="mono">${hours(row.horas_extras_detectadas)}</td>
        <td><span class="state ${stateTone(row.estado)}">${esc(labels[row.estado]||row.estado)}</span>${row.horas_autorizadas && row.horas_autorizadas < row.horas_extras_detectadas ? `<div class="mono">${hours(row.horas_autorizadas)} hs aut.</div>` : ''}</td>
        <td>${row.cargado_sap?'<span class="sap">Si</span>':'-'}</td>
      </tr>`;
    }).join('') + overflow || '<tr><td colspan="12">No hay registros para esta vista o filtros.</td></tr>';
    renderSelection();
    renderKpis();
  }
  function renderSelection(){
    const count = state.selected.size;
    $('bulk-bar').classList.toggle('visible', count>0 || state.dirty.size>0);
    $('selected-count').textContent = `${count} seleccionadas`;
    $('select-all').checked = visibleRows().length>0 && visibleRows().every(r=>state.selected.has(`${r.legajo}|${r.fecha}`));
    $('select-all').indeterminate = count>0 && !$('select-all').checked;
    $('save-btn').disabled = state.busy || !state.dirty.size;
    $('export-btn').disabled = state.busy || !state.rows.length;
  }
  async function loadMeta(){
    const meta = await api('/api/horas-extras/meta');
    if(!meta) return;
    state.meta = meta;
    $('user-label').textContent = meta.user.display_name || meta.user.username;
    $('profile-label').textContent = `${meta.access.profile || meta.user.role || 'consulta'} · ${meta.access.scope || 'modulo'}`;
    const canConfig = ['admin','rrhh'].includes(meta.user.role) || String(meta.access.profile || '').toUpperCase() === 'RRHH';
    $('config-tab').hidden = !canConfig;
  }
  async function loadFilters(){
    const selectedSector = $('sector-filter').value;
    const data = await api('/api/horas-extras/filtros');
    if(!data) return;
    state.catalog = data.sectores || {};
    const sectors = Object.keys(state.catalog).sort((a,b)=>collator.compare(a,b));
    const keepSelected = selectedSector && sectors.includes(selectedSector);
    $('sector-filter').innerHTML = '<option value="">Todos</option>' + sectors.map(s=>`<option value="${esc(s)}" ${keepSelected && s===selectedSector?'selected':''}>${esc(s)}</option>`).join('');
    renderFunctions();
  }
  function queryParams(){
    if($('fecha-desde').value>$('fecha-hasta').value) throw new Error('Revise el rango de fechas.');
    const p = new URLSearchParams({desde:$('fecha-desde').value,hasta:$('fecha-hasta').value});
    if($('sector-filter').value) p.set('sector',$('sector-filter').value);
    const funcs = selectedFunctions();
    const all = sectorFunctions();
    if(funcs.length && funcs.length !== all.length) funcs.forEach(f=>p.append('funcion',f));
    return p;
  }
  async function loadRows(){
    setBusy(true);msg('Consultando Actividad Diaria y decisiones...');
    try{
      const params = queryParams();
      const selectedState = $('estado-filter').value;
      const data = await api('/api/horas-extras/registros?' + params.toString());
      if(!data) return;
      state.rows = data.rows || [];
      HEIndicators.capture(state.rows, params, selectedState);
      $('indicadores-tab').hidden = false;
      state.selected.clear();state.dirty.clear();
      renderRows();
      msg(data.quality?.message || `${state.rows.length} registros cargados.`);
    }catch(e){msg(e.message,true)}finally{setBusy(false)}
  }
  function applyBulk(nextState){
    if(!state.selected.size) return;
    const note = $('bulk-note').value.trim();
    for(const key of state.selected){
      const row = state.rows.find(r=>`${r.legajo}|${r.fecha}`===key);
      if(!row) continue;
      row.estado = nextState;
      row.observacion = note;
      if(['pre_autorizada','aprobada_gerente','cargada_sap'].includes(nextState)) row.horas_autorizadas = row.horas_extras_detectadas;
      state.dirty.set(key, {...row, nextState, note});
    }
    renderRows();
    msg(`${state.dirty.size} cambios preparados. Presione Guardar.`);
  }
  function etapaFor(estado){
    if(estado === 'pre_autorizada' || estado === 'rechazada_jefe') return 'pre_autorizacion';
    if(estado === 'aprobada_gerente' || estado === 'rechazada_gerente') return 'gerencia';
    if(estado === 'cargada_sap') return 'sap';
    return 'ajuste';
  }
  function partialStateForView(){
    if(state.view === 'gerencia') return 'aprobada_gerente';
    return 'pre_autorizada';
  }
  async function save(){
    if(!state.dirty.size) return;
    setBusy(true);msg('Guardando decisiones...');
    try{
      const rows = [...state.dirty.values()].map(row=>({
        legajo:row.legajo,fecha:row.fecha,etapa:etapaFor(row.estado),estado:row.estado,
        horas_autorizadas:row.horas_autorizadas,observacion:row.observacion || row.note || ''
      }));
      const result = await api('/api/horas-extras/decisiones',{method:'POST',body:JSON.stringify({rows})});
      if(!result) return;
      state.dirty.clear();state.selected.clear();
      renderRows();
      msg(`${result.guardadas} decisiones guardadas.`);
    }catch(e){msg(e.message,true)}finally{setBusy(false)}
  }
  function openDetail(key){
    const row = state.rows.find(r=>`${r.legajo}|${r.fecha}`===key);
    if(!row) return;
    state.detailKey = key;
    $('drawer-title').textContent = `${row.empleado} · ${row.fecha}`;
    const fields = [
      ['Legajo',row.legajo],['Sector',row.sector],['Funcion',row.funcion],['Area personal',row.desc_area_personal||'-'],
      ['PH',row.ph||'-'],['Inicio real',row.inicio_real||'-'],['Fin real',row.fin_real||'-'],['Horas trabajadas',hours(row.horas_trabajadas)],
      ['HE detectadas',hours(row.horas_extras_detectadas)],['Estado',labels[row.estado]||row.estado],['SAP',row.cargado_sap?'Si':'No'],['Observacion',row.observacion||'-']
    ];
    $('drawer-detail').innerHTML = fields.map(([k,v])=>`<div class="detail-item"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');
    $('partial-hours').value = row.horas_autorizadas && row.horas_autorizadas < row.horas_extras_detectadas ? hours(row.horas_autorizadas) : '';
    $('partial-note').value = row.observacion || '';
    $('drawer-trace').textContent = row.usuario_cambio ? `${row.usuario_cambio} · ${row.fecha_cambio}` : 'Sin movimientos guardados en esta vista.';
    $('drawer').classList.add('open');$('drawer').setAttribute('aria-hidden','false');
  }
  function preparePartial(event){
    event.preventDefault();
    const row = state.rows.find(r=>`${r.legajo}|${r.fecha}`===state.detailKey);
    if(!row) return;
    const input = $('partial-hours').value.trim();
    if(!/^\d{2,}:[0-5]\d$/.test(input)){
      msg('Ingrese las horas en formato HH:MM, por ejemplo 01:45.',true);
      return;
    }
    const [hh,mm] = input.split(':').map(Number);
    const value = hh + mm/60;
    if(!Number.isFinite(value) || value <= 0 || value >= Number(row.horas_extras_detectadas || 0)){
      msg('La aprobacion parcial requiere horas mayores a cero y menores a las detectadas.', true);
      return;
    }
    row.estado = partialStateForView();
    row.horas_autorizadas = value;
    row.observacion = $('partial-note').value.trim() || `Aprobacion parcial por ${hours(value)} hs.`;
    state.dirty.set(state.detailKey, {...row, note:row.observacion});
    state.selected.add(state.detailKey);
    renderRows();
    msg(`Aprobacion parcial preparada para ${row.legajo}: ${hours(value)} hs. Presione Guardar.`);
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
  document.querySelector('.segmented').addEventListener('click', e=>{
    const btn = e.target.closest('[data-view]'); if(!btn) return;
    state.view = btn.dataset.view;
    document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b===btn));
    const config = state.view === 'config';
    const indicators = state.view === 'indicadores';
    $('config-panel').hidden = !config;
    $('indicadores-panel').hidden = !indicators;
    $('grid-panel').hidden = config || indicators;
    $('kpi-grid').hidden = config || indicators;
    document.querySelector('.flow-panel').hidden = config || indicators;
    if(indicators) return;
    if(config){loadConfig().catch(err=>msg(err.message,true));return}
    renderRows();
  });
  $('filters').addEventListener('submit', e=>{
    e.preventDefault();
    (state.view === 'config' ? loadConfig() : loadRows()).catch(err=>msg(err.message,true));
  });
  $('sector-filter').addEventListener('change',()=>{renderFunctions();});
  $('filters').addEventListener('change',()=>HEIndicators.markFilters());
  $('funcion-search').addEventListener('input',()=>HEIndicators.markFilters());
  $('funciones-summary').onclick=()=>$('funciones-menu').classList.toggle('open');
  $('funcion-search').addEventListener('input',renderFunctions);
  $('funciones-checks').addEventListener('change',updateFunctionSummary);
  document.addEventListener('click', e=>{if(!$('funciones-menu').contains(e.target))$('funciones-menu').classList.remove('open');});
  $('rows-body').addEventListener('click', e=>{
    const detail = e.target.closest('[data-detail]'); if(detail) openDetail(detail.dataset.detail);
    const check = e.target.closest('[data-check]'); if(check){check.checked?state.selected.add(check.dataset.check):state.selected.delete(check.dataset.check);renderSelection();}
  });
  document.querySelector('#grid-panel thead').addEventListener('click', e=>{
    const btn = e.target.closest('[data-sort]'); if(!btn) return;
    if(state.sort===btn.dataset.sort) state.dir *= -1; else {state.sort=btn.dataset.sort;state.dir=1}
    renderRows();
  });
  $('select-all').onchange=e=>{visibleRows().forEach(r=>{const k=`${r.legajo}|${r.fecha}`;e.target.checked?state.selected.add(k):state.selected.delete(k)});renderRows();};
  $('bulk-bar').addEventListener('click', e=>{const btn=e.target.closest('[data-bulk]');if(btn)applyBulk(btn.dataset.bulk);});
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
  $('partial-form').addEventListener('submit', preparePartial);
  $('export-btn').onclick=exportExcel;
  $('drawer-close').onclick=()=>{$('drawer').classList.remove('open');$('drawer').setAttribute('aria-hidden','true');state.detailKey='';};
  $('logout-btn').onclick=async()=>{await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});location.replace('/login')};
  $('fecha-hasta').value = localDate();
  $('fecha-desde').value = localDate(-30);
  $('sync-chip').textContent = 'Filtros';
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
