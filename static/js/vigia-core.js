/**
 * vigia-core.js — Lógica compartida de VigIA
 * Auth · Backend calls · IA · Alertas · Helpers
 */

// ── Auth ─────────────────────────────────────────────────────────────────────

const MOCK_USERS = [
  { user: 'supervisor', pass: '1234', role: 'supervisor', name: 'Supervisor Turno' },
  { user: 'jefe',       pass: '1234', role: 'jefe',       name: 'Jefe de Depósito' },
  { user: 'admin',      pass: '1234', role: 'admin',      name: 'Administrador'    },
];

function checkAuth() {
  const session = JSON.parse(sessionStorage.getItem('vigia_session') || 'null');
  if (!session) { window.location.href = '/login.html'; return null; }
  return session;
}

function getSession() {
  return JSON.parse(sessionStorage.getItem('vigia_session') || 'null');
}

function logout() {
  sessionStorage.removeItem('vigia_session');
  window.location.href = '/login.html';
}

// ── API key helpers ───────────────────────────────────────────────────────────

function getKey() {
  const el = document.getElementById('api-key');
  return el ? el.value.trim() : '';
}

function setApiStatus(text, cls) {
  const el = document.getElementById('api-status');
  if (!el) return;
  el.textContent = text;
  el.className = 'api-status ' + (cls || '');
}

function onApiKeyChange() {
  const k = getKey();
  if (!k) { setApiStatus('sin clave · análisis local', ''); return; }
  if (!k.startsWith('sk-ant-')) { setApiStatus('clave inválida', 'err'); return; }
  setApiStatus('clave ok · IA habilitada', 'ok');
  if (typeof lastAiTick !== 'undefined') lastAiTick = -999;
}

// ── Llamadas al backend ───────────────────────────────────────────────────────

async function callBackend(endpoint, body) {
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function loadProviders() {
  try {
    const res = await fetch('/api/providers');
    if (!res.ok) return [];
    const data = await res.json();
    return data.available || [];
  } catch { return []; }
}

// ── Llamada directa a Claude (browser) ───────────────────────────────────────

async function callClaude(system, user, history) {
  const key = getKey();
  if (!key || !key.startsWith('sk-ant-')) return null;
  const messages = history
    ? [...history, { role: 'user', content: user }]
    : [{ role: 'user', content: user }];
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-access': 'true',
    },
    body: JSON.stringify({ model: 'claude-sonnet-4-20250514', max_tokens: 1000, system, messages }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()).content?.[0]?.text || '';
}

// ── IA: análisis genérico ─────────────────────────────────────────────────────
// El caller pasa el system prompt (AI_SYSTEM_PROMPT) y el contexto string.
// aiAlerts y aiAnalyzing son variables del módulo del proceso.

async function runAiAnalysis(systemPrompt, context, onSuccess, onFallback) {
  const key = getKey();
  if (!key || !key.startsWith('sk-ant-')) {
    if (onFallback) onFallback(context);
    return;
  }
  setApiStatus('Analizando operación...', 'loading');
  try {
    const raw = await callClaude(systemPrompt, context, null);
    const parsed = JSON.parse(raw.replace(/```json|```/g, '').trim());
    const alerts = (parsed.alerts || []).map(a => ({ ...a, time: nowStr(), source: 'ia' }));
    setApiStatus('IA activa · análisis ok', 'ok');
    if (onSuccess) onSuccess(alerts);
  } catch (e) {
    console.error(e);
    setApiStatus('error IA · análisis local', 'err');
    if (onFallback) onFallback(context);
  }
}

// ── Chat genérico ─────────────────────────────────────────────────────────────

async function sendChatMessage(message, systemPrompt, history, onReply) {
  if (!getKey() || !getKey().startsWith('sk-ant-')) {
    if (onReply) onReply('Ingresá una API key válida para usar el asistente.');
    return;
  }
  try {
    const reply = await callClaude(systemPrompt, message, history.slice(0, -1));
    if (onReply) onReply(reply);
  } catch (e) {
    if (onReply) onReply('Error al consultar la IA.');
  }
}

// ── Render de alertas (genérico) ──────────────────────────────────────────────

function renderAiAlerts(alerts, containerId) {
  const el = document.getElementById(containerId || 'ai-alerts');
  if (!el) return;
  if (!alerts || !alerts.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--muted)">Sin alertas activas.</div>';
    return;
  }
  el.innerHTML = alerts.map(a => `
    <div class="ai-alert ${a.severity}">
      <div class="ai-tag">${a.source === 'ia' ? '✦ IA' : 'LOCAL'}</div>
      <strong>${a.title}</strong><br>${a.detail}
      ${a.action ? `<div class="alert-rec">→ ${a.action}</div>` : ''}
      <div class="alert-time">${a.time}</div>
    </div>
  `).join('');
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const rand  = (a, b) => a + Math.random() * (b - a);
const noise = (b, f) => b * (1 + rand(-f, f));
const fmt   = n => Math.round(n).toLocaleString('es');

function nowStr() {
  const n = new Date();
  return String(n.getHours()).padStart(2,'0') + ':' + String(n.getMinutes()).padStart(2,'0');
}

function updateClock(elementId) {
  const el = document.getElementById(elementId || 'clock-time');
  if (!el) return;
  const n = new Date();
  el.textContent =
    String(n.getHours()).padStart(2,'0') + ':' +
    String(n.getMinutes()).padStart(2,'0') + ':' +
    String(n.getSeconds()).padStart(2,'0');
}
