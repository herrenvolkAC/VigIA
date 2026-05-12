/**
 * vigia-nav.js - Header dinámico y navegación entre procesos de VigIA
 */

const PROCESOS_NAV = [
  { id: 'picking', label: 'Picking', url: '/picking.html', activo: true },
  { id: 'gestion', label: 'Gestión Operativa', url: '/gestion-operativa.html', activo: true },
  { id: 'recepcion', label: 'Recepción', url: '/recepcion.html', activo: false },
  { id: 'reposicion', label: 'Reposición', url: '/reposicion.html', activo: false },
  { id: 'planificacion', label: 'Planificación', url: '/planificacion.html', activo: false },
];

function initHeader(proceso, opts) {
  const el = document.getElementById('vigia-header');
  if (!el) return;

  const session = getSession();
  const userName = session ? session.name : '—';
  const userRole = session ? session.role : '';

  opts = opts || {};

  const processLabel = proceso !== 'selector'
    ? `<span class="header-sep">·</span><span class="header-process-label">${proceso.toUpperCase()}</span>`
    : '';

  const navPills = PROCESOS_NAV.map(p => {
    const isCurrent = p.id === proceso;
    const isDisabled = !p.activo && !isCurrent;
    let cls = 'nav-pill';
    if (isCurrent) cls += ' active';
    if (isDisabled) cls += ' disabled';
    const tag = isDisabled
      ? `<span class="${cls}">${p.label}</span>`
      : `<a href="${p.url}" class="${cls}">${p.label}</a>`;
    return tag;
  }).join('');

  const clockHtml = opts.showClock !== false
    ? `<div class="clock">CD COTO | <span id="clock-time">--:--:--</span></div>`
    : '';

  const modeBadgeHtml = opts.showModeBadge
    ? `<div id="mode-badge" class="badge b-sim">Simulación</div>`
    : '';

  el.innerHTML = `
    <div class="header-inner">
      <a class="header-brand" href="/selector.html">
          <img class="header-brand-mark" src="/resources/APPLogo.png?v=20260416-102647" alt="Logo VigIA">
        <div class="header-brand-copy">
          <span class="header-brand-kicker">Gemelo operativo</span>
          <span class="header-logo">VigIA</span>
        </div>
      </a>
      ${processLabel}
      <div class="nav-pills">${navPills}</div>
      ${clockHtml}
      ${modeBadgeHtml}
      <div class="header-right">
        <span class="header-user"><strong>${userName}</strong> · ${userRole}</span>
        ${proceso !== 'selector' ? `<a href="/selector.html" class="btn-selector">← selector</a>` : ''}
        <button class="btn-logout" onclick="logout()">cerrar sesión</button>
      </div>
    </div>
  `;

  if (opts.showClock !== false) {
    setInterval(() => updateClock('clock-time'), 1000);
    updateClock('clock-time');
  }
}

function updateProviderBadge(provider) {
  const el = document.getElementById('provider-badge');
  if (!el) return;
  el.textContent = provider || 'IA ACTIVA';
}
