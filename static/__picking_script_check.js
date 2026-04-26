
// ══════════════════════════════════════════════════════════════════
//  DATOS DEL EXCEL (Programa 5441 — valores sugeridos por defecto)
// ══════════════════════════════════════════════════════════════════
let EXCEL_DATA = {
  programa: '5441',
  olas: [
    { num:1,  label:'OLA 1',  turno:'Tarde',  ini:14, fin:16,
      progSecos:12342, progNOA:2817,  ejecSecos:14273, ejecNOA:1670,
      dotProg:48, dotEjec:60, prodProg:315.80, prodEjec:265.72, obs:'' },
    { num:2,  label:'OLA 2',  turno:'Tarde',  ini:16, fin:18,
      progSecos:13302, progNOA:1354,  ejecSecos:12654, ejecNOA:1965,
      dotProg:48, dotEjec:60, prodProg:305.34, prodEjec:243.65, obs:'' },
    { num:3,  label:'OLA 3',  turno:'Tarde',  ini:18, fin:20,
      progSecos:10297, progNOA:986,   ejecSecos:10053, ejecNOA:1702,
      dotProg:48, dotEjec:50, prodProg:235.07, prodEjec:235.10, obs:'' },
    { num:4,  label:'OLA 4',  turno:'Tarde',  ini:20, fin:22,
      progSecos:8733,  progNOA:1250,  ejecSecos:9877,  ejecNOA:1798,
      dotProg:48, dotEjec:50, prodProg:207.98, prodEjec:233.50, obs:'' },
    { num:5,  label:'OLA 5',  turno:'Noche',  ini:22, fin:24,
      progSecos:13039, progNOA:1609,  ejecSecos:10012, ejecNOA:1381,
      dotProg:47, dotEjec:55, prodProg:311.66, prodEjec:207.15,
      obs:'Pasa 1 armador de refrigerados a secos' },
    { num:6,  label:'OLA 6',  turno:'Noche',  ini:0,  fin:2,
      progSecos:6667,  progNOA:2298,  ejecSecos:11276, ejecNOA:1520,
      dotProg:47, dotEjec:55, prodProg:190.74, prodEjec:232.65, obs:'' },
    { num:7,  label:'OLA 7',  turno:'Noche',  ini:2,  fin:4,
      progSecos:11405, progNOA:1369,  ejecSecos:6870,  ejecNOA:1077,
      dotProg:47, dotEjec:45, prodProg:271.80, prodEjec:176.60,
      obs:'Se refuerza NOA con 4 operarios de secos' },
    { num:8,  label:'OLA 8',  turno:'Noche',  ini:4,  fin:6,
      progSecos:9775,  progNOA:516,   ejecSecos:9126,  ejecNOA:879,
      dotProg:47, dotEjec:45, prodProg:218.95, prodEjec:222.33,
      obs:'Los 4 operarios retornan a secos' },
    { num:9,  label:'OLA 9',  turno:'Mañana', ini:6,  fin:8,
      progSecos:15361, progNOA:1103,  ejecSecos:18008, ejecNOA:713,
      dotProg:58, dotEjec:81, prodProg:283.86, prodEjec:231.12,
      obs:'Pasan armadores de NOA, Refri a Secos y 1 maquinista de Refri' },
    { num:10, label:'OLA 10', turno:'Mañana', ini:8,  fin:10,
      progSecos:16929, progNOA:681,   ejecSecos:12666, ejecNOA:814,
      dotProg:58, dotEjec:81, prodProg:303.63, prodEjec:166.42, obs:'' },
    { num:11, label:'OLA 11', turno:'Mañana', ini:10, fin:12,
      progSecos:12309, progNOA:905,   ejecSecos:16320, ejecNOA:1023,
      dotProg:58, dotEjec:72, prodProg:227.83, prodEjec:240.88, obs:'' },
    { num:12, label:'OLA 12', turno:'Mañana', ini:12, fin:14,
      progSecos:12707, progNOA:1022,  ejecSecos:12658, ejecNOA:1682,
      dotProg:58, dotEjec:71, prodProg:236.71, prodEjec:201.97, obs:'' },
  ],
  turnoTotales: {
    Tarde:  { prog:51081, ejec:53992 },
    Noche:  { prog:46678, ejec:42141 },
    Mañana: { prog:61018, ejec:63884 },
  }
};

async function loadCumplimientoData() {
  try {
    const res = await fetch('/api/cumplimiento/ultimo');
    if (!res.ok) throw new Error('No se pudo cargar cumplimiento');
    const data = await res.json();
    if (!data || !Array.isArray(data.olas) || data.olas.length === 0) return;
    EXCEL_DATA = {
      programa: data.programa || EXCEL_DATA.programa,
      olas: data.olas,
      turnoTotales: data.turnoTotales || EXCEL_DATA.turnoTotales,
    };
  } catch (err) {
    console.warn('Cumplimiento: usando datos locales por fallback.', err);
  }
}

// ── Estado ────────────────────────────────────────────────────────
let selectedOla    = detectOlaActual();
let activeProvider = 'claude';
let providersLoaded = false;
let aiAlerts       = [];
let chatHistory    = [];
let dashboardLive  = false;
let currentFormData = null;  // datos confirmados más recientes
let historicoOlas   = {};    // {ola_num → prom_ejec} actualizado tras cada análisis IA
let modoReal        = false; // false = prueba (sin guardar), true = datos reales (guarda en BD)
let analisisProductividadCache = null;
let analisisProductividadLoading = false;
let analisisProductividadIaLoading = false;
let analisisProductividadIaCache = null;
let onlineTurnoState = null;
let plantelTurns = [];
let plantelLastResult = null;
let plantelLoading = false;

const fmt   = n => Math.round(n).toLocaleString('es');
const fmtF  = n => parseFloat(n).toFixed(1);
const nowStr= () => { const n=new Date(); return String(n.getHours()).padStart(2,'0')+':'+String(n.getMinutes()).padStart(2,'0'); };

// ── Detectar ola actual por hora ──────────────────────────────────
function detectOlaActual() {
  const h = new Date().getHours() + new Date().getMinutes()/60;
  const idx = EXCEL_DATA.olas.findIndex(o => {
    if (o.ini < o.fin) return h >= o.ini && h < o.fin;
    return h >= o.ini || h < o.fin;
  });
  return idx >= 0 ? idx : 8; // default OLA 9 si no hay match
}

