
  const $ = id => document.getElementById(id);
  const GROUP_OPERATIONS = ['PICKING', 'CLARK', 'CARGA', 'CARRETEO', 'CONTROL DE PROCESOS CHP + CBF'];
  const GROUP_FIXED_BY_DIVISION_DEFAULTS = {
    'SECOS + NOA': 260000,
    'OTRAS CAMARAS': 55000,
    'CAMARA 06': 5000,
    'AREA SECOS Y NO ALIMENTOS': 3000,
    'AREA REFRIGERADOS': 0,
  };
  const GROUP_FIXED_DEFAULTS = Object.fromEntries(
    GROUP_OPERATIONS.flatMap(operacion =>
      Object.entries(GROUP_FIXED_BY_DIVISION_DEFAULTS).map(([division, value]) => [`${operacion}|${division}`, value])
    )
  );
  const state = {activeTab:'tabla-premios', propuestaAutonomaView:'bultos', escenarioAumentoTabla:0, escenarioBolsaGrupal:10000000, escenarioBolsaAdicional:0, scenarioSectors:[], scenarioResult:null, scenarioLoading:false, hasConsulted:false, loading:false, evaluacionPickingLoading:false, calculoPagoGrupalLoading:false, punto0Loading:false, loadError:'', fechaDesde:'', fechaHasta:'', operacion:'PICKING', almacen:'TODOS', loadGeneration:0, tabLoadKeys:{}, tabPromises:{}, tabAbortControllers:{}, tabNavigationGeneration:0, ausenciaCatalogo:[], ausenciasNoComputables:['VACAC','FRANCO'], ausenciaScenarioPending:[], resumenRows:[], detalleResumenRows:[], detalleRows:[], detalleGridRows:[], detalleGridTotal:0, groupFixedDaily:{...GROUP_FIXED_DEFAULTS}, groupMarginPct:90, groupBonusRows:[], groupFilters:{almacen:'TODOS', fecha:'', legajo:''}, groupLegajoSelected:'', estudio:null, estudioFilters:{sector:[], estado:'', tipo:'', texto:''}, estudioOperacionSelected:null, estudioEnabled:false, tablaPremios:null, evaluacionPicking:null, evaluacionPickingLegajoFilter:'', evaluacionPickingSelected:'', evaluacionPickingDaySelected:'', evaluacionPickingHourSelected:'', calculoPagoGrupal:null, punto0:null, calculoPagoGrupalSectorSelected:'', calculoPagoGrupalSelectedDate:'', calculoPagoGrupalLegajoSelected:'', sorts:{}, explicacion:null};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const fmt = value => new Intl.NumberFormat('es-AR', {maximumFractionDigits:2}).format(Number(value || 0));
  const money = value => '$ ' + fmt(value);
  const money2 = value => '$ ' + new Intl.NumberFormat('es-AR', {minimumFractionDigits:2, maximumFractionDigits:2}).format(Number(value || 0));
  const signedMoney2 = value => `${Number(value || 0) > 0 ? '+' : ''}${money2(value)}`;
  const round2 = value => Math.round(Number(value || 0) * 100) / 100;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  function groupMarginPct(){
    const value = Number(state.groupMarginPct);
    return Number.isFinite(value) ? clamp(value, 0, 200) : 90;
  }
  function groupMarginRatio(){
    return groupMarginPct() / 100;
  }
  function unidadProductiva(){
    if (state.operacion === 'CONTROL DE PROCESOS CHP + CBF') return 'Huecos';
    if (['CLARK', 'CARGA', 'CARRETEO'].includes(state.operacion)) return 'Pallets';
    return 'Bultos';
  }
  function unidadProductivaLower(){
    return unidadProductiva().toLowerCase();
  }
  function groupFixedKey(division, operacion=state.operacion){
    return `${String(operacion || 'PICKING').trim().toUpperCase()}|${String(division || '').trim()}`;
  }
  function pctDiff(base, value){
    const b = Math.abs(Number(base || 0));
    if (!b) return '0%';
    return `${fmt((Number(value || 0) / b) * 100)}%`;
  }
  function signedMoney(value){ return `${Number(value || 0) > 0 ? '+' : ''}${money(value)}`; }
  function localDateInput(date){
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  }
  function maxQueryDate(){
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return localDateInput(d);
  }
  function previousMonthRange(){
    const today = new Date();
    const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const end = new Date(today.getFullYear(), today.getMonth(), 0);
    return {desde:localDateInput(start), hasta:localDateInput(end)};
  }
  function setupDateLimits(){
    const max = maxQueryDate();
    const range = previousMonthRange();
    ['rango-desde','rango-hasta','detalle-f-fecha'].forEach(id => { $(id).max = max; });
    $('rango-desde').value = range.desde;
    $('rango-hasta').value = range.hasta;
    state.fechaDesde = range.desde;
    state.fechaHasta = range.hasta;
  }
  function syncCombo(){
    state.operacion = $('operacion-select').value || 'PICKING';
    state.almacen = $('almacen-select').value || 'TODOS';
  }
  function currentTabDataKey(){ return `${state.fechaDesde}|${state.fechaHasta}|${state.operacion}|${state.almacen}`; }
  function invalidateTabLoads(){ state.loadGeneration += 1; Object.values(state.tabAbortControllers).forEach(controller=>controller.abort()); state.tabAbortControllers = {}; state.tabLoadKeys = {}; state.tabPromises = {}; }
  function beginTabNavigation(tab){
    Object.entries(state.tabAbortControllers).forEach(([name,controller])=>{if(name!==tab) controller.abort();});
    Object.keys(state.tabAbortControllers).forEach(name=>{if(name!==tab) delete state.tabAbortControllers[name];});
    state.tabNavigationGeneration += 1;
    return state.tabNavigationGeneration;
  }
  function isAbortError(error){ return error?.name === 'AbortError'; }
  function clearLoadedData(){
    invalidateTabLoads();
    state.hasConsulted = false;
    state.resumenRows = [];
    state.detalleResumenRows = [];
    state.detalleRows = [];
    state.detalleGridRows = [];
    state.detalleGridTotal = 0;
    state.groupBonusRows = [];
    state.groupLegajoSelected = '';
    state.estudio = null;
    state.estudioOperacionSelected = null;
    state.evaluacionPicking = null;
    state.tablaPremios = null;
    state.calculoPagoGrupal = null;
    state.ausenciaCatalogo = [];
    state.ausenciaScenarioPending = [];
    state.ausenciasNoComputables = ['VACAC','FRANCO'];
    state.punto0 = null;
    state.evaluacionPickingSelected = '';
    state.evaluacionPickingDaySelected = '';
  }
  function comboParams(){
    syncCombo();
    return {operacion:state.operacion, almacen:state.almacen, divisor_horario:6.5};
  }
  function updateGlobalFiltersForTab(tab=state.activeTab){
    const isStudy = tab === 'estudio';
    const isTablaPremios = tab === 'tabla-premios';
    const isEvaluacionPicking = tab === 'evaluacion-picking';
    const isCalculoPagoGrupal = tab === 'calculo-pago-grupal';
    const isPropuestaAutonoma = tab === 'propuesta-autonoma';
    const isPunto0 = tab === 'punto0';
    $('main-filters').classList.toggle('study-mode', isStudy);
    ['rango-desde','rango-hasta'].forEach(id => $(id)?.closest('.field')?.classList.toggle('hidden', isTablaPremios));
    document.querySelectorAll('.scenario-filter').forEach(el => el.classList.toggle('hidden', isStudy || isTablaPremios || isEvaluacionPicking || isCalculoPagoGrupal || isPropuestaAutonoma || isPunto0));
    $('scope-label').textContent = isStudy ? 'Estudio transversal' : isTablaPremios ? 'Foto de escalas' : isEvaluacionPicking ? 'EvaluaciÃ³n local' : 'Ciclo diario';
    $('scope-text').textContent = isStudy
      ? 'Rango calendario contra Oracle Productiv. No aplica operacion, division ni escenario horario.'
      : isTablaPremios ? 'Escala vigente capturada localmente. Los cambios Oracle se informan y no reemplazan la foto.'
      : isEvaluacionPicking ? 'Bultos reales por hora y sector. Se consulta Oracle sÃ³lo para dÃ­as aÃºn no cargados.'
      : 'Incluye ambos extremos - 06:00 a 06:00 - siempre desde cache';
  }
  async function setupDefaultCachedDate(){
    const range = previousMonthRange();
    $('rango-desde').value = range.desde;
    $('rango-hasta').value = range.hasta;
    state.fechaDesde = range.desde;
    state.fechaHasta = range.hasta;
  }

  function setStatus(text, error=false){ $('status').textContent = text; $('status').classList.toggle('error', error); }
  function setBusy(isBusy){
    state.loading = isBusy;
    $('consultar-rango').disabled = isBusy;
    $('rango-desde').disabled = isBusy;
    $('rango-hasta').disabled = isBusy;
    $('operacion-select').disabled = isBusy;
    $('almacen-select').disabled = isBusy;
    $('detalle-f-fecha').disabled = isBusy;
    $('detalle-f-legajo').disabled = isBusy;
    $('limpiar-detalle-filtros').disabled = isBusy;
    document.querySelectorAll('.tab-btn,.row-link,#cerrar-detalle').forEach(el => { el.disabled = isBusy; });
    $('consultar-rango').textContent = isBusy ? 'Consultando...' : 'Consultar';
  }
  async function api(path, options={}){
    const res = await fetch(path, {credentials:'same-origin', headers:{'Content-Type':'application/json'}, ...options});
    if (res.status === 401) { location.href = '/login?next=/analisis-premio-productividad.html'; return {}; }
    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || 'No se pudo completar la operacion.'); }
    return res.json();
  }
  function qs(params){ return Object.entries(params).filter(([,v]) => v !== '' && v !== null && v !== undefined && v !== false).map(([k,v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&'); }
  function kpi(label, value, foot='', cls=''){ return `<article class="kpi-cell ${cls}"><div class="label">${esc(label)}</div><div class="kpi-number">${esc(value)}</div><div class="kpi-foot">${esc(foot)}</div></article>`; }
  function productividadFoot(bultos, legajos, dias=1){
    const qtyBultos = Number(bultos || 0);
    const qtyLegajos = Number(legajos || 0);
    const qtyDias = Math.max(1, Number(dias || 1));
    const bultosDia = qtyBultos / qtyDias;
    const prod = qtyLegajos ? bultosDia / qtyLegajos : 0;
    return `${unidadProductiva()}/dia ${fmt(bultosDia)} Â· Legajos ${fmt(qtyLegajos)} Â· Productividad ${fmt(prod)}`;
  }
  function bars(id, rows, key='valor', label='grupo'){
    const max = Math.max(...(rows || []).map(r => Math.abs(Number(r[key] || 0))), 1);
    $(id).innerHTML = `<div class="bars">${(rows || []).slice(0,10).map((r,i) => {
      const val = Number(r[key] || 0); const pct = Math.max(2, Math.abs(val) / max * 100);
      const cls = val < 0 ? 'bad' : i % 3 === 1 ? 'blue' : i % 3 === 2 ? 'amber' : '';
      return `<div class="bar-row"><div class="bar-label" title="${esc(r[label])}">${esc(r[label])}</div><div class="bar-track"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div><div class="bar-value">${fmt(val)}</div></div>`;
    }).join('') || '<div class="empty">Sin datos</div>'}</div>`;
  }
  function groupPaymentsByDate(rows){
    const map = new Map();
    (rows || []).forEach(row => {
      const fecha = String(row.fecha || '').slice(0, 10);
      if (!fecha) return;
      const item = map.get(fecha) || {fecha, premio:0, sinExtras:0, horas:0, horasSinExtras:0};
      item.premio += Number(row.premio_anterior || 0);
      item.sinExtras += Number(row.premio_actual || 0);
      item.horas += Number(row.premio_x_horas || 0);
      item.horasSinExtras += Number(row.premio_x_horas_sin_extras || 0);
      map.set(fecha, item);
    });
    return [...map.values()].sort((a,b) => a.fecha.localeCompare(b.fecha));
  }
  function renderPaymentEvolution(id, rows){
    const data = groupPaymentsByDate(rows);
    const w=1800,h=250,left=72,right=18,top=18,bottom=42;
    const max = Math.max(...data.flatMap(r => [r.premio, r.sinExtras, r.horas, r.horasSinExtras]), 1);
    const plotW = w - left - right, plotH = h - top - bottom;
    const xFor = i => left + (data.length === 1 ? plotW / 2 : i * plotW / (data.length - 1));
    const yFor = v => top + plotH - (Number(v || 0) / max) * plotH;
    const series = [
      {key:'premio', label:'Pagado actual', tone:'ok'},
      {key:'sinExtras', label:'Sin extras', tone:'amber'},
      {key:'horas', label:'Por horas con extras', tone:'blue'},
      {key:'horasSinExtras', label:'Por horas sin extras', tone:'red'},
    ];
    const mid = max / 2;
    const tickCount = Math.min(7, data.length);
    const tickIndexes = [...new Set(Array.from({length:tickCount},(_,i)=>Math.round(i * (data.length - 1) / Math.max(tickCount - 1, 1))))];
    $(id).innerHTML = data.length ? `
      <div class="evolution-wrap">
        <svg class="line-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Evolucion de pagos">
          <line class="grid" x1="${left}" y1="${yFor(max)}" x2="${w-right}" y2="${yFor(max)}"></line>
          <line class="grid" x1="${left}" y1="${yFor(mid)}" x2="${w-right}" y2="${yFor(mid)}"></line>
          <line class="axis" x1="${left}" y1="${top}" x2="${left}" y2="${h-bottom}"></line>
          <line class="axis" x1="${left}" y1="${h-bottom}" x2="${w-right}" y2="${h-bottom}"></line>
          <text class="axis-label" x="4" y="${yFor(max)+4}">${esc(money(max))}</text>
          <text class="axis-label" x="4" y="${yFor(mid)+4}">${esc(money(mid))}</text>
          <text class="axis-label" x="4" y="${h-bottom+4}">$ 0</text>
          ${tickIndexes.map(i => {
            const x = xFor(i);
            const label = String(data[i]?.fecha || '').slice(5);
            return `<line class="grid" x1="${x}" y1="${h-bottom}" x2="${x}" y2="${h-bottom+4}"></line><text class="axis-label" x="${Math.max(2, Math.min(x - 16, w - right - 34))}" y="${h-8}">${esc(label)}</text>`;
          }).join('')}
          ${series.map(s => `<polyline class="${s.tone}" points="${data.map((r,i)=>`${xFor(i)},${yFor(r[s.key])}`).join(' ')}"></polyline>`).join('')}
          ${series.map(s => data.map((r,i) => {
            const x = xFor(i), y = yFor(r[s.key]);
            const textX = Math.min(x + 8, w - right - 190);
            const textY = Math.max(y - 8, top + 10);
            return `
              <g class="point">
                <circle class="${s.tone}" cx="${x}" cy="${y}" r="3"></circle>
                <circle class="point-hit" cx="${x}" cy="${y}" r="12"></circle>
                <text class="point-label" x="${textX}" y="${textY}">${esc(r.fecha)} - ${esc(s.label)} - ${esc(money(r[s.key]))}</text>
              </g>`;
          }).join('')).join('')}
        </svg>
      </div>
      <div class="chart-legend">
        <span><i class="legend-dot"></i>Pagado actual</span>
        <span><i class="legend-dot amber"></i>Sin extras</span>
        <span><i class="legend-dot blue"></i>Por horas con extras</span>
        <span><i class="legend-dot red"></i>Por horas sin extras</span>
      </div>
    ` : '<div class="empty">Sin datos</div>';
  }
  function sortValue(row, col){
    const value = row[col.key];
    if (col.num || col.money || typeof value === 'number') return Number(value || 0);
    return String(value ?? '').toLocaleLowerCase('es-AR');
  }
  function sortedRows(id, cols, rows){
    const sort = state.sorts[id];
    const data = [...(rows || [])];
    if (!sort) return data;
    const col = cols.find(c => c.key === sort.key);
    if (!col) return data;
    data.sort((a,b) => {
      const av = sortValue(a, col); const bv = sortValue(b, col);
      if (av < bv) return sort.dir === 'asc' ? -1 : 1;
      if (av > bv) return sort.dir === 'asc' ? 1 : -1;
      return 0;
    });
    return data;
  }
  function table(id, cols, rows, options={}){
    const sort = state.sorts[id];
    const sorted = sortedRows(id, cols, rows);
    const data = options.maxRows ? sorted.slice(0, options.maxRows) : sorted;
    $(id).innerHTML = `<thead><tr>${cols.map(c => {
      const mark = sort?.key === c.key ? (sort.dir === 'asc' ? ' â†‘' : ' â†“') : '';
      return `<th class="sortable" data-key="${esc(c.key)}" style="${c.w ? `width:${c.w}` : ''}" title="Ordenar por ${esc(c.label)}">${esc(c.label)}${mark}</th>`;
    }).join('')}</tr></thead><tbody>${data.map(row => `<tr>${cols.map(c => {
      const raw = row[c.key]; const shown = c.format ? c.format(raw, row) : c.money ? money(raw) : c.num ? fmt(raw) : c.bool ? (raw ? '<span class="pill warn">Si</span>' : '<span class="pill">No</span>') : esc(raw);
      const val = c.link ? `<button class="secondary-cta row-link" data-action="${esc(c.link)}" data-key="${esc(c.key)}">${shown}</button>` : shown;
      return `<td class="${c.mono ? 'mono' : ''}" title="${esc(raw)}">${val}</td>`;
    }).join('')}</tr>`).join('') || `<tr><td colspan="${cols.length}">Sin datos.</td></tr>`}</tbody>`;
    $(id).querySelectorAll('th.sortable').forEach(th => {
      th.onclick = () => {
        const key = th.dataset.key;
        const current = state.sorts[id];
        state.sorts[id] = current?.key === key && current.dir === 'asc' ? {key, dir:'desc'} : {key, dir:'asc'};
        table(id, cols, rows, options);
      };
    });
    $(id).querySelectorAll('[data-action="detalle-legajo"]').forEach(btn => {
      btn.onclick = event => {
        event.stopPropagation();
        const tr = btn.closest('tr');
        const index = Array.from(tr.parentElement.children).indexOf(tr);
        const row = data[index];
        cargarDetalleLegajo(row.fecha, row.operario).catch(e => setStatus(e.message, true));
      };
    });
    $(id).querySelectorAll('[data-action="estudio-operacion"]').forEach(btn => {
      btn.onclick = event => {
        event.stopPropagation();
        const tr = btn.closest('tr');
        const index = Array.from(tr.parentElement.children).indexOf(tr);
        const row = data[index];
        seleccionarEstudioOperacion(row);
      };
    });
    if (id === 'tabla-estudio-operacion') {
      $(id).querySelectorAll('tbody tr').forEach((tr, index) => {
        tr.style.cursor = 'pointer';
        tr.onclick = () => seleccionarEstudioOperacion(data[index]);
      });
    }
  }
  function optionList(values, selected, emptyLabel){
    return `<option value="">${esc(emptyLabel)}</option>${(values || []).map(value => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(value)}</option>`).join('')}`;
  }
  function updateEstudioChecklistSummary(key){
    const selected = state.estudioFilters[key] || [];
    const summary = $(`estudio-summary-${key}`);
    const clearBtn = document.querySelector(`[data-estudio-clear="${key}"]`);
    const allBtn = document.querySelector(`[data-estudio-select-all="${key}"]`);
    const emptyLabel = key === 'funcion' ? 'Todas' : 'Todos';
    if (summary) summary.textContent = selected.length ? `${selected.length} seleccionados` : emptyLabel;
    if (clearBtn) clearBtn.disabled = selected.length === 0;
    if (allBtn) allBtn.disabled = selected.length > 0 && selected.length === $(`estudio-f-${key}`).querySelectorAll('input').length;
  }
  function setEstudioChecklist(key, values){
    const box = $(`estudio-f-${key}`);
    const available = values || [];
    const keep = (state.estudioFilters[key] || []).filter(value => available.includes(value));
    state.estudioFilters[key] = keep;
    updateEstudioChecklistSummary(key);
    box.innerHTML = available.map(value => `
      <label class="study-check-item" title="${esc(value)}">
        <input type="checkbox" data-estudio-filter="${esc(key)}" value="${esc(value)}" ${keep.includes(value) ? 'checked' : ''}>
        <span>${esc(value)}</span>
      </label>
    `).join('') || '<div class="empty">Sin opciones</div>';
  }
  function filteredEstudioRows(){
    const data = state.estudio || {};
    const f = state.estudioFilters;
    const text = String(f.texto || '').trim().toLowerCase();
    const sectores = new Set(f.sector || []);
    return (data.rows || []).filter(row => {
      if (sectores.size && !sectores.has(row.sector)) return false;
      if (f.estado && row.estado !== f.estado) return false;
      if (f.tipo && row.tipo_cobro !== f.tipo) return false;
      if (text) {
        const hay = [row.legajo,row.nombre,row.sector,row.funcion_rrhh,row.operaciones_premio,row.operaciones_medibles_premio,row.operaciones_no_medibles_premio,row.divisiones_premio,row.estado,row.tipo_cobro].join(' ').toLowerCase();
        if (!hay.includes(text)) return false;
      }
      return true;
    });
  }
  function estudioOperacionMatches(row, selected){
    if (!selected || !selected.operacion) return false;
    return (row.operaciones_detalle || []).some(item =>
      String(item.operacion || '') === String(selected.operacion || '') &&
      String(item.tipo_premio || '') === String(selected.tipo_premio || '')
    );
  }
  function estudioOperacionValues(row, selected){
    const items = (row.operaciones_detalle || []).filter(item =>
      String(item.operacion || '') === String(selected.operacion || '') &&
      String(item.tipo_premio || '') === String(selected.tipo_premio || '')
    );
    return {
      ...row,
      operacion_seleccionada: selected.operacion,
      tipo_premio_seleccionado: selected.tipo_premio,
      dias_operacion: items.reduce((acc, item) => acc + Number(item.dias_con_medicion || 0), 0),
      jornadas_operacion: items.reduce((acc, item) => acc + Number(item.jornadas_con_medicion || 0), 0),
      jornadas_premio_operacion: items.reduce((acc, item) => acc + Number(item.jornadas_con_premio || 0), 0),
      productividad_operacion: round2(items.reduce((acc, item) => acc + Number(item.productividad_total || 0), 0)),
      premio_operacion: round2(items.reduce((acc, item) => acc + Number(item.premio_total || 0), 0)),
    };
  }
  function seleccionarEstudioOperacion(row){
    if (!row || !row.operacion) return;
    state.estudioOperacionSelected = {operacion: row.operacion || '', tipo_premio: row.tipo_premio || ''};
    renderEstudioOperacionLegajos();
    $('tabla-estudio-operacion-legajos')?.closest('.data-panel')?.scrollIntoView({behavior:'smooth', block:'start'});
    setStatus(`Operacion seleccionada: ${row.operacion} (${row.tipo_premio || 'Premio'}).`);
  }
  function estudioBySector(rows){
    const map = new Map();
    (rows || []).forEach(row => {
      const key = row.sector || 'Sin sector';
      const item = map.get(key) || {sector:key, activos:0, con_premio:0, con_actividad:0, actividad_sin_premio:0, premio_medible_total:0, premio_no_medible_total:0, premio_total:0};
      item.activos += 1;
      if (Number(row.premio_actual_total || 0) > 0) item.con_premio += 1;
      if (Number(row.productividad_total || 0) > 0) item.con_actividad += 1;
      if (Number(row.productividad_total || 0) > 0 && Number(row.premio_actual_total || 0) <= 0) item.actividad_sin_premio += 1;
      item.premio_medible_total = round2(item.premio_medible_total + Number(row.premio_medible_total || 0));
      item.premio_no_medible_total = round2(item.premio_no_medible_total + Number(row.premio_no_medible_total || 0));
      item.premio_total = round2(item.premio_total + Number(row.premio_actual_total || 0));
      map.set(key, item);
    });
    return [...map.values()].sort((a,b) => Number(b.premio_total || 0) - Number(a.premio_total || 0));
  }
  function estudioByOperacion(rows){
    const map = new Map();
    (rows || []).forEach(row => {
      (row.operaciones_detalle || []).forEach(op => {
        const operacion = String(op.operacion || '').trim();
        const tipo = String(op.tipo_premio || '').trim();
        if (!operacion) return;
        const key = `${tipo}|${operacion}`;
        const item = map.get(key) || {operacion, tipo_premio:tipo, legajos_set:new Set(), legajos:0, productividad_total:0, premio_total:0};
        item.legajos_set.add(String(row.legajo || ''));
        item.productividad_total = round2(item.productividad_total + Number(op.productividad_total || 0));
        item.premio_total = round2(item.premio_total + Number(op.premio_total || 0));
        map.set(key, item);
      });
    });
    return [...map.values()].map(item => ({...item, legajos:item.legajos_set.size, legajos_set:undefined})).sort((a,b) => Number(b.premio_total || 0) - Number(a.premio_total || 0));
  }
  function renderEstudioOperacionLegajos(){
    const selected = state.estudioOperacionSelected;
    if (!selected || !selected.operacion) {
      $('estudio-operacion-detalle-title').textContent = 'click en una operacion';
      table('tabla-estudio-operacion-legajos', [
        {key:'legajo', label:'Legajo', mono:true},
        {key:'nombre', label:'Nombre'},
      ], []);
      return;
    }
    const rows = filteredEstudioRows().filter(row => estudioOperacionMatches(row, selected)).map(row => estudioOperacionValues(row, selected));
    $('estudio-operacion-detalle-title').textContent = `${selected.operacion} Â· ${selected.tipo_premio || 'Premio'} Â· ${fmt(rows.length)} legajos`;
    table('tabla-estudio-operacion-legajos', [
      {key:'legajo', label:'Legajo', w:'82px', mono:true},
      {key:'nombre', label:'Nombre', w:'210px'},
      {key:'sector', label:'Sector RRHH', w:'190px'},
      {key:'funcion_rrhh', label:'Funcion RRHH', w:'190px'},
      {key:'tipo_cobro', label:'Tipo cobro', w:'100px'},
      {key:'operacion_seleccionada', label:'Operacion', w:'210px'},
      {key:'tipo_premio_seleccionado', label:'Tipo op.', w:'100px'},
      {key:'dias_operacion', label:'Dias op.', num:true, w:'86px'},
      {key:'jornadas_operacion', label:'Jorn. op.', num:true, w:'92px'},
      {key:'jornadas_premio_operacion', label:'Jorn. premio op.', num:true, w:'130px'},
      {key:'productividad_operacion', label:'Prod. op.', num:true, w:'100px'},
      {key:'premio_operacion', label:'Premio op.', money:true, w:'120px'},
      {key:'premio_actual_total', label:'Premio', money:true, w:'120px'},
    ], rows);
  }
  function renderEstudio(){
    const data = state.estudio || {};
    const k = data.kpis || {};
    const rows = filteredEstudioRows();
    const sectorRows = estudioBySector(rows);
    const operacionRows = estudioByOperacion(rows);
    const filtradosConPremio = rows.filter(r => Number(r.premio_actual_total || 0) > 0).length;
    const filtradosActividadSinPremio = rows.filter(r => Number(r.productividad_total || 0) > 0 && Number(r.premio_actual_total || 0) <= 0).length;
    $('kpis-estudio').innerHTML = [
      kpi('Activos RRHH', fmt(k.activos_rrhh), 'Universo rrhh_personas active=1.', 'blue'),
      kpi('Cobran productividad', fmt(k.con_premio), `${fmt(k.sin_premio)} activos sin premio en el rango.`, 'ok'),
      kpi('Cobro no medible', fmt(k.con_premio_no_medible), `${money(k.premio_no_medible_total)} de premio sin unidad productiva.`, k.con_premio_no_medible ? 'warn' : 'ok'),
      kpi('Premio medible', money(k.premio_medible_total), `${money(k.premio_no_medible_total)} no medible.`, 'ok'),
      kpi('Premio total actual', money(k.premio_total), `${fmt(k.jornadas_con_premio)} jornadas con pago.`, 'ok'),
      kpi('Filtrados visibles', fmt(rows.length), `${fmt(filtradosConPremio)} cobran; ${fmt(filtradosActividadSinPremio)} actividad sin premio.`),
      kpi('Fuera RRHH activo', fmt(k.premio_fuera_rrhh_activo), `${money(k.premio_fuera_rrhh_total)} con premio/actividad fuera del universo.`, k.premio_fuera_rrhh_activo ? 'bad' : 'ok'),
    ].join('');
    const meta = data.meta || {};
    $('estudio-meta').textContent = `${meta.fecha_desde || state.fechaDesde} a ${meta.fecha_hasta || state.fechaHasta} Â· ${fmt(rows.length)} legajos visibles`;
    table('tabla-estudio-legajos', [
      {key:'legajo', label:'Legajo', w:'82px', mono:true},
      {key:'nombre', label:'Nombre', w:'210px'},
      {key:'sector', label:'Sector RRHH', w:'190px'},
      {key:'funcion_rrhh', label:'Funcion RRHH', w:'190px'},
      {key:'tipo_cobro', label:'Tipo cobro', w:'100px'},
      {key:'operaciones_medibles_premio', label:'Op. medible', w:'190px'},
      {key:'operaciones_no_medibles_premio', label:'Op. no medible', w:'190px'},
      {key:'divisiones_premio', label:'Division premio', w:'150px'},
      {key:'estado', label:'Estado', w:'150px'},
      {key:'dias_con_medicion', label:'Dias med.', num:true, w:'86px'},
      {key:'jornadas_con_premio', label:'Jorn. premio', num:true, w:'105px'},
      {key:'productividad_total', label:'Prod.', num:true, w:'100px'},
      {key:'premio_medible_total', label:'Premio med.', money:true, w:'120px'},
      {key:'premio_no_medible_total', label:'Premio no med.', money:true, w:'130px'},
      {key:'premio_actual_total', label:'Premio', money:true, w:'120px'},
    ], rows);
    table('tabla-estudio-sector', [
      {key:'sector', label:'Sector', w:'250px'},
      {key:'activos', label:'Activos', num:true, w:'90px'},
      {key:'con_premio', label:'Cobran', num:true, w:'90px'},
      {key:'con_actividad', label:'Actividad', num:true, w:'95px'},
      {key:'actividad_sin_premio', label:'Act. sin premio', num:true, w:'130px'},
      {key:'premio_medible_total', label:'Premio med.', money:true, w:'130px'},
      {key:'premio_no_medible_total', label:'Premio no med.', money:true, w:'140px'},
      {key:'premio_total', label:'Premio', money:true, w:'130px'},
    ], sectorRows);
    table('tabla-estudio-operacion', [
      {key:'operacion', label:'Operacion', w:'230px', link:'estudio-operacion'},
      {key:'tipo_premio', label:'Tipo', w:'100px'},
      {key:'legajos', label:'Legajos', num:true, w:'90px'},
      {key:'productividad_total', label:'Produccion', num:true, w:'130px'},
      {key:'premio_total', label:'Premio', money:true, w:'130px'},
    ], operacionRows);
    table('tabla-estudio-fuera-rrhh', [
      {key:'legajo', label:'Legajo', mono:true, w:'90px'},
      {key:'estado_rrhh', label:'Estado RRHH', w:'130px'},
      {key:'nombre', label:'Nombre RRHH', w:'210px'},
      {key:'sector', label:'Sector RRHH', w:'190px'},
      {key:'funcion_rrhh', label:'Funcion RRHH', w:'190px'},
      {key:'fecha_baja', label:'Fecha baja', w:'110px', mono:true},
      {key:'tipo_cobro', label:'Tipo cobro', w:'110px'},
      {key:'operaciones_medibles_premio', label:'Op. medible', w:'200px'},
      {key:'operaciones_no_medibles_premio', label:'Op. no medible', w:'210px'},
      {key:'divisiones_premio', label:'Division premio', w:'170px'},
      {key:'jornadas_con_medicion', label:'Jornadas', num:true, w:'95px'},
      {key:'jornadas_con_premio', label:'Jorn. premio', num:true, w:'120px'},
      {key:'productividad_total', label:'Prod.', num:true, w:'120px'},
      {key:'premio_medible_total', label:'Premio med.', money:true, w:'130px'},
      {key:'premio_no_medible_total', label:'Premio no med.', money:true, w:'140px'},
      {key:'premio_actual_total', label:'Premio', money:true, w:'130px'},
    ], data.rows_fuera_rrhh || []);
    renderEstudioOperacionLegajos();
  }
  function refreshEstudioFilters(){
    const data = state.estudio || {};
    setEstudioChecklist('sector', data.sectores || []);
    $('estudio-f-estado').value = state.estudioFilters.estado || '';
    $('estudio-f-tipo').value = state.estudioFilters.tipo || '';
    $('estudio-f-texto').value = state.estudioFilters.texto || '';
  }
  function renderTablaPremios(){
    const data = state.tablaPremios;
    if (!data) return;
    const foto = data.foto || {};
    const changed = Number(foto.source_changed || 0) === 1;
    $('kpis-tabla-premios').innerHTML = [
      kpi('Foto', foto.snapshot_id || 'sin foto', `capturada ${foto.captured_at || '-'}`, changed ? 'warn' : 'ok'),
      kpi('Escalas jornada', fmt(foto.scale_rows || (data.escalas_jornada || []).length), 'filas almacenadas localmente'),
      kpi('Sectores', fmt(foto.sector_rows || (data.sectores || []).length), 'configurados en PV_TIEMPOS_DE_PICKING'),
    ].join('');
    $('tabla-premios-foto').innerHTML = `<div class="premio-source-note ${changed ? 'warn' : ''}">${changed ? 'Se detectaron cambios en Oracle. La foto local se conserva y no fue recalculada.' : 'La escala fue capturada como foto local. Mientras no se fuerce una nueva versiÃ³n, las tablas se leen desde SQLite.'} ${foto.archivo_local ? `Archivo: ${esc(foto.archivo_local)}` : ''}</div>`;
    const jornadaCols = [
      {key:'grupo_productivo',label:'Grupo',w:'180px'}, {key:'nivel',label:'Nivel',num:true,w:'70px'},
      {key:'desde',label:'Desde jornada',num:true}, {key:'hasta',label:'Hasta jornada',num:true},
      {key:'premio',label:'Premio jornada',money:true},
    ];
    const horaCols = [
      {key:'grupo_productivo',label:'Grupo',w:'180px'}, {key:'nivel',label:'Nivel',num:true,w:'70px'},
      {key:'desde_hora',label:'Desde /6.5',num:true}, {key:'hasta_hora',label:'Hasta /6.5',num:true},
      {key:'premio_hora',label:'Premio /6.5',money:true},
    ];
    table('tabla-premios-jornada', jornadaCols, data.escalas_jornada || []);
    table('tabla-premios-hora', horaCols, data.escalas_hora || []);
    const sectorCols = [
      {key:'nivel',label:'Nivel',num:true,w:'65px'}, {key:'desde_hora_sector',label:'Desde bultos',num:true},
      {key:'hasta_hora_sector',label:'Hasta bultos',num:true}, {key:'premio_hora',label:'Premio hora',money:true},
    ];
    $('tabla-premios-sectores').innerHTML = (data.sectores || []).map((sector, index) => {
      const id = `tabla-premio-sector-${index}`;
      const method = sector.metodo_de_calculo || 'SIN CONFIG';
      const note = method === 'ESPECIFICO' ? 'Escala propia del sector; intervienen posiciones/setup.' : 'Escala propia del sector.';
      return `<article class="premio-sector-card"><div class="chart-title"><strong>${esc(`D${sector.division} Â· Sector ${sector.sector}`)}</strong><span>${esc(`${sector.grupo_productivo || 'SIN GRUPO'} Â· ${method}`)}</span></div><div class="premio-source-note">${esc(note)}</div><div class="table-wrap"><table class="paper-table" id="${id}"></table></div></article>`;
    }).join('') || '<div class="premio-source-note warn">No hay sectores configurados.</div>';
    (data.sectores || []).forEach((sector, index) => table(`tabla-premio-sector-${index}`, sectorCols, sector.filas || []));
    const sectorRows=(data.sectores || []).flatMap(sector=>(sector.filas || []).map(row=>({...row,division:sector.division,sector:sector.sector,grupo_productivo:sector.grupo_productivo,metodo_de_calculo:sector.metodo_de_calculo})));
    table('tabla-premios-sector-consolidada',[
      {key:'division',label:'DivisiÃ³n',num:true},
      {key:'sector',label:'Sector',mono:true},
      {key:'grupo_productivo',label:'Grupo productivo'},
      {key:'metodo_de_calculo',label:'MÃ©todo'},
      {key:'nivel',label:'Nivel',num:true},
      {key:'desde_hora_sector',label:'Desde bultos',num:true},
      {key:'hasta_hora_sector',label:'Hasta bultos',num:true},
      {key:'premio_hora',label:'Premio por hora',money:true},
      {key:'equivalencia',label:'Equivalencia',num:true}
    ],sectorRows);
  }

  async function loadTablaPremios(){
    const key='static';
    if (state.tablaPremios && state.tabLoadKeys.tablaPremios===key){ renderTablaPremios(); return true; }
    if (state.tabPromises.tablaPremios) return state.tabPromises.tablaPremios;
    const generation=state.loadGeneration;
    const controller=new AbortController();
    state.tabAbortControllers.tablaPremios=controller;
    const promise=(async()=>{
      const data=await api('/api/analisis-premio-productividad/tabla-premios',{signal:controller.signal});
      if (generation!==state.loadGeneration) return false;
      state.tablaPremios=data; state.tabLoadKeys.tablaPremios=key; renderTablaPremios(); return true;
    })();
    state.tabPromises.tablaPremios=promise;
    try { return await promise; } finally { if (state.tabPromises.tablaPremios===promise) delete state.tabPromises.tablaPremios; if (state.tabAbortControllers.tablaPremios===controller) delete state.tabAbortControllers.tablaPremios; }
  }

  function renderEvaluacionPickingDetalleAgrupado(data){
    const selectedDay = state.evaluacionPickingDaySelected || '';
    const selectedKey = state.evaluacionPickingSelected || '';
    const selectedLegajo = selectedKey.includes('|') ? selectedKey.split('|').pop() : selectedKey;
    const rows = (data.rows || []).filter(item => !selectedDay || String(item.fecha_base || '').slice(0,10) === selectedDay).filter(item => !selectedLegajo || String(item.legajo || '') === String(selectedLegajo));
    const byHour = new Map();
    rows.forEach(row => {
      const key = `${row.fecha_base}|${row.legajo}|${row.hora}`;
      const item = byHour.get(key) || {...row, sectores_hora:0, bultos_hora:0, equivalencia_sector_hora:0, equivalencia_traslado_hora:0, equivalencia_consolidacion_hora:0, premio_hora_aplicado_total:0, niveles_set:new Set(), niveles_reales_set:new Set(), desde_set:new Set(), hasta_set:new Set(), factores_set:new Set()};
      item.sectores_hora += 1; item.bultos_hora += Number(row.bultos_reales || 0); item.equivalencia_sector_hora += Number(row.equivalencia_sector || 0); item.equivalencia_traslado_hora += Number(row.equivalencia_traslado || 0); item.equivalencia_consolidacion_hora += Number(row.equivalencia_consolidacion || 0); item.premio_hora_aplicado_total += Number(row.premio_aplicado || 0); if (row.nivel != null) item.niveles_set.add(String(row.nivel)); if (row.nivel_actual != null) item.niveles_reales_set.add(String(row.nivel_actual)); if (row.desde_bultos != null) item.desde_set.add(Number(row.desde_bultos)); if (row.hasta_bultos != null) item.hasta_set.add(Number(row.hasta_bultos)); item.factores_set.add(Number(row.factor_multiplicador || 1)); byHour.set(key, item);
    });
    const hours = [...byHour.values()].map(row => ({...row, bultos_hora:row.bultos_hora, nivel_escala:[...(row.niveles_set || [])].sort((a,b) => Number(a)-Number(b)).join(', ') || 'N/D', nivel_real:[...(row.niveles_reales_set || [])].sort((a,b) => Number(a)-Number(b)).join(', ') || 'N/D', desde_real:[...(row.desde_actual != null ? [row.desde_actual] : [])].map(Number)[0] ?? null, hasta_real:[...(row.hasta_actual != null ? [row.hasta_actual] : [])].map(Number)[0] ?? null, desde_escala:[...(row.desde_set || [])].sort((a,b) => a-b)[0] ?? 0, hasta_escala:[...(row.hasta_set || [])].sort((a,b) => b-a)[0] ?? 0, factor_multiplicador:[...(row.factores_set || [1])].sort((a,b) => a-b).map(value => `${value}x`).join(', '), premio_hora_aplicado_total:round2(row.premio_hora_aplicado_total)})).sort((a,b) => {
      const ah = (Number(a.hora) + 2) % 24;
      const bh = (Number(b.hora) + 2) % 24;
      return ah - bh || Number(a.hora) - Number(b.hora);
    });
    const equivalentesTotales = hours.reduce((sum, row) => sum + Number(row.equivalencia_sector_hora || 0) + Number(row.equivalencia_traslado_hora || 0) + Number(row.equivalencia_consolidacion_hora || 0), 0);
    const bultosRealesTotales = hours.reduce((sum, row) => sum + Number(row.bultos_hora || 0), 0);
    const excedenteTotal = Math.max(0, equivalentesTotales - bultosRealesTotales);
    const excedentePorHora = hours.length ? excedenteTotal / hours.length : 0;
    hours.forEach(row => { row.bultos_reales_hora = Number(row.bultos_hora || 0); row.excedente_distribuido = excedentePorHora; row.bultos_hora = row.bultos_reales_hora + excedentePorHora; });
    $('evaluacion-sector-hora-title').textContent = 'seleccionar una hora';
    $('tabla-evaluacion-detalle-sectores').innerHTML = '<tbody><tr><td>Selecciona una hora para ver sus sectores.</td></tr></tbody>';
    table('tabla-evaluacion-detalle', [
      {key:'fecha_base',label:'Fecha',mono:true}, {key:'legajo',label:'Legajo',mono:true}, {key:'hora',label:'Hora',num:true}, {key:'sectores_hora',label:'Sectores',num:true}, {key:'bultos_hora',label:'Bultos + equiv. distribuida',format:value => fmt(value)}, {key:'excedente_distribuido',label:'Excedente distribuido',format:value => fmt(value)}, {key:'nivel_real',label:'Nivel cobrado'}, {key:'desde_real',label:'Desde cobrado',num:true}, {key:'hasta_real',label:'Hasta cobrado',num:true}, {key:'nivel_escala',label:'Nivel nuevo'}, {key:'factor_multiplicador',label:'Factor'},
      {key:'premio_hora_aplicado_total',label:'MÃ©todo nuevo',money:true},
    ], hours);
    const selectedHourKey = state.evaluacionPickingHourSelected || '';
    const orderedHours = sortedRows('tabla-evaluacion-detalle', [{key:'fecha_base'},{key:'legajo'},{key:'hora',num:true},{key:'sectores_hora',num:true},{key:'bultos_hora',num:true},{key:'excedente_distribuido',num:true},{key:'nivel_real'},{key:'desde_real',num:true},{key:'hasta_real',num:true},{key:'nivel_escala'},{key:'factor_multiplicador'},{key:'premio_hora_aplicado_total',money:true}], hours);
    $('tabla-evaluacion-detalle').querySelectorAll('tbody tr').forEach((tr,index) => { const row = orderedHours[index]; tr.classList.toggle('active', `${row?.fecha_base}|${row?.legajo}|${row?.hora}` === selectedHourKey); });
    $('tabla-evaluacion-detalle').querySelectorAll('tbody tr').forEach((tr,index) => { tr.onclick = event => { event.stopPropagation(); const row = orderedHours[index]; if (!row) return; state.evaluacionPickingHourSelected = `${row.fecha_base}|${row.legajo}|${row.hora}`; $('tabla-evaluacion-detalle').querySelectorAll('tbody tr.active').forEach(item => item.classList.remove('active')); tr.classList.add('active'); const sectors = rows.filter(item => String(item.fecha_base) === String(row.fecha_base) && String(item.legajo) === String(row.legajo) && Number(item.hora) === Number(row.hora)); $('evaluacion-sector-hora-title').textContent = `hora ${row.hora} Â· ${row.fecha_base} Â· legajo ${row.legajo}`; table('tabla-evaluacion-detalle-sectores', [{key:'sector',label:'Sector'},{key:'funciones',label:'Funciones'},{key:'segundos_sector',label:'Minutos',num:true,format:value => fmt(Number(value || 0) / 60)},{key:'bultos_reales',label:'Bultos',num:true},{key:'premio_aplicado',label:'MÃ©todo nuevo',money:true},{key:'premio_real_asignado',label:'Pago real asignado',money:true},{key:'diferencia',label:'Diferencia',format:value => value == null ? 'N/D' : signedMoney2(value)},{key:'nivel',label:'Nivel',num:true}], sectors); }; });
    $('tabla-evaluacion-detalle').onclick = event => { const tr = event.target.closest('tbody tr'); if (!tr) return; const index = Array.from(tr.parentElement.children).indexOf(tr); const row = orderedHours[index]; if (row) { state.evaluacionPickingHourSelected = `${row.fecha_base}|${row.legajo}|${row.hora}`; $('tabla-evaluacion-detalle').querySelectorAll('tbody tr.active').forEach(item => item.classList.remove('active')); tr.classList.add('active'); const sectors = rows.filter(item => String(item.fecha_base) === String(row.fecha_base) && String(item.legajo) === String(row.legajo) && Number(item.hora) === Number(row.hora)); $('evaluacion-sector-hora-title').textContent = `hora ${row.hora} Â· ${row.fecha_base} Â· legajo ${row.legajo}`; table('tabla-evaluacion-detalle-sectores', [{key:'sector',label:'Sector'},{key:'funciones',label:'Funciones'},{key:'segundos_sector',label:'Minutos',num:true,format:value => fmt(Number(value || 0) / 60)},{key:'bultos_reales',label:'Bultos',num:true},{key:'premio_aplicado',label:'MÃ©todo nuevo',money:true},{key:'premio_real_asignado',label:'Pago real asignado',money:true},{key:'diferencia',label:'Diferencia',format:value => value == null ? 'N/D' : signedMoney2(value)},{key:'nivel',label:'Nivel',num:true}], sectors); } };
    const umbrales = hours.map(row => Number(row.desde_real || 0) / 8).filter(value => Number.isFinite(value) && value > 0);
    const umbralCompensacion = umbrales.length ? Math.min(...umbrales) : 0;
    renderDetalleLegajoChart(hours.map(row => {
      const bultos = Number(row.bultos_reales_hora || 0);
      return {hora:row.hora, bultos, equivalencia_extra:Number(row.excedente_distribuido || 0), bultos_hora_min:umbralCompensacion, bultos_hora_max:0, escala_actual_desde:row.desde_real == null ? null : Number(row.desde_real) / 8, escala_actual_hasta:row.hasta_real == null ? null : Number(row.hasta_real) / 8, escala_actual_nivel:row.nivel_real, premio_x_hora:row.premio_hora_aplicado_total, bultos_modulo:0, prod_modulo:umbralCompensacion * 8, es_hora_estandar:umbralCompensacion <= 0 || (bultos + Number(row.excedente_distribuido || 0)) <= umbralCompensacion, modo_compensacion:true};
    }), false, null, 'evaluacion-detalle-chart');
    $('evaluacion-detalle-chart').querySelectorAll('.prod-bar').forEach((bar,index) => { bar.style.cursor = 'pointer'; bar.onclick = () => { const row = hours[index]; if (!row) return; state.evaluacionPickingHourSelected = `${row.fecha_base}|${row.legajo}|${row.hora}`; $('tabla-evaluacion-detalle').querySelectorAll('tbody tr.active').forEach(item => item.classList.remove('active')); const tableRows = [...$('tabla-evaluacion-detalle').querySelectorAll('tbody tr')]; const selectedTr = tableRows.find((tr, i) => orderedHours[i] && `${orderedHours[i].fecha_base}|${orderedHours[i].legajo}|${orderedHours[i].hora}` === state.evaluacionPickingHourSelected); selectedTr?.classList.add('active'); const sectors = rows.filter(item => String(item.fecha_base) === String(row.fecha_base) && String(item.legajo) === String(row.legajo) && Number(item.hora) === Number(row.hora)); $('evaluacion-sector-hora-title').textContent = `hora ${row.hora} Â· ${row.fecha_base} Â· legajo ${row.legajo}`; table('tabla-evaluacion-detalle-sectores', [{key:'sector',label:'Sector'},{key:'funciones',label:'Funciones'},{key:'segundos_sector',label:'Minutos',num:true,format:value => fmt(Number(value || 0) / 60)},{key:'bultos_reales',label:'Bultos',num:true},{key:'premio_aplicado',label:'MÃ©todo nuevo',money:true},{key:'premio_real_asignado',label:'Pago real asignado',money:true},{key:'diferencia',label:'Diferencia',format:value => value == null ? 'N/D' : signedMoney2(value)},{key:'nivel',label:'Nivel',num:true}], sectors); }; });
  }

  function renderEvaluacionPickingDetalle(data){
    const selectedDay = state.evaluacionPickingDaySelected || '';
    const selectedKey = state.evaluacionPickingSelected || '';
    const parts = selectedKey.split('|');
    const selectedLegajo = parts.length === 2 ? parts[1] : '';
    let detail = data.rows || [];
    if (selectedDay) detail = detail.filter(item => String(item.fecha_base || '').slice(0,10) === selectedDay);
    if (selectedLegajo) detail = detail.filter(item => String(item.legajo || '') === String(selectedLegajo));
    $('evaluacion-detalle-title').textContent = selectedLegajo
      ? `legajo ${selectedLegajo} Â· ${selectedDay}`
      : selectedDay ? `todos los legajos Â· ${selectedDay}` : 'seleccionar un dÃ­a';
    if (!selectedDay) {
      $('tabla-evaluacion-detalle').innerHTML = '<tbody><tr><td>Selecciona un registro de EvaluaciÃ³n de actividad Picking.</td></tr></tbody>';
      return;
    }
    const pagoReal = (value) => value === null || value === undefined ? 'N/D' : money(value);
    const detailCols = [
      {key:'fecha_base',label:'Fecha',mono:true}, {key:'legajo',label:'Legajo',mono:true}, {key:'hora',label:'Hora',num:true}, {key:'sector',label:'Sector'}, {key:'funciones',label:'Funciones'},
      {key:'segundos_sector',label:'Minutos',num:true,format:value => fmt(Number(value || 0) / 60)},
      {key:'peso_sector',label:'Peso',num:true,format:value => `${fmt(Number(value || 0) * 100)} %`},
      {key:'bultos_reales',label:'Bultos reales',num:true}, {key:'ritmo_bultos_hora',label:'Ritmo hora',num:true},
      {key:'nivel',label:'Nivel',num:true}, {key:'desde_bultos',label:'Desde',num:true}, {key:'hasta_bultos',label:'Hasta',num:true},
      {key:'premio_hora',label:'Premio hora',money:true}, {key:'premio_aplicado',label:'MÃ©todo nuevo',money:true}, {key:'premio_real_asignado',label:'Pago real',format:pagoReal},
      {key:'diferencia',label:'Diferencia',format:value => value === null || value === undefined ? 'N/D' : signedMoney2(value)}, {key:'estado',label:'Estado'},
    ];
    table('tabla-evaluacion-detalle', detailCols, detail);
    bindEvaluacionHeaders('tabla-evaluacion-detalle', detailCols, detail);
  }

  function bindEvaluacionHeaders(id, cols, rows){
    const target = $(id);
    if (!target) return;
    target.querySelectorAll('th.sortable').forEach(th => {
      th.onclick = event => {
        event.stopPropagation();
        const key = th.dataset.key;
        const current = state.sorts[id];
        state.sorts[id] = current?.key === key && current.dir === 'asc' ? {key, dir:'desc'} : {key, dir:'asc'};
        table(id, cols, rows);
        bindEvaluacionHeaders(id, cols, rows);
      };
    });
  }

  function renderEvaluacionPicking(){
    const originalData = state.evaluacionPicking;
    if (!originalData) return;
    const filtroLegajo = String(state.evaluacionPickingLegajoFilter || '').trim().toLowerCase();
    const legajoMatch = row => !filtroLegajo || String(row?.legajo || '').toLowerCase().includes(filtroLegajo);
    const filteredLegajoRows = (originalData.resumen_legajos || []).filter(legajoMatch);
    const filteredRows = (originalData.rows || []).filter(legajoMatch);
    const dayMap = new Map();
    filteredLegajoRows.forEach(row => {
      const fecha = String(row.fecha || '').slice(0,10);
      if (!fecha) return;
      const item = dayMap.get(fecha) || {fecha, legajos_set:new Set(), premio_real:0, premio:0};
      item.legajos_set.add(String(row.legajo || ''));
      item.premio_real += Number(row.premio_real || 0);
      item.premio += Number(row.premio || 0);
      dayMap.set(fecha, item);
    });
    const filteredDays = [...dayMap.values()].map(row => ({...row, legajos:row.legajos_set.size, legajos_set:undefined}));
    const data = {...originalData, rows:filteredRows, resumen_legajos:filteredLegajoRows, resumen_dias:filtroLegajo ? filteredDays : (originalData.resumen_dias || [])};
    if (state.evaluacionPickingSelected && !data.resumen_legajos.some(row => String(row.legajo) === String(state.evaluacionPickingSelected))) state.evaluacionPickingSelected = '';
    if (!data) return;
    const k = data.kpis || {};
    const meta = data.meta || {};
    const selectedDay = state.evaluacionPickingDaySelected || '';
    const pagosDisponibles = Number(meta.legajos_pago_real_disponible || 0) > 0;
    const pagoRealLabel = pagosDisponibles ? money(k.premio_real) : 'N/D';
    const pagoRealFoot = pagosDisponibles ? `cache local Â· ${fmt(meta.legajos_pago_real_disponible)} legajos` : 'Sin pagos reales cargados en cache local';
    const bultosRealesTotal = filteredRows.reduce((sum, row) => sum + Number(row.bultos_reales || 0), 0);
    const equivalentesTotal = filteredRows.reduce((sum, row) => sum + Number(row.equivalencia_sector || 0) + Number(row.equivalencia_traslado || 0) + Number(row.equivalencia_consolidacion || 0), 0);
    const diasConMultiplicador = new Set(filteredLegajoRows.filter(row => Number(row.factor_multiplicador || 1) > 1).map(row => String(row.fecha || '').slice(0,10))).size;
    $('kpis-evaluacion-picking').innerHTML = [
      kpi('Legajos distintos', fmt(k.legajos), 'personas Ãºnicas en el rango'),
      kpi('Pago real', pagoRealLabel, pagoRealFoot, pagosDisponibles ? '' : 'warn'),
      kpi('Pago final bultos', money(k.pago_final_bultos), 'individual + bolsa grupal por bultos', 'ok'),
      kpi('Pago final horas', money(k.pago_final_horas), 'individual + bolsa grupal por horas', 'ok'),
      kpi('Bolsa grupal', money(k.bolsa_grupal || meta.bolsa_grupal || 0), 'adicional a distribuir', 'warn'),
      kpi('MÃ©todo nuevo', money(k.premio_nuevo), 'escala sectorial por hora', 'ok'),
      kpi('Brecha', signedMoney2(Number(k.premio_nuevo || 0) - Number(k.premio_real || 0)), 'mÃ©todo nuevo menos pago actual', Number(k.premio_nuevo || 0) >= Number(k.premio_real || 0) ? 'ok' : 'bad'),
      kpi('Nuevo / actual', Number(k.premio_real || 0) > 0 ? `${fmt(Number(k.premio_nuevo || 0) * 100 / Number(k.premio_real || 0))} %` : 'N/D', 'incluye multiplicadores detectados', Number(k.premio_real || 0) > 0 && Number(k.premio_nuevo || 0) >= Number(k.premio_real || 0) ? 'ok' : 'warn'),
    ].join('');
    $('evaluacion-picking-meta').textContent = `${meta.fecha_desde || ''} a ${meta.fecha_hasta || ''} Â· ${fmt(meta.dias_cache || 0)} dÃ­as cache Â· ${fmt(meta.dias_oracle || 0)} dÃ­as actividad Â· ${fmt(meta.dias_pago_oracle || 0)} dÃ­as pago real`;
    $('kpis-evaluacion-picking-equivalencias').innerHTML = [
      kpi('Bultos reales', fmt(bultosRealesTotal), 'producciÃ³n fÃ­sica del rango'),
      kpi('Bultos equivalentes', fmt(equivalentesTotal), 'base por la que se pagÃ³ el mÃ©todo actual', 'warn'),
      kpi('Equivalencias / conversiones', fmt(Math.max(0, equivalentesTotal - bultosRealesTotal)), 'diferencia entre real y equivalente'),
      kpi('% incluido de mÃ¡s', bultosRealesTotal > 0 ? `${fmt((equivalentesTotal - bultosRealesTotal) * 100 / bultosRealesTotal)} %` : 'N/D', 'equivalencias sobre bultos reales', 'warn'),
      kpi('DÃ­as con multiplicador', fmt(diasConMultiplicador), 'premios con factor adicional', diasConMultiplicador ? 'warn' : 'ok'),
    ].join('');
    const filtroInput = $('evaluacion-f-legajo');
    if (filtroInput && filtroInput.value !== String(state.evaluacionPickingLegajoFilter || '')) filtroInput.value = String(state.evaluacionPickingLegajoFilter || '');
    $('evaluacion-clear-filtro-legajo')?.classList.toggle('hidden', !filtroLegajo);
    const pagoReal = (value) => value === null || value === undefined ? 'N/D' : money(value);
    const difference = (value, row) => row.premio_real === null || row.premio_real === undefined ? 'N/D' : signedMoney2(Number(row.premio || 0) - Number(row.premio_real || 0));
    const factorsByDay = new Map();
    (data.resumen_legajos || []).forEach(row => {
      const day = String(row.fecha || '').slice(0,10);
      if (!day) return;
      const factors = factorsByDay.get(day) || new Set();
      factors.add(Number(row.factor_multiplicador || 1));
      factorsByDay.set(day, factors);
    });
    const days = (data.resumen_dias || []).map(row => {
      const actual = Number(row.premio_real || 0);
      const nuevo = Number(row.premio || 0);
      const factors = [...(factorsByDay.get(String(row.fecha || '').slice(0,10)) || new Set([1]))].sort((a,b) => a-b);
      return {...row, diferencia: row.premio_real === null || row.premio_real === undefined ? null : nuevo - actual, diferencia_final_bultos: row.premio_real === null || row.premio_real === undefined ? null : Number(row.pago_final_bultos || 0) - actual, diferencia_final_horas: row.premio_real === null || row.premio_real === undefined ? null : Number(row.pago_final_horas || 0) - actual, porcentaje_nuevo: actual > 0 ? nuevo * 100 / actual : null, factor_multiplicador: factors.length === 1 ? factors[0] : null, factor_label: factors.length === 1 ? `${factors[0]}x` : 'Mixto'};
    });
    const maxPagoDia = Math.max(1, ...days.map(row => Number(row.premio_real || 0)));
    $('evaluacion-resumen-visual').innerHTML = `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;font-family:'IBM Plex Mono',monospace;font-size:11px"><div style="border-left:3px solid var(--blue);background:#F8FAF7;padding:9px">Pago actual<strong style="display:block;font-size:18px;margin-top:4px">${esc(money(k.premio_real))}</strong></div><div style="border-left:3px solid var(--green);background:#F8FAF7;padding:9px">MÃ©todo nuevo<strong style="display:block;font-size:18px;margin-top:4px">${esc(money(k.premio_nuevo))}</strong></div><div style="border-left:3px solid var(--amber);background:#F8FAF7;padding:9px">Nuevo / actual<strong style="display:block;font-size:18px;margin-top:4px">${Number(k.premio_real || 0) > 0 ? `${fmt(Number(k.premio_nuevo || 0) * 100 / Number(k.premio_real || 0))} %` : 'N/D'}</strong></div></div>`;
    $('evaluacion-diario-visual').innerHTML = `<div style="margin-top:12px;font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--ink-soft);letter-spacing:.08em;text-transform:uppercase">ComparaciÃ³n diaria Â· azul actual Â· verde nuevo</div>${days.map(row => { const actual = Number(row.premio_real || 0); const nuevo = Number(row.premio || 0); const widthActual = actual * 100 / maxPagoDia; const widthNuevo = nuevo * 100 / maxPagoDia; const alert = row.factor_multiplicador && row.factor_multiplicador > 1 ? 'border:1px solid var(--amber);' : ''; return `<div style="display:grid;grid-template-columns:82px 1fr 170px;gap:8px;align-items:center;margin-top:6px;font-family:'IBM Plex Mono',monospace;font-size:10px;${alert}"><span>${esc(row.fecha)}</span><span style="height:16px;background:#EEF2EE;display:block;position:relative"><i style="display:block;position:absolute;left:0;top:0;height:7px;width:${widthActual}%;background:var(--blue)"></i><i style="display:block;position:absolute;left:0;bottom:0;height:7px;width:${widthNuevo}%;background:var(--green)"></i></span><span style="white-space:nowrap;color:var(--ink-soft)">${esc(row.factor_label)} Â· ${row.porcentaje_nuevo == null ? 'N/D' : `${fmt(row.porcentaje_nuevo)} %`}</span></div>`; }).join('')}`;
    /* tabla renderizada una sola vez con la definiciÃ³n final de columnas */
    if (false) table('tabla-evaluacion-dias', [
      {key:'fecha',label:'Fecha',mono:true}, {key:'legajos',label:'Legajos',num:true},
      {key:'premio_real',label:'Pago real',format:pagoReal}, {key:'premio',label:'MÃ©todo nuevo individual',money:true}, {key:'pago_final_bultos',label:'Pago final + grupal bultos',money:true}, {key:'diferencia_final_bultos',label:'Diferencia final bultos',format:difference}, {key:'pago_final_horas',label:'Pago final + grupal horas',money:true}, {key:'diferencia_final_horas',label:'Diferencia final horas',format:difference}, {key:'adicional_grupal_bultos',label:'Adic. grupal bultos',money:true}, {key:'adicional_grupal_horas',label:'Adic. grupal horas',money:true},
      {key:'diferencia',label:'Diferencia individual',format:difference}, {key:'diferencia_final_bultos',label:'Diferencia final bultos',format:difference}, {key:'diferencia_final_horas',label:'Diferencia final horas',format:difference}, {key:'factor_label',label:'Factor'}, {key:'porcentaje_nuevo',label:'Nuevo / actual',format:value => value == null ? 'N/D' : `${fmt(value)} %`},
    ], data.resumen_dias || []);
    bindEvaluacionHeaders('tabla-evaluacion-dias', [{key:'fecha',label:'Fecha'}, {key:'legajos',label:'Legajos',num:true}, {key:'premio_real',label:'Pago real',money:true}, {key:'premio',label:'MÃ©todo nuevo',money:true}, {key:'diferencia',label:'Diferencia'}, {key:'factor_label',label:'Factor'}, {key:'porcentaje_nuevo',label:'Nuevo / actual',num:true}], days);
    table('tabla-evaluacion-dias', [
      {key:'fecha',label:'Fecha',mono:true}, {key:'legajos',label:'Legajos',num:true},
      {key:'premio_real',label:'Pago real',format:pagoReal}, {key:'premio',label:'MÃƒÂ©todo nuevo individual',money:true}, {key:'adicional_grupal_bultos',label:'Adic. grupal bultos',money:true}, {key:'pago_final_bultos',label:'Pago final bultos',money:true}, {key:'adicional_grupal_horas',label:'Adic. grupal horas',money:true}, {key:'pago_final_horas',label:'Pago final horas',money:true},
      {key:'diferencia',label:'Diferencia',format:difference}, {key:'factor_label',label:'Factor'}, {key:'porcentaje_nuevo',label:'Nuevo / actual',format:value => value == null ? 'N/D' : `${fmt(value)} %`},
    ], days);
    const diasCols = [
      {key:'fecha',label:'Fecha',mono:true}, {key:'legajos',label:'Legajos',num:true},
      {key:'premio_real',label:'Pago real',format:pagoReal}, {key:'premio',label:'Metodo nuevo individual',money:true},
      {key:'adicional_grupal_bultos',label:'Adic. grupal bultos',money:true}, {key:'pago_final_bultos',label:'Pago final bultos',money:true},
      {key:'adicional_grupal_horas',label:'Adic. grupal horas',money:true}, {key:'pago_final_horas',label:'Pago final horas',money:true},
      {key:'diferencia',label:'Diferencia',format:difference}, {key:'factor_label',label:'Factor'},
      {key:'porcentaje_nuevo',label:'Nuevo / actual',format:value => value == null ? 'N/D' : `${fmt(value)} %`},
    ];
    bindEvaluacionHeaders('tabla-evaluacion-dias', diasCols, days);
    $('tabla-evaluacion-dias').querySelectorAll('tbody tr').forEach((tr, index) => {
      tr.onclick = event => { event.stopPropagation(); const row = sortedRows('tabla-evaluacion-dias', diasCols, days)[index]; state.evaluacionPickingDaySelected = row?.fecha || ''; state.evaluacionPickingSelected = ''; renderEvaluacionPicking(); };
    });
    $('tabla-evaluacion-dias').onclick = event => {
      const tr = event.target.closest('tbody tr');
      if (!tr) return;
      const index = Array.from(tr.parentElement.children).indexOf(tr);
       const row = sortedRows('tabla-evaluacion-dias', diasCols, days)[index];
      if (row) { state.evaluacionPickingDaySelected = row.fecha; state.evaluacionPickingSelected = ''; renderEvaluacionPicking(); }
    };
    $('evaluacion-clear-dia').onclick = () => { state.evaluacionPickingDaySelected = ''; state.evaluacionPickingSelected = ''; renderEvaluacionPicking(); };
    $('evaluacion-clear-dia').classList.toggle('hidden', !selectedDay);
    const legajoCols = [
      {key:'legajo',label:'Legajo',mono:true}, {key:'fechas',label:'DÃ­as',num:true}, {key:'bultos_reales',label:'Bultos reales',num:true}, {key:'bultos_equivalentes',label:'Bultos equivalentes',num:true}, {key:'porcentaje_equivalencias',label:'% equiv. de mÃ¡s',format:value => value == null ? 'N/D' : `${fmt(value)} %`},
      {key:'premio_real',label:'Pago real',format:pagoReal}, {key:'premio',label:'MÃ©todo nuevo',money:true},
      {key:'adicional_grupal_bultos',label:'Grupal bultos',money:true}, {key:'pago_final_bultos',label:'Final bultos',money:true}, {key:'diferencia_final_bultos',label:'Dif. bultos vs actual',format:signedMoney2},
      {key:'adicional_grupal_horas',label:'Grupal horas',money:true}, {key:'pago_final_horas',label:'Final horas',money:true}, {key:'diferencia_final_horas',label:'Dif. horas vs actual',format:signedMoney2},
    ];
    const allLegajos = (data.resumen_legajos || []).map(row => ({...row, diferencia: row.premio_real === null || row.premio_real === undefined ? null : Number(row.premio || 0) - Number(row.premio_real || 0)}));
    const legajoMap = new Map();
    allLegajos.forEach(row => { const item = legajoMap.get(String(row.legajo)) || {legajo:row.legajo, premio_real:0, premio:0, adicional_grupal_bultos:0, adicional_grupal_horas:0, pago_final_bultos:0, pago_final_horas:0, bultos_actuales:0, bultos_reales:0, bultos_equivalentes:0, fechas:0, diferencia:0}; item.premio_real += Number(row.premio_real || 0); item.premio += Number(row.premio || 0); item.adicional_grupal_bultos += Number(row.adicional_grupal_bultos_dia ?? row.adicional_grupal_bultos ?? 0); item.adicional_grupal_horas += Number(row.adicional_grupal_horas_dia ?? row.adicional_grupal_horas ?? 0); item.pago_final_bultos += Number(row.pago_final_bultos_dia ?? row.pago_final_bultos ?? 0); item.pago_final_horas += Number(row.pago_final_horas_dia ?? row.pago_final_horas ?? 0); item.bultos_actuales += Number(row.bultos_actuales || 0); item.bultos_reales += Number(row.bultos_reales || 0); item.bultos_equivalentes += Number(row.total_equivalentes || row.bultos_actuales || 0); item.fechas += 1; item.diferencia = item.premio - item.premio_real; legajoMap.set(String(row.legajo), item); });
    const mainLegajos = [...legajoMap.values()].map(row => ({...row, premio_real:round2(row.premio_real), premio:round2(row.premio), adicional_grupal_bultos:round2(row.adicional_grupal_bultos), adicional_grupal_horas:round2(row.adicional_grupal_horas), pago_final_bultos:round2(row.pago_final_bultos), pago_final_horas:round2(row.pago_final_horas), bultos_actuales:round2(row.bultos_actuales), bultos_reales:round2(row.bultos_reales), bultos_equivalentes:round2(row.bultos_equivalentes), porcentaje_equivalencias:row.bultos_reales > 0 ? round2((row.bultos_equivalentes - row.bultos_reales) * 100 / row.bultos_reales) : null, diferencia:round2(row.diferencia), diferencia_final_bultos:round2(row.pago_final_bultos - row.premio_real), diferencia_final_horas:round2(row.pago_final_horas - row.premio_real)}));
    const legajos = mainLegajos;
    const legajoPanel = $('tabla-evaluacion-legajos').closest('.data-panel');
    if (legajoPanel) legajoPanel.querySelector('.chart-title strong').textContent = 'Legajos';
    $('evaluacion-legajos-count').textContent = selectedDay ? `${fmt(legajos.length)} del ${selectedDay}` : `${fmt(legajos.length)} legajos`;
    $('evaluacion-clear-legajo').classList.toggle('hidden', !state.evaluacionPickingSelected);
    $('evaluacion-clear-legajo').onclick = () => { state.evaluacionPickingSelected = ''; renderEvaluacionPicking(); };
    if (!state.evaluacionPickingSelected && !selectedDay) {
      $('evaluacion-detalle-title').textContent = 'seleccionar un legajo';
      $('tabla-evaluacion-detalle').innerHTML = '<tbody><tr><td>Selecciona un legajo para ver el detalle horario.</td></tr></tbody>';
    }
    legajoCols.push({key:'diferencia',label:'Diferencia',format:difference});
    table('tabla-evaluacion-legajos', legajoCols, legajos);
    const selectedLegajo = state.evaluacionPickingSelected || '';
    const pagoActualRows = selectedLegajo ? allLegajos.filter(row => String(row.legajo) === String(selectedLegajo)) : [];
    const pagoComparacionRows = pagoActualRows.map(row => { const totalEquivalentes = Number(row.total_equivalentes || 0) || Number(row.bultos_actuales || 0); const finalBultos=Number(row.pago_final_bultos_dia || 0); const finalHoras=Number(row.pago_final_horas_dia || 0); return {...row, bultos_actuales:Number(row.bultos_actuales || 0), equivalencia_sector:Number(row.equivalencia_sector || 0), equivalencia_traslado:Number(row.equivalencia_traslado || 0), equivalencia_consolidacion:Number(row.equivalencia_consolidacion || 0), total_equivalentes:totalEquivalentes, adicionales_equivalentes:totalEquivalentes - Number(row.bultos_actuales || 0), excedente_escala:Number(row.desde_actual || 0) > 0 ? totalEquivalentes - Number(row.desde_actual || 0) : null, bultos_nuevo:Number(row.bultos_reales || 0), premio_nuevo:Number(row.premio || 0), adicional_grupal_bultos:Number(row.adicional_grupal_bultos_dia || 0), adicional_grupal_horas:Number(row.adicional_grupal_horas_dia || 0), pago_final_bultos:finalBultos, pago_final_horas:finalHoras, diferencia_final_bultos:finalBultos-Number(row.premio_real || 0), diferencia_final_horas:finalHoras-Number(row.premio_real || 0), diferencia_pago:Number(row.premio || 0) - Number(row.premio_real || 0)}; });
    const pagoPanel = $('tabla-evaluacion-pago-actual').closest('.data-panel');
    if (pagoPanel) pagoPanel.querySelector('.chart-title strong').textContent = 'ComparaciÃ³n de Pagos';
    $('evaluacion-pago-actual-title').textContent = selectedLegajo ? `legajo ${selectedLegajo}` : 'seleccionar un legajo';
    table('tabla-evaluacion-pago-actual', [
      {key:'fecha',label:'Fecha',mono:true}, {key:'bultos_actuales',label:'Bultos actuales',format:value => fmt(value)}, {key:'nivel_actual',label:'Nivel actual',num:true}, {key:'premio_real',label:'Pago actual',money:true}, {key:'bultos_nuevo',label:'Bultos nuevo',format:value => fmt(value)}, {key:'premio_nuevo',label:'MÃ©todo nuevo',money:true}, {key:'diferencia_pago',label:'Diferencia',format:value => signedMoney2(value)},
    ], pagoComparacionRows);
    const pagoComparacionCols = [{key:'fecha',label:'Fecha',mono:true},{key:'bultos_actuales',label:'Bultos reales',format:value=>fmt(value)},{key:'equivalencia_sector',label:'Equiv. sector',format:value=>fmt(value)},{key:'equivalencia_traslado',label:'Equiv. traslado',format:value=>fmt(value)},{key:'equivalencia_consolidacion',label:'Equiv. consolidaciÃ³n',format:value=>fmt(value)},{key:'total_equivalentes',label:'Total liquidado',format:value=>fmt(value)},{key:'nivel_actual',label:'Nivel actual',num:true},{key:'excedente_escala',label:'Excedente escala',format:value=>value==null?'N/D':fmt(value)},{key:'factor_multiplicador',label:'Factor'},{key:'premio_real',label:'Pago actual',money:true},{key:'bultos_nuevo',label:'Bultos nuevo',format:value=>fmt(value)},{key:'premio_nuevo',label:'MÃ©todo nuevo',money:true},{key:'diferencia_pago',label:'Diferencia',format:value=>signedMoney2(value)}];
    pagoComparacionCols.splice(pagoComparacionCols.length - 1, 0,
      {key:'adicional_grupal_bultos',label:'Adic. grupal bultos',money:true}, {key:'pago_final_bultos',label:'Pago final bultos',money:true},
      {key:'diferencia_final_bultos',label:'Dif. final bultos',format:value=>signedMoney2(value)}, {key:'adicional_grupal_horas',label:'Adic. grupal horas',money:true}, {key:'pago_final_horas',label:'Pago final horas',money:true}, {key:'diferencia_final_horas',label:'Dif. final horas',format:value=>signedMoney2(value)}
    );
    table('tabla-evaluacion-pago-actual', pagoComparacionCols, pagoComparacionRows);
    const pagoComparacionSorted = sortedRows('tabla-evaluacion-pago-actual', pagoComparacionCols, pagoComparacionRows);
    $('tabla-evaluacion-pago-actual').querySelectorAll('tbody tr').forEach((tr,index) => { const row = pagoComparacionSorted[index]; tr.classList.toggle('active', String(row?.fecha || '') === String(state.evaluacionPickingDaySelected || '')); tr.onclick = event => { event.stopPropagation(); state.evaluacionPickingDaySelected = row?.fecha || ''; state.evaluacionPickingHourSelected = ''; renderEvaluacionPicking(); }; });
    $('tabla-evaluacion-pago-actual').onclick = event => { const tr = event.target.closest('tbody tr'); if (!tr) return; const index = Array.from(tr.parentElement.children).indexOf(tr); const row = sortedRows('tabla-evaluacion-pago-actual', pagoComparacionCols, pagoComparacionRows)[index]; if (row) { state.evaluacionPickingDaySelected = row.fecha; renderEvaluacionPicking(); } };
    bindEvaluacionHeaders('tabla-evaluacion-legajos', legajoCols, legajos);
    $('tabla-evaluacion-legajos').querySelectorAll('tbody tr').forEach((tr, index) => {
      const currentRows = sortedRows('tabla-evaluacion-legajos', legajoCols, legajos);
      tr.classList.toggle('active', String(currentRows[index]?.legajo || '') === String(state.evaluacionPickingSelected || ''));
      tr.onclick = event => {
        event.stopPropagation();
        const rows = sortedRows('tabla-evaluacion-legajos', legajoCols, legajos);
        const row = rows[index];
        state.evaluacionPickingSelected = String(row.legajo);
        state.evaluacionPickingDaySelected = '';
        $('evaluacion-detalle-title').textContent = `legajo ${row.legajo} Â· ${row.fecha}`;
        const detail = (data.rows || []).filter(item => String(item.fecha_base || '').slice(0,10) === row.fecha && String(item.legajo || '') === String(row.legajo || ''));
        table('tabla-evaluacion-detalle', [
          {key:'hora',label:'Hora',num:true}, {key:'sector',label:'Sector'}, {key:'funciones',label:'Funciones'},
          {key:'segundos_sector',label:'Minutos',num:true,format:value => fmt(Number(value || 0) / 60)},
          {key:'peso_sector',label:'Peso',num:true,format:value => `${fmt(Number(value || 0) * 100)} %`},
          {key:'bultos_reales',label:'Bultos reales',num:true}, {key:'ritmo_bultos_hora',label:'Ritmo hora',num:true},
          {key:'nivel',label:'Nivel',num:true}, {key:'desde_bultos',label:'Desde',num:true}, {key:'hasta_bultos',label:'Hasta',num:true},
          {key:'premio_hora',label:'Premio hora',money:true}, {key:'premio_aplicado',label:'MÃƒÂ©todo nuevo',money:true}, {key:'premio_real_asignado',label:'Pago real',format:pagoReal}, {key:'diferencia',label:'Diferencia',format:(value) => value === null || value === undefined ? 'N/D' : signedMoney2(value)}, {key:'estado',label:'Estado'},
        ], detail);
        renderEvaluacionPicking();
      };
    });
    $('tabla-evaluacion-legajos').onclick = event => {
      const tr = event.target.closest('tbody tr');
      if (!tr) return;
      const index = Array.from(tr.parentElement.children).indexOf(tr);
      const row = sortedRows('tabla-evaluacion-legajos', legajoCols, legajos)[index];
      if (row) { state.evaluacionPickingSelected = String(row.legajo); state.evaluacionPickingDaySelected = ''; renderEvaluacionPicking(); }
    };
    renderEvaluacionPickingDetalleAgrupado(data);
    if ($('tabla-evaluacion-sectores')) table('tabla-evaluacion-sectores', [
      {key:'division',label:'DivisiÃ³n',num:true}, {key:'sector',label:'Sector'}, {key:'legajos',label:'Legajos',num:true},
      {key:'horas',label:'Horas',num:true}, {key:'bultos_reales',label:'Bultos reales',num:true}, {key:'premio',label:'Premio',money:true},
    ], data.resumen_sectores || []);
  }

  async function loadEvaluacionPicking(){
    if (state.evaluacionPickingLoading) return false;
    const ownBusy = !state.loading;
    if (ownBusy) setBusy(true);
    state.evaluacionPickingLoading = true;
    try {
      state.fechaDesde = $('rango-desde').value;
      state.fechaHasta = $('rango-hasta').value;
      if (!state.fechaDesde || !state.fechaHasta) throw new Error('Indica fecha desde y fecha hasta.');
      setStatus('Consultando EvaluaciÃƒÂ³n Picking...');
      state.evaluacionPicking = await api('/api/analisis-premio-productividad/punto0/evaluacion?' + qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta}));
      renderEvaluacionPicking();
      return true;
    } finally {
      state.evaluacionPickingLoading = false;
      if (ownBusy) setBusy(false);
    }
  }

  function renderCalculoPagoGrupal(){
    const data = state.calculoPagoGrupal;
    if (!data) return;
    const groupScenarioInput=$('escenario-bolsa-grupal-grupo');
    if (groupScenarioInput) groupScenarioInput.value=Number(state.escenarioBolsaGrupal||0);
    bindScenarioInput('escenario-bolsa-grupal-grupo','escenarioBolsaGrupal');
    const sectores = data.sectores || [];
    renderAusenciaConfig(data);
    const selected = state.calculoPagoGrupalSectorSelected || '';
    $('kpis-calculo-pago-grupal').innerHTML = [kpi('Sectores', fmt(sectores.length), 'dotaciÃ³n desde legajero'), kpi('Legajos', fmt(data.meta?.dotacion_legajos || 0), 'nÃ³mina activa'), kpi('Rango', `${data.meta?.fecha_desde || ''} a ${data.meta?.fecha_hasta || ''}`, 'dÃ­as evaluados')].join('');
    $('kpis-calculo-pago-grupal').innerHTML = [kpi('Sectores', fmt(sectores.length), 'dotaciÃ³n desde legajero'), kpi('Legajos', fmt(data.meta?.dotacion_legajos || 0), 'nÃ³mina activa'), kpi('Bolsa grupal', money(data.meta?.bolsa_grupal || 0), 'pago actual menos mÃ©todo nuevo', 'warn'), kpi('DÃ­as habilitados', fmt(data.meta?.dias_habilitados || 0), 'cumplimiento >= 90%'), kpi('Rango', `${data.meta?.fecha_desde || ''} a ${data.meta?.fecha_hasta || ''}`, 'dÃ­as evaluados')].join('');
    $('kpis-calculo-pago-grupal').innerHTML = [kpi('Sectores', fmt(sectores.length), 'dotaciÃ³n desde legajero'), kpi('Legajos', fmt(data.meta?.dotacion_legajos || 0), 'nÃ³mina activa'), kpi('Bolsa escenario', money(state.escenarioBolsaGrupal || 0), 'parÃ¡metro de simulaciÃ³n', 'warn'), kpi('DÃ­as habilitados', fmt(data.meta?.dias_habilitados || 0), 'cumplimiento >= 90%'), kpi('Rango', `${data.meta?.fecha_desde || ''} a ${data.meta?.fecha_hasta || ''}`, 'dÃ­as evaluados')].join('');
    $('calculo-pago-grupal-meta').textContent = selected ? `sector seleccionado: ${selected}` : 'seleccionar un sector';
    const sectorCols = [{key:'sector',label:'Sector',mono:true},{key:'legajos_totales',label:'Legajos',num:true},{key:'dias',label:'DÃ­as evaluados',num:true},{key:'dias_con_premio',label:'DÃ­as habilitados (â‰¥90%)',num:true},{key:'porcentaje_dias_con_premio',label:'% dÃ­as habilitados',format:value=>`${fmt(value)} %`}];
    table('tabla-calculo-pago-grupal-sectores', sectorCols, sectores);
    const ordered = sortedRows('tabla-calculo-pago-grupal-sectores', sectorCols, sectores);
    $('tabla-calculo-pago-grupal-sectores').querySelectorAll('tbody tr').forEach((tr,index)=>{ const row=ordered[index]; tr.classList.toggle('active', row?.sector === selected); tr.onclick=event=>{event.stopPropagation(); const next=row?.sector || ''; state.calculoPagoGrupalSectorSelected=next === selected ? '' : next; state.calculoPagoGrupalSelectedDate=''; state.calculoPagoGrupalLegajoSelected=''; renderCalculoPagoGrupal();}; });
    const detail=(data.detalle||[]).filter(row=>!selected || row.sector===selected);
    $('calculo-pago-grupal-detalle-title').textContent=selected ? `Detalle diario Â· ${selected}` : 'Detalle diario del sector';
    const detailCols=[{key:'sector',label:'Sector',mono:true},{key:'fecha',label:'Fecha',mono:true},{key:'dotacion_activa',label:'NÃƒÂ³mina activa',num:true},{key:'ausencias_no_computables',label:'Ausencias excluidas',num:true},{key:'legajos_totales',label:'Target',num:true},{key:'legajos_con_premio',label:'Legajos con premio',num:true},{key:'cumplimiento',label:'Cumplimiento',format:value=>`${fmt(value)} %`}];
    table('tabla-calculo-pago-grupal-detalle',detailCols,detail);
    const detailRows=sortedRows('tabla-calculo-pago-grupal-detalle',detailCols,detail);
    const detailTable=$('tabla-calculo-pago-grupal-detalle');
    detailTable.querySelectorAll('tbody tr').forEach((tr,index)=>{
      const row=detailRows[index];
      tr.dataset.fecha=row?.fecha||'';
      tr.classList.toggle('active',Boolean(row?.fecha) && row.fecha===state.calculoPagoGrupalSelectedDate);
    });
    detailTable.onclick=event=>{
      const tr=event.target.closest('tbody tr');
      if (!tr || !detailTable.contains(tr)) return;
      event.stopPropagation();
      const index=Array.from(tr.parentElement.children).indexOf(tr);
      const currentRows=sortedRows('tabla-calculo-pago-grupal-detalle',detailCols,detail);
      const next=currentRows[index]?.fecha||'';
      state.calculoPagoGrupalSelectedDate=next===state.calculoPagoGrupalSelectedDate?'':next;
      state.calculoPagoGrupalLegajoSelected='';
      renderCalculoPagoGrupal();
    };
    const selectedDetail=detailRows.find(row=>String(row.fecha||'')===String(state.calculoPagoGrupalSelectedDate||''));
    $('calculo-pago-grupal-detalle-status').textContent=selectedDetail ? `Fecha ${selectedDetail.fecha} Â· target ${fmt(selectedDetail.legajos_totales)} Â· premio ${fmt(selectedDetail.legajos_con_premio)} Â· cumplimiento ${fmt(selectedDetail.cumplimiento)} %` : 'seleccionar una fila para filtrar los legajos';
    $('calculo-pago-grupal-clear-date').classList.toggle('hidden',!state.calculoPagoGrupalSelectedDate);
    $('calculo-pago-grupal-clear-date').onclick=()=>{state.calculoPagoGrupalSelectedDate='';state.calculoPagoGrupalLegajoSelected='';renderCalculoPagoGrupal();};
    const legajoDetail = (data.detalle_legajos || []).filter(row => (!selected || row.sector === selected) && (!state.calculoPagoGrupalSelectedDate || row.fecha === state.calculoPagoGrupalSelectedDate));
    const distribucionDiaria = new Map((data.distribucion_legajos_dia || []).map(row => [`${String(row.fecha || '').slice(0,10)}|${String(row.legajo)}`, row]));
    const legajoDetailConDistribucion = legajoDetail.map(row => {
      const distribucion = distribucionDiaria.get(`${String(row.fecha || '').slice(0,10)}|${String(row.legajo)}`) || {};
      return {...row, adicional_bultos:Number(distribucion.adicional_bultos || 0), adicional_horas:Number(distribucion.adicional_horas || 0)};
    });
    $('calculo-pago-grupal-legajos-title').textContent = selected && state.calculoPagoGrupalSelectedDate ? `Legajos Â· ${selected} Â· ${state.calculoPagoGrupalSelectedDate}` : 'Detalle de legajos';
    const legajoCols=[{key:'sector',label:'Sector',mono:true},{key:'fecha',label:'Fecha',mono:true},{key:'legajo',label:'Legajo',mono:true},{key:'incluido_target',label:'Incluido en target',format:value=>value?'Incluido':'No incluido'},{key:'bultos',label:'Bultos',format:value=>fmt(value)},{key:'premio_nuevo',label:'Premio nuevo',money:true},{key:'adicional_bultos',label:'Adic. proporcional bultos',money:true},{key:'adicional_horas',label:'Adic. proporcional horas',money:true},{key:'motivo_ausencia',label:'Motivo ausencia'}];
    table('tabla-calculo-pago-grupal-legajos', legajoCols, legajoDetailConDistribucion);
    const orderedLegajos=sortedRows('tabla-calculo-pago-grupal-legajos',legajoCols,legajoDetailConDistribucion);
    $('tabla-calculo-pago-grupal-legajos').querySelectorAll('tbody tr').forEach((tr,index)=>{const row=orderedLegajos[index];const key=row?`${row.sector}|${row.fecha}|${row.legajo}`:'';tr.classList.toggle('active',key===state.calculoPagoGrupalLegajoSelected);tr.onclick=event=>{event.stopPropagation();state.calculoPagoGrupalLegajoSelected=key===state.calculoPagoGrupalLegajoSelected?'':key;renderCalculoPagoGrupal();};});
    renderAusenciasGrupal(data.detalle_legajos || []);
  }

  function ausenciaOptionKey(value){ const raw=String(value ?? '').trim(); return raw ? raw.toUpperCase() : '__EMPTY__'; }
  function renderAusenciaConfig(data){
    const rows=data.detalle_legajos || [];
    if (!state.ausenciaCatalogo.length){
      state.ausenciaCatalogo=[...new Set(rows.map(row=>String(row.motivo_ausencia ?? '').trim()).filter(raw=>raw.toUpperCase()!=='SIN NOVEDAD' && raw.toUpperCase()!=='SIN_NOVEDAD'))].sort((a,b)=>a.localeCompare(b,'es'));
      state.ausenciaScenarioPending=[...state.ausenciasNoComputables];
    }
    const list=$('lista-ausencias-configurables'); if (!list) return;
    list.innerHTML=state.ausenciaCatalogo.length ? state.ausenciaCatalogo.map(raw=>{const key=ausenciaOptionKey(raw);const upper=raw.toUpperCase();const checked=state.ausenciaScenarioPending.includes(key) || state.ausenciaScenarioPending.includes(upper) || state.ausenciasNoComputables.some(item=>item && (upper.includes(item) || item.includes(upper)));const label=raw || 'Sin motivo informado';return `<label class="absence-check-item"><input type="checkbox" data-ausencia-key="${esc(key)}" ${checked?'checked':''}> <span>${esc(label)}</span></label>`;}).join('') : '<div class="scenario-chart-note">No se detectaron ausencias configurables.</div>';
    list.querySelectorAll('input[data-ausencia-key]').forEach(input=>input.onchange=()=>{state.ausenciaScenarioPending=[...list.querySelectorAll('input:checked')].map(item=>item.dataset.ausenciaKey);$('ausencias-config-status').textContent='Cambios pendientes. PresionÃ¡ â€œRecalcular escenarioâ€ para aplicarlos.';});
    $('recalcular-ausencias-grupal').onclick=async()=>{
      const button=$('recalcular-ausencias-grupal');button.disabled=true;button.textContent='Recalculando...';state.ausenciasNoComputables=[...state.ausenciaScenarioPending];state.tabLoadKeys.calculoPagoGrupal='';
      try { await loadCalculoPagoGrupal();$('ausencias-config-status').textContent='Escenario recalculado. El target y los dÃ­as habilitados reflejan la selecciÃ³n.'; }
      catch(error){if (!isAbortError(error)) {$('ausencias-config-status').textContent=error.message;setStatus(error.message,true);}}
      finally {button.disabled=false;button.textContent='Recalcular escenario';}
    };
  }

  function renderAusenciasGrupal(rows){
    const chart=$('grafico-ausencias-grupal'); if (!chart) return;
    const counts=new Map();
    (rows || []).forEach(row=>{const raw=String(row.motivo_ausencia || '').trim();const normalized=raw.toUpperCase();if (normalized==='SIN NOVEDAD' || normalized==='SIN_NOVEDAD') return;const motivo=raw || 'Sin motivo informado';counts.set(motivo,(counts.get(motivo)||0)+1);});
    const items=[...counts.entries()].sort((a,b)=>b[1]-a[1]);
    if (!items.length){chart.innerHTML='<div class="scenario-empty">No hay registros de ausencia en el rango seleccionado.</div>';return;}
    const total=items.reduce((sum,item)=>sum+item[1],0); const colors=['#1769AA','#2E8B57','#D08A00','#B5413A','#7C3AED','#008B8B','#6B7280','#C2410C']; let cursor=0;
    const stops=items.map((item,index)=>{const start=cursor;cursor+=item[1]*100/total;return `${colors[index%colors.length]} ${start}% ${cursor}%`;}).join(',');
    chart.innerHTML=`<div class="absence-pie" style="background:conic-gradient(${stops})" role="img" aria-label="DistribuciÃ³n de tipos de ausencia"></div><div><div class="absence-legend">${items.map((item,index)=>`<div class="absence-legend-row"><span class="absence-dot" style="background:${colors[index%colors.length]}"></span><span>${esc(item[0])}</span><strong>${fmt(item[1])} (${fmt(item[1]*100/total)}%)</strong></div>`).join('')}</div><div class="scenario-chart-note">DistribuciÃ³n por registros de la grilla de legajos. Total: ${fmt(total)}.</div></div>`;
  }

  async function loadCalculoPagoGrupal(){
    state.fechaDesde=$('rango-desde').value; state.fechaHasta=$('rango-hasta').value;
    const selectedAbsences=Array.isArray(state.ausenciasNoComputables) ? state.ausenciasNoComputables : ['VACAC','FRANCO'];
    const absenceKey=JSON.stringify([...selectedAbsences].sort());
    const key=`${currentTabDataKey()}|${absenceKey}`;
    if (state.calculoPagoGrupal && state.tabLoadKeys.calculoPagoGrupal===key){ renderCalculoPagoGrupal(); return true; }
    if (state.tabPromises.calculoPagoGrupal) return state.tabPromises.calculoPagoGrupal;
    state.calculoPagoGrupalLoading=true;
    const generation=state.loadGeneration;
    const controller=new AbortController();
    state.tabAbortControllers.calculoPagoGrupal=controller;
    const promise=(async()=>{
      const data=await api('/api/analisis-premio-productividad/calculo-pago-grupal?' + qs({fecha_desde:state.fechaDesde,fecha_hasta:state.fechaHasta,motivos_no_computables:absenceKey}),{signal:controller.signal});
      if (generation!==state.loadGeneration) return false;
      state.calculoPagoGrupal=data; state.tabLoadKeys.calculoPagoGrupal=key; state.ausenciasNoComputables=data.meta?.motivos_no_computables || selectedAbsences; renderCalculoPagoGrupal(); return true;
    })();
    state.tabPromises.calculoPagoGrupal=promise;
    try { return await promise; } finally { if (state.tabPromises.calculoPagoGrupal===promise) delete state.tabPromises.calculoPagoGrupal; if (state.tabAbortControllers.calculoPagoGrupal===controller) delete state.tabAbortControllers.calculoPagoGrupal; state.calculoPagoGrupalLoading=false; }
  }

  function propuestaSemana(fecha){
    const d = new Date(`${String(fecha || '').slice(0,10)}T12:00:00`);
    if (Number.isNaN(d.getTime())) return '';
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.toISOString().slice(0,10);
  }
  function renderPropuestaAutonoma(){
    const data = state.evaluacionPicking || {};
    const rows = data.resumen_legajos || [];
    const groupRows = (state.calculoPagoGrupal || {}).distribucion_legajos || [];
    const groupMap = new Map(groupRows.map(row => [String(row.legajo), row]));
    const weeks = [...new Set(rows.map(row => propuestaSemana(row.fecha)).filter(Boolean))].sort();
    const byLegajo = new Map();
    rows.forEach(row => { const key=String(row.legajo || ''); const item=byLegajo.get(key)||{legajo:key,semanas:new Set(),dias:0,bultos:0,individual:0,pago_actual:0,pago_actual_disponible:false,penalizacion_tnc:0,penalizacion_error:0}; item.semanas.add(propuestaSemana(row.fecha)); item.dias+=1; item.bultos+=Number(row.bultos_reales||0); item.individual+=Number(row.premio||0); if (row.premio_real !== null && row.premio_real !== undefined) { item.pago_actual+=Number(row.premio_real||0); item.pago_actual_disponible=true; } item.penalizacion_tnc+=Number(row.penalizacion_tnc||0); item.penalizacion_error+=Number(row.penalizacion_error||0); byLegajo.set(key,item); });
    const totalPoints=[...byLegajo.values()].reduce((sum,item)=>sum+item.semanas.size,0); const increasePct=Math.max(0,Number(state.escenarioAumentoTabla||0)); const increaseFactor=1+increasePct/100; const individualBudget=Math.max(0,Number(state.escenarioBolsaAdicional||0)); const groupBudget=Math.max(0,Number(state.escenarioBolsaGrupal||0)); const pointValue=totalPoints?individualBudget/totalPoints:0;
    const groupBTotal=groupRows.reduce((sum,row)=>sum+Number(row.adicional_bultos||0),0); const groupHTotal=groupRows.reduce((sum,row)=>sum+Number(row.adicional_horas||0),0);
    const proposalRows=[...byLegajo.values()].map(item=>{ const groupItem=groupMap.get(item.legajo)||{}; const individualBase=item.individual*increaseFactor; const individualAdd=item.semanas.size*pointValue; const groupB=groupBTotal?groupBudget*Number(groupItem.adicional_bultos||0)/groupBTotal:0; const groupH=groupHTotal?groupBudget*Number(groupItem.adicional_horas||0)/groupHTotal:0; return {legajo:item.legajo,semanas:item.semanas.size,constancia:`${item.semanas.size}/${weeks.length} semanas`,calidad:'A validar',pago_actual:item.pago_actual_disponible?item.pago_actual:null,premio_base:individualBase,adicional_individual:individualAdd,grupal_bultos:groupB,final_bultos:individualBase+individualAdd+groupB,diferencia_bultos:item.pago_actual_disponible?individualBase+individualAdd+groupB-item.pago_actual:null,grupal_horas:groupH,final_horas:individualBase+individualAdd+groupH,diferencia_horas:item.pago_actual_disponible?individualBase+individualAdd+groupH-item.pago_actual:null,dias:item.dias,bultos:item.bultos}; }).sort((a,b)=>b.adicional_individual-a.adicional_individual||String(a.legajo).localeCompare(String(b.legajo)));
    state.propuestaRows=proposalRows;
    renderPropuestaResumen(proposalRows);
    const legajosConPenalizacion=[...byLegajo.values()].filter(item=>item.penalizacion_tnc>0 || item.penalizacion_error>0).length;
    $('kpis-propuesta-autonoma').innerHTML=[kpi('Presupuesto individual',money(individualBudget),'Bolsa autÃ³noma mensual para constancia individual.','ok'),kpi('Valor por semana',money(pointValue),`${fmt(totalPoints)} puntos observados en ${fmt(byLegajo.size)} legajos.`),kpi('Presupuesto grupal',money(groupBudget),'Bultos y horas son alternativas.','ok'),kpi('Semanas del rango',fmt(weeks.length),'En producciÃ³n se usarÃ¡n semanas operativas cerradas.'),kpi('Calidad Oracle',`${fmt(legajosConPenalizacion)} legajos`, 'TNC y errores integrados; en esta prueba informan y todavÃ­a no descuentan.',legajosConPenalizacion?'warn':'ok')].join('');
    table('tabla-propuesta-autonoma-montos',[{key:'semanas',label:'Semanas con actividad',num:true},{key:'interpretacion',label:'QuÃ© significa'},{key:'adicional',label:'Adicional individual',money:true},{key:'calidad',label:'CondiciÃ³n de calidad'}],Array.from({length:weeks.length+1},(_,index)=>({semanas:index,interpretacion:index===0?'Sin actividad en el rango':index===weeks.length?'Constancia completa del rango':'Actividad sostenida durante el perÃ­odo',adicional:index*pointValue,calidad:index===0?'No aplica':'Debe estar habilitada'})));
    proposalRows.forEach(item=>{const source=byLegajo.get(item.legajo)||{}; item.penalizacion_tnc=Number(source.penalizacion_tnc||0); item.penalizacion_error=Number(source.penalizacion_error||0); item.calidad=(item.penalizacion_tnc>0 || item.penalizacion_error>0)?'Revisar penalizaciÃ³n':'Sin penalizaciones';});
    table('tabla-propuesta-autonoma-legajos',[{key:'legajo',label:'Legajo',mono:true},{key:'semanas',label:'Semanas',num:true},{key:'constancia',label:'Constancia'},{key:'calidad',label:'Calidad'},{key:'penalizacion_tnc',label:'Exceso TNC',money:true},{key:'penalizacion_error',label:'Errores',money:true},{key:'premio_base',label:'Individual base',money:true},{key:'adicional_individual',label:'Adic. individual',money:true},{key:'grupal_bultos',label:'Adic. grupal bultos',money:true},{key:'final_bultos',label:'Final bultos',money:true},{key:'grupal_horas',label:'Adic. grupal horas',money:true},{key:'final_horas',label:'Final horas',money:true},{key:'dias',label:'DÃ­as',num:true},{key:'bultos',label:'Bultos',num:true}],proposalRows);
    table('tabla-propuesta-autonoma-legajos',[{key:'legajo',label:'Legajo',mono:true},{key:'semanas',label:'Semanas',num:true},{key:'constancia',label:'Constancia'},{key:'calidad',label:'Calidad'},{key:'penalizacion_tnc',label:'Exceso TNC',money:true},{key:'penalizacion_error',label:'Errores',money:true},{key:'pago_actual',label:'Pago actual',money:true},{key:'premio_base',label:'Individual base',money:true},{key:'adicional_individual',label:'Adic. individual',money:true},{key:'grupal_bultos',label:'Premio grupal bultos',money:true},{key:'final_bultos',label:'Pago final bultos',money:true},{key:'diferencia_bultos',label:'Dif. bultos vs actual',format:value=>signedMoney2(value)},{key:'grupal_horas',label:'Premio grupal horas',money:true},{key:'final_horas',label:'Pago final horas',money:true},{key:'diferencia_horas',label:'Dif. horas vs actual',format:value=>signedMoney2(value)},{key:'dias',label:'Dias',num:true},{key:'bultos',label:'Bultos',num:true}],proposalRows);
    renderPropuestaScenarioExtras(proposalRows, increasePct, individualBudget, groupBudget);
  }

  function renderPropuestaResumen(proposalRows){
    const actual=proposalRows.reduce((sum,row)=>sum+(row.pago_actual==null?0:Number(row.pago_actual||0)),0);
    const nuevoBultos=proposalRows.reduce((sum,row)=>sum+Number(row.final_bultos||0),0); const nuevoHoras=proposalRows.reduce((sum,row)=>sum+Number(row.final_horas||0),0);
    const diferenciaBultos=nuevoBultos-actual; const diferenciaHoras=nuevoHoras-actual;
    $('kpis-propuesta-resumen').innerHTML=[kpi('Total pago actual',money(actual),'referencia acumulada del rango'),kpi('Total nuevo Â· bultos',money(nuevoBultos),'incluye premio grupal por bultos','ok'),kpi('Diferencia Â· bultos',signedMoney2(diferenciaBultos),diferenciaBultos>=0?'sobre el actual':'debajo del actual',diferenciaBultos>=0?'ok':'warn'),kpi('Total nuevo Â· horas',money(nuevoHoras),'incluye premio grupal por horas','ok'),kpi('Diferencia Â· horas',signedMoney2(diferenciaHoras),diferenciaHoras>=0?'sobre el actual':'debajo del actual',diferenciaHoras>=0?'ok':'warn')].join('');
  }

  function renderImpactBell(id, rows, totalKey, mode){
    const chart=$(id); if (!chart) return;
    const bins=Array.from({length:11},(_,index)=>({label:`${index*10}%`,count:0})); let withoutReference=0;
    (rows||[]).forEach(row=>{const actual=Number(row.pago_actual||0);if (!(actual>0)){withoutReference+=1;return;}const reduction=Math.max(0,Math.min(100,(1-Number(row[totalKey]||0)/actual)*100));const index=reduction>=100?10:Math.floor(reduction/10);bins[index].count+=1;});
    const maxCount=Math.max(1,...bins.map(item=>item.count)); const total=bins.reduce((sum,item)=>sum+item.count,0); const width=920,height=310,left=55,right=20,top=18,bottom=55,plotW=width-left-right,plotH=height-top-bottom,baseY=top+plotH;
    const points=bins.map((item,index)=>{const x=left+index*plotW/(bins.length-1);const y=baseY-(item.count/maxCount)*plotH;return {x,y,count:item.count,label:item.label};});
    const path=points.map((point,index)=>`${index?'L':'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' '); const area=`M ${points[0].x} ${baseY} ${points.map(point=>`L ${point.x} ${point.y}`).join(' ')} L ${points.at(-1).x} ${baseY} Z`;
    const grid=Array.from({length:5},(_,index)=>{const y=top+index*plotH/4;const value=Math.round(maxCount*(1-index/4));return `<line class="grid" x1="${left}" x2="${width-right}" y1="${y}" y2="${y}"></line><text x="${left-8}" y="${y+4}" text-anchor="end">${fmt(value)}</text>`;}).join('');
    chart.innerHTML=`<svg class="scenario-bell" viewBox="0 0 ${width} ${height}" role="img" aria-label="Impacto final por ${mode}"><text x="${width/2}" y="${height-8}" text-anchor="middle">Porcentaje cobrado de menos</text><text x="14" y="${height/2}" text-anchor="middle" transform="rotate(-90 14 ${height/2})">Cantidad de legajos</text>${grid}<line class="axis" x1="${left}" x2="${width-right}" y1="${baseY}" y2="${baseY}"></line><path class="area" d="${area}"></path><path class="line" d="${path}"></path>${points.map(point=>`<circle class="point" cx="${point.x}" cy="${point.y}" r="4"><title>${point.label}: ${fmt(point.count)} legajos</title></circle><text x="${point.x}" y="${baseY+18}" text-anchor="middle">${point.label}</text>`).join('')}</svg><div class="scenario-chart-note">Incluye productividad ajustada, adicional individual y premio grupal por ${mode}. Sin referencia o pago actual cero: ${fmt(withoutReference)}. Total graficado: ${fmt(total)}.</div>`;
  }

  function renderPropuestaScenarioExtras(proposalRows, increasePct, individualBudget, groupBudget){
    const increaseInput=$('escenario-aumento-tabla');
    const groupInput=$('escenario-bolsa-grupal');
    const additionalInput=$('escenario-bolsa-adicional');
    if (increaseInput) increaseInput.value=Number(state.escenarioAumentoTabla||0);
    if (groupInput) groupInput.value=Number(state.escenarioBolsaGrupal||0);
    if (additionalInput) additionalInput.value=Number(state.escenarioBolsaAdicional||0);
    const segmentDefs=[
      {label:'100% menos',match:(ratio,actual)=>actual>0 && ratio<=0},
      {label:'80% a 99% menos',match:(ratio,actual)=>actual>0 && ratio>0 && ratio<.2},
      {label:'60% a 79% menos',match:(ratio,actual)=>actual>0 && ratio>=.2 && ratio<.4},
      {label:'50% a 59% menos',match:(ratio,actual)=>actual>0 && ratio>=.4 && ratio<.5},
      {label:'30% a 49% menos',match:(ratio,actual)=>actual>0 && ratio>=.5 && ratio<.7},
      {label:'1% a 29% menos',match:(ratio,actual)=>actual>0 && ratio>=.7 && ratio<1},
      {label:'Igual o mayor',match:(ratio,actual)=>actual>0 && ratio>=1},
      {label:'Sin referencia actual',match:(_,actual)=>actual===null}
    ];
    const counts=segmentDefs.map(def=>({...def,count:0}));
    proposalRows.forEach(row=>{const actual=row.pago_actual==null?null:Number(row.pago_actual);const individual=Number(row.premio_base||0)+Number(row.adicional_individual||0);const ratio=actual>0?individual/actual:actual===null?null:0;const bucket=counts.find(item=>item.match(ratio,actual));if(bucket) bucket.count+=1;});
    const maxCount=Math.max(1,...counts.map(item=>item.count));
    const total=proposalRows.length;
    const chart=$('grafico-segmentos-pago-individual');
    if (chart) chart.innerHTML=counts.map(item=>`<div class="scenario-bar-row"><span>${esc(item.label)}</span><span class="scenario-bar-track"><span class="scenario-bar-fill" style="width:${item.count*100/maxCount}%"></span></span><span class="scenario-bar-value">${fmt(item.count)} personas (${total?fmt(item.count*100/total):'0'}%)</span></div>`).join('')+`<div class="scenario-chart-note">ComparaciÃ³n del pago individual nuevo (tabla ajustada + adicional, si corresponde) contra el pago actual.</div>`;
    const bellBins=Array.from({length:11},(_,index)=>({label:`${index*10}%`,count:0}));
    let bellWithoutReference=0;
    proposalRows.forEach(row=>{const actual=row.pago_actual==null?null:Number(row.pago_actual);if (!(actual>0)){bellWithoutReference+=1;return;}const individual=Number(row.premio_base||0)+Number(row.adicional_individual||0);const reduction=Math.max(0,Math.min(100,(1-individual/actual)*100));const index=reduction>=100?10:Math.floor(reduction/10);bellBins[index].count+=1;});
    const bellMax=Math.max(1,...bellBins.map(item=>item.count));
    const bellTotal=bellBins.reduce((sum,item)=>sum+item.count,0);
    if (chart){
      const width=920,height=310,left=55,right=20,top=18,bottom=55,plotW=width-left-right,plotH=height-top-bottom,baseY=top+plotH;
      const points=bellBins.map((item,index)=>{const x=left+index*plotW/(bellBins.length-1);const y=baseY-(item.count/bellMax)*plotH;return {x,y,count:item.count,label:item.label};});
      const linePath=points.map((point,index)=>`${index?'L':'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
      const areaPath=`M ${points[0].x.toFixed(1)} ${baseY} ${points.map(point=>`L ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ')} L ${points[points.length-1].x.toFixed(1)} ${baseY} Z`;
      const grid=Array.from({length:5},(_,index)=>{const y=top+index*plotH/4;const value=Math.round(bellMax*(1-index/4));return `<line class="grid" x1="${left}" x2="${width-right}" y1="${y}" y2="${y}"></line><text x="${left-8}" y="${y+4}" text-anchor="end">${fmt(value)}</text>`;}).join('');
      chart.innerHTML=`<svg class="scenario-bell" viewBox="0 0 ${width} ${height}" role="img" aria-label="DistribuciÃ³n de legajos por porcentaje de premio individual cobrado de menos"><text x="${width/2}" y="${height-8}" text-anchor="middle">Porcentaje de premio individual cobrado de menos</text><text x="14" y="${height/2}" text-anchor="middle" transform="rotate(-90 14 ${height/2})">Cantidad de legajos</text>${grid}<line class="axis" x1="${left}" x2="${width-right}" y1="${baseY}" y2="${baseY}"></line><path class="area" d="${areaPath}"></path><path class="line" d="${linePath}"></path>${points.map(point=>`<circle class="point" cx="${point.x}" cy="${point.y}" r="4"><title>${point.label}: ${fmt(point.count)} legajos</title></circle><text x="${point.x}" y="${baseY+18}" text-anchor="middle">${point.label}</text>`).join('')}</svg><div class="scenario-chart-note">Se compara el pago individual nuevo â€”tabla ajustada + adicional, si correspondeâ€” contra el pago actual. Legajos con pago actual cero o sin referencia: ${fmt(bellWithoutReference)}. Total graficado: ${fmt(bellTotal)}.</div>`;
    }
    renderImpactBell('grafico-impacto-pago-bultos',proposalRows,'final_bultos','bultos');
    renderImpactBell('grafico-impacto-pago-horas',proposalRows,'final_horas','horas');
    bindScenarioInput('escenario-aumento-tabla','escenarioAumentoTabla');
    bindScenarioInput('escenario-bolsa-grupal','escenarioBolsaGrupal');
    bindScenarioInput('escenario-bolsa-adicional','escenarioBolsaAdicional');
  }
  let scenarioRecalcTimer=null;
  function scheduleScenarioRecalc(key){
    if (scenarioRecalcTimer) clearTimeout(scenarioRecalcTimer);
    scenarioRecalcTimer=setTimeout(()=>{
      scenarioRecalcTimer=null;
      if (state.activeTab==='calculo-pago-grupal' && key==='escenarioBolsaGrupal' && state.calculoPagoGrupal) renderCalculoPagoGrupal();
      if (state.activeTab==='propuesta-autonoma' && state.evaluacionPicking && state.calculoPagoGrupal){renderPropuestaAutonoma();renderPropuestaAutonomaAlternatives();}
    },250);
  }
  function bindScenarioInput(id,key){
    const input=$(id); if (!input || input.dataset.bound==='1') return;
    input.dataset.bound='1';
    input.addEventListener('input',()=>{state[key]=Math.max(0,Number(input.value||0));scheduleScenarioRecalc(key);});
  }

  function renderPropuestaAutonomaAlternatives(){
    const source=$('tabla-propuesta-autonoma-legajos');
    if (!source || !source.innerHTML) return;
    const configs=[
      {view:'bultos',target:'tabla-propuesta-autonoma-legajos-bultos',hide:label=>label.includes('horas') || (Number(state.escenarioBolsaAdicional||0)===0 && label.includes('adic. individual'))},
      {view:'horas',target:'tabla-propuesta-autonoma-legajos-horas',hide:label=>label.includes('grupal bultos') || label.includes('final bultos') || (Number(state.escenarioBolsaAdicional||0)===0 && label.includes('adic. individual'))}
    ];
    configs.forEach(config=>{
      const target=$(config.target); target.innerHTML=source.innerHTML;
      const headers=[...target.querySelectorAll('thead th')];
      headers.forEach((th,index)=>{
        const hidden=config.hide(th.textContent.trim().toLowerCase());
        th.classList.toggle('hidden',hidden);
        target.querySelectorAll(`tbody tr`).forEach(tr=>tr.children[index]?.classList.toggle('hidden',hidden));
        th.onclick=()=>{
          const key=th.dataset.key;
          const current=state.sorts['tabla-propuesta-autonoma-legajos'];
          state.sorts['tabla-propuesta-autonoma-legajos']=current?.key===key && current.dir==='asc' ? {key,dir:'desc'} : {key,dir:'asc'};
          renderPropuestaAutonoma();
          renderPropuestaAutonomaAlternatives();
        };
      });
    });
    const showBultos=state.propuestaAutonomaView!=='horas';
    $('tabla-propuesta-autonoma-legajos-bultos').parentElement.classList.toggle('hidden',!showBultos);
    $('tabla-propuesta-autonoma-legajos-horas').parentElement.classList.toggle('hidden',showBultos);
    $('propuesta-tab-bultos').classList.toggle('active',showBultos);
    $('propuesta-tab-horas').classList.toggle('active',!showBultos);
    $('propuesta-tab-bultos').onclick=()=>{state.propuestaAutonomaView='bultos';renderPropuestaResumen(state.propuestaRows||[]);renderPropuestaAutonomaAlternatives();};
    $('propuesta-tab-horas').onclick=()=>{state.propuestaAutonomaView='horas';renderPropuestaResumen(state.propuestaRows||[]);renderPropuestaAutonomaAlternatives();};
  }

  async function loadEstudio(){
    if (!state.estudioEnabled) {
      setStatus('Solapa de estudio no habilitada para este usuario.', true);
      return;
    }
    if (!state.fechaDesde || !state.fechaHasta) {
      state.fechaDesde = $('rango-desde').value;
      state.fechaHasta = $('rango-hasta').value;
    }
    const data = await api('/api/analisis-premio-productividad/estudio?' + qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta}));
    state.estudio = data;
    refreshEstudioFilters();
    renderEstudio();
  }
  function dateList(desde, hasta){
    const start = new Date(`${desde}T00:00:00`);
    const end = new Date(`${hasta}T00:00:00`);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return [];
    if (end < start) return [];
    const out = [];
    const cur = new Date(start);
    while (cur <= end) {
      out.push(cur.toISOString().slice(0,10));
      cur.setDate(cur.getDate() + 1);
    }
    return out;
  }
  function svgEmpty(text='Sin datos'){
    return `<div class="empty">${esc(text)}</div>`;
  }
  function renderResumenGrid(){
    return;
  }
  function svgBars(id, rows, options={}){
    const data = (rows || []).filter(x => Number.isFinite(Number(x.value))).slice(0, options.limit || 8);
    if (!data.length) { $(id).innerHTML = svgEmpty(); return; }
    const w = options.width || 980, h = options.height || 280;
    const left = options.left || 210, right = options.right || 34, top = 24, bottom = 30;
    const max = Math.max(...data.map(x => Math.abs(Number(x.value || 0))), 1);
    const rowH = (h - top - bottom) / data.length;
    const plotW = w - left - right;
    $(id).innerHTML = `
      <svg class="insight-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(options.label || 'Grafico')}">
        <line class="axis" x1="${left}" y1="${top}" x2="${left}" y2="${h-bottom}"></line>
        ${data.map((r,i) => {
          const value = Number(r.value || 0);
          const barW = Math.max(2, Math.abs(value) / max * plotW);
          const y = top + i * rowH + rowH * .22;
          const cls = r.cls || (value < 0 ? 'bar-hours' : 'bar-actual');
          return `
            <text class="axis-label" x="6" y="${y + rowH * .35}">${esc(r.label)}</text>
            <rect class="${cls}" x="${left}" y="${y}" width="${barW}" height="${Math.max(12,rowH*.38)}"></rect>
            <text class="value-label" x="${Math.min(left + barW + 8, w - 170)}" y="${y + rowH * .32}">${esc(r.money ? money(value) : fmt(value))}</text>
          `;
        }).join('')}
      </svg>`;
  }
  function pieSlicePath(cx, cy, r, startAngle, endAngle){
    const start = {
      x: cx + r * Math.cos(startAngle),
      y: cy + r * Math.sin(startAngle),
    };
    const end = {
      x: cx + r * Math.cos(endAngle),
      y: cy + r * Math.sin(endAngle),
    };
    const large = endAngle - startAngle > Math.PI ? 1 : 0;
    return `M ${cx} ${cy} L ${start.x} ${start.y} A ${r} ${r} 0 ${large} 1 ${end.x} ${end.y} Z`;
  }
  function renderPrizePie(id, rows, valueKey, label){
    const total = (rows || []).length;
    if (!total) { $(id).innerHTML = svgEmpty(); return; }
    const conPremio = (rows || []).filter(row => Number(row[valueKey] || 0) > .01).length;
    const sinPremio = Math.max(0, total - conPremio);
    const pct = conPremio / total;
    const cx = 150, cy = 118, r = 78;
    const start = -Math.PI / 2;
    const end = start + Math.PI * 2 * pct;
    const fullGreen = pct >= .9999;
    const fullRed = pct <= .0001;
    const premioPath = fullGreen
      ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="var(--green)"></circle>`
      : fullRed
      ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="var(--red)"></circle>`
      : `<path d="${pieSlicePath(cx, cy, r, start, end)}" fill="var(--green)"></path><path d="${pieSlicePath(cx, cy, r, end, start + Math.PI * 2)}" fill="var(--red)"></path>`;
    $(id).innerHTML = `
      <svg class="insight-svg" viewBox="0 0 520 250" role="img" aria-label="${esc(label)}">
        ${premioPath}
        <circle cx="${cx}" cy="${cy}" r="48" fill="var(--panel)"></circle>
        <text class="value-label" x="${cx}" y="${cy-4}" text-anchor="middle" style="font-size:24px">${esc(fmt(pct * 100))}%</text>
        <text class="axis-label" x="${cx}" y="${cy+18}" text-anchor="middle">cobra premio</text>
        <rect x="300" y="72" width="16" height="16" fill="var(--green)"></rect>
        <text class="axis-label" x="326" y="84">Jornadas con premio: ${esc(fmt(conPremio))}</text>
        <rect x="300" y="110" width="16" height="16" fill="var(--red)"></rect>
        <text class="axis-label" x="326" y="122">Jornadas sin premio: ${esc(fmt(sinPremio))}</text>
        <text class="axis-label" x="300" y="162">${esc(label)}</text>
        <text class="axis-label" x="300" y="184">Unidad: jornada x legajo</text>
      </svg>
      <div class="pie-summary">
        <div class="pie-cell"><div class="label">Jornadas con premio</div><strong>${esc(fmt(conPremio))}</strong><div class="kpi-foot">${esc(fmt(pct * 100))}%</div></div>
        <div class="pie-cell no"><div class="label">Jornadas sin premio</div><strong>${esc(fmt(sinPremio))}</strong><div class="kpi-foot">${esc(fmt((1 - pct) * 100))}%</div></div>
      </div>`;
  }
  function renderPrizePies(rows){
    renderPrizePie('chart-premio-actual-pie', rows, 'premio_anterior', 'Actual jornada con extras');
    renderPrizePie('chart-premio-horas-pie', rows, 'premio_x_horas', 'Metodo por horas con extras');
  }
  function renderOperatorPrizeOverlap(rows){
    const byLegajo = new Map();
    (rows || []).forEach(row => {
      const legajo = String(row.operario || '').trim();
      if (!legajo) return;
      const item = byLegajo.get(legajo) || {actual:false, horas:false};
      item.actual = item.actual || Number(row.premio_anterior || 0) > .01;
      item.horas = item.horas || Number(row.premio_x_horas || 0) > .01;
      byLegajo.set(legajo, item);
    });
    const total = Math.max(1, byLegajo.size);
    const values = [...byLegajo.values()];
    const actual = values.filter(x => x.actual).length;
    const horas = values.filter(x => x.horas).length;
    function operatorPie(title, conPremio, label){
      const sinPremio = Math.max(0, byLegajo.size - conPremio);
      const pct = conPremio / total;
      const cx = 150, cy = 118, r = 78;
      const start = -Math.PI / 2;
      const end = start + Math.PI * 2 * pct;
      const premioPath = pct >= .9999
        ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="var(--green)"></circle>`
        : pct <= .0001
        ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="var(--red)"></circle>`
        : `<path d="${pieSlicePath(cx, cy, r, start, end)}" fill="var(--green)"></path><path d="${pieSlicePath(cx, cy, r, end, start + Math.PI * 2)}" fill="var(--red)"></path>`;
      return `<article class="chart-panel">
        <div class="chart-title"><strong>${esc(title)}</strong><span>operarios unicos</span></div>
        <svg class="insight-svg" viewBox="0 0 520 250" role="img" aria-label="${esc(title)}">
          ${premioPath}
          <circle cx="${cx}" cy="${cy}" r="48" fill="var(--panel)"></circle>
          <text class="value-label" x="${cx}" y="${cy-4}" text-anchor="middle" style="font-size:24px">${esc(fmt(pct * 100))}%</text>
          <text class="axis-label" x="${cx}" y="${cy+18}" text-anchor="middle">cobra premio</text>
          <rect x="300" y="72" width="16" height="16" fill="var(--green)"></rect>
          <text class="axis-label" x="326" y="84">Cobran: ${esc(fmt(conPremio))}</text>
          <rect x="300" y="110" width="16" height="16" fill="var(--red)"></rect>
          <text class="axis-label" x="326" y="122">No cobran: ${esc(fmt(sinPremio))}</text>
          <text class="axis-label" x="300" y="162">${esc(label)}</text>
          <text class="axis-label" x="300" y="184">Base: ${esc(fmt(byLegajo.size))} operarios</text>
        </svg>
        <div class="pie-summary">
          <div class="pie-cell"><div class="label">Operarios con premio</div><strong>${esc(fmt(conPremio))}</strong><div class="kpi-foot">${esc(fmt(pct * 100))}%</div></div>
          <div class="pie-cell no"><div class="label">Operarios sin premio</div><strong>${esc(fmt(sinPremio))}</strong><div class="kpi-foot">${esc(fmt((1 - pct) * 100))}%</div></div>
        </div>
      </article>`;
    }
    $('operarios-premio-resumen').innerHTML = `
      <div class="chart-title"><strong>Operarios con premio</strong><span>actual vs horas</span></div>
      <div class="operator-pie-grid">
        ${operatorPie('Metodo actual', actual, 'Actual jornada con extras')}
        ${operatorPie('Metodo por horas', horas, 'Horas /6.5 con extras')}
      </div>`;
  }
  function renderCaseCardsResumen(rows){
    const withGap = [...(rows || [])].map(r => ({
      ...r,
      gapHoras:Number(r.premio_x_horas || 0) - Number(r.premio_anterior || 0),
      gapActual:Number(r.premio_anterior || 0) - Number(r.premio_x_horas || 0),
    }));
    const actualGana = withGap.filter(r => r.gapActual > .01).sort((a,b) => b.gapActual - a.gapActual).slice(0,4);
    const horasGana = withGap.filter(r => r.gapHoras > .01).sort((a,b) => b.gapHoras - a.gapHoras).slice(0,4);
    if (!actualGana.length && !horasGana.length) { $('case-cards-resumen').innerHTML = svgEmpty(); return; }
    function card(row, mode){
      const actual = Number(row.premio_anterior || 0);
      const horas = Number(row.premio_x_horas || 0);
      const max = Math.max(actual, horas, 1);
      const gap = mode === 'actual' ? row.gapActual : row.gapHoras;
      const title = mode === 'actual' ? 'Actual mucho mayor que horas' : 'Horas mucho mayor que actual';
      return `<article class="case-card ${mode === 'actual' ? 'ok' : ''}" data-fecha="${esc(row.fecha)}" data-legajo="${esc(row.operario)}" title="Abrir detalle horario">
        <div class="case-card-title"><strong>${esc(row.operario)}</strong><span class="pill ${mode === 'actual' ? '' : 'bad'}">${esc(row.fecha)}</span></div>
        <div class="kpi-foot">${esc(title)}: <strong>${esc(money(gap))}</strong></div>
        <div class="mini-bars">
          <div class="mini-row"><span>Actual</span><div class="mini-track"><div class="mini-fill" style="width:${Math.max(2, actual/max*100)}%"></div></div><span>${esc(money(actual))}</span></div>
          <div class="mini-row"><span>Horas + ext.</span><div class="mini-track"><div class="mini-fill bad" style="width:${Math.max(2, horas/max*100)}%"></div></div><span>${esc(money(horas))}</span></div>
        </div>
        <div class="kpi-foot" style="margin-top:8px">${esc(unidadProductiva())} total ${esc(fmt(row.bultos))} - ${esc(unidadProductiva())} turno ${esc(fmt(row.bultosturno))} - Desc. ${esc(money(row.descuentos_total))}</div>
        <button class="secondary-cta case-action" data-action="case-detail" type="button">Ver detalle horario</button>
      </article>`;
    }
    $('case-cards-resumen').innerHTML = `
      <div class="chart-title" style="margin-top:4px"><strong>Actual gana</strong><span>4 brechas mas grandes</span></div>
      <div class="case-card-grid">${actualGana.map(row => card(row, 'actual')).join('') || '<div class="empty">Sin casos</div>'}</div>
      <div class="chart-title" style="margin-top:14px"><strong>Horas gana</strong><span>4 brechas mas grandes</span></div>
      <div class="case-card-grid">${horasGana.map(row => card(row, 'horas')).join('') || '<div class="empty">Sin casos</div>'}</div>
    `;
    $('case-cards-resumen').querySelectorAll('.case-card').forEach(card => {
      card.onclick = () => cargarDetalleLegajo(card.dataset.fecha, card.dataset.legajo).catch(e => setStatus(e.message, true));
    });
    $('case-cards-resumen').querySelectorAll('[data-action="case-detail"]').forEach(btn => {
      btn.onclick = event => {
        event.stopPropagation();
        const card = btn.closest('.case-card');
        cargarDetalleLegajo(card.dataset.fecha, card.dataset.legajo).catch(e => setStatus(e.message, true));
      };
    });
  }
  function renderExecutiveCharts(data){
    const rows = data.rows || [];
    renderPrizePies(rows);
    renderOperatorPrizeOverlap(rows);
    renderCaseCardsResumen(rows);
  }
  function renderCriticalReading(data){
    const rows = data.rows || [];
    const k = data.kpis || {};
    const escenario = data.meta?.escenario_horario || '/6.5';
    const brechaConExtras = Number(k.premio_x_horas || 0) - Number(k.premio_anterior || 0);
    const brechaSinExtras = Number(k.premio_x_horas_sin_extras || 0) - Number(k.premio_actual || 0);
    const horasMayor = rows.filter(r => Number(r.premio_x_horas || 0) > Number(r.premio_anterior || 0) + .01);
    const horasMenor = rows.filter(r => Number(r.premio_x_horas || 0) < Number(r.premio_anterior || 0) - .01);
    const iguales = Math.max(0, rows.length - horasMayor.length - horasMenor.length);
    const ahorroPotencial = horasMenor.reduce((acc,r) => acc + (Number(r.premio_anterior || 0) - Number(r.premio_x_horas || 0)), 0);
    const sobrecostoPotencial = horasMayor.reduce((acc,r) => acc + (Number(r.premio_x_horas || 0) - Number(r.premio_anterior || 0)), 0);
    const casosBase = Math.max(1, rows.length);
    const montoBase = Math.max(1, ahorroPotencial + sobrecostoPotencial);
    const actualCeroHorasPaga = rows
      .filter(r => Number(r.premio_anterior || 0) <= .01 && Number(r.premio_x_horas || 0) > .01)
      .sort((a,b) => Number(b.premio_x_horas || 0) - Number(a.premio_x_horas || 0));
    const conclusion = brechaConExtras > 0
      ? `El pago por horas no aparece como una mejora economica natural: en el rango suma ${money(k.premio_x_horas)} contra ${money(k.premio_anterior)} del metodo actual, un sobrecosto neto de ${money(brechaConExtras)}.`
      : `El pago por horas muestra ahorro neto en el rango: suma ${money(k.premio_x_horas)} contra ${money(k.premio_anterior)} del metodo actual, una baja de ${money(Math.abs(brechaConExtras))}.`;
    $('interpretacion').innerHTML = [
      `<strong>Conclusion ejecutiva.</strong> ${conclusion}`,
      `<strong>Escenario activo.</strong> Escala ${escenario}: cambian umbrales y premio por hora; la base del metodo actual no cambia.`,
      `<strong>Casos.</strong> Horas paga menos en ${fmt(horasMenor.length)} casos (${fmt(horasMenor.length / casosBase * 100)}%), mas en ${fmt(horasMayor.length)} (${fmt(horasMayor.length / casosBase * 100)}%) e iguala en ${fmt(iguales)}.`,
      `<strong>Montos.</strong> Ahorros puntuales: ${money(ahorroPotencial)}. Sobrecostos puntuales: ${money(sobrecostoPotencial)}.`,
      `<strong>Clave.</strong> Hay ${fmt(actualCeroHorasPaga.length)} casos con actual $0 y pago horario > $0; ahi falla la premisa de ahorro por promediar la jornada.`,
    ].map(x => `<li>${x}</li>`).join('');
  }
  function buildDetailStats(detailRows){
    const map = new Map();
    (detailRows || []).forEach(row => {
      const fecha = String(row.fecha_base || row.fecha || '').slice(0,10);
      const legajo = String(row.legajo || row.operario || '').trim();
      const almacen = String(row.almacen || '');
      if (!fecha || !legajo) return;
      const key = `${fecha}|${legajo}|${almacen}`;
      const item = map.get(key) || {horasSet:new Set(), horasProductivas:0, bultos:0, minDiarioEstimado:0};
      const bultos = Number(row.bultos || 0);
      if (bultos > 0) item.horasSet.add(String(row.hora ?? ''));
      item.horasProductivas = item.horasSet.size;
      item.bultos += bultos;
      const minHora = Number(row.bultos_hora_min || 0);
      if (Number(row.premio_x_hora || 0) > 0 && minHora > 0) {
        const minDiario = minHora * 8;
        item.minDiarioEstimado = item.minDiarioEstimado ? Math.min(item.minDiarioEstimado, minDiario) : minDiario;
      }
      map.set(key, item);
    });
    return map;
  }
  function estimateEligibilitySavings(rows, detailRows){
    const stats = buildDetailStats(detailRows);
    const out = {
      horas:{casos:0, ahorro:0, evaluados:0},
      bultos:{casos:0, ahorro:0, evaluados:0},
    };
    (rows || []).forEach(row => {
      const actual = Number(row.premio_anterior || 0);
      const horas = Number(row.premio_x_horas || 0);
      const sobrecosto = horas - actual;
      if (sobrecosto <= .01) return;
      const key = `${String(row.fecha || '').slice(0,10)}|${String(row.operario || '').trim()}|${String(row.almacen || '')}`;
      const item = stats.get(key);
      if (!item) return;
      out.horas.evaluados += 1;
      out.bultos.evaluados += 1;
      if (item.horasProductivas < 4) {
        out.horas.casos += 1;
        out.horas.ahorro += sobrecosto;
      }
      const minDiario = Number(item.minDiarioEstimado || 0);
      const umbralBultos = minDiario ? minDiario * .5 : 0;
      if (umbralBultos > 0 && Number(row.bultos || item.bultos || 0) < umbralBultos) {
        out.bultos.casos += 1;
        out.bultos.ahorro += sobrecosto;
      }
    });
    return out;
  }
  function renderSuggestions(data, detailRows=[]){
    const rows = data.rows || [];
    const actualCeroHorasPaga = rows.filter(r => Number(r.premio_anterior || 0) <= .01 && Number(r.premio_x_horas || 0) > .01).length;
    const horasMayor = rows.filter(r => Number(r.premio_x_horas || 0) > Number(r.premio_anterior || 0) + .01).length;
    const eligibility = estimateEligibilitySavings(rows, detailRows);
    $('sugerencias').innerHTML = [
      `Elegibilidad minima: >= 4 horas productivas evitaria ${money(eligibility.horas.ahorro)} en ${fmt(eligibility.horas.casos)} casos.`,
      `Piso de volumen: >= 50% de ${unidadProductivaLower()} minimos diarios estimados evitaria ${money(eligibility.bultos.ahorro)} en ${fmt(eligibility.bultos.casos)} casos.`,
      `Regla de control: actual $0 y horas > $0 requiere habilitacion previa (${fmt(actualCeroHorasPaga)} casos).`,
      `Piloto mensual con topes por jornada antes de productivizar (${fmt(horasMayor)} casos donde horas paga mas).`,
    ].map(x => `<li>${esc(x)}</li>`).join('');
  }
  function groupBonusStats(detailRows=[]){
    const divisor = 6.5;
    const margin = groupMarginRatio();
    const turnos = [
      {key:'1', label:'Turno maÃ±ana'},
      {key:'2', label:'Turno tarde'},
      {key:'3', label:'Turno noche'},
    ];
    const turnoCode = value => {
      const text = String(value || '').toUpperCase().trim();
      if (text === '1' || text.includes('MA')) return '1';
      if (text === '2' || text.includes('TARDE')) return '2';
      if (text === '3' || text.includes('NOCHE')) return '3';
      return text || 'SIN TURNO';
    };
    const paidScales = (detailRows || [])
      .filter(row => Number(row.bultos_modulo || 0) > 0 && Number(row.premio_x_hora || 0) > 0 && Number(row.bultos_hora_min || 0) > 0)
      .map(row => Number(row.bultos_hora_min || 0) * divisor);
    const minDailyPaid = paidScales.length ? Math.min(...paidScales) : 0;
    const byShift = new Map();
    const uniquePeople = new Set();
    (detailRows || []).forEach(row => {
      const fecha = String(row.fecha_base || row.fecha || '').slice(0,10);
      if (!fecha) return;
      const turno = turnoCode(row.turno);
      const key = `${fecha}|${turno}`;
      const item = byShift.get(key) || {fecha, turno, bultos:0, personas:new Set()};
      const bultos = Number(row.bultos_modulo || 0);
      item.bultos += bultos;
      const legajo = String(row.legajo || row.operario || '').trim();
      if (bultos > 0 && legajo) {
        item.personas.add(legajo);
        uniquePeople.add(legajo);
      }
      byShift.set(key, item);
    });
    const shifts = [...byShift.values()].sort((a,b) => `${a.fecha}|${a.turno}`.localeCompare(`${b.fecha}|${b.turno}`)).map(item => {
      const personas = item.personas.size;
      const target = minDailyPaid * personas * margin;
      return {...item, personas, target, cumple:item.bultos >= target && target > 0};
    });
    const targetByDay = new Map();
    shifts.forEach(shift => {
      const item = targetByDay.get(shift.fecha) || {target:0, bultos:0};
      item.target += shift.target;
      item.bultos += shift.bultos;
      targetByDay.set(shift.fecha, item);
    });
    const targetMes = shifts.reduce((acc, shift) => acc + shift.target, 0);
    const bultosMes = shifts.reduce((acc, shift) => acc + shift.bultos, 0);
    const targetDiaProm = targetByDay.size ? [...targetByDay.values()].reduce((acc, day) => acc + day.target, 0) / targetByDay.size : 0;
    const diasRango = dateList(state.fechaDesde, state.fechaHasta).length;
    const diasConBase = new Set(shifts.map(shift => shift.fecha)).size;
    const byTurno = {};
    turnos.forEach(turno => {
      const rows = shifts.filter(shift => shift.turno === turno.key);
      const bultos = rows.reduce((acc, shift) => acc + shift.bultos, 0);
      const dias = rows.length;
      byTurno[turno.key] = {
        ...turno,
        legajos:dias ? rows.reduce((acc, shift) => acc + shift.personas, 0) / dias : 0,
        bultos,
        dias,
        promBultosDia:dias ? bultos / dias : 0,
        cumplen:rows.filter(shift => shift.cumple).length,
      };
    });
    const legajosDiaProm = targetByDay.size ? shifts.reduce((acc, shift) => acc + shift.personas, 0) / targetByDay.size : 0;
    return {divisor, margin, minDailyPaid, shifts, uniquePeople:uniquePeople.size, legajosDiaProm, targetMes, bultosMes, targetDiaProm, diasRango, diasConBase, byTurno, turnos};
  }
  function groupFixedValue(almacen){
    const division = String(almacen || '').trim();
    const key = groupFixedKey(division);
    return Number(
      state.groupFixedDaily[key]
      ?? GROUP_FIXED_DEFAULTS[key]
      ?? GROUP_FIXED_BY_DIVISION_DEFAULTS[division]
      ?? 0
    );
  }
  function groupBonusQualificationByDay(detailRows=[]){
    const stats = groupBonusStats(detailRows);
    const minDailyPaid = Number(stats.minDailyPaid || 0);
    const margin = groupMarginRatio();
    const byShift = new Map();
    const turnoCode = value => {
      const text = String(value || '').toUpperCase().trim();
      if (text === '1' || text.includes('MA')) return '1';
      if (text === '2' || text.includes('TARDE')) return '2';
      if (text === '3' || text.includes('NOCHE')) return '3';
      return text || 'SIN TURNO';
    };
    (detailRows || []).forEach(row => {
      const fecha = String(row.fecha_base || row.fecha || '').slice(0,10);
      const almacen = String(row.almacen || '').trim();
      if (!fecha || !almacen) return;
      const turno = turnoCode(row.turno);
      const key = `${fecha}|${almacen}|${turno}`;
      const item = byShift.get(key) || {fecha, almacen, turno, bultos:0, personas:new Set()};
      const bultos = Number(row.bultos_modulo || 0);
      item.bultos += bultos;
      const legajo = String(row.legajo || row.operario || '').trim();
      if (bultos > 0 && legajo) item.personas.add(legajo);
      byShift.set(key, item);
    });
    const byDay = new Map();
    [...byShift.values()].forEach(shift => {
      const key = `${shift.fecha}|${shift.almacen}`;
      const item = byDay.get(key) || {bultos:0, target:0, turnos:0, turnos_cumplen:0};
      const target = minDailyPaid * shift.personas.size * margin;
      const cumple = target > 0 && shift.bultos >= target;
      item.bultos += shift.bultos;
      item.target += target;
      item.turnos += 1;
      if (cumple) item.turnos_cumplen += 1;
      byDay.set(key, item);
    });
    byDay.forEach(item => {
      item.cumple = item.target > 0 && item.bultos >= item.target;
    });
    return byDay;
  }
  function groupBonusSimulationRows(detailRows=[]){
    const qualificationByDay = groupBonusQualificationByDay(detailRows);
    const premioHorasByDay = new Map();
    const premioActualByDay = new Map();
    (state.resumenRows || []).forEach(row => {
      const fecha = String(row.fecha || row.fecha_base || '').slice(0,10);
      const almacen = String(row.almacen || '').trim();
      const legajo = String(row.operario || row.legajo || '').trim();
      if (fecha && almacen && legajo) {
        const key = `${fecha}|${almacen}|${legajo}`;
        premioHorasByDay.set(key, Number(premioHorasByDay.get(key) || 0) + Number(row.premio_x_horas || 0));
        premioActualByDay.set(key, Number(premioActualByDay.get(key) || 0) + Number(row.premio_anterior ?? row.premio_actual ?? 0));
      }
    });
    const byPersonDay = new Map();
    (detailRows || []).forEach(row => {
      const fecha = String(row.fecha_base || row.fecha || '').slice(0,10);
      const almacen = String(row.almacen || '').trim();
      const legajo = String(row.legajo || row.operario || '').trim();
      if (!fecha || !almacen || !legajo) return;
      const key = `${fecha}|${almacen}|${legajo}`;
      const item = byPersonDay.get(key) || {fecha, almacen, legajo, nombre:String(row.nombre || '').trim(), bultos:0, premio_horas_65:0};
      item.bultos += Number(row.bultos_modulo || 0);
      item.premio_horas_65 += Number(row.premio_x_hora || 0);
      if (!item.nombre && row.nombre) item.nombre = String(row.nombre || '').trim();
      byPersonDay.set(key, item);
    });
    (state.resumenRows || []).forEach(row => {
      const fecha = String(row.fecha || row.fecha_base || '').slice(0,10);
      const almacen = String(row.almacen || '').trim();
      const legajo = String(row.operario || row.legajo || '').trim();
      if (!fecha || !almacen || !legajo) return;
      const key = `${fecha}|${almacen}|${legajo}`;
      if (!byPersonDay.has(key)) {
        byPersonDay.set(key, {
          fecha,
          almacen,
          legajo,
          nombre:String(row.nombre || '').trim(),
          bultos:Number(row.bultosturno ?? row.bultos ?? 0),
          premio_horas_65:Number(premioHorasByDay.get(key) || 0),
        });
      }
    });
    const byAlmacenDay = new Map();
    [...byPersonDay.values()].forEach(row => {
      const key = `${row.fecha}|${row.almacen}`;
      const qualification = qualificationByDay.get(key) || {cumple:false, target:0, turnos_cumplen:0, turnos:0};
      const item = byAlmacenDay.get(key) || {bultos:0, fijo:qualification.cumple ? groupFixedValue(row.almacen) : 0, target:qualification.target || 0, cumple:qualification.cumple === true, turnos_cumplen:qualification.turnos_cumplen || 0, turnos:qualification.turnos || 0};
      item.bultos += Number(row.bultos || 0);
      byAlmacenDay.set(key, item);
    });
    return [...byPersonDay.values()].map(row => {
      const day = byAlmacenDay.get(`${row.fecha}|${row.almacen}`) || {bultos:0, fijo:0};
      const rowKey = `${row.fecha}|${row.almacen}|${row.legajo}`;
      const premioHoras = premioHorasByDay.get(rowKey) ?? row.premio_horas_65;
      const premioActual = premioActualByDay.get(rowKey) ?? 0;
      const montoGrupal = day.bultos > 0 && row.bultos > 0 ? Number(day.fijo || 0) * row.bultos / day.bultos : 0;
      const totalModelo = premioHoras + montoGrupal;
      return {
        legajo:row.legajo,
        nombre:row.nombre,
        fecha:row.fecha,
        almacen:row.almacen,
        premio_actual:round2(premioActual),
        premio_horas_65:round2(premioHoras),
        bultos:round2(row.bultos),
        bultos_target:round2(day.target),
        estado_objetivo:day.cumple ? 'Cumple' : 'No cumple',
        turnos_sobre_target:`${day.turnos_cumplen || 0}/${day.turnos || 0}`,
        monto_fijo_objetivo_grupal:round2(montoGrupal),
        total_a_cobrar:round2(totalModelo),
        diferencia:round2(totalModelo - premioActual),
      };
    }).sort((a,b) => a.fecha.localeCompare(b.fecha) || a.almacen.localeCompare(b.almacen) || a.legajo.localeCompare(b.legajo));
  }
  function groupBonusCols(){
    return [
      {key:'legajo', label:'Legajo', mono:true, w:'90px'},
      {key:'nombre', label:'Nombre', w:'170px'},
      {key:'fecha', label:'Fecha', mono:true, w:'105px'},
      {key:'almacen', label:'Division', w:'170px'},
      {key:'premio_horas_65', label:'$ Premio x Horas / 6.5', money:true, w:'150px'},
      {key:'bultos', label:unidadProductiva(), num:true, w:'110px'},
      {key:'bultos_target', label:'Target dia', num:true, w:'120px'},
      {key:'estado_objetivo', label:'Objetivo', w:'105px'},
      {key:'monto_fijo_objetivo_grupal', label:'$ Monto Fijo objetivo Grupal', money:true, w:'170px'},
      {key:'total_a_cobrar', label:'Total a Cobrar', money:true, w:'140px'},
    ];
  }
  function filteredGroupBonusRows(){
    const almacen = state.groupFilters.almacen || 'TODOS';
    const fecha = state.groupFilters.fecha || '';
    const legajo = String(state.groupFilters.legajo || '').trim();
    return (state.groupBonusRows || []).filter(row => {
      const okAlmacen = almacen === 'TODOS' || row.almacen === almacen;
      const okFecha = !fecha || row.fecha === fecha;
      const okLegajo = !legajo || String(row.legajo || '').includes(legajo);
      return okAlmacen && okFecha && okLegajo;
    });
  }
  function renderGroupFilterOptions(rows){
    const current = state.groupFilters.almacen || 'TODOS';
    const almacenes = [...new Set((rows || []).map(row => row.almacen).filter(Boolean))].sort((a,b) => a.localeCompare(b));
    $('grupal-f-almacen').innerHTML = [`<option value="TODOS">TODOS</option>`, ...almacenes.map(almacen => `<option value="${esc(almacen)}">${esc(almacen)}</option>`)].join('');
    $('grupal-f-almacen').value = almacenes.includes(current) ? current : 'TODOS';
    state.groupFilters.almacen = $('grupal-f-almacen').value;
    $('grupal-f-fecha').min = state.fechaDesde || '';
    $('grupal-f-fecha').max = state.fechaHasta || '';
    if (state.groupFilters.fecha && (state.groupFilters.fecha < state.fechaDesde || state.groupFilters.fecha > state.fechaHasta)) {
      state.groupFilters.fecha = '';
    }
    $('grupal-f-fecha').value = state.groupFilters.fecha || '';
    $('grupal-f-legajo').value = state.groupFilters.legajo || '';
  }
  function renderGroupFilterTotals(rows){
    const total = key => rows.reduce((acc, row) => acc + Number(row[key] || 0), 0);
    $('grupal-filter-totals').innerHTML = [
      ['Premio x Horas / 6.5', money(total('premio_horas_65'))],
      [unidadProductiva(), fmt(total('bultos'))],
      ['Monto Fijo objetivo Grupal', money(total('monto_fijo_objetivo_grupal'))],
      ['Total a Cobrar', money(total('total_a_cobrar'))],
    ].map(([label, value]) => `<div class="group-total-cell"><div class="label">${esc(label)}</div><strong>${esc(value)}</strong></div>`).join('');
  }
  function renderGroupBonusTable(){
    const rows = filteredGroupBonusRows();
    renderGroupFilterTotals(rows);
    table('tabla-premio-grupal', groupBonusCols(), rows);
  }
  function groupLegajoPeriodCols(){
    return [
      {key:'legajo', label:'Legajo', mono:true, w:'90px'},
      {key:'nombre', label:'Nombre', w:'180px'},
      {key:'almacenes', label:'Divisiones', w:'190px'},
      {key:'jornadas', label:'Jornadas', num:true, w:'95px'},
      {key:'premio_actual', label:'$ MÃ©todo actual', money:true, w:'145px'},
      {key:'premio_horas_65', label:'$ Individual /6.5', money:true, w:'155px'},
      {key:'monto_fijo_objetivo_grupal', label:'$ Premio grupal', money:true, w:'150px'},
      {key:'total_a_cobrar', label:'$ MÃ©todo nuevo', money:true, w:'150px'},
      {key:'diferencia', label:'$ Diferencia', money:true, w:'135px'},
    ];
  }
  function groupLegajoDetailCols(){
    return [
      {key:'fecha', label:'Fecha', mono:true, w:'105px'},
      {key:'almacen', label:'Division', w:'180px'},
      {key:'premio_actual', label:'$ MÃ©todo actual', money:true, w:'140px'},
      {key:'premio_horas_65', label:'$ Individual /6.5', money:true, w:'140px'},
      {key:'monto_fijo_objetivo_grupal', label:'$ Grupal', money:true, w:'130px'},
      {key:'total_a_cobrar', label:'$ MÃ©todo nuevo', money:true, w:'150px'},
      {key:'diferencia', label:'$ Diferencia', money:true, w:'130px'},
      {key:'bultos', label:unidadProductiva(), num:true, w:'95px'},
      {key:'bultos_target', label:'Target dia', num:true, w:'115px'},
      {key:'estado_objetivo', label:'Objetivo', w:'105px'},
    ];
  }
  function groupLegajoPeriodRows(){
    const byLegajo = new Map();
    (state.groupBonusRows || []).forEach(row => {
      const legajo = String(row.legajo || '').trim();
      if (!legajo) return;
      const item = byLegajo.get(legajo) || {
        legajo,
        nombre:row.nombre || '',
        almacenesSet:new Set(),
        fechasSet:new Set(),
        premio_actual:0,
        premio_horas_65:0,
        monto_fijo_objetivo_grupal:0,
        total_a_cobrar:0,
        diferencia:0,
      };
      if (row.almacen) item.almacenesSet.add(row.almacen);
      if (row.fecha) item.fechasSet.add(row.fecha);
      if (!item.nombre && row.nombre) item.nombre = row.nombre;
      item.premio_actual += Number(row.premio_actual || 0);
      item.premio_horas_65 += Number(row.premio_horas_65 || 0);
      item.monto_fijo_objetivo_grupal += Number(row.monto_fijo_objetivo_grupal || 0);
      item.total_a_cobrar += Number(row.total_a_cobrar || 0);
      item.diferencia += Number(row.diferencia || 0);
      byLegajo.set(legajo, item);
    });
    return [...byLegajo.values()].map(row => ({
      ...row,
      jornadas:row.fechasSet.size,
      almacenes:[...row.almacenesSet].sort((a,b) => a.localeCompare(b)).join(', '),
      premio_actual:round2(row.premio_actual),
      premio_horas_65:round2(row.premio_horas_65),
      monto_fijo_objetivo_grupal:round2(row.monto_fijo_objetivo_grupal),
      total_a_cobrar:round2(row.total_a_cobrar),
      diferencia:round2(row.diferencia),
    })).sort((a,b) => b.total_a_cobrar - a.total_a_cobrar || a.legajo.localeCompare(b.legajo));
  }
  function renderGroupLegajoDetail(){
    const legajo = String(state.groupLegajoSelected || '').trim();
    const rows = (state.groupBonusRows || []).filter(row => String(row.legajo || '') === legajo);
    const first = rows[0] || {};
    $('grupal-legajo-detalle-title').textContent = legajo ? `${legajo}${first.nombre ? ` - ${first.nombre}` : ''}` : 'selecciona un legajo';
    table('tabla-grupal-legajo-detalle', groupLegajoDetailCols(), rows);
  }
  function renderGroupLegajoImpactPie(rows){
    const total = (rows || []).length;
    if (!total) { $('chart-grupal-legajos-impacto').innerHTML = svgEmpty(); return; }
    const items = [
      {key:'mas', label:'CobrarÃ­a mÃ¡s', value:rows.filter(row => Number(row.diferencia || 0) > .01).length, color:'var(--green)', cls:''},
      {key:'menos', label:'CobrarÃ­a menos', value:rows.filter(row => Number(row.diferencia || 0) < -.01).length, color:'var(--red)', cls:'bad'},
      {key:'igual', label:'CobrarÃ­a igual', value:rows.filter(row => Math.abs(Number(row.diferencia || 0)) <= .01).length, color:'var(--blue)', cls:'neutral'},
    ];
    const cx = 150, cy = 118, r = 78;
    let angle = -Math.PI / 2;
    const arc = (start, end) => {
      const x1 = cx + r * Math.cos(start), y1 = cy + r * Math.sin(start);
      const x2 = cx + r * Math.cos(end), y2 = cy + r * Math.sin(end);
      const large = end - start > Math.PI ? 1 : 0;
      return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
    };
    const paths = items.map(item => {
      const start = angle;
      const end = start + Math.PI * 2 * (item.value / total);
      angle = end;
      if (!item.value) return '';
      return `<path d="${arc(start, end)}" fill="${item.color}" stroke="#fff" stroke-width="2"></path>`;
    }).join('');
    $('chart-grupal-legajos-impacto').innerHTML = `
      <svg class="insight-svg" viewBox="0 0 760 280" role="img" aria-label="Impacto por legajo">
        ${paths}
        <circle cx="${cx}" cy="${cy}" r="38" fill="var(--panel)" stroke="var(--rule)"></circle>
        <text x="${cx}" y="${cy - 4}" text-anchor="middle" class="value-label">${fmt(total)}</text>
        <text x="${cx}" y="${cy + 18}" text-anchor="middle" class="axis-label">legajos</text>
        ${items.map((item, index) => {
          const y = 64 + index * 54;
          const pct = total ? (item.value / total) * 100 : 0;
          return `<rect x="340" y="${y - 14}" width="18" height="18" fill="${item.color}"></rect>
            <text x="370" y="${y}" class="value-label">${esc(item.label)}: ${fmt(item.value)} (${fmt(pct)}%)</text>`;
        }).join('')}
      </svg>
      <div class="winner-summary">
        ${items.map(item => `<div class="winner-cell ${esc(item.cls)}"><div class="label">${esc(item.label)}</div><strong>${fmt(item.value)}</strong><div class="kpi-foot">${fmt((item.value / total) * 100)}% de legajos</div></div>`).join('')}
      </div>
    `;
  }
  function renderGroupLegajoPeriod(){
    const rows = groupLegajoPeriodRows();
    const totalActual = rows.reduce((acc, row) => acc + Number(row.premio_actual || 0), 0);
    const totalNuevo = rows.reduce((acc, row) => acc + Number(row.total_a_cobrar || 0), 0);
    const diferencia = totalNuevo - totalActual;
    $('kpis-grupal-legajos').innerHTML = [
      kpi('Legajos', fmt(rows.length), `${state.fechaDesde} a ${state.fechaHasta}`),
      kpi('MÃ©todo actual', money(totalActual), 'Suma pagada en el perÃ­odo'),
      kpi('MÃ©todo nuevo', money(totalNuevo), `Diferencia ${signedMoney(diferencia)}`, diferencia > .01 ? 'warn' : diferencia < -.01 ? 'ok' : ''),
    ].join('');
    renderGroupLegajoImpactPie(rows);
    if (!rows.some(row => row.legajo === state.groupLegajoSelected)) {
      state.groupLegajoSelected = rows[0]?.legajo || '';
    }
    table('tabla-grupal-legajos-periodo', groupLegajoPeriodCols(), rows);
    const sorted = sortedRows('tabla-grupal-legajos-periodo', groupLegajoPeriodCols(), rows);
    $('tabla-grupal-legajos-periodo').querySelectorAll('th.sortable').forEach(th => {
      th.onclick = () => {
        const key = th.dataset.key;
        const current = state.sorts['tabla-grupal-legajos-periodo'];
        state.sorts['tabla-grupal-legajos-periodo'] = current?.key === key && current.dir === 'asc' ? {key, dir:'desc'} : {key, dir:'asc'};
        renderGroupLegajoPeriod();
      };
    });
    $('tabla-grupal-legajos-periodo').querySelectorAll('tbody tr').forEach((tr, index) => {
      const row = sorted[index];
      if (!row || !row.legajo) return;
      tr.classList.toggle('active', row.legajo === state.groupLegajoSelected);
      tr.onclick = () => {
        state.groupLegajoSelected = row.legajo;
        renderGroupLegajoPeriod();
      };
    });
    renderGroupLegajoDetail();
  }
  function renderPremioGrupalLegajos(){
    state.groupBonusRows = groupBonusSimulationRows(state.detalleRows || []);
    renderGroupLegajoPeriod();
  }
  async function loadPremioGrupalLegajos(){
    if (!state.resumenRows.length) {
      const resumenData = await api('/api/analisis-premio-productividad/rango-cache?' + qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...comboParams()}));
      state.resumenRows = resumenData.rows || [];
    }
    if (!state.detalleRows.length) state.detalleRows = await loadDetalleRowsForCurrentRange();
    renderPremioGrupalLegajos();
  }
  function exportGroupBonusExcel(){
    const rows = filteredGroupBonusRows();
    if (!rows.length) {
      setStatus('No hay registros filtrados para exportar.', true);
      return;
    }
    const cols = groupBonusCols();
    const html = `<!doctype html><html><head><meta charset="utf-8"></head><body><table border="1"><thead><tr>${cols.map(c => `<th>${esc(c.label)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${cols.map(c => `<td>${esc(c.money || c.num ? Number(row[c.key] || 0) : row[c.key])}</td>`).join('')}</tr>`).join('')}</tbody></table></body></html>`;
    const blob = new Blob([html], {type:'application/vnd.ms-excel;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const filtroAlmacen = (state.groupFilters.almacen || 'TODOS').replaceAll(' ', '_').replaceAll('+', 'mas');
    const filtroFecha = state.groupFilters.fecha || `${state.fechaDesde}_a_${state.fechaHasta}`;
    const filtroLegajo = state.groupFilters.legajo ? `_legajo_${state.groupFilters.legajo}` : '';
    a.href = url;
    a.download = `premio_grupal_${filtroAlmacen}_${filtroFecha}${filtroLegajo}.xls`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatus(`Excel generado con ${fmt(rows.length)} registros filtrados.`);
  }
  function renderPremioGrupal(){
    const stats = groupBonusStats(state.detalleRows || []);
    const simRows = groupBonusSimulationRows(state.detalleRows || []);
    state.groupBonusRows = simRows;
    renderGroupFilterOptions(simRows);
    const totalGrupal = simRows.reduce((acc, row) => acc + Number(row.monto_fijo_objetivo_grupal || 0), 0);
    const totalCobrar = simRows.reduce((acc, row) => acc + Number(row.total_a_cobrar || 0), 0);
    const activeAlmacenes = [...new Set((state.detalleRows || []).map(row => String(row.almacen || '').trim()).filter(Boolean))];
    const fixedDailyTotal = activeAlmacenes.reduce((acc, almacen) => acc + groupFixedValue(almacen), 0);
    const fixedLabel = state.almacen === 'TODOS' ? 'Fijo diario total' : `Fijo diario division ${state.almacen}`;
    $('grupal-parametros').innerHTML = [
      `<div class="group-param"><div class="label">${esc(unidadProductiva())} minimos a realizar</div><strong>${esc(fmt(stats.minDailyPaid))}</strong><div class="kpi-foot">Primer nivel con pago > 0, sin horas extra</div></div>`,
      `<div class="group-param"><label class="label" for="grupal-margen-pct">% margen</label><div class="group-margin-control"><input id="grupal-margen-pct" type="number" min="0" max="200" step="1" value="${esc(groupMarginPct())}"><span>%</span></div><div class="kpi-foot">Factor aplicado al objetivo. Recalcula target y reparto elegible.</div></div>`,
      `<div class="group-param"><div class="label">${esc(fixedLabel)}</div><strong>${esc(money(state.almacen === 'TODOS' ? fixedDailyTotal : groupFixedValue(state.almacen)))}</strong><div class="kpi-foot">Editable por gerencia. Reparto puro por ${esc(unidadProductivaLower())} del dia.</div></div>`,
    ].join('');
    const totalRow = `<div class="group-kpi-row"><div class="group-row-title">Totales</div>${[
      kpi('Cantidad legajos', fmt(stats.legajosDiaProm), `Promedio diario de personas con ${unidadProductivaLower()} de turno > 0.`),
      kpi(`${unidadProductiva()} target dia`, fmt(stats.targetDiaProm), 'Promedio diario de la suma de targets por turno.', 'warn'),
      kpi(`${unidadProductiva()} target mes`, fmt(stats.targetMes), `Suma targets por turno. ${unidadProductiva()} turno reales: ${fmt(stats.bultosMes)}.`, stats.bultosMes >= stats.targetMes ? 'ok' : 'bad'),
      kpi('Reparto grupal', money(totalGrupal), `Total simulado en ${fmt(simRows.length)} legajo/dia con reparto puro.`, 'ok'),
    ].join('')}</div>`;
    const turnoRows = stats.turnos.map(turno => {
      const item = stats.byTurno[turno.key] || {legajos:0, promBultosDia:0, cumplen:0, dias:0};
      const pctCumplen = item.dias ? (item.cumplen / item.dias) * 100 : 0;
      return `<div class="group-kpi-row"><div class="group-row-title">${esc(turno.label)}</div>${[
        kpi('Cantidad legajos', fmt(item.legajos), `Promedio diario de personas con ${unidadProductivaLower()} de turno > 0.`),
        kpi(`Prom. ${unidadProductivaLower()} x dia`, fmt(item.promBultosDia), `Promedio de ${unidadProductivaLower()} de turno por dia/turno.`),
        kpi('Dias sobre target', `${fmt(item.cumplen)} / ${fmt(item.dias)} (${fmt(pctCumplen)}%)`, 'Dias del turno que superaron su target.', item.cumplen >= item.dias && item.dias ? 'ok' : item.cumplen ? 'warn' : 'bad'),
        kpi(`${unidadProductiva()} turno`, fmt(item.bultos), `Suma de ${unidadProductivaLower()} dentro del turno en el rango.`),
      ].join('')}</div>`;
    }).join('');
    $('kpis-grupal').innerHTML = totalRow + turnoRows;
    renderGroupBonusTable();
  }
  async function loadPremioGrupal(){
    if (!state.resumenRows.length) {
      const resumenData = await api('/api/analisis-premio-productividad/rango-cache?' + qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...comboParams()}));
      state.resumenRows = resumenData.rows || [];
    }
    if (!state.detalleRows.length) state.detalleRows = await loadDetalleRowsForCurrentRange();
    renderPremioGrupal();
  }
  async function ensureCache(){
    return consultarRango(false);
  }
  async function consultarRango(force=false){
    if (state.loading) return false;
    state.fechaDesde = $('rango-desde').value;
    state.fechaHasta = $('rango-hasta').value;
    const combo = comboParams();
    if (!state.fechaDesde || !state.fechaHasta) {
      setStatus('Indica fecha desde y fecha hasta.', true);
      return false;
    }
    const max = maxQueryDate();
    if (state.fechaDesde > max || state.fechaHasta > max) {
      setStatus(`La fecha maxima permitida es ${max}. No se puede consultar el dia actual ni futuro.`, true);
      return false;
    }
    setBusy(true);
    try {
      const days = dateList(state.fechaDesde, state.fechaHasta);
      if (!days.length) {
        setStatus('Fecha hasta no puede ser menor a fecha desde.', true);
        return false;
      }
      if (state.activeTab === 'estudio') {
        state.estudioOperacionSelected = null;
        await loadEstudio();
        state.hasConsulted = true;
        setStatus('Estudio actualizado desde Oracle Productiv.');
        return true;
      }
      if (state.activeTab === 'evaluacion-picking') {
        await loadEvaluacionPicking();
        state.hasConsulted = true;
        setStatus('EvaluaciÃ³n Picking actualizada; los dÃ­as completos se leen desde cache local.');
        return true;
      }
      if (state.activeTab === 'punto0') {
        await loadPunto0();
        state.hasConsulted = true;
        return true;
      }
      if (state.activeTab === 'propuesta-autonoma') {
        await loadTab('propuesta-autonoma');
        state.hasConsulted = true;
        setStatus('Propuesta autÃ³noma actualizada desde cache local.');
        return true;
      }
      if (state.activeTab === 'calculo-pago-grupal') {
        // Esta solapa trabaja sobre la evaluaciÃ³n cacheada y no debe disparar
        // la precarga general ni quedar esperando faltantes de Oracle.
        await loadCalculoPagoGrupal();
        state.hasConsulted = true;
        setStatus('CÃ¡lculo Pago Grupal actualizado desde cache local.');
        return true;
      }
      const cobertura = await api('/api/analisis-premio-productividad/cache-cobertura?' + qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...combo}));
      const faltantes = cobertura.faltantes || [];
      const operacionesCacheadas = cobertura.operaciones_cacheadas || [state.operacion];
      const alcanceCarga = operacionesCacheadas.length > 1 ? `operaciones ${operacionesCacheadas.join(' + ')}` : `operacion ${operacionesCacheadas[0] || state.operacion}`;
      setStatus(faltantes.length
        ? `Cache diaria (${alcanceCarga}): ${fmt(cobertura.dias_cache)}/${fmt(cobertura.dias)} dias completos. Faltantes que iran a Oracle: ${faltantes.slice(0,6).join(', ')}${faltantes.length > 6 ? '...' : ''}.`
        : `Cache diaria completa (${alcanceCarga}): ${fmt(cobertura.dias_cache)}/${fmt(cobertura.dias)} dias. No deberia consultar Oracle.`
      );
      if (!force && !faltantes.length) {
        const data = await api('/api/analisis-premio-productividad/rango-cache?' + qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...combo}));
        data.meta = {
          ...(data.meta || {}),
          dias_oracle: 0,
          dias_cache: cobertura.dias_cache,
          detalle_dias: (cobertura.cache || []).map(x => ({fecha:x.fecha, estado:'cache', rows:x.rows})),
        };
        state.loadError = '';
        state.detalleRows = await loadDetalleRowsForCurrentRange();
        renderResumen(data, state.detalleRows);
        state.hasConsulted = true;
        if (state.activeTab === 'grupal') renderPremioGrupal();
        if (state.activeTab === 'grupal-legajos') renderPremioGrupalLegajos();
        if (state.activeTab === 'detalle') await loadDetalle();
        if (state.activeTab === 'cache') await loadCache();
        setStatus(`Rango listo desde cache para ${alcanceCarga}. Dias: ${cobertura.dias || 0}, desde Oracle: 0, ya cacheados: ${cobertura.dias_cache || 0}.`);
        return true;
      }
      const estados = [];
      const diasAConsultar = force ? days : faltantes;
      for (let i = 0; i < diasAConsultar.length; i++) {
        const day = diasAConsultar[i];
        setStatus(`Consultando faltante ${day} (${i + 1}/${diasAConsultar.length}). Se completan ${alcanceCarga} desde Oracle...`);
        const parcial = await api('/api/analisis-premio-productividad/consultar-rango', {
          method:'POST',
          body:JSON.stringify({fecha_desde:day, fecha_hasta:day, force, ...combo})
        });
        const detalleDia = parcial.meta?.detalle_dias || [];
        estados.push(...detalleDia);
        const estadoDia = detalleDia[0]?.estado || 'cache';
        const rowsDia = detalleDia[0]?.rows || 0;
        const opsDia = (detalleDia[0]?.operaciones || []).map(x => `${x.operacion}:${fmt(x.rows || 0)}`).join(' Â· ');
        setStatus(`${day} listo desde ${estadoDia === 'oracle' ? 'Oracle' : 'cache'} (${fmt(rowsDia)} registros${opsDia ? `; ${opsDia}` : ''}).`);
      }
      setStatus('Leyendo rango completo desde cache SQLite...');
      const data = await api('/api/analisis-premio-productividad/rango-cache?' + qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...combo}));
      data.meta = {
        ...(data.meta || {}),
        detalle_dias: estados,
        dias_oracle: estados.filter(x => x.estado === 'oracle').length,
        dias_cache: force ? estados.filter(x => x.estado === 'cache').length : cobertura.dias_cache,
      };
      state.loadError = '';
      state.detalleRows = await loadDetalleRowsForCurrentRange();
      renderResumen(data, state.detalleRows);
      state.hasConsulted = true;
      if (state.activeTab === 'grupal') renderPremioGrupal();
      if (state.activeTab === 'grupal-legajos') renderPremioGrupalLegajos();
      if (state.activeTab === 'detalle') await loadDetalle();
      if (state.activeTab === 'cache') await loadCache();
      const m = data.meta || {};
      setStatus(`Rango listo desde cache para ${alcanceCarga}. Dias: ${m.dias || 0}, desde Oracle: ${m.dias_oracle || 0}, ya cacheados: ${m.dias_cache || 0}.`);
      return true;
    } finally {
      setBusy(false);
    }
  }
  async function loadResumen(){
    const params = qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...comboParams()});
    const data = await api('/api/analisis-premio-productividad/rango-cache?' + params);
    state.detalleRows = await loadDetalleRowsForCurrentRange();
    renderResumen(data, state.detalleRows);
  }
  async function loadDetalleRowsForCurrentRange(){
    const params = qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...comboParams(), limit:0, compact:true});
    const detailData = await api('/api/analisis-premio-productividad/detalle-cache?' + params);
    return detailData.rows || [];
  }
  function renderResumen(data, detailRows=null){
    const k = data.kpis || {};
    const escenario = data.meta?.escenario_horario || '/6.5';
    const dias = data.meta?.dias || new Set((data.rows || []).map(row => String(row.fecha || '').slice(0,10)).filter(Boolean)).size || 1;
    const footTotal = productividadFoot(k.bultos, k.operarios, dias);
    const footTurno = productividadFoot(k.bultosturno, k.operarios, dias);
    const footExtra = productividadFoot(k.bultos_extra, k.operarios_extra, dias);
    const impactoExtraActual = Number(k.premio_anterior || 0) - Number(k.premio_actual || 0);
    const impactoExtraHoras = Number(k.premio_x_horas || 0) - Number(k.premio_x_horas_sin_extras || 0);
    const brechaConExtras = Number(k.premio_anterior || 0) - Number(k.premio_x_horas || 0);
    const brechaSinExtras = Number(k.premio_actual || 0) - Number(k.premio_x_horas_sin_extras || 0);
    state.resumenRows = data.rows || [];
    const incentivoGrupalRows = groupBonusSimulationRows(detailRows || state.detalleRows || []);
    const incentivoGrupal = incentivoGrupalRows.reduce((acc, row) => acc + Number(row.monto_fijo_objetivo_grupal || 0), 0);
    const finalConGrupal = Number(k.premio_x_horas_sin_extras || 0) + incentivoGrupal;
    $('kpis-resumen').innerHTML = [
      kpi('Actual jornada', money(k.premio_anterior), `Pago real neto del modulo. Base: ${footTotal}`),
      kpi('Actual sin extras', money(k.premio_actual), `Recalcula escala diaria solo con ${unidadProductivaLower()} del turno. Cae ${money(impactoExtraActual)} (${pctDiff(k.premio_anterior, impactoExtraActual)}).`, 'warn'),
      kpi('Extras en metodo actual', money(impactoExtraActual), `Actual jornada - Actual sin extras. Mide cuanto suma la produccion fuera del turno. ${footExtra}`, impactoExtraActual > 0 ? 'bad' : 'ok'),
      kpi(`Horas con extras ${escenario}`, money(k.premio_x_horas), `Suma premios por hora y aplica el mismo descuento monetario. Vs actual: ${signedMoney(-brechaConExtras)}.`, brechaConExtras < 0 ? 'bad' : 'ok'),
      kpi(`Horas sin extras ${escenario}`, money(k.premio_x_horas_sin_extras), `Solo horas dentro del turno. Vs actual sin extras: ${signedMoney(-brechaSinExtras)}.`, brechaSinExtras < 0 ? 'bad' : 'ok'),
      kpi(`Extras en metodo horario ${escenario}`, money(impactoExtraHoras), 'Horas con extras - Horas sin extras. Mide cuanto suman los tramos fuera del turno.', impactoExtraHoras > 0 ? 'warn' : 'ok'),
      kpi('Horas sin extras /6.5', money(k.premio_x_horas_sin_extras), 'Base individual del nuevo metodo, sin produccion extra.'),
      kpi('Incentivo grupal', money(incentivoGrupal), 'Suma del monto a pagar de incentivo grupal segun fijos diarios vigentes.', 'ok'),
      kpi('Suma final', money(finalConGrupal), 'Horas sin extras /6.5 + incentivo grupal.', finalConGrupal > Number(k.premio_actual || 0) ? 'warn' : 'ok'),
    ].join('');
    renderExecutiveCharts(data);
    renderCriticalReading(data);
    renderSuggestions(data, detailRows || state.detalleRows || []);
    $('validaciones').innerHTML = [
      'Resultado mostrado desde cache diaria pp_caso_modelo_dia. Oracle se consulta solo para dias faltantes.',
      `Escenario horario activo: escala ${escenario}. Los umbrales y premios por hora se recalculan con ese divisor.`,
      'TNC/error no se distribuye por hora: se estima el descuento monetario con el metodo actual y se aplica al escenario horario.',
      `La version sin extras del metodo actual usa ${unidadProductivaLower()} del turno contra la escala diaria vigente; la version horaria simplemente excluye horas fuera del turno.`
    ].map(x => `<li>${esc(x)}</li>`).join('');
  }
  function problematicaCols(){
    if (state.problematicaMode === 'horas_extra') return [
      {key:'fecha',label:'Fecha',mono:true,w:'92px'},
      {key:'operario',label:'Legajo',mono:true,w:'90px'},
      {key:'premio_actual',label:'Premio actual',money:true},
      {key:'premio_x_horas_sin_extras',label:'Premio horario turno',money:true},
      {key:'bultos_turno',label:`${unidadProductiva()} estandar`,num:true},
      {key:'bultos_fuera_turno',label:`${unidadProductiva()} extra`,num:true},
      {key:'pct_fuera_turno',label:'% extra',num:true},
      {key:'promedio_dentro_turno',label:'Prom est.',num:true},
      {key:'promedio_extra_activa',label:'Prom extra',num:true},
      {key:'diferencia_x_horas_sin_extras',label:'Diferencia',money:true},
      {key:'severidad',label:'Estado',w:'90px'},
    ];
    return [
      {key:'fecha',label:'Fecha',mono:true,w:'92px'},
      {key:'operario',label:'Legajo',mono:true,w:'90px'},
      {key:'premio_actual',label:'Premio actual',money:true},
      {key:'premio_x_horas_sin_extras',label:'Premio horario',money:true},
      {key:'hora_pico_label',label:'Pico',mono:true,w:'72px'},
      {key:'bultos_pico',label:`${unidadProductiva()} pico`,num:true},
      {key:'promedio_posterior',label:'Prom posterior',num:true},
      {key:'caida_posterior_pct',label:'Caida %',num:true},
      {key:'concentracion_pico_pct',label:'Concentracion %',num:true},
      {key:'severidad',label:'Estado',w:'90px'},
      {key:'detalle_origen',label:'Origen',w:'80px'},
    ];
  }
  function renderProblematicaChart(caso){
    if (!caso) {
      $('problematica-selected').innerHTML = '';
      $('problematica-chart').innerHTML = '<div class="empty">Sin casos para graficar.</div>';
      return;
    }
    const escala = caso.escala_premio_actual || caso.escala_objetivo || {};
    const escalaLabel = escala.label || '';
    const escalaMonto = Number(escala.premio_cobrado || escala.premio_diario || caso.premio_actual || 0);
    $('problematica-selected').innerHTML = [
      summaryCell('Caso', caso.titulo_caso || ''),
      summaryCell('Fecha', caso.fecha || ''),
      summaryCell('Legajo', caso.operario || ''),
      summaryCell('Pico', caso.hora_pico_label || ''),
      summaryCell(`${unidadProductiva()} pico`, caso.bultos_pico || 0, false, true),
      summaryCell('Prom posterior', caso.promedio_posterior || 0, false, true),
      summaryCell('Caida posterior', `${fmt(caso.caida_posterior_pct)}%`),
      summaryCell('Premio actual', escalaLabel ? `${escalaLabel} - ${money(escalaMonto)}` : money(escalaMonto)),
      summaryCell('Total cobrado', caso.premio_actual || 0, true),
      summaryCell('Premio horario', caso.premio_x_horas_sin_extras || 0, true),
      summaryCell('Diferencia', caso.diferencia_x_horas_sin_extras || 0, true),
      summaryCell('Horas sobre obj.', caso.resumen_modelo?.horas_sobre_objetivo_cobrado || 0, false, true),
      summaryCell('Horas sin premio h.', caso.resumen_modelo?.horas_sin_premio_horario || 0, false, true),
      summaryCell(`${unidadProductiva()} estandar`, caso.resumen_modelo?.bultos_dentro_turno || caso.bultos_turno || 0, false, true),
      summaryCell(`${unidadProductiva()} extra`, caso.resumen_modelo?.bultos_fuera_turno || 0, false, true),
      summaryCell('% extra', `${fmt(caso.resumen_modelo?.pct_fuera_turno || caso.pct_fuera_turno || 0)}%`),
    ].join('');
    const horas = (caso.horas || []).filter(x => Number(x.bultos || 0) > 0);
    if (!horas.length) {
      $('problematica-chart').innerHTML = `<div class="empty">Detalle horario pendiente para graficar. ${esc(caso.motivo || '')}</div>`;
      return;
    }
    const w = 1100, h = 320, left = 46, right = 18, top = 46, bottom = 54;
    const objetivo = Number(caso.objetivo_cobrado_hora || 0);
    const bandMax = Math.max(...horas.map(x => {
      const max = Number(x.bultos_hora_max || 0);
      return max > 10000 ? 0 : max;
    }), 0);
    const maxVal = Math.max(...horas.map(x => Number(x.bultos || 0)), objetivo, bandMax, 1);
    const plotW = w - left - right;
    const plotH = h - top - bottom;
    const xFor = idx => left + (horas.length === 1 ? plotW / 2 : idx * plotW / (horas.length - 1));
    const yFor = val => top + plotH - (Number(val || 0) / maxVal) * plotH;
    const points = horas.map((item, idx) => ({...item, x:xFor(idx), y:yFor(item.bultos_equilibrio ?? (item.bultos + item.equivalencia_extra))}));
    const allPolyline = points.map(p => `${p.x},${p.y}`).join(' ');
    const posteriorPoints = points.filter(p => p.es_pico || p.es_posterior);
    const posteriorPolyline = posteriorPoints.map(p => `${p.x},${p.y}`).join(' ');
    const yMid = yFor(maxVal / 2);
    const yObjetivo = yFor(objetivo);
    const step = horas.length > 1 ? plotW / (horas.length - 1) : plotW;
    const bandWidth = Math.max(18, step * .58);
    const bgSegments = [];
    if (modoCompensacion) {
      bgSegments.push({start:left, end:w - right, es_extra:false, label:'DistribuciÃ³n horaria'});
    } else points.forEach((p, idx) => {
      const start = idx === 0 ? left : (points[idx - 1].x + p.x) / 2;
      const end = idx === points.length - 1 ? w - right : (p.x + points[idx + 1].x) / 2;
      const last = bgSegments[bgSegments.length - 1];
      if (last && Boolean(last.es_extra) === Boolean(p.es_extra)) {
        last.end = end;
      } else {
        bgSegments.push({start, end, es_extra:p.es_extra, label:p.es_extra ? 'Extra' : 'Estandar'});
      }
    });
    const objetivoLabel = escalaMonto > 0
      ? `Premio actual: ${escalaLabel || 'escala actual'} - ${money(escalaMonto)}`
      : 'Premio actual';
    $('problematica-chart').innerHTML = `
      <svg class="problem-line-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Caida posterior al pico por hora">
        ${bgSegments.map(s => `<rect class="${s.es_extra ? 'extra-bg' : 'standard-bg'}" x="${s.start}" y="${top}" width="${s.end - s.start}" height="${plotH}"><title>${s.es_extra ? 'Horas extra / fuera del turno asignado' : 'Horas estandar / dentro del turno asignado'}</title></rect>`).join('')}
        ${bgSegments.map(s => `<text class="legend-label" x="${s.start + (s.end - s.start) / 2}" y="${top - 10}" text-anchor="middle">${s.label}</text>`).join('')}
        ${bgSegments.slice(1).map(s => `<line class="turno-cut" x1="${s.start}" y1="${top}" x2="${s.start}" y2="${top + plotH}"></line>`).join('')}
        <line class="grid" x1="${left}" y1="${top}" x2="${w - right}" y2="${top}"></line>
        <line class="grid" x1="${left}" y1="${yMid}" x2="${w - right}" y2="${yMid}"></line>
        <line class="axis" x1="${left}" y1="${top}" x2="${left}" y2="${h - bottom}"></line>
        <line class="axis" x1="${left}" y1="${h - bottom}" x2="${w - right}" y2="${h - bottom}"></line>
        <text class="axis-label" x="${left - 8}" y="${top + 4}" text-anchor="end">${fmt(maxVal)}</text>
        <text class="axis-label" x="${left - 8}" y="${yMid + 4}" text-anchor="end">${fmt(maxVal / 2)}</text>
        ${points.map(p => {
          const rawMax = Number(p.bultos_hora_max || 0);
          const max = rawMax > 10000 ? maxVal : Math.max(0, rawMax);
          if (!max) return '';
          const yTop = yFor(max);
          const yBottom = yFor(0);
          const premioHora = Number(p.premio_x_hora || 0);
          const montoLabel = money(premioHora);
          const maxLabel = rawMax > 10000 ? 'sin tope' : fmt(max);
          const labelY = Math.min(yBottom - 5, Math.max(top + 12, yTop + 14));
          return `<g>
            <rect class="hour-band" x="${p.x - bandWidth / 2}" y="${yTop}" width="${bandWidth}" height="${Math.max(2, yBottom - yTop)}"><title>Franja horaria de referencia 0-${maxLabel} b/h - ${montoLabel}</title></rect>
            <text class="hour-band-label" x="${p.x}" y="${labelY}" text-anchor="middle">${esc(montoLabel)}</text>
          </g>`;
        }).join('')}
        ${objetivo > 0 ? `<line class="line-objetivo" x1="${left}" y1="${yObjetivo}" x2="${w - right}" y2="${yObjetivo}"></line>
        <text class="legend-label" x="${w - right}" y="${Math.max(12, yObjetivo - 7)}" text-anchor="end">${esc(objetivoLabel)}</text>` : ''}
        <polyline class="line-main" points="${allPolyline}"></polyline>
        ${posteriorPoints.length > 1 ? `<polyline class="line-posterior" points="${posteriorPolyline}"></polyline>` : ''}
        ${points.map(p => {
          const caidaFuerte = p.es_posterior && Number(p.caida_vs_pico_pct || 0) >= 50;
          const cls = p.es_pico ? 'pico' : caidaFuerte ? 'caida' : p.es_extra ? 'extra' : p.es_posterior ? 'posterior' : 'pre';
          const title = `${p.hora_label}: ${fmt(p.bultos)} ${unidadProductivaLower()}${p.es_pico ? ' - pico' : p.es_posterior ? ` - caida ${fmt(p.caida_vs_pico_pct)}% vs pico` : ''}`;
          return `
            <circle class="point ${cls}" cx="${p.x}" cy="${p.y}" r="${p.es_pico ? 6 : 5}"><title>${esc(title)}</title></circle>
            <text class="label" x="${p.x}" y="${Math.max(12, p.y - 10)}" text-anchor="middle">${fmt(p.bultos)}</text>
            <text class="axis-label" x="${p.x}" y="${h - 16}" text-anchor="middle">${esc(p.hora_label)}</text>
          `;
        }).join('')}
        <text class="legend-label" x="${left}" y="14">Linea azul: produccion real por hora - Verde: estandar - Rojo: extra - Amarillo: escala horaria</text>
      </svg>`;
  }
  function renderProblematicaTable(rows){
    const cols = problematicaCols();
    const selected = Math.min(state.problematicaSelected || 0, Math.max(rows.length - 1, 0));
    state.problematicaSelected = selected;
    const emptyText = state.problematicaView === 'confirmados'
      ? 'Sin casos que superen la regla de caida posterior. Usa Candidatos analizados para ver la base revisada.'
      : state.problematicaView === 'pendientes'
        ? 'No hay candidatos pendientes de detalle.'
        : 'Sin candidatos analizados para los parametros actuales.';
    $('tabla-problematica').innerHTML = `<thead><tr>${cols.map(c => `<th style="${c.w ? `width:${c.w}` : ''}">${esc(c.label)}</th>`).join('')}</tr></thead><tbody>${rows.map((row,idx) => `<tr class="${idx === selected ? 'active' : ''}" data-index="${idx}">${cols.map(c => {
      const raw = row[c.key];
      const shown = c.money ? money(raw) : c.num ? fmt(raw) : esc(raw);
      const pill = c.key === 'severidad' ? `<span class="pill ${raw === 'Critico' ? 'bad' : raw === 'Revisar' ? 'warn' : ''}">${shown}</span>` : shown;
      return `<td class="${c.mono ? 'mono' : ''}" title="${esc(raw)}">${pill}</td>`;
    }).join('')}</tr>`).join('') || `<tr><td colspan="${cols.length}">${esc(emptyText)}</td></tr>`}</tbody>`;
    $('tabla-problematica').querySelectorAll('tbody tr[data-index]').forEach(tr => {
      tr.onclick = () => {
        state.problematicaSelected = Number(tr.dataset.index || 0);
        renderProblematicaTable(state.problematicaRows || []);
        renderProblematicaChart((state.problematicaRows || [])[state.problematicaSelected]);
      };
    });
    renderProblematicaChart(rows[selected]);
  }
  function setProblematicaView(view){
    state.problematicaView = view;
    state.problematicaRows = state.problematicaSets[view] || [];
    state.problematicaSelected = 0;
    renderProblematicaViewbar();
    renderProblematicaTable(state.problematicaRows);
  }
  function setProblematicaMode(mode){
    state.problematicaMode = mode;
    const modeData = state.problematicaModes[mode] || {};
    state.problematicaSets = {
      confirmados: modeData.casos || [],
      analizados: modeData.analizados || [],
      pendientes: state.problematicaModes.pendientes || [],
    };
    state.problematicaView = state.problematicaSets.confirmados.length ? 'confirmados' : state.problematicaSets.analizados.length ? 'analizados' : 'pendientes';
    renderProblematicaModebar();
    renderProblematicaKpis(modeData.kpis || {}, mode);
    setProblematicaView(state.problematicaView);
  }
  function renderProblematicaModebar(){
    const modes = state.problematicaModes || {};
    const items = [
      {key:'caida_inicio', label:'Caida inicio', count:(modes.caida_inicio?.casos || []).length},
      {key:'horas_extra', label:'Horas extra', count:(modes.horas_extra?.casos || []).length},
    ];
    $('problematica-modebar').innerHTML = items.map(item => `
      <button type="button" class="problem-view-btn ${state.problematicaMode === item.key ? 'active' : ''}" data-mode="${esc(item.key)}">
        ${esc(item.label)} (${fmt(item.count)})
      </button>
    `).join('');
    $('problematica-modebar').querySelectorAll('[data-mode]').forEach(btn => {
      btn.onclick = () => setProblematicaMode(btn.dataset.mode || 'caida_inicio');
    });
  }
  function renderProblematicaViewbar(){
    const sets = state.problematicaSets || {};
    const items = [
      {key:'confirmados', label:'Caida confirmada', count:(sets.confirmados || []).length},
      {key:'analizados', label:'Candidatos analizados', count:(sets.analizados || []).length},
      {key:'pendientes', label:'Pendientes detalle', count:(sets.pendientes || []).length},
    ];
    $('problematica-viewbar').innerHTML = items.map(item => `
      <button type="button" class="problem-view-btn ${state.problematicaView === item.key ? 'active' : ''}" data-view="${esc(item.key)}">
        ${esc(item.label)} (${fmt(item.count)})
      </button>
    `).join('');
    $('problematica-viewbar').querySelectorAll('[data-view]').forEach(btn => {
      btn.onclick = () => setProblematicaView(btn.dataset.view || 'confirmados');
    });
  }
  function renderProblematicaKpis(k, mode){
    const isExtra = mode === 'horas_extra';
    $('kpis-problematica').innerHTML = [
      kpi(isExtra ? 'Casos horas extra' : 'Casos con caida', fmt(k.casos_detectados), `${fmt(k.casos_analizados)} analizados`),
      kpi('Premio actual', money(k.premio_actual), 'Casos usados como ejemplo'),
      kpi('Premio horario turno', money(k.premio_x_horas_sin_extras), 'Dentro del turno asignado', 'warn'),
      kpi('Diferencia estimada', money(k.diferencia_estimada), 'Modelo actual vs horario', 'ok'),
      isExtra
        ? kpi('% extra prom.', `${fmt(k.pct_fuera_turno_promedio)}%`, 'Produccion fuera de turno', 'bad')
        : kpi('Caida prom.', `${fmt(k.caida_posterior_promedio)}%`, 'Posterior al pico', 'bad'),
      kpi('Candidatos', fmt(k.candidatos), 'Premio > $40.000, sin penalizaciones'),
      kpi('Detalle Oracle', fmt(k.detalle_oracle || 0), 'Consultas enriquecidas'),
      kpi('Detalle cache', fmt(k.detalle_cache || 0), 'Ya disponible'),
    ].join('');
  }
  async function loadProblematica(){
    setStatus('Buscando ejemplos de caida posterior al pico. Puede consultar Oracle para detalles faltantes...');
    const data = await api('/api/analisis-premio-productividad/problematica-modelo-actual?' + qs({
      fecha_desde:state.fechaDesde,
      fecha_hasta:state.fechaHasta,
      ...comboParams(),
      umbral_premio:40000,
      max_candidatos:40,
      caida_min_pct:50,
      concentracion_min_pct:0,
      min_bultos_turno:400,
    }));
    state.problematicaModes = data.modos || {
      caida_inicio: {casos:data.casos_confirmados || [], analizados:data.casos || [], kpis:data.kpis || {}},
      horas_extra: {casos:data.casos_horas_extra || [], analizados:data.casos_horas_extra || [], kpis:data.kpis_por_modo?.horas_extra || {}},
    };
    state.problematicaModes.pendientes = data.candidatos_pendientes || [];
    const defaultMode = (state.problematicaModes.caida_inicio?.casos || []).length ? 'caida_inicio' : 'horas_extra';
    setProblematicaMode(defaultMode);
    $('problematica-lectura').innerHTML = (data.lectura || []).map(x => `<li>${esc(x)}</li>`).join('');
    const sinDetalle = data.candidatos_sin_detalle || [];
    $('problematica-sin-detalle').innerHTML = sinDetalle.length
      ? sinDetalle.slice(0,8).map(x => `<li>${esc(x.fecha)} - legajo ${esc(x.operario)} - ${esc(x.motivo)}</li>`).join('')
      : '<li>Todos los candidatos priorizados tuvieron detalle horario disponible o fueron enriquecidos desde Oracle.</li>';
    const totalCandidatos = Number(data.kpis?.candidatos || 0);
    if (!totalCandidatos) {
      setStatus(`Sin candidatos para problematica en ${state.fechaDesde} a ${state.fechaHasta} (${state.operacion} / ${state.almacen}). ProbÃ¡ otro rango con premios mayores al umbral.`, true);
    }
  }
  function finalCols(){
    const escenario = '/6.5';
    return [
      {key:'fecha',label:'Fecha',mono:true,w:'92px'},
      {key:'operario',label:'Operario',mono:true,w:'100px',link:'detalle-legajo'},
      {key:'operacion',label:'Operacion'},
      {key:'bultos',label:unidadProductiva(),num:true},
      {key:'almacen',label:'Division'},
      {key:'descuentos_total',label:'Desc. TNC/error',money:true},
      {key:'premio_x_horas_bruto',label:`Premio horas ${escenario} bruto`,money:true},
      {key:'premio_x_horas',label:`Premio horas ${escenario} neto`,money:true},
      {key:'premio_x_horas_sin_extras_bruto',label:`Premio horas ${escenario} sin extras bruto`,money:true},
      {key:'premio_x_horas_sin_extras',label:`Premio horas ${escenario} sin extras neto`,money:true},
      {key:'productividad_anterior',label:'Prod anterior',num:true},
      {key:'premio_anterior',label:'Premio anterior neto',money:true},
      {key:'bultosturno',label:`${unidadProductiva()} turno`,num:true},
      {key:'premio_actual_bruto',label:'Premio sin extras bruto',money:true},
      {key:'premio_actual',label:'Premio sin extras neto',money:true},
      {key:'diferencia_x_horas',label:'Diferencia x horas',money:true},
      {key:'diferencia_sin_extras',label:'Diferencia sin extras',money:true},
      {key:'diferencia_x_horas_sin_extras',label:'Diferencia x horas sin extras',money:true},
    ];
  }
  function detalleLegajoCols(){
    const escenario = '/6.5';
    return [
      {key:'hora',label:'Hora',num:true,w:'70px'},
      {key:'turno',label:'Turno',w:'92px'},
      {key:'bultos',label:`${unidadProductiva()} + equiv. distribuida`,num:true},
      {key:'excedente_distribuido',label:'Excedente equiv. distribuido',num:true},
      {key:'sobrante_equilibrio',label:'Sobrante vs umbral',num:true},
      {key:'bultos_hora_min',label:'Min hora',num:true},
      {key:'bultos_hora_max',label:'Max hora',num:true},
      {key:'premio_x_hora',label:`Premio hora ${escenario}`,money:true},
      {key:'bultos_modulo',label:`${unidadProductiva()} modulo`,num:true},
    ];
  }
  function detalleCacheCols(){
    const escenario = '/6.5';
    return [
      {key:'fecha_base',label:'Fecha cache',mono:true,w:'102px'},
      {key:'legajo',label:'Legajo',mono:true,w:'90px'},
      {key:'hora',label:'Hora',num:true,w:'70px'},
      {key:'turno',label:'Turno',w:'92px'},
      {key:'operacion',label:'Operacion'},
      {key:'almacen',label:'Division'},
      {key:'bultos',label:unidadProductiva(),num:true},
      {key:'bultos_modulo',label:`${unidadProductiva()} modulo`,num:true},
      {key:'premio_x_hora',label:`Premio hora ${escenario}`,money:true},
      {key:'prod_modulo',label:'Prod modulo',num:true},
      {key:'pago_modulo',label:'Pago modulo',money:true},
      {key:'loaded_at',label:'Cacheado',mono:true,w:'150px'},
    ];
  }
  function summaryCell(label, value, moneyValue=false, numValue=false){
    const shown = moneyValue ? money(value) : numValue ? fmt(value) : value;
    return `<div class="summary-cell"><div class="label">${esc(label)}</div><strong title="${esc(shown)}">${esc(shown)}</strong></div>`;
  }
  function detalleTurnoStart(rows){
    return detalleTurnoStartInfo(rows).start;
  }
  function detalleTurnoStartInfo(rows){
    const turnos = new Set((rows || []).map(row => String(row.turno || '').toUpperCase().trim()).filter(Boolean));
    if ([...turnos].some(turno => turno.includes('NOCHE') || turno === 'TN' || turno === '3' || turno.includes('TURNO 3'))) return {start:22, known:true};
    if ([...turnos].some(turno => turno.includes('TARDE') || turno === '2' || turno.includes('TURNO 2'))) return {start:14, known:true};
    if ([...turnos].some(turno => turno.includes('MA') || turno.includes('MANANA') || turno === '1' || turno.includes('TURNO 1'))) return {start:6, known:true};
    return {start:0, known:false};
  }
  function detalleHoraOrden(row, startHour){
    const hora = Number(row.hora || 0);
    return ((hora - startHour) + 24) % 24;
  }
  function sortDetalleRows(rows){
    const startHour = detalleTurnoStart(rows);
    return [...(rows || [])].sort((a,b) => {
      const seq = detalleHoraOrden(a, startHour) - detalleHoraOrden(b, startHour);
      if (seq) return seq;
      return Number(a.hora || 0) - Number(b.hora || 0);
    });
  }
  function detalleStandardHours(rows){
    const info = detalleTurnoStartInfo(rows);
    if (info.known) return Array.from({length:8}, (_, idx) => (info.start + idx) % 24);
    return [...new Set((rows || [])
      .filter(row => Number(row.bultos_modulo || 0) > 0)
      .map(row => Number(row.hora))
      .filter(hora => Number.isFinite(hora)))]
      .sort((a,b) => detalleHoraOrden({hora:a}, info.start) - detalleHoraOrden({hora:b}, info.start));
  }
  function completarDetalleHoras(rows){
    const sorted = sortDetalleRows(rows).map(row => ({...row}));
    const standardHours = detalleStandardHours(sorted);
    if (!standardHours.length) return sorted;
    const standardSet = new Set(standardHours);
    sorted.forEach(row => {
      const hora = Number(row.hora);
      row.es_hora_estandar = standardSet.has(hora) || Number(row.bultos_modulo || 0) > 0;
    });
    const existingHours = new Set(sorted.map(row => Number(row.hora)).filter(hora => Number.isFinite(hora)));
    const template = sorted.find(row => Number(row.bultos_modulo || 0) > 0) || sorted[0] || {};
    standardHours.forEach(hora => {
      if (existingHours.has(hora)) return;
      sorted.push({
        ...template,
        hora,
        bultos:0,
        bultos_hora_min:0,
        bultos_hora_max:125,
        premio_x_hora:0,
        bultos_modulo:0,
        es_hora_estandar:true,
        hora_relleno:true,
      });
    });
    const objetivo = Number(sorted.find(row => Number(row.prod_modulo || 0) > 0)?.prod_modulo || 0) / 8;
    const horasEquilibrio = standardHours.length || sorted.length;
    const equivalenciasTotales = sorted.reduce((sum, row) => {
      if (row.hora_relleno) return sum;
      const raw = Number(row.bultos_reales);
      const total = Number(row.total_equivalentes);
      if (Number.isFinite(total) && total > 0) return sum + Math.max(0, total - (Number.isFinite(raw) ? raw : 0));
      const componentes = Number(row.equivalencia_sector || 0) + Number(row.equivalencia_traslado || 0) + Number(row.equivalencia_consolidacion || 0);
      if (componentes > 0) return sum + componentes;
      return sum + Math.max(0, Number(row.equivalencia_extra || 0));
    }, 0);
    const excedenteDistribuido = horasEquilibrio ? equivalenciasTotales / horasEquilibrio : 0;
    sorted.forEach(row => {
      const rawValue = Number(row.bultos_reales);
      const raw = Number.isFinite(rawValue) ? rawValue : Number(row.bultos || 0);
      row.bultos_reales = raw;
      row.excedente_distribuido = excedenteDistribuido;
      row.bultos_equilibrio = raw + excedenteDistribuido;
      row.bultos = row.bultos_equilibrio;
      row.sobrante_equilibrio = objetivo ? row.bultos_equilibrio - objetivo : 0;
      row.equivalencia_extra = excedenteDistribuido;
    });
    return sortDetalleRows(sorted);
  }
  function renderDetalleSummary(rows, kpis){
    const first = rows[0] || {};
    const turnos = [...new Set((rows || []).map(r => r.turno).filter(Boolean))].join(', ');
    $('detalle-summary').innerHTML = [
      summaryCell('Fecha', first.fecha || ''),
      summaryCell('Turno', turnos || first.turno || ''),
      summaryCell('Operario', first.operario || ''),
      summaryCell('Nombre', first.nombre || ''),
      summaryCell('Operacion', first.operacion || ''),
      summaryCell('Division', first.almacen || ''),
      summaryCell('Prod modulo', first.prod_modulo || 0, false, true),
      summaryCell('Pago modulo', first.pago_modulo || 0, true),
      summaryCell(`${unidadProductiva()} modulo`, kpis.bultos_modulo || 0, false, true),
      summaryCell(`${unidadProductiva()} turno`, kpis.bultosturno || 0, false, true),
      summaryCell('Premio sin extra', kpis.premio_sin_extra || first.premio_sin_extra || 0, true),
      summaryCell('Penalizacion TNC', kpis.penalizacion_tnc || first.penalizacion_tnc || ''),
      summaryCell('Penalizacion error', kpis.penalizacion_error || first.penalizacion_error || ''),
    ].join('');
  }
  function escalaActualFromRows(rows){
    const first = rows[0] || {};
    const productividad = Number(first.prod_modulo || 0);
    const pagoModulo = Number(first.pago_modulo || 0);
    let best = null;
    (rows || []).forEach(row => {
      const minHora = Number(row.bultos_hora_min || 0);
      const maxHora = Number(row.bultos_hora_max || 0);
      const premioHora = Number(row.premio_x_hora || 0);
      if (!premioHora && !pagoModulo) return;
      const minBultos = minHora * 8;
      const maxBultos = maxHora * 8;
      const maxCmp = maxHora >= 10000 ? Infinity : maxBultos;
      const premioDia = Number(row.pago_modulo || 0) || premioHora * 8;
      const matchesPremio = pagoModulo > 0 && Math.abs(premioDia - pagoModulo) < 1;
      const matchesProd = productividad > minBultos && productividad <= maxCmp;
      if ((matchesPremio || matchesProd) && (!best || (matchesPremio && matchesProd))) {
        best = {minBultos, maxBultos, premio:pagoModulo || premioDia};
      }
    });
    if (!best) return {label:'', premio:pagoModulo};
    const maxLabel = best.maxBultos >= 80000 ? 'sin tope' : fmt(best.maxBultos);
    return {label:`${fmt(best.minBultos)}-${maxLabel} ${unidadProductivaLower()}`, premio:best.premio};
  }
  function detalleExtraTransfers(points, objetivo, preserveSourceObjective=false){
    const balance = p => Number(p.bultos_equilibrio ?? p.bultos ?? 0);
    const standard = points.filter(p => balance(p) < objetivo);
    const extras = [];
    const standardSurplus = points.filter(p => balance(p) > objetivo)
      .sort((a,b) => balance(b) - balance(a));
    const transfers = [];
    const targetAdded = new Map();
    const sourceUsed = new Map();
    const standardSourceUsed = new Map();
    function useSources(target, sources, sourceKind, need){
      for (const source of sources) {
        if (need <= 0) break;
        if (source.idx === target.idx) continue;
        const used = sourceUsed.get(source.idx) || 0;
        const available = sourceKind === 'standard' || preserveSourceObjective
          ? Math.max(0, balance(source) - objetivo - used)
          : Math.max(0, balance(source) - used);
        if (!available) continue;
        const amount = Math.min(need, available);
        const added = targetAdded.get(target.idx) || 0;
        transfers.push({
          source,
          target,
          amount,
          sourceKind,
          targetBase:balance(target) + added,
          sourceBase:balance(source) - used,
        });
        targetAdded.set(target.idx, added + amount);
        sourceUsed.set(source.idx, used + amount);
        if (sourceKind === 'standard') standardSourceUsed.set(source.idx, (standardSourceUsed.get(source.idx) || 0) + amount);
        need -= amount;
      }
      return need;
    }
    standard.forEach(target => {
      const currentAdded = targetAdded.get(target.idx) || 0;
      let need = Math.max(0, objetivo - balance(target) - currentAdded);
      need = useSources(target, extras, 'extra', need);
      if (need > 0) useSources(target, standardSurplus, 'standard', need);
    });
    const leftover = extras.map(source => ({source, amount:Math.max(0, balance(source) - (preserveSourceObjective ? objetivo : 0) - (sourceUsed.get(source.idx) || 0))})).filter(x => x.amount > 0);
    return {transfers, leftover, targetAdded, standardSourceUsed, sourceUsed};
  }
  function renderDetalleLegajoChart(rows, animate=false, exportProgress=null, targetId='detalle-legajo-chart'){
    const chartTarget = $(targetId);
    if (targetId === 'detalle-legajo-chart') state.detalleChartRows = rows || [];
    const horas = (rows || [])
      .filter(row => row.hora !== undefined && row.hora !== null && row.hora !== '')
      .map((row, idx) => ({
        idx,
        hora_label: `${String(Number(row.hora || 0)).padStart(2, '0')}:00`,
        bultos: Number(row.bultos_reales ?? row.bultos ?? 0),
        equivalencia_extra: Number(row.excedente_distribuido ?? row.equivalencia_extra ?? 0),
        bultos_equilibrio: Number(row.bultos_equilibrio ?? row.bultos ?? 0),
        bultos_hora_max: Number(row.bultos_hora_max || 0),
        premio_x_hora: Number(row.premio_x_hora || 0),
        es_extra: row.es_hora_estandar === true ? false : Number(row.bultos_modulo || 0) <= 0,
        modo_compensacion: row.modo_compensacion === true,
      }));
    if (!horas.length) {
      if (chartTarget) chartTarget.innerHTML = '<div class="empty">Sin produccion horaria para graficar.</div>';
      return;
    }
    const w = 1100, h = 300, left = 46, right = 18, top = 44, bottom = 48;
    const escala = escalaActualFromRows(rows || []);
    const objetivo = Number((rows[0] || {}).prod_modulo || 0) / 8;
    const modoCompensacion = horas.some(row => row.modo_compensacion);
    const tieneEquivalentes = horas.some(row => row.equivalencia_extra > 0);
    const prePoints = horas.map((item, idx) => ({...item, x:0, y:0, idx}));
    const transferModel = detalleExtraTransfers(prePoints, objetivo, modoCompensacion);
    const inflatedMax = Math.max(...prePoints.map(p => Number(p.bultos_equilibrio ?? p.bultos ?? 0) + (transferModel.targetAdded.get(p.idx) || 0)), 0);
    const bandMax = Math.max(...horas.map(x => {
      const max = Number(x.bultos_hora_max || 0);
      return max > 10000 ? 0 : max;
    }), 0);
    const escalaActualDesde = Number((rows[0] || {}).escala_actual_desde || 0);
    const escalaActualHasta = Number((rows[0] || {}).escala_actual_hasta || 0);
    const escalaActualNivel = String((rows[0] || {}).escala_actual_nivel || '');
    const maxVal = Math.max(...horas.map(x => x.bultos + x.equivalencia_extra), ...horas.map(x => x.bultos), inflatedMax, objetivo, bandMax, escalaActualHasta, 1);
    const plotW = w - left - right;
    const plotH = h - top - bottom;
    const xFor = idx => left + (horas.length === 1 ? plotW / 2 : idx * plotW / (horas.length - 1));
    const yFor = val => top + plotH - (Number(val || 0) / maxVal) * plotH;
    const points = horas.map((item, idx) => ({...item, x:xFor(idx), y:yFor(item.bultos)}));
    const allPolyline = points.map(p => `${p.x},${p.y}`).join(' ');
    const yMid = yFor(maxVal / 2);
    const yObjetivo = yFor(objetivo);
    const step = horas.length > 1 ? plotW / (horas.length - 1) : plotW;
    const bandWidth = Math.max(18, step * .58);
    const prodBarWidth = Math.max(12, Math.min(34, step * .34));
    const bgSegments = [];
    points.forEach((p, idx) => {
      const start = idx === 0 ? left : (points[idx - 1].x + p.x) / 2;
      const end = idx === points.length - 1 ? w - right : (p.x + points[idx + 1].x) / 2;
      const last = bgSegments[bgSegments.length - 1];
      if (last && Boolean(last.es_extra) === Boolean(p.es_extra)) last.end = end;
      else bgSegments.push({start, end, es_extra:p.es_extra, label:p.es_extra ? (modoCompensacion ? 'Pico' : 'Extra') : (modoCompensacion ? 'Bajo umbral' : 'Estandar')});
    });
    const objetivoLabel = escala.premio > 0
      ? `Premio actual: ${escala.label || 'escala actual'} - ${money(escala.premio)}`
      : 'Premio actual';
    const transferModelFinal = detalleExtraTransfers(points, objetivo, modoCompensacion);
    const totalExtra = transferModelFinal.transfers.reduce((acc, item) => acc + item.amount, 0) + transferModelFinal.leftover.reduce((acc, item) => acc + item.amount, 0);
    const totalAsignadoExtra = transferModelFinal.transfers.filter(item => item.sourceKind === 'extra').reduce((acc, item) => acc + item.amount, 0);
    const totalAsignadoStandard = transferModelFinal.transfers.filter(item => item.sourceKind === 'standard').reduce((acc, item) => acc + item.amount, 0);
    const totalAsignado = totalAsignadoExtra + totalAsignadoStandard;
    const showTransfers = animate || exportProgress !== null;
    const totalRaw = points.reduce((sum, p) => sum + Number(p.bultos || 0), 0);
    const totalEquivalente = points.reduce((sum, p) => sum + Number(p.bultos_equilibrio ?? p.bultos ?? 0), 0);
    const residualEquivalente = objetivo > 0 ? totalEquivalente - objetivo * points.length : 0;
    const transferNote = objetivo > 0
      ? `${fmt(totalRaw)} bultos reales + ${fmt(totalEquivalente - totalRaw)} excedentes equiv. distribuidos (${fmt((totalEquivalente - totalRaw) / Math.max(1, points.length))}/hora) = ${fmt(totalEquivalente)} equivalentes Â· ${fmt(totalAsignadoStandard)} reasignados Â· remanente ${fmt(residualEquivalente)}`
      : 'No hay umbral horario para equilibrar';
    if (!chartTarget) return;
    chartTarget.innerHTML = `
      <div class="detalle-anim-head">
        <div class="detalle-anim-note">${esc(transferNote)}</div>
        <div class="detalle-anim-actions">
          <button type="button" class="secondary-cta" id="animar-detalle-extra" ${totalAsignado ? '' : 'disabled'}>Animar equilibrio</button>
          <button type="button" class="secondary-cta" id="exportar-detalle-gif" ${totalAsignado ? '' : 'disabled'}>Exportar GIF</button>
          <button type="button" class="secondary-cta" id="reset-detalle-extra">Original</button>
        </div>
      </div>
      <svg class="problem-line-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Produccion por hora del legajo">
        ${bgSegments.map(s => `<rect class="${s.es_extra ? 'extra-bg' : 'standard-bg'}" x="${s.start}" y="${top}" width="${s.end - s.start}" height="${plotH}"><title>${s.es_extra ? 'Horas extra / fuera del turno asignado' : 'Horas estandar / dentro del turno asignado'}</title></rect>`).join('')}
        ${bgSegments.map(s => `<text class="legend-label" x="${s.start + (s.end - s.start) / 2}" y="${top - 10}" text-anchor="middle">${s.label}</text>`).join('')}
        ${bgSegments.slice(1).map(s => `<line class="turno-cut" x1="${s.start}" y1="${top}" x2="${s.start}" y2="${top + plotH}"></line>`).join('')}
        <line class="grid" x1="${left}" y1="${top}" x2="${w - right}" y2="${top}"></line>
        <line class="grid" x1="${left}" y1="${yMid}" x2="${w - right}" y2="${yMid}"></line>
        <line class="axis" x1="${left}" y1="${top}" x2="${left}" y2="${h - bottom}"></line>
        <line class="axis" x1="${left}" y1="${h - bottom}" x2="${w - right}" y2="${h - bottom}"></line>
        <text class="axis-label" x="${left - 8}" y="${top + 4}" text-anchor="end">${fmt(maxVal)}</text>
        <text class="axis-label" x="${left - 8}" y="${yMid + 4}" text-anchor="end">${fmt(maxVal / 2)}</text>
        ${escalaActualHasta > escalaActualDesde ? `<rect class="hour-band" x="${left}" y="${yFor(escalaActualHasta)}" width="${plotW}" height="${Math.max(3, yFor(escalaActualDesde) - yFor(escalaActualHasta))}"><title>Escala cobrada de jornada /6,5: nivel ${escalaActualNivel || 'N/D'} Â· ${fmt(escalaActualDesde)} a ${fmt(escalaActualHasta)} bultos por hora</title></rect><text class="hour-band-label" x="${left + 6}" y="${Math.max(top + 14, yFor(escalaActualHasta) + 14)}">Escala cobrada /6,5 Â· nivel ${esc(escalaActualNivel || 'N/D')} Â· ${fmt(escalaActualDesde)}-${fmt(escalaActualHasta)}</text>` : ''}
        ${points.map(p => {
          const total = Number(p.bultos_equilibrio ?? (p.bultos + p.equivalencia_extra));
          const yTop = yFor(total);
          return `<rect class="prod-bar standard" x="${p.x - prodBarWidth / 2}" y="${yTop}" width="${prodBarWidth}" height="${Math.max(1, yFor(0) - yTop)}"><title>${esc(`${p.hora_label}: ${fmt(p.bultos)} reales + ${fmt(p.equivalencia_extra)} equivalentes = ${fmt(total)} ${unidadProductivaLower()} equivalentes`)} </title></rect>`;
        }).join('')}
        ${objetivo > 0 ? points.filter(p => !p.es_extra).map(p => `<line class="target-cap" x1="${p.x - prodBarWidth / 2 - 3}" y1="${yObjetivo}" x2="${p.x + prodBarWidth / 2 + 3}" y2="${yObjetivo}"></line>`).join('') : ''}
        ${showTransfers ? transferModelFinal.leftover.map(item => {
          const p = item.source;
          const used = (p.bultos_equilibrio ?? p.bultos) - item.amount;
          const yTop = yFor(p.bultos_equilibrio ?? p.bultos);
          const yBottom = yFor(used);
          return `<rect class="leftover-extra" x="${p.x - prodBarWidth / 2}" y="${yTop}" width="${prodBarWidth}" height="${Math.max(1, yBottom - yTop)}"><title>Extra sin reasignar: ${fmt(item.amount)} ${unidadProductivaLower()}</title></rect>`;
        }).join('') : ''}
        ${showTransfers ? points.filter(p => transferModelFinal.sourceUsed.get(p.idx)).map(p => {
          const amount = transferModelFinal.sourceUsed.get(p.idx) || 0;
          const yTop = yFor(p.bultos_equilibrio ?? p.bultos);
          const yBottom = yFor((p.bultos_equilibrio ?? p.bultos) - amount);
          return `<rect class="source-used" x="${p.x - prodBarWidth / 2}" y="${yTop}" width="${prodBarWidth}" height="${Math.max(1, yBottom - yTop)}"><title>Bultos reasignados desde ${esc(p.hora_label)}: ${fmt(amount)} ${unidadProductivaLower()}</title></rect>`;
        }).join('') : ''}
        ${points.map(p => {
          const rawMax = Number(p.bultos_hora_max || 0);
          const max = rawMax > 10000 ? maxVal : Math.max(0, rawMax);
          if (!max) return '';
          const rawMin = Number(p.bultos_hora_min || 0);
          const min = Math.max(0, Math.min(max, rawMin));
          const yTop = yFor(max);
          const yBottom = yFor(min);
          const montoLabel = money(Number(p.premio_x_hora || 0));
          const maxLabel = rawMax > 10000 ? 'sin tope' : fmt(max);
          const minLabel = fmt(min);
          const labelY = Math.min(yBottom - 5, Math.max(top + 12, yTop + 14));
          return `<g>
            <rect class="hour-band" x="${p.x - bandWidth / 2}" y="${yTop}" width="${bandWidth}" height="${Math.max(2, yBottom - yTop)}"><title>Rango de escala ${minLabel}-${maxLabel} bultos - ${montoLabel}</title></rect>
            <text class="hour-band-label" x="${p.x}" y="${labelY}" text-anchor="middle">${esc(montoLabel)}</text>
          </g>`;
        }).join('')}
        ${showTransfers ? transferModelFinal.transfers.map((item, idx) => {
          const finalTop = yFor(item.targetBase + item.amount);
          const finalBottom = yFor(item.targetBase);
          const sourceTop = yFor(item.sourceBase);
          const fromX = item.source.x - item.target.x;
          const fromY = sourceTop - finalTop;
          const frameProgress = exportProgress === null ? null : Math.max(0, Math.min(1, (exportProgress - idx * 0.035) / 0.72));
          const eased = frameProgress === null ? null : 1 - Math.pow(1 - frameProgress, 3);
          const transform = eased === null ? '' : ` transform="translate(${fromX * (1 - eased)} ${fromY * (1 - eased)})"`;
          const cls = `${animate && exportProgress === null ? 'transfer-segment animating' : 'transfer-segment'} ${item.sourceKind === 'standard' ? 'from-standard' : ''}`;
          const sourceLabel = item.sourceKind === 'standard' ? (modoCompensacion ? 'excedente bajo umbral' : 'excedente estandar') : (modoCompensacion ? 'pico' : 'extra');
          return `<rect class="${cls}" style="--from-x:${fromX}px;--from-y:${fromY}px;animation-delay:${idx * 90}ms" x="${item.target.x - prodBarWidth / 2}" y="${finalTop}" width="${prodBarWidth}" height="${Math.max(2, finalBottom - finalTop)}"${transform}><title>${fmt(item.amount)} ${unidadProductivaLower()} ${sourceLabel} de ${esc(item.source.hora_label)} montados sobre ${esc(item.target.hora_label)}</title></rect>`;
        }).join('') : ''}
        ${objetivo > 0 ? `<line class="line-objetivo" x1="${left}" y1="${yObjetivo}" x2="${w - right}" y2="${yObjetivo}"></line>
        <text class="legend-label" x="${w - right}" y="${Math.max(12, yObjetivo - 7)}" text-anchor="end">${esc(objetivoLabel)}</text>` : ''}
        <polyline class="line-main" points="${allPolyline}"></polyline>
        ${points.map(p => `
          <circle class="point ${p.es_extra ? 'extra' : 'pre'}" cx="${p.x}" cy="${p.y}" r="5"><title>${esc(`${p.hora_label}: ${fmt(p.bultos)} ${unidadProductivaLower()}`)}</title></circle>
          <text class="label" x="${p.x}" y="${Math.max(12, p.y - 10)}" text-anchor="middle">${fmt(p.bultos + p.equivalencia_extra)} eq.</text>
          <text class="axis-label" x="${p.x}" y="${h - 14}" text-anchor="middle">${esc(p.hora_label)}</text>
        `).join('')}
        <text class="legend-label" x="${left}" y="14">${modoCompensacion ? 'Azul: bultos + equivalencia - Naranja: reasignado durante el equilibrio - Verde: umbral horario' : 'Azul: bultos + equivalencia - Naranja: reasignado - Verde: objetivo horario'}</text>
      </svg>`;
    $('animar-detalle-extra').onclick = () => renderDetalleLegajoChart(rows || [], true, null, targetId);
    $('exportar-detalle-gif').onclick = () => targetId === 'detalle-legajo-chart' ? exportarDetalleGif().catch(e => setStatus(e.message, true)) : setStatus('La exportaciÃ³n GIF estÃ¡ disponible desde Datos.', true);
    $('reset-detalle-extra').onclick = () => renderDetalleLegajoChart(rows || [], false, null, targetId);
  }
  const detalleGifSvgStyle = `
    .grid{stroke:#D4DBD8;stroke-width:1;opacity:.75}.axis{stroke:#A9B4AC;stroke-width:1}
    .standard-bg{fill:#DDEEE3;opacity:.82}.extra-bg{fill:#F4DDE0;opacity:.82}
    .turno-cut{stroke:#5C6773;stroke-width:1.5;stroke-dasharray:5 4;opacity:.85}
    .hour-band{fill:#FBE7C8;stroke:#E1BF76;stroke-width:1;opacity:.55}
    .hour-band-label{font-family:'IBM Plex Mono',monospace;font-size:10px;fill:#6F4300;paint-order:stroke;stroke:#FFFFFF;stroke-width:3px;stroke-linejoin:round}
    .line-main{fill:none;stroke:#0B5FAE;stroke-width:3;stroke-linejoin:round;stroke-linecap:round}
    .line-objetivo{stroke:#1F7A4D;stroke-width:2.5;stroke-dasharray:8 5}
    .point{stroke:#FFFFFF;stroke-width:3}.point.pre{fill:#1F7A4D}.point.extra{fill:#C8102E}
    .prod-bar{stroke:#FFFFFF;stroke-width:1.5;opacity:.72}.prod-bar.standard{fill:#0B5FAE}.prod-bar.extra{fill:#C8102E}
    .transfer-segment{fill:#B25F00;stroke:#6F4300;stroke-width:.8;opacity:.9}.transfer-segment.from-standard{fill:#E8A23A;stroke:#6F4300;stroke-dasharray:3 2}
    .leftover-extra{fill:#C8102E;opacity:.45;stroke:#C8102E;stroke-width:1}.source-used{fill:#FFFFFF;stroke:#0B5FAE;stroke-width:1;stroke-dasharray:3 2;opacity:.52}
    .target-cap{stroke:#1F7A4D;stroke-width:2;stroke-dasharray:3 3}
    .label{font-family:'IBM Plex Mono',monospace;font-size:11px;fill:#0E1620;paint-order:stroke;stroke:#FFFFFF;stroke-width:3px;stroke-linejoin:round}
    .equiv-label{font-family:'IBM Plex Mono',monospace;font-size:10px;fill:#4C1D95;font-weight:700;paint-order:stroke;stroke:#FFFFFF;stroke-width:3px;stroke-linejoin:round}
    .axis-label,.legend-label{font-family:'IBM Plex Mono',monospace;font-size:10px;fill:#5C6773}
  `;
  function currentDetalleSvgForExport(){
    const svg = $('detalle-legajo-chart').querySelector('svg');
    if (!svg) throw new Error('No hay grafico de detalle para exportar.');
    const clone = svg.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', '1280');
    clone.setAttribute('height', '349');
    const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    bg.setAttribute('x', '0'); bg.setAttribute('y', '0'); bg.setAttribute('width', '1100'); bg.setAttribute('height', '300'); bg.setAttribute('fill', '#FFFFFF');
    clone.insertBefore(bg, clone.firstChild);
    const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    style.textContent = detalleGifSvgStyle;
    clone.insertBefore(style, clone.firstChild);
    return new XMLSerializer().serializeToString(clone);
  }
  function svgMarkupToPngData(markup, width=1280, height=349){
    return new Promise((resolve, reject) => {
      const img = new Image();
      const blob = new Blob([markup], {type:'image/svg+xml;charset=utf-8'});
      const url = URL.createObjectURL(blob);
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);
        URL.revokeObjectURL(url);
        resolve(canvas.toDataURL('image/png'));
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('No se pudo rasterizar el SVG.')); };
      img.src = url;
    });
  }
  async function exportarDetalleGif(){
    const rows = state.detalleChartRows || [];
    if (!rows.length) throw new Error('AbrÃ­ un detalle de legajo antes de exportar.');
    const btn = $('exportar-detalle-gif');
    btn.disabled = true;
    btn.textContent = 'Generando...';
    setStatus('Generando frames del GIF...');
    try {
      const frames = [];
      const frameCount = 32;
      for (let i = 0; i < frameCount; i++) {
        const progress = i / (frameCount - 1);
        renderDetalleLegajoChart(rows, false, progress);
        await new Promise(resolve => requestAnimationFrame(resolve));
        frames.push(await svgMarkupToPngData(currentDetalleSvgForExport()));
      }
      renderDetalleLegajoChart(rows, false);
      setStatus('Armando GIF para PowerPoint...');
      const first = rows[0] || {};
      const filename = `detalle-legajo-${first.operario || 'legajo'}-impacto-extras.gif`;
      const res = await fetch('/api/analisis-premio-productividad/exportar-gif', {
        credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        method:'POST',
        body:JSON.stringify({frames, duration_ms:85, filename})
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'No se pudo exportar el GIF.');
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus(`GIF exportado: ${filename}`);
    } catch (e) {
      renderDetalleLegajoChart(rows, false);
      throw e;
    } finally {
      const fresh = $('exportar-detalle-gif');
      if (fresh) {
        fresh.disabled = false;
        fresh.textContent = 'Exportar GIF';
      }
    }
  }
  async function cargarDetalleLegajo(fecha, legajo){
    if (state.loading) return;
    setBusy(true);
    $('detalle-modal').classList.add('active');
    $('detalle-title').textContent = `Detalle legajo ${legajo}`;
    $('detalle-status').textContent = 'Consultando cache...';
    try {
      const data = await api('/api/analisis-premio-productividad/detalle-legajo?' + qs({fecha, legajo, ...comboParams()}));
      const detalleRows = completarDetalleHoras(data.rows || []);
      renderDetalleSummary(detalleRows, data.kpis || {});
      renderDetalleLegajoChart(detalleRows);
      table('tabla-detalle-legajo', detalleLegajoCols(), detalleRows);
      const m = data.meta || {}; const k = data.kpis || {};
      $('detalle-status').textContent = `${esc(m.fecha)} Â· ${esc(m.origen)} Â· hora ${esc(m.escenario_horario || '/6.5')} Â· ${fmt(k.horas)} horas Â· ${fmt(k.bultos)} ${unidadProductivaLower()}`;
      setStatus(`Detalle ${legajo} cargado desde ${m.origen === 'oracle' ? 'Oracle y cacheado' : 'cache'}.`);
    } finally {
      setBusy(false);
    }
  }
  function cerrarDetalle(){
    if (state.loading) return;
    $('detalle-modal').classList.remove('active');
  }
  function filterDataRows(rows){
    const fecha = $('detalle-f-fecha').value;
    const legajo = $('detalle-f-legajo').value.trim();
    return (rows || []).filter(row => {
      const okFecha = !fecha || String(row.fecha_base || row.fecha || '').slice(0,10) === fecha;
      const okLegajo = !legajo || String(row.legajo || row.operario || '').includes(legajo);
      return okFecha && okLegajo;
    });
  }
  function renderDetalleCacheGrid(){
    const resumenRows = filterDataRows(state.detalleResumenRows);
    const detailRows = filterDataRows(state.detalleGridRows);
    table('tabla-datos-resumen', finalCols(), resumenRows, {maxRows:1000});
    table('tabla-detalle-cache', detalleCacheCols(), detailRows, {maxRows:1000});
    const totalResumen = state.detalleResumenRows.length;
    const totalDetalle = state.detalleGridTotal || state.detalleGridRows.length;
    const visibleResumen = Math.min(resumenRows.length, 1000);
    const visibleDetalle = Math.min(detailRows.length, 1000);
    const fecha = $('detalle-f-fecha').value;
    const legajo = $('detalle-f-legajo').value.trim();
    const filtros = [fecha ? `fecha ${fecha}` : '', legajo ? `legajo ${legajo}` : ''].filter(Boolean).join(' Â· ');
    $('detalle-filter-info').textContent = filtros
      ? `Mostrando ${fmt(visibleResumen)}/${fmt(totalResumen)} resumen y ${fmt(visibleDetalle)}/${fmt(totalDetalle)} detalle - ${filtros}`
      : `Mostrando hasta ${fmt(visibleResumen)} resumen y ${fmt(visibleDetalle)}/${fmt(totalDetalle)} detalle`;
  }
  async function loadDetalle(){
    const params = qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...comboParams()});
    const detailParams = qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...comboParams(), limit:5000, offset:0});
    const resumenData = await api('/api/analisis-premio-productividad/rango-cache?' + params);
    const data = await api('/api/analisis-premio-productividad/detalle-cache?' + detailParams);
    const detailDate = $('detalle-f-fecha').value;
    if (detailDate && (detailDate < state.fechaDesde || detailDate > state.fechaHasta)) $('detalle-f-fecha').value = '';
    state.detalleResumenRows = resumenData.rows || [];
    state.detalleGridRows = data.rows || [];
    state.detalleGridTotal = Number(data.total || state.detalleGridRows.length);
    renderDetalleCacheGrid();
  }
  async function loadCache(){
    const data = await api('/api/analisis-premio-productividad/datos-cache?' + qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta, ...comboParams()}));
    const c = data.counts || {};
    const coverage = data.coverage || {};
    const versions = data.query_versions || {};
    const procesos = data.procesos || [];
    $('cache-info').innerHTML = `<table class="paper-table"><tbody>
      <tr><th>Rango</th><td>${esc(data.fecha_desde)} a ${esc(data.fecha_hasta)}</td></tr>
      <tr><th>Operacion / Division</th><td>${esc(data.operacion || state.operacion)} / ${esc(data.almacen || state.almacen)}</td></tr>
      <tr><th>Estado</th><td><span class="pill ${coverage.dias_faltantes ? 'warn' : ''}">${coverage.dias_faltantes ? 'INCOMPLETO' : 'OK'}</span></td></tr>
      <tr><th>Cobertura diaria</th><td>${fmt(coverage.dias_cache || 0)} / ${fmt(coverage.dias || 0)} dias cacheados${coverage.faltantes?.length ? ` Â· faltantes: ${esc(coverage.faltantes.join(', '))}` : ''}</td></tr>
      <tr><th>Versiones</th><td>Dia: <span class="mono">${esc(versions.dia)}</span> Â· Detalle: <span class="mono">${esc(versions.detalle)}</span></td></tr>
      <tr><th>Base SQLite</th><td class="mono">${esc(data.db_path || '')}</td></tr>
      ${Object.entries(c).map(([k,v]) => `<tr><th>${esc(k)}</th><td class="mono">${esc(v)}</td></tr>`).join('')}
    </tbody></table>`;
    $('cache-info').insertAdjacentHTML('beforeend', `<ul class="notes" style="margin-top:12px">${procesos.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`);
  }
  function syncFormValues(source, clone){
    const sourceControls = source.querySelectorAll('input,select,textarea');
    const cloneControls = clone.querySelectorAll('input,select,textarea');
    sourceControls.forEach((control, idx) => {
      const target = cloneControls[idx];
      if (!target) return;
      if (control.tagName === 'SELECT') {
        target.value = control.value;
        Array.from(target.options).forEach(opt => { opt.selected = opt.value === control.value; });
      } else {
        target.setAttribute('value', control.value || '');
        target.value = control.value || '';
      }
    });
  }
  function removePrintControls(root){
    root.querySelectorAll('button,a.paper-link,.logout-btn,.primary-cta,.secondary-cta,.icon-btn,.tab-btn,.tool-row,.header-right').forEach(el => el.remove());
  }
  function printHtmlDocument(title, contentHtml, mode='resumen'){
    const win = window.open('', '_blank', 'width=1400,height=900');
    if (!win) throw new Error('El navegador bloqueo la ventana de impresion.');
    const baseStyle = document.querySelector('style')?.textContent || '';
    const printStyle = `
      @page{size:A4 landscape;margin:8mm}
      html,body{background:#FFFFFF!important}
      body{min-height:auto!important;background-image:none!important;color:#0E1620!important}
      .paper-app{min-height:auto!important;padding:0!important;width:100%!important}
      .paper-header,.filters,.status,.chart-panel,.text-panel,.kpi-cell,.data-panel,.modal-head,.modal-panel{break-inside:avoid;box-shadow:none!important}
      .paper-tabs,.header-right,.tool-row,button,.paper-link,.logout-btn,.primary-cta,.secondary-cta,.icon-btn{display:none!important}
      .paper-panel{display:block!important}
      .kpi-row{grid-template-columns:repeat(3,1fr)!important;gap:8px!important;margin:8px 0!important}
      .executive-grid,.dashboard-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:8px!important;margin-top:8px!important}
      .executive-wide{grid-column:1/-1!important}
      .chart-panel,.text-panel{min-height:0!important;padding:9px!important}
      .kpi-cell{min-height:82px!important;padding:8px 10px!important}
      .kpi-number{font-size:20px!important}
      .case-card-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}
      .modal-backdrop{display:block!important;position:static!important;background:#FFFFFF!important;padding:0!important}
      .modal-panel{width:100%!important;max-height:none!important;border:0!important;display:block!important}
      .modal-body{overflow:visible!important;padding:8px 0 0!important}
      .modal-summary{grid-template-columns:repeat(6,minmax(95px,1fr))!important}
      .detalle-chart{height:auto!important;min-height:310px!important;overflow:visible!important}
      .detalle-chart .problem-line-chart{height:auto!important}
      .table-wrap,.modal-body .table-wrap{max-height:none!important;overflow:visible!important}
      .paper-table{font-size:10px!important;page-break-inside:auto!important}
      .paper-table tr{break-inside:avoid!important}
      .paper-table th,.paper-table td{padding:5px 6px!important}
      .print-meta{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#5C6773;margin:0 0 8px}
      ${mode === 'detalle' ? '.paper-table{table-layout:auto!important}.problem-chart{border-left:0!important;border-bottom:0!important}' : ''}
    `;
    win.document.open();
    win.document.write(`<!doctype html><html lang="es"><head><meta charset="utf-8"><title>${esc(title)}</title><style>${baseStyle}</style><style>${printStyle}</style></head><body>${contentHtml}</body></html>`);
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 500);
  }
  function exportarResumenPdf(){
    const wrapper = document.createElement('div');
    wrapper.className = 'paper-app';
    const header = document.querySelector('.paper-header').cloneNode(true);
    const filters = document.querySelector('.filters').cloneNode(true);
    syncFormValues(document.querySelector('.filters'), filters);
    const status = $('status').cloneNode(true);
    const panel = $('panel-resumen').cloneNode(true);
    panel.classList.add('active');
    [header, filters, panel].forEach(removePrintControls);
    const meta = document.createElement('div');
    meta.className = 'print-meta';
    meta.textContent = `Exportado ${new Date().toLocaleString('es-AR')} - Rango ${state.fechaDesde} a ${state.fechaHasta} - ${state.operacion} / ${state.almacen} - Escenario hora /6.5`;
    wrapper.append(header, filters, status, meta, panel);
    printHtmlDocument('Analisis Premio Productividad - Resumen', wrapper.outerHTML, 'resumen');
  }
  function exportarDetallePdf(){
    const modal = $('detalle-modal');
    if (!modal.classList.contains('active') || !(state.detalleChartRows || []).length) {
      setStatus('Abri un detalle horario antes de exportar el PDF.', true);
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'modal-backdrop active';
    const panel = modal.querySelector('.modal-panel').cloneNode(true);
    removePrintControls(panel);
    const meta = document.createElement('div');
    meta.className = 'print-meta';
    const first = (state.detalleChartRows || [])[0] || {};
    meta.textContent = `Exportado ${new Date().toLocaleString('es-AR')} - Fecha ${first.fecha || ''} - Legajo ${first.operario || ''}`;
    panel.querySelector('.modal-body')?.prepend(meta);
    wrapper.append(panel);
    const title = $('detalle-title').textContent || 'Detalle por legajo';
    printHtmlDocument(`Analisis Premio Productividad - ${title}`, wrapper.outerHTML, 'detalle');
  }
  function renderFijosGrupalModal(){
    const almacenes = Object.keys(GROUP_FIXED_BY_DIVISION_DEFAULTS);
    $('fijos-grupal-title').textContent = `Editar fijos diarios ${state.operacion} por division`;
    $('fijos-grupal-body').innerHTML = almacenes.map(almacen => {
      const key = groupFixedKey(almacen);
      return `
      <tr>
        <td class="mono">${esc(almacen)}</td>
        <td><input class="paper-input" data-fixed-key="${esc(key)}" type="number" min="0" step="1000" value="${Number(state.groupFixedDaily[key] ?? GROUP_FIXED_DEFAULTS[key] ?? 0)}"></td>
      </tr>`;
    }).join('');
  }
  function abrirFijosGrupal(){
    renderFijosGrupalModal();
    $('fijos-grupal-modal').classList.add('active');
  }
  function cerrarFijosGrupal(){
    $('fijos-grupal-modal').classList.remove('active');
  }
  function aplicarFijosGrupal(){
    $('fijos-grupal-body').querySelectorAll('input[data-fixed-key]').forEach(input => {
      const key = input.dataset.fixedKey;
      state.groupFixedDaily[key] = Math.max(0, Number(input.value || 0));
    });
    cerrarFijosGrupal();
    if (state.activeTab === 'grupal') renderPremioGrupal();
    if (state.activeTab === 'grupal-legajos') renderPremioGrupalLegajos();
    setStatus(`Fijos diarios actualizados para ${state.operacion}.`);
  }
  function restaurarFijosGrupal(){
    state.groupFixedDaily = {...GROUP_FIXED_DEFAULTS};
    renderFijosGrupalModal();
    if (state.activeTab === 'grupal') renderPremioGrupal();
    if (state.activeTab === 'grupal-legajos') renderPremioGrupalLegajos();
    setStatus('Fijos diarios restaurados a los valores default.');
  }
  function aplicarMargenGrupal(value){
    const next = Number(value);
    state.groupMarginPct = Number.isFinite(next) ? clamp(next, 0, 200) : 90;
    if (state.activeTab === 'grupal') renderPremioGrupal();
    else if (state.activeTab === 'grupal-legajos') renderPremioGrupalLegajos();
    else if (state.activeTab === 'resumen') loadResumen().catch(e => setStatus(e.message, true));
  }
  function renderPunto0(){
    const data = state.punto0;
    if (!data) {
      $('kpis-punto0').innerHTML = kpi('Punto 0', 'No calculado', 'PresionÃ¡ recalcular para publicar el rango.', 'warn');
      $('tabla-punto0').innerHTML = '<tbody><tr><td>El rango todavÃ­a no tiene una corrida congelada.</td></tr></tbody>';
      return;
    }
    const m = data.meta || {};
    $('kpis-punto0').innerHTML = [
      kpi('Estado', m.status || 'PUBLISHED', `${data.run_id || ''}`, 'ok'),
      kpi('Pago actual', money(m.pago_actual_total), 'referencia oficial cacheada'),
      kpi('Premio individual', money(m.premio_individual_total), 'escala sectorial vigente', 'ok'),
      kpi('Bolsa grupal', money(m.bolsa_grupal), 'distribuciÃ³n por bultos y horas', 'warn'),
      kpi('Filas', fmt(m.rows ?? m.rows_count ?? 0), `${fmt(m.legajos ?? m.legajos_count ?? 0)} legajos`),
    ].join('');
    $('punto0-meta').textContent = `${m.fecha_desde || state.fechaDesde} a ${m.fecha_hasta || state.fechaHasta} Â· snapshot ${m.snapshot_id || '-'} Â· validaciÃ³n ${Math.abs(Number(m.actual_diff || 0)) <= .05 ? 'OK' : 'REVISAR'}`;
    table('tabla-punto0', [
      {key:'fecha_base',label:'Fecha',mono:true}, {key:'legajo',label:'Legajo',mono:true}, {key:'sector',label:'Sector'}, {key:'turno',label:'Turno'},
      {key:'bultos_reales',label:'Bultos reales',num:true}, {key:'horas',label:'Horas',num:true}, {key:'premio_actual',label:'Pago actual',money:true},
      {key:'premio_individual',label:'Individual P0',money:true}, {key:'adicional_grupal_bultos',label:'Grupal bultos',money:true}, {key:'pago_final_bultos',label:'Final bultos',money:true},
      {key:'adicional_grupal_horas',label:'Grupal horas',money:true}, {key:'pago_final_horas',label:'Final horas',money:true},
    ], data.rows || [], {maxRows:2000});
  }
  async function loadPunto0(){
    state.fechaDesde = $('rango-desde').value; state.fechaHasta = $('rango-hasta').value;
    try {
      state.punto0 = await api('/api/analisis-premio-productividad/punto0?' + qs({fecha_desde:state.fechaDesde, fecha_hasta:state.fechaHasta}));
      renderPunto0();
    } catch (e) {
      state.punto0 = null; renderPunto0();
      if (!String(e.message || '').includes('todavÃ­a no fue calculado')) throw e;
      setStatus('El Punto 0 no estÃ¡ calculado para este rango. PodÃ©s publicarlo con el botÃ³n de la solapa.', true);
    }
  }
  async function recalcularPunto0(){
    if (state.punto0Loading) return;
    state.punto0Loading = true; $('punto0-recalcular').disabled = true; $('punto0-recalcular').textContent = 'Calculando...';
    try {
      const fechaDesde = $('rango-desde').value, fechaHasta = $('rango-hasta').value;
      setStatus('Calculando y validando Punto 0 desde cache local...');
      await api('/api/analisis-premio-productividad/punto0/recalcular', {method:'POST', body:JSON.stringify({fecha_desde:fechaDesde, fecha_hasta:fechaHasta, force:false})});
      await loadPunto0();
      setStatus('Punto 0 publicado y congelado para el rango seleccionado.');
    } finally {
      state.punto0Loading = false; $('punto0-recalcular').disabled = false; $('punto0-recalcular').textContent = 'Recalcular / publicar Punto 0';
    }
  }
  function scenarioSectorNames(){
    const source=state.tablaPremios||{}; const rows=source.escalas_sector_hora||[]; const names=[...new Set(rows.map(row=>String(row.sector||'').trim()).filter(Boolean))];
    return names.sort((a,b)=>a.localeCompare(b,'es'));
  }
  function renderScenarioEditor(){
    const target=$('tabla-scenario-sectores'); if(!target) return;
    const rows=state.scenarioSectors||[];
    target.innerHTML=`<thead><tr><th>Sector</th><th>Grupo productivo</th><th>Aumento premio %</th><th>Ajuste umbral %</th><th>Uso</th></tr></thead><tbody>${rows.map((row,index)=>`<tr><td class="mono">${esc(row.sector)}</td><td>${esc(row.grupo||'-')}</td><td><input class="scenario-editor-input" data-scenario-index="${index}" data-scenario-field="premio_pct" type="number" min="-100" max="300" step="5" value="${Number(row.premio_pct||0)}"></td><td><input class="scenario-editor-input" data-scenario-index="${index}" data-scenario-field="umbral_pct" type="number" min="-90" max="90" step="5" value="${Number(row.umbral_pct||0)}"></td><td>${row.premio_pct||row.umbral_pct ? '<span class="pill warn">Ajustado</span>' : '<span class="pill">Base</span>'}</td></tr>`).join('')||'<tr><td colspan="5">Cargando sectores...</td></tr>'}</tbody>`;
    target.querySelectorAll('[data-scenario-index]').forEach(input=>input.oninput=()=>{const item=state.scenarioSectors[Number(input.dataset.scenarioIndex)]; if(item) item[input.dataset.scenarioField]=Number(input.value||0); renderScenarioEditor();});
  }
  function loadDefaultScenarioSectors(){
    const critical=new Set(['B1','AM','PI','N1','VA']);
    state.scenarioSectors=scenarioSectorNames().map(sector=>{const meta=(state.tablaPremios?.sectores||[]).find(row=>String(row.sector||'').trim()===sector)||{}; return {sector,grupo:meta.grupo_productivo||'',premio_pct:critical.has(sector)?30:0,umbral_pct:0};});
    renderScenarioEditor(); $('scenario-status').textContent='Propuesta cargada: +30% en B1, AM, PI, N1 y VA.';
  }
  function renderScenarioCharts(result){
    const s=result?.scenario||{}; const totals=[{label:'Actual',value:Number(s.total_actual||0)},{label:'Base nueva',value:Number(s.total_base||0)},{label:'Escenario',value:Number(s.total_escenario||0)}];
    bars('grafico-scenario-totales',totals,'value','label');
    const grouped=new Map(); (result?.rows||[]).forEach(row=>{const item=grouped.get(row.sector)||{label:row.sector,value:0}; item.value+=Number(row.diferencia||0); grouped.set(row.sector,item);});
    bars('grafico-scenario-sectores',[...grouped.values()].sort((a,b)=>Math.abs(b.value)-Math.abs(a.value)),'value','label');
  }
  function renderScenarioResult(result){
    state.scenarioResult=result; const s=result?.scenario; if(!s){$('kpis-scenario').innerHTML=''; $('tabla-scenario-resultados').innerHTML=''; return;}
    $('kpis-scenario').innerHTML=[kpi('Actual',money(s.total_actual),'referencia congelada'),kpi('Base nueva',money(s.total_base),'sin ajuste sectorial'),kpi('Escenario',money(s.total_escenario),'resultado simulado',s.diferencia_pct>=0?'ok':'warn'),kpi('Diferencia',signedMoney2(s.diferencia),`${fmt(s.diferencia_pct)} vs actual`,s.diferencia_pct>=0?'ok':'warn'),kpi('Legajos',fmt(s.legajos),'resultado individual')].join('');
    table('tabla-scenario-resultados',[{key:'legajo',label:'Legajo',mono:true},{key:'sector',label:'Sector'},{key:'pago_actual',label:'Actual',money:true},{key:'pago_base',label:'Base nueva',money:true},{key:'pago_escenario',label:'Escenario',money:true},{key:'diferencia',label:'Diferencia',format:value=>signedMoney2(value)},{key:'diferencia_pct',label:'Dif. %',format:value=>value==null?'-':`${fmt(value)}%`}],result.rows||[],{maxRows:500});
    renderScenarioCharts(result); $('scenario-status').textContent=`${s.nombre} Â· ${s.estado} Â· ${fmt(s.diferencia_pct)}% vs actual.`;
    const actions=$('scenario-status').parentElement; let publish=$('scenario-publish'); if(!publish){publish=document.createElement('button'); publish.id='scenario-publish'; publish.className='secondary-cta'; publish.textContent='Publicar escenario'; actions.insertBefore(publish,actions.lastElementChild); } publish.disabled=s.estado==='PUBLICADO'; publish.onclick=async()=>{await api(`/api/analisis-premio-productividad/escenarios/${encodeURIComponent(s.scenario_id)}/publicar`,{method:'POST'}); s.estado='PUBLICADO'; renderScenarioResult(result);};
  }
  async function loadScenarioModule(){
    if(!state.tablaPremios) state.tablaPremios=await api('/api/analisis-premio-productividad/tabla-premios');
    if(!state.scenarioSectors.length) loadDefaultScenarioSectors(); else renderScenarioEditor();
    if(!state.scenarioResult) { const list=await api('/api/analisis-premio-productividad/escenarios?' + qs({fecha_desde:state.fechaDesde,fecha_hasta:state.fechaHasta})); const latest=list.escenarios?.[0]; if(latest) { state.scenarioResult=await api(`/api/analisis-premio-productividad/escenarios/${encodeURIComponent(latest.scenario_id)}`); renderScenarioResult(state.scenarioResult); } }
  }
  async function simulateScenario(){
    if(state.scenarioLoading) return; state.scenarioLoading=true; $('scenario-simulate').disabled=true; $('scenario-status').textContent='Simulando sobre Punto 0 y cache local...';
    try { const payload={fecha_desde:$('rango-desde').value,fecha_hasta:$('rango-hasta').value,nombre:$('scenario-name').value||'Escenario sectorial',descripcion:$('scenario-description').value||'',sectores:(state.scenarioSectors||[]).filter(row=>Number(row.premio_pct||0)||Number(row.umbral_pct||0)).map(row=>({sector:row.sector,premio_pct:Number(row.premio_pct||0),umbral_pct:Number(row.umbral_pct||0)}))}; const result=await api('/api/analisis-premio-productividad/escenarios/simular',{method:'POST',body:JSON.stringify(payload)}); renderScenarioResult(result); } finally { state.scenarioLoading=false; $('scenario-simulate').disabled=false; }
  }
  async function loadTab(tab=state.activeTab){
    updateGlobalFiltersForTab(tab);
    if (tab === 'punto0') {
      await loadPunto0();
      return;
    }
    if (tab === 'evaluacion-picking') {
      if (!state.evaluacionPicking) {
        setStatus('EvaluaciÃ³n Picking lista. PresionÃ¡ Consultar para cargarla manualmente.');
      } else {
        renderEvaluacionPicking();
      }
      return;
    }
    if (tab === 'propuesta-autonoma') {
      if (!state.evaluacionPicking) await loadEvaluacionPicking();
      if (!state.calculoPagoGrupal) await loadCalculoPagoGrupal();
      renderPropuestaAutonoma();
      renderPropuestaAutonomaAlternatives();
      await loadScenarioModule();
      return;
    }
    if (!state.hasConsulted && !['tabla-premios','evaluacion-picking','propuesta-autonoma','calculo-pago-grupal','punto0'].includes(tab)) {
      state.activeTab = tab;
      setStatus('Sin consulta ejecutada. AjustÃ¡ los filtros y presionÃ¡ Consultar para cargar datos.');
      return;
    }
    state.activeTab = tab; setStatus(tab === 'tabla-premios' ? 'Tomando/leyendo foto local de escalas...' : tab === 'evaluacion-picking' ? 'Cargando evaluaciÃ³n por legajo, hora y sector...' : 'Leyendo desde SQLite/cache...');
    if (tab === 'tabla-premios') await loadTablaPremios();
    if (tab === 'evaluacion-picking') await loadEvaluacionPicking();
    if (tab === 'calculo-pago-grupal') await loadCalculoPagoGrupal();
    if (tab === 'resumen') await loadResumen();
    if (tab === 'grupal') await loadPremioGrupal();
    if (tab === 'grupal-legajos') await loadPremioGrupalLegajos();
    if (tab === 'estudio') await loadEstudio();
    if (tab === 'detalle') await loadDetalle();
    if (tab === 'cache') await loadCache();
    if (state.activeTab !== tab) return;
    setStatus(tab === 'tabla-premios' ? 'Tabla Premios actualizada desde la foto local.' : tab === 'evaluacion-picking' ? 'EvaluaciÃ³n Picking actualizada desde cache local.' : 'Datos actualizados desde cache SQLite.');
  }
  function activate(tab){
    if (state.loading) return;
    const navigationGeneration=beginTabNavigation(tab);
    document.querySelectorAll('.tab-btn').forEach(x => x.classList.toggle('active', x.dataset.tab === tab));
    document.querySelectorAll('.paper-panel').forEach(x => x.classList.remove('active'));
    $(`panel-${tab}`).classList.add('active');
    state.activeTab = tab;
    updateGlobalFiltersForTab(tab);
    if (!state.hasConsulted && !['tabla-premios','evaluacion-picking','propuesta-autonoma','calculo-pago-grupal','punto0'].includes(tab)) {
      setStatus('Sin consulta ejecutada. AjustÃ¡ los filtros y presionÃ¡ Consultar para cargar datos.');
      return;
    }
    loadTab(tab).then(()=>{if (navigationGeneration!==state.tabNavigationGeneration || state.activeTab!==tab) return;}).catch(e => { if (!isAbortError(e)) setStatus(e.message, true); });
  }
  async function init(){
    setupDateLimits();
    document.querySelector('.tab-btn[data-tab="calculo-pago-grupal"]')?.replaceChildren(document.createTextNode('CÃ¡lculo Pago Grupal'));
    const me = await api('/api/auth/me'); $('user-label').textContent = me.display_name || me.username;
    const estudioMeta = await api('/api/analisis-premio-productividad/estudio/meta').catch(() => ({enabled:false}));
    state.estudioEnabled = Boolean(estudioMeta.enabled);
    document.querySelectorAll('.tab-btn[data-tab="estudio"]').forEach(btn => btn.classList.toggle('hidden', !state.estudioEnabled));
    await setupDefaultCachedDate();
    updateGlobalFiltersForTab('tabla-premios');
    setStatus('Listo. No se ejecutÃ³ ninguna consulta automÃ¡tica; presionÃ¡ Consultar para cargar datos.');
  }
  document.querySelectorAll('.tab-btn').forEach(btn => btn.onclick = () => activate(btn.dataset.tab));
  async function onComboChange(){
    syncCombo();
    clearLoadedData();
    setStatus('Filtros modificados. PresionÃ¡ Consultar para ejecutar la carga.');
  }
  $('operacion-select').onchange = () => onComboChange().catch(e => setStatus(e.message, true));
  $('almacen-select').onchange = () => onComboChange().catch(e => setStatus(e.message, true));
  $('rango-desde').onchange = () => onComboChange().catch(e => setStatus(e.message, true));
  $('rango-hasta').onchange = () => onComboChange().catch(e => setStatus(e.message, true));
  $('consultar-rango').onclick = () => consultarRango(false).catch(e => setStatus(e.message, true));
  $('punto0-recalcular').onclick = () => recalcularPunto0().catch(e => setStatus(e.message, true));
  $('scenario-simulate').onclick = () => simulateScenario().catch(e => { $('scenario-status').textContent=e.message; setStatus(e.message, true); });
  $('scenario-load-default').onclick = () => loadDefaultScenarioSectors();
  $('scenario-clear').onclick = () => { state.scenarioSectors=(state.scenarioSectors||[]).map(row=>({...row,premio_pct:0,umbral_pct:0})); renderScenarioEditor(); $('scenario-status').textContent='Ajustes limpiados. La tabla base queda sin modificaciones.'; };
  $('evaluacion-f-legajo').oninput = () => { state.evaluacionPickingLegajoFilter = $('evaluacion-f-legajo').value || ''; state.evaluacionPickingSelected = ''; state.evaluacionPickingDaySelected = ''; state.evaluacionPickingHourSelected = ''; renderEvaluacionPicking(); };
  $('evaluacion-clear-filtro-legajo').onclick = () => { state.evaluacionPickingLegajoFilter = ''; $('evaluacion-f-legajo').value = ''; state.evaluacionPickingSelected = ''; state.evaluacionPickingDaySelected = ''; state.evaluacionPickingHourSelected = ''; renderEvaluacionPicking(); };
  $('evaluacion-precargar').onclick = async () => {
    if (state.loading || state.evaluacionPickingLoading) return;
    const desde = $('rango-desde').value, hasta = $('rango-hasta').value;
    if (!desde || !hasta) return setStatus('Indica fecha desde y fecha hasta.', true);
    state.evaluacionPickingLoading = true;
    $('evaluacion-precargar').disabled = true;
    $('evaluacion-precargar').textContent = 'Precargando...';
    try {
      setStatus('Precargando EvaluaciÃ³n Picking desde Oracle y guardando en SQLite...');
      await api('/api/analisis-premio-productividad/precargar-evaluacion-picking?' + qs({fecha_desde:desde, fecha_hasta:hasta}), {method:'POST'});
      setStatus('Precarga finalizada. Las prÃ³ximas consultas de EvaluaciÃ³n Picking serÃ¡n locales.');
      state.evaluacionPickingLoading = false;
      await loadEvaluacionPicking();
    } catch (e) { setStatus(e.message, true); }
    finally { state.evaluacionPickingLoading = false; $('evaluacion-precargar').disabled = false; $('evaluacion-precargar').textContent = 'Precargar desde Oracle'; }
  };
  function setEvaluacionDetalleVista(vista){
    const grafico = vista === 'grafico';
    $('evaluacion-detalle-vista-grilla').classList.toggle('hidden', grafico);
    $('evaluacion-detalle-vista-grafico').classList.toggle('hidden', !grafico);
    $('evaluacion-detalle-tab-grilla').classList.toggle('active', !grafico);
    $('evaluacion-detalle-tab-grafico').classList.toggle('active', grafico);
  }
  $('evaluacion-detalle-tab-grilla').onclick = () => setEvaluacionDetalleVista('grilla');
  $('evaluacion-detalle-tab-grafico').onclick = () => setEvaluacionDetalleVista('grafico');
  $('evaluacion-visual-toggle').onclick = () => {
    const body = $('evaluacion-visual-body');
    const collapsed = body.classList.toggle('hidden');
    $('evaluacion-visual-toggle').textContent = collapsed ? 'Mostrar' : 'Ocultar';
  };
  $('detalle-f-fecha').oninput = renderDetalleCacheGrid;
  $('detalle-f-legajo').oninput = renderDetalleCacheGrid;
  $('estudio-f-estado').onchange = () => { state.estudioFilters.estado = $('estudio-f-estado').value || ''; renderEstudio(); };
  $('estudio-f-tipo').onchange = () => { state.estudioFilters.tipo = $('estudio-f-tipo').value || ''; renderEstudio(); };
  $('estudio-f-texto').oninput = () => { state.estudioFilters.texto = $('estudio-f-texto').value || ''; renderEstudio(); };
  document.addEventListener('change', event => {
    const input = event.target.closest('input[type="checkbox"][data-estudio-filter]');
    if (!input) return;
    const key = input.dataset.estudioFilter;
    const current = new Set(state.estudioFilters[key] || []);
    if (input.checked) current.add(input.value); else current.delete(input.value);
    state.estudioFilters[key] = Array.from(current);
    updateEstudioChecklistSummary(key);
    renderEstudio();
  });
  document.querySelectorAll('[data-estudio-clear]').forEach(button => {
    button.addEventListener('click', () => {
      const key = button.dataset.estudioClear;
      state.estudioFilters[key] = [];
      setEstudioChecklist(key, Array.from($(`estudio-f-${key}`).querySelectorAll('input')).map(input => input.value));
      renderEstudio();
    });
  });
  document.querySelectorAll('[data-estudio-select-all]').forEach(button => {
    button.addEventListener('click', () => {
      const key = button.dataset.estudioSelectAll;
      const values = Array.from($(`estudio-f-${key}`).querySelectorAll('input')).map(input => input.value);
      state.estudioFilters[key] = values;
      setEstudioChecklist(key, values);
      renderEstudio();
    });
  });
  $('limpiar-detalle-filtros').onclick = () => {
    $('detalle-f-fecha').value = '';
    $('detalle-f-legajo').value = '';
    renderDetalleCacheGrid();
  };
  $('exportar-resumen-pdf').onclick = () => {
    try { exportarResumenPdf(); } catch (e) { setStatus(e.message, true); }
  };
  $('exportar-detalle-pdf').onclick = () => {
    try { exportarDetallePdf(); } catch (e) { setStatus(e.message, true); }
  };
  $('editar-fijos-grupal').onclick = abrirFijosGrupal;
  $('cerrar-fijos-grupal').onclick = cerrarFijosGrupal;
  $('aplicar-fijos-grupal').onclick = aplicarFijosGrupal;
  $('restaurar-fijos-grupal').onclick = restaurarFijosGrupal;
  $('fijos-grupal-modal').onclick = event => { if (event.target.id === 'fijos-grupal-modal') cerrarFijosGrupal(); };
  $('grupal-parametros').addEventListener('change', event => {
    if (event.target.id === 'grupal-margen-pct') aplicarMargenGrupal(event.target.value);
  });
  $('grupal-f-almacen').onchange = () => {
    state.groupFilters.almacen = $('grupal-f-almacen').value || 'TODOS';
    renderGroupBonusTable();
  };
  $('grupal-f-fecha').oninput = () => {
    state.groupFilters.fecha = $('grupal-f-fecha').value || '';
    renderGroupBonusTable();
  };
  $('grupal-f-legajo').oninput = () => {
    state.groupFilters.legajo = $('grupal-f-legajo').value.trim();
    renderGroupBonusTable();
  };
  $('exportar-grupal-excel').onclick = exportGroupBonusExcel;
  $('cerrar-detalle').onclick = cerrarDetalle;
  $('detalle-modal').onclick = event => { if (event.target.id === 'detalle-modal') cerrarDetalle(); };
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { cerrarDetalle(); cerrarFijosGrupal(); } });
  $('logout-btn').onclick = async () => { await fetch('/api/auth/logout', {method:'POST', credentials:'same-origin'}); location.href='/login'; };
  init().catch(e => setStatus(e.message, true));

