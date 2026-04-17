
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
//  DATOS DEL EXCEL (Programa 5441 â€” valores sugeridos por defecto)
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
const EXCEL_DATA = {
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
    { num:9,  label:'OLA 9',  turno:'MaÃ±ana', ini:6,  fin:8,
      progSecos:15361, progNOA:1103,  ejecSecos:18008, ejecNOA:713,
      dotProg:58, dotEjec:81, prodProg:283.86, prodEjec:231.12,
      obs:'Pasan armadores de NOA, Refri a Secos y 1 maquinista de Refri' },
    { num:10, label:'OLA 10', turno:'MaÃ±ana', ini:8,  fin:10,
      progSecos:16929, progNOA:681,   ejecSecos:12666, ejecNOA:814,
      dotProg:58, dotEjec:81, prodProg:303.63, prodEjec:166.42, obs:'' },
    { num:11, label:'OLA 11', turno:'MaÃ±ana', ini:10, fin:12,
      progSecos:12309, progNOA:905,   ejecSecos:16320, ejecNOA:1023,
      dotProg:58, dotEjec:72, prodProg:227.83, prodEjec:240.88, obs:'' },
    { num:12, label:'OLA 12', turno:'MaÃ±ana', ini:12, fin:14,
      progSecos:12707, progNOA:1022,  ejecSecos:12658, ejecNOA:1682,
      dotProg:58, dotEjec:71, prodProg:236.71, prodEjec:201.97, obs:'' },
  ],
  turnoTotales: {
    Tarde:  { prog:51081, ejec:53992 },
    Noche:  { prog:46678, ejec:42141 },
    MaÃ±ana: { prog:61018, ejec:63884 },
  }
};

// â”€â”€ Estado â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
let selectedOla    = detectOlaActual();
let activeProvider = 'claude';
let providersLoaded = false;
let aiAlerts       = [];
let chatHistory    = [];
let dashboardLive  = false;
let currentFormData = null;  // datos confirmados mÃ¡s recientes

const fmt   = n => Math.round(n).toLocaleString('es');
const fmtF  = n => parseFloat(n).toFixed(1);
const nowStr= () => { const n=new Date(); return String(n.getHours()).padStart(2,'0')+':'+String(n.getMinutes()).padStart(2,'0'); };

// â”€â”€ Detectar ola actual por hora â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function detectOlaActual() {
  const h = new Date().getHours() + new Date().getMinutes()/60;
  const idx = EXCEL_DATA.olas.findIndex(o => {
    if (o.ini < o.fin) return h >= o.ini && h < o.fin;
    return h >= o.ini || h < o.fin;
  });
  return idx >= 0 ? idx : 8; // default OLA 9 si no hay match
}

function initProviderBar() {
  document.querySelector('.ai-provider-bar label').textContent = 'Proveedor IA';
  const wrap = document.getElementById('provider-btns');
  document.getElementById('ai-alerts').innerHTML =
    '<div style="font-size:11px;color:var(--muted)">TodavÃ­a no se ejecutÃ³ ningÃºn anÃ¡lisis.</div>';
  wrap.innerHTML = '';
  [
    { id:'claude', name:'Claude (manual)' },
    { id:'azure', name:'Azure OpenAI (manual)' },
  ].forEach(p => {
    const btn = document.createElement('button');
    btn.className = 'prov-btn' + (p.id === activeProvider ? ' active ' + p.id : '');
    btn.dataset.id = p.id;
    btn.textContent = p.name;
    btn.onclick = () => selectProvider(p.id);
    wrap.appendChild(btn);
  });
  updateAiBadge(activeProvider);
  setProviderStatus('Listo para editar Â· sin consulta inicial', '');
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

// â”€â”€ Inicializar formulario â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function initForm() {
  // Botones de ola
  const wrap = document.getElementById('ola-btns');
  wrap.innerHTML = '';
  EXCEL_DATA.olas.forEach((o, i) => {
    const btn = document.createElement('button');
    btn.className = 'ola-btn' + (i === selectedOla ? ' active' : '');
    btn.textContent = o.label;
    btn.onclick = () => selectOla(i);
    wrap.appendChild(btn);
  });
  loadOlaIntoForm(selectedOla);
}

function selectOla(idx) {
  selectedOla = idx;
  document.querySelectorAll('.ola-btn').forEach((b, i) => {
    b.className = 'ola-btn' + (i === idx ? ' active' : '');
  });
  loadOlaIntoForm(idx);
}

