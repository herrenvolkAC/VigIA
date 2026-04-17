/**
 * vigia-ui.js — Componentes UI reutilizables de VigIA
 * KPIs · Barras · Operarios · Proyección · Chat
 */

// ── KPIs ──────────────────────────────────────────────────────────────────────
// kpis: [{ label, value, sub, subClass, color, id }]
// Si id está definido, actualiza los elementos existentes sin re-renderizar.
function renderKPIs(kpis) {
  kpis.forEach(k => {
    const valEl = document.getElementById(k.valueId || k.id + '-val');
    const subEl = document.getElementById(k.subId   || k.id + '-sub');
    if (valEl) {
      valEl.textContent = k.value;
      if (k.valueColor) valEl.style.color = k.valueColor;
    }
    if (subEl) {
      subEl.textContent  = k.sub;
      subEl.className    = 'kpi-sub ' + (k.subClass || '');
    }
  });
}

// ── Barras por sector ─────────────────────────────────────────────────────────
// sectores: [{ name, actual, objetivo, objTurno, color }]
function renderBarras(sectores, containerId) {
  const el = document.getElementById(containerId || 'bar-chart');
  if (!el) return;
  el.innerHTML = '';
  sectores.forEach(s => {
    const pAct = Math.min(s.actual / s.objTurno, 1.05);
    const pExp = Math.min(s.objetivo / s.objTurno, 1);
    const pct  = Math.round((s.actual / s.objTurno) * 100);
    const diff = s.actual - s.objetivo;
    const color = diff >= 0 ? s.color : 'var(--accent2)';
    el.innerHTML += `
      <div class="bar-row">
        <div class="bar-label">${s.name}</div>
        <div>
          <div class="bar-track">
            <div class="bar-expected" style="width:${pExp * 100}%"></div>
            <div class="bar-actual"   style="width:${pAct * 100}%;background:${color};opacity:.85"></div>
          </div>
          <div style="font-size:9px;color:var(--muted);margin-top:3px">
            ${fmt(s.actual)} / ${fmt(s.objTurno)} bultos
            &nbsp;<span style="color:${diff >= 0 ? 'var(--accent)' : 'var(--accent2)'}">
              ${diff >= 0 ? '+' : ''}${fmt(diff)}
            </span>
          </div>
        </div>
        <div class="bar-pct" style="color:${color}">${pct}%</div>
      </div>`;
  });
}

// ── Operarios ─────────────────────────────────────────────────────────────────
// ops: [{ name, perf, std, color? }]
function renderOperarios(ops, containerId) {
  const el = document.getElementById(containerId || 'ops-grid');
  if (!el) return;
  el.innerHTML = '';
  ops.forEach(o => {
    const std   = o.std || 110;
    const pct   = Math.round((o.perf / std) * 100);
    const color = o.color || (o.perf >= std * 0.95 ? 'var(--accent)' : o.perf >= std * 0.80 ? 'var(--warn)' : 'var(--accent2)');
    el.innerHTML += `
      <div class="op-card">
        <div class="op-name">${o.name}</div>
        <div class="op-stat" style="color:${color}">${o.perf} b/h</div>
        <div class="op-bar-track">
          <div class="op-bar-fill" style="width:${Math.min(pct,100)}%;background:${color}"></div>
        </div>
      </div>`;
  });
}

// ── Proyección ────────────────────────────────────────────────────────────────
// proj: { rate, olasLabel, total, gap, objTotal }
function renderProyeccion(proj) {
  const set = (id, val, color) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = val;
    if (color) el.style.color = color;
  };
  set('proj-rate',  `${fmt(proj.rate)} bultos/h`);
  set('proj-olas',  proj.olasLabel || '—');
  set('proj-total', fmt(proj.total) + ' bultos');
  const gp  = proj.objTotal - proj.total;
  const gpe = document.getElementById('proj-gap');
  if (gpe) {
    gpe.textContent = gp <= 0
      ? `+${fmt(Math.abs(gp))} excedente`
      : `${fmt(gp)} faltantes`;
    gpe.style.color = gp <= 0 ? 'var(--accent)' : 'var(--accent2)';
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────────

function toggleChat() {
  const b = document.getElementById('chat-body');
  if (!b) return;
  b.className = b.className.includes('open') ? 'chat-body' : 'chat-body open';
}

function appendChat(text, role, id) {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  const d = document.createElement('div');
  d.className = 'chat-msg ' + role;
  d.textContent = text;
  if (id) d.id = id;
  el.appendChild(d);
  el.scrollTop = el.scrollHeight;
}