function turnoKey(turno) {
  const raw = String(turno || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  if (raw.includes('man')) return 'manana';
  if (raw.includes('tar')) return 'tarde';
  if (raw.includes('noc')) return 'noche';
  return raw;
}

function turnoLabel(turno) {
  const key = turnoKey(turno);
  if (key === 'manana') return 'Mañana';
  if (key === 'tarde') return 'Tarde';
  if (key === 'noche') return 'Noche';
  return turno || '';
}

function turnoTagClass(turno) {
  const key = turnoKey(turno);
  if (key === 'manana') return 'Manana';
  if (key === 'tarde') return 'Tarde';
  if (key === 'noche') return 'Noche';
  return turno || '';
}

function updateOnlineTurnoStatus(payload) {
  const el = document.getElementById('online-tab-status');
  if (!el) return;
  if (!payload) {
    el.textContent = 'Tomará el turno de la ola seleccionada en pantalla y cerrará al último corte de 15 minutos.';
    return;
  }
  const origen = payload.oracle_usado ? 'Oracle + cache local' : 'Cache local';
  const refresco = payload.sin_actualizacion_productiva
    ? `Sin actualización nueva. Se mantiene la sugerencia del corte ${payload.corte_hasta || '—'}.`
    : `${payload.bloques_nuevos || 0} bloque(s) nuevos incorporados hasta ${payload.corte_hasta || '—'}.`;
  el.textContent = `Turno ${payload.turno || '—'} · inicio ${payload.turno_inicio || '—'} · ${origen}. ${refresco}`;
}

function mergeOnlineTurnoData(payload) {
  if (!payload || !Array.isArray(payload.olas)) return;
  const turno = payload.turno;
  EXCEL_DATA.olas = EXCEL_DATA.olas.map(ola => {
    if (turnoKey(ola.turno) !== turnoKey(turno)) return ola;
    const updated = payload.olas.find(item => Number(item.num) === Number(ola.num));
    if (!updated) return ola;
    return {
      ...ola,
      turno: updated.turno || ola.turno,
      ejecSecos: updated.ejecSecos ?? ola.ejecSecos,
      ejecNOA: updated.ejecNOA ?? ola.ejecNOA,
      ejecTotal: updated.ejecTotal ?? ola.ejecTotal,
      dotEjec: updated.dotEjec ?? ola.dotEjec,
      prodEjec: updated.prodEjec ?? ola.prodEjec,
      obs: updated.obs ?? ola.obs,
    };
  });
  EXCEL_DATA.turnoTotales = {
    ...EXCEL_DATA.turnoTotales,
    ...(payload.turnoTotales || {}),
  };
}

function fillFormWithOnlineSelected(selected) {
  if (!selected) return;
  const setManual = (inputId, sugId, value) => {
    const input = document.getElementById(inputId);
    const suggestion = document.getElementById(sugId);
    if (input) {
      input.value = value ?? '';
      input.classList.remove('manual-empty');
      input.classList.add('manual-input');
    }
    if (suggestion) {
      suggestion.textContent = `(Oracle: ${(value ?? 0).toLocaleString ? value.toLocaleString('es-AR') : value})`;
    }
  };
  setManual('f-ejec-secos', 'sug-ejec-secos', selected.ejecSecos || 0);
  setManual('f-ejec-noa', 'sug-ejec-noa', selected.ejecNOA || 0);
  setManual('f-dot-ejec', 'sug-dot-ejec', selected.dotEjec || 0);
  document.getElementById('f-obs').value = selected.obs || '';
  updateAutoFields();
}

function renderOnlineTurnoResult(data) {
  const container = document.getElementById('online-tab-results');
  if (!container) return;
  if (!data) {
    container.innerHTML = '<div class="analisis-empty">Todavía no se ejecutó el análisis on line.</div>';
    return;
  }

  const resumen = data.resumen || {};
  const ultimoBloque = (Array.isArray(data.bloques) && data.bloques.length)
    ? data.bloques[data.bloques.length - 1].cantidad
    : 0;
  const zonas = Array.isArray(data.zonas) ? data.zonas.slice(0, 4) : [];
  container.innerHTML = `
    <div class="online-meta">
      <div class="online-meta-card">
        <strong>Turno analizado:</strong> ${data.turno || '—'} · <strong>Inicio:</strong> ${data.turno_inicio || '—'} · <strong>Corte:</strong> ${data.corte_hasta || '—'}<br>
        <strong>Origen:</strong> ${data.oracle_usado ? 'Oracle + cache local' : 'Cache local'} · <strong>Bloques nuevos:</strong> ${data.bloques_nuevos || 0} · <strong>Actualización productiva:</strong> ${data.sin_actualizacion_productiva ? 'sin cambios' : 'con datos nuevos'}
      </div>
    </div>
    <div class="online-kpis">
      <div class="online-kpi">
        <div class="online-kpi-label">Acumulado real</div>
        <div class="online-kpi-value">${(resumen.cantidad_total || 0).toLocaleString('es-AR')}</div>
        <div class="online-kpi-sub">Desde inicio de turno</div>
      </div>
      <div class="online-kpi">
        <div class="online-kpi-label">Movimientos</div>
        <div class="online-kpi-value">${(resumen.movimientos_total || 0).toLocaleString('es-AR')}</div>
        <div class="online-kpi-sub">Registros Oracle acumulados</div>
      </div>
      <div class="online-kpi">
        <div class="online-kpi-label">Promedio picking</div>
        <div class="online-kpi-value">${(resumen.productividad_operario || 0).toLocaleString('es-AR')}</div>
        <div class="online-kpi-sub">Bultos por operario acumulado</div>
      </div>
      <div class="online-kpi">
        <div class="online-kpi-label">Prod. por hora</div>
        <div class="online-kpi-value">${(resumen.ritmo_turno_hora || 0).toLocaleString('es-AR')}</div>
        <div class="online-kpi-sub">${(resumen.operarios_activos || 0).toLocaleString('es-AR')} operarios activos</div>
      </div>
    </div>
    <div class="online-suggestion">
      <div class="online-suggestion-top">
        <span class="online-suggestion-badge">Sugerencia ejecutiva del turno</span>
        <span class="online-suggestion-provider">Motor: <strong>${String(data.ia_provider || 'ia').toUpperCase()}</strong> · ${data.ia_model || 'modelo no informado'}${data.ia_generated_at ? ' · ' + data.ia_generated_at : ''}</span>
      </div>
      <div class="online-suggestion-text">${data.sugerencia_ia || 'Sin sugerencia disponible.'}</div>
      <div class="online-suggestion-expand">
        <button class="online-suggestion-toggle" onclick="toggleOnlineSuggestionDetail(this)">Ver detalle</button>
        <div class="online-suggestion-detail">${data.sugerencia_detalle || 'Si hacés esto ahora, deberías sostener mejor la productividad del turno en el próximo bloque.'}</div>
      </div>
    </div>
    <div class="online-summary">
      <div class="analisis-section-title" style="margin-bottom:10px;">Resumen interno</div>
      ${data.internal_summary || 'Sin resumen interno disponible.'}<br><br>
      <strong>Último bloque de 15 minutos:</strong> ${(ultimoBloque || 0).toLocaleString('es-AR')} bultos<br>
      <strong>Zonas con más volumen:</strong> ${zonas.length ? zonas.map(z => `${z.zona}: ${Math.round(z.cantidad_total).toLocaleString('es-AR')}`).join(' · ') : 'Sin datos'}
    </div>
  `;
}

function toggleOnlineSuggestionDetail(btn) {
  const detail = btn?.parentElement?.querySelector('.online-suggestion-detail');
  if (!detail) return;
  const visible = detail.classList.toggle('visible');
  btn.textContent = visible ? 'Ocultar detalle' : 'Ver detalle';
}

async function actualizarTurnoOnline() {
  const btn = document.getElementById('btn-online-turno');
  const o = EXCEL_DATA.olas[selectedOla];
  if (!btn || !o) return;

  btn.disabled = true;
  btn.textContent = '⏳ Consultando...';
  switchMainTab('productividad');
  switchProdTab('online');
  updateOnlineTurnoStatus({
    turno: turnoLabel(o.turno),
    turno_inicio: 'calculando',
    corte_hasta: 'calculando',
    oracle_usado: true,
    bloques_nuevos: 0,
    sugerencia_reutilizada: true,
    ia_provider: activeProvider || 'ia',
    ia_generated_at: '',
    sin_actualizacion_productiva: false,
  });

  try {
    const resp = await fetch('/api/cumplimiento/online-turno', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        turno: o.turno,
        ola_num: o.num,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'No se pudo consultar productividad online.');

    onlineTurnoState = data;
    mergeOnlineTurnoData(data);
    updateOnlineTurnoStatus(data);
    renderOnlineTurnoResult(data);

    const refreshedIndex = EXCEL_DATA.olas.findIndex(item => Number(item.num) === Number(data.selected_ola?.num));
    if (refreshedIndex >= 0) {
      selectedOla = refreshedIndex;
    }
    initForm();
    fillFormWithOnlineSelected(data.selected_ola);
  } catch (err) {
    updateOnlineTurnoStatus(null);
    renderOnlineTurnoResult({
      turno: turnoLabel(o.turno),
      turno_inicio: '—',
      corte_hasta: '—',
      oracle_usado: false,
      bloques_nuevos: 0,
      sin_actualizacion_productiva: true,
      ia_provider: activeProvider || 'ia',
      ia_model: '—',
      ia_generated_at: '',
      sugerencia_ia: 'Usar carga manual o reintentar en el próximo corte.',
      internal_summary: err.message || 'No se pudo actualizar el turno desde Oracle.',
      resumen: {},
      esperado: {},
      selected_ola: { label: o.label, ejecTotal: 0, dotEjec: 0, prodEjec: 0 },
    });
  } finally {
    btn.disabled = false;
    btn.textContent = '⟳ Oracle online';
  }
}

// ── Modo Prueba / Real ────────────────────────────────────────────
function toggleModoReal() {
  modoReal = !modoReal;
  const btn = document.getElementById('modo-btn');
  if (modoReal) {
    btn.className = 'modo-btn real';
    btn.textContent = '✅ REAL';
    btn.title = 'REAL: los datos se guardarán en la BD al analizar';
  } else {
    btn.className = 'modo-btn prueba';
    btn.textContent = '🧪 PRUEBA';
    btn.title = 'PRUEBA: los cálculos NO se guardan en la BD';
  }
}

// ── Capa 3: Proyección histórica ──────────────────────────────────
function updateProjectionHistorico(d) {
  if (!d || Object.keys(historicoOlas).length === 0) return;

  const olasDelTurno = EXCEL_DATA.olas.filter(o => o.turno === d.turno);
  const olasPast     = olasDelTurno.filter(o => o.num < d.olaNum);
  const olasRest     = olasDelTurno.filter(o => o.num > d.olaNum);

  const pastEjec = olasPast.reduce((a, o) => a + o.ejecSecos + o.ejecNOA, 0);

  // Para cada ola futura: usar promedio histórico si existe, sino ratio actual
  let restEstim    = 0;
  let usaHistorico = false;
  const ratio = d.progTotal > 0 ? d.ejecTotal / d.progTotal : 1;
  olasRest.forEach(o => {
    const hist = historicoOlas[String(o.num)] ?? historicoOlas[o.num];
    if (hist != null) {
      restEstim += hist;
      usaHistorico = true;
    } else {
      restEstim += (o.progSecos + o.progNOA) * ratio;
    }
  });

  const proyeccion = pastEjec + d.ejecTotal + restEstim;
  const objTurno   = EXCEL_DATA.turnoTotales[d.turno]?.prog || 0;
  const gap        = proyeccion - objTurno;

  // KPI Proyección Cierre
  const projEl = document.getElementById('kpi-proj');
  if (projEl) {
    const badge = usaHistorico ? '<span class="hist-badge">HIST</span>' : '';
    projEl.innerHTML = fmt(proyeccion) + (badge ? ' ' + badge : '');
    const ps = document.getElementById('kpi-proj-sub');
    if (ps) {
      const projDiff = proyeccion - objTurno;
      ps.className   = 'kpi-sub ' + (projDiff>=0?'good':projDiff>=-objTurno*0.05?'warn':'bad');
      ps.textContent = projDiff>=0
        ? '✓ +'+fmt(projDiff)+' sobre objetivo'
        : '⚠ déficit est. '+fmt(Math.abs(projDiff))+' bultos';
    }
  }

  // KPI Desvío (ola actual — no cambia, pero actualizamos card de proyección)
  const gEl   = document.getElementById('kpi-gap');
  const gCard = gEl ? gEl.closest('.kpi') : null;
  // El desvío de ola no cambia; lo que refrescamos es el color del card proyección
  const projCard = projEl ? projEl.closest('.kpi') : null;
  if (projCard) {
    projCard.className = 'kpi ' + (gap >= 0 ? 'green' : gap >= -objTurno * 0.05 ? 'yellow' : 'orange');
  }

  // Proyección box (panel inferior)
  const ptEl = document.getElementById('proj-total');
  if (ptEl) ptEl.textContent = fmt(proyeccion) + ' bultos';
  const pgEl = document.getElementById('proj-gap');
  if (pgEl) {
    const br = objTurno - proyeccion;
    pgEl.textContent = br<=0 ? '+'+fmt(Math.abs(br))+' excedente' : fmt(br)+' faltantes';
    pgEl.style.color = br<=0 ? 'var(--accent)' : 'var(--accent2)';
  }
}

function initProviderBar() {
  document.querySelector('.ai-provider-bar label').textContent = 'Proveedor IA';
  const wrap = document.getElementById('provider-btns');
  document.getElementById('ai-alerts').innerHTML =
    '<div style="font-size:11px;color:var(--muted)">Todavía no se ejecutó ningún análisis.</div>';
  wrap.innerHTML = '<span style="font-size:11px;color:var(--muted)">cargando...</span>';
  updateAiBadge(activeProvider);
  setProviderStatus('Listo para editar · sin consulta inicial', '');
  loadProviders();
}

async function ensureProvidersLoaded() {
  if (providersLoaded) return;
  setProviderStatus('Verificando proveedores...', 'loading');
  try {
    const data = await fetch('/api/providers').then(r => r.json());
    providersLoaded = true;
    if (data.available?.some(p => p.id === activeProvider && p.configured)) {
      data.active = activeProvider;
    }
    renderProviderBtns(data);
  } catch (e) {
    setProviderStatus('No se pudieron verificar proveedores', 'err');
  }
}

// ── Inicializar formulario ────────────────────────────────────────
function initForm() {
  // Botones de ola
  const wrap = document.getElementById('ola-btns');
  wrap.innerHTML = '';
  const groups = [
    { key: 'manana', label: 'Turno mañana' },
    { key: 'tarde', label: 'Turno tarde' },
    { key: 'noche', label: 'Turno noche' },
  ];
  groups.forEach(group => {
    const row = document.createElement('div');
    row.className = 'ola-btn-row';

    const rowLabel = document.createElement('div');
    rowLabel.className = 'ola-row-label';
    rowLabel.textContent = group.label;
    row.appendChild(rowLabel);

    const buttons = document.createElement('div');
    buttons.className = 'ola-row-buttons';
    EXCEL_DATA.olas.forEach((o, i) => {
      if (turnoKey(o.turno) !== group.key) return;
      const btn = document.createElement('button');
      btn.className = 'ola-btn' + (i === selectedOla ? ' active' : '');
      btn.textContent = `${o.ini}:00 a ${o.fin === 24 ? '00:00' : o.fin + ':00'} ${o.label}`;
      btn.onclick = () => selectOla(i);
      buttons.appendChild(btn);
    });

    if (!buttons.children.length) return;
    row.appendChild(buttons);
    wrap.appendChild(row);
  });
  loadOlaIntoForm(selectedOla);
}

function selectOla(idx) {
  selectedOla = idx;
  document.querySelectorAll('.ola-btn').forEach((b, i) => {
    b.className = 'ola-btn' + (i === idx ? ' active' : '');
  });
  loadOlaIntoForm(idx);
  resetPlantelForm();
}

function loadOlaIntoForm(idx) {
  const o = EXCEL_DATA.olas[idx];
  const finStr = o.fin === 24 ? '00:00' : o.fin + ':00';

  // Tags de turno y horario (incluir tiempo transcurrido)
  const turnoTag = document.getElementById('turno-tag');
  turnoTag.textContent = turnoLabel(o.turno);
  turnoTag.className = 'ola-turno-tag ' + turnoTagClass(o.turno);

  const ahora = new Date();
  const horaActual = ahora.getHours() + ahora.getMinutes() / 60;
  let minTranscurridos = Math.round((horaActual - o.ini) * 60);
  if (minTranscurridos < 0) minTranscurridos += 24 * 60; // cruzó medianoche
  const horasT = Math.floor(minTranscurridos / 60);
  const minT = minTranscurridos % 60;
  const tiempoStr = horasT > 0 ? `${horasT}h ${minT}m` : `${minT}m`;

  document.getElementById('ola-horario').textContent = o.ini + ':00 – ' + finStr + ' · ' + tiempoStr + ' transcurridos';
  document.getElementById('form-ola-tag').textContent = o.label + ' · ' + turnoLabel(o.turno);

  // Poblar campos con valores sugeridos (programados — vienen del Excel)
  setField('f-prog-secos', o.progSecos, 'sug-prog-secos', o.progSecos);
  setField('f-prog-noa',   o.progNOA,   'sug-prog-noa',   o.progNOA);
  setField('f-dot-prog',   o.dotProg,   'sug-dot-prog',   o.dotProg);

  // Campos de ingreso manual — siempre vacíos al cargar
  clearManualField('f-ejec-secos', 'sug-ejec-secos', o.ejecSecos);
  clearManualField('f-ejec-noa',   'sug-ejec-noa',   o.ejecNOA);
  clearManualField('f-dot-ejec',   'sug-dot-ejec',   o.dotEjec);

  if (onlineTurnoState && turnoKey(onlineTurnoState.turno) === turnoKey(o.turno)) {
    fillFormWithOnlineSelected(o);
  }

  document.getElementById('f-obs').value = o.obs || '';
  document.getElementById('sug-obs').textContent = o.obs ? '(Excel: "'+o.obs+'")'  : '';

  updateAutoFields();
}

function clearManualField(inputId, sugId, sugValue) {
  const input = document.getElementById(inputId);
  input.value = '';
  input.classList.remove('modified', 'manual-empty');
  input.classList.add('manual-input');
  if (sugId) {
    document.getElementById(sugId).textContent = '(Excel: ' + (Number.isInteger(sugValue) ? sugValue.toLocaleString('es') : parseFloat(sugValue).toFixed(1)) + ')';
  }
}

function setField(inputId, value, sugId, sugValue) {
  const input = document.getElementById(inputId);
  input.value = value;
  input.classList.remove('modified');
  if (sugId) {
    document.getElementById(sugId).textContent = '(Excel: ' + (Number.isInteger(sugValue) ? sugValue.toLocaleString('es') : parseFloat(sugValue).toFixed(1)) + ')';
  }
}

function onFieldChange() {
  updateAutoFields();
  markModified();
}

function markModified() {
  const o = EXCEL_DATA.olas[selectedOla];
  // Solo marcan modified los campos que tienen valor sugerido del Excel (no los manuales)
  const checks = [
    ['f-prog-secos', o.progSecos],
    ['f-prog-noa',   o.progNOA],
    ['f-dot-prog',   o.dotProg],
  ];
  checks.forEach(([id, orig]) => {
    const el = document.getElementById(id);
    const v = parseFloat(el.value);
    el.classList.toggle('modified', Math.abs(v - orig) > 0.5);
  });
}

function updateAutoFields() {
  const ps = parseFloat(document.getElementById('f-prog-secos').value) || 0;
  const pn = parseFloat(document.getElementById('f-prog-noa').value) || 0;
  const progTotal = ps + pn;
  document.getElementById('f-prog-total').value = Math.round(progTotal);

  // Ejec. Total: sólo mostrar si al menos uno de los manuales tiene valor
  const esRaw = document.getElementById('f-ejec-secos').value;
  const enRaw = document.getElementById('f-ejec-noa').value;
  const es = parseFloat(esRaw) || 0;
  const en = parseFloat(enRaw) || 0;
  const ejecTotalEl = document.getElementById('f-ejec-total');
  if (esRaw === '' && enRaw === '') {
    ejecTotalEl.value = '';
  } else {
    ejecTotalEl.value = Math.round(es + en);
  }
  const ejecTotal = es + en;

  const dp = parseFloat(document.getElementById('f-dot-prog').value) || 0;
  const deRaw = document.getElementById('f-dot-ejec').value;
  const de = parseFloat(deRaw) || 0;
  document.getElementById('f-dot-dif').value = deRaw !== '' ? Math.round(de - dp) : '';

  // Productividad — calculada automáticamente
  const prodProgEl = document.getElementById('f-prod-prog');
  const prodEjecEl = document.getElementById('f-prod-ejec');
  const varEl = document.getElementById('f-prod-var');

  const pp = (progTotal > 0 && dp > 0) ? progTotal / dp : null;
  const pe = (ejecTotal > 0 && de > 0 && deRaw !== '') ? ejecTotal / de : null;

  prodProgEl.value = pp !== null ? pp.toFixed(1) : '';
  prodEjecEl.value = pe !== null ? pe.toFixed(1) : '';

  if (pp !== null && pe !== null) {
    const varP = pp > 0 ? ((pe - pp) / pp * 100) : 0;
    varEl.value = (varP >= 0 ? '+' : '') + varP.toFixed(1) + '%';
    varEl.style.color = varP >= 0 ? 'var(--accent)' : 'var(--accent2)';
  } else {
    varEl.value = '';
    varEl.style.color = '';
  }
}

function resetToSuggested() {
  loadOlaIntoForm(selectedOla);
}

function toggleForm() {
  const body = document.getElementById('form-body');
  const open = body.classList.contains('open');
  open ? _closeForm(body) : _openForm(body);
}

function _openForm(body) {
  body = body || document.getElementById('form-body');
  const chev = document.getElementById('form-chevron');
  body.style.display = 'block';
  body.classList.add('open');
  chev.textContent = '▲';
  chev.classList.add('open');
}

function _closeForm(body) {
  body = body || document.getElementById('form-body');
  const chev = document.getElementById('form-chevron');
  body.style.display = 'none';
  body.classList.remove('open');
  chev.textContent = '▼';
  chev.classList.remove('open');
}

// ── Leer formulario como objeto ───────────────────────────────────
function readForm() {
  const o = EXCEL_DATA.olas[selectedOla];
  return {
    olaIdx:    selectedOla,
    olaNum:    o.num,
    label:     o.label,
    turno:     o.turno,
    ini:       o.ini,
    fin:       o.fin,
    progSecos: parseFloat(document.getElementById('f-prog-secos').value) || 0,
    progNOA:   parseFloat(document.getElementById('f-prog-noa').value)   || 0,
    progTotal: parseFloat(document.getElementById('f-prog-total').value) || 0,
    ejecSecos: parseFloat(document.getElementById('f-ejec-secos').value) || 0,
    ejecNOA:   parseFloat(document.getElementById('f-ejec-noa').value)   || 0,
    ejecTotal: parseFloat(document.getElementById('f-ejec-total').value) || 0,
    dotProg:   parseFloat(document.getElementById('f-dot-prog').value)   || 0,
    dotEjec:   parseFloat(document.getElementById('f-dot-ejec').value)   || 0,
    prodProg:  parseFloat(document.getElementById('f-prod-prog').value)  || null,
    prodEjec:  parseFloat(document.getElementById('f-prod-ejec').value)  || null,
    obs:       document.getElementById('f-obs').value.trim(),
  };
}

// ══════════════════════════════════════════════════════════════════
//  CALCULAR Y ANALIZAR
// ══════════════════════════════════════════════════════════════════
async function calcularYAnalizar() {
  // Validar campos manuales obligatorios
  const manualFields = [
    { id: 'f-ejec-secos', label: 'Bultos Ejec. Secos' },
    { id: 'f-ejec-noa',   label: 'Bultos Ejec. NOA' },
    { id: 'f-dot-ejec',   label: 'Dotación Real' },
  ];
  const vacios = manualFields.filter(f => document.getElementById(f.id).value.trim() === '');

  if (vacios.length > 0) {
    // Resaltar campos vacíos
    manualFields.forEach(f => {
      const el = document.getElementById(f.id);
      if (el.value.trim() === '') {
        el.classList.add('manual-empty');
        el.classList.remove('manual-input');
        setTimeout(() => { el.classList.remove('manual-empty'); el.classList.add('manual-input'); }, 2000);
      }
    });

    // Mostrar mensaje de error
    const errMsg = document.getElementById('campos-vacios-msg');
    if (errMsg) {
      errMsg.style.display = 'flex';
      errMsg.textContent = '⚠ Completar: ' + vacios.map(f => f.label).join(', ');
      setTimeout(() => { errMsg.style.display = 'none'; }, 4000);
    }
    return;
  }

  const btn = document.getElementById('btn-calcular');
  btn.disabled = true;
  btn.textContent = '⏳ Calculando...';

  currentFormData = readForm();

  // Mostrar dashboard
  document.getElementById('dashboard-empty').style.display = 'none';
  document.getElementById('dashboard').style.display = 'block';
  dashboardLive = true;

  // Actualizar badge
  const badge = document.getElementById('status-badge');
  badge.className = 'badge b-live';
  badge.textContent = 'EN VIVO · ' + nowStr();

  // Renderizar dashboard con los datos del formulario
  renderDashboard(currentFormData);

  // Colapsar formulario
  _closeForm();

  // Llamar a la IA
  await runAiAnalysis(buildContext(currentFormData));

  btn.disabled = false;
  btn.textContent = '▶ Recalcular';
}

// ── Render del dashboard ──────────────────────────────────────────
function renderDashboard(d) {
  const gap  = d.ejecTotal - d.progTotal;
  const t    = EXCEL_DATA.turnoTotales[d.turno];

  // Proyección simple: si ejecTotal / progTotal ratio se mantiene para las olas restantes
  const ratio    = d.progTotal > 0 ? d.ejecTotal / d.progTotal : 1;
  const olasDelTurno = EXCEL_DATA.olas.filter(o => o.turno === d.turno);
  const olasRest = olasDelTurno.filter(o => o.num > d.olaNum);
  const restProg = olasRest.reduce((a, o) => a + o.progSecos + o.progNOA, 0);
  const olasPast = olasDelTurno.filter(o => o.num < d.olaNum);
  const pastEjec = olasPast.reduce((a, o) => a + o.ejecSecos + o.ejecNOA, 0);
  const proyeccion = pastEjec + d.ejecTotal + restProg * ratio;
  const objTurno   = t ? t.prog : d.progTotal * olasDelTurno.length;

  // KPIs
  document.getElementById('kpi-real').textContent     = fmt(d.ejecTotal);
  document.getElementById('kpi-real-sub').textContent = 'turno ' + d.turno + ' · ' + d.label;
  document.getElementById('kpi-exp').textContent      = fmt(d.progTotal);

  const gEl  = document.getElementById('kpi-gap');
  const gSub = document.getElementById('kpi-gap-sub');
  const gCard = gEl.closest('.kpi');
  gEl.textContent  = (gap>=0?'+':'') + fmt(gap);
  gEl.style.color  = '#ffffff';
  gCard.className  = 'kpi ' + (gap >= 0 ? 'green' : gap >= -d.progTotal * 0.05 ? 'yellow' : 'orange');
  gSub.className   = 'kpi-sub ' + (gap>=0 ? 'good' : 'bad');
  gSub.textContent = gap>=0 ? 'por encima del objetivo' : 'por debajo del objetivo';

  document.getElementById('kpi-proj').textContent = fmt(proyeccion);
  const projDiff = proyeccion - objTurno;
  const ps = document.getElementById('kpi-proj-sub');
  ps.className   = 'kpi-sub ' + (projDiff>=0?'good':projDiff>=-objTurno*0.05?'warn':'bad');
  ps.textContent = projDiff>=0
    ? '✓ +'+fmt(projDiff)+' sobre objetivo'
    : '⚠ déficit est. '+fmt(Math.abs(projDiff))+' bultos';

  // Proyección box
  document.getElementById('proj-rate').textContent  = fmtF(d.prodEjec) + ' b/op';
  document.getElementById('proj-dot').textContent   = d.dotEjec + ' operarios';
  document.getElementById('proj-total').textContent = fmt(proyeccion) + ' bultos';
  const br = objTurno - proyeccion;
  const gpe = document.getElementById('proj-gap');
  gpe.textContent = br<=0 ? '+'+fmt(Math.abs(br))+' excedente' : fmt(br)+' faltantes';
  gpe.style.color = br<=0 ? 'var(--accent)' : 'var(--accent2)';

  // Barras sectores
  renderBarras(d);

  // Olas
  renderOlas(d);

  // Operarios
  renderOperarios(d);
}

function renderBarras(d) {
  const el = document.getElementById('bar-chart');
  const rows = [
    { name:'Secos', prog:d.progSecos, ejec:d.ejecSecos, color:'#00e5a0' },
    { name:'NOA',   prog:d.progNOA,   ejec:d.ejecNOA,   color:'#00bcd4' },
  ];
  el.innerHTML = '';
  rows.forEach(r => {
    const max   = Math.max(r.prog, r.ejec) * 1.05 || 1;
    const pProg = r.prog / max;
    const pEjec = Math.min(r.ejec / max, 1.05);
    const diff  = r.ejec - r.prog;
    const color = diff >= 0 ? r.color : 'var(--accent2)';
    const pct   = r.prog > 0 ? Math.round(r.ejec/r.prog*100) : 0;
    el.innerHTML += `<div class="bar-row">
      <div class="bar-label">${r.name}</div>
      <div>
        <div class="bar-track">
          <div class="bar-expected" style="width:${pProg*100}%"></div>
          <div class="bar-actual" style="width:${pEjec*100}%;background:${color};opacity:.85"></div>
        </div>
        <div style="font-size:9px;color:var(--muted);margin-top:3px">
          ${fmt(r.ejec)} ejec / ${fmt(r.prog)} prog &nbsp;
          <span style="color:${diff>=0?'var(--accent)':'var(--accent2)'}">${diff>=0?'+':''}${fmt(diff)}</span>
        </div>
      </div>
      <div class="bar-pct" style="color:${color}">${pct}%</div>
    </div>`;
  });
}

function renderOlas(d) {
  const el = document.getElementById('olas-grid');
  const olasDelTurno = EXCEL_DATA.olas.filter(o => o.turno === d.turno);
  el.innerHTML = '';
  olasDelTurno.forEach(o => {
    const isPast    = o.num < d.olaNum;
    const isCurrent = o.num === d.olaNum;
    const cls       = isPast ? 'past' : isCurrent ? 'current' : 'future';

    let ejecDisplay, pAct, pExp, color;
    if (isPast) {
      const eT = o.ejecSecos + o.ejecNOA;
      const pT = o.progSecos + o.progNOA;
      pAct = Math.min(eT/pT, 1.1); pExp = 1;
      color = eT >= pT ? 'var(--accent)' : 'var(--accent2)';
      ejecDisplay = `<span style="color:${color}">${fmt(eT)}</span>`;
    } else if (isCurrent) {
      pAct = Math.min(d.ejecTotal/d.progTotal, 1.05); pExp = 1;
      color = d.ejecTotal >= d.progTotal ? 'var(--accent)' : 'var(--accent2)';
      ejecDisplay = `<span style="color:${color}">${fmt(d.ejecTotal)}</span>`;
    } else {
      pAct = 0; pExp = 1; color = 'var(--muted)';
      ejecDisplay = `<span style="color:var(--muted)">${fmt(o.progSecos+o.progNOA)}</span>`;
    }

    const finStr = o.fin === 24 ? '00' : o.fin;
    el.innerHTML += `<div class="ola-row ${cls}">
      <div class="ola-name">${o.label} · ${o.ini}:00–${finStr}:00</div>
      <div class="ola-bar-wrap">
        <div class="ola-bar-exp" style="width:${pExp*100}%"></div>
        <div class="ola-bar-act" style="width:${pAct*100}%;background:${color};opacity:.8"></div>
      </div>
      <div class="ola-prog">${fmt(o.progSecos+o.progNOA)}</div>
      <div class="ola-ejec">${ejecDisplay}</div>
    </div>`;
  });
}

function renderOperarios(d) {
  const el = document.getElementById('ops-grid');
  el.innerHTML = '';
  const n = Math.min(Math.max(Math.round(d.dotEjec), 1), 16);
  const nombres = ['García J.','Rodríguez M.','López K.','Martínez S.','Fernández R.',
                   'Díaz P.','Torres A.','Gómez C.','Núñez P.','Álvarez R.',
                   'Peralta D.','Sosa M.','Herrera F.','Romero G.','Castro L.','Medina T.'];
  for (let i = 0; i < n; i++) {
    const base  = d.prodEjec || 220;
    const perf  = Math.round(base * (0.88 + Math.random() * 0.24));
    const pct   = Math.round(perf/base*100);
    const color = perf>=base*0.95?'var(--accent)':perf>=base*0.80?'var(--warn)':'var(--accent2)';
    el.innerHTML += `<div class="op-card">
      <div class="op-name">${nombres[i]||'Op '+(i+1)}</div>
      <div class="op-stat" style="color:${color}">${perf} b/op</div>
      <div class="op-bar-track"><div class="op-bar-fill" style="width:${Math.min(pct,100)}%;background:${color}"></div></div>
    </div>`;
  }
}

// ── Contexto para IA ──────────────────────────────────────────────
function buildContext(d) {
  const gap       = d.ejecTotal - d.progTotal;
  const varDot    = d.dotEjec - d.dotProg;
  const varProd   = d.prodProg > 0 ? ((d.prodEjec - d.prodProg) / d.prodProg * 100) : 0;
  const olasDelTurno = EXCEL_DATA.olas.filter(o => o.turno === d.turno);
  const olasRest  = olasDelTurno.filter(o => o.num > d.olaNum).length;

  const _now = new Date();
  const nowMin = _now.getHours() * 60 + _now.getMinutes();
  const iniMin = d.ini * 60;
  const finMin = (d.fin === 24 ? 1440 : d.fin * 60);
  const durMin = finMin - iniMin;
  const transcurridos = Math.min(Math.max(0, nowMin - iniMin), durMin);
  const restantes     = Math.max(0, finMin - nowMin);
  const pctTiempo     = durMin > 0 ? Math.round(transcurridos / durMin * 100) : 0;
  const estadoOla     = nowMin < iniMin ? 'OLA NO INICIADA'
                      : nowMin >= finMin ? 'OLA CERRADA'
                      : 'OLA EN CURSO';

  return `VIGIA · ESTADO OPERATIVO — CD Coto · Programa ${EXCEL_DATA.programa}
Turno: ${d.turno} | ${d.label} (${d.ini}:00–${d.fin===24?'00:00':d.fin+':00'}) | ${nowStr()} hs
TIEMPO DE OLA: ${transcurridos} min transcurridos / ${restantes} min restantes (${pctTiempo}% del tiempo de ola transcurrido) — ${estadoOla}

BULTOS:
- Programado: Secos ${fmt(d.progSecos)} + NOA ${fmt(d.progNOA)} = Total ${fmt(d.progTotal)}
- Ejecutado:  Secos ${fmt(d.ejecSecos)} + NOA ${fmt(d.ejecNOA)} = Total ${fmt(d.ejecTotal)}
- Desvío: ${gap>=0?'+':''}${fmt(gap)} bultos (${(d.progTotal>0?(d.ejecTotal/d.progTotal*100).toFixed(1):0)}% del objetivo)

DOTACIÓN:
- Programada: ${d.dotProg} operarios
- Real: ${d.dotEjec} operarios (${varDot>=0?'+':''}${varDot} vs programado)

PRODUCTIVIDAD:
- Programada: ${fmtF(d.prodProg)} bultos/operario
- Real: ${fmtF(d.prodEjec)} bultos/operario (${varProd>=0?'+':''}${varProd.toFixed(1)}% vs programado)

OLAS RESTANTES EN EL TURNO: ${olasRest}
${d.obs ? 'OBSERVACIÓN: ' + d.obs : ''}`;
}

// ── Overlay carga IA ─────────────────────────────────────────────
function showAiLoading(title, sub) {
  const prov = activeProvider || 'ia';
  const labels = {claude:'✨ Claude AI',ollama:'🖥 Ollama (Local)',gemini:'🌐 Gemini',azure:'☁ Azure OpenAI'};
  document.getElementById('ai-overlay-title').textContent = title || 'Consultando IA...';
  document.getElementById('ai-overlay-sub').textContent = sub || 'Por favor esperá. El análisis se está procesando.';
  document.getElementById('ai-overlay-prov').textContent = labels[prov] || ('🤖 ' + prov.toUpperCase());
  document.getElementById('ai-overlay-warn').style.display = prov === 'ollama' ? 'block' : 'none';
  document.getElementById('ai-loading-overlay').classList.add('visible');
}
function hideAiLoading() {
  document.getElementById('ai-loading-overlay').classList.remove('visible');
}

// ── IA ────────────────────────────────────────────────────────────
async function runAiAnalysis(context) {
  showAiLoading('Analizando operación...', 'Calculando proyección, historial y alertas del turno.');
  setProviderStatus('Analizando operación...', 'loading');
  document.getElementById('ai-alerts').innerHTML = '<div class="debug-empty">⏳ Consultando IA...</div>';

  const d = currentFormData || {};
  const fechaHoy = new Date().toISOString().split('T')[0];
  // En modo prueba no enviamos turno_id → el backend no guarda la predicción
  let turnoIdParaGuardar = null;
  if (modoReal && d.turnoId) {
    turnoIdParaGuardar = d.turnoId;
  }

  const requestPayload = {
    context,
    turno:    d.turno   || 'Tarde',
    fecha:    fechaHoy,
    ola_num:  d.olaNum  || 1,
    ...(turnoIdParaGuardar ? { turno_id: turnoIdParaGuardar } : {}),
  };
  renderDebugRequest(requestPayload);

  let rawResponse = null;
  try {
    const resp = await fetch('/api/analyze', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(requestPayload),
    });
    rawResponse = await resp.json();
    renderDebugResponse(rawResponse);

    if (rawResponse.error) throw new Error(rawResponse.error);
    aiAlerts = (rawResponse.alerts || []).map(a => ({ ...a, time: nowStr(), source:'ia' }));
    setProviderStatus((rawResponse.provider_used || activeProvider) + (rawResponse.fallback ? ' (fallback)' : '') + ' · ok', 'ok');

    // Mostrar resumen del turno
    const resumen = rawResponse.resumen_turno || '';
    const resWrap = document.getElementById('resumen-turno-wrap');
    if (resumen && resWrap) {
      document.getElementById('resumen-turno-text').textContent = resumen;
      resWrap.style.display = 'flex';
    }

    actualizarSugerencias(d, rawResponse.historico || {});

    // Capa 3: guardar histórico de olas y refinar proyección
    const olasHist = rawResponse.historico?.olas_hist;
    if (olasHist && Object.keys(olasHist).length > 0) {
      historicoOlas = olasHist;
      updateProjectionHistorico(d);
    }

    document.getElementById('ai-chat').style.display = 'block';
  } catch(e) {
    console.warn('[IA] error:', e.message);
    if (!rawResponse) renderDebugResponse({ error: e.message });
    const providerLabel = (activeProvider || 'IA').toUpperCase();
    setProviderStatus(providerLabel + ' · error', 'err');
    aiAlerts = [];
    document.getElementById('ai-alerts').innerHTML = `
      <div class="ai-alert bad" style="text-align:center;padding:28px 24px;">
        <div style="font-size:32px;margin-bottom:12px;">⚠️</div>
        <div class="alert-title" style="margin-bottom:8px;">Error al consultar ${providerLabel}</div>
        <div class="alert-detail" style="margin-bottom:16px;opacity:0.9;">${e.message || 'No se pudo obtener respuesta del proveedor de IA.'}</div>
        <div class="alert-action" style="font-size:12px;">Seleccioná otro proveedor en la barra superior e intentá nuevamente.</div>
      </div>`;
    document.getElementById('resumen-turno-wrap').style.display = 'none';
    document.getElementById('sugerencias-wrap').style.display = 'none';
    hideAiLoading();
    return;
  }
  hideAiLoading();
  renderAiAlerts();
}

