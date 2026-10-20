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
  const rowsOriginales = d.rows || [];
  const gruposVisualesMap = new Map();
  rowsOriginales.forEach(row => {
    const key = [row.sector, row.funcion_legajero, row.operacion_medible, row.division_madre || '', row.grupo_productivo_id ?? '', row.uc_por_operario, row.factor_ausentismo, row.premio_grupal, Boolean(row.activo)].join('||');
    const item = gruposVisualesMap.get(key) || {...row, turnos: []};
    item.turnos.push(String(row.turno || ''));
    gruposVisualesMap.set(key, item);
  });
  const gruposVisuales = [...gruposVisualesMap.values()].map(item => ({...item, turnos: [...new Set(item.turnos)].sort((a,b)=>String(a).localeCompare(String(b),'es',{numeric:true}))}));
  $('param-grupal-rows').innerHTML = gruposVisuales.map((x, i) => `<tr>
    <td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(x.turnos.join(', '))}</td>
    <td><select class="input" data-pg="operacion">${operationOptions(x.operacion_medible)}</select></td>
    <td>${divisionChecks(x.division_madre)}</td>
    <td><select class="input" data-pg="grupo" aria-label="Grupo productivo del parámetro ${i + 1}">${groupOptions(x.grupo_productivo_id)}</select></td>
    <td><input class="input" type="number" min="0" step="any" data-pg="uc" value="${x.uc_por_operario}"></td>
    <td><input class="input" type="number" min="0" max="100" step="any" data-pg="factor" value="${x.factor_ausentismo}"></td>
    <td><input class="input" type="number" min="0" step="0.01" data-pg="premio" value="${x.premio_grupal}"></td>
    <td class="pg-accion"><button class="secondary" data-pg-save="${i}">Guardar grupo</button><button class="secondary" data-pg-delete="${i}" style="margin-top:6px">Quitar grupo</button></td></tr>`).join('') || '<tr><td colspan="10">Sin parámetros configurados.</td></tr>';
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
      const x = gruposVisuales[Number(button.dataset.pgSave)];
      const value = key => row.querySelector(`[data-pg="${key}"]`).value;
      const divisionValues = () => [...row.querySelectorAll('[data-pg="division"] input:checked')].map(input => input.value);
      const payloads = x.turnos.map(turno => ({sector: x.sector, funcion_legajero: x.funcion_legajero, turno,
        activo: Boolean(x.activo), operacion_medible: value('operacion'), uc_por_operario: value('uc'),
        division_madre: divisionValues(), grupo_productivo_id: value('grupo') || null,
        factor_ausentismo: value('factor'), premio_grupal: value('premio')}));
      let ok = true;
      for (const payload of payloads) ok = await save(button, payload) && ok;
      if (ok) await loadParametrosGrupales();
    };
  });
  document.querySelectorAll('[data-pg-delete]').forEach(button => button.onclick = async () => {
    const x = gruposVisuales[Number(button.dataset.pgDelete)];
    if (!confirm(`¿Quitar el parámetro ${x.sector} / ${x.funcion_legajero} / turnos ${x.turnos.join(', ')}?`)) return;
    button.disabled = true;
    try {
      for (const turno of x.turnos) {
        await grupalRequest('parametros-grupales', {sector: x.sector, funcion_legajero: x.funcion_legajero, turno}, 'DELETE');
      }
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
  $('status').textContent = `${gruposVisuales.length} grupos visibles · ${(d.rows || []).length} parámetros por turno · ${pending} pendientes de operación medible`;
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

function diaSemanaCache(fecha) {
  const value = String(fecha || '');
  if (!/^\d{8}$/.test(value)) return '';
  const date = new Date(Number(value.slice(0, 4)), Number(value.slice(4, 6)) - 1, Number(value.slice(6, 8)));
  return ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'][date.getDay()];
}


async function loadEscalasIndividualesGrupales() {
  const data = await grupalRequest('escalas-individuales-grupales', null, 'GET');
  window.escalasIndividualesGrupalesData = data;
  const order = (a, b) => String(a || '').localeCompare(String(b || ''), 'es', {numeric:true, sensitivity:'base'});
  const rowsAll = data.rows || [];
  const sectorSel = $('eig-sector'), funcionSel = $('eig-funcion');
  const currentSector = sectorSel?.value || '', currentFuncion = funcionSel?.value || '';
  const sectores = [...new Set((data.filtros || []).map(x => x.sector).filter(Boolean))].sort(order);
  if (sectorSel && !sectorSel.dataset.bound) {
    sectorSel.dataset.bound = '1';
    sectorSel.onchange = () => { if (funcionSel) funcionSel.value = ''; renderEscalasIndividualesGrupales(); };
  }
  if (funcionSel && !funcionSel.dataset.bound) {
    funcionSel.dataset.bound = '1';
    funcionSel.onchange = renderEscalasIndividualesGrupales;
  }
  if (sectorSel) sectorSel.innerHTML = '<option value="">Todos</option>' + sectores.map(x => `<option value="${esc(x)}" ${x === currentSector ? 'selected' : ''}>${esc(x)}</option>`).join('');
  const funciones = [...new Set((data.filtros || []).filter(x => !sectorSel?.value || x.sector === sectorSel.value).map(x => x.funcion_legajero).filter(Boolean))].sort(order);
  if (funcionSel) funcionSel.innerHTML = '<option value="">Todas</option>' + funciones.map(x => `<option value="${esc(x)}" ${x === currentFuncion ? 'selected' : ''}>${esc(x)}</option>`).join('');
  if ($('eig-generar') && !$('eig-generar').dataset.bound) {
    $('eig-generar').dataset.bound = '1';
    $('eig-generar').onclick = async () => {
      const b = $('eig-generar'); b.disabled = true; b.textContent = 'Generando...';
      try {
        const res = await grupalRequest('escalas-individuales-grupales/generar', {}, 'POST');
        $('eig-meta').textContent = `Generadas ${res.filas} filas para ${res.perfiles} perfiles.`;
        await loadEscalasIndividualesGrupales();
      } catch (e) { $('eig-meta').textContent = e.message; $('eig-meta').style.color = '#C8102E'; }
      finally { b.disabled = false; b.textContent = 'Generar desde grupales'; }
    };
  }
  renderEscalasIndividualesGrupales();
}

let resumenEscalasState = {modo: 'uc', rows: []};

function ensureResumenEscalasView() {
  if ($('view-resumen-escalas')) return;
  const section = document.createElement('section');
  section.className = 'view';
  section.id = 'view-resumen-escalas';
  section.innerHTML = `<div class="view-title"><strong>Resumen de escalas y montos</strong><span>vista consolidada de sólo lectura para revisión gerencial</span></div>
    <div class="resumen-escalas-actions"><button class="primary" id="re-toggle" type="button">Ver montos de premio</button><span class="status" id="re-meta" style="margin:0">Cargando configuración...</span></div>
    <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>División</th><th>Operación</th><th>Segmento</th><th class="num" data-re-head="grupal">Grupal</th><th class="num" data-re-head="n1">Indiv 1</th><th class="num" data-re-head="n2">Indiv 2</th><th class="num" data-re-head="n3">Indiv 3</th><th class="num" data-re-head="n4">Indiv 4</th><th class="num" data-re-head="n5">Indiv 5</th><th>Unidad</th></tr></thead><tbody id="re-rows"><tr><td colspan="10">Cargando...</td></tr></tbody></table></div>`;
  document.querySelector('main .panel').appendChild(section);
  $('re-toggle').onclick = () => {
    resumenEscalasState.modo = resumenEscalasState.modo === 'uc' ? 'monto' : 'uc';
    renderResumenEscalas();
  };
}

function nombreDivisionResumen(sector) {
  const value = String(sector || '').toUpperCase();
  if (value.includes('NOA')) return 'NOA';
  if (value.includes('REFRIG')) return 'Refrigerados';
  if (value.includes('SECO')) return 'Secos';
  return sector || 'Sin división';
}

function segmentoResumenEscalas(item) {
  const funcion = String(item.funcion_legajero || '').toUpperCase();
  if (!String(item.sector || '').toUpperCase().includes('REFRIG')) return '';
  if (funcion.includes('T06') || funcion.includes('CONGELADOS')) return 'Congelados';
  if (funcion === 'ARMADOR' || funcion.includes('AUTOELEVADORISTA')) return 'Otras cámaras';
  return '';
}

function unidadResumenEscalas(unidad) {
  const value = String(unidad || '').toUpperCase();
  return ({PALET: 'Palets', BULTO: 'Bultos', PLU: 'PLUs', HUECO: 'PLUs'})[value] || unidad || '—';
}

function renderResumenEscalas() {
  const modo = resumenEscalasState.modo;
  const rows = resumenEscalasState.rows || [];
  const fmtUc = value => Number(value || 0).toLocaleString('es-AR', {maximumFractionDigits: 0});
  const fmtMonto = value => Number(value || 0).toLocaleString('es-AR', {style: 'currency', currency: 'ARS', maximumFractionDigits: 0});
  const fmt = modo === 'monto' ? fmtMonto : fmtUc;
  $('re-toggle').textContent = modo === 'uc' ? 'Ver montos de premio' : 'Ver valores UC';
  document.querySelectorAll('[data-re-head]').forEach(header => {
    const level = header.dataset.reHead;
    header.textContent = level === 'grupal' ? (modo === 'uc' ? 'Grupal UC' : 'Premio grupal') : (modo === 'uc' ? `Indiv ${level.slice(1)} UC` : `Premio indiv ${level.slice(1)}`);
  });
  $('re-rows').innerHTML = rows.map(item => {
    const value = level => modo === 'uc'
      ? (level === 'grupal' ? item.uc_por_operario : item[`nivel_${level}_desde`])
      : (level === 'grupal' ? item.premio_grupal : item[`nivel_${level}_premio`]);
    return `<tr><td>${esc(nombreDivisionResumen(item.sector))}</td><td>${esc(operacionDisplay(item.operacion_medible))}</td><td class="variant">${esc(item.segmento_resumen || segmentoResumenEscalas(item) || '—')}</td><td class="num mono">${fmt(value('grupal'))}</td><td class="num mono">${fmt(value(1))}</td><td class="num mono">${fmt(value(2))}</td><td class="num mono">${fmt(value(3))}</td><td class="num mono">${fmt(value(4))}</td><td class="num mono">${fmt(value(5))}</td><td>${esc(unidadResumenEscalas(item.unidad_medida))}</td></tr>`;
  }).join('') || '<tr><td colspan="10">No hay perfiles configurados con escalas individuales.</td></tr>';
}

async function loadResumenEscalas() {
  ensureResumenEscalasView();
  document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.id === 'view-resumen-escalas'));
  $('re-meta').textContent = 'Consolidando parámetros y escalas vigentes...';
  const [parametros, escalas] = await Promise.all([
    grupalRequest('parametros-grupales', null, 'GET'),
    grupalRequest('escalas-individuales-grupales', null, 'GET'),
  ]);
  const unidades = new Map((parametros.operaciones || []).map(x => [String(x.operacion || '').toUpperCase(), x.unidad_medida || '']));
  const grupos = new Map();
  (parametros.rows || []).filter(x => Number(x.activo) && x.operacion_medible).forEach(x => {
    const key = [x.sector, x.funcion_legajero, String(x.operacion_medible).toUpperCase(), x.division_madre || ''].join('\u001f');
    if (!grupos.has(key)) grupos.set(key, {
      sector: x.sector, funcion_legajero: x.funcion_legajero, operacion_medible: String(x.operacion_medible).toUpperCase(),
      division_madre: x.division_madre || '', uc_por_operario: Number(x.uc_por_operario || 0),
      premio_grupal: Number(x.premio_grupal || 0), unidad_medida: unidades.get(String(x.operacion_medible).toUpperCase()) || '',
    });
  });
  (escalas.rows || []).forEach(x => {
    const key = [x.sector, x.funcion_legajero, String(x.operacion_medible || '').toUpperCase(), x.division_madre || ''].join('\u001f');
    const item = grupos.get(key);
    const nivel = Number(x.nivel || 0);
    if (!item || nivel < 1 || nivel > 5) return;
    item[`nivel_${nivel}_desde`] = Number(x.desde_uc || 0);
    item[`nivel_${nivel}_premio`] = Number(x.premio || 0);
  });
  const candidatos = [...grupos.values()].filter(item => item.nivel_1_desde != null);
  const valorFirma = item => [item.uc_por_operario, item.premio_grupal,
    ...[1,2,3,4,5].flatMap(nivel => [item[`nivel_${nivel}_desde`], item[`nivel_${nivel}_premio`]]), item.unidad_medida].join('|');
  // Secos administra Zona 1 y Zona 2 por separado, pero la presentación no
  // debe duplicar la misma escala. Sólo se consolidan filas idénticas; si un
  // día difieren, se conserva una fila por sector para hacerlo visible.
  const familias = new Map();
  candidatos.forEach(item => {
    const key = [nombreDivisionResumen(item.sector), operacionDisplay(item.operacion_medible), segmentoResumenEscalas(item)].join('|');
    const list = familias.get(key) || []; list.push(item); familias.set(key, list);
  });
  const consolidados = [];
  familias.forEach(items => {
    const firmas = new Set(items.map(valorFirma));
    if (firmas.size > 1) {
      items.forEach(item => consolidados.push({...item, segmento_resumen: segmentoResumenEscalas(item) || String(item.sector || '').replace(/^CD-/i, '')}));
      return;
    }
    const item = {...items[0]};
    item.sectores_consolidados = [...new Set(items.map(x => x.sector))];
    consolidados.push(item);
  });
  resumenEscalasState.rows = consolidados.sort((a, b) =>
    nombreDivisionResumen(a.sector).localeCompare(nombreDivisionResumen(b.sector), 'es') ||
    operacionDisplay(a.operacion_medible).localeCompare(operacionDisplay(b.operacion_medible), 'es') ||
    String(a.segmento_resumen || segmentoResumenEscalas(a)).localeCompare(String(b.segmento_resumen || segmentoResumenEscalas(b)), 'es'));
  $('re-meta').textContent = `${resumenEscalasState.rows.length} perfiles configurados. La vista no permite editar valores.`;
  renderResumenEscalas();
  prepararOrdenTablaEscalas('re-rows', ['txt','txt','txt','num','num','num','num','num','num','txt']);
}

function renderEscalasIndividualesGrupales() {
  const data = window.escalasIndividualesGrupalesData || {rows: []};
  const sector = $('eig-sector')?.value || '', funcion = $('eig-funcion')?.value || '';
  const rows = (data.rows || []).filter(x => (!sector || x.sector === sector) && (!funcion || x.funcion_legajero === funcion));
  const fmt = v => Number(v || 0).toLocaleString('es-AR', {maximumFractionDigits: 0});
  const fmtPct = v => Number(v || 0).toLocaleString('es-AR', {maximumFractionDigits: 2});
  $('eig-meta').style.color = '';
  $('eig-meta').textContent = `${rows.length} tramos agrupados. Se administran una vez por sector/función/operación/división y se replican internamente a los turnos: ${[...new Set(rows.flatMap(x => x.turnos || []))].sort().join(', ') || '—'}.`;
  $('eig-rows').innerHTML = rows.map((x, i) => `<tr data-eig-group-key="${esc([x.sector,x.funcion_legajero,x.operacion_medible,x.division_madre||''].join('||'))}">
    <td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(x.turnos_label || x.turno || 'Todos')}</td><td>${esc(operacionDisplay(x.operacion_medible))}</td><td>${esc(x.division_madre_label || x.division_madre || '—')}</td>
    <td class="mono">${fmt(x.uc_por_operario)}</td><td class="mono">${esc(x.nivel)}</td>
    <td><input class="input" type="number" step="0.01" min="0" data-eig="pct" value="${esc(x.pct_sobre_anterior || '')}"></td>
    <td class="mono" data-eig-calc="desde">${fmt(x.desde_uc)}</td>
    <td class="mono" data-eig-calc="hasta">${x.hasta_uc ? fmt(x.hasta_uc) : 'Sin tope'}</td>
    <td><input class="input" type="number" step="0.01" data-eig="premio" value="${esc(x.premio)}"></td>
    <td>${esc(x.origen)}</td><td><button class="secondary" data-eig-save="${i}">Guardar grupo</button></td></tr>`).join('') || '<tr><td colspan="13">Sin escalas. Usá Generar desde grupales.</td></tr>';
  const recalcularGrupoDom = groupKey => {
    const groupRows = [...document.querySelectorAll(`#eig-rows tr[data-eig-group-key="${CSS.escape(groupKey)}"]`)];
    if (!groupRows.length) return;
    let valor = Number((rows.find(x => [x.sector,x.funcion_legajero,x.operacion_medible,x.division_madre||''].join('||') === groupKey)?.uc_por_operario) || 0);
    const desde = [];
    groupRows.sort((a,b)=>Number(a.cells[6].textContent)-Number(b.cells[6].textContent)).forEach((tr, idx) => {
      const pct = Number(tr.querySelector('[data-eig="pct"]')?.value || 0);
      valor = Math.ceil(valor * (1 + pct / 100));
      desde[idx] = valor;
    });
    groupRows.sort((a,b)=>Number(a.cells[6].textContent)-Number(b.cells[6].textContent)).forEach((tr, idx) => {
      tr.querySelector('[data-eig-calc="desde"]').textContent = fmt(desde[idx]);
      tr.querySelector('[data-eig-calc="hasta"]').textContent = idx < groupRows.length - 1 ? fmt(desde[idx + 1]) : 'Sin tope';
    });
  };
  document.querySelectorAll('#eig-rows input[data-eig="pct"]').forEach(input => input.oninput = () => recalcularGrupoDom(input.closest('tr').dataset.eigGroupKey));
  document.querySelectorAll('[data-eig-save]').forEach(button => button.onclick = async () => {
    const x = rows[Number(button.dataset.eigSave)], groupKey = [x.sector,x.funcion_legajero,x.operacion_medible,x.division_madre||''].join('||');
    const groupRows = [...document.querySelectorAll(`#eig-rows tr[data-eig-group-key="${CSS.escape(groupKey)}"]`)].sort((a,b)=>Number(a.cells[6].textContent)-Number(b.cells[6].textContent));
    const niveles = groupRows.map(tr => ({
      nivel: Number(tr.cells[6].textContent || 0),
      pct_sobre_anterior: tr.querySelector('[data-eig="pct"]').value,
      premio: tr.querySelector('[data-eig="premio"]').value
    }));
    button.disabled = true; button.textContent = 'Guardando...';
    try {
      const res = await grupalRequest('escalas-individuales-grupales', {modo:'porcentajes_perfil', sector:x.sector, funcion_legajero:x.funcion_legajero,
        operacion_medible:x.operacion_medible, division_madre:x.division_madre || '', niveles}, 'PUT');
      button.textContent = `Guardado (${res.turnos_actualizados || 0} turnos)`;
      await loadEscalasIndividualesGrupales();
    } catch (e) { button.textContent = 'Error'; $('eig-meta').textContent = e.message; $('eig-meta').style.color = '#C8102E'; }
    finally { button.disabled = false; }
  });
  prepararOrdenTablaEscalas('eig-rows', ['txt','txt','txt','txt','txt','num','num','num','num','num','num','txt','txt']);
}

async function loadParticipacionIndividual() {
  if (!$('pig-consultar').dataset.bound) {
    $('pig-consultar').dataset.bound = '1';
    $('pig-consultar').onclick = () => loadParticipacionIndividual().catch(e => { $('pig-meta').textContent = e.message; $('pig-meta').style.color = '#C8102E'; });
    $('pig-sector').onchange = () => renderParticipacionFiltros(window.participacionIndividualData || {filtros: []});
  }
  $('pig-meta').style.color = '';
  $('pig-meta').textContent = 'Calculando participación por niveles...';
  const params = qs({fecha_desde:$('desde').value, fecha_hasta:$('hasta').value, sector:$('pig-sector').value || '', funcion_legajero:$('pig-funcion').value || ''});
  const data = await grupalRequest('participacion-escalas-individuales?' + params, null, 'GET');
  window.participacionIndividualData = data;
  renderParticipacionFiltros(data);
  renderParticipacionIndividual(data);
}

function renderParticipacionFiltros(data) {
  const order = (a, b) => String(a || '').localeCompare(String(b || ''), 'es', {numeric:true, sensitivity:'base'});
  const sector = $('pig-sector')?.value || '', funcion = $('pig-funcion')?.value || '';
  const sectores = [...new Set((data.filtros || []).map(x => x.sector).filter(Boolean))].sort(order);
  $('pig-sector').innerHTML = '<option value="">Todos</option>' + sectores.map(x => `<option value="${esc(x)}" ${x === sector ? 'selected' : ''}>${esc(x)}</option>`).join('');
  const funciones = [...new Set((data.filtros || []).filter(x => !sector || x.sector === sector).map(x => x.funcion_legajero).filter(Boolean))].sort(order);
  $('pig-funcion').innerHTML = '<option value="">Todas</option>' + funciones.map(x => `<option value="${esc(x)}" ${x === funcion ? 'selected' : ''}>${esc(x)}</option>`).join('');
}

function renderParticipacionIndividual(data) {
  const fmt = v => Number(v || 0).toLocaleString('es-AR', {maximumFractionDigits:0});
  const resumen = data.resumen || [], rows = data.rows || [];
  $('pig-meta').textContent = rows.length ? `${rows.length} días/perfil · ${data.nota || ''}` : 'Sin datos. Generá las escalas o revisá los filtros.';
  const cols = ['grupal','nivel_0','nivel_1','nivel_2','nivel_3','nivel_4','nivel_5'];
  $('pig-resumen').innerHTML = resumen.map(x => `<tr><td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(x.turno)}</td><td>${fmt(x.dias)}</td><td>${fmt(x.evaluados)}</td>${cols.map(c => `<td>${fmt(x[c])}</td>`).join('')}</tr>`).join('') || '<tr><td colspan="12">Sin resumen.</td></tr>';
  $('pig-rows').innerHTML = rows.map(x => `<tr><td>${esc(x.fecha)}</td><td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(x.turno)}</td><td>${fmt(x.evaluados)}</td>${cols.map(c => `<td>${fmt(x[c])}</td>`).join('')}</tr>`).join('') || '<tr><td colspan="12">Sin detalle.</td></tr>';
  renderParticipacionChart(resumen);
  prepararOrdenTablaEscalas('pig-resumen', ['txt','txt','txt','num','num','num','num','num','num','num','num','num']);
  prepararOrdenTablaEscalas('pig-rows', ['txt','txt','txt','txt','num','num','num','num','num','num','num','num']);
}

function renderParticipacionChart(rows) {
  const target = $('pig-chart');
  const fmt = v => Number(v || 0).toLocaleString('es-AR', {maximumFractionDigits:0});
  if (!target) return;
  if (!rows.length) { target.innerHTML = '<div class="status">Sin datos para graficar.</div>'; return; }
  // Eventos legajo-día: Grupal viene del cálculo grupal; N1..N5 son
  // acumulados por umbral individual.
  const labels = ['Grupal','Nivel 1','Nivel 2','Nivel 3','Nivel 4','Nivel 5'];
  const shortLabels = ['Grupal','N1','N2','N3','N4','N5'];
  const colors = ['#B8C0BC','#8FBA9C','#6EA6D9','#D9B86E','#C98A7A','#7D67B1'];
  const totals = [
    rows.reduce((acc, x) => acc + Number(x.grupal || 0), 0),
    ...[1,2,3,4,5].map(n => rows.reduce((acc, x) => acc + Number(x[`nivel_${n}`] || 0), 0))
  ];
  const totalEventos = totals.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...totals);
  const w = 920, h = 310, ml = 72, mr = 58, mb = 48, mt = 24, gap = 18;
  const barW = (w - ml - mr - gap * (totals.length - 1)) / totals.length;
  const y = v => mt + (1 - v / max) * (h - mt - mb);
  target.innerHTML = `<svg viewBox="0 0 ${w} ${h}" class="ep-svg" role="img" aria-label="Pareto de eventos por nivel individual">
    <line x1="${ml}" x2="${w-mr}" y1="${h-mb}" y2="${h-mb}" stroke="#D4DBD8"/>
    ${totals.map((v,i) => { const x=ml+i*(barW+gap), yy=y(v), bh=h-mb-yy, pct=totalEventos ? v/totalEventos*100 : 0; return `<rect x="${x}" y="${yy}" width="${barW}" height="${bh}" fill="${colors[i]}"><title>${labels[i]}: ${fmt(v)} eventos (${pct.toLocaleString('es-AR',{maximumFractionDigits:1})}%)</title></rect><text x="${x+barW/2}" y="${Math.max(mt+10, yy-6)}" text-anchor="middle">${fmt(v)}</text><text x="${x+barW/2}" y="${h-20}" text-anchor="middle">${shortLabels[i]}</text>`; }).join('')}
    <text x="${ml-10}" y="${mt}" text-anchor="end">Eventos</text>
  </svg><div class="status">Total eventos legajo-día evaluados: ${fmt(totalEventos)}. “Grupal” son eventos que cobran grupal. N1..N5 son acumulados por umbral individual.</div>`;
}