function loadOlaIntoForm(idx) {
  const o = EXCEL_DATA.olas[idx];
  const finStr = o.fin === 24 ? '00:00' : o.fin + ':00';

  // Tags de turno y horario
  const turnoTag = document.getElementById('turno-tag');
  turnoTag.textContent = o.turno;
  turnoTag.className = 'ola-turno-tag ' + o.turno;
  document.getElementById('ola-horario').textContent = o.ini + ':00 â€“ ' + finStr;
  document.getElementById('form-ola-tag').textContent = o.label + ' Â· ' + o.turno;

  // Poblar campos con valores sugeridos
  setField('f-prog-secos', o.progSecos, 'sug-prog-secos', o.progSecos);
  setField('f-prog-noa',   o.progNOA,   'sug-prog-noa',   o.progNOA);
  setField('f-ejec-secos', o.ejecSecos, 'sug-ejec-secos', o.ejecSecos);
  setField('f-ejec-noa',   o.ejecNOA,   'sug-ejec-noa',   o.ejecNOA);
  setField('f-dot-prog',   o.dotProg,   'sug-dot-prog',   o.dotProg);
  setField('f-dot-ejec',   o.dotEjec,   'sug-dot-ejec',   o.dotEjec);
  setField('f-prod-prog',  o.prodProg,  'sug-prod-prog',  o.prodProg);
  setField('f-prod-ejec',  o.prodEjec,  'sug-prod-ejec',  o.prodEjec);

  document.getElementById('f-obs').value = o.obs || '';
  document.getElementById('sug-obs').textContent = o.obs ? '(Excel: "'+o.obs+'")'  : '';

  updateAutoFields();
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
  const checks = [
    ['f-prog-secos', o.progSecos],
    ['f-prog-noa',   o.progNOA],
    ['f-ejec-secos', o.ejecSecos],
    ['f-ejec-noa',   o.ejecNOA],
    ['f-dot-prog',   o.dotProg],
    ['f-dot-ejec',   o.dotEjec],
    ['f-prod-prog',  o.prodProg],
    ['f-prod-ejec',  o.prodEjec],
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
  document.getElementById('f-prog-total').value = Math.round(ps + pn);

  const es = parseFloat(document.getElementById('f-ejec-secos').value) || 0;
  const en = parseFloat(document.getElementById('f-ejec-noa').value) || 0;
  document.getElementById('f-ejec-total').value = Math.round(es + en);

  const dp = parseFloat(document.getElementById('f-dot-prog').value) || 0;
  const de = parseFloat(document.getElementById('f-dot-ejec').value) || 0;
  document.getElementById('f-dot-dif').value = Math.round(de - dp);

  const pp = parseFloat(document.getElementById('f-prod-prog').value) || 0;
  const pe = parseFloat(document.getElementById('f-prod-ejec').value) || 0;
  const varP = pp > 0 ? ((pe - pp) / pp * 100) : 0;
  const varEl = document.getElementById('f-prod-var');
  varEl.value = (varP >= 0 ? '+' : '') + varP.toFixed(1) + '%';
  varEl.style.color = varP >= 0 ? 'var(--accent)' : 'var(--accent2)';
}

function resetToSuggested() {
  loadOlaIntoForm(selectedOla);
}

function toggleForm() {
  const body  = document.getElementById('form-body');
  const chev  = document.getElementById('form-chevron');
  const open  = body.classList.contains('open');
  body.style.display = open ? 'none' : 'block';
  body.classList.toggle('open', !open);
  chev.textContent = open ? 'â–¼' : 'â–²';
  chev.classList.toggle('open', !open);
}

// â”€â”€ Leer formulario como objeto â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
    prodProg:  parseFloat(document.getElementById('f-prod-prog').value)  || 0,
    prodEjec:  parseFloat(document.getElementById('f-prod-ejec').value)  || 0,
    obs:       document.getElementById('f-obs').value.trim(),
  };
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
//  CALCULAR Y ANALIZAR
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
async function calcularYAnalizar() {
  const btn = document.getElementById('btn-calcular');
  btn.disabled = true;
  btn.textContent = 'â³ Calculando...';

  currentFormData = readForm();
  await ensureProvidersLoaded();

  // Mostrar dashboard
  document.getElementById('dashboard-empty').style.display = 'none';
  document.getElementById('dashboard').style.display = 'block';
  dashboardLive = true;

  // Actualizar badge
  const badge = document.getElementById('status-badge');
  badge.className = 'badge b-live';
  badge.textContent = 'EN VIVO Â· ' + nowStr();

  // Renderizar dashboard con los datos del formulario
  renderDashboard(currentFormData);

  // Colapsar formulario
  const body = document.getElementById('form-body');
  const chev = document.getElementById('form-chevron');
  body.style.display = 'none';
  body.classList.remove('open');
  chev.textContent = 'â–¼';
  chev.classList.remove('open');

  // Llamar a la IA
  await runAiAnalysis(buildContext(currentFormData));

  btn.disabled = false;
  btn.textContent = 'â–¶ Recalcular';
}