function renderDebugRequest(payload) {
  const el = document.getElementById('debug-request');
  el.textContent = JSON.stringify(payload, null, 2);
}

function renderDebugResponse(data) {
  const el = document.getElementById('debug-response');
  el.textContent = JSON.stringify(data, null, 2);
}

function runLocalAlerts() {
  if (!currentFormData) return;
  const d   = currentFormData;
  const gap = d.ejecTotal - d.progTotal;
  const t   = EXCEL_DATA.turnoTotales[d.turno];
  const alerts = [];

  if (gap < -500)
    alerts.push({severity:'bad', title:'Desvío crítico en la ola',
      detail:`${fmt(Math.abs(gap))} bultos bajo el objetivo programado.`,
      action:'Redistribuir dotación. Revisar causa de demora.'});
  else if (gap < -100)
    alerts.push({severity:'warn', title:'Desvío en desarrollo',
      detail:`${fmt(Math.abs(gap))} bultos bajo lo esperado en esta ola.`,
      action:'Monitorear ritmo en la próxima ola.'});
  else
    alerts.push({severity:'ok', title:'Ola dentro del objetivo',
      detail:`Desvío ${gap>=0?'+':''}${fmt(gap)} bultos. Ritmo estable.`,
      action:'Mantener dotación actual.'});

  if (d.dotEjec < d.dotProg)
    alerts.push({severity:'warn', title:'Dotación por debajo del plan',
      detail:`${d.dotEjec} operarios reales vs ${d.dotProg} programados.`,
      action:`Cubrir faltante de ${d.dotProg - d.dotEjec} operarios si es posible.`});

  const varProd = d.prodProg > 0 ? (d.prodEjec - d.prodProg) / d.prodProg * 100 : 0;
  if (varProd < -15)
    alerts.push({severity:'warn', title:'Productividad por debajo del plan',
      detail:`${fmtF(d.prodEjec)} b/op real vs ${fmtF(d.prodProg)} b/op programado (${varProd.toFixed(1)}%).`,
      action:'Revisar causas: ausentismo, pausas no planificadas, congestión.'});

  aiAlerts = alerts.map(a => ({...a, time: nowStr(), source:'local'}));
  renderAiAlerts();
}

