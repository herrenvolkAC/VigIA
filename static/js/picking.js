/**
 * picking.js — Lógica específica del proceso de Picking · VigIA
 */

// ── System prompt de IA para picking ─────────────────────────────────────────
const AI_SYSTEM_PROMPT = `Sos un analista operativo senior de picking en CD Coto.
Recibís el estado actual de la operación y generás alertas accionables para el supervisor de turno.
Respondé SOLO con JSON válido, sin markdown:
{"alerts":[{"severity":"ok|warn|bad","title":"título breve máx 8 palabras","detail":"qué está pasando con números concretos","action":"qué hacer ahora, específico y operativo"}]}
2-4 alertas. bad=crítico, warn=riesgo, ok=positivo. Acciones concretas con números cuando sea posible.`;

// ── Constantes ────────────────────────────────────────────────────────────────
const SECTORES = [
  { name: 'Secos', color: '#00e5a0' },
  { name: 'NOA',   color: '#00bcd4' },
];

const OLA_DEF = [
  { num:1,  label:'OLA 1',  ini:14, fin:16, turno:'Tarde'  },
  { num:2,  label:'OLA 2',  ini:16, fin:18, turno:'Tarde'  },
  { num:3,  label:'OLA 3',  ini:18, fin:20, turno:'Tarde'  },
  { num:4,  label:'OLA 4',  ini:20, fin:22, turno:'Tarde'  },
  { num:5,  label:'OLA 5',  ini:22, fin:24, turno:'Noche'  },
  { num:6,  label:'OLA 6',  ini:0,  fin:2,  turno:'Noche'  },
  { num:7,  label:'OLA 7',  ini:2,  fin:4,  turno:'Noche'  },
  { num:8,  label:'OLA 8',  ini:4,  fin:6,  turno:'Noche'  },
  { num:9,  label:'OLA 9',  ini:6,  fin:8,  turno:'Mañana' },
  { num:10, label:'OLA 10', ini:8,  fin:10, turno:'Mañana' },
  { num:11, label:'OLA 11', ini:10, fin:12, turno:'Mañana' },
  { num:12, label:'OLA 12', ini:12, fin:14, turno:'Mañana' },
];

// ── Estado global ─────────────────────────────────────────────────────────────
let mode        = 'sim';   // 'sim' | 'real'
let scenario    = 'normal';
let planillaData = null;
let aiAlerts    = [];
let aiAnalyzing = false;
let lastAiTick  = -999;
let tick        = 0;
let chatHistory = [];

// Estado simulación
let simZones = { Secos: 0, NOA: 0 };
let simOps   = [];
let simMinute = 0;

const SIM_SCENARIOS = {
  normal: { factor: 1.0,  noise: 0.06 },
  lento:  { factor: 0.75, noise: 0.08 },
  pico:   { factor: 1.25, noise: 0.07 },
  crisis: { factor: 0.55, noise: 0.12 },
};
const SIM_OPS  = ['García J.','Rodríguez M.','López K.','Martínez S.','Fernández R.','Díaz P.','Torres A.','Gómez C.'];
const SIM_BASE = [95, 88, 102, 78, 110, 92, 85, 97];

// ── Helpers de hora ───────────────────────────────────────────────────────────
function currentHour() { return new Date().getHours() + new Date().getMinutes() / 60; }

function olaActualIdx(hora) {
  return OLA_DEF.findIndex(o => {
    if (o.ini < o.fin) return hora >= o.ini && hora < o.fin;
    return hora >= o.ini || hora < o.fin;
  });
}

function turnoActual(hora) {
  if (hora >= 14 && hora < 22) return 'Tarde';
  if (hora >= 22 || hora < 6)  return 'Noche';
  return 'Mañana';
}

