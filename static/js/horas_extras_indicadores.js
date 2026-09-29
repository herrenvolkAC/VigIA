(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const fmt = value => Number(value || 0).toLocaleString('es-AR', {maximumFractionDigits:1});
  const amount = value => Math.max(0, Number(value) || 0);
  function duration(value) {
    const numeric = Number(value);
    const minutes = Number.isFinite(numeric) ? Math.round(Math.max(0,numeric)*60) : 0;
    return `${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`;
  }
  const finalStates = new Set(['aprobada_gerente','ajuste_aprobado','cargada_sap']);
  function aggregate(rows) {
    const result = {total:0, approved:0, pending:0, denied:0, days:new Map(), sectors:new Map(), people:new Map(), stages:[[],[],[]]};
    for(const r of rows) {
      const h = amount(r.horas_extras_detectadas);
      const authorized = Math.min(h, amount(r.horas_autorizadas));
      const closed = finalStates.has(r.estado);
      const rejected = String(r.estado).startsWith('rechazada');
      const approved = closed ? authorized : 0;
      const pending = closed || rejected ? 0 : h;
      result.total += h; result.approved += approved; result.pending += pending;
      result.denied += closed ? h - approved : rejected ? h : 0;
      const date = String(r.fecha).slice(0,10);
      result.days.set(date, (result.days.get(date) || 0) + h);
      const sector = r.sector || 'Sin sector';
      const s = result.sectors.get(sector) || {name:sector,total:0,approved:0};
      s.total += h; s.approved += approved; result.sectors.set(sector,s);
      const key = String(r.legajo);
      const p = result.people.get(key) || {name:r.empleado || key,legajo:key,total:0};
      p.total += h; result.people.set(key,p);
      if(pending) result.stages[r.estado === 'detectada' ? 0 : r.estado === 'pre_autorizada' ? 1 : 2].push({h,date});
    }
    return result;
  }
  function daysBetween(from,to) {
    const days = [];
    for(let date = new Date(from+'T00:00:00Z'), end = new Date(to+'T00:00:00Z'); date <= end; date.setUTCDate(date.getUTCDate()+1)) days.push(date.toISOString().slice(0,10));
    return days;
  }
  function render(rows, params, selectedState) {
    const a = aggregate(rows);
    const days = daysBetween(params.get('desde'),params.get('hasta'));
    const maxDay = Math.max(1,...a.days.values());
    const pct = a.total ? a.approved/a.total*100 : 0;
    const pendPct = a.total ? a.pending/a.total*100 : 0;
    const sectorRows = [...a.sectors.values()].sort((x,y)=>y.total-x.total);
    const maxSector = Math.max(1,...sectorRows.map(s=>s.total));
    const people = [...a.people.values()].sort((x,y)=>y.total-x.total);
    const bins = [{label:'Hasta 02:00',count:0},{label:'02:00 a 05:00',count:0},{label:'05:00 a 10:00',count:0},{label:'Mas de 10:00',count:0}];
    people.forEach(p=>bins[p.total<=2?0:p.total<=5?1:p.total<=10?2:3].count++);
    const maxBin = Math.max(1,...bins.map(b=>b.count));
    const points = days.map((d,i)=>`${days.length===1?500:20+i/(days.length-1)*960},${170-(a.days.get(d)||0)/maxDay*145}`);
    const context = [params.get('sector') || 'Todos los sectores',...params.getAll('funcion'),selectedState || 'Todos los estados'].join(' / ');
    const empty = '<p class="insight-empty">Sin registros para esta consulta.</p>';
    document.getElementById('indicadores-panel').innerHTML = `
      <header class="insight-header"><div><span class="insight-label">Horas extras / Indicadores</span><h3>${esc(params.get('desde'))} al ${esc(params.get('hasta'))}</h3><p>${esc(context)}</p></div><div class="insight-stamp">Ultima consulta<strong>${esc(new Date().toLocaleString('es-AR'))}</strong></div></header>
      <p id="insight-stale" class="insight-stale" role="status" hidden>Filtros modificados. Presione Consultar para actualizar.</p>
      <div class="insight-pulse"><div class="insight-total"><span>Horas realizadas</span><strong>${duration(a.total)}</strong><span>${rows.length} registros</span></div><div><span>Personas</span><strong>${fmt(a.people.size)}</strong><span>con horas extras</span></div><div><span>Promedio por persona</span><strong>${duration(a.people.size?a.total/a.people.size:0)}</strong><span>acumuladas en el periodo</span></div><div><span>Pendientes de decision</span><strong class="pending-number">${duration(a.pending)}</strong><span>${a.stages.reduce((n,s)=>n+s.length,0)} registros</span></div></div>
      ${!rows.length?empty:`<div class="insight-grid">
        <section class="insight-trend"><header><h3>Evolucion diaria</h3><span>Maximo ${duration(Math.max(...a.days.values()))} / dia</span></header><svg class="insight-line" viewBox="0 0 1000 195" role="img" aria-label="Horas extras por dia"><path d="M20 170H980 M20 97H980 M20 25H980" class="chart-guides"/><polyline points="${points.join(' ')}" class="chart-line"/>${days.map((d,i)=>`<circle cx="${points[i].split(',')[0]}" cy="${points[i].split(',')[1]}" r="4" tabindex="0"><title>${esc(d)}: ${duration(a.days.get(d))}</title></circle>`).join('')}</svg><div class="axis-labels"><span>${esc(days[0])}</span><span>${esc(days[days.length-1])}</span></div></section>
        <section><header><h3>Nivel de aprobacion</h3></header><div class="approval-layout"><div class="approval-ring" role="img" aria-label="${fmt(pct)} por ciento aprobado" style="--approved:${pct}%;--pending:${pct+pendPct}%"><div><strong>${fmt(pct)}%</strong><span>aprobado</span></div></div><ul class="insight-legend">${[['approved','Aprobadas',a.approved],['pending','Pendientes',a.pending],['denied','No autorizadas',a.denied]].map(([c,l,h])=>`<li><i class="${c}"></i><span>${l}</span><strong>${duration(h)}</strong></li>`).join('')}</ul></div></section>
        <section><header><h3>Horas por sector</h3><span>Realizadas / aprobadas</span></header><div class="sector-bars">${sectorRows.map(s=>`<div class="sector-bar" tabindex="0" title="${esc(s.name)}: ${duration(s.total)} realizadas, ${duration(s.approved)} aprobadas"><div><span>${esc(s.name)}</span><strong>${duration(s.total)} / ${duration(s.approved)}</strong></div><div class="bar-track"><span style="width:${s.total/maxSector*100}%"></span><b style="width:${s.approved/maxSector*100}%"></b></div></div>`).join('')}</div></section>
        <section><header><h3>Actividad del periodo</h3><span>Intensidad diaria</span></header><div class="heat-calendar">${days.map((d,i)=>`${i===0||d.endsWith('-01')?`<strong class="heat-month">${esc(new Date(d+'T00:00:00Z').toLocaleDateString('es-AR',{month:'long',year:'numeric',timeZone:'UTC'}))}</strong>`:''}<span tabindex="0" class="heat-day" style="--heat:${(a.days.get(d)||0)/maxDay}" title="${esc(d)}: ${duration(a.days.get(d))}" aria-label="${esc(d)}: ${duration(a.days.get(d))}">${Number(d.slice(-2))}</span>`).join('')}</div><div class="heat-key">Menor <span></span> Mayor</div></section>
        <section class="insight-circuit"><header><h3>Circuito pendiente</h3><span>${a.pending?'Por etapa':'Circuito al dia'}</span></header><div class="pending-stages">${a.stages.map((s,i)=>`<div><span class="stage-index">0${i+1}</span><h4>${['Jefatura','Gerencia','Ajustes / seguimiento'][i]}</h4><strong>${duration(s.reduce((n,r)=>n+r.h,0))}</strong><span>${s.length} registros</span><small>${s.length?`Fecha de actividad mas antigua: ${esc(s.map(r=>r.date).sort()[0])}`:'Sin pendientes'}</small></div>`).join('')}</div></section>
        <section><header><h3>Distribucion por persona</h3><span>Horas acumuladas</span></header><div class="distribution">${bins.map(b=>`<div><strong>${b.count}</strong><div><span style="height:${b.count/maxBin*100}%"></span></div><small>${b.label}</small></div>`).join('')}</div></section>
        <section><header><h3>Mayor acumulacion</h3><span>Primeras 10 personas</span></header><ol class="people-ranking">${people.slice(0,10).map(p=>`<li><div><strong>${esc(p.name)}</strong><small>Legajo ${esc(p.legajo)}</small></div><b>${duration(p.total)}</b></li>`).join('')}</ol></section>
      </div>`}`;
  }
  window.HEIndicators = {
    duration,
    aggregate,
    capture(rows,params,selectedState) {render(rows.filter(r=>!selectedState||r.estado===selectedState),params,selectedState);},
    markFilters() {const notice=document.getElementById('insight-stale');if(notice)notice.hidden=false;}
  };
})();
