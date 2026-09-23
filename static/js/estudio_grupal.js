// Parámetros y navegación del premio grupal: grupo -> día -> nómina completa.
function operacionDisplay(value) {
  const op = String(value || '').trim().toUpperCase();
  if (op === 'PALETS OPERADOS') return 'Carga';
  return value || '';
}

async function grupalRequest(url, payload, method = 'PUT') {
  const response = await fetch('/api/estudio-premios-productividad/' + url, {
    credentials: 'same-origin',
    ...(payload ? {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)} : {})
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(body.detail || 'No se pudo completar la consulta.');
  return body;
}

async function loadParametrosGrupales() {
  const d = await grupalRequest('parametros-grupales');
  const order = (a, b) => a.localeCompare(b, 'es', {sensitivity: 'base'});
  const options = (field, label, catalogo = d.catalogo || []) => `<option value="">${label}</option>` +
    [...new Set(catalogo.map(x => x[field]).filter(Boolean))].sort(order)
      .map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join('');
  $('pg-sector').innerHTML = options('sector', 'Seleccioná sector');
  const cargarFunciones = () => {
    const sector = $('pg-sector').value;
    const catalogo = sector ? (d.catalogo || []).filter(x => x.sector === sector) : [];
    $('pg-funcion').innerHTML = options('funcion_legajero',
      sector ? 'Seleccioná función' : 'Primero seleccioná sector', catalogo);
  };
  cargarFunciones();
  $('pg-sector').onchange = cargarFunciones;
  const operaciones = [...(d.operaciones || [])].sort((a, b) => order(a.operacion, b.operacion));
  const operationOptions = selected => '<option value="">Seleccioná operación medible</option>' +
    (selected && !operaciones.some(x => x.operacion === selected) ?
      `<option value="${esc(selected)}" selected>${esc(selected)} · revisar clasificación</option>` : '') +
    operaciones.map(x => `<option value="${esc(x.operacion)}" ${x.operacion === selected ? 'selected' : ''}>${esc(operacionDisplay(x.operacion))} · ${esc(x.unidad_medida)}</option>`).join('');
  $('pg-operacion').innerHTML = operationOptions('');
  const grupos = [...(d.grupos_productivos || [])].sort((a, b) => order(a.descripcion, b.descripcion));
  const groupOptions = selected => '<option value="">Sin grupo productivo</option>' +
    (selected != null && !grupos.some(x => String(x.id) === String(selected)) ?
      `<option value="${esc(selected)}" selected>Grupo ${esc(selected)} (fuera de catálogo)</option>` : '') +
    grupos.map(x => `<option value="${esc(x.id)}" ${String(x.id) === String(selected) ? 'selected' : ''}>${esc(x.descripcion)}</option>`).join('');
  $('pg-grupo').innerHTML = groupOptions(null);
  const divisiones = [...(d.divisiones || [])].map(item => typeof item === 'string'
    ? {codigo: item, label: item}
    : {codigo: String(item.codigo || ''), label: item.label || `${item.codigo || ''}${item.descripcion ? ` · ${item.descripcion}` : ''}`})
    .filter(item => item.codigo).sort((a, b) => order(a.label, b.label));
  const selectedDivisions = selected => new Set(String(selected || '').split(',').map(x => x.trim()).filter(Boolean));
  const divisionOptions = selected => {
    const seleccionadas = selectedDivisions(selected);
    const fuera = [...seleccionadas].filter(x => !divisiones.some(dv => dv.codigo === x));
    return fuera.map(x => `<option value="${esc(x)}" selected>${esc(x)} · fuera de catálogo</option>`).join('') +
      divisiones.map(x => `<option value="${esc(x.codigo)}" ${seleccionadas.has(x.codigo) ? 'selected' : ''}>${esc(x.label)}</option>`).join('');
  };
  const divisionChecks = selected => {
    const seleccionadas = selectedDivisions(selected);
    return `<div class="pg-division-checks" data-pg="division">${divisiones.map(x => `<label class="pg-division-chip ${seleccionadas.has(x.codigo) ? 'checked' : ''}"><input type="checkbox" value="${esc(x.codigo)}" ${seleccionadas.has(x.codigo) ? 'checked' : ''}>${esc(x.label)}</label>`).join('')}</div>`;
  };
  if ($('pg-division')) $('pg-division').innerHTML = divisionOptions('');
  $('param-grupal-rows').innerHTML = (d.rows || []).map((x, i) => `<tr>
    <td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(x.turno)}</td>
    <td><select class="input" data-pg="operacion">${operationOptions(x.operacion_medible)}</select></td>
    <td>${divisionChecks(x.division_madre)}</td>
    <td><select class="input" data-pg="grupo" aria-label="Grupo productivo del parámetro ${i + 1}">${groupOptions(x.grupo_productivo_id)}</select></td>
    <td><input class="input" type="number" min="0" step="any" data-pg="uc" value="${x.uc_por_operario}"></td>
    <td><input class="input" type="number" min="0" max="100" step="any" data-pg="factor" value="${x.factor_ausentismo}"></td>
    <td><input class="input" type="number" min="0" step="0.01" data-pg="premio" value="${x.premio_grupal}"></td>
    <td class="pg-accion"><button class="secondary" data-pg-save="${i}">Guardar</button><button class="secondary" data-pg-delete="${i}" style="margin-top:6px">Quitar</button></td></tr>`).join('') || '<tr><td colspan="10">Sin parámetros configurados.</td></tr>';
  const save = async (button, payload) => {
    button.disabled = true;
    button.textContent = 'Guardando...';
    try {
      await grupalRequest('parametros-grupales', payload);
      button.textContent = 'Guardado';
      $('status').style.color = '';
      $('status').textContent = 'Parámetro guardado. Consultá Cálculo grupal diario para recalcular.';
      return true;
    } catch (error) {
      button.textContent = 'Reintentar';
      $('status').style.color = '#C8102E';
      $('status').textContent = error.message;
      return false;
    } finally { button.disabled = false; }
  };
  document.querySelectorAll('[data-pg-save]').forEach(button => {
    const row = button.closest('tr');
    row.querySelectorAll('input,select').forEach(input => input.onchange = () => {
      input.closest('.pg-division-chip')?.classList.toggle('checked', input.checked);
      button.textContent = 'Guardar';
    });
    button.onclick = async () => {
      const x = d.rows[Number(button.dataset.pgSave)];
      const value = key => row.querySelector(`[data-pg="${key}"]`).value;
      const divisionValues = () => [...row.querySelectorAll('[data-pg="division"] input:checked')].map(input => input.value);
      await save(button, {sector: x.sector, funcion_legajero: x.funcion_legajero, turno: x.turno,
        activo: Boolean(x.activo), operacion_medible: value('operacion'), uc_por_operario: value('uc'),
        division_madre: divisionValues(), grupo_productivo_id: value('grupo') || null,
        factor_ausentismo: value('factor'), premio_grupal: value('premio')});
    };
  });
  document.querySelectorAll('[data-pg-delete]').forEach(button => button.onclick = async () => {
    const x = d.rows[Number(button.dataset.pgDelete)];
    if (!confirm(`¿Quitar el parámetro ${x.sector} / ${x.funcion_legajero} / turno ${x.turno}?`)) return;
    button.disabled = true;
    try {
      await grupalRequest('parametros-grupales', {sector: x.sector,
        funcion_legajero: x.funcion_legajero, turno: x.turno}, 'DELETE');
      $('status').style.color = '';
      $('status').textContent = 'Parámetro eliminado. El cálculo grupal debe actualizarse.';
      await loadParametrosGrupales();
    } catch (error) {
      $('status').style.color = '#C8102E';
      $('status').textContent = error.message;
    } finally { button.disabled = false; }
  });
  $('pg-alta').onclick = async () => {
    const divisionesMadre = $('pg-division') ? [...$('pg-division').selectedOptions].map(option => option.value) : [];
    if (await save($('pg-alta'), {sector: $('pg-sector').value, funcion_legajero: $('pg-funcion').value,
      turno: $('pg-turno').value, operacion_medible: $('pg-operacion').value, uc_por_operario: $('pg-uc').value,
      division_madre: divisionesMadre,
      grupo_productivo_id: $('pg-grupo').value || null,
      factor_ausentismo: $('pg-factor').value, premio_grupal: $('pg-premio').value})) await loadParametrosGrupales();
  };
  const pending = (d.rows || []).filter(x => !operaciones.some(op => op.operacion === x.operacion_medible)).length;
  $('status').textContent = `${(d.rows || []).length} parámetros · ${pending} pendientes de operación medible`;
  await loadTurnosGrupales();
}

async function loadTurnosGrupales() {
  const d = await grupalRequest('turnos-grupales');
  const render = () => {
    const search = $('turnos-buscar').value.trim().toLocaleLowerCase('es');
    const rows = (d.rows || []).map((x, index) => ({...x, index})).filter(x =>
      `${x.legajo} ${x.nombre} ${x.sector} ${x.funcion_legajero}`.toLocaleLowerCase('es').includes(search));
    $('turnos-meta').textContent = `${rows.length} de ${d.rows.length} legajos · ${d.rows.filter(x => !x.turno_fijo).length} sin turno asignado. ${d.criterio}`;
    $('turnos-rows').innerHTML = rows.map(x => `<tr>
      <td>${esc(x.legajo)}</td><td>${esc(x.nombre)}</td><td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td>
      <td><input class="input" data-turno-input="${x.index}" value="${esc(x.turno_fijo)}" placeholder="Sin asignar" maxlength="20" aria-label="Turno fijo legajo ${esc(x.legajo)}"></td>
      <td>${esc(x.turno_probable || 'Sin historial')}</td><td>${x.dias_turno} / ${x.total_dias}</td>
      <td>${esc(Object.entries(JSON.parse(x.distribucion || '{}')).map(([t, n]) => `${t}: ${n} días`).join(' · '))}</td>
      <td>${esc(x.origen)}</td><td><button class="secondary" data-turno-save="${x.index}">Guardar</button></td></tr>`).join('') || '<tr><td colspan="10">Sin coincidencias.</td></tr>';
    document.querySelectorAll('[data-turno-save]').forEach(button => button.onclick = async () => {
      const x = d.rows[Number(button.dataset.turnoSave)];
      const turno = button.closest('tr').querySelector('input').value.trim();
      button.disabled = true;
      try {
        await grupalRequest('turnos-grupales', {legajo: x.legajo, turno_fijo: turno});
        x.turno_fijo = turno; x.origen = 'manual';
        render();
        $('turnos-meta').textContent = `Turno de ${x.legajo} guardado: ${turno || 'Sin asignar'}. Volvé a consultar el cálculo grupal.`;
      } catch (error) {
        button.disabled = false; button.textContent = 'Reintentar';
        $('turnos-meta').textContent = error.message;
      }
    });
  };
  $('turnos-buscar').oninput = render;
  render();
}

function habilitarOrdenGrupal() {
  document.querySelectorAll('#view-grupal table').forEach(table => table.querySelectorAll('th').forEach((th, col) => {
    th.onclick = () => {
      const body = table.querySelector('tbody');
      const rows = [...body.querySelectorAll('tr')].filter(row => row.children.length > 1);
      const dir = th.dataset.dir === '1' ? -1 : 1;
      th.dataset.dir = String(dir);
      rows.sort((a, b) => {
        const av = a.children[col]?.textContent.trim() || '', bv = b.children[col]?.textContent.trim() || '';
        const number = value => Number(value.replace(/\./g, '').replace(',', '.').replace(/[$%\s]/g, ''));
        const an = number(av), bn = number(bv);
        return dir * (av && bv && Number.isFinite(an) && Number.isFinite(bn) ? an - bn : av.localeCompare(bv, 'es', {numeric: true}));
      });
      rows.forEach(row => body.appendChild(row));
    };
  }));
}

async function loadEscalasPropuestas() {
  const params = {
    fecha_desde: $('desde').value,
    fecha_hasta: $('hasta').value,
    operacion: $('ep-operacion')?.value || '',
    division: $('ep-division')?.value || '',
    turno: $('ep-turno')?.value || ''
  };
  if ($('ep-meta')) $('ep-meta').textContent = 'Cargando simulación desde cache...';
  if ($('ep-chart')) $('ep-chart').innerHTML = '<div class="empty">Cargando gráfico...</div>';
  if ($('ep-dinamica-rows')) $('ep-dinamica-rows').innerHTML = '<tr><td colspan="7">Cargando datos...</td></tr>';
  if ($('ep-unica-rows')) $('ep-unica-rows').innerHTML = '<tr><td colspan="8">Cargando datos...</td></tr>';
  if ($('ep-individual-rows')) $('ep-individual-rows').innerHTML = '<tr><td colspan="6">Seleccioná una fila para calcular la escala individual.</td></tr>';
  if ($('ep-individual-meta')) $('ep-individual-meta').textContent = 'Sin fila seleccionada.';
  const data = await grupalRequest('escalas-propuestas?' + qs(params), null, 'GET');
  const rows = data.rows || [], series = data.series || [];
  escalasPropuestasSeriesActual = series;
  const opOptions = (values, selected, all) => `<option value="">${all}</option>` +
    values.map(v => `<option value="${esc(v)}" ${v === selected ? 'selected' : ''}>${esc(operacionDisplay(v))}</option>`).join('');
  const divOptions = (values, selected) => '<option value="">Todas</option>' +
    values.map(x => {
      const value = typeof x === 'string' ? x : x.value;
      const label = typeof x === 'string' ? x : x.label;
      return `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`;
    }).join('');
  if ($('ep-operacion')) $('ep-operacion').innerHTML = opOptions(data.filtros?.operaciones || [], params.operacion, 'Todas');
  if ($('ep-division')) $('ep-division').innerHTML = divOptions(data.filtros?.divisiones || [], params.division);
  if ($('ep-turno')) $('ep-turno').innerHTML = opOptions(data.filtros?.turnos || [], params.turno, 'Todos');
  if ($('ep-operacion') && !$('ep-operacion').dataset.bound) {
    $('ep-operacion').dataset.bound = '1';
    $('ep-operacion').onchange = () => { if ($('ep-division')) $('ep-division').value = ''; if ($('ep-turno')) $('ep-turno').value = ''; loadEscalasPropuestas().catch(e => $('ep-meta').textContent = e.message); };
  }
  if ($('ep-division') && !$('ep-division').dataset.bound) {
    $('ep-division').dataset.bound = '1';
    $('ep-division').onchange = () => loadEscalasPropuestas().catch(e => $('ep-meta').textContent = e.message);
  }
  if ($('ep-turno') && !$('ep-turno').dataset.bound) {
    $('ep-turno').dataset.bound = '1';
    $('ep-turno').onchange = () => loadEscalasPropuestas().catch(e => $('ep-meta').textContent = e.message);
  }
  if ($('ep-pct-objetivo') && !$('ep-pct-objetivo').dataset.bound) {
    $('ep-pct-objetivo').dataset.bound = '1';
    $('ep-pct-objetivo').oninput = () => renderEscalasDinamicas(escalasPropuestasSeriesActual);
  }
  if ($('ep-uc-unica') && !$('ep-uc-unica').dataset.bound) {
    $('ep-uc-unica').dataset.bound = '1';
    $('ep-uc-unica').oninput = () => renderEscalasDinamicas(escalasPropuestasSeriesActual);
  }
  $('ep-meta').textContent = rows.length ? `${rows.length} filas · ${data.nota || ''}` : `Sin datos para la selección actual. ${data.nota || ''}`;
  renderEscalasDinamicas(escalasPropuestasSeriesActual);
  prepararTabsEscalasPropuestas();
  renderEscalasPropuestasChart(escalasPropuestasSeriesActual);
}

function epPctObjetivo() {
  const raw = Number($('ep-pct-objetivo')?.value || 50);
  return Math.max(0, Math.min(100, Number.isFinite(raw) ? raw : 50));
}

function epUcUnica() {
  const raw = Number($('ep-uc-unica')?.value || 0);
  return Math.max(0, Number.isFinite(raw) ? raw : 0);
}

function epUcParaPct(serie, pct) {
  const points = [...(serie.points || [])].sort((a, b) => Number(b.pct_dias || 0) - Number(a.pct_dias || 0));
  if (!points.length) return 0;
  const eligible = points.filter(point => Number(point.pct_dias || 0) >= pct);
  return Number((eligible.length ? eligible[eligible.length - 1] : points[0]).uc || 0);
}

function epDiasParaUc(serie, uc) {
  const points = serie.points || [];
  if (!points.length) return {dias_cobra:0, pct_dias:0};
  return points.reduce((best, point) => Math.abs(Number(point.uc || 0) - uc) < Math.abs(Number(best.uc || 0) - uc) ? point : best, points[0]);
}

function renderEscalasDinamicas(series) {
  const pct = epPctObjetivo();
  const ucUnica = epUcUnica();
  const dinamica = $('ep-dinamica-rows'), unica = $('ep-unica-rows');
  if (!dinamica || !unica) return;
  const fmt = value => Math.ceil(Number(value || 0)).toLocaleString('es-AR', {maximumFractionDigits:0});
  const pctFmt = value => `${Number(value || 0).toLocaleString('es-AR', {maximumFractionDigits:1})}%`;
  const ordered = [...series].sort((a,b) => String(operacionDisplay(a.operacion)).localeCompare(String(operacionDisplay(b.operacion)), 'es', {numeric:true}) || String(a.division_label || a.division || '').localeCompare(String(b.division_label || b.division || ''), 'es', {numeric:true}) || String(a.turno || '').localeCompare(String(b.turno || ''), 'es', {numeric:true}));
  dinamica.innerHTML = ordered.map((s, index) => {
    const uc = epUcParaPct(s, pct);
    return `<tr data-ep-dyn-index="${index}"><td>${esc(operacionDisplay(s.operacion))}</td><td>${esc(s.division_label || s.division || '—')}</td><td>${esc(s.turno || 'Todos')}</td><td class="mono">${Number(s.dias || 0).toLocaleString('es-AR')}</td><td class="mono">${pctFmt(pct)}</td><td class="mono">${fmt(uc)}</td><td>${esc(s.unidad_label || s.unidad_medida || 'UC')}</td></tr>`;
  }).join('') || '<tr><td colspan="7">Sin datos para la selección actual.</td></tr>';
  unica.innerHTML = ordered.map(s => {
    const impact = epDiasParaUc(s, ucUnica);
    const diff = Number(impact.pct_dias || 0) - pct;
    return `<tr><td>${esc(operacionDisplay(s.operacion))}</td><td>${esc(s.division_label || s.division || '—')}</td><td>${esc(s.turno || 'Todos')}</td><td class="mono">${fmt(ucUnica)}</td><td class="mono">${Number(s.dias || 0).toLocaleString('es-AR')}</td><td class="mono">${Number(impact.dias_cobra || 0).toLocaleString('es-AR')}</td><td class="mono">${pctFmt(impact.pct_dias || 0)}</td><td class="mono">${diff >= 0 ? '+' : ''}${pctFmt(diff)}</td></tr>`;
  }).join('') || '<tr><td colspan="8">Sin datos para simular.</td></tr>';
  prepararOrdenTablaEscalas('ep-dinamica-rows', ['txt','txt','txt','num','num','num','txt']);
  prepararOrdenTablaEscalas('ep-unica-rows', ['txt','txt','txt','num','num','num','num','num']);
  prepararEscalaIndividualDinamica(ordered, pct);
}

function prepararOrdenTablaEscalas(bodyId, types) {
  const body = $(bodyId), table = body?.closest('table');
  const flag = `data-sort-${bodyId}`;
  if (!body || !table || table.getAttribute(flag)) return;
  table.setAttribute(flag, '1');
  const number = value => Number(String(value || '').replace(/[^0-9,.-]/g, '').replace(/\./g, '').replace(',', '.')) || 0;
  table.tHead.addEventListener('click', event => {
    const th = event.target.closest('th'); if (!th) return;
    const col = [...th.parentElement.cells].indexOf(th), dir = th.dataset.sortDir === '1' ? -1 : 1;
    [...th.parentElement.cells].forEach(item => { delete item.dataset.sortDir; item.removeAttribute('data-arrow'); });
    th.dataset.sortDir = String(dir); th.dataset.arrow = dir === 1 ? '↑' : '↓';
    [...body.rows].filter(row => row.cells.length > 1).sort((a,b) => {
      const av = a.cells[col]?.textContent || '', bv = b.cells[col]?.textContent || '';
      return dir * (types[col] === 'num' ? number(av) - number(bv) : av.localeCompare(bv, 'es', {numeric:true, sensitivity:'base'}));
    }).forEach(row => body.appendChild(row));
  });
}

function prepararEscalaIndividualDinamica(series, pct) {
  const body = $('ep-dinamica-rows'), target = $('ep-individual-rows'), meta = $('ep-individual-meta');
  if (!body || !target) return;
  const limpiar = () => {
    body.querySelectorAll('tr').forEach(row => row.classList.remove('ep-selected-row'));
    target.innerHTML = '<tr><td colspan="6">Seleccioná una fila para calcular la escala individual.</td></tr>';
    if (meta) meta.textContent = 'Sin fila seleccionada.';
    delete body.dataset.selectedIndex;
  };
  limpiar();
  body.onclick = event => {
    const row = event.target.closest('tr[data-ep-dyn-index]');
    if (!row) return;
    const index = row.dataset.epDynIndex;
    if (body.dataset.selectedIndex === index) { limpiar(); return; }
    body.querySelectorAll('tr').forEach(item => item.classList.toggle('ep-selected-row', item === row));
    body.dataset.selectedIndex = index;
    const item = series[Number(index)];
    const base = Math.ceil(epUcParaPct(item, pct));
    const operacion = operacionDisplay(item?.operacion || '');
    const division = item?.division_label || item?.division || '—';
    const turno = item?.turno || 'Todos';
    if (!base) {
      target.innerHTML = '<tr><td colspan="6">La fila seleccionada no tiene UC sugerida válida.</td></tr>';
      if (meta) meta.textContent = 'No se pudo calcular escala individual.';
      return;
    }
    const fmt = value => Math.ceil(Number(value || 0)).toLocaleString('es-AR', {maximumFractionDigits: 0});
    target.innerHTML = [1,2,3,4,5].map(nivel => {
      const desde = base * (1 + nivel * 0.10);
      const hasta = base * (1 + (nivel + 1) * 0.10);
      return `<tr><td class="mono">${nivel}</td><td>${esc(operacion)}</td><td>${esc(division)}</td><td>${esc(turno)}</td><td class="mono">${fmt(desde)}</td><td class="mono">${fmt(hasta)}</td></tr>`;
    }).join('');
    if (meta) meta.textContent = `Base dinámica: ${fmt(base)} UC para ${pct}% de días. Rangos individuales en incrementos de 10%.`;
  };
}

function prepararTabsEscalasPropuestas() {
  document.querySelectorAll('[data-ep-tab]').forEach(button => {
    if (button.dataset.bound) return;
    button.dataset.bound = '1';
    button.onclick = () => {
      const tab = button.dataset.epTab;
      document.querySelectorAll('[data-ep-tab]').forEach(item => item.classList.toggle('active', item === button));
      document.querySelectorAll('#view-escalas-propuestas .ep-panel').forEach(panel => panel.classList.toggle('active', panel.id === `ep-panel-${tab}`));
    };
  });
}

function renderEscalasPropuestasChart(series) {
  const target = $('ep-chart');
  if (!target) return;
  if (!series.length) { target.innerHTML = '<div class="empty">Elegí una operación medible para ver el área de simulación.</div>'; return; }
  const w = 980, h = 360, ml = 54, mr = 22, mt = 24, mb = 42;
  const maxX = 100;
  const maxY = Math.max(1, ...series.flatMap(s => (s.points || []).map(p => Number(p.uc || 0))));
  const x = value => ml + (Number(value || 0) / maxX) * (w - ml - mr);
  const y = value => mt + (1 - Number(value || 0) / maxY) * (h - mt - mb);
  const unidadLabel = series.find(s => s.unidad_label)?.unidad_label || 'UC real';
  const colors = ['#1F7A4D', '#0B5FAE', '#C8102E', '#7A5C00', '#6A3FA0', '#007C89'];
  const gridY = [0, Math.round(maxY / 4), Math.round(maxY / 2), Math.round(maxY * 3 / 4), Math.round(maxY)];
  const gridX = [0, 25, 50, 75, 100];
  const formatUC = value => Number(value || 0).toLocaleString('es-AR', {maximumFractionDigits: 1});
  const nearestPoint = (points, pct) => (points || []).reduce((best, point) => {
    const dist = Math.abs(Number(point.pct_dias || 0) - pct);
    return !best || dist < best.dist ? {point, dist} : best;
  }, null)?.point || {uc: 0, pct_dias: 0, dias_cobra: 0};
  const seriesLabel = s => s.division_label || s.division || 'Sin división';
  const areas = series.map((s, i) => {
    const color = colors[i % colors.length];
    const pts = (s.points || []).map(p => `${x(p.pct_dias)},${y(p.uc)}`).join(' ');
    const areaPts = `${x(0)},${y(0)} ${pts} ${x(0)},${y(maxY)}`;
    return `<polygon points="${areaPts}" fill="${color}" opacity="0.12"></polygon><polyline fill="none" stroke="${color}" stroke-width="2.4" points="${pts}"><title>${esc(operacionDisplay(s.operacion))} · ${esc(seriesLabel(s))}</title></polyline>`;
  }).join('');
  const marks50 = series.map((s, i) => {
    const color = colors[i % colors.length], uc50 = Number(s.uc_sugerido_50 || 0);
    const px = x(50), py = y(uc50), labelY = Math.max(mt + 12, Math.min(h - mb - 8, py + ((i % 3) - 1) * 14));
    const labelX = Math.min(w - mr - 185, px + 10);
    return `<circle cx="${px}" cy="${py}" r="4.5" fill="${color}" stroke="#FFF" stroke-width="1.5"><title>${esc(seriesLabel(s))} · ${esc(unidadLabel)} ${formatUC(uc50)}</title></circle><line x1="${px + 5}" x2="${labelX - 3}" y1="${py}" y2="${labelY}" stroke="${color}" stroke-width="1" opacity=".75"/><text x="${labelX}" y="${labelY + 4}" fill="${color}">${esc(seriesLabel(s))} · ${formatUC(uc50)} ${esc(unidadLabel)}</text>`;
  }).join('');
  const legend = series.map((s, i) => `<span><i style="background:${colors[i % colors.length]}"></i>${esc(seriesLabel(s))} · 50% ${formatUC(s.uc_sugerido_50 || 0)} ${esc(s.unidad_label || unidadLabel)}</span>`).join('');
  target.innerHTML = `<div class="ep-legend">${legend}</div><svg class="ep-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="Porcentaje de días con premio por ${esc(unidadLabel)}">
    ${gridY.map(v => `<line x1="${ml}" x2="${w - mr}" y1="${y(v)}" y2="${y(v)}" stroke="#D4DBD8"/><text x="${ml - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join('')}
    ${gridX.map(v => `<line x1="${x(v)}" x2="${x(v)}" y1="${mt}" y2="${h - mb}" stroke="#E4E9E6"/><text x="${x(v)}" y="${h - 15}" text-anchor="middle">${v}%</text>`).join('')}
    <line x1="${x(50)}" x2="${x(50)}" y1="${mt}" y2="${h - mb}" stroke="#0E1620" stroke-width="1.2" stroke-dasharray="5 5" opacity=".55"/><text x="${x(50) + 6}" y="${mt + 12}">50%</text>
    <line class="ep-hover-line" x1="${x(0)}" x2="${x(0)}" y1="${mt}" y2="${h - mb}" stroke="#0E1620" stroke-width="1" stroke-dasharray="3 4" opacity="0"/>
    <text x="${w / 2}" y="${h - 2}" text-anchor="middle">% de días que supera el umbral</text>
    <text x="14" y="${h / 2}" transform="rotate(-90 14 ${h / 2})" text-anchor="middle">${esc(unidadLabel)} por operario</text>
    ${areas}
    ${marks50}
  </svg><div class="ep-tooltip" aria-live="polite"></div>`;
  const svg = target.querySelector('svg');
  const hoverLine = target.querySelector('.ep-hover-line');
  const tooltip = target.querySelector('.ep-tooltip');
  if (!svg || !hoverLine || !tooltip) return;
  svg.addEventListener('mousemove', event => {
    const pt = svg.createSVGPoint();
    pt.x = event.clientX; pt.y = event.clientY;
    const cursor = pt.matrixTransform(svg.getScreenCTM().inverse());
    const pct = Math.max(0, Math.min(100, ((cursor.x - ml) / (w - ml - mr)) * 100));
    const lineX = x(pct);
    hoverLine.setAttribute('x1', String(lineX));
    hoverLine.setAttribute('x2', String(lineX));
    hoverLine.setAttribute('opacity', '0.9');
    const items = series.map((s, i) => {
      const p = nearestPoint(s.points, pct);
      return `<div><span style="color:${colors[i % colors.length]}">●</span> ${esc(seriesLabel(s))}: <strong>${formatUC(p.uc)} ${esc(s.unidad_label || unidadLabel)}</strong></div>`;
    }).join('');
    tooltip.innerHTML = `<strong>${Math.round(pct)}% de días</strong>${items}`;
    const rect = target.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.width - 260, event.clientX - rect.left + 12));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = '34px';
    tooltip.style.display = 'block';
  });
  svg.addEventListener('mouseleave', () => {
    hoverLine.setAttribute('opacity', '0');
    tooltip.style.display = 'none';
  });
}

function ordenarDetalleDiario() {
  const table = $('grupal-dias')?.closest('table');
  if (!table || table.dataset.columnasOrdenadas) return;
  const header = table.tHead?.rows[0];
  if (!header || header.cells.length !== 20) return;
  // Índices de la disposición histórica: fuera de vigencia, sin actividad y
  // sin confirmar. Se llevan al final para dejar juntas las métricas de pago.
  const fueraVigencia = header.cells[4], sinActividad = header.cells[5], sinConfirmar = header.cells[10];
  header.cells[3].textContent = 'Activos del turno';
  sinActividad.textContent = 'Sin actividad';
  header.append(fueraVigencia, sinConfirmar, sinActividad);
  table.dataset.columnasOrdenadas = '1';
}

function prepararPanelActividadGrupal() {
  if ($('grupal-actividad')) return;
  const nomina = $('grupal-legajos')?.closest('.table-wrap');
  if (!nomina) return;
  const title = document.createElement('div');
  title.className = 'view-title';
  title.innerHTML = '<strong>Actividad del legajo seleccionado</strong><span id="grupal-actividad-meta">Seleccioná un legajo de la nómina.</span>';
  const wrap = document.createElement('div');
  wrap.className = 'table-wrap';
  wrap.innerHTML = '<table><thead><tr><th>Operación WMS</th><th>División</th><th>Sector WMS</th><th>Palets</th><th>PLU</th><th>Cantidad</th><th>Peso</th><th>Filas cache</th></tr></thead><tbody id="grupal-actividad"><tr><td colspan="8">Seleccioná un legajo de la nómina.</td></tr></tbody></table>';
  nomina.after(title, wrap);
}

function vaciarActividadGrupal(mensaje) {
  prepararPanelActividadGrupal();
  $('grupal-actividad').innerHTML = `<tr><td colspan="8">${esc(mensaje)}</td></tr>`;
  $('grupal-actividad-meta').textContent = mensaje;
}

async function cargarActividadGrupal(fecha, legajo) {
  prepararPanelActividadGrupal();
  const body = $('grupal-actividad'), clave = `${fecha}:${legajo}`;
  body.dataset.consulta = clave;
  body.innerHTML = '<tr><td colspan="8">Consultando actividad WMS…</td></tr>';
  $('grupal-actividad-meta').textContent = `Legajo ${legajo} · ${fecha}`;
  try {
    const params = new URLSearchParams({fecha, legajo});
    const response = await fetch('/api/estudio-premios-productividad/actividad-legajo?' + params, {credentials: 'same-origin'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(data.detail || 'No se pudo leer la actividad del legajo.');
    if (body.dataset.consulta !== clave) return;
    const num = value => Number(value || 0).toLocaleString('es-AR', {maximumFractionDigits: 3});
    body.innerHTML = (data.rows || []).map(x => `<tr><td>${esc(x.funcion_wms)}</td><td>${esc(x.division || '—')}</td><td>${esc(x.sector || '—')}</td><td>${num(x.palets)}</td><td>${num(x.plus)}</td><td>${num(x.cantidad)}</td><td>${num(x.peso)}</td><td>${num(x.filas_cache)}</td></tr>`).join('') || '<tr><td colspan="8">El legajo no tiene actividad WMS para ese día.</td></tr>';
    $('grupal-actividad-meta').textContent = `${legajo} · ${fecha} · ${data.total || 0} operaciones WMS`;
  } catch (error) {
    if (body.dataset.consulta === clave) {
      body.innerHTML = `<tr><td colspan="8">${esc(error.message)}</td></tr>`;
      $('grupal-actividad-meta').textContent = error.message;
    }
  }
}

function prepararAccionRecalcularGrupal() {
  if ($('grupal-recalcular')) return;
  const title = document.querySelector('#view-grupal > .view-title');
  if (!title) return;
  const button = document.createElement('button');
  button.id = 'grupal-recalcular'; button.className = 'primary'; button.textContent = 'Actualizar cálculo';
  button.onclick = async () => {
    button.disabled = true; button.textContent = 'Actualizando...';
    try { await loadGrupal(); $('status').textContent = 'Cálculo grupal actualizado.'; }
    catch (error) { $('status').textContent = error.message; $('status').style.color = '#C8102E'; }
    finally { button.disabled = false; button.textContent = 'Actualizar cálculo'; }
  };
  title.append(button);
}

async function loadGrupal() {
  ordenarDetalleDiario();
  prepararPanelActividadGrupal();
  prepararAccionRecalcularGrupal();
  $('grupal-rows').innerHTML = '<tr><td colspan="10">Calculando...</td></tr>';
  $('grupal-dias').innerHTML = '<tr><td colspan="18">Seleccioná un grupo.</td></tr>';
  $('grupal-legajos').innerHTML = '<tr><td colspan="16">Seleccioná un día.</td></tr>';
  $('grupal-sin-turno').innerHTML = '';
  $('grupal-meta').textContent = 'Consultando nómina y asistencia...';
  const d = await grupalRequest('calculo-grupal?' + qs({fecha_desde: $('desde').value, fecha_hasta: $('hasta').value}));
  const money = value => Number(value || 0).toLocaleString('es-AR', {style: 'currency', currency: 'ARS'});
  const num = value => Number(value || 0).toLocaleString('es-AR', {maximumFractionDigits: 6});
  const empty = (id, columns, message) => { $(id).innerHTML = `<tr><td colspan="${columns}">${message}</td></tr>`; };
  const n1 = d.nivel_1 || [], n2 = d.nivel_2 || [], n3 = d.nivel_3 || [];
  const sameGroup = (a, b) => a.sector === b.sector && a.funcion_legajero === b.funcion_legajero && a.turno === b.turno;
  empty('grupal-dias', 18, 'Seleccioná un grupo.');
  empty('grupal-legajos', 16, 'Seleccioná un día.');
  vaciarActividadGrupal('Seleccioná un día y un legajo de la nómina.');
  $('grupal-sin-turno').innerHTML = (d.sin_turno || []).map(x => `<tr><td>${esc(x.legajo)}</td><td>${esc(x.nombre)}</td><td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td></tr>`).join('') || '<tr><td colspan="4">Todos los legajos de los sectores/funciones configurados tienen turno fijo.</td></tr>';
  $('grupal-meta').textContent = `${$('desde').value} a ${$('hasta').value} · ${n1.length} grupos configurados · ${num(d.total_filas)} jornadas de nómina · ${d.nota || ''}`;
  $('grupal-rows').innerHTML = n1.map((x, i) => `<tr data-g1="${i}" class="selectable-row">
    <td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(x.turno)}</td>
    <td>${esc(x.operacion || 'Pendiente')}</td><td>${esc(x.grupo_productivo || 'Sin grupo productivo')}</td><td>${x.dias}</td><td>${num(x.nomina_total)}</td>
    <td>${num(Math.round(Number(x.operarios_activos) ? Number(x.uc_computables || 0) / Number(x.operarios_activos) : 0))}</td>
    <td>${x.dias_cumplen}</td><td>${money(x.premio_grupal_total)}</td></tr>`).join('') || '<tr><td colspan="10">No hay parámetros grupales activos.</td></tr>';
  document.querySelectorAll('#grupal-rows [data-g1]').forEach(tr => tr.onclick = () => {
    document.querySelectorAll('#grupal-rows tr').forEach(row => row.classList.toggle('hierarchy-selected', row === tr));
    empty('grupal-legajos', 16, 'Seleccioná un día.');
    vaciarActividadGrupal('Seleccioná un día y un legajo de la nómina.');
    const group = n1[Number(tr.dataset.g1)], days = n2.filter(x => sameGroup(x, group));
    $('grupal-dias').innerHTML = days.map((x, i) => `<tr data-g2="${i}" class="selectable-row">
      <td>${esc(x.fecha)}</td><td>${esc(x.operacion || 'Pendiente')} · ${esc(x.unidad_medida)}</td>
      <td>${x.nomina_total}</td><td>${x.activos}</td><td>${x.presentes}</td><td>${x.ausentes_permitidos}</td><td>${x.ausentes_no_permitidos}</td><td>${x.polivalentes}</td>
      <td>${x.nomina_computable}</td><td>${num(x.objetivo_por_operario)}</td>
      <td>${num(Math.round(Number(x.operarios_promedio) ? Number(x.uc_computables || 0) / Number(x.operarios_promedio) : 0))}</td>
      <td>${num(x.uc_computables)}</td><td>${x.evaluable ? num(x.target) : 'Pendiente'}</td>
      <td>${esc(x.estado)}</td><td>${x.beneficiarios}</td><td>${money(x.premio_grupal)}</td>
      <td>${money(x.premio_grupal_total)}</td><td>${esc(x.turno)}</td></tr>`).join('') || '<tr><td colspan="18">Sin días.</td></tr>';
    document.querySelectorAll('#grupal-dias [data-g2]').forEach(dr => dr.onclick = () => {
      document.querySelectorAll('#grupal-dias tr').forEach(row => row.classList.toggle('hierarchy-selected', row === dr));
      const day = days[Number(dr.dataset.g2)], people = n3.filter(x => sameGroup(x, day) && x.fecha === day.fecha);
      vaciarActividadGrupal('Seleccioná un legajo de la nómina.');
      $('grupal-legajos').innerHTML = people.map(x => `<tr data-g3="${esc(x.legajo)}" class="selectable-row">
        <td>${esc(x.fecha)}</td><td>${esc(x.legajo)}</td><td>${esc(x.nombre)}</td>
        <td>${esc(x.turno_fijo)}</td><td>${esc(x.asistencia)}</td>
        <td>${esc(x.ausencia || '—')}</td><td>${x.asistencia === 'Ausente' ? (x.ausencia_permitida ? 'Sí' : 'No') : '—'}</td>
        <td>${x.es_polivalencia ? 'Sí' : 'No'}</td><td>${x.tiene_actividad ? 'Sí' : 'No'}</td><td>${esc(x.motivo_inclusion)}</td><td>${x.pendiente_calculo ? 'Pendiente' : (x.integra_meta ? 'Sí' : 'No')}</td>
        <td>${num(x.uc_brutas)}</td><td>${num(x.uc_computables)}</td><td>${x.beneficiario ? 'Sí' : 'No'}</td>
        <td>${x.pendiente_calculo || (x.beneficiario && !day.evaluable) ? 'Pendiente' : (x.cobra ? 'Sí' : 'No')}</td><td>${money(x.premio_grupal)}</td></tr>`).join('') || '<tr><td colspan="16">Sin nómina activa.</td></tr>';
      document.querySelectorAll('#grupal-legajos [data-g3]').forEach(row => row.onclick = () => {
        document.querySelectorAll('#grupal-legajos tr').forEach(item => item.classList.toggle('hierarchy-selected', item === row));
        cargarActividadGrupal(day.fecha, row.dataset.g3);
      });
    });
  });
  habilitarOrdenGrupal();
}

document.addEventListener('DOMContentLoaded', () => {
  ordenarDetalleDiario();
  prepararPanelActividadGrupal();
  prepararAccionRecalcularGrupal();
});