function renderAiAlerts() {
  const el = document.getElementById('ai-alerts');
  if (!aiAlerts.length) {
    el.innerHTML = '<div class="debug-empty">Sin alertas activas.</div>';
    return;
  }
  const SEV_LABEL = { bad:'⚠ Crítico', warn:'⚡ Atención', ok:'✓ OK' };
  el.innerHTML = aiAlerts.map(a => `
    <div class="ai-alert ${a.severity}">
      <div class="alert-header">
        <span class="alert-badge ${a.severity}">${SEV_LABEL[a.severity] || a.severity}</span>
        <span class="alert-fuente">${a.source==='ia' ? '✦ IA · '+a.time : 'LOCAL · '+a.time}</span>
      </div>
      <div class="alert-title">${a.title}</div>
      <div class="alert-detail">${a.detail}</div>
      ${a.action ? `<div class="alert-action">${a.action}</div>` : ''}
    </div>`).join('');
}

// ── Tabs principales ─────────────────────────────────────────────
function switchMainTab(tab) {
  ['plan','productividad','plantel'].forEach(t => {
    document.getElementById('mtab-btn-'+t).classList.toggle('active', t === tab);
    document.getElementById('mtab-'+t).classList.toggle('active', t === tab);
  });
  if (tab === 'productividad') {
    cargarRanking();
    poblarSelectoresProductividad();
  }
  if (tab === 'plantel') {
    initPlantelModule();
  }
}

// ── Sub-tabs Productividad ────────────────────────────────────────
function switchProdTab(tab) {
  if (tab === 'sugerencias') {
    const blocked = document.getElementById('stab-sugerencias');
    if (blocked) blocked.classList.add('active');
    ['online','analisis','ranking','comparativa'].forEach(t => {
      document.getElementById('stab-btn-'+t).classList.remove('active');
      document.getElementById('stab-'+t).classList.remove('active');
    });
    document.getElementById('stab-btn-sugerencias').classList.add('active');
    return;
  }
  ['online','analisis','ranking','comparativa','sugerencias'].forEach(t => {
    document.getElementById('stab-btn-'+t).classList.toggle('active', t === tab);
    document.getElementById('stab-'+t).classList.toggle('active', t === tab);
  });
}

// ── Plantel Operativo ─────────────────────────────────────────────
async function loadPlantelTurnos() {
  try {
    const resp = await fetch('/api/plantel/turnos');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'No se pudieron cargar los turnos.');
    plantelTurns = Array.isArray(data.turnos) ? data.turnos : [];
  } catch (err) {
    console.warn('Plantel: usando turnos por fallback.', err);
    plantelTurns = [
      { turno_key: 'tarde', turno_label: 'Tarde', hora_inicio: '14:00', hora_fin: '22:00' },
      { turno_key: 'noche', turno_label: 'Noche', hora_inicio: '22:00', hora_fin: '06:00' },
      { turno_key: 'manana', turno_label: 'Mañana', hora_inicio: '06:00', hora_fin: '14:00' },
    ];
  }

  const sel = document.getElementById('plantel-turno');
  if (!sel) return;
  sel.innerHTML = plantelTurns.map(t => `<option value="${t.turno_key}">${t.turno_label} · ${t.hora_inicio} - ${t.hora_fin}</option>`).join('');
}

function resetPlantelForm() {
  const selected = EXCEL_DATA.olas[selectedOla];
  const turnoSel = document.getElementById('plantel-turno');
  const secosInput = document.getElementById('plantel-bultos-secos');
  const noaInput = document.getElementById('plantel-bultos-noa');
  const nameInput = document.getElementById('plantel-scenario-name');
  if (selected && turnoSel) turnoSel.value = turnoKey(selected.turno);
  if (selected && secosInput) secosInput.value = Math.round(selected.progSecos || 0);
  if (selected && noaInput) noaInput.value = Math.round(selected.progNOA || 0);
  if (nameInput) {
    const tLabel = selected ? turnoLabel(selected.turno) : 'Turno';
    nameInput.value = `Escenario base ${String(tLabel).toLowerCase()}`;
  }
}

function renderPlantelKPIs(data) {
  const wrap = document.getElementById('plantel-kpis');
  if (!wrap || !data || !data.summary) return;
  const summary = data.summary;
  wrap.innerHTML = `
    <div class="plantel-kpi">
      <div class="plantel-kpi-label">Turno</div>
      <div class="plantel-kpi-value">${summary.turno || '—'}</div>
      <div class="plantel-kpi-sub">${summary.rango_horario || '—'} · escenario ${summary.scenario_id || 'nuevo'}</div>
    </div>
    <div class="plantel-kpi">
      <div class="plantel-kpi-label">Elegibles</div>
      <div class="plantel-kpi-value">${summary.operarios_elegibles || 0}</div>
      <div class="plantel-kpi-sub">Solo operarios con historial en el turno evaluado</div>
    </div>
    <div class="plantel-kpi">
      <div class="plantel-kpi-label">Capacidad vs Baseline</div>
      <div class="plantel-kpi-value">${(summary.mejora_capacidad_pct || 0).toFixed(1)}%</div>
      <div class="plantel-kpi-sub">${Math.round(summary.capacidad_total_sugerida || 0).toLocaleString('es-AR')} vs ${Math.round(summary.capacidad_total_baseline || 0).toLocaleString('es-AR')} bultos</div>
    </div>
    <div class="plantel-kpi">
      <div class="plantel-kpi-label">Fuente</div>
      <div class="plantel-kpi-value">${summary.source_name === 'oracle_productiva' ? 'Oracle' : 'Local'}</div>
      <div class="plantel-kpi-sub">${summary.rows_used || 0} movimientos históricos analizados</div>
    </div>
  `;
}

function renderPlantelSummaryTable(data) {
  const wrap = document.getElementById('plantel-summary-table');
  if (!wrap) return;
  const almacenes = Array.isArray(data?.almacenes) ? data.almacenes : [];
  if (!almacenes.length) {
    wrap.className = 'plantel-empty';
    wrap.textContent = 'Todavía no se ejecutó una sugerencia.';
    return;
  }
  wrap.className = 'plantel-table';
  wrap.innerHTML = `
    <div class="plantel-row head">
      <div>Almacén</div>
      <div>Demanda</div>
      <div>Ideal</div>
      <div>Baseline</div>
      <div>Riesgo</div>
    </div>
    ${almacenes.map(item => `
      <div class="plantel-row">
        <div>
          <div class="plantel-cell-main">${item.almacen}</div>
          <div class="plantel-cell-sub">${Math.round(item.lineas_turno || 0).toLocaleString('es-AR')} líneas</div>
        </div>
        <div>
          <div class="plantel-cell-main">${Math.round(item.bultos_turno || 0).toLocaleString('es-AR')} bultos</div>
          <div class="plantel-cell-sub">Cobertura ideal ${Number(item.cobertura_pct || 0).toFixed(1)}%</div>
        </div>
        <div>
          <div class="plantel-cell-main">${item.dotacion_sugerida || 0} op</div>
          <div class="plantel-cell-sub">${Math.round(item.capacidad_equipo || 0).toLocaleString('es-AR')} bultos · fin ${item.hora_fin_estimada || '—'}</div>
        </div>
        <div>
          <div class="plantel-cell-main">${item.baseline_dotacion || 0} op</div>
          <div class="plantel-cell-sub">${Math.round(item.baseline_capacidad || 0).toLocaleString('es-AR')} bultos · fin ${item.baseline_hora_fin_estimada || '—'}</div>
        </div>
        <div>
          <span class="plantel-risk ${item.riesgo || 'medio'}">${item.riesgo || 'medio'}</span>
          <div class="plantel-cell-sub">Baseline ${Number(item.baseline_cobertura_pct || 0).toFixed(1)}%</div>
        </div>
      </div>
    `).join('')}
  `;
}

function renderPlantelExplanations(data) {
  const wrap = document.getElementById('plantel-explanations');
  if (!wrap) return;
  const exp = data?.explanations || {};
  const almacenes = Array.isArray(exp.almacenes) ? exp.almacenes : [];
  const whatIf = Array.isArray(exp.what_if) ? exp.what_if : [];
  wrap.className = 'plantel-explain';
  wrap.innerHTML = `
    <div class="plantel-explain-item"><strong>Lectura general</strong><br>${exp.summary || 'Sin explicación disponible.'}</div>
    ${almacenes.map(item => `<div class="plantel-explain-item"><strong>${item.almacen}</strong><br>${item.explicacion}</div>`).join('')}
    <div class="plantel-explain-item"><strong>What If sugeridos</strong><br>${whatIf.map(item => `• ${item}`).join('<br>') || '• Ajustar demanda y recalcular.'}</div>
  `;
}

function renderPlantelAssignments(data) {
  const wrap = document.getElementById('plantel-assignments');
  if (!wrap) return;
  const assignments = Array.isArray(data?.suggested_assignments) ? data.suggested_assignments : [];
  if (!assignments.length) {
    wrap.className = 'plantel-empty';
    wrap.textContent = 'Todavía no hay asignación calculada.';
    return;
  }
  wrap.className = 'plantel-assignment-list';
  wrap.innerHTML = assignments.map(item => `
    <div class="plantel-assignment">
      <div class="plantel-assignment-top">
        <div>
          <div class="plantel-operator">${item.operario_nombre || item.operario_id}</div>
          <div class="plantel-cell-sub">${item.operario_id}</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;">
          <span class="plantel-badge">${item.almacen}</span>
          ${Number(item.penalizacion || 0) > 0 ? `<span class="plantel-penalty">Penalidad ${Number(item.penalizacion).toFixed(2)}</span>` : ''}
        </div>
      </div>
      <div class="plantel-cell-sub">Score ${Number(item.score || 0).toFixed(1)} · capacidad estimada ${Math.round(item.capacidad_estimada || 0).toLocaleString('es-AR')} bultos turno</div>
      <div class="plantel-cell-sub">${item.explicacion_ia || item.motivo_principal || 'Sin detalle'}</div>
    </div>
  `).join('');
}

function renderPlantelScenarios(items) {
  const wrap = document.getElementById('plantel-scenarios');
  if (!wrap) return;
  const escenarios = Array.isArray(items) ? items : [];
  if (!escenarios.length) {
    wrap.className = 'plantel-empty';
    wrap.textContent = 'Todavía no hay escenarios guardados.';
    return;
  }
  wrap.className = 'plantel-scenarios';
  wrap.innerHTML = escenarios.map(item => `
    <div class="plantel-scenario-card">
      <strong>${item.nombre || 'Escenario'}</strong>
      <div class="plantel-cell-sub">${item.turno_label || '—'} · ${item.hora_inicio || '—'} - ${item.hora_fin || '—'}</div>
      <div class="plantel-cell-sub">Elegibles: ${item.summary?.operarios_elegibles || 0}</div>
      <div class="plantel-cell-sub">Mejora: ${Number(item.summary?.mejora_capacidad_pct || 0).toFixed(1)}%</div>
      <div class="plantel-cell-sub">${item.created_at || ''}</div>
    </div>
  `).join('');
}

async function loadPlantelScenarios() {
  try {
    const resp = await fetch('/api/plantel/escenarios');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'No se pudieron cargar los escenarios.');
    renderPlantelScenarios(data.escenarios || []);
  } catch (err) {
    console.warn('Plantel: no se pudieron cargar escenarios.', err);
  }
}

function renderPlantelResult(data) {
  plantelLastResult = data;
  renderPlantelKPIs(data);
  renderPlantelSummaryTable(data);
  renderPlantelExplanations(data);
  renderPlantelAssignments(data);
}

async function runPlantelScenario() {
  if (plantelLoading) return;
  const turnoSel = document.getElementById('plantel-turno');
  const status = document.getElementById('plantel-status');
  const runBtn = document.getElementById('plantel-run-btn');
  if (!turnoSel || !status || !runBtn) return;

  const payload = {
    turno: turnoSel.value,
    scenario_name: document.getElementById('plantel-scenario-name')?.value || '',
    almacenes: [
      { almacen: 'SECTOR SECOS', bultos_turno: Number(document.getElementById('plantel-bultos-secos')?.value || 0), lineas_turno: 0 },
      { almacen: 'VARIOS NO ALIMENTOS', bultos_turno: Number(document.getElementById('plantel-bultos-noa')?.value || 0), lineas_turno: 0 },
    ],
  };

  plantelLoading = true;
  runBtn.disabled = true;
  status.textContent = 'Consultando histórico del turno y generando sugerencia de plantel operativo...';
  try {
    const resp = await fetch('/api/plantel/sugerencias', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'No se pudo calcular la sugerencia de plantel.');
    renderPlantelResult(data);
    await loadPlantelScenarios();
    status.textContent = `Escenario ${data.summary?.scenario_id || 'nuevo'} generado. ${data.summary?.operarios_elegibles || 0} operarios elegibles en turno ${data.summary?.turno || '—'}.`;
  } catch (err) {
    status.textContent = err.message || 'Se produjo un error al calcular el escenario.';
    const summaryEl = document.getElementById('plantel-summary-table');
    if (summaryEl) {
      summaryEl.className = 'plantel-empty';
      summaryEl.textContent = err.message || 'Se produjo un error.';
    }
  } finally {
    plantelLoading = false;
    runBtn.disabled = false;
  }
}