async function loadUmbralesGrupales(consultar = false) {
  if (!$('ug-consultar').dataset.bound) {
    $('ug-consultar').dataset.bound = '1';
    $('ug-consultar').onclick = () => loadUmbralesGrupales(true).catch(e => { $('ug-meta').textContent = e.message; $('ug-meta').style.color = '#C8102E'; });
    $('ug-sector').onchange = () => { renderUmbralesFiltros(window.umbralesGrupalesCatalogo || window.umbralesGrupalesData || {filtros: []}); limpiarUmbralesGrupales('Elegí filtros y presioná Consultar.'); };
    $('ug-operacion').onchange = () => { renderUmbralesFiltros(window.umbralesGrupalesCatalogo || window.umbralesGrupalesData || {filtros: []}); limpiarUmbralesGrupales('Elegí filtros y presioná Consultar.'); };
    $('ug-funcion').onchange = () => limpiarUmbralesGrupales('Elegí filtros y presioná Consultar.');
    $('ug-habiles').onchange = () => limpiarUmbralesGrupales('Elegí filtros y presioná Consultar.');
  }
  $('ug-meta').style.color = '';
  const params = qs({fecha_desde:$('desde').value, fecha_hasta:$('hasta').value, sector: consultar ? ($('ug-sector').value || '') : '', operacion: consultar ? ($('ug-operacion').value || '') : '', funcion_legajero: consultar ? ($('ug-funcion').value || '') : '', excluir_fines:$('ug-habiles').checked ? 1 : 0});
  $('ug-meta').textContent = consultar ? 'Calculando umbrales desde cálculo grupal diario...' : 'Cargando filtros disponibles...';
  const data = await grupalRequest('umbrales-grupales?' + params, null, 'GET');
  if (!consultar) {
    window.umbralesGrupalesCatalogo = data;
    renderUmbralesFiltros(data);
    limpiarUmbralesGrupales('Elegí filtros y presioná Consultar.');
    return;
  }
  window.umbralesGrupalesData = data;
  window.umbralesGrupalesCatalogo = {...(window.umbralesGrupalesCatalogo || {}), filtros: data.filtros || []};
  renderUmbralesFiltros(data);
  renderUmbralesGrupales(data);
}

