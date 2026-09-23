/* Cálculo puro del índice mensual. No realiza consultas ni persiste datos. */
(function (root) {
  'use strict';
  const number = value => value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
  const iso = value => {
    const text = String(value);
    return text.includes('-') ? text.slice(0, 10) : `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
  };
  const key = row => [row.ID_PV_GRUPO_DE_FUNCIONES, row.ID_PV_GRUPO_PRODUCTIVO ?? '', row.ID_PV_UNIDAD_DE_PRODUCCION ?? ''].join('|');

  function scaleOrder(scales) {
    const codes = new Map();
    for (const row of scales) {
      const code = number(row.NIVEL), lower = number(row.DESDE);
      if (code == null || lower == null) continue;
      if (!codes.has(code)) codes.set(code, []);
      codes.get(code).push(lower);
    }
    const order = [...codes].map(([code, thresholds]) => ({code, min: Math.min(...thresholds), max: Math.max(...thresholds)}))
      .sort((a, b) => a.min - b.min);
    // A single fixed payment tier is not a performance scale. If historical
    // thresholds overlap, a stable ordinal cannot be established safely.
    if (order.length < 2) return {valid: false, reason: 'Sin escala de varios niveles', order: []};
    if (order.some((row, i) => i > 0 && order[i - 1].max >= row.min)) {
      return {valid: false, reason: 'Orden de niveles ambiguo entre escalas', order: []};
    }
    return {valid: true, order: order.map((row, i) => ({...row, ordinal: i + 1})), reason: ''};
  }

  function monthsBetween(start, end) {
    const result = [], cursor = new Date(start.slice(0, 7) + '-01T12:00:00');
    const last = end.slice(0, 7);
    while (true) {
      const month = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, '0')}`;
      if (month > last) break;
      result.push(month);
      cursor.setMonth(cursor.getMonth() + 1);
    }
    return result;
  }

  function build(data) {
    const months = monthsBetween(data.desde, data.hasta), series = new Map();
    const absent = new Set((data.dias || []).filter(r => ['SI', 'S', '1'].includes(String(r.AUSENTE).toUpperCase())).map(r => String(r.ID)));
    const seen = new Set();
    for (const row of data.pagos || []) {
      if (row.ID != null && seen.has(String(row.ID))) continue;
      if (row.ID != null) seen.add(String(row.ID));
      const k = key(row);
      if (!series.has(k)) {
        const scales = (data.escalas || []).filter(s => String(s.ID_DE_GRUPO_DE_FUNCIONES) === String(row.ID_PV_GRUPO_DE_FUNCIONES)
          && String(s.ID_DE_GRUPO_PRODUCTIVO ?? '') === String(row.ID_PV_GRUPO_PRODUCTIVO ?? ''));
        series.set(k, {key: k, name: row.OPERACION || 'Sin operación',
          label: `${row.OPERACION || 'Sin operación'} · ${row.GRUPO_PRODUCTIVO || 'General'} · ${row.ID_PV_UNIDAD_DE_PRODUCCION || 'Sin unidad'}`,
          scale: scaleOrder(scales), byDay: new Map()});
      }
      const item = series.get(k), date = iso(row.FECHA);
      if (date < data.desde || date > data.hasta) continue;
      if (!item.byDay.has(date)) item.byDay.set(date, []);
      item.byDay.get(date).push(row);
    }
    const output = [];
    for (const item of series.values()) {
      const ordinals = new Map(item.scale.order.map(s => [s.code, s.ordinal]));
      const bucket = new Map(months.map(month => [month, {month, value: null, days: [], excluded: [], changes: []}]));
      const thresholds = new Map();
      for (const [date, rows] of [...item.byDay].sort((a, b) => a[0].localeCompare(b[0]))) {
        const month = bucket.get(date.slice(0, 7));
        let reason = item.scale.reason;
        const records = [];
        for (const row of rows) {
          if (absent.has(String(row.ID_PV_DIA_LABORAL))) {reason = 'Ausencia registrada'; break;}
          const code = number(row.OBJETIVO_NIVEL_ALCANZADO);
          let ordinal = ordinals.get(code);
          // Zero means below the first threshold only with positive productive
          // evidence, a NO access flag and an explicit comparable projection.
          if (ordinal == null && code === 0 && item.scale.valid && item.scale.order[0].min > 0
              && String(row.ACCEDE_AL_PREMIO).toUpperCase() === 'NO'
              && number(row.OBJETIVO_PRODUCCION_8HS) != null && row.OBJETIVO_PRODUCCION_8HS < item.scale.order[0].min
              && (number(row.PRODUCCION_TOTAL) || 0) > 0) ordinal = 0;
          if (ordinal == null) {reason = reason || 'Nivel sin correspondencia verificable'; break;}
          const time = number(row.TIEMPO_DURANTE_PH_EN_SEGUNDOS);
          records.push({ordinal, code, seconds: time != null && time > 0 ? time : null});
          const threshold = number(row.OBJETIVO_UMBRAL_PARA_8HS);
          if (threshold != null) {
            if (thresholds.has(code) && thresholds.get(code) !== threshold) {
              month.changes.push({date, code, before: thresholds.get(code), after: threshold});
            }
            thresholds.set(code, threshold);
          }
        }
        if (reason) {month.excluded.push({date, reason}); continue;}
        const same = new Set(records.map(r => r.ordinal)).size === 1;
        if (!same && records.some(r => r.seconds == null)) {
          month.excluded.push({date, reason: 'Varios niveles sin tiempos comparables'}); continue;
        }
        const seconds = records.reduce((s, r) => s + (r.seconds || 0), 0);
        const value = same ? records[0].ordinal : records.reduce((s, r) => s + r.ordinal * r.seconds, 0) / seconds;
        month.days.push({date, value, records, weighted: !same});
      }
      const points = [...bucket.values()];
      for (const point of points) {
        point.n = point.days.length;
        if (point.n) point.value = point.days.reduce((s, d) => s + d.value, 0) / point.n;
        point.partial = point.month === data.desde.slice(0, 7) && !data.desde.endsWith('-01');
        const end = new Date(data.hasta + 'T12:00:00'), lastDay = new Date(end.getFullYear(), end.getMonth() + 1, 0).getDate();
        point.partial ||= point.month === data.hasta.slice(0, 7) && end.getDate() !== lastDay;
      }
      output.push({key: item.key, name: item.name, label: item.label, scale: item.scale, points,
        count: points.reduce((n, p) => n + p.n, 0)});
    }
    return {months, series: output.sort((a, b) => a.label.localeCompare(b.label))};
  }
  const api = {build, scaleOrder, monthsBetween};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.HistoriaNiveles = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
