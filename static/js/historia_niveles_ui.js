(function (root) {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const fmt = value => value == null ? '—' : Number(value).toLocaleString('es-AR', {maximumFractionDigits: 2});
  const monthName = month => new Date(month + '-01T12:00:00').toLocaleDateString('es-AR', {month: 'short', year: '2-digit'});
  const palette = ['#1f7a4d', '#0b5fae', '#b05d13', '#8848ac', '#00838b', '#b53e66', '#6c7429', '#4759a8'];
  let model = {series: [], months: []}, selected = new Set(), onSelect = () => {}, selectedPoint = null;

  function pointLabel(series, point) {
    const index = series.points.indexOf(point), prior = series.points[index - 1];
    const delta = prior?.value != null && point.value != null ? point.value - prior.value : null;
    return `${series.label} · ${monthName(point.month)} · Nivel medio ${fmt(point.value)} · ${point.n} jornadas evaluadas`
      + (delta == null ? '' : ` · Variación mensual ${delta > 0 ? '+' : ''}${fmt(delta)}`)
      + (point.n > 0 && point.n < 5 ? ' · Pocas jornadas' : '') + (point.partial ? ' · Mes parcial' : '')
      + (point.excluded.length ? ` · ${point.excluded.length} jornadas excluidas` : '')
      + (point.changes.length ? ' · Cambio observado de umbral' : '');
  }

  function render() {
    $('monthly-legend').innerHTML = model.series.map((s, i) => `<label class="monthly-choice ${!s.count ? 'unavailable' : ''}">
      <input type="checkbox" data-line="${i}" ${selected.has(s.key) ? 'checked' : ''} ${!s.count ? 'disabled' : ''}>
      <i style="background:${s.color}"></i><span>${esc(s.label)}<small>${s.count ? `${s.count} jornadas evaluables` : esc(s.scale.reason || 'Sin jornadas interpretables')}</small></span></label>`).join('') || '<p>Sin operaciones registradas en el período.</p>';
    $('monthly-legend').querySelectorAll('input').forEach(input => input.onchange = () => {
      const s = model.series[Number(input.dataset.line)];
      if (input.checked) selected.add(s.key); else selected.delete(s.key);
      renderChart();
      if (selectedPoint && !selected.has(selectedPoint.series.key)) {
        selectedPoint = null; $('monthly-detail').hidden = true;
      }
    });
    $('monthly-method').innerHTML = model.series.map(s => `<details><summary>${esc(s.label)}</summary>
      <p>${s.scale.valid ? s.scale.order.map(r => `<span class="badge">Código ${esc(r.code)} → posición ${r.ordinal}</span>`).join(' ') : esc(s.scale.reason)}</p>
      <p class="hint">${s.points.reduce((n, p) => n + p.excluded.length, 0)} jornadas excluidas. ${s.scale.valid ? 'Orden de referencia por umbral ascendente; no equivale a reconstruir una escala histórica faltante.' : 'Esta operación no genera un índice.'}</p>${s.points.some(p => p.excluded.length) ? `<details><summary>Ver jornadas excluidas</summary>${s.points.flatMap(p => p.excluded).map(d => `<p class="hint">${esc(d.date)} · ${esc(d.reason)}</p>`).join('')}</details>` : ''}</details>`).join('');
    renderChart();
  }

  function renderChart() {
    const visible = model.series.filter(s => selected.has(s.key) && s.count);
    $('monthly-tooltip').textContent = 'Pasá sobre un punto o seleccionalo para ver las jornadas del mes.';
    if (!visible.length) {
      $('monthly-chart').innerHTML = '<div class="monthly-empty">Seleccioná al menos una operación con jornadas evaluables.</div>';
      return;
    }
    const width = Math.max(720, model.months.length * 90 + 100), height = 310, left = 55, right = width - 35, top = 25, bottom = 260;
    const max = Math.max(1, ...visible.map(s => s.scale.order.length));
    const x = i => model.months.length === 1 ? (left + right) / 2 : left + i * (right - left) / (model.months.length - 1);
    const y = v => bottom - v / max * (bottom - top);
    let svg = `<svg viewBox="0 0 ${width} ${height}" style="min-width:${width}px" aria-label="Nivel medio mensual por operación" role="group">`;
    for (let level = 0; level <= max; level += Math.max(1, Math.ceil(max / 10))) {
      svg += `<line x1="${left}" y1="${y(level)}" x2="${right}" y2="${y(level)}" class="monthly-grid"/><text x="${left - 12}" y="${y(level) + 4}" text-anchor="end">${level}</text>`;
    }
    model.months.forEach((m, i) => {svg += `<text x="${x(i)}" y="${bottom + 28}" text-anchor="middle">${esc(monthName(m))}</text>`;});
    visible.forEach(s => {
      let path = '', connected = false;
      s.points.forEach((p, i) => {
        if (p.value == null) {connected = false; return;}
        path += `${connected ? 'L' : 'M'}${x(i)},${y(p.value)} `; connected = true;
      });
      svg += `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="2.5"/>`;
    });
    // Draw interactive points after lines. White outlines distinguish overlaps;
    // the accessible table below provides access to every coincident point.
    visible.forEach(s => {
      const si = model.series.indexOf(s);
      s.points.forEach((p, i) => {
        if (p.value == null) return;
        if (p.changes.length) svg += `<circle cx="${x(i)}" cy="${y(p.value)}" r="10" fill="none" stroke="#c58719" stroke-width="2"/>`;
        svg += `<circle cx="${x(i)}" cy="${y(p.value)}" r="6" fill="${p.n < 5 ? '#fff' : s.color}" stroke="${s.color}" stroke-width="2"
          role="button" tabindex="0" data-series="${si}" data-point="${i}" aria-label="${esc(pointLabel(s, p))}"><title>${esc(pointLabel(s, p))}</title></circle>`;
      });
    });
    svg += '</svg>';
    const matrix = `<details class="monthly-matrix"><summary>Ver valores mensuales de todas las líneas</summary><div class="table-wrap"><table><thead><tr><th>Mes</th>${visible.map(s => `<th>${esc(s.label)}</th>`).join('')}</tr></thead><tbody>${model.months.map((m, i) => `<tr><td>${esc(monthName(m))}</td>${visible.map(s => {
      const p = s.points[i]; return `<td>${p.value == null ? `—${p.excluded.length ? ` (${p.excluded.length} excluidas)` : ''}` : `<button type="button" data-series="${model.series.indexOf(s)}" data-point="${i}" title="${esc(pointLabel(s, p))}">${fmt(p.value)} · ${p.n} días${p.partial ? ' · parcial' : ''}</button>`}</td>`;
    }).join('')}</tr>`).join('')}</tbody></table></div></details>`;
    $('monthly-chart').innerHTML = `<div class="monthly-svg-wrap">${svg}</div>${matrix}`;
    $('monthly-chart').querySelectorAll('[data-point]').forEach(el => {
      const s = model.series[Number(el.dataset.series)], p = s.points[Number(el.dataset.point)];
      const show = () => {$('monthly-tooltip').textContent = pointLabel(s, p);};
      el.onmouseenter = show; el.onfocus = show;
      el.onclick = () => {show(); showDetail(s, p); onSelect(s.key, p.month);};
      if (el.tagName.toLowerCase() === 'circle') el.onkeydown = e => {
        if (e.key === 'Enter' || e.key === ' ') {e.preventDefault(); el.onclick();}
      };
    });
  }

  function showDetail(series, point) {
    selectedPoint = {series, point};
    const box = $('monthly-detail'); box.hidden = false;
    box.innerHTML = `<h3>${esc(series.label)} · ${esc(monthName(point.month))}</h3><p class="monthly-tooltip">${esc(pointLabel(series, point))}</p>
      <div class="table-wrap"><table><thead><tr><th>Jornada</th><th>Código(s) registrado(s)</th><th>Valor diario del índice</th><th>Criterio</th></tr></thead><tbody>${point.days.map(d => `<tr><td><button type="button" data-monthly-day="${esc(d.date)}">${esc(d.date)}</button></td><td>${esc([...new Set(d.records.map(r => r.code))].join(' / '))}</td><td>${fmt(d.value)}</td><td>${d.weighted ? 'Ponderado por tiempo computado' : 'Un nivel en la jornada'}</td></tr>`).join('')}</tbody></table></div>
      ${point.excluded.length ? `<details><summary>Jornadas excluidas (${point.excluded.length})</summary>${point.excluded.map(d => `<p>${esc(d.date)} · ${esc(d.reason)}</p>`).join('')}</details>` : ''}
      ${point.changes.length ? `<details open><summary>Cambios observados de umbral</summary>${point.changes.map(c => `<p>${esc(c.date)} · Código ${esc(c.code)} · ${fmt(c.before)} → ${fmt(c.after)}</p>`).join('')}<p class="hint">Los cambios se detectan comparando el mismo código entre liquidaciones disponibles. No implican una fecha exacta de vigencia.</p></details>` : ''}`;
    box.querySelectorAll('[data-monthly-day]').forEach(button => button.onclick = () => onSelect(series.key, point.month, button.dataset.monthlyDay));
  }

  root.HistoriaNivelesUI = {load(data, callback) {
    model = root.HistoriaNiveles.build(data); onSelect = callback; selectedPoint = null;
    model.series.forEach(s => {
      const hash = [...s.key].reduce((n, c) => (n * 31 + c.charCodeAt(0)) >>> 0, 0);
      s.color = palette[hash % palette.length];
    });
    selected = new Set(model.series.filter(s => s.count).map(s => s.key));
    $('monthly-detail').hidden = true;
    $('monthly-all').onclick = () => {selected = new Set(model.series.filter(s => s.count).map(s => s.key)); render();};
    $('monthly-none').onclick = () => {selected.clear(); selectedPoint = null; $('monthly-detail').hidden = true; render();};
    render();
  }};
})(window);