function limpiarUmbralesGrupales(mensaje) {
  if ($('ug-meta')) $('ug-meta').textContent = mensaje;
  if ($('ug-cards')) $('ug-cards').innerHTML = '';
  if ($('ug-chart')) $('ug-chart').innerHTML = '<div class="status">Sin consulta ejecutada.</div>';
  if ($('ug-resumen')) $('ug-resumen').innerHTML = '<tr><td colspan="10">Consultá para cargar.</td></tr>';
  if ($('ug-rows')) $('ug-rows').innerHTML = '<tr><td colspan="10">Consultá para cargar.</td></tr>';
}
function renderUmbralesFiltros(data) {
  const order = (a, b) => String(a || '').localeCompare(String(b || ''), 'es', {numeric:true, sensitivity:'base'});
  const sector = $('ug-sector')?.value || '', operacion = $('ug-operacion')?.value || '', funcion = $('ug-funcion')?.value || '';
  const filtros = data.filtros || [];
  const sectores = [...new Set(filtros.map(x => x.sector).filter(Boolean))].sort(order);
  $('ug-sector').innerHTML = '<option value="">Todos</option>' + sectores.map(x => `<option value="${esc(x)}" ${x === sector ? 'selected' : ''}>${esc(x)}</option>`).join('');
  const operaciones = [...new Set(filtros.filter(x => !sector || x.sector === sector).map(x => x.operacion).filter(Boolean))].sort(order);
  $('ug-operacion').innerHTML = '<option value="">Todas</option>' + operaciones.map(x => `<option value="${esc(x)}" ${x === operacion ? 'selected' : ''}>${esc(operacionDisplay(x))}</option>`).join('');
  const funciones = [...new Set(filtros.filter(x => (!sector || x.sector === sector) && (!operacion || x.operacion === operacion)).map(x => x.funcion_legajero).filter(Boolean))].sort(order);
  $('ug-funcion').innerHTML = '<option value="">Todas</option>' + funciones.map(x => `<option value="${esc(x)}" ${x === funcion ? 'selected' : ''}>${esc(x)}</option>`).join('');
}

