(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const money = value => (Number(value || 0) / 100).toLocaleString('es-AR', {style:'currency', currency:'ARS'});
  const values = (rows, key) => [...new Set(rows.map(row => String(row[key] || '').trim()).filter(Boolean))].sort((a,b) => a.localeCompare(b, 'es'));
  const select = (label, id) => `<label class="field">${label}<select class="input" id="${id}"><option value="">Todos</option></select></label>`;
  const hms = value => { const total = Math.max(0, Math.round(Number(value || 0))); const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60; return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`; };
  const installSummary = () => {
    const view = $('view-resumen-legajos'); if (!view) return;
    const oldDetail = $('resumen-legajo-detalle'); if (oldDetail) oldDetail.remove();
    if (!view.dataset.actividadResumen) {
      view.dataset.actividadResumen = '1';
      const title = view.querySelector('.view-title strong'); if (title) title.textContent = 'Actividad productiva por legajo';
      const table = view.querySelector('.table-wrap table');
      if (table?.tHead?.rows?.[0]) {
        table.tHead.rows[0].innerHTML = '<th>Fecha</th><th>Legajo</th><th>Nombre</th><th>Sector legajero</th><th>Función legajero</th><th>Funciones WMS agrupadas</th><th>Operación</th><th>Otras operaciones medibles</th><th>División</th><th>Producción real</th><th>Unidad</th><th>Tiempo</th><th>Bultos</th><th>Palets</th><th>Etapas</th><th>Tiempo inconsistente</th>';
      }
      const mainWrap = view.querySelector('.table-wrap');
      const bar = document.createElement('div'); bar.style.cssText = 'display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin:10px 0';
      bar.innerHTML = '<label class="field">Fecha desde<input class="input" id="rl-desde" type="date"></label><label class="field">Fecha hasta<input class="input" id="rl-hasta" type="date"></label>' + select('Operación','rl-operacion') + '<label class="field">Filas por página<select class="input" id="rl-limit"><option value="500">500</option><option value="1000" selected>1000</option><option value="2000">2000</option><option value="5000">5000</option></select></label>' + select('Sector legajero','rl-sector') + select('Función legajero','rl-funcion') + select('División','rl-division') + '<button class="primary" id="rl-consultar" type="button">Consultar resumen</button><button class="secondary" id="rl-prev" type="button" disabled>Anterior</button><button class="secondary" id="rl-next" type="button" disabled>Siguiente</button>';
      view.insertBefore(bar, mainWrap);
      const summary = document.createElement('section');
      summary.id = 'resumen-legajos-operaciones';
      summary.innerHTML = '<div class="view-title"><strong>Resumen por operación y división</strong><span id="rl-resumen-meta">Elegí fechas y presioná Consultar resumen.</span></div><div class="table-wrap"><table><thead><tr><th>Operación</th><th>División</th><th>Días con actividad</th><th>Legajos con actividad</th><th>Unidad</th><th>Bultos</th><th>Palets</th><th>Producción real</th><th>Productividad promedio</th><th>Tiempo</th><th>Etapas</th><th>Tiempo inconsistente</th></tr></thead><tbody id="rl-resumen-rows"><tr><td colspan="12">Sin consulta ejecutada.</td></tr></tbody></table></div>';
      view.insertBefore(summary, mainWrap);
      const detail = document.createElement('section');
      detail.id = 'resumen-legajos-dia-detalle';
      detail.innerHTML = '<div class="view-title"><strong>Actividad completa del legajo/día</strong><span id="rl-dia-meta">Seleccioná una fila.</span></div><div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Legajo</th><th>Funciones WMS agrupadas</th><th>Operación</th><th>División</th><th>Producción real</th><th>Unidad</th><th>Tiempo</th><th>Bultos</th><th>Palets</th><th>Etapas</th><th>Tiempo inconsistente</th></tr></thead><tbody id="rl-dia-rows"><tr><td colspan="12">Seleccioná una fila de la grilla superior.</td></tr></tbody></table></div>';
      mainWrap.after(detail);
      $('rl-desde').value = $('desde')?.value || '';
      $('rl-hasta').value = $('hasta')?.value || '';
      ['rl-sector','rl-funcion','rl-operacion','rl-division'].forEach(id => $(id).onchange = () => view.__resumenActividadPaint?.());
      $('rl-consultar').onclick = () => { view.__resumenActividadOffset = 0; view.__resumenActividadDivisionConsulta = ''; view.__resumenOperacionesLoad?.(); };
      $('rl-prev').onclick = () => { view.__resumenActividadOffset = Math.max(0, Number(view.__resumenActividadOffset || 0) - Number($('rl-limit').value || 1000)); view.__resumenActividadLoad?.(); };
      $('rl-next').onclick = () => { view.__resumenActividadOffset = Number(view.__resumenActividadOffset || 0) + Number($('rl-limit').value || 1000); view.__resumenActividadLoad?.(); };
      $('rl-resumen-rows').addEventListener('click', event => {
        const row = event.target.closest('tr'); if (!row || row.cells.length < 2 || !row.dataset.operacion) return;
        [...$('rl-resumen-rows').rows].forEach(item => item.classList.toggle('hierarchy-selected', item === row));
        $('rl-operacion').value = row.dataset.operacion;
        view.__resumenActividadDivisionConsulta = row.dataset.division || '';
        view.__resumenActividadOffset = 0;
        view.__resumenActividadLoad?.();
      });
      table?.tHead?.addEventListener('click', event => {
        const th = event.target.closest('th'); if (!th) return;
        const column = [...th.parentElement.cells].indexOf(th), direction = th.dataset.sortDir === '1' ? -1 : 1;
        [...th.parentElement.cells].forEach(head => delete head.dataset.sortDir); th.dataset.sortDir = String(direction);
        const numeric = value => Number(String(value || '').replace(/[^0-9,-]/g, '').replace(/\./g, '').replace(',', '.'));
        [...$('resumen-legajos-rows').rows].filter(row => row.cells.length > 1).sort((a,b) => {
          const av = a.cells[column]?.textContent.trim() || '', bv = b.cells[column]?.textContent.trim() || '', an = numeric(av), bn = numeric(bv);
          return direction * (Number.isFinite(an) && Number.isFinite(bn) && String(av).match(/\d/) && String(bv).match(/\d/) ? an - bn : av.localeCompare(bv, 'es', {numeric:true, sensitivity:'base'}));
        }).forEach(row => $('resumen-legajos-rows').appendChild(row));
      });
      $('resumen-legajos-rows').addEventListener('click', async event => {
        const row = event.target.closest('tr'); if (!row || row.cells.length < 2) return;
        const fecha = row.cells[0].textContent.trim(), legajo = row.cells[1].textContent.trim();
        if (!fecha || !legajo) return;
        [...$('resumen-legajos-rows').rows].forEach(item => item.classList.toggle('hierarchy-selected', item === row));
        const meta = $('rl-dia-meta'), body = $('rl-dia-rows');
        meta.textContent = `Legajo ${legajo} · ${fecha} · consultando actividad completa…`;
        body.innerHTML = '<tr><td colspan="12">Consultando actividad completa del día…</td></tr>';
        try {
          const iso = `${fecha.slice(0,4)}-${fecha.slice(4,6)}-${fecha.slice(6,8)}`;
          const q = new URLSearchParams({fecha_desde:iso, fecha_hasta:iso, legajo, limit:'5000', offset:'0'});
          const response = await fetch('/api/estudio-premios-productividad/resumen-legajos/actividad?'+q,{credentials:'same-origin'});
          const data = await response.json(); if (!response.ok) throw Error(data.detail || 'No se pudo cargar la actividad del día.');
          body.innerHTML = (data.rows || []).map(item => `<tr><td class="mono">${esc(item.fecha)}</td><td class="mono">${esc(item.legajo)}</td><td>${esc(item.funcion_realizada)}</td><td>${esc(item.operacion_agrupada)}</td><td>${esc(division(item))}</td><td class="mono">${num(item.produccion_real)}</td><td>${esc(item.unidad||'')}</td><td class="mono">${hms(item.segundos_validos)}</td><td class="mono">${num(item.bultos)}</td><td class="mono">${num(item.palets)}</td><td class="mono">${num(item.etapas)}</td><td class="mono">${num(item.etapas_inconsistentes_tiempo)}</td></tr>`).join('') || '<tr><td colspan="12">No hay actividad productiva para ese legajo/día.</td></tr>';
          meta.textContent = `Legajo ${legajo} · ${fecha} · ${(data.rows || []).length} filas de actividad`;
        } catch (error) {
          body.innerHTML = `<tr><td colspan="12">${esc(error.message)}</td></tr>`;
          meta.textContent = error.message;
        }
      });
      fetch('/api/estudio-premios-productividad/resumen-legajos/actividad/catalogo',{credentials:'same-origin'})
        .then(r=>r.json().then(d=>({ok:r.ok,d})))
        .then(({ok,d})=>{if(!ok)throw Error(d.detail||'No se pudo cargar operaciones.');$('rl-operacion').innerHTML='<option value="">Seleccioná operación</option>'+(d.operaciones||[]).map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');})
        .catch(e=>$('resumen-legajos-meta').textContent=e.message);
    }
    let rows = view.__resumenActividadRows || [], note = view.__resumenActividadNote || '';
    const num = value => Number(value || 0).toLocaleString('es-AR', {maximumFractionDigits:2});
    const division = item => item.division_desc ? `${item.division} · ${item.division_desc}` : (item.division || '—');
    const sortTable = (tbody, header) => {
      const column = [...header.parentElement.cells].indexOf(header), direction = header.dataset.sortDir === '1' ? -1 : 1;
      [...header.parentElement.cells].forEach(head => delete head.dataset.sortDir); header.dataset.sortDir = String(direction);
      const numeric = value => Number(String(value || '').replace(/[^0-9,-]/g, '').replace(/\./g, '').replace(',', '.'));
      [...tbody.rows].filter(row => row.cells.length > 1).sort((a,b) => {
        const av = a.cells[column]?.textContent.trim() || '', bv = b.cells[column]?.textContent.trim() || '', an = numeric(av), bn = numeric(bv);
        return direction * (Number.isFinite(an) && Number.isFinite(bn) && String(av).match(/\d/) && String(bv).match(/\d/) ? an - bn : av.localeCompare(bv, 'es', {numeric:true, sensitivity:'base'}));
      }).forEach(row => tbody.appendChild(row));
    };
    if (!view.dataset.actividadResumenSort) {
      view.dataset.actividadResumenSort = '1';
      $('resumen-legajos-operaciones')?.querySelector('thead')?.addEventListener('click', event => {
        const th = event.target.closest('th'); if (th) sortTable($('rl-resumen-rows'), th);
      });
    }
    const paint = () => {
      const sector=$('rl-sector')?.value || '', funcion=$('rl-funcion')?.value || '', div=$('rl-division')?.value || '';
      const filtered=rows.filter(x=>(!sector||x.sector_legajero===sector)&&(!funcion||x.funcion_legajero===funcion)&&(!div||String(x.division)===div));
      $('resumen-legajos-rows').innerHTML=filtered.map(x=>`<tr><td class="mono">${esc(x.fecha)}</td><td class="mono">${esc(x.legajo)}</td><td>${esc(x.nombre)}</td><td>${esc(x.sector_legajero)}</td><td>${esc(x.funcion_legajero)}</td><td>${esc(x.funcion_realizada)}</td><td>${esc(x.operacion_agrupada)}</td><td>${esc(x.otras_operaciones_medibles||'—')}</td><td>${esc(division(x))}</td><td class="mono">${num(x.produccion_real)}</td><td>${esc(x.unidad||'')}</td><td class="mono">${hms(x.segundos_validos)}</td><td class="mono">${num(x.bultos)}</td><td class="mono">${num(x.palets)}</td><td class="mono">${num(x.etapas)}</td><td class="mono">${num(x.etapas_inconsistentes_tiempo)}</td></tr>`).join('') || '<tr><td colspan="16">Sin actividad productiva para los filtros elegidos.</td></tr>';
      const total=Number(view.__resumenActividadTotal || rows.length), offset=Number(view.__resumenActividadOffset || 0), limit=Number(view.__resumenActividadLimit || rows.length);
      const pageEnd=Math.min(offset + rows.length, total);
      $('resumen-legajos-meta').textContent=`Mostrando ${offset + 1}-${pageEnd} de ${total} filas totales · ${filtered.length} visibles en esta página${note?` · ${note}`:''}`;
    };
    view.__resumenActividadPaint = paint;
    async function load() {
      const ticket = String(Date.now()); view.dataset.actividadTicket = ticket;
      const button = $('rl-consultar'); if (button) button.disabled = true;
      const prev = $('rl-prev'), next = $('rl-next'); if (prev) prev.disabled = true; if (next) next.disabled = true;
      $('resumen-legajos-meta').textContent='Consultando actividad productiva…';
      try {
        const limit=Number($('rl-limit').value || 1000), offset=Number(view.__resumenActividadOffset || 0), operacion=$('rl-operacion').value, divisionConsulta=view.__resumenActividadDivisionConsulta || $('rl-division').value || '';
        if (!operacion) throw Error('Seleccioná una operación antes de consultar.');
        const q = new URLSearchParams({fecha_desde:$('rl-desde').value || $('desde').value, fecha_hasta:$('rl-hasta').value || $('hasta').value, legajo:$('legajo').value.trim(), operacion, division:divisionConsulta, limit:String(limit), offset:String(offset)});
        const r=await fetch('/api/estudio-premios-productividad/resumen-legajos/actividad?'+q,{credentials:'same-origin'}); const d=await r.json(); if(!r.ok) throw Error(d.detail||'No se pudo cargar la actividad productiva.');
        if (view.dataset.actividadTicket !== ticket) return;
        rows=d.rows||[]; note=d.nota||''; view.__resumenActividadRows=rows; view.__resumenActividadNote=note;
        view.__resumenActividadTotal=Number(d.total || rows.length); view.__resumenActividadLimit=Number(d.limit || limit); view.__resumenActividadOffset=Number(d.offset || offset);
        [['rl-sector','sector_legajero'],['rl-funcion','funcion_legajero'],['rl-division','division']].forEach(([id,key])=>$(id).innerHTML='<option value="">Todos</option>'+values(rows,key).map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join(''));
        paint();
      } catch (e) {
        if (view.dataset.actividadTicket === ticket) $('resumen-legajos-meta').textContent=e.message;
      } finally {
        if (view.dataset.actividadTicket === ticket && button) button.disabled = false;
        if (view.dataset.actividadTicket === ticket && prev) prev.disabled = Number(view.__resumenActividadOffset || 0) <= 0;
        if (view.dataset.actividadTicket === ticket && next) next.disabled = Number(view.__resumenActividadOffset || 0) + rows.length >= Number(view.__resumenActividadTotal || rows.length);
      }
    }
    view.__resumenActividadLoad = load;
    async function loadSummary() {
      const button = $('rl-consultar'); if (button) button.disabled = true;
      $('rl-resumen-meta').textContent = 'Consultando resumen de operaciones…';
        $('rl-resumen-rows').innerHTML = '<tr><td colspan="12">Consultando resumen…</td></tr>';
      try {
        const q = new URLSearchParams({fecha_desde:$('rl-desde').value || $('desde').value, fecha_hasta:$('rl-hasta').value || $('hasta').value});
        const r = await fetch('/api/estudio-premios-productividad/resumen-legajos/actividad/resumen?'+q,{credentials:'same-origin'});
        const d = await r.json(); if(!r.ok) throw Error(d.detail || 'No se pudo cargar el resumen.');
        $('rl-resumen-rows').innerHTML = (d.rows || []).map(item => `<tr data-operacion="${esc(item.operacion_agrupada)}" data-division="${esc(item.division)}"><td>${esc(item.operacion_agrupada)}</td><td>${esc(division(item))}</td><td class="mono">${num(item.dias_con_actividad)}</td><td class="mono">${num(item.legajos_con_actividad)}</td><td>${esc(item.unidad || '')}</td><td class="mono">${num(item.bultos)}</td><td class="mono">${num(item.palets)}</td><td class="mono">${num(item.produccion_real)}</td><td class="mono">${num(item.productividad_promedio)}</td><td class="mono">${hms(item.segundos_validos)}</td><td class="mono">${num(item.etapas)}</td><td class="mono">${num(item.etapas_inconsistentes_tiempo)}</td></tr>`).join('') || '<tr><td colspan="12">No hay actividad para el rango seleccionado.</td></tr>';
        $('rl-resumen-meta').textContent = `${(d.rows || []).length} operaciones/divisiones · seleccioná una fila para ver el detalle por legajo/día.`;
        $('resumen-legajos-meta').textContent = 'Seleccioná una fila del resumen superior para cargar el detalle.';
        $('resumen-legajos-rows').innerHTML = '<tr><td colspan="16">Seleccioná una operación/división del resumen superior.</td></tr>';
        $('rl-dia-meta').textContent = 'Seleccioná una fila del detalle por legajo/día.';
        $('rl-dia-rows').innerHTML = '<tr><td colspan="12">Seleccioná una fila de la grilla de detalle.</td></tr>';
      } catch (e) {
        $('rl-resumen-meta').textContent = e.message;
        $('rl-resumen-rows').innerHTML = `<tr><td colspan="12">${esc(e.message)}</td></tr>`;
      } finally {
        if (button) button.disabled = false;
      }
    }
    view.__resumenOperacionesLoad = loadSummary;
    if (!view.__resumenActividadRows) {
      $('resumen-legajos-meta').textContent = 'Elegí fechas y presioná Consultar para cargar la actividad productiva.';
      $('resumen-legajos-rows').innerHTML = '<tr><td colspan="16">Sin consulta ejecutada.</td></tr>';
    } else {
      paint();
    }
  };
  const installSummaryDetail = () => {
    const oldDetail = $('resumen-legajo-detalle'); if (oldDetail) oldDetail.remove();
  };
  window.loadResumenLegajos = async () => {
    if (!$('resumen-legajos-rows')) {
      const section = document.createElement('section');
      section.className = 'view';
      section.id = 'view-resumen-legajos';
      section.innerHTML = '<div class="view-title"><strong>Actividad productiva por legajo</strong></div><div class="status" id="resumen-legajos-meta"></div><div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Legajo</th><th>Nombre</th><th>Sector legajero</th><th>Función legajero</th><th>Funciones WMS agrupadas</th><th>Operación</th><th>Otras operaciones medibles</th><th>División</th><th>Producción real</th><th>Unidad</th><th>Tiempo</th><th>Bultos</th><th>Palets</th><th>Etapas</th><th>Tiempo inconsistente</th></tr></thead><tbody id="resumen-legajos-rows"></tbody></table></div>';
      document.querySelector('main').appendChild(section);
    }
    document.querySelectorAll('.view').forEach(item => item.classList.toggle('active', item.id === 'view-resumen-legajos'));
    installSummary();
  };
  const installPol = () => {
    const view=$('view-polivalencias-datos'); if(!view||$('pd-sector'))return;
    const detailTable=$('pol-datos-rows')?.closest('table');
    const resumenBody=$('pol-datos-resumen-rows');
    if(!detailTable||!resumenBody)return;
    detailTable.tHead.rows[0].innerHTML='<th>Fecha</th><th>Legajo</th><th>Nombre</th><th>Sector</th><th>Función legajero</th><th>Turno madre</th><th>Operación madre</th><th>Operación de polivalencia</th><th>Pago polivalencia</th>';
    const summary=document.createElement('section');summary.id='pol-datos-resumen';summary.setAttribute('aria-label','Resumen de polivalencias');summary.style.cssText='display:grid;grid-template-columns:repeat(3,minmax(190px,1fr));gap:10px;margin:10px 0 14px';view.insertBefore(summary,$('pol-datos-meta'));
    const bar=document.createElement('div');bar.style.cssText='display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin:10px 0';bar.innerHTML=select('Sector','pd-sector')+select('Función','pd-funcion')+select('Turno','pd-turno');view.insertBefore(bar,view.querySelector('.table-wrap'));
    const opMadre=x=>x.operacion_madre||x.operacion_a||'—';
    const fields=['fecha','legajo','nombre','sector','funcion','turno','operacion_madre','operacion_b','pago_polivalencia'];let rows=[], catalog=false, sort={field:'fecha',direction:1};
    const paint=()=>{const visible=[...rows].sort((a,b)=>{const av=(sort.field==='operacion_madre'?opMadre(a):a[sort.field])??'',bv=(sort.field==='operacion_madre'?opMadre(b):b[sort.field])??'';const an=Number(av),bn=Number(bv);return sort.direction*(Number.isFinite(an)&&Number.isFinite(bn)&&String(av).trim()!==''&&String(bv).trim()!==''?an-bn:String(av).localeCompare(String(bv),'es',{numeric:true,sensitivity:'base'}));});const grouped=new Map();rows.forEach(x=>{const key=[x.sector||'—',x.funcion||'—',opMadre(x),x.operacion_b||'—'].join('');const item=grouped.get(key)||{sector:x.sector||'—',funcion:x.funcion||'—',madre:opMadre(x),cambio:x.operacion_b||'—',cantidad:0};item.cantidad+=1;grouped.set(key,item);});const resumen=[...grouped.values()].sort((a,b)=>b.cantidad-a.cantidad||a.sector.localeCompare(b.sector,'es',{numeric:true})||a.funcion.localeCompare(b.funcion,'es',{numeric:true})||a.madre.localeCompare(b.madre,'es',{numeric:true})||a.cambio.localeCompare(b.cambio,'es',{numeric:true}));resumenBody.innerHTML=resumen.map(x=>`<tr><td>${esc(x.sector)}</td><td>${esc(x.funcion)}</td><td class="mono">→</td><td>${esc(x.madre)}</td><td>${esc(x.cambio)}</td><td class="mono">${Number(x.cantidad).toLocaleString('es-AR')}</td></tr>`).join('')||'<tr><td colspan="6">No se detectaron cambios para resumir con los filtros actuales.</td></tr>';$('pol-datos-rows').innerHTML=visible.map(x=>`<tr><td>${esc(x.fecha)}</td><td>${esc(x.legajo)}</td><td>${esc(x.nombre)}</td><td>${esc(x.sector)}</td><td>${esc(x.funcion)}</td><td>${esc(x.turno)}</td><td>${esc(opMadre(x))}</td><td>${esc(x.operacion_b)}</td><td>${Number(x.pago_polivalencia||0).toLocaleString('es-AR',{style:'currency',currency:'ARS'})}</td></tr>`).join('')||'<tr><td colspan="9">No hay polivalencias para estos filtros. Se requieren parámetros grupales activos para sector, función y turno madre.</td></tr>';const legajos=new Set(rows.map(x=>String(x.legajo||'').trim()).filter(Boolean)).size,dias=new Set(rows.map(x=>String(x.fecha||'').trim()).filter(Boolean)).size,pago=rows.reduce((sum,x)=>sum+Number(x.pago_polivalencia||0),0);summary.innerHTML=[['Legajos con polivalencia',legajos],['Días con polivalencia',dias],['Pago total',pago.toLocaleString('es-AR',{style:'currency',currency:'ARS'})]].map(([label,value])=>`<article class="premios-total-card"><span>${label}</span><strong>${value}</strong></article>`).join('');};
    const load=async()=>{const q=new URLSearchParams({fecha_desde:$('desde').value,fecha_hasta:$('hasta').value,legajo:$('legajo').value.trim(),sector:$('pd-sector').value,funcion:$('pd-funcion').value,turno:$('pd-turno').value});$('pol-datos-meta').textContent='Consultando polivalencias configuradas…';resumenBody.innerHTML='<tr><td colspan="6">Leyendo resumen del último cálculo diario…</td></tr>';$('pol-datos-rows').innerHTML='<tr><td colspan="9">Leyendo polivalencias del último cálculo diario…</td></tr>';const r=await fetch('/api/estudio-premios-productividad/polivalencias?'+q,{credentials:'same-origin'});const d=await r.json();if(!r.ok)throw Error(d.detail||'No se pudieron cargar las polivalencias.');rows=d.rows||[];if(!catalog){catalog=true;[['pd-sector','sector'],['pd-funcion','funcion'],['pd-turno','turno']].forEach(([id,key])=>$(id).innerHTML='<option value="">Todos</option>'+values(rows,key).map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join(''));}paint();$('pol-datos-meta').textContent=`${rows.length} combinaciones detectadas · ${d.nota||'datos actualizados'}`;};
    ['pd-sector','pd-funcion','pd-turno'].forEach(id=>$(id).onchange=()=>load().catch(e=>$('pol-datos-meta').textContent=e.message));
    detailTable.tHead.addEventListener('click',event=>{const header=event.target.closest('th');if(!header)return;const index=[...header.parentElement.cells].indexOf(header),field=fields[index];if(!field)return;sort={field,direction:sort.field===field?-sort.direction:1};[...header.parentElement.cells].forEach(item=>{item.classList.remove('sorted');item.removeAttribute('data-arrow');});header.classList.add('sorted');header.dataset.arrow=sort.direction===1?'↑':'↓';paint();});
    window.loadPolivalenciasDatos=load;
  };
  const installTotalsCards = () => {
    const view=$('view-premios-totales'), body=$('premios-totales-rows'); if(!view||!body||$('premios-totales-resumen'))return;
    const summary=document.createElement('section');summary.id='premios-totales-resumen';summary.setAttribute('aria-label','Totales de las filas visibles');view.insertBefore(summary,$('premios-totales-meta'));
    const controls=document.createElement('div');controls.id='premios-totales-controles';controls.innerHTML='<span id="premios-totales-alcance">Suma de todas las filas visibles.</span><button class="secondary" id="premios-totales-todas" type="button" disabled>Mostrar suma de todas</button><span class="premios-totales-ayuda">Ctrl/Cmd agrega o quita filas · Shift selecciona un rango</span>';view.insertBefore(controls,summary);
    const number=value=>Number(String(value||'').replace(/[^0-9,-]/g,'').replace(/\./g,'').replace(',','.'))||0;
    const money=value=>value.toLocaleString('es-AR',{style:'currency',currency:'ARS'});
    const key=row=>[0,1,2,3].map(index=>row.cells[index]?.textContent.trim()||'').join('\u001f');
    let selectedKeys=new Set(),anchorKey='';
    const render=()=>{const visibles=[...body.rows].filter(row=>!row.hidden&&row.cells.length>=10),selected=visibles.filter(row=>selectedKeys.has(key(row))),rows=selected.length?selected:visibles,sum=index=>rows.reduce((total,row)=>total+number(row.cells[index]?.textContent),0);const cards=[['Total real pagado',sum(4),'destacado'],['Total nuevo',sum(5),'destacado'],['Diferencia',sum(9),'diferencia'],['Grupal nuevo',sum(6),''],['Individual nuevo',sum(7),''],['Polivalencia nueva',sum(8),'']];summary.innerHTML=cards.map(([label,value,kind])=>`<article class="premios-total-card ${kind}"><span>${label}</span><strong>${money(value)}</strong></article>`).join('');summary.dataset.filas=String(rows.length);[...body.rows].forEach(row=>row.classList.toggle('premios-total-seleccionada',selectedKeys.has(key(row))));const alcance=$('premios-totales-alcance'),button=$('premios-totales-todas');if(selected.length){alcance.textContent=selected.length===1?`Fila seleccionada: ${selected[0].cells[0].textContent.trim()} · ${selected[0].cells[1].textContent.trim()}.`:`${selected.length} filas seleccionadas.`;button.disabled=false;}else{alcance.textContent=`Suma de las ${visibles.length} filas visibles.`;button.disabled=true;}};
    body.addEventListener('click',event=>{const row=event.target.closest('tr');if(!row||row.hidden||row.cells.length<10)return;const visibles=[...body.rows].filter(item=>!item.hidden&&item.cells.length>=10),clicked=key(row);if(event.shiftKey&&anchorKey){const from=visibles.findIndex(item=>key(item)===anchorKey),to=visibles.indexOf(row);if(from>=0&&to>=0){selectedKeys=new Set(visibles.slice(Math.min(from,to),Math.max(from,to)+1).map(key));}else{selectedKeys=new Set([clicked]);}}else if(event.ctrlKey||event.metaKey){if(selectedKeys.has(clicked))selectedKeys.delete(clicked);else selectedKeys.add(clicked);anchorKey=clicked;}else{selectedKeys=new Set([clicked]);anchorKey=clicked;}render();});
    $('premios-totales-todas').onclick=()=>{selectedKeys=new Set();anchorKey='';render();};
    const table=body.closest('table');table.tHead.addEventListener('click',event=>{const header=event.target.closest('th');if(!header)return;const column=[...header.parentElement.cells].indexOf(header),direction=header.dataset.sortDir==='1'?-1:1;[...header.parentElement.cells].forEach(item=>{delete item.dataset.sortDir;item.removeAttribute('data-arrow');});header.dataset.sortDir=String(direction);header.dataset.arrow=direction===1?'↑':'↓';[...body.rows].filter(row=>row.cells.length>=10).sort((a,b)=>{const av=a.cells[column]?.textContent.trim()||'',bv=b.cells[column]?.textContent.trim()||'';if(column>=4)return direction*(number(av)-number(bv));return direction*av.localeCompare(bv,'es',{numeric:true,sensitivity:'base'});}).forEach(row=>body.appendChild(row));render();});
    let observer;const refresh=()=>{observer.disconnect();totals();render();observer.observe(body,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden']});};observer=new MutationObserver(refresh);observer.observe(body,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden']});refresh();
  };
  const totals = () => { const body=$('premios-totales-rows'); if(!body)return; const number=value=>Number(String(value||'').replace(/[^0-9,-]/g,'').replace(/\./g,'').replace(',','.'))||0;[...body.rows].forEach(row=>{const vals=[5,6,7,8].map(i=>number(row.cells[i]?.textContent));row.hidden=!vals.some(v=>v>0);}); };
  const installMapFilters = () => {
    const view=$('view-polivalencias'); if (!view || $('mapa-pol-a')) return;
    const bar=document.createElement('div'); bar.style.cssText='display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin:10px 0';
    bar.innerHTML=select('Operación A','mapa-pol-a')+select('Operación B','mapa-pol-b'); view.insertBefore(bar,view.querySelector('.table-wrap'));
    const apply=()=>{const a=$('mapa-pol-a').value,b=$('mapa-pol-b').value;[...$('polivalencias-rows').rows].forEach(row=>row.hidden=(a&&row.cells[0]?.textContent.trim()!==a)||(b&&row.cells[1]?.textContent.trim()!==b));};
    const refresh=()=>{const rows=[...$('polivalencias-rows').rows];[['mapa-pol-a',0],['mapa-pol-b',1]].forEach(([id,col])=>{$(id).innerHTML='<option value="">Todos</option>'+[...new Set(rows.map(r=>r.cells[col]?.textContent.trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'es')).map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');});apply();};
    $('mapa-pol-a').onchange=apply; $('mapa-pol-b').onchange=apply;
    document.querySelector('[data-param-view="polivalencias"]')?.addEventListener('click',()=>setTimeout(refresh,75));
  };
  const enhancePolEditor = async () => {
    const view=$('view-polivalencias'), body=$('polivalencias-rows'); if(!view||!body)return;
    const response=await fetch('/api/estudio-premios-productividad/mapa-polivalencia',{credentials:'same-origin'}),data=await response.json();
    if(!response.ok)throw Error(data.detail||'No se pudo cargar el mapa de polivalencias.');
    let amount=$('pol-importe');
    if(!amount){
      const label=document.createElement('label');label.className='field';label.innerHTML='Importe por operación A<input class="input" id="pol-importe" type="number" min="0" step="0.01" value="0">';
      $('pol-si').closest('label').after(label);amount=$('pol-importe');
    }
    const toCents=value=>Math.round((Number(String(value||'').replace(',','.'))||0)*100);
    const save=async({operaciones_a,operaciones_b,polivalencia,premio_centavos})=>{
      if(!operaciones_a.length||!operaciones_b.length)throw Error('Seleccioná una operación A y una operación B.');
      const q=await fetch('/api/estudio-premios-productividad/mapa-polivalencia',{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({operaciones_a,operaciones_b,modo:'directo',polivalencia,premio_centavos})});
      const answer=await q.json().catch(()=>({}));if(!q.ok)throw Error(answer.detail||'No se pudo guardar la polivalencia.');
    };
    body.closest('table').tHead.rows[0].innerHTML='<th>Operación A</th><th>Operación B</th><th>Polivalencia</th><th>Importe de A</th><th>Acción</th><th>Actualizado</th>';
    body.innerHTML=(data.relaciones||[]).map((item,index)=>`<tr><td>${esc(item.operacion_a)}</td><td>${esc(item.operacion_b)}</td><td><select class="input" data-pol-activo="${index}"><option value="1" ${Number(item.polivalencia)?'selected':''}>Sí</option><option value="0" ${!Number(item.polivalencia)?'selected':''}>No</option></select></td><td><input class="input" data-pol-importe="${index}" type="number" min="0" step="0.01" value="${((Number(item.premio_centavos)||0)/100).toFixed(2)}"></td><td><button class="secondary" data-pol-save="${index}">Guardar</button></td><td class="mono">${esc(item.updated_at||'')}</td></tr>`).join('')||'<tr><td colspan="6">No hay relaciones configuradas.</td></tr>';
    document.querySelectorAll('[data-pol-save]').forEach(button=>button.onclick=async()=>{const index=Number(button.dataset.polSave),item=data.relaciones[index],row=button.closest('tr');button.disabled=true;try{await save({operaciones_a:[item.operacion_a],operaciones_b:[item.operacion_b],polivalencia:row.querySelector('[data-pol-activo]').value==='1',premio_centavos:toCents(row.querySelector('[data-pol-importe]').value)});amount.value=row.querySelector('[data-pol-importe]').value;await enhancePolEditor();$('status').style.color='';$('status').textContent=`Polivalencia guardada: ${item.operacion_a} → ${item.operacion_b}`;}catch(error){$('polivalencias-meta').textContent=error.message;$('polivalencias-meta').style.color='#C8102E';}finally{button.disabled=false;}});
    $('pol-guardar').onclick=async()=>{const a=[...$('pol-a').selectedOptions].map(option=>option.value),b=[...$('pol-b').selectedOptions].map(option=>option.value),button=$('pol-guardar');button.disabled=true;try{await save({operaciones_a:a,operaciones_b:b,polivalencia:$('pol-si').value==='1',premio_centavos:toCents(amount.value)});await enhancePolEditor();$('status').style.color='';$('status').textContent=`Polivalencias guardadas para ${a.join(', ')}`;}catch(error){$('polivalencias-meta').textContent=error.message;$('polivalencias-meta').style.color='#C8102E';}finally{button.disabled=false;}};
    $('polivalencias-meta').style.color='';$('polivalencias-meta').textContent=`${(data.operaciones||[]).length} operaciones · ${(data.relaciones||[]).length} relaciones · el importe es único por operación A y se aplica a todas sus B`;
  };
  const installProfilePolivalencias = async () => {
    const view=$('view-polivalencias');if(!view)return;
    [...view.children].forEach(child=>{if(!child.classList.contains('view-title')&&child.id!=='pol-reglas-perfil')child.hidden=true;});
    let panel=$('pol-reglas-perfil');if(!panel){panel=document.createElement('section');panel.id='pol-reglas-perfil';view.appendChild(panel);}panel.hidden=false;
    const response=await fetch('/api/estudio-premios-productividad/polivalencia-reglas',{credentials:'same-origin'}),data=await response.json();if(!response.ok)throw Error(data.detail||'No se pudieron cargar las reglas de polivalencia.');
    const key=item=>[item.sector,item.funcion_legajero,item.operacion_madre].join('\u001f');
    const profileLabel=item=>`${item.sector} · ${item.funcion_legajero} · ${item.operacion_madre}`;
    panel.innerHTML=`<div class="status">${esc(data.nota||'')}</div><div style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin:10px 0"><label class="field">Perfil y operación madre<select class="input" id="pr-perfil">${(data.perfiles||[]).map((item,index)=>`<option value="${index}">${esc(profileLabel(item))}</option>`).join('')}</select></label><label class="field">Operaciones B adicionales (opcional)<select class="input" id="pr-operaciones" multiple size="6">${(data.operaciones||[]).map(item=>`<option value="${esc(item)}">${esc(item)}</option>`).join('')}</select></label><label class="field">Importe por jornada<input class="input" id="pr-importe" type="number" min="0" step="0.01" value="0"></label><button class="primary" id="pr-guardar">Guardar regla</button><button class="secondary" id="pr-desactivar">Desactivar</button></div><div class="table-wrap"><table><thead><tr><th>Sector</th><th>Función</th><th>Operación madre</th><th>Operaciones B</th><th>Importe por jornada</th><th>Estado</th><th>Acción</th></tr></thead><tbody id="pr-reglas-rows"></tbody></table></div>`;
    const profiles=data.perfiles||[], rules=data.reglas||[], cents=value=>Math.round((Number(String(value||'').replace(',','.'))||0)*100), amount=value=>(Number(value||0)/100).toLocaleString('es-AR',{style:'currency',currency:'ARS'});
    const selectedProfile=()=>profiles[Number($('pr-perfil').value)]||null;
    const loadRule=()=>{const profile=selectedProfile();if(!profile)return;const rule=rules.find(item=>key(item)===key(profile));const selected=new Set(rule?.operaciones_b||[]);[...$('pr-operaciones').options].forEach(option=>option.selected=selected.has(option.value));$('pr-importe').value=rule?((Number(rule.premio_centavos||0)/100).toFixed(2)):'0';$('pr-desactivar').disabled=!rule||!Number(rule.activo);};
    const save=async activo=>{const profile=selectedProfile();if(!profile)throw Error('Elegí un perfil con parámetros grupales activos.');const operaciones_b=[...$('pr-operaciones').selectedOptions].map(option=>option.value);const q=await fetch('/api/estudio-premios-productividad/polivalencia-reglas',{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({...profile,operaciones_b,premio_centavos:cents($('pr-importe').value),activo})});const answer=await q.json().catch(()=>({}));if(!q.ok)throw Error(answer.detail||'No se pudo guardar la regla.');await installProfilePolivalencias();};
    $('pr-perfil').onchange=loadRule;$('pr-guardar').onclick=async()=>{const button=$('pr-guardar');button.disabled=true;try{await save(true);$('status').style.color='';$('status').textContent='Regla de polivalencia guardada.';}catch(error){$('status').textContent=error.message;$('status').style.color='#C8102E';}finally{button.disabled=false;}};$('pr-desactivar').onclick=async()=>{const button=$('pr-desactivar');button.disabled=true;try{await save(false);$('status').style.color='';$('status').textContent='Regla de polivalencia desactivada.';}catch(error){$('status').textContent=error.message;$('status').style.color='#C8102E';}finally{button.disabled=false;}};
    $('pr-reglas-rows').innerHTML=rules.map((item,index)=>`<tr><td>${esc(item.sector)}</td><td>${esc(item.funcion_legajero)}</td><td>${esc(item.operacion_madre)}</td><td>${esc((item.operaciones_b||[]).join(' · ')||'—')}</td><td class="mono">${amount(item.premio_centavos)}</td><td>${Number(item.activo)?'Activa':'Inactiva'}</td><td><button class="secondary" data-pr-editar="${index}">Editar</button></td></tr>`).join('')||'<tr><td colspan="7">Todavía no hay reglas de polivalencia configuradas.</td></tr>';
    document.querySelectorAll('[data-pr-editar]').forEach(button=>button.onclick=()=>{const rule=rules[Number(button.dataset.prEditar)],index=profiles.findIndex(item=>key(item)===key(rule));if(index<0)return;$('pr-perfil').value=String(index);loadRule();$('pr-perfil').focus();});
    loadRule();
  };
  window.renderPolivalenciaPerfil=installProfilePolivalencias;
  const installUnified = () => {
    if ($('view-palets-unificados')) return;
    const view=document.createElement('section');view.className='view';view.id='view-palets-unificados';view.innerHTML='<div class="view-title"><strong>Palets carga + traslado</strong><span>aporte unificado por etapa y palet</span></div><div class="status" id="pu-meta"></div><div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Legajo</th><th>Palets trabajados</th><th>Etapas traslado</th><th>Etapas carga</th></tr></thead><tbody id="pu-rows"></tbody></table></div></section>';document.querySelector('main').appendChild(view);
    const recalcular=document.createElement('button');recalcular.className='secondary';recalcular.id='pu-recalcular';recalcular.textContent='Recalcular aportes';view.querySelector('.view-title').appendChild(recalcular);
    const load=async()=>{const q=new URLSearchParams({fecha_desde:$('desde').value,fecha_hasta:$('hasta').value,legajo:$('legajo').value.trim()});const r=await fetch('/api/estudio-premios-productividad/palets-carga-traslado?'+q,{credentials:'same-origin'}),d=await r.json();if(!r.ok)throw Error(d.detail||'No se pudieron cargar los palets.');$('pu-rows').innerHTML=(d.rows||[]).map(x=>`<tr><td>${esc(x.fecha)}</td><td>${esc(x.legajo)}</td><td>${esc(x.palets_trabajados)}</td><td>${esc(x.traslados)}</td><td>${esc(x.cargas)}</td></tr>`).join('')||'<tr><td colspan="5">No hay contribuciones calculadas para el período.</td></tr>';$('pu-meta').textContent=`${d.total||0} jornadas · traslado seguido de carga del mismo legajo cuenta una vez`;};
    recalcular.onclick=async()=>{recalcular.disabled=true;try{const q=new URLSearchParams({fecha_desde:$('desde').value,fecha_hasta:$('hasta').value});const r=await fetch('/api/estudio-premios-productividad/palets-carga-traslado/recalcular?'+q,{method:'POST',credentials:'same-origin'}),d=await r.json();if(!r.ok)throw Error(d.detail||'No se pudieron recalcular los aportes.');await load();$('pu-meta').textContent=`${d.contribuciones||0} aportes recalculados. ${$('pu-meta').textContent}`;}catch(error){$('pu-meta').textContent=error.message;}finally{recalcular.disabled=false;}};
    document.querySelector('[data-view="palets-unificados"]').addEventListener('click',()=>setTimeout(()=>load().catch(e=>$('pu-meta').textContent=e.message),0));
  };
  const installCompoundComponents = async () => {
    const body=$('param-grupal-rows'); if(!body) return;
    const r=await fetch('/api/estudio-premios-productividad/parametros-grupales',{credentials:'same-origin'}),d=await r.json(); if(!r.ok) throw Error(d.detail||'No se pudieron cargar componentes.');
    const table=body.closest('table'); const head=table.tHead.rows[0]; if(!head.querySelector('[data-componentes-head]')){const th=document.createElement('th');th.dataset.componentesHead='1';th.textContent='Funciones WMS (Palet = 1)';head.insertBefore(th,head.lastElementChild);}
    [...body.rows].forEach((row,index)=>{const item=d.rows[index];if(!item)return;const selected=new Set((item.componentes||[]).map(x=>x.funcion_wms));const origen=item.componentes_origen==='operacion'?'Definición de la operación':'Personalizado';const cell=document.createElement('td');cell.className='pg-componentes';cell.innerHTML=`<details class="pg-componentes-editor"><summary><strong>${selected.size?`${selected.size} componentes`:'Sin componentes'}</strong><small>${esc(origen)}</small></summary><div class="pg-componentes-contenido"><select class="input" multiple size="6" data-comp="${index}">${(d.funciones_wms||[]).map(x=>`<option value="${esc(x)}" ${selected.has(x)?'selected':''}>${esc(x)}</option>`).join('')}</select><button class="secondary pg-componentes-guardar" data-comp-save="${index}">Guardar componentes</button></div></details>`;row.insertBefore(cell,row.lastElementChild);cell.querySelector('[data-comp-save]').onclick=async event=>{const b=event.currentTarget,ops=[...cell.querySelector('select').selectedOptions].map(x=>x.value);b.disabled=true;try{const response=await fetch('/api/estudio-premios-productividad/parametros-grupales/componentes',{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({sector:item.sector,funcion_legajero:item.funcion_legajero,turno:item.turno,funciones_wms:ops})}),answer=await response.json();if(!response.ok)throw Error(answer.detail||'No se pudieron guardar componentes.');cell.querySelector('summary strong').textContent=`${answer.componentes.length} componentes`;cell.querySelector('summary small').textContent='Personalizado';b.textContent='Guardado';}catch(error){b.textContent='Error';$('status').textContent=error.message;}finally{b.disabled=false;}};});
  };
  document.addEventListener('DOMContentLoaded',()=>{const tab=document.querySelector('[data-view="resumen-legajos"]');tab?.addEventListener('click',()=>setTimeout(installSummaryDetail,80));setTimeout(installSummaryDetail,0);});
  document.addEventListener('DOMContentLoaded',()=>{installSummary();installPol();installMapFilters();installUnified();installTotalsCards();document.querySelector('[data-view="resumen-legajos"]').addEventListener('click',()=>setTimeout(installSummary,25));document.querySelector('[data-param-view="param-grupal"]').addEventListener('click',()=>setTimeout(()=>installCompoundComponents().catch(e=>$('status').textContent=e.message),60));document.querySelector('[data-view="premios-totales"]').addEventListener('click',()=>setTimeout(()=>{installTotalsCards();totals();},50));document.addEventListener('click',async event=>{const button=event.target.closest('[data-etapa-detalle]');if(!button)return;const row=button.closest('tr');const existing=row.nextElementSibling;if(existing?.dataset.etapaDetalle){existing.remove();return;}button.disabled=true;button.textContent='…';try{const cells=row.cells,q=new URLSearchParams({fecha:cells[0].textContent.trim(),legajo:cells[1].textContent.trim(),id_etapa:cells[2].textContent.trim()});const response=await fetch('/api/estudio-premios-productividad/cache-wms/etapa-detalle?'+q,{credentials:'same-origin'}),data=await response.json();if(!response.ok)throw Error(data.detail||'No se pudo leer el detalle.');const detail=document.createElement('tr');detail.dataset.etapaDetalle='1';detail.innerHTML=`<td colspan="15"><strong>Filas fuente:</strong> ${(data.rows||[]).map(x=>`#${esc(x.source_row_num)} · palet ${esc(x.pallet||'—')} · PLU ${esc(x.plu||'—')} · cantidad ${esc(x.cantidad??'—')} · peso ${esc(x.peso??'—')}`).join(' &nbsp; | &nbsp; ')||'Sin filas'}</td>`;row.after(detail);button.textContent='Ocultar';}catch(error){button.textContent='Error';}finally{button.disabled=false;}});});
  const bindProfilePolivalencias=()=>{const button=document.querySelector('[data-param-view="polivalencias"]');if(!button||button.dataset.profileRulesBound)return;button.dataset.profileRulesBound='1';const activate=()=>setTimeout(()=>installProfilePolivalencias().catch(error=>{$('status').textContent=error.message;}),0),previous=button.onclick;button.onclick=event=>{const result=previous?.call(button,event);activate();return result;};};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bindProfilePolivalencias);else bindProfilePolivalencias();
})();
