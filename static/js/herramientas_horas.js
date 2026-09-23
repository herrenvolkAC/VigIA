(() => {
  let catalog = {}, rows = [], dirty = new Set(), loaded = false, busy = false;
  const selectedRows = new Set();
  let sortKey = 'fecha', sortDirection = -1;
  const collator = new Intl.Collator('es', {numeric:true, sensitivity:'base'});
  const msg = (text, error = false) => { $('he-message').textContent = text; $('he-message').classList.toggle('status-error', error); };
  const argentinaTime = value => {
    if (!value) return '';
    const stamp = new Date(value.replace(' ', 'T') + (/(Z|[+-]\d{2}:\d{2})$/.test(value) ? '' : 'Z'));
    if (Number.isNaN(stamp.getTime())) return value;
    return new Intl.DateTimeFormat('es-AR', {timeZone:'America/Argentina/Buenos_Aires',
      day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'}).format(stamp);
  };
  const hours = n => { const m = Math.round(Number(n) * 60); return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`; };
  function lock(value) {
    busy = value;
    for (const el of document.querySelectorAll('#he-form input,#he-form select,#he-form button,#he-body input,#he-body select,.he-bulk button,.he-bulk input,#he-head button,#he-select-all')) el.disabled = value;
    $('he-guardar').disabled = value || !dirty.size;
    selection();
  }
  function summary() {
    const totals = {Realizadas: 0, Pendientes: 0, Autorizadas: 0, Rechazadas: 0};
    rows.forEach(r => { totals.Realizadas += r.horas; if(r.estado==='parcial'){const approved=Math.max(0,Math.min(r.horas,Number(r.horas_autorizadas)||0));totals.Autorizadas+=approved;totals.Rechazadas+=r.horas-approved;}else totals[{pendiente:'Pendientes',autorizada:'Autorizadas',rechazada:'Rechazadas'}[r.estado]] += r.horas; });
    $('he-kpis').innerHTML = Object.entries(totals).map(([k,v]) => `<div class="kpi"><div class="kpi-label">${k}</div><div class="kpi-value mono">${hours(v)}</div></div>`).join('');
  }
  function render() {
    $('he-body').innerHTML = rows.map((r,i) => ({r,i})).sort((a,b) => sortDirection * (['horas','horas_autorizadas'].includes(sortKey) ? (a.r[sortKey]||0)-(b.r[sortKey]||0) : collator.compare(a.r[sortKey] || '', b.r[sortKey] || '')) || a.i-b.i).map(({r,i}) => `<tr data-he-row="${i}"><td><input type="checkbox" data-select-row="${i}" ${selectedRows.has(i)?'checked':''} aria-label="Seleccionar ${esc(r.legajo)} ${esc(r.fecha)}"></td><td>${esc(r.fecha)}</td><td>${esc(r.legajo)}</td><td>${esc(r.empleado)}</td><td>${esc(r.sector)}</td><td>${esc(r.funcion)}</td><td class="mono">${hours(r.horas)}</td><td>${r.revision ? '<div class="status-warn">Requiere revisión</div>' : ''}<select data-field="estado" aria-label="Decisión ${esc(r.legajo)} ${esc(r.fecha)}">${[['pendiente','Pendiente'],['autorizada','Autorizar'],['rechazada','Rechazar'],['parcial','Aprobación parcial']].map(([v,l]) => `<option value="${v}" ${v===r.estado?'selected':''}>${l}</option>`).join('')}</select></td><td>${r.estado==='parcial'?`<input data-field="horas_autorizadas" type="number" min="0" max="${r.horas}" step="any" value="${esc(r.horas_autorizadas??'')}" aria-label="Horas autorizadas ${esc(r.legajo)} ${esc(r.fecha)}" placeholder="Ej.: 1,5">`:`<span class="mono">${hours(r.estado==='autorizada'?r.horas:0)}</span>`}</td><td><input data-field="observacion" maxlength="500" value="${esc(r.observacion)}" aria-label="Observación ${esc(r.legajo)} ${esc(r.fecha)}"></td><td>${esc(r.usuario)}<br>${esc(argentinaTime(r.updated_at))}${r.updated_at?' (Argentina)':''}</td></tr>`).join('') || '<tr><td colspan="11">No hay horas extras para los filtros seleccionados.</td></tr>';
    summary(); selection();
    document.querySelectorAll('#he-head [data-sort]').forEach(b => b.parentElement.setAttribute('aria-sort', b.dataset.sort===sortKey ? (sortDirection===1?'ascending':'descending') : 'none'));
  }
  function functions() {
    const options = catalog[$('he-sector').value] || [];
    $('he-checks').innerHTML = options.length ? `<label><input type="checkbox" id="he-all" checked>Todas</label>` + options.map(f => `<label><input type="checkbox" name="he-funcion" value="${esc(f)}" checked>${esc(f)}</label>`).join('') : '';
    $('he-funciones').querySelector('summary').textContent = options.length ? 'Todas las funciones' : 'Seleccione un sector';
  }
  $('he-checks').addEventListener('change', e => {
    const checks = [...document.querySelectorAll('[name="he-funcion"]')];
    if (e.target.id === 'he-all') checks.forEach(c => c.checked = e.target.checked);
    const count = checks.filter(c => c.checked).length;
    $('he-all').checked = count === checks.length;
    $('he-all').indeterminate = count > 0 && count < checks.length;
    $('he-funciones').querySelector('summary').textContent = `${count} funciones seleccionadas`;
  });
  $('he-sector').addEventListener('change', functions);
  async function tab(horas) {
    $('panel-viajes').hidden = horas; $('panel-horas').hidden = !horas;
    for (const [id,active] of [['tab-viajes',!horas],['tab-horas',horas]]) {
      $(id).classList.toggle('active', active); $(id).setAttribute('aria-selected', String(active)); $(id).tabIndex = active ? 0 : -1;
    }
    if (horas && !loaded) {
      try { const data = await api('/api/herramientas/horas-extras/filtros'); if (!data) return;
        catalog = data.sectores; loaded = true;
        $('he-sector').innerHTML = '<option value="">Seleccione un sector</option>' + Object.keys(catalog).map(s => `<option>${esc(s)}</option>`).join('');
      } catch(e) { msg(e.message, true); }
    }
  }
  $('tab-viajes').onclick = () => tab(false); $('tab-horas').onclick = () => tab(true);
  document.querySelector('.main-tabs').addEventListener('keydown', e => {
    if (['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) { e.preventDefault(); const h = e.key === 'End' || (e.key !== 'Home' && e.target.id === 'tab-viajes'); tab(h); $(h?'tab-horas':'tab-viajes').focus(); }
  });
  const today = nowLocal().slice(0,10); $('he-hasta').value = today; $('he-desde').value = today.slice(0,8)+'01';
  let lastQuery = '';
  async function query(params) {
    const data = await api('/api/herramientas/horas-extras?' + params);
    if (!data) return false;
    rows = data.rows; dirty.clear(); selectedRows.clear(); lastQuery = params; render(); return true;
  }
  $('he-form').addEventListener('submit', async e => {
    e.preventDefault(); if (busy) return;
    if ($('he-desde').value > $('he-hasta').value) return msg('Revise el rango de fechas.', true);
    const checks = [...document.querySelectorAll('[name="he-funcion"]')];
    const selected = checks.filter(c => c.checked);
    if (checks.length && !selected.length) return msg('Seleccione al menos una función.', true);
    if (dirty.size && !confirm('Hay cambios sin guardar. ¿Descartarlos y consultar?')) return;
    const params = new URLSearchParams({desde:$('he-desde').value,hasta:$('he-hasta').value,sector:$('he-sector').value});
    if (selected.length !== checks.length) selected.forEach(c => params.append('funcion',c.value));
    lock(true); msg('Consultando…');
    try { if (await query(params.toString())) msg(`${rows.length} registros. Horas expresadas en HH:MM.`); } catch(e) { msg(e.message, true); } finally { lock(false); }
  });
  $('he-body').addEventListener('input', e => {
    const field = e.target.dataset.field; if (!field || busy) return;
    const i = Number(e.target.closest('tr').dataset.heRow); rows[i][field] = field==='horas_autorizadas' ? (e.target.value===''?null:Number(e.target.value)) : e.target.value; dirty.add(i);
    if(field==='estado'){rows[i].horas_autorizadas=rows[i].estado==='autorizada'?rows[i].horas:rows[i].estado==='parcial'?null:0;render();}
    $('he-guardar').disabled = false; summary(); msg(`${dirty.size} filas con cambios sin guardar.`);
  });
  $('he-guardar').onclick = async () => {
    if (busy || !dirty.size) return;
    const changed = [...dirty].map(i => rows[i]);
    if (changed.length > 1000) return msg('Guarde hasta 1000 filas por operación; reduzca el rango de consulta.', true);
    if (changed.some(r => r.estado==='rechazada' && !r.observacion.trim())) return msg('Indique el motivo en cada fila rechazada.', true);
    if(changed.some(r=>r.estado==='parcial'&&(!Number.isFinite(r.horas_autorizadas)||r.horas_autorizadas<=0||r.horas_autorizadas>=r.horas)))return msg('Ingrese horas parciales mayores a cero y menores a las realizadas (ej.: 1,5 = 1 h 30 min).',true);
    lock(true); msg('Guardando…');
    try {
      const result = await api('/api/herramientas/horas-extras/decisiones', {method:'POST',body:JSON.stringify({rows:changed})});
      if (!result) return;
      dirty.clear();
      try { await query(lastQuery); msg(`${result.guardadas} decisiones guardadas.`); }
      catch(e) { msg('Decisiones guardadas. Vuelva a consultar para actualizar la pantalla.', true); }
    } catch(e) { msg(e.message, true); } finally { lock(false); }
  };
  function selection() {
    $('he-selection').textContent = `${selectedRows.size} de ${rows.length} filas seleccionadas`;
    $('he-select-all').checked = rows.length > 0 && selectedRows.size === rows.length;
    $('he-select-all').indeterminate = selectedRows.size > 0 && selectedRows.size < rows.length;
    $('he-select-all').disabled = busy || !rows.length;
    $('he-aprobar').disabled = $('he-rechazar').disabled = busy || !selectedRows.size;
    $('he-exportar').disabled = busy || !rows.length;
  }
  $('he-head').addEventListener('click', e => {
    const button = e.target.closest('[data-sort]'); if (!button || busy) return;
    if (sortKey === button.dataset.sort) sortDirection *= -1;
    else { sortKey = button.dataset.sort; sortDirection = 1; }
    render();
  });
  $('he-select-all').addEventListener('change', e => {
    if (busy) return;
    selectedRows.clear(); if (e.target.checked) rows.forEach((r,i) => selectedRows.add(i)); render();
  });
  $('he-body').addEventListener('change', e => {
    if (e.target.dataset.selectRow === undefined || busy) return;
    const index = Number(e.target.dataset.selectRow);
    if (e.target.checked) selectedRows.add(index); else selectedRows.delete(index);
    selection();
  });
  function bulk(estado) {
    if (busy || !selectedRows.size) return;
    const motivo = $('he-motivo').value.trim();
    if (estado === 'rechazada' && !motivo) return msg('Ingrese el motivo del rechazo masivo.', true);
    const affected = new Set([...dirty, ...selectedRows]);
    if (affected.size > 1000) return msg('Seleccione hasta 1000 filas por operación, incluyendo cambios pendientes.', true);
    selectedRows.forEach(i => { rows[i].estado = estado; rows[i].horas_autorizadas=estado==='autorizada'?rows[i].horas:0; if (estado === 'rechazada') rows[i].observacion = motivo; dirty.add(i); });
    render(); $('he-guardar').disabled = false;
    msg(`${selectedRows.size} filas preparadas para ${estado==='autorizada'?'aprobar':'rechazar'}. Presione Guardar cambios.`);
  }
  $('he-aprobar').onclick = () => bulk('autorizada');
  $('he-rechazar').onclick = () => bulk('rechazada');
  $('he-exportar').onclick = async () => {
    if (busy || !rows.length) return;
    if (dirty.size) return msg('Guarde los cambios antes de exportar las decisiones.', true);
    lock(true); msg('Generando Excel…');
    try {
      const params = new URLSearchParams(lastQuery); params.set('orden',sortKey); params.set('direccion',sortDirection===1?'asc':'desc');
      const response = await fetch('/api/herramientas/horas-extras/exportar.xlsx?' + params, {credentials:'same-origin'});
      if (response.status===401) { location.href='/login?next=/herramientas.html'; return; }
      if (!response.ok) throw new Error(await exportError(response));
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a');
      link.href = url; link.download = `horas_extras_${params.get('desde')}_${params.get('hasta')}.xlsx`;
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),30000);
      msg('Excel exportado con las decisiones guardadas.');
    } catch(e) { msg(e.message,true); } finally { lock(false); }
  };
  window.addEventListener('beforeunload', e => { if(dirty.size) { e.preventDefault(); e.returnValue=''; } });
})();