async function initPlantelModule() {
  if (!plantelTurns.length) {
    await loadPlantelTurnos();
    resetPlantelForm();
  }
  await loadPlantelScenarios();
}

function toInputLocalValue(date) {
  const pad = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function inputLocalToBackend(value) {
  if (!value) return '';
  return value.replace('T', ' ') + ':00';
}

function initAnalisisProductividadDefaults() {
  const desde = document.getElementById('analisis-fecha-desde');
  const hasta = document.getElementById('analisis-fecha-hasta');
  if (!desde || !hasta) return;
  if (desde.value && hasta.value) return;

  const now = new Date();
  const start = new Date(now);
  start.setDate(start.getDate() - 1);
  start.setHours(14, 0, 0, 0);

  const end = new Date(now);
  end.setHours(14, 0, 0, 0);

  desde.value = toInputLocalValue(start);
  hasta.value = toInputLocalValue(end);
}

function limpiarAnalisisProductividad() {
  analisisProductividadCache = null;
  analisisProductividadLoading = false;
  analisisProductividadIaLoading = false;
  analisisProductividadIaCache = null;
  const exportBtn = document.getElementById('analisis-export-btn');
  const runBtn = document.getElementById('analisis-run-btn');
  if (exportBtn) exportBtn.disabled = true;
  if (runBtn) runBtn.disabled = false;
  document.getElementById('analisis-results').innerHTML =
    '<div class="analisis-empty">Todavía no se ejecutó el análisis de productividad.</div>';
  document.getElementById('analisis-status').textContent =
    'Seleccioná un rango y ejecutá el análisis a demanda.';
  initAnalisisProductividadDefaults();
}

function renderCollapsibleSection(title, innerHtml, opts = {}) {
  const collapsed = opts.collapsed ? ' collapsed' : '';
  const label = opts.collapsed ? 'Expandir' : 'Contraer';
  return `
    <div class="analisis-section analisis-collapse${collapsed}">
      <div class="analisis-collapse-header" onclick="toggleAnalisisSection(this)">
        <div class="analisis-collapse-title">${title}</div>
        <div class="analisis-collapse-toggle">
          <span class="analisis-collapse-toggle-text">${label}</span>
          <span class="analisis-collapse-toggle-icon">${opts.collapsed ? '▼' : '▲'}</span>
        </div>
      </div>
      <div class="analisis-collapse-body">
        ${innerHtml}
      </div>
    </div>
  `;
}

function toggleAnalisisSection(el) {
  const section = el.closest('.analisis-collapse');
  if (!section) return;
  const collapsed = section.classList.toggle('collapsed');
  const txt = section.querySelector('.analisis-collapse-toggle-text');
  const icon = section.querySelector('.analisis-collapse-toggle-icon');
  if (txt) txt.textContent = collapsed ? 'Expandir' : 'Contraer';
  if (icon) icon.textContent = collapsed ? '▼' : '▲';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function exportarAnalisisPDF() {
  if (!analisisProductividadCache) return;

  const data = analisisProductividadCache || {};
  const iaData = analisisProductividadIaCache || {};
  const rango = data.rango || {};
  const resumen = data.resumen || {};
  const alertas = data.alertas_internas || [];
  const historico = data.historico || {};
  const ia = iaData.analisis || null;
  const iaProvider = iaData.provider ? iaData.provider.toUpperCase() : '';
  const iaModel = iaData.model_used || '';
  const rangoTexto = `${rango.fecha_desde || 'Sin dato'} a ${rango.fecha_hasta || 'Sin dato'}`;
  const lecturaEjecutiva = ia && ia.resumen
    ? ia.resumen
    : 'La lectura ejecutiva IA no estaba disponible al momento de exportar este informe.';
  const hallazgos = ia && Array.isArray(ia.hallazgos) && ia.hallazgos.length
    ? ia.hallazgos
    : ['Sin hallazgos IA disponibles.'];
  const recomendaciones = ia && Array.isArray(ia.recomendaciones) && ia.recomendaciones.length
    ? ia.recomendaciones
    : ['Sin acciones IA disponibles.'];
  const analisisInternoItems = [
    `Movimientos relevados: ${(resumen.movimientos_total || 0).toLocaleString('es-AR')}`,
    `Operarios activos: ${(resumen.operarios_total || 0).toLocaleString('es-AR')}`,
    `Zonas analizadas: ${(resumen.zonas_total || 0).toLocaleString('es-AR')}`,
    `Cantidad total procesada: ${(resumen.cantidad_total || 0).toLocaleString('es-AR')}`,
    `Productividad promedio: ${(resumen.productividad_promedio || 0).toLocaleString('es-AR')} unidades/h`,
    ...(alertas.length ? alertas : ['Sin alertas internas destacadas para este rango.']),
  ];

  if (historico.muestras_operario || historico.muestras_zona) {
    analisisInternoItems.push(
      `Baseline historico disponible: ${historico.muestras_operario || 0} operarios y ${historico.muestras_zona || 0} zonas con comparativa.`
    );
  }

  const win = window.open('', '_blank', 'width=1024,height=900');
  if (!win) return;

  win.document.write(`
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8">
      <title>Analisis Ejecutivo de Productividad</title>
      <style>
        @page { size: A4; margin: 16mm; }
        html, body { margin: 0; padding: 0; background: #ffffff; color: #111827; font-family: Arial, sans-serif; }
        .page { max-width: 760px; margin: 0 auto; }
        h1 { font-size: 24px; margin: 0 0 8px; color: #0f172a; }
        .range { font-size: 13px; color: #475569; margin-bottom: 16px; }
        .meta { font-size: 12px; color: #475569; margin-bottom: 18px; }
        .section { margin-bottom: 20px; page-break-inside: avoid; }
        .section-title { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: #0f172a; margin: 0 0 10px; padding-bottom: 6px; border-bottom: 1px solid #cbd5e1; }
        .paragraph { font-size: 13px; line-height: 1.6; color: #1f2937; }
        ul { margin: 8px 0 0 18px; padding: 0; }
        li { font-size: 13px; line-height: 1.6; color: #1f2937; margin-bottom: 6px; }
      </style>
    </head>
    <body>
      <div class="page">
        <h1>Analisis Ejecutivo de Productividad</h1>
        <div class="range">Rango consultado: ${escapeHtml(rangoTexto)}</div>
        ${(iaProvider || iaModel) ? `<div class="meta">IA utilizada: ${escapeHtml(iaProvider)}${iaModel ? ` · ${escapeHtml(iaModel)}` : ''}</div>` : ''}

        <div class="section">
          <div class="section-title">Lectura Ejecutiva del Rendimiento Operativo</div>
          <div class="paragraph">${escapeHtml(lecturaEjecutiva)}</div>
        </div>

        <div class="section">
          <div class="section-title">Hallazgos Clave</div>
          <ul>
            ${hallazgos.map(item => `<li>${escapeHtml(item)}</li>`).join('')}
          </ul>
        </div>

        <div class="section">
          <div class="section-title">Acciones Sugeridas</div>
          <ul>
            ${recomendaciones.map(item => `<li>${escapeHtml(item)}</li>`).join('')}
          </ul>
        </div>

        <div class="section">
          <div class="section-title">Resultado del Analisis Interno</div>
          <ul>
            ${analisisInternoItems.map(item => `<li>${escapeHtml(item)}</li>`).join('')}
          </ul>
        </div>
      </div>
    </body>
    </html>
  `);
  win.document.close();
  win.onload = () => {
    win.focus();
    setTimeout(() => win.print(), 250);
  };
}

function renderAnalisisProductividad(data, aiData) {
  const results = document.getElementById('analisis-results');
  const resumen = data.resumen || {};
  const alertas = data.alertas_internas || [];
  const top = data.top_operarios || [];
  const bottom = data.bottom_operarios || [];
  const zonas = data.zonas || [];
  const ia = aiData && aiData.analisis ? aiData.analisis : null;
  const iaProvider = aiData && aiData.provider ? aiData.provider.toUpperCase() : 'IA';
  const iaModel = aiData && aiData.model_used ? aiData.model_used : 'modelo no informado';
  const exportBtn = document.getElementById('analisis-export-btn');
  const runBtn = document.getElementById('analisis-run-btn');
  if (exportBtn) exportBtn.disabled = false;
  if (runBtn) runBtn.disabled = analisisProductividadLoading;

  const renderRows = arr => {
    if (!arr.length) return '<div class="analisis-empty">Sin operarios para mostrar en este rango.</div>';
    return `
      <div class="analisis-table">
        <div class="analisis-row head">
          <div>Operario</div>
          <div>Zonas</div>
          <div style="text-align:right">Prod. general</div>
          <div style="text-align:right">Cantidad</div>
        </div>
        ${arr.map(op => `
          <div class="analisis-row ${op.estado || ''}">
            <div class="analisis-op">${op.operario}</div>
            <div class="analisis-zonas">${(op.zonas || []).slice(0,3).map(z => `${z.zona}: ${z.productividad}/h`).join(' · ') || 'Sin zonas'}</div>
            <div class="analisis-metric">${(op.productividad_general || 0).toLocaleString('es-AR')} /h</div>
            <div class="analisis-metric">${(op.cantidad_total || 0).toLocaleString('es-AR')}</div>
          </div>
        `).join('')}
      </div>`;
  };

  const renderZonaRows = () => {
    if (!zonas.length) return '<div class="analisis-empty">Sin productividad por zona para este rango.</div>';
    return `
      <div class="analisis-table">
        <div class="analisis-row head">
          <div>Zona</div>
          <div>Resumen</div>
          <div style="text-align:right">Productividad</div>
          <div style="text-align:right">Cantidad</div>
        </div>
        ${zonas.map(z => `
          <div class="analisis-row">
            <div class="analisis-op">${z.zona}</div>
            <div class="analisis-zonas">${z.operarios} operarios · ${z.movimientos} movimientos · ${z.horas_activas || 0} h activas</div>
            <div class="analisis-metric">${(z.productividad || 0).toLocaleString('es-AR')} /h</div>
            <div class="analisis-metric">${(z.cantidad_total || 0).toLocaleString('es-AR')}</div>
          </div>
        `).join('')}
      </div>`;
  };

  results.innerHTML = `
    <div class="analisis-shell">
    <div class="analisis-section" style="padding:0;background:transparent;border:none;box-shadow:none;margin-bottom:18px;">
      <div class="analisis-ia-hero">
        <div class="analisis-ia-topline">
          <span class="analisis-ia-badge">Analisis IA prioritario</span>
          <span class="analisis-ia-provider">Motor: <strong>${iaProvider}</strong> · ${iaModel}</span>
        </div>
        <div class="analisis-ia-title">Lectura ejecutiva del rendimiento operativo</div>
        ${ia ? `
          <div class="analisis-ia-summary">${ia.resumen || 'Sin resumen generado.'}</div>
          <div class="analisis-ia-columns">
            <div class="analisis-ia-panel">
              <div class="analisis-ia-panel-title">Hallazgos clave</div>
              <div class="analisis-ia-list">
                ${(ia.hallazgos || []).map(item => `<div class="analisis-ia-list-item">${item}</div>`).join('')}
              </div>
            </div>
            <div class="analisis-ia-panel">
              <div class="analisis-ia-panel-title">Acciones sugeridas</div>
              <div class="analisis-ia-list">
                ${(ia.recomendaciones || []).map(item => `<div class="analisis-ia-list-item">${item}</div>`).join('')}
              </div>
            </div>
          </div>
        ` : `
          <div class="analisis-ia-summary">Todavía no se pudo generar la lectura IA para este rango. El análisis interno igualmente ya está disponible debajo.</div>
        `}
      </div>
    </div>

    <div class="analisis-grid">
      <div class="analisis-kpi">
        <div class="analisis-kpi-label">Operarios</div>
        <div class="analisis-kpi-value">${(resumen.operarios_total || 0).toLocaleString('es-AR')}</div>
        <div class="analisis-kpi-sub">Activos en la ventana</div>
      </div>
      <div class="analisis-kpi">
        <div class="analisis-kpi-label">Movimientos</div>
        <div class="analisis-kpi-value">${(resumen.movimientos_total || 0).toLocaleString('es-AR')}</div>
        <div class="analisis-kpi-sub">Registros productivos consultados</div>
      </div>
      <div class="analisis-kpi">
        <div class="analisis-kpi-label">Cantidad total</div>
        <div class="analisis-kpi-value">${(resumen.cantidad_total || 0).toLocaleString('es-AR')}</div>
        <div class="analisis-kpi-sub">Unidades procesadas</div>
      </div>
      <div class="analisis-kpi">
        <div class="analisis-kpi-label">Prod. promedio</div>
        <div class="analisis-kpi-value">${(resumen.productividad_promedio || 0).toLocaleString('es-AR')}</div>
        <div class="analisis-kpi-sub">Unidades por hora</div>
      </div>
    </div>

    ${renderCollapsibleSection('Analisis interno', `
      <div class="analisis-summary">
        Ventana analizada: <strong>${data.rango.fecha_desde}</strong> a <strong>${data.rango.fecha_hasta}</strong>.
        Se relevaron <strong>${(resumen.movimientos_total || 0).toLocaleString('es-AR')}</strong> movimientos,
        con <strong>${(resumen.operarios_total || 0).toLocaleString('es-AR')}</strong> operarios y
        <strong>${(resumen.zonas_total || 0).toLocaleString('es-AR')}</strong> zonas.
      </div>
    `)}

    ${renderCollapsibleSection('Alertas internas', `
      <div class="analisis-list">
        ${(alertas.length ? alertas : ['Sin alertas internas destacadas para este rango.']).map(item => `
          <div class="analisis-item">${item}</div>
        `).join('')}
      </div>
    `)}

    ${renderCollapsibleSection('Top productividad por operario', renderRows(top), { collapsed: true })}

    ${renderCollapsibleSection('Menor productividad por operario', renderRows(bottom), { collapsed: true })}

    ${renderCollapsibleSection('Productividad por zona', renderZonaRows(), { collapsed: true })}
    </div>
  `;
}

function renderAnalisisProductividadV2(data, aiData) {
  const results = document.getElementById('analisis-results');
  const resumen = data.resumen || {};
  const alertas = data.alertas_internas || [];
  const top = data.top_operarios || [];
  const bottom = data.bottom_operarios || [];
  const zonas = data.zonas || [];
  const historico = data.historico || {};
  const ia = aiData && aiData.analisis ? aiData.analisis : null;
  const iaProvider = aiData && aiData.provider ? aiData.provider.toUpperCase() : 'IA';
  const iaModel = aiData && aiData.model_used ? aiData.model_used : 'modelo no informado';
  const iaCacheHit = !!(aiData && aiData.cache && aiData.cache.ia_cache_hit);
  const internoCacheHit = !!(data.cache && data.cache.interno_cache_hit);
  const showInlineIaLoading = analisisProductividadIaLoading && !ia;
  const iaLiveProvider = (activeProvider || 'claude').toUpperCase();
  const exportBtn = document.getElementById('analisis-export-btn');
  const runBtn = document.getElementById('analisis-run-btn');
  if (exportBtn) exportBtn.disabled = false;
  if (runBtn) runBtn.disabled = analisisProductividadLoading;

  const renderRows = arr => {
    if (!arr.length) return '<div class="analisis-empty">Sin operarios para mostrar en este rango.</div>';
    return `
      <div class="analisis-table">
        <div class="analisis-row head">
          <div>Operario</div>
          <div>Zonas</div>
          <div style="text-align:right">Prod. general</div>
          <div style="text-align:right">Cantidad</div>
        </div>
        ${arr.map(op => `
          <div class="analisis-row ${op.estado || ''}">
            <div class="analisis-op">${op.operario}</div>
            <div class="analisis-zonas">
              ${(op.zonas || []).slice(0,3).map(z => `${z.zona}: ${z.productividad}/h`).join(' · ') || 'Sin zonas'}
              ${op.historico ? `<div style="margin-top:6px;color:${op.historico.delta_vs_promedio_pct >= 0 ? 'var(--green)' : '#fca5a5'};font-size:11px;">Hist.: ${(op.historico.promedio_productividad || 0).toLocaleString('es-AR')} /h · ${op.historico.delta_vs_promedio_pct >= 0 ? '+' : ''}${(op.historico.delta_vs_promedio_pct || 0).toLocaleString('es-AR')}%</div>` : ''}
            </div>
            <div class="analisis-metric">${(op.productividad_general || 0).toLocaleString('es-AR')} /h</div>
            <div class="analisis-metric">${(op.cantidad_total || 0).toLocaleString('es-AR')}</div>
          </div>
        `).join('')}
      </div>`;
  };

  const renderZonaRows = () => {
    if (!zonas.length) return '<div class="analisis-empty">Sin productividad por zona para este rango.</div>';
    return `
      <div class="analisis-table">
        <div class="analisis-row head">
          <div>Zona</div>
          <div>Resumen</div>
          <div style="text-align:right">Productividad</div>
          <div style="text-align:right">Cantidad</div>
        </div>
        ${zonas.map(z => `
          <div class="analisis-row">
            <div class="analisis-op">${z.zona}</div>
            <div class="analisis-zonas">
              ${z.operarios} operarios · ${z.movimientos} movimientos · ${z.horas_activas || 0} h activas
              ${z.historico ? `<div style="margin-top:6px;color:${z.historico.delta_vs_promedio_pct >= 0 ? 'var(--green)' : '#fca5a5'};font-size:11px;">Hist.: ${(z.historico.promedio_productividad || 0).toLocaleString('es-AR')} /h · ${z.historico.delta_vs_promedio_pct >= 0 ? '+' : ''}${(z.historico.delta_vs_promedio_pct || 0).toLocaleString('es-AR')}%</div>` : ''}
            </div>
            <div class="analisis-metric">${(z.productividad || 0).toLocaleString('es-AR')} /h</div>
            <div class="analisis-metric">${(z.cantidad_total || 0).toLocaleString('es-AR')}</div>
          </div>
        `).join('')}
      </div>`;
  };

  const renderHistoricoOperarios = () => {
    const bajos = historico.operarios_mas_bajos_vs_historico || [];
    const altos = historico.operarios_mas_altos_vs_historico || [];
    if (!bajos.length && !altos.length) return '<div class="analisis-empty">Todavia no hay baseline historico suficiente para comparar operarios.</div>';
    return `
      <div class="analisis-table">
        <div class="analisis-row head">
          <div>Operario</div>
          <div>Comparativa</div>
          <div style="text-align:right">Actual</div>
          <div style="text-align:right">Hist.</div>
        </div>
        ${[...bajos, ...altos.filter(item => !bajos.some(low => low.operario === item.operario))].slice(0,10).map(item => `
          <div class="analisis-row ${item.delta_pct < 0 ? 'bad' : 'ok'}">
            <div class="analisis-op">${item.operario}</div>
            <div class="analisis-zonas">${item.ventanas} ventanas historicas · ${item.delta_pct >= 0 ? '+' : ''}${item.delta_pct.toLocaleString('es-AR')}%</div>
            <div class="analisis-metric">${(item.actual || 0).toLocaleString('es-AR')} /h</div>
            <div class="analisis-metric">${(item.promedio_historico || 0).toLocaleString('es-AR')} /h</div>
          </div>
        `).join('')}
      </div>`;
  };

  const renderHistoricoZonas = () => {
    const bajas = historico.zonas_mas_bajas_vs_historico || [];
    const altas = historico.zonas_mas_altas_vs_historico || [];
    if (!bajas.length && !altas.length) return '<div class="analisis-empty">Todavia no hay baseline historico suficiente para comparar zonas.</div>';
    return `
      <div class="analisis-table">
        <div class="analisis-row head">
          <div>Zona</div>
          <div>Comparativa</div>
          <div style="text-align:right">Actual</div>
          <div style="text-align:right">Hist.</div>
        </div>
        ${[...bajas, ...altas.filter(item => !bajas.some(low => low.zona === item.zona))].slice(0,10).map(item => `
          <div class="analisis-row ${item.delta_pct < 0 ? 'bad' : 'ok'}">
            <div class="analisis-op">${item.zona}</div>
            <div class="analisis-zonas">${item.ventanas} ventanas historicas · ${item.delta_pct >= 0 ? '+' : ''}${item.delta_pct.toLocaleString('es-AR')}%</div>
            <div class="analisis-metric">${(item.actual || 0).toLocaleString('es-AR')} /h</div>
            <div class="analisis-metric">${(item.promedio_historico || 0).toLocaleString('es-AR')} /h</div>
          </div>
        `).join('')}
      </div>`;
  };

  results.innerHTML = `
    <div class="analisis-shell">
    <div class="analisis-section" style="padding:0;background:transparent;border:none;box-shadow:none;margin-bottom:18px;">
      <div class="analisis-ia-hero">
        <div class="analisis-ia-topline">
          <span class="analisis-ia-badge">Analisis IA prioritario</span>
          <span class="analisis-ia-provider">Motor: <strong>${iaProvider}</strong> · ${iaModel}${iaCacheHit ? ' · caché' : ''}</span>
          ${showInlineIaLoading ? '<span class="analisis-ia-live">IA en ejecucion</span>' : ''}
        </div>
        <div class="analisis-ia-title">Lectura ejecutiva del rendimiento operativo</div>
        ${ia ? `
          <div class="analisis-ia-summary">${ia.resumen || 'Sin resumen generado.'}</div>
          <div class="analisis-ia-columns">
            <div class="analisis-ia-panel">
              <div class="analisis-ia-panel-title">Hallazgos clave</div>
              <div class="analisis-ia-list">
                ${(ia.hallazgos || []).map(item => `<div class="analisis-ia-list-item">${item}</div>`).join('')}
              </div>
            </div>
            <div class="analisis-ia-panel">
              <div class="analisis-ia-panel-title">Acciones sugeridas</div>
              <div class="analisis-ia-list">
                ${(ia.recomendaciones || []).map(item => `<div class="analisis-ia-list-item">${item}</div>`).join('')}
              </div>
            </div>
          </div>
        ` : `
          <div class="analisis-ia-summary">${showInlineIaLoading ? 'La IA esta ejecutando el analisis de productividad sobre el resumen interno y el contexto historico. Ya podes revisar los calculos locales mientras se arma la lectura ejecutiva.' : 'Todavia no se pudo generar la lectura IA para este rango. El analisis interno igualmente ya esta disponible debajo.'}</div>
          ${showInlineIaLoading ? `
            <div class="analisis-ia-progress">
              <div class="analisis-ia-progress-card">
                <div class="analisis-ia-progress-title">Proceso en curso</div>
                <div class="analisis-ia-progress-text">Se esta evaluando productividad general, comparativas por zona y desvio historico para priorizar hallazgos y acciones operativas.</div>
              </div>
              <div class="analisis-ia-progress-meta">
                <span class="analisis-ia-progress-chip">Proveedor: <strong>${iaLiveProvider}</strong></span>
                <span class="analisis-ia-progress-chip">Fuente: resumen interno + baseline historico</span>
                <span class="analisis-ia-progress-chip">Modo: lectura ejecutiva no bloqueante</span>
              </div>
            </div>
          ` : ''}
        `}
      </div>
    </div>

    <div class="analisis-grid">
      <div class="analisis-kpi">
        <div class="analisis-kpi-label">Operarios</div>
        <div class="analisis-kpi-value">${(resumen.operarios_total || 0).toLocaleString('es-AR')}</div>
        <div class="analisis-kpi-sub">Activos en la ventana</div>
      </div>
      <div class="analisis-kpi">
        <div class="analisis-kpi-label">Movimientos</div>
        <div class="analisis-kpi-value">${(resumen.movimientos_total || 0).toLocaleString('es-AR')}</div>
        <div class="analisis-kpi-sub">Registros productivos consultados</div>
      </div>
      <div class="analisis-kpi">
        <div class="analisis-kpi-label">Cantidad total</div>
        <div class="analisis-kpi-value">${(resumen.cantidad_total || 0).toLocaleString('es-AR')}</div>
        <div class="analisis-kpi-sub">Unidades procesadas</div>
      </div>
      <div class="analisis-kpi">
        <div class="analisis-kpi-label">Prod. promedio</div>
        <div class="analisis-kpi-value">${(resumen.productividad_promedio || 0).toLocaleString('es-AR')}</div>
        <div class="analisis-kpi-sub">Unidades por hora</div>
      </div>
    </div>

    ${renderCollapsibleSection('Analisis interno', `
      <div class="analisis-summary">
        Ventana analizada: <strong>${data.rango.fecha_desde}</strong> a <strong>${data.rango.fecha_hasta}</strong>.
        Se relevaron <strong>${(resumen.movimientos_total || 0).toLocaleString('es-AR')}</strong> movimientos,
        con <strong>${(resumen.operarios_total || 0).toLocaleString('es-AR')}</strong> operarios y
        <strong>${(resumen.zonas_total || 0).toLocaleString('es-AR')}</strong> zonas.
        ${internoCacheHit ? '<br><span style="color:var(--accent2);font-size:11px;">Resumen interno recuperado desde caché local.</span>' : ''}
      </div>
    `)}

    ${renderCollapsibleSection('Alertas internas', `
      <div class="analisis-list">
        ${(alertas.length ? alertas : ['Sin alertas internas destacadas para este rango.']).map(item => `
          <div class="analisis-item">${item}</div>
        `).join('')}
      </div>
    `)}

    ${renderCollapsibleSection('Top productividad por operario', renderRows(top), { collapsed: true })}

    ${renderCollapsibleSection('Menor productividad por operario', renderRows(bottom), { collapsed: true })}

    ${renderCollapsibleSection('Productividad por zona', renderZonaRows(), { collapsed: true })}

    ${renderCollapsibleSection('Comparativa historica por operario', renderHistoricoOperarios(), { collapsed: true })}

    ${renderCollapsibleSection('Comparativa historica por zona', renderHistoricoZonas(), { collapsed: true })}
    </div>
  `;
}

async function cargarAnalisisProductividad() {
  if (analisisProductividadLoading) return;
  initAnalisisProductividadDefaults();
  const desdeVal = document.getElementById('analisis-fecha-desde').value;
  const hastaVal = document.getElementById('analisis-fecha-hasta').value;
  const status = document.getElementById('analisis-status');
  const results = document.getElementById('analisis-results');
  const runBtn = document.getElementById('analisis-run-btn');
  const exportBtn = document.getElementById('analisis-export-btn');

  if (!desdeVal || !hastaVal) {
    status.textContent = 'Completá fecha y hora desde/hasta.';
    return;
  }

  analisisProductividadLoading = true;
  analisisProductividadIaCache = null;
  if (runBtn) runBtn.disabled = true;
  if (exportBtn) exportBtn.disabled = true;
  const fecha_desde = inputLocalToBackend(desdeVal);
  const fecha_hasta = inputLocalToBackend(hastaVal);
  status.textContent = 'Consultando BD productiva y armando analisis interno...';
  results.innerHTML = '<div class="analisis-empty">Procesando consulta productiva y resumen interno...</div>';

  try {
    const internoResp = await fetch(`/api/productividad/analisis/interno?fecha_desde=${encodeURIComponent(fecha_desde)}&fecha_hasta=${encodeURIComponent(fecha_hasta)}`);
    const interno = await internoResp.json();
    if (!internoResp.ok) throw new Error(interno.detail || 'No se pudo generar el analisis interno.');

    analisisProductividadCache = interno;
    analisisProductividadIaLoading = true;
    status.textContent = `Analisis interno listo. Ejecutando lectura IA en segundo plano con ${String(activeProvider || 'claude').toUpperCase()}.`;
    renderAnalisisProductividadV2(interno, null);

    const iaResp = await fetch('/api/productividad/analisis/ia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resumen_interno: interno }),
    });
    const ia = await iaResp.json();
    if (!iaResp.ok) throw new Error(ia.detail || 'No se pudo generar el analisis IA.');

    analisisProductividadIaLoading = false;
    status.textContent = `Analisis ${interno.cache?.interno_cache_hit ? 'interno recuperado de caché' : 'interno generado'} e IA ${ia.cache?.ia_cache_hit ? 'recuperada de caché' : 'generada'} correctamente.`;
    analisisProductividadIaCache = ia;
    renderAnalisisProductividadV2(interno, ia);
  } catch (e) {
    analisisProductividadIaLoading = false;
    analisisProductividadIaCache = null;
    status.textContent = 'Se produjo un error al generar el analisis.';
    results.innerHTML = `<div class="analisis-empty" style="color:var(--red);border-color:#fecaca;">${e.message}</div>`;
  } finally {
    analisisProductividadIaLoading = false;
    analisisProductividadLoading = false;
    if (runBtn) runBtn.disabled = false;
  }
}

// ── Ranking ───────────────────────────────────────────────────────
async function cargarRanking() {
  const container = document.getElementById('ranking-container');
  if (!container) return;
  if (container.dataset.loaded === '1') return;

  container.innerHTML = '<div style="padding:30px;text-align:center;color:var(--muted);font-size:13px;"><div style="width:28px;height:28px;border:3px solid var(--border);border-top-color:var(--green);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px;"></div>Cargando ranking...</div>';

  try {
    const data = await fetch('/api/operarios/ranking').then(r => r.json());
    if (!data.operarios || data.operarios.length === 0) {
      container.innerHTML = '<div class="recom-empty">Sin datos de operarios para hoy.</div>';
      return;
    }

    const bajoEstandar = data.operarios.filter(o => o.bajo_estandar).length;
    let html = `
      <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;">
        <div style="padding:10px 16px;background:var(--ok-light);border:1px solid var(--ok);border-radius:8px;font-size:13px;color:var(--ok);font-weight:600;">
          👷 ${data.total} operarios activos
        </div>
        ${bajoEstandar > 0 ? `<div style="padding:10px 16px;background:#fef2f2;border:1px solid var(--red);border-radius:8px;font-size:13px;color:var(--red);font-weight:600;">⚠️ ${bajoEstandar} bajo estándar</div>` : ''}
      </div>
      <div class="ranking-header">
        <span>#</span><span>Operario</span>
        <span style="text-align:right">Picks</span>
        <span class="rh-vel" style="text-align:right">Vel. prom.</span>
        <span style="text-align:right">Tasa error</span>
        <span style="text-align:right">Estado</span>
      </div>`;

    data.operarios.forEach((op, idx) => {
      const pos = idx + 1;
      const velColor = op.vel_promedio > 40 ? 'var(--red)' : op.vel_promedio > 32 ? 'var(--amber)' : 'var(--ok)';
      const errColor = op.tasa_error > 5 ? 'var(--red)' : op.tasa_error > 3 ? 'var(--amber)' : 'var(--ok)';
      html += `
        <div class="ranking-row ${op.estado}">
          <span class="ranking-pos ${pos <= 3 ? 'top3' : ''}">${pos <= 3 ? ['🥇','🥈','🥉'][pos-1] : pos}</span>
          <span class="ranking-id">${op.operario_id}</span>
          <span class="ranking-val">${op.picks.toLocaleString()}</span>
          <span class="ranking-val ranking-vel" style="color:${velColor}">${op.vel_promedio}s</span>
          <span class="ranking-val" style="color:${errColor}">${op.tasa_error}%</span>
          <span class="ranking-badge ${op.estado}">${op.estado === 'ok' ? '✓ OK' : op.estado === 'warn' ? '⚡ Atención' : '⚠ Crítico'}</span>
        </div>`;
    });

    container.innerHTML = html;
    container.dataset.loaded = '1';
  } catch(e) {
    container.innerHTML = `<div class="recom-empty" style="color:var(--red);">Error: ${e.message}</div>`;
  }
}

// ── Sugerencias bajo estándar ─────────────────────────────────────
async function cargarSugerencias() {
  const container = document.getElementById('suger-container');
  if (!container || container.dataset.loaded === '1') return;

  container.innerHTML = '';
  showAiLoading('Identificando operarios bajo estándar...', 'Analizando ranking de productividad.');

  try {
    const ranking = await fetch('/api/operarios/ranking').then(r => r.json());
    const bajos = (ranking.operarios || []).filter(o => o.bajo_estandar).slice(0, 5);

    if (bajos.length === 0) {
      hideAiLoading();
      container.innerHTML = '<div class="recom-empty">✅ Todos los operarios están dentro del estándar.</div>';
      return;
    }

    let html = `<div style="padding:10px 16px;background:#fef2f2;border:1px solid var(--red);border-radius:8px;font-size:13px;color:var(--red);font-weight:600;margin-bottom:20px;">⚠️ ${bajos.length} operario${bajos.length > 1 ? 's' : ''} bajo estándar</div>`;
    container.innerHTML = html + '<div id="suger-cards"></div>';

    const cardsEl = document.getElementById('suger-cards');
    for (let i = 0; i < bajos.length; i++) {
      const op = bajos[i];
      showAiLoading(
        `Generando sugerencias ${i + 1} de ${bajos.length}...`,
        `Analizando operario ${op.operario_id} con IA.`
      );
      try {
        const data = await fetch(`/api/recomendaciones/${op.operario_id}/enriquecido`).then(r => r.json());
        const recs = (data.recomendaciones || []).slice(0, 2);
        let cardHtml = `<div style="margin-bottom:20px;"><div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;padding:10px 14px;background:var(--surface-alt);border-radius:8px;border-left:4px solid ${op.estado==='bad'?'var(--red)':'var(--amber)'};">
          <span style="font-weight:700;color:var(--text-hi);">${op.operario_id}</span>
          <span class="ranking-badge ${op.estado}" style="margin-left:4px;">${op.estado==='bad'?'⚠ Crítico':'⚡ Atención'}</span>
          <span style="font-size:12px;color:var(--muted);margin-left:auto;">Vel: ${op.vel_promedio}s · Error: ${op.tasa_error}%</span>
        </div>`;
        recs.forEach(rec => {
          cardHtml += `<div class="recom-card-light ${op.estado==='bad'?'bad':'warn'}" style="margin-left:16px;">
            <div class="recom-card-title">${rec.titulo}</div>
            <div class="recom-desc">${rec.descripcion}</div>
            <div class="recom-accion"><div class="recom-accion-text">⚡ ${rec.accion}</div></div>
            <div class="recom-impacto">💰 ${rec.impacto}</div>
          </div>`;
        });
        cardHtml += '</div>';
        cardsEl.innerHTML += cardHtml;
      } catch(e) {
        cardsEl.innerHTML += `<div class="recom-empty" style="color:var(--muted);margin-bottom:12px;">Sin sugerencias para ${op.operario_id}</div>`;
      }
    }
    hideAiLoading();
    container.dataset.loaded = '1';
  } catch(e) {
    hideAiLoading();
    container.innerHTML = `<div class="recom-empty" style="color:var(--red);">Error: ${e.message}</div>`;
  }
}

// ── Comparativa (sub-tab productividad) ──────────────────────────
async function poblarSelectoresProductividad() {
  const sel = document.getElementById('comp2-operario-sel');
  if (!sel || sel.options.length > 1) return;
  try {
    const data = await fetch('/api/operarios').then(r => r.json());
    (data.operarios || []).forEach(op => {
      const opt = document.createElement('option');
      opt.value = op.operario_id;
      opt.textContent = op.operario_id + (op.nombre ? ' — ' + op.nombre : '');
      sel.appendChild(opt);
    });
  } catch(e) {}
}

async function cargarComparativa2() {
  const opId = document.getElementById('comp2-operario-sel').value;
  const container = document.getElementById('comp2-container');
  if (!opId || !container) return;

  container.innerHTML = '<div style="padding:30px;text-align:center;color:var(--muted);font-size:13px;"><div style="width:28px;height:28px;border:3px solid var(--border);border-top-color:var(--green);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px;"></div>Calculando comparativa...</div>';

  try {
    const analisis = await fetch(`/api/operarios/${opId}/analisis/completo`).then(r => r.json());
    const an = analisis.analisis || analisis;

    // Campos reales del endpoint /analisis/completo
    const sku    = an.correlacion_sku_operario || {};
    const patron = an.patron_semanal           || {};
    const pausa  = an.recuperacion_pausa       || {};
    const zscore = an.anomalia_zscore          || {};

    const skuTop      = (sku.skus_expertos || [])[0] || null;
    const velProm     = sku.velocidad_promedio_seg != null ? sku.velocidad_promedio_seg.toFixed(1) + ' s/pick' : '—';
    const especialPct = sku.especialidad_pct != null ? sku.especialidad_pct.toFixed(0) + '%' : '—';

    const mejorDia   = patron.dia_mas_fuerte || '—';
    const peorDia    = patron.dia_mas_debil  || '—';
    const variacion  = patron.variacion_pct  != null ? patron.variacion_pct.toFixed(1) + '%' : '—';
    const varClass   = (patron.variacion_pct || 0) > 20 ? 'warn' : 'good';

    const recPct    = pausa.promedio_recuperacion_pct != null ? pausa.promedio_recuperacion_pct.toFixed(1) + '%' : '—';
    const recClass  = (pausa.promedio_recuperacion_pct || 0) >= 50 ? 'good' : (pausa.promedio_recuperacion_pct || 0) >= 20 ? 'warn' : 'bad';
    const nPausas   = pausa.pausas_analizadas ?? '—';
    const efectivas = pausa.pausas_efectivas  ?? '—';
    const mejorTipo = pausa.mejor_tipo_pausa  || '—';

    const anomalos  = zscore.picks_anomalos   ?? '—';
    const analizados= zscore.picks_analizados ?? '—';
    const pctAnom   = zscore.porcentaje_anomalas != null ? zscore.porcentaje_anomalas.toFixed(1) + '%' : '—';
    const razon     = zscore.razon_probable   || '—';
    const confianza = zscore.confianza_pct    != null ? zscore.confianza_pct.toFixed(0) + '%' : '—';
    const anomClass = (zscore.porcentaje_anomalas || 0) > 10 ? 'bad' : (zscore.porcentaje_anomalas || 0) > 3 ? 'warn' : 'good';

    container.innerHTML = `
      <div style="margin-bottom:16px;padding:12px 16px;background:var(--green-light);border:1px solid var(--green);border-radius:10px;font-size:13px;color:var(--green);font-weight:600;">
        📊 Análisis: <strong>${opId}</strong>
      </div>
      <div class="comp-grid">
        <div class="comp-card">
          <div class="comp-card-title">Velocidad y Especialización SKU</div>
          <div class="comp-row"><span class="comp-row-label">Vel. promedio</span><span class="comp-row-val">${velProm}</span></div>
          <div class="comp-row"><span class="comp-row-label">SKU más fuerte</span><span class="comp-row-val good">${skuTop ? skuTop.sku_id : '—'}</span></div>
          <div class="comp-row"><span class="comp-row-label">Vel. en SKU top</span><span class="comp-row-val good">${skuTop ? skuTop.velocidad_seg.toFixed(1)+' s/pick' : '—'}</span></div>
          <div class="comp-row"><span class="comp-row-label">Especialidad</span><span class="comp-row-val">${especialPct}</span></div>
          ${sku.recomendacion ? `<div style="margin-top:10px;font-size:11px;color:var(--muted);font-style:italic;line-height:1.5;">${sku.recomendacion}</div>` : ''}
        </div>
        <div class="comp-card">
          <div class="comp-card-title">Patrón Semanal</div>
          <div class="comp-row"><span class="comp-row-label">Mejor día</span><span class="comp-row-val good">${mejorDia}</span></div>
          <div class="comp-row"><span class="comp-row-label">Peor día</span><span class="comp-row-val warn">${peorDia}</span></div>
          <div class="comp-row"><span class="comp-row-label">Variación semana</span><span class="comp-row-val ${varClass}">${variacion}</span></div>
          ${patron.recomendacion ? `<div style="margin-top:10px;font-size:11px;color:var(--muted);font-style:italic;line-height:1.5;">${patron.recomendacion}</div>` : ''}
        </div>
        <div class="comp-card">
          <div class="comp-card-title">Recuperación tras Pausas</div>
          <div class="comp-row"><span class="comp-row-label">Recuperación prom.</span><span class="comp-row-val ${recClass}">${recPct}</span></div>
          <div class="comp-row"><span class="comp-row-label">Pausas analizadas</span><span class="comp-row-val">${nPausas}</span></div>
          <div class="comp-row"><span class="comp-row-label">Pausas efectivas</span><span class="comp-row-val good">${efectivas}</span></div>
          <div class="comp-row"><span class="comp-row-label">Mejor tipo pausa</span><span class="comp-row-val">${mejorTipo}</span></div>
        </div>
        <div class="comp-card">
          <div class="comp-card-title">Anomalías Detectadas</div>
          <div class="comp-row"><span class="comp-row-label">Picks anómalos</span><span class="comp-row-val ${anomClass}">${anomalos} / ${analizados}</span></div>
          <div class="comp-row"><span class="comp-row-label">% anomalías</span><span class="comp-row-val ${anomClass}">${pctAnom}</span></div>
          <div class="comp-row"><span class="comp-row-label">Razón probable</span><span class="comp-row-val">${razon}</span></div>
          <div class="comp-row"><span class="comp-row-label">Confianza análisis</span><span class="comp-row-val">${confianza}</span></div>
        </div>
      </div>`;
  } catch(e) {
    container.innerHTML = `<div class="recom-empty" style="color:var(--red);">Error: ${e.message}</div>`;
  }
}

// ── ai-panel tabs (Cumplimiento de Plan) ─────────────────────────
function switchAiTab(tab) {
  ['analysis','debug'].forEach(t => {
    document.getElementById('tab-btn-'+t).classList.toggle('active', t === tab);
    document.getElementById('tab-'+t).classList.toggle('active', t === tab);
  });
}

// ── Recomendaciones tab ───────────────────────────────────────────
async function populateRecomOpSelector() {
  const sel = document.getElementById('recom-operario-sel');
  if (sel.options.length > 1) return; // ya poblado
  try {
    const data = await fetch('/api/operarios').then(r => r.json());
    (data.operarios || []).forEach(op => {
      const opt = document.createElement('option');
      opt.value = op.operario_id;
      opt.textContent = op.operario_id + (op.nombre ? ' — ' + op.nombre : '');
      sel.appendChild(opt);
    });
    // También poblar el selector de comparativas
    const sel2 = document.getElementById('comp-operario-sel');
    if (sel2.options.length === 1) {
      (data.operarios || []).forEach(op => {
        const opt = document.createElement('option');
        opt.value = op.operario_id;
        opt.textContent = op.operario_id + (op.nombre ? ' — ' + op.nombre : '');
        sel2.appendChild(opt);
      });
    }
  } catch(e) { console.warn('Error cargando operarios:', e); }
}

async function populateCompOpSelector() {
  const sel = document.getElementById('comp-operario-sel');
  if (sel.options.length > 1) return;
  await populateRecomOpSelector();
}

async function cargarRecomendacionesPicking() {
  const opId = document.getElementById('recom-operario-sel').value;
  const container = document.getElementById('recom-container-picking');
  if (!opId) return;

  container.innerHTML = '<div style="padding:30px;text-align:center;color:var(--muted);font-size:13px;"><div style="width:28px;height:28px;border:3px solid var(--border);border-top-color:var(--green);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px;"></div>Generando recomendaciones con IA...</div>';

  try {
    const data = await fetch(`/api/recomendaciones/${opId}/enriquecido`).then(r => r.json());
    if (!data.recomendaciones || data.recomendaciones.length === 0) {
      container.innerHTML = '<div class="recom-empty">✅ Sin recomendaciones activas — operario en buen estado.</div>';
      return;
    }
    const genTime = (data.generation_time_ms / 1000).toFixed(1);
    const cached = data.cached ? ' · caché' : '';
    let html = `<div class="recom-ai-banner"><strong>✨ ${data.powered_by || 'IA'}</strong><span>⏱ ${genTime}s${cached} · ${data.recomendaciones.length} recomendaciones</span></div>`;

    const SEV = { caida_progresiva:'bad', tasa_error:'bad', reduccion_errores:'bad', patron_semanal:'warn', recuperacion_pausa:'warn', gestion_pausas:'warn', especializacion:'', anomalia:'warn' };
    data.recomendaciones.forEach((rec, i) => {
      const sev = SEV[(rec.tipo||'').toLowerCase().replace(/\s/g,'_')] || '';
      const conf = rec.confianza || 80;
      const confColor = conf >= 85 ? 'var(--ok)' : conf >= 70 ? 'var(--amber)' : 'var(--red)';
      html += `
        <div class="recom-card-light ${sev}" style="animation-delay:${i*.1}s">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:10px;">
            <div class="recom-card-title">${rec.titulo}</div>
            <span class="recom-chip">${rec.tipo || 'insight'}</span>
          </div>
          <div class="recom-conf-wrap">
            <span class="recom-conf-label">Confianza IA</span>
            <div class="recom-conf-track"><div class="recom-conf-fill" style="width:${conf}%;background:${confColor};"></div></div>
            <span class="recom-conf-val" style="color:${confColor}">${conf}%</span>
          </div>
          <div class="recom-desc">${rec.descripcion}</div>
          <div class="recom-accion"><div class="recom-accion-text">⚡ ${rec.accion}</div></div>
          <div class="recom-impacto">💰 ${rec.impacto}</div>
        </div>`;
    });
    container.innerHTML = html;
  } catch(e) {
    container.innerHTML = `<div class="recom-empty" style="color:var(--red);">Error cargando recomendaciones: ${e.message}</div>`;
  }
}

// ── Comparativas tab ──────────────────────────────────────────────
async function cargarComparativasPicking() {
  const opId = document.getElementById('comp-operario-sel').value;
  const container = document.getElementById('comp-container-picking');
  if (!opId) return;

  container.innerHTML = '<div style="padding:30px;text-align:center;color:var(--muted);font-size:13px;"><div style="width:28px;height:28px;border:3px solid var(--border);border-top-color:var(--green);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px;"></div>Calculando comparativa...</div>';

  try {
    const [analisis, todos] = await Promise.all([
      fetch(`/api/operarios/${opId}/analisis/completo`).then(r => r.json()),
      fetch('/api/operarios').then(r => r.json())
    ]);

    const op = (todos.operarios || []).find(o => o.operario_id === opId) || {};
    const an = analisis.analisis || analisis;

    // Extraer métricas clave
    const caida = an.caida_progresiva || {};
    const sku = an.correlacion_sku || {};
    const pausa = an.recuperacion_pausa || {};
    const patron = an.patron_semanal || {};
    const zscore = an.anomalia_zscore || {};

    const sev = v => v >= 85 ? 'good' : v >= 65 ? 'warn' : 'bad';
    const bar = (val, max=100, color='var(--green)') =>
      `<div class="comp-bar-wrap"><div class="comp-bar-track"><div class="comp-bar-fill" style="width:${Math.min(val,100)}%;background:${color};"></div></div></div>`;

    container.innerHTML = `
      <div style="margin-bottom:16px;padding:12px 16px;background:var(--green-light);border:1px solid var(--green);border-radius:10px;font-size:13px;color:var(--green);font-weight:600;">
        📊 Análisis comparativo: <strong>${opId}</strong>${op.nombre ? ' — '+op.nombre : ''}
      </div>
      <div class="comp-grid">
        <div class="comp-card">
          <div class="comp-card-title">Caída de productividad</div>
          <div class="comp-row">
            <span class="comp-row-label">Porcentaje de caída</span>
            <span class="comp-row-val ${sev(100-(caida.porcentaje_caida||0))}">${caida.porcentaje_caida != null ? caida.porcentaje_caida.toFixed(1)+'%' : '—'}</span>
          </div>
          <div class="comp-row">
            <span class="comp-row-label">Severidad</span>
            <span class="comp-row-val ${caida.severidad === 'CRÍTICA' ? 'bad' : caida.severidad === 'ALTA' ? 'warn' : 'good'}">${caida.severidad || '—'}</span>
          </div>
          <div class="comp-row">
            <span class="comp-row-label">Picks inicio vs fin turno</span>
            <span class="comp-row-val">${caida.picks_inicio != null ? caida.picks_inicio+' → '+caida.picks_fin : '—'}</span>
          </div>
        </div>
        <div class="comp-card">
          <div class="comp-card-title">Especialización por SKU</div>
          <div class="comp-row">
            <span class="comp-row-label">SKU más fuerte</span>
            <span class="comp-row-val good">${sku.sku_top || '—'}</span>
          </div>
          <div class="comp-row">
            <span class="comp-row-label">Velocidad en SKU top</span>
            <span class="comp-row-val">${sku.velocidad_sku_top != null ? sku.velocidad_sku_top.toFixed(1)+' seg/pick' : '—'}</span>
          </div>
          <div class="comp-row">
            <span class="comp-row-label">Ventaja vs promedio</span>
            <span class="comp-row-val good">${sku.ventaja_pct != null ? '+'+sku.ventaja_pct.toFixed(1)+'%' : '—'}</span>
          </div>
        </div>
        <div class="comp-card">
          <div class="comp-card-title">Recuperación tras pausas</div>
          <div class="comp-row">
            <span class="comp-row-label">Recuperación post-pausa</span>
            <span class="comp-row-val ${sev(pausa.pct_recuperacion||0)}">${pausa.pct_recuperacion != null ? pausa.pct_recuperacion.toFixed(1)+'%' : '—'}</span>
          </div>
          <div class="comp-row">
            <span class="comp-row-label">Pausas analizadas</span>
            <span class="comp-row-val">${pausa.n_pausas != null ? pausa.n_pausas : '—'}</span>
          </div>
          <div class="comp-row">
            <span class="comp-row-label">Tiempo promedio pausa</span>
            <span class="comp-row-val">${pausa.duracion_promedio != null ? pausa.duracion_promedio.toFixed(0)+' min' : '—'}</span>
          </div>
        </div>
        <div class="comp-card">
          <div class="comp-card-title">Patrón semanal / Anomalías</div>
          <div class="comp-row">
            <span class="comp-row-label">Mejor día de la semana</span>
            <span class="comp-row-val good">${patron.mejor_dia || '—'}</span>
          </div>
          <div class="comp-row">
            <span class="comp-row-label">Variabilidad semanal</span>
            <span class="comp-row-val ${sev(100-(patron.variabilidad||0))}">${patron.variabilidad != null ? patron.variabilidad.toFixed(1)+'%' : '—'}</span>
          </div>
          <div class="comp-row">
            <span class="comp-row-label">Z-score actual</span>
            <span class="comp-row-val ${Math.abs(zscore.zscore||0) > 2 ? 'bad' : 'good'}">${zscore.zscore != null ? zscore.zscore.toFixed(2) : '—'}</span>
          </div>
        </div>
      </div>`;
  } catch(e) {
    container.innerHTML = `<div class="recom-empty" style="color:var(--red);">Error cargando comparativa: ${e.message}</div>`;
  }
}

// ── Proveedor IA ──────────────────────────────────────────────────
async function loadProviders() {
  try {
    const data = await fetch('/api/providers').then(r => r.json());
    activeProvider = data.active;
    renderProviderBtns(data);
  } catch(e) {
    document.getElementById('provider-btns').innerHTML =
      '<span style="font-size:11px;color:var(--accent2)">Backend no disponible</span>';
    setProviderStatus('sin conexión', 'err');
  }
}

function renderProviderBtns(data) {
  providersLoaded = true;
  const wrap = document.getElementById('provider-btns');
  wrap.innerHTML = '';
  data.available.forEach(p => {
    const btn = document.createElement('button');
    btn.className = 'prov-btn' +
      (p.id === data.active ? ' active ' + p.id : '') +
      (!p.configured ? ' unconfigured' : '');
    btn.dataset.id = p.id;
    btn.innerHTML  = (p.configured ? '<span class="check">✓</span> ' : '') + p.name;
    btn.title      = p.configured ? p.name + ' — configurado' : p.name + ' — completar .env';
    if (p.configured) btn.onclick = () => selectProvider(p.id, data.available);
    wrap.appendChild(btn);
  });
  updateAiBadge(data.active);
  const any = data.available.some(p => p.configured);
  setProviderStatus(any ? data.active + ' listo' : 'sin proveedor configurado', any ? 'ok' : 'err');
}

function selectProvider(id) {
  activeProvider = id;
  document.querySelectorAll('.prov-btn').forEach(b => {
    b.classList.remove('active','claude','azure','ollama','gemini');
    if (b.dataset.id === id) b.classList.add('active', id);
  });
  updateAiBadge(id);
  setProviderStatus(id + ' activo', 'ok');

  // Si ya hay datos calculados y el form está colapsado → expandir y señalar el botón
  if (currentFormData) {
    const body = document.getElementById('form-body');
    if (!body.classList.contains('open')) {
      _openForm(body);
    }
    // Scroll suave al botón y efecto de pulso para indicar que hay que recalcular
    const btn = document.getElementById('btn-calcular');
    btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
    btn.classList.add('pulse-hint');
    setTimeout(() => btn.classList.remove('pulse-hint'), 1800);
  }
}

function updateAiBadge(provider) {
  const badge = document.getElementById('ai-badge');
  if (provider === 'gemini')      { badge.className='badge b-ai gemini'; badge.textContent='GEMINI'; }
  else if (provider === 'azure')  { badge.className='badge b-ai azure';  badge.textContent='AZURE GPT'; }
  else if (provider === 'ollama') { badge.className='badge b-ai ollama'; badge.textContent='OLLAMA'; }
  else                            { badge.className='badge b-ai';         badge.textContent='CLAUDE'; }
}

function setProviderStatus(text, cls) {
  const el = document.getElementById('provider-status');
  el.textContent = text;
  el.className   = cls || '';
}

// Proveedor IA fijo por configuracion backend (.env)
function initProviderBar() {
  document.getElementById('ai-alerts').innerHTML =
    '<div style="font-size:11px;color:var(--muted)">Todavia no se ejecuto ningun analisis.</div>';
  updateAiBadge(activeProvider);
  setProviderStatus('Proveedor fijo por configuracion', '');
  loadProviders();
}

async function ensureProvidersLoaded() {
  if (providersLoaded) return;
  setProviderStatus('Leyendo proveedor configurado...', 'loading');
  try {
    const data = await fetch('/api/config/ia').then(r => r.json());
    activeProvider = (data.provider || activeProvider || 'claude').toLowerCase();
    providersLoaded = true;
    updateAiBadge(activeProvider);
    setProviderStatus((data.label || activeProvider) + ' fijo por .env', 'ok');
  } catch (e) {
    providersLoaded = true;
    setProviderStatus('No se pudo leer configuracion IA', 'err');
  }
}

async function loadProviders() {
  try {
    const data = await fetch('/api/config/ia').then(r => r.json());
    activeProvider = (data.provider || activeProvider || 'claude').toLowerCase();
    providersLoaded = true;
    updateAiBadge(activeProvider);
    setProviderStatus((data.label || activeProvider) + ' fijo por .env', 'ok');
  } catch(e) {
    providersLoaded = true;
    setProviderStatus('sin conexion', 'err');
  }
}

function renderProviderBtns(data) {
  activeProvider = (data.active || data.provider || activeProvider || 'claude').toLowerCase();
  providersLoaded = true;
  updateAiBadge(activeProvider);
  setProviderStatus(activeProvider + ' fijo por .env', 'ok');
}

function selectProvider() {
  updateAiBadge(activeProvider);
  setProviderStatus('Proveedor fijo por .env', 'ok');
}

// ── Chat ──────────────────────────────────────────────────────────
function toggleChat() {
  const body   = document.getElementById('chat-body');
  const header = document.getElementById('chat-header');
  const chev   = document.getElementById('chat-chevron');
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  header.classList.toggle('open', !isOpen);
  chev.classList.toggle('open', !isOpen);
}

function openChat() {
  const body   = document.getElementById('chat-body');
  const header = document.getElementById('chat-header');
  const chev   = document.getElementById('chat-chevron');
  if (!body.classList.contains('open')) {
    body.classList.add('open');
    header.classList.add('open');
    chev.classList.add('open');
  }
  document.getElementById('ai-chat').style.display = 'block';
  document.getElementById('chat-input')?.focus();
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg   = input.value.trim();
  if (!msg) return;
  await ensureProvidersLoaded();
  input.value = '';
  appendChat(msg, 'user');
  chatHistory.push({ role:'user', content:msg });
  appendChat('...', 'ai', 'typing');

  const ctx = currentFormData ? buildContext(currentFormData) : 'Sin datos cargados aún.';
  try {
    const result = await fetch('/api/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ message:msg, history:chatHistory.slice(0,-1), context:ctx }),
    }).then(r => r.json());
    chatHistory.push({ role:'assistant', content: result.reply });
    document.getElementById('typing')?.remove();
    appendChat(result.reply, 'ai');
  } catch(e) {
    document.getElementById('typing')?.remove();
    appendChat('Error al consultar la IA.', 'ai');
  }
}