// â”€â”€ Render del dashboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function renderDashboard(d) {
  const gap  = d.ejecTotal - d.progTotal;
  const t    = EXCEL_DATA.turnoTotales[d.turno];

  // ProyecciÃ³n simple: si ejecTotal / progTotal ratio se mantiene para las olas restantes
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
  document.getElementById('kpi-real-sub').textContent = 'turno ' + d.turno + ' Â· ' + d.label;
  document.getElementById('kpi-exp').textContent      = fmt(d.progTotal);

  const gEl  = document.getElementById('kpi-gap');
  const gSub = document.getElementById('kpi-gap-sub');
  gEl.textContent  = (gap>=0?'+':'') + fmt(gap);
  gEl.style.color  = gap>=0 ? 'var(--accent)' : 'var(--accent2)';
  gSub.className   = 'kpi-sub ' + (gap>=0 ? 'good' : 'bad');
  gSub.textContent = gap>=0 ? 'por encima del objetivo' : 'por debajo del objetivo';

  document.getElementById('kpi-proj').textContent = fmt(proyeccion);
  const projDiff = proyeccion - objTurno;
  const ps = document.getElementById('kpi-proj-sub');
  ps.className   = 'kpi-sub ' + (projDiff>=0?'good':projDiff>=-objTurno*0.05?'warn':'bad');
  ps.textContent = projDiff>=0
    ? 'âœ“ +'+fmt(projDiff)+' sobre objetivo'
    : 'âš  dÃ©ficit est. '+fmt(Math.abs(projDiff))+' bultos';

  // ProyecciÃ³n box
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
      <div class="ola-name">${o.label} Â· ${o.ini}:00â€“${finStr}:00</div>
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
  const nombres = ['GarcÃ­a J.','RodrÃ­guez M.','LÃ³pez K.','MartÃ­nez S.','FernÃ¡ndez R.',
                   'DÃ­az P.','Torres A.','GÃ³mez C.','NÃºÃ±ez P.','Ãlvarez R.',
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

// â”€â”€ Contexto para IA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function buildContext(d) {
  const gap       = d.ejecTotal - d.progTotal;
  const varDot    = d.dotEjec - d.dotProg;
  const varProd   = d.prodProg > 0 ? ((d.prodEjec - d.prodProg) / d.prodProg * 100) : 0;
  const olasDelTurno = EXCEL_DATA.olas.filter(o => o.turno === d.turno);
  const olasRest  = olasDelTurno.filter(o => o.num > d.olaNum).length;

  return `VIGIA Â· ESTADO OPERATIVO â€” CD Coto Â· Programa ${EXCEL_DATA.programa}
Turno: ${d.turno} | ${d.label} (${d.ini}:00â€“${d.fin===24?'00:00':d.fin+':00'}) | ${nowStr()} hs

BULTOS:
- Programado: Secos ${fmt(d.progSecos)} + NOA ${fmt(d.progNOA)} = Total ${fmt(d.progTotal)}
- Ejecutado:  Secos ${fmt(d.ejecSecos)} + NOA ${fmt(d.ejecNOA)} = Total ${fmt(d.ejecTotal)}
- DesvÃ­o: ${gap>=0?'+':''}${fmt(gap)} bultos (${(d.progTotal>0?(d.ejecTotal/d.progTotal*100).toFixed(1):0)}% del objetivo)

DOTACIÃ“N:
- Programada: ${d.dotProg} operarios
- Real: ${d.dotEjec} operarios (${varDot>=0?'+':''}${varDot} vs programado)

PRODUCTIVIDAD:
- Programada: ${fmtF(d.prodProg)} bultos/operario
- Real: ${fmtF(d.prodEjec)} bultos/operario (${varProd>=0?'+':''}${varProd.toFixed(1)}% vs programado)

OLAS RESTANTES EN EL TURNO: ${olasRest}
${d.obs ? 'OBSERVACIÃ“N: ' + d.obs : ''}`;
}

// â”€â”€ IA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function runAiAnalysis(context) {
  setProviderStatus('Analizando operaciÃ³n...', 'loading');
  try {
    const result = await fetch('/api/analyze', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ provider: activeProvider, context }),
    }).then(r => r.json());

    if (result.error) throw new Error(result.error);
    aiAlerts = (result.alerts || []).map(a => ({ ...a, time: nowStr(), source:'ia' }));
    setProviderStatus(result.provider_used + ' Â· ok', 'ok');
  } catch(e) {
    console.warn('[IA] fallback local:', e.message);
    setProviderStatus('error IA Â· anÃ¡lisis local', 'err');
    runLocalAlerts();
  }
  renderAiAlerts();
}

