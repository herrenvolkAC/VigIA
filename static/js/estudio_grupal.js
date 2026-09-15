// Parámetros y navegación del premio grupal: grupo -> día -> nómina completa.
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
    operaciones.map(x => `<option value="${esc(x.operacion)}" ${x.operacion === selected ? 'selected' : ''}>${esc(x.operacion)} · ${esc(x.unidad_medida)}</option>`).join('');
  $('pg-operacion').innerHTML = operationOptions('');
  const grupos = [...(d.grupos_productivos || [])].sort((a, b) => order(a.descripcion, b.descripcion));
  const groupOptions = selected => '<option value="">Sin grupo productivo</option>' +
    (selected != null && !grupos.some(x => String(x.id) === String(selected)) ?
      `<option value="${esc(selected)}" selected>Grupo ${esc(selected)} (fuera de catálogo)</option>` : '') +
    grupos.map(x => `<option value="${esc(x.id)}" ${String(x.id) === String(selected) ? 'selected' : ''}>${esc(x.descripcion)}</option>`).join('');
  $('pg-grupo').innerHTML = groupOptions(null);
  $('param-grupal-rows').innerHTML = (d.rows || []).map((x, i) => `<tr>
    <td>${esc(x.sector)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(x.turno)}</td>
    <td><select class="input" data-pg="operacion">${operationOptions(x.operacion_medible)}</select></td>
    <td><select class="input" data-pg="grupo" aria-label="Grupo productivo del parámetro ${i + 1}">${groupOptions(x.grupo_productivo_id)}</select></td>
    <td><input class="input" type="number" min="0" step="any" data-pg="uc" value="${x.uc_por_operario}"></td>
    <td><input class="input" type="number" min="0" max="100" step="any" data-pg="factor" value="${x.factor_ausentismo}"></td>
    <td><input class="input" type="number" min="0" step="0.01" data-pg="premio" value="${x.premio_grupal}"></td>
    <td class="pg-accion"><button class="secondary" data-pg-save="${i}">Guardar</button><button class="secondary" data-pg-delete="${i}" style="margin-top:6px">Quitar</button></td></tr>`).join('') || '<tr><td colspan="9">Sin parámetros configurados.</td></tr>';
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
    row.querySelectorAll('input,select').forEach(input => input.onchange = () => { button.textContent = 'Guardar'; });
    button.onclick = async () => {
      const x = d.rows[Number(button.dataset.pgSave)];
      const value = key => row.querySelector(`[data-pg="${key}"]`).value;
      await save(button, {sector: x.sector, funcion_legajero: x.funcion_legajero, turno: x.turno,
        activo: Boolean(x.activo), operacion_medible: value('operacion'), uc_por_operario: value('uc'),
        grupo_productivo_id: value('grupo') || null,
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
    if (await save($('pg-alta'), {sector: $('pg-sector').value, funcion_legajero: $('pg-funcion').value,
      turno: $('pg-turno').value, operacion_medible: $('pg-operacion').value, uc_por_operario: $('pg-uc').value,
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