function renderUmbralesGrupales(data) {
  const fmt = v => v == null ? '—' : Number(v || 0).toLocaleString('es-AR', {maximumFractionDigits:0});
  const pct = (num, den) => den ? `${Number(num / den * 100).toLocaleString('es-AR', {maximumFractionDigits:1})}%` : '—';
  const resumen = data.resumen || [], rows = data.detalle || [];
  const series = data.series || [];
  const total = resumen[0] || {};
  $('ug-meta').textContent = rows.length ? `${fmt(data.dias_periodo || total.dias_evaluados)} días del período · ${data.nota || ''}` : 'Sin datos para los filtros. Actualizá cálculo grupal diario o revisá sector/operación.';
  const referenciaPorcentaje = (fila, porcentaje, puntos = []) => {
    const diasApi = Number(fila[`dias_objetivo_${porcentaje}`] || 0);
    const ucApi = fila[`umbral_${porcentaje}`];
    if (diasApi > 0 && ucApi != null) return {dias: diasApi, uc: ucApi};
    const dias = Math.ceil(puntos.length * porcentaje / 100);
    const punto = puntos[dias - 1];
    return {dias, uc: punto?.uc ?? null};
  };
  const renderCards = indice => {
    const perfil = resumen[indice] || {};
    const puntos = series[indice]?.puntos || [];
    const umbralPorcentaje = porcentaje => {
      const ref = referenciaPorcentaje(perfil, porcentaje, puntos);
      return `${fmt(ref.uc)} UC<br><small>${fmt(ref.dias)} días del período</small>`;
    };
    $('ug-cards').innerHTML = [
      ['Días evaluados', fmt(perfil.dias_evaluados)],
      ['Cobran hoy', `${fmt(perfil.dias_cobra_actual)} (${pct(perfil.dias_cobra_actual, perfil.dias_evaluados)})`],
      ['UC para cobrar el 25%', umbralPorcentaje(25)],
      ['UC para cobrar el 50%', umbralPorcentaje(50)],
      ['UC para cobrar el 75%', umbralPorcentaje(75)],
    ].map(([label,value]) => `<article class="ug-card"><span>${label}</span><strong>${value}</strong></article>`).join('');
  };
  renderCards(0);
  const celdaPorcentaje = (x, porcentaje, indice) => { const ref = referenciaPorcentaje(x, porcentaje, series[indice]?.puntos || []); return `${fmt(ref.uc)} UC<br><small>${fmt(ref.dias)} días</small>`; };
  document.querySelectorAll('#ug-resumen thead th').forEach((th, index) => {
    if (index === 4) th.textContent = 'UC al 25%';
    if (index === 5) th.textContent = 'UC al 50%';
    if (index === 6) th.textContent = 'UC al 75%';
  });
  $('ug-resumen').innerHTML = resumen.map((x,i) => {
    const serie = (data.series || [])[i] || {};
    return `<tr data-ug-serie="${i}" class="selectable-row"><td>${esc(serie.funcion_legajero || x.perfil || x.turno)}</td><td>${fmt(x.dias_evaluados)}</td><td>${fmt(x.dias_cobra_actual)}</td><td>${fmt(x.objetivo_actual_promedio)}</td><td>${celdaPorcentaje(x, 25, i)}</td><td>${celdaPorcentaje(x, 50, i)}</td><td>${celdaPorcentaje(x, 75, i)}</td><td>${fmt(x.mejor_umbral)}</td><td>${fmt(x.mediana_umbral)}</td><td>${fmt(x.peor_umbral)}</td></tr>`;
  }).join('') || '<tr><td colspan="10">Sin resumen.</td></tr>';
  $('ug-rows').innerHTML = rows.map(x => `<tr><td>${esc(x.fecha)}</td><td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(operacionDisplay(x.operacion))}</td><td>${esc(x.division_madre_label || x.division_madre || '—')}</td><td>${esc(x.turno)}</td><td>${fmt(x.nomina_computable)}</td><td>${fmt(x.produccion)}</td><td>${fmt(x.objetivo_actual)}</td><td>${fmt(x.umbral_uc)}</td><td>${x.cobra_actual ? 'Sí' : 'No'}</td></tr>`).join('') || '<tr><td colspan="11">Sin detalle.</td></tr>';
  const mostrarSerie = indice => {
    const serie = series[indice];
    renderCards(indice);
    renderUmbralesChart(serie ? [serie] : [], serie?.objetivo_actual ?? resumen[indice]?.objetivo_actual_promedio);
    if (series.length > 1 && $('ug-chart')) {
      const selector = document.createElement('div');
      selector.className = 'status';
      selector.style.margin = '0 0 8px';
      selector.innerHTML = `<strong>Perfil del gráfico:</strong> ${series.map((item, i) => `<button type="button" class="secondary" data-ug-profile="${i}" ${i === indice ? 'disabled' : ''}>${esc(item.funcion_legajero || item.perfil || `Perfil ${i + 1}`)}</button>`).join(' ')}`;
      $('ug-chart').prepend(selector);
      selector.querySelectorAll('[data-ug-profile]').forEach(button => button.onclick = () => {
        const next = Number(button.dataset.ugProfile || 0);
        document.querySelectorAll('[data-ug-serie]').forEach(row => row.classList.toggle('hierarchy-selected', Number(row.dataset.ugSerie) === next));
        mostrarSerie(next);
      });
    }
  };
  mostrarSerie(0);
  document.querySelectorAll('[data-ug-serie]').forEach(row => row.onclick = () => {
    document.querySelectorAll('[data-ug-serie]').forEach(r => r.classList.toggle('hierarchy-selected', r === row));
    const idx = Number(row.dataset.ugSerie || 0);
    mostrarSerie(idx);
  });
  document.querySelector('[data-ug-serie]')?.classList.add('hierarchy-selected');
  prepararOrdenTablaEscalas('ug-resumen', ['txt','num','num','num','num','num','num','num','num','num']);
  prepararOrdenTablaEscalas('ug-rows', ['txt','txt','txt','txt','txt','txt','num','num','num','num','txt']);
}