function runLocalAlerts() {
  if (!currentFormData) return;
  const d   = currentFormData;
  const gap = d.ejecTotal - d.progTotal;
  const t   = EXCEL_DATA.turnoTotales[d.turno];
  const alerts = [];

  if (gap < -500)
    alerts.push({severity:'bad', title:'DesvÃ­o crÃ­tico en la ola',
      detail:`${fmt(Math.abs(gap))} bultos bajo el objetivo programado.`,
      action:'Redistribuir dotaciÃ³n. Revisar causa de demora.'});
  else if (gap < -100)
    alerts.push({severity:'warn', title:'DesvÃ­o en desarrollo',
      detail:`${fmt(Math.abs(gap))} bultos bajo lo esperado en esta ola.`,
      action:'Monitorear ritmo en la prÃ³xima ola.'});
  else
    alerts.push({severity:'ok', title:'Ola dentro del objetivo',
      detail:`DesvÃ­o ${gap>=0?'+':''}${fmt(gap)} bultos. Ritmo estable.`,
      action:'Mantener dotaciÃ³n actual.'});

  if (d.dotEjec < d.dotProg)
    alerts.push({severity:'warn', title:'DotaciÃ³n por debajo del plan',
      detail:`${d.dotEjec} operarios reales vs ${d.dotProg} programados.`,
      action:`Cubrir faltante de ${d.dotProg - d.dotEjec} operarios si es posible.`});

  const varProd = d.prodProg > 0 ? (d.prodEjec - d.prodProg) / d.prodProg * 100 : 0;
  if (varProd < -15)
    alerts.push({severity:'warn', title:'Productividad por debajo del plan',
      detail:`${fmtF(d.prodEjec)} b/op real vs ${fmtF(d.prodProg)} b/op programado (${varProd.toFixed(1)}%).`,
      action:'Revisar causas: ausentismo, pausas no planificadas, congestiÃ³n.'});

  aiAlerts = alerts.map(a => ({...a, time: nowStr(), source:'local'}));
  renderAiAlerts();
}

function renderAiAlerts() {
  const el = document.getElementById('ai-alerts');
  if (!aiAlerts.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--muted)">Sin alertas activas.</div>';
    return;
  }
  el.innerHTML = aiAlerts.map(a => `<div class="ai-alert ${a.severity}">
    <div class="ai-tag">${a.source==='ia'?'âœ¦ IA':'LOCAL'}</div>
    <strong>${a.title}</strong><br>${a.detail}
    ${a.action ? `<div class="alert-rec">â†’ ${a.action}</div>` : ''}
    <div class="alert-time">${a.time}</div>
  </div>`).join('');
}

// â”€â”€ Proveedor IA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function loadProviders() {
  try {
    const data = await fetch('/api/providers').then(r => r.json());
    activeProvider = data.active;
    renderProviderBtns(data);
  } catch(e) {
    document.getElementById('provider-btns').innerHTML =
      '<span style="font-size:11px;color:var(--accent2)">Backend no disponible</span>';
    setProviderStatus('sin conexiÃ³n', 'err');
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
    btn.innerHTML  = (p.configured ? '<span class="check">âœ“</span> ' : '') + p.name;
    btn.title      = p.configured ? p.name + ' â€” configurado' : p.name + ' â€” completar .env';
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
    b.classList.remove('active','claude','azure');
    if (b.dataset.id === id) b.classList.add('active', id);
  });
  updateAiBadge(id);
  setProviderStatus(id + ' activo', 'ok');
}

function updateAiBadge(provider) {
  const badge = document.getElementById('ai-badge');
  if (provider === 'azure') { badge.className='badge b-ai azure'; badge.textContent='AZURE GPT'; }
  else                       { badge.className='badge b-ai';       badge.textContent='CLAUDE'; }
}

function setProviderStatus(text, cls) {
  const el = document.getElementById('provider-status');
  el.textContent = text;
  el.className   = cls || '';
}

// â”€â”€ Chat â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function toggleChat() {
  const b = document.getElementById('chat-body');
  b.className = b.className.includes('open') ? 'chat-body' : 'chat-body open';
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

  const ctx = currentFormData ? buildContext(currentFormData) : 'Sin datos cargados aÃºn.';
  try {
    const result = await fetch('/api/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ provider:activeProvider, message:msg, history:chatHistory.slice(0,-1), context:ctx }),
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
  const d  = document.createElement('div');
  d.className = 'chat-msg ' + r;
  d.textContent = t;
  if (id) d.id = id;
  el.appendChild(d);
  el.scrollTop = el.scrollHeight;
}

// â”€â”€ Reloj â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function updateClock() {
  const n = new Date();
  document.getElementById('clock-time').textContent =
    String(n.getHours()).padStart(2,'0')+':'+
    String(n.getMinutes()).padStart(2,'0')+':'+
    String(n.getSeconds()).padStart(2,'0');
}

// â”€â”€ Inicio (sin cÃ¡lculos automÃ¡ticos) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
initProviderBar();
initForm();
setInterval(updateClock, 1000);
updateClock();