// ── Parseo de planilla ────────────────────────────────────────────────────────
function parsePlanilla(raw) {
  const programa       = raw[2]?.[1] || '—';
  const totalProgramado = raw[2]?.[4] || 0;
  const olaRows = [6,7,8,9, 11,12,13,14, 16,17,18,19];

  const olas = olaRows.map((ri, i) => {
    const row      = raw[ri] || [];
    const dotProg  = parseFloat(row[10]) || 0;
    const dotEjec  = parseFloat(row[12]) || 0;
    const prodProg = parseFloat(row[13]) || 0;
    const prodEjec = parseFloat(row[14]) || 0;
    return {
      num:       i + 1,
      label:     OLA_DEF[i].label,
      turno:     OLA_DEF[i].turno,
      ini:       OLA_DEF[i].ini,
      fin:       OLA_DEF[i].fin,
      progSecos: parseFloat(row[2])  || 0,
      progNOA:   parseFloat(row[3])  || 0,
      progTotal: parseFloat(row[4])  || 0,
      ejecSecos: parseFloat(row[5])  || 0,
      ejecNOA:   parseFloat(row[6])  || 0,
      ejecTotal: parseFloat(row[7])  || 0,
      dotProg:   dotProg  > 0 && dotProg  < 150 ? dotProg  : 0,
      dotEjec:   dotEjec  > 0 && dotEjec  < 150 ? dotEjec  : 0,
      prodProg:  prodProg > 0 && prodProg < 800  ? prodProg : 0,
      prodEjec:  prodEjec > 0 && prodEjec < 800  ? prodEjec : 0,
      obs:       row[18] || '',
    };
  });

  const avgDot = arr => arr.length
    ? Math.round(arr.reduce((s, o) => s + o.dotEjec, 0) / arr.length)
    : 0;

  const olasTarde  = olas.filter(o => o.turno === 'Tarde');
  const olasNoche  = olas.filter(o => o.turno === 'Noche');
  const olasMañana = olas.filter(o => o.turno === 'Mañana');

  const turnos = {
    Tarde:  { dotEjec: avgDot(olasTarde),  ejecTotal: parseFloat(raw[10]?.[7]) || 0, progTotal: parseFloat(raw[10]?.[4]) || 0 },
    Noche:  { dotEjec: avgDot(olasNoche),  ejecTotal: parseFloat(raw[15]?.[7]) || 0, progTotal: parseFloat(raw[15]?.[4]) || 0 },
    Mañana: { dotEjec: avgDot(olasMañana), ejecTotal: parseFloat(raw[20]?.[7]) || 0, progTotal: parseFloat(raw[20]?.[4]) || 0 },
  };

  const ausencia = {
    Tarde:  { Secos: parseFloat(raw[24]?.[2])||0, NOA: parseFloat(raw[24]?.[3])||0 },
    Noche:  { Secos: parseFloat(raw[25]?.[2])||0, NOA: parseFloat(raw[25]?.[3])||0 },
    Mañana: { Secos: parseFloat(raw[26]?.[2])||0, NOA: parseFloat(raw[26]?.[3])||0 },
  };

  return { programa, totalProgramado, olas, turnos, ausencia };
}

// ── Carga de archivo ──────────────────────────────────────────────────────────
function loadFile(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const wb  = XLSX.read(e.target.result, { type: 'array' });
      const ws  = wb.Sheets[wb.SheetNames[0]];
      const raw = XLSX.utils.sheet_to_json(ws, { header: 1, defval: null });
      planillaData = parsePlanilla(raw);
      const st = document.getElementById('load-status');
      st.className   = 'load-status ok';
      st.textContent = `✓ Programa ${planillaData.programa} · ${planillaData.olas.length} olas`;
      const btnReal = document.getElementById('btn-real');
      btnReal.style.opacity      = '1';
      btnReal.style.pointerEvents = 'auto';
      setMode('real');
    } catch (err) {
      const st = document.getElementById('load-status');
      st.className   = 'load-status err';
      st.textContent = 'Error al leer la planilla: ' + err.message;
      console.error(err);
    }
  };
  reader.readAsArrayBuffer(file);
}