function appendChat(t, r, id) {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  const d = document.createElement('div');
  d.className = 'chat-msg ' + r;
  d.textContent = t;
  if (id) d.id = id;
  el.appendChild(d);
  el.scrollTop = el.scrollHeight;
}

// ── Sugerencias de preguntas ──────────────────────────────────────
function generarSugerenciasPreguntas(estado, historico) {
  const DIAS = ['lunes','martes','miércoles','jueves','viernes','sábado','domingo'];
  const diaNombre = DIAS[historico.dia_semana ?? new Date().getDay() - 1] || 'hoy';

  const base = [
    '¿Vamos a cerrar el turno?',
    '¿Cómo vamos vs el histórico de hoy?',
    '¿Cuál es la ola más crítica?',
  ];

  const condicionales = [];
  const gap = estado.ejecTotal - estado.progTotal;
  if (gap < -500)
    condicionales.push('¿Cuánto tiempo me queda para recuperar?');
  if (estado.dotEjec && estado.dotProg && estado.dotEjec < estado.dotProg * 0.9)
    condicionales.push('¿Qué impacto tiene la dotación baja?');
  if (historico.prom_turno && estado.ejecTotal && estado.ejecTotal < historico.prom_turno * 0.8)
    condicionales.push('¿Qué necesito para cerrar el turno?');

  const historicas = [
    `¿Cuál fue el mejor ${diaNombre} del año?`,
    `¿Cómo cerraron los últimos ${diaNombre}s?`,
  ];

  return [...condicionales.slice(0,2), ...base.slice(0,2), ...historicas].slice(0,4);
}