function renderUmbralesChart(series, objetivoActivo = null) {
  const target = $('ug-chart');
  const fmt = v => Number(v || 0).toLocaleString('es-AR', {maximumFractionDigits:0});
  if (!target) return;
  const serie = (series || [])[0];
  const puntos = serie?.puntos || [];
  if (!puntos.length) { target.innerHTML = '<div class="status">Sin datos para graficar.</div>'; return; }
  const maxX = Math.max(1, ...puntos.map(p => Number(p.dias || 0)));
  const objetivoNum = objetivoActivo == null ? null : Number(objetivoActivo || 0);
  const maxY = Math.max(1, ...puntos.map(p => Number(p.uc || 0)), objetivoNum || 0);
  const tituloGrafico = [serie?.sector, serie?.funcion_legajero].filter(Boolean).join(' - ');
  const refsDesdeApi = (serie?.referencias || []).filter(r => Number(r?.dias || 0) >= 1 && Number(r?.dias || 0) <= maxX);
  const refsPct = refsDesdeApi.length ? refsDesdeApi : [25, 50, 75].map(porcentaje => {
    const dias = Math.ceil(puntos.length * porcentaje / 100);
    const punto = puntos[dias - 1];
    return {porcentaje, dias, uc: punto?.uc ?? 0};
  });
  const refs = [...new Set([...refsPct.map(r => Number(r.dias)), maxX])].sort((a, b) => a - b);
  const referenciaPorDia = new Map(refsPct.map(r => [Number(r.dias), r]));
  if (!refs.includes(maxX)) refs.push(maxX);
  const ySteps = 5;
  const w = 980, h = 390, ml = 74, mr = 34, mt = 32, mb = 58;
  const x = v => ml + (Number(v || 0) - 1) / Math.max(1, maxX - 1) * (w - ml - mr);
  const y = v => mt + (1 - Number(v || 0) / maxY) * (h - mt - mb);
  const line = pts => pts.map((p,i) => `${i ? 'L' : 'M'}${x(p.dias).toFixed(1)},${y(p.uc).toFixed(1)}`).join(' ');
  const areaPath = `${line(puntos)} L${x(puntos[puntos.length-1].dias).toFixed(1)},${h-mb} L${x(puntos[0].dias).toFixed(1)},${h-mb} Z`;
  const yGrid = Array.from({length:ySteps+1},(_,i)=>maxY/ySteps*i).filter(v=>v>0);
  target.innerHTML = `<svg viewBox="0 0 ${w} ${h}" class="ep-svg" role="img" aria-label="Umbral promedio UC por cantidad de días con premio" style="max-width:100%;height:auto;background:#fff">
    <rect x="0" y="0" width="${w}" height="${h}" fill="#fff"/>
    <text x="${w / 2}" y="18" text-anchor="middle" font-size="13" font-weight="700" fill="#17202A">${esc(tituloGrafico || 'Umbrales grupales')}</text>
    ${yGrid.map(v => `<line x1="${ml}" x2="${w-mr}" y1="${y(v)}" y2="${y(v)}" stroke="#EEF2F0"/><text x="${ml-10}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="#5C6773">${fmt(v)}</text>`).join('')}
    ${refs.map(v => { const ref = referenciaPorDia.get(Number(v)); const label = ref ? `${ref.porcentaje}% (${v})` : v; return `<line x1="${x(v)}" x2="${x(v)}" y1="${mt}" y2="${h-mb}" stroke="#F1F5F3"/><text x="${x(v)}" y="${h-35}" text-anchor="middle" font-size="11" fill="#5C6773">${label}</text>`; }).join('')}
    <line x1="${ml}" x2="${w-mr}" y1="${h-mb}" y2="${h-mb}" stroke="#C8D1CD"/><line x1="${ml}" x2="${ml}" y1="${mt}" y2="${h-mb}" stroke="#C8D1CD"/>
    ${objetivoNum ? `<line x1="${ml}" x2="${w-mr}" y1="${y(objetivoNum)}" y2="${y(objetivoNum)}" stroke="#DC2626" stroke-width="2" stroke-dasharray="8 5"/><text x="${w-mr-6}" y="${Math.max(mt+12, y(objetivoNum)-7)}" text-anchor="end" font-size="12" fill="#B42318">Umbral activo ${fmt(objetivoNum)} UC</text>` : ''}
    <path d="${areaPath}" fill="#2563EB" opacity="0.14"/>
    <path d="${line(puntos)}" fill="none" stroke="#2563EB" stroke-width="3.5"/>
    ${puntos.filter(p => refs.includes(Number(p.dias))).map(p => { const ref = referenciaPorDia.get(Number(p.dias)); return `<circle cx="${x(p.dias)}" cy="${y(p.uc)}" r="4" fill="#fff" stroke="#2563EB" stroke-width="2"><title>${p.dias} días: ${fmt(p.uc)} UC</title></circle>${ref ? `<text x="${x(p.dias)}" y="${y(p.uc)-9}" text-anchor="middle" font-size="11" fill="#1D4ED8">${ref.porcentaje}% · ${fmt(p.uc)}</text>` : ''}`; }).join('')}
    <g class="ug-hover" style="display:none;pointer-events:none"><line class="ug-hover-line" y1="${mt}" y2="${h-mb}" stroke="#1D4ED8" stroke-dasharray="4 4"/><circle class="ug-hover-dot" r="5" fill="#fff" stroke="#1D4ED8" stroke-width="2"/><rect class="ug-hover-box" rx="4" ry="4" width="122" height="38" fill="#111827" opacity="0.92"/><text class="ug-hover-text" fill="#fff" font-size="11" font-family="IBM Plex Mono, monospace"></text></g>
    <rect class="ug-hover-capture" x="${ml}" y="${mt}" width="${w-ml-mr}" height="${h-mt-mb}" fill="transparent"/>
    <text x="${ml-10}" y="${mt-10}" text-anchor="end" font-size="12" fill="#344054">UC objetivo</text><text x="${w/2}" y="${h-12}" text-anchor="middle" font-size="12" fill="#344054">Días con premio</text>
  </svg><div class="status">Serie: ${esc(serie?.perfil || serie?.turno || 'Perfil')}. La línea roja marca el umbral activo del perfil. Las marcas 10, 15 y 20 indican el valor de UC objetivo para cobrar esa cantidad de días. Mové el mouse sobre la curva para ver valores.</div>`;
  const svg = target.querySelector('svg');
  const hover = target.querySelector('.ug-hover');
  const capture = target.querySelector('.ug-hover-capture');
  const hLine = target.querySelector('.ug-hover-line');
  const hDot = target.querySelector('.ug-hover-dot');
  const hBox = target.querySelector('.ug-hover-box');
  const hText = target.querySelector('.ug-hover-text');
  const nearestPoint = clientX => {
    const rect = svg.getBoundingClientRect();
    const sx = (clientX - rect.left) / rect.width * w;
    const dia = Math.max(1, Math.min(maxX, Math.round(1 + (sx - ml) / Math.max(1, (w - ml - mr)) * Math.max(1, maxX - 1))));
    return puntos.reduce((best, p) => Math.abs(Number(p.dias) - dia) < Math.abs(Number(best.dias) - dia) ? p : best, puntos[0]);
  };
  capture.addEventListener('mousemove', event => {
    const p = nearestPoint(event.clientX), px = x(p.dias), py = y(p.uc);
    hover.style.display = '';
    hLine.setAttribute('x1', px); hLine.setAttribute('x2', px);
    hDot.setAttribute('cx', px); hDot.setAttribute('cy', py);
    const boxX = Math.min(w - mr - 122, Math.max(ml + 4, px + 10));
    const boxY = Math.max(mt + 4, py - 48);
    hBox.setAttribute('x', boxX); hBox.setAttribute('y', boxY);
    hText.setAttribute('x', boxX + 8); hText.setAttribute('y', boxY + 15);
    hText.innerHTML = `<tspan x="${boxX + 8}" dy="0">${p.dias} días</tspan><tspan x="${boxX + 8}" dy="16">${fmt(p.uc)} UC</tspan>`;
  });
  capture.addEventListener('mouseleave', () => { hover.style.display = 'none'; });
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
  const titulos = [
    'Fecha', 'Día', 'Operación / unidad', 'Producción computable', 'Meta del día',
    'Resultado', 'Nómina fija', 'Activos del día', 'Presentes', 'Ausentes permitidos',
    'Ausentes no permitidos', 'Polivalentes', 'Nómina computable', 'Objetivo por operario',
    'Producción promedio computable', 'Beneficiarios', 'Premio por beneficiario',
    'Premio total', 'Turno', 'Análisis'
  ];
  titulos.forEach((titulo, index) => { header.cells[index].textContent = titulo; });
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
  $('grupal-rows').innerHTML = '<tr><td colspan="11">Calculando...</td></tr>';
  $('grupal-dias').innerHTML = '<tr><td colspan="20">Seleccioná un grupo.</td></tr>';
  $('grupal-legajos').innerHTML = '<tr><td colspan="16">Seleccioná un día.</td></tr>';
  $('grupal-sin-turno').innerHTML = '';
  $('grupal-meta').textContent = 'Consultando nómina y asistencia...';
  const d = await grupalRequest('calculo-grupal?' + qs({fecha_desde: $('desde').value, fecha_hasta: $('hasta').value}));
  const money = value => Number(value || 0).toLocaleString('es-AR', {style: 'currency', currency: 'ARS'});
  const num = value => Number(value || 0).toLocaleString('es-AR', {maximumFractionDigits: 6});
  const analisisGrupo = x => {
    if (!Number(x.nomina_total || 0)) return 'Parámetro activo sin nómina asociada.';
    if (!Number(x.target || 0)) return 'Sin meta calculada; revisar nómina o configuración.';
    const cumplimiento = Number(x.cumplimiento || 0);
    const dias = Number(x.dias || 0), cumplen = Number(x.dias_cumplen || 0);
    const promedio = Number(x.operarios_activos || 0) ? Number(x.uc_computables || 0) / Number(x.operarios_activos || 1) : 0;
    if (cumplimiento >= 100 && cumplen >= Math.ceil(dias * 0.7)) return 'Cumple acumulado y sostiene buena frecuencia de días con premio.';
    if (cumplimiento >= 100) return 'Cumple acumulado, pero con días irregulares debajo de meta.';
    if (cumplen === 0) return `No alcanza: promedio ${num(Math.round(promedio))} por operario y ningún día supera la meta.`;
    return `No alcanza acumulado: ${cumplen}/${dias} días superan; revisar brechas diarias y productividad promedio.`;
  };
  const analisisDia = x => {
    if (!x.evaluable) return 'Pendiente: faltan datos completos para evaluar.';
    if (!Number(x.nomina_total || 0)) return 'Sin nómina fija para este perfil.';
    if (x.cumple) return 'Supera la meta; el plantel habilitado cobra premio grupal.';
    const partes = [];
    const objetivoNeto = Number(x.objetivo_por_operario || 0) * (1 - Number(x.factor_ausentismo || 0) / 100);
    const promedio = Number(x.operarios_promedio || 0) ? Number(x.uc_computables || 0) / Number(x.operarios_promedio || 1) : 0;
    if (objetivoNeto && promedio < objetivoNeto * 0.8) partes.push('producción promedio muy por debajo del objetivo');
    else if (objetivoNeto && promedio < objetivoNeto) partes.push('producción promedio debajo del objetivo');
    if (Number(x.ausentes_no_permitidos || 0) > 0) partes.push(`${x.ausentes_no_permitidos} ausente(s) no permitido(s) integran meta con 0`);
    if (Number(x.polivalentes || 0) > 0) partes.push(`${x.polivalentes} polivalente(s) salen de la meta`);
    const sinProd = Math.max(0, Number(x.presentes || 0) - Number(x.beneficiarios || 0) - Number(x.polivalentes || 0));
    if (sinProd > 0) partes.push(`${sinProd} presente(s) sin producción computable o no habilitados`);
    if (Number(x.nomina_computable || 0) <= 2) partes.push('nómina computable muy chica');
    return partes.join('; ') || 'No supera por brecha menor; revisar detalle por legajo.';
  };
  const empty = (id, columns, message) => { $(id).innerHTML = `<tr><td colspan="${columns}">${message}</td></tr>`; };
  const n1 = d.nivel_1 || [], n2 = d.nivel_2 || [], n3 = d.nivel_3 || [];
  const sameGroup = (a, b) => a.sector === b.sector && a.funcion_legajero === b.funcion_legajero && a.turno === b.turno;
  empty('grupal-dias', 20, 'Seleccioná un grupo.');
  empty('grupal-legajos', 16, 'Seleccioná un día.');
  vaciarActividadGrupal('Seleccioná un día y un legajo de la nómina.');
  $('grupal-sin-turno').innerHTML = (d.sin_turno || []).map(x => `<tr><td>${esc(x.legajo)}</td><td>${esc(x.nombre)}</td><td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td></tr>`).join('') || '<tr><td colspan="4">Todos los legajos de los sectores/funciones configurados tienen turno fijo.</td></tr>';
  $('grupal-meta').textContent = `${$('desde').value} a ${$('hasta').value} · ${n1.length} grupos configurados · ${num(d.total_filas)} jornadas de nómina · ${d.nota || ''}`;
  $('grupal-rows').innerHTML = n1.map((x, i) => `<tr data-g1="${i}" class="selectable-row">
    <td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(x.turno)}</td>
    <td>${esc(x.operacion || 'Pendiente')}</td><td>${esc(x.grupo_productivo || 'Sin grupo productivo')}</td><td>${x.dias}</td><td>${num(x.nomina_total)}</td>
    <td>${num(Math.round(Number(x.operarios_activos) ? Number(x.uc_computables || 0) / Number(x.operarios_activos) : 0))}</td>
    <td>${x.dias_cumplen}</td><td>${money(x.premio_grupal_total)}</td><td>${esc(analisisGrupo(x))}</td></tr>`).join('') || '<tr><td colspan="11">No hay parámetros grupales activos.</td></tr>';
  document.querySelectorAll('#grupal-rows [data-g1]').forEach(tr => tr.onclick = () => {
    document.querySelectorAll('#grupal-rows tr').forEach(row => row.classList.toggle('hierarchy-selected', row === tr));
    empty('grupal-legajos', 16, 'Seleccioná un día.');
    vaciarActividadGrupal('Seleccioná un día y un legajo de la nómina.');
    const group = n1[Number(tr.dataset.g1)], days = n2.filter(x => sameGroup(x, group));
    $('grupal-dias').innerHTML = days.map((x, i) => `<tr data-g2="${i}" class="selectable-row">
      <td>${esc(x.fecha)}</td><td>${esc(diaSemanaCache(x.fecha))}</td><td>${esc(x.operacion || 'Pendiente')} · ${esc(x.unidad_medida)}</td>
      <td>${num(x.uc_computables)}</td><td>${x.evaluable ? num(x.target) : 'Pendiente'}</td><td>${esc(x.estado)}</td>
      <td>${x.nomina_total}</td><td>${x.activos}</td><td>${x.presentes}</td><td>${x.ausentes_permitidos}</td><td>${x.ausentes_no_permitidos}</td><td>${x.polivalentes}</td>
      <td>${x.nomina_computable}</td><td>${num(x.objetivo_por_operario)}</td>
      <td>${num(Math.round(Number(x.operarios_promedio) ? Number(x.uc_computables || 0) / Number(x.operarios_promedio) : 0))}</td>
      <td>${x.beneficiarios}</td><td>${money(x.premio_grupal)}</td>
      <td>${money(x.premio_grupal_total)}</td><td>${esc(x.turno)}</td><td>${esc(analisisDia(x))}</td></tr>`).join('') || '<tr><td colspan="20">Sin días.</td></tr>';
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
  // Septiembre ya está materializado en el laboratorio: el escenario inicial
  // debe abarcar ambos meses, sin impedir que el usuario elija otro rango.
  if ($('desde')?.value === '2026-08-01' && $('hasta')?.value === '2026-08-31') {
    $('hasta').value = '2026-09-30';
  }
  ordenarDetalleDiario();
  prepararPanelActividadGrupal();
  prepararAccionRecalcularGrupal();
});