// ── Modo y escenario ──────────────────────────────────────────────────────────
function setMode(m) {
  if (m === 'real' && !planillaData) return;
  mode = m;
  document.getElementById('btn-sim').className  = 'mode-btn' + (m === 'sim'  ? ' active' : '');
  document.getElementById('btn-real').className = 'mode-btn' + (m === 'real' ? ' active' : '');
  document.getElementById('sim-bar').style.display  = m === 'sim'  ? 'flex' : 'none';
  document.getElementById('prog-bar').style.display = m === 'real' ? 'flex' : 'none';
  const badge = document.getElementById('mode-badge');
  if (badge) {
    if (m === 'real') { badge.className = 'badge b-real'; badge.textContent = 'DATOS REALES'; }
    else              { badge.className = 'badge b-sim';  badge.textContent = 'SIMULACIÓN'; }
  }
  lastAiTick = -999;
  if (m === 'real') renderReal();
}

function setScenario(s, btn) {
  scenario = s;
  document.querySelectorAll('.sim-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  lastAiTick = -999;
}

// ── Calcular estado real ───────────────────────────────────────────────────────
function calcEstadoReal() {
  if (!planillaData) return null;
  const hora    = currentHour();
  const turno   = turnoActual(hora);
  const olaIdx  = olaActualIdx(hora);
  const olaDef  = OLA_DEF[olaIdx];

  const olasDelTurno   = planillaData.olas.filter(o => o.turno === turno);
  const olasCompletas  = olasDelTurno.filter(o => o.num < olaIdx + 1);
  const olaActualData  = planillaData.olas[olaIdx];

  let fracOla = 0;
  if (olaDef.ini < olaDef.fin) {
    fracOla = (hora - olaDef.ini) / (olaDef.fin - olaDef.ini);
  } else {
    const horaAdj = hora >= olaDef.ini ? hora - olaDef.ini : hora + (24 - olaDef.ini);
    fracOla = horaAdj / 2;
  }
  fracOla = Math.min(Math.max(fracOla, 0), 1);

  const bultosSecosCom = olasCompletas.reduce((a, o) => a + o.ejecSecos, 0);
  const bultosNOACom   = olasCompletas.reduce((a, o) => a + o.ejecNOA,   0);
  const parcialSecos   = olaActualData.ejecSecos * fracOla * noise(1, 0.05);
  const parcialNOA     = olaActualData.ejecNOA   * fracOla * noise(1, 0.05);
  const totalSecos     = bultosSecosCom + parcialSecos;
  const totalNOA       = bultosNOACom   + parcialNOA;
  const totalReal      = totalSecos + totalNOA;

  const objOlasCompletas = olasCompletas.reduce((a, o) => a + o.progTotal, 0);
  const objParcialOlaAct = olaActualData.progTotal * fracOla;
  const objetivoAcum     = objOlasCompletas + objParcialOlaAct;

  const objTurno         = planillaData.turnos[turno].progTotal;
  const olasRestantes    = olasDelTurno.filter(o => o.num > olaIdx + 1);
  const ritmoBultosHora  = olaActualData.ejecTotal > 0
    ? (olaActualData.ejecTotal * noise(1, 0.05)) / 2
    : 0;
  const proyeccion = totalReal + olasRestantes.reduce((a, o) => a + o.progTotal * noise(1, 0.08), 0);
  const dotacion   = olaActualData.dotEjec > 0 ? olaActualData.dotEjec : 20;
  const prodReal   = olaActualData.prodEjec > 0 ? olaActualData.prodEjec : 220;

  return {
    turno, olaIdx, olaActual: olaActualData, fracOla,
    totalSecos, totalNOA, totalReal, objetivoAcum, objTurno,
    gap: totalReal - objetivoAcum, proyeccion, ritmoBultosHora,
    olasRestantes: olasRestantes.length, olasRestantesArr: olasRestantes,
    dotacion, prodReal, hora, programa: planillaData.programa,
  };
}

// ── Render modo REAL ──────────────────────────────────────────────────────────
function renderReal() {
  if (!planillaData) return;
  const st = calcEstadoReal();
  if (!st) return;

  // Prog bar
  document.getElementById('prog-num').textContent      = st.programa;
  document.getElementById('prog-turno').textContent    = st.turno;
  document.getElementById('prog-total').textContent    = fmt(st.objTurno) + ' bultos';
  document.getElementById('prog-dotacion').textContent = st.dotacion + ' operarios';
  document.getElementById('ola-badge-wrap').innerHTML  =
    `<span class="ola-badge">● ${OLA_DEF[st.olaIdx].label} en curso</span>`;

  // KPIs
  document.getElementById('kpi-real').textContent     = fmt(st.totalReal);
  document.getElementById('kpi-real-sub').textContent = `turno ${st.turno}`;
  document.getElementById('kpi-exp').textContent      = fmt(st.objetivoAcum);

  const gEl  = document.getElementById('kpi-gap');
  const gSub = document.getElementById('kpi-gap-sub');
  gEl.textContent  = (st.gap >= 0 ? '+' : '') + fmt(st.gap);
  gEl.style.color  = st.gap >= 0 ? 'var(--accent)' : 'var(--accent2)';
  gSub.className   = 'kpi-sub ' + (st.gap >= 0 ? 'good' : 'bad');
  gSub.textContent = st.gap >= 0 ? 'por encima del objetivo' : 'por debajo del objetivo';

  document.getElementById('kpi-proj').textContent = fmt(st.proyeccion);
  const ps   = document.getElementById('kpi-proj-sub');
  const diff = st.proyeccion - st.objTurno;
  ps.className   = 'kpi-sub ' + (diff >= 0 ? 'good' : diff >= -st.objTurno * 0.05 ? 'warn' : 'bad');
  ps.textContent = diff >= 0
    ? `✓ +${fmt(diff)} sobre objetivo`
    : `⚠ déficit est. ${fmt(Math.abs(diff))} bultos`;

  // Proyección panel
  renderProyeccion({
    rate:     st.ritmoBultosHora,
    olasLabel:`${st.olasRestantes} olas`,
    total:    st.proyeccion,
    objTotal: st.objTurno,
  });

  renderBarrasReal(st);
  renderOlasReal(st);
  renderOperariosReal(st);

  if (tick - lastAiTick >= 30) {
    lastAiTick = tick;
    runAiAnalysis(
      AI_SYSTEM_PROMPT,
      buildContextReal(st),
      alerts => { aiAlerts = alerts; renderAiAlerts(aiAlerts, 'ai-alerts'); },
      () => runLocalAlerts(),
    );
  }
}

function renderBarrasReal(st) {
  const turno       = st.turno;
  const olasDelTurno = planillaData.olas.filter(o => o.turno === turno);
  const olasComp    = olasDelTurno.filter(o => o.num < st.olaIdx + 1).length;
  const sectores = [
    {
      name: 'Secos', actual: st.totalSecos, color: '#00e5a0',
      objTurno: planillaData.turnos[turno].progTotal * 0.87,
      objetivo: planillaData.olas[st.olaIdx].progSecos * (st.fracOla + olasComp / 4),
    },
    {
      name: 'NOA', actual: st.totalNOA, color: '#00bcd4',
      objTurno: planillaData.turnos[turno].progTotal * 0.13,
      objetivo: planillaData.olas[st.olaIdx].progNOA * (st.fracOla + olasComp / 4),
    },
  ];
  renderBarras(sectores, 'bar-chart');
}

function renderOlasReal(st) {
  const el           = document.getElementById('olas-grid');
  const olasDelTurno = planillaData.olas.filter(o => o.turno === st.turno);
  el.innerHTML = '';
  olasDelTurno.forEach(ola => {
    const isPast    = ola.num < st.olaIdx + 1;
    const isCurrent = ola.num === st.olaIdx + 1;
    const isFuture  = ola.num > st.olaIdx + 1;
    const cls = isPast ? 'past' : isCurrent ? 'current' : 'future';
    let actualBultos, pAct, pExp, color;

    if (isPast) {
      actualBultos = ola.ejecTotal;
      pAct  = Math.min(ola.ejecTotal / ola.progTotal, 1.1);
      pExp  = 1;
      color = ola.ejecTotal >= ola.progTotal ? 'var(--accent)' : 'var(--accent2)';
    } else if (isCurrent) {
      actualBultos = ola.ejecTotal * st.fracOla;
      pAct  = Math.min(actualBultos / ola.progTotal, 1.05);
      pExp  = st.fracOla;
      color = 'var(--accent)';
    } else {
      actualBultos = null;
      pAct  = 0; pExp = 1; color = 'var(--muted)';
    }

    const ejecTxt = isPast
      ? `<span style="color:${color}">${fmt(actualBultos)}</span>`
      : isCurrent
        ? `<span style="color:var(--warn)">${fmt(actualBultos)} ...</span>`
        : `<span style="color:var(--muted)">${fmt(ola.progTotal)}</span>`;

    const finLabel = OLA_DEF[ola.num - 1].fin === 24 ? '00' : OLA_DEF[ola.num - 1].fin;
    el.innerHTML += `
      <div class="ola-row ${cls}">
        <div class="ola-name">${ola.label} · ${OLA_DEF[ola.num-1].ini}:00–${finLabel}:00</div>
        <div class="ola-bar-wrap">
          <div class="ola-bar-exp" style="width:${pExp*100}%"></div>
          <div class="ola-bar-act" style="width:${pAct*100}%;background:${color};opacity:.8"></div>
        </div>
        <div class="ola-prog">${fmt(ola.progTotal)}</div>
        <div class="ola-ejec">${ejecTxt}</div>
      </div>`;
  });
}

function renderOperariosReal(st) {
  const dotReal = st.olaActual.dotEjec || st.dotacion || 8;
  const n       = Math.min(Math.max(Math.round(dotReal), 1), 16);
  const prodStd = st.olaActual.prodEjec > 0 ? st.olaActual.prodEjec : 220;
  const nombres = ['García J.','Rodríguez M.','López K.','Martínez S.','Fernández R.',
                   'Díaz P.','Torres A.','Gómez C.','Núñez P.','Álvarez R.',
                   'Peralta D.','Sosa M.','Herrera F.','Romero G.','Castro L.','Medina T.'];
  const ops = Array.from({ length: n }, (_, i) => ({
    name: nombres[i] || 'Op ' + (i + 1),
    perf: Math.round(noise(prodStd, 0.15)),
    std:  prodStd,
  }));
  renderOperarios(ops, 'ops-grid');
}

// ── Render modo SIM ───────────────────────────────────────────────────────────
function renderSim() {
  const sc     = SIM_SCENARIOS[scenario];
  const hora   = 6 + simMinute / 60;
  const turno  = turnoActual(hora % 24);
  const oIdx   = olaActualIdx(hora % 24);
  const TARGET = 55000;
  const frac   = simMinute / 480;
  const totalReal = simZones.Secos + simZones.NOA;
  const objAcum   = TARGET * frac;
  const gap       = totalReal - objAcum;
  const rate      = (TARGET / 8) * sc.factor;
  const horasLeft = (1 - frac) * 8;
  const proj      = totalReal + rate * horasLeft;

  // KPIs
  document.getElementById('kpi-real').textContent     = fmt(totalReal);
  document.getElementById('kpi-real-sub').textContent = `turno ${turno}`;
  document.getElementById('kpi-exp').textContent      = fmt(objAcum);

  const gEl  = document.getElementById('kpi-gap');
  const gSub = document.getElementById('kpi-gap-sub');
  gEl.textContent  = (gap >= 0 ? '+' : '') + fmt(gap);
  gEl.style.color  = gap >= 0 ? 'var(--accent)' : 'var(--accent2)';
  gSub.className   = 'kpi-sub ' + (gap >= 0 ? 'good' : 'bad');
  gSub.textContent = gap >= 0 ? 'por encima del objetivo' : 'por debajo del objetivo';

  document.getElementById('kpi-proj').textContent = fmt(proj);
  const ps = document.getElementById('kpi-proj-sub');
  const d  = proj - TARGET;
  ps.className   = 'kpi-sub ' + (d >= 0 ? 'good' : d >= -TARGET * 0.05 ? 'warn' : 'bad');
  ps.textContent = d >= 0
    ? `✓ +${fmt(d)} sobre objetivo`
    : `⚠ déficit est. ${fmt(Math.abs(d))} bultos`;

  renderProyeccion({
    rate:     rate,
    olasLabel:`${4 - Math.floor(frac * 4)} olas`,
    total:    proj,
    objTotal: TARGET,
  });

  // Barras sim
  renderBarras([
    { name: 'Secos', actual: simZones.Secos, objetivo: TARGET * 0.87 * frac, objTurno: TARGET * 0.87, color: '#00e5a0' },
    { name: 'NOA',   actual: simZones.NOA,   objetivo: TARGET * 0.13 * frac, objTurno: TARGET * 0.13, color: '#00bcd4' },
  ], 'bar-chart');

  renderOlasSim(oIdx, frac);

  renderOperarios(
    simOps.map(o => ({ name: o.name, perf: o.perf, std: 110 })),
    'ops-grid'
  );

  if (tick - lastAiTick >= 30) {
    lastAiTick = tick;
    runAiAnalysis(
      AI_SYSTEM_PROMPT,
      buildContextSim(totalReal, objAcum, gap, proj, TARGET, rate, horasLeft),
      alerts => { aiAlerts = alerts; renderAiAlerts(aiAlerts, 'ai-alerts'); },
      () => runLocalAlerts(),
    );
  }
}

function renderOlasSim(oIdx, frac) {
  const el    = document.getElementById('olas-grid');
  const olasT = OLA_DEF.filter(o => o.turno === 'Mañana');
  const oIdxT = olasT.findIndex(o => o.num === oIdx + 1);
  el.innerHTML = '';
  olasT.forEach((o, i) => {
    const past = i < oIdxT, curr = i === oIdxT, fut = i > oIdxT;
    const cls  = past ? 'past' : curr ? 'current' : 'future';
    const prog = Math.round(55000 / 12);
    const ejec = past
      ? Math.round(noise(prog, 0.08))
      : curr ? Math.round(prog * (frac % 0.25) * 4 * noise(1, 0.06))
      : null;
    const col  = past ? (ejec >= prog ? 'var(--accent)' : 'var(--accent2)') : 'var(--accent)';
    el.innerHTML += `
      <div class="ola-row ${cls}">
        <div class="ola-name">${o.label} · ${o.ini}:00–${o.fin}:00</div>
        <div class="ola-bar-wrap">
          <div class="ola-bar-exp" style="width:100%"></div>
          <div class="ola-bar-act" style="width:${past?noise(90,0.1):curr?(frac%0.25)*400:0}%;background:${col};opacity:.8"></div>
        </div>
        <div class="ola-prog">${fmt(prog)}</div>
        <div class="ola-ejec">${ejec!=null
          ? `<span style="color:${col}">${fmt(ejec)}</span>`
          : `<span style="color:var(--muted)">${fmt(prog)}</span>`}</div>
      </div>`;
  });
}

// ── Contextos para IA ─────────────────────────────────────────────────────────
function buildContextReal(st) {
  const olasDelTurno = planillaData.olas.filter(o => o.turno === st.turno);
  const olasComp     = olasDelTurno.filter(o => o.num < st.olaIdx + 1);
  return `VIGIA · ESTADO OPERATIVO EN TIEMPO REAL
Programa N° ${st.programa} · CD Coto
Turno: ${st.turno} | Hora actual: ${Math.floor(st.hora)}:${String(Math.round((st.hora%1)*60)).padStart(2,'0')}
${OLA_DEF[st.olaIdx].label} en curso (${Math.round(st.fracOla*100)}% completada)

TOTALES DEL TURNO:
- Bultos preparados: ${fmt(st.totalReal)}
- Objetivo acumulado a esta hora: ${fmt(st.objetivoAcum)}
- Desvío: ${st.gap>=0?'+':''}${fmt(st.gap)} bultos
- Proyección de cierre: ${fmt(st.proyeccion)}
- Objetivo del turno: ${fmt(st.objTurno)}
- Olas restantes: ${st.olasRestantes}

SECTORES:
- Secos: ${fmt(st.totalSecos)} bultos preparados
- NOA: ${fmt(st.totalNOA)} bultos preparados

OLA EN CURSO (${OLA_DEF[st.olaIdx].label}):
- Programado: ${fmt(st.olaActual.progTotal)} bultos
- Ejecutado histórico completo: ${fmt(st.olaActual.ejecTotal)} bultos
- Avance estimado actual: ${fmt(st.olaActual.ejecTotal*st.fracOla)} bultos
- Dotación programada: ${st.olaActual.dotProg} operarios
- Dotación real: ${st.olaActual.dotEjec} operarios
- Productividad real histórica: ${Math.round(st.olaActual.prodEjec)} bultos/operario
${st.olaActual.obs ? '- Observación: '+st.olaActual.obs : ''}

OLAS COMPLETADAS EN ESTE TURNO: ${olasComp.length}
${olasComp.map(o=>`- ${o.label}: prog ${fmt(o.progTotal)} / ejec ${fmt(o.ejecTotal)} (${o.ejecTotal>=o.progTotal?'+'+fmt(o.ejecTotal-o.progTotal):fmt(o.ejecTotal-o.progTotal)})`).join('\n')}`;
}

function buildContextSim(real, exp, gap, proj, target, rate, horasLeft) {
  return `VIGIA · ESTADO OPERATIVO (MODO SIMULACIÓN)
Turno Mañana · CD Coto
Bultos preparados: ${fmt(real)} | Objetivo acumulado: ${fmt(exp)}
Desvío: ${gap>=0?'+':''}${fmt(gap)} | Proyección: ${fmt(proj)} / ${fmt(target)}
Ritmo: ${fmt(rate)} bultos/h | Horas restantes: ${horasLeft.toFixed(1)}
Secos: ${fmt(simZones.Secos)} | NOA: ${fmt(simZones.NOA)}`;
}

// ── Alertas locales fallback ──────────────────────────────────────────────────
function runLocalAlerts() {
  const alerts = [];
  if (mode === 'real' && planillaData) {
    const st = calcEstadoReal();
    if (!st) return;
    const { gap, proyeccion: proj, objTurno: obj } = st;
    if (gap < -500)
      alerts.push({ severity:'bad',  title:'Desvío crítico acumulado',      detail:`${fmt(Math.abs(gap))} bultos bajo el objetivo acumulado.`,     action:'Revisar dotación y redistribuir operarios entre sectores.',            time:nowStr(), source:'local' });
    else if (gap < -150)
      alerts.push({ severity:'warn', title:'Desvío en desarrollo',           detail:`${fmt(Math.abs(gap))} bultos bajo lo esperado a esta hora.`,    action:'Monitorear ritmo. Evaluar refuerzo si continúa la próxima ola.',       time:nowStr(), source:'local' });
    else
      alerts.push({ severity:'ok',   title:'Ritmo dentro del objetivo',      detail:`Desvío ${gap>=0?'+':''}${fmt(gap)} bultos. Operación estable.`, action:'Mantener ritmo actual.',                                               time:nowStr(), source:'local' });
    if (proj < obj * 0.93)
      alerts.push({ severity:'bad',  title:'Proyección de cierre en riesgo', detail:`Proyección: ${fmt(proj)} bultos. Déficit estimado: ${fmt(obj-proj)}.`, action:'Intervención necesaria. Evaluar extensión de turno o refuerzo.', time:nowStr(), source:'local' });
    else if (proj < obj)
      alerts.push({ severity:'warn', title:'Proyección ajustada al límite',  detail:`Proyección: ${fmt(proj)} / ${fmt(obj)}. Sin margen de caída.`,  action:'Mantener ritmo sin interrupciones.',                                    time:nowStr(), source:'local' });
    if (st.olaActual.dotEjec < st.olaActual.dotProg)
      alerts.push({ severity:'warn', title:'Dotación por debajo de lo programado', detail:`Programados: ${st.olaActual.dotProg} / Reales: ${st.olaActual.dotEjec} operarios.`, action:`Cubrir diferencia de ${st.olaActual.dotProg-st.olaActual.dotEjec} operarios si es posible.`, time:nowStr(), source:'local' });
  } else {
    alerts.push({ severity:'ok', title:'Simulación activa', detail:'Modo simulación sin datos reales cargados.', action:'Cargar planilla DatosModelo.xlsx para análisis con datos reales.', time:nowStr(), source:'local' });
  }
  aiAlerts = alerts;
  renderAiAlerts(aiAlerts, 'ai-alerts');
}

// ── Chat ──────────────────────────────────────────────────────────────────────
async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg   = input.value.trim();
  if (!msg) return;
  input.value = '';
  appendChat(msg, 'user');
  chatHistory.push({ role: 'user', content: msg });
  appendChat('...', 'ai', 'typing');

  const ctx = mode === 'real' && planillaData
    ? buildContextReal(calcEstadoReal())
    : 'Modo simulación activo.';
  const sysPrompt = `Sos un asistente operativo del CD Coto. Respondés preguntas del supervisor de turno sobre el estado del picking. Español, conciso, máx 3 oraciones. Solo usás datos del contexto.\n\nCONTEXTO:\n${ctx}`;

  await sendChatMessage(msg, sysPrompt, chatHistory, reply => {
    chatHistory.push({ role: 'assistant', content: reply });
    document.getElementById('typing')?.remove();
    appendChat(reply, 'ai');
  });
}

// ── Loop principal ────────────────────────────────────────────────────────────
function mainLoop() {
  tick++;
  if (mode === 'real' && planillaData) {
    renderReal();
  } else {
    const sc = SIM_SCENARIOS[scenario];
    simMinute += 2;
    if (simMinute > 480) { simMinute = 0; simZones = { Secos: 0, NOA: 0 }; }
    const perTick = (55000 * sc.factor * noise(1, sc.noise)) * (2 / 60);
    simZones.Secos += perTick * 0.87 * noise(1, sc.noise * 1.5);
    simZones.NOA   += perTick * 0.13 * noise(1, sc.noise * 1.5);
    simOps = SIM_OPS.map((n, i) => ({
      name: n,
      perf: Math.max(20, Math.round(noise(SIM_BASE[i] * sc.factor, sc.noise * 2))),
    }));
    renderSim();
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Deshabilitar botón real hasta que haya planilla
  const btnReal = document.getElementById('btn-real');
  if (btnReal) { btnReal.style.opacity = '.4'; btnReal.style.pointerEvents = 'none'; }

  runLocalAlerts();
  setInterval(mainLoop, 1000);
});