function renderizarSugerencias(sugerencias) {
  const wrap  = document.getElementById('sugerencias-wrap');
  const chips = document.getElementById('sugerencias-chips');
  if (!wrap || !chips) return;
  wrap.style.display = sugerencias.length ? 'block' : 'none';
  chips.innerHTML = sugerencias.map(p =>
    `<button class="chip" onclick="enviarPregunta(${JSON.stringify(p)})">${p}</button>`
  ).join('');
}

async function enviarPregunta(pregunta) {
  openChat();
  appendChat(pregunta, 'user');
  chatHistory.push({ role:'user', content: pregunta });
  appendChat('...', 'ai', 'typing');

  const ctx = currentFormData ? buildContext(currentFormData) : 'Sin datos cargados aún.';
  try {
    const result = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: pregunta, history: chatHistory.slice(0,-1), context: ctx }),
    }).then(r => r.json());
    chatHistory.push({ role:'assistant', content: result.reply });
    document.getElementById('typing')?.remove();
    appendChat(result.reply, 'ai');
  } catch(e) {
    document.getElementById('typing')?.remove();
    appendChat('Error al consultar la IA.', 'ai');
  }
}

function actualizarSugerencias(estado, historico) {
  window._estadoActual   = estado;
  window._historicoActual = historico;
  renderizarSugerencias(generarSugerenciasPreguntas(estado, historico));
}

// ── Reloj ─────────────────────────────────────────────────────────
function updateClock() {
  const n = new Date();
  document.getElementById('clock-time').textContent =
    String(n.getHours()).padStart(2,'0')+':'+
    String(n.getMinutes()).padStart(2,'0')+':'+
    String(n.getSeconds()).padStart(2,'0');
}

// ── Inicio (sin cálculos automáticos) ────────────────────────────
(async function bootstrap() {
  await loadCumplimientoData();
  selectedOla = detectOlaActual();
  initProviderBar();
  initForm();
  await loadPlantelTurnos();
  resetPlantelForm();
  await loadPlantelScenarios();
  initAnalisisProductividadDefaults();
  setInterval(updateClock, 1000);
  updateClock();
})();
