/* SATAT charts: small inline-SVG helpers shared by the dashboard and the
   reference pages. No library, no network: every chart renders offline. */

'use strict';

(function () {
  const NS = 'http://www.w3.org/2000/svg';

  function s(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
    if (parent) parent.appendChild(node);
    return node;
  }

  function h(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function fmt(v, digits) {
    const n = Number(v);
    if (!Number.isFinite(n)) return '-';
    if (digits !== undefined) return n.toFixed(digits);
    return Math.abs(n) >= 1000 ? n.toLocaleString('en-US') : String(Math.round(n * 100) / 100);
  }

  /* ---------------------------------------------------------- tooltip */

  let tipNode = null;
  function tip() {
    if (tipNode) return tipNode;
    tipNode = h('div', 'sc-tip');
    tipNode.hidden = true;
    document.body.appendChild(tipNode);
    const move = (e) => {
      const target = e.target.closest ? e.target.closest('[data-tip]') : null;
      if (!target) { tipNode.hidden = true; return; }
      tipNode.textContent = target.getAttribute('data-tip');
      tipNode.hidden = false;
      const pad = 12;
      const w = tipNode.offsetWidth, ht = tipNode.offsetHeight;
      let x = e.clientX + pad, y = e.clientY + pad;
      if (x + w > window.innerWidth - 6) x = e.clientX - w - pad;
      if (y + ht > window.innerHeight - 6) y = e.clientY - ht - pad;
      tipNode.style.transform = 'translate(' + Math.max(4, x) + 'px,' + Math.max(4, y) + 'px)';
    };
    document.addEventListener('pointermove', move, { passive: true });
    document.addEventListener('pointerdown', move, { passive: true });
    document.addEventListener('scroll', () => { tipNode.hidden = true; }, { passive: true, capture: true });
    return tipNode;
  }

  function tipped(node, text) {
    node.setAttribute('data-tip', text);
    tip();
    return node;
  }

  /* ---------------------------------------------------------- legend */

  function legend(items, opts) {
    const box = h('div', 'sc-legend' + (opts && opts.inline ? ' inline' : ''));
    items.forEach((it) => {
      const row = h('div', 'sc-legend-row');
      const sw = h('span', 'sc-swatch');
      sw.style.background = it.color;
      row.appendChild(sw);
      row.appendChild(h('span', 'sc-legend-label', it.label));
      if (it.value !== undefined) row.appendChild(h('span', 'sc-legend-value', fmt(it.value)));
      box.appendChild(row);
    });
    return box;
  }

  /* ---------------------------------------------------------- donut */

  function donut(host, items, opts) {
    const o = Object.assign({ size: 150, thickness: 20, center: null, sub: '' }, opts);
    const total = items.reduce((a, it) => a + (Number(it.value) || 0), 0);
    const wrap = h('div', 'sc-donut' + (o.size < 120 ? ' small' : ''));
    const svg = s('svg', { viewBox: '0 0 100 100', width: o.size, height: o.size, role: 'img',
      'aria-label': o.label || 'Donut chart' }, wrap);
    const r = 50 - o.thickness / 2 - 1;
    const c = 2 * Math.PI * r;
    s('circle', { cx: 50, cy: 50, r, fill: 'none', stroke: 'rgba(255,255,255,.06)',
      'stroke-width': o.thickness }, svg);

    let offset = 0;
    items.forEach((it) => {
      const v = Number(it.value) || 0;
      if (!v || !total) return;
      const len = (v / total) * c;
      const arc = s('circle', {
        cx: 50, cy: 50, r, fill: 'none', stroke: it.color, 'stroke-width': o.thickness,
        'stroke-dasharray': Math.max(0, len - 0.6) + ' ' + (c - len + 0.6),
        'stroke-dashoffset': -offset, transform: 'rotate(-90 50 50)', class: 'sc-arc'
      }, svg);
      tipped(arc, it.label + ': ' + fmt(v) + ' (' + (v / total * 100).toFixed(1) + '%)');
      offset += len;
    });

    const centre = h('div', 'sc-donut-centre');
    centre.appendChild(h('b', null, o.center === null ? fmt(total) : o.center));
    if (o.sub) centre.appendChild(h('span', null, o.sub));
    wrap.appendChild(centre);
    wrap.style.width = o.size + 'px';
    wrap.style.height = o.size + 'px';

    const out = h('div', 'sc-donut-wrap');
    out.appendChild(wrap);
    if (o.legend !== false) {
      out.appendChild(legend(items.filter((it) => Number(it.value) > 0)));
    }
    host.appendChild(out);
    return out;
  }

  /* ---------------------------------------------------------- ring */

  function ring(value, opts) {
    const o = Object.assign({ size: 44, color: '#e2892f', thickness: 5 }, opts);
    const v = Math.max(0, Math.min(1, Number(value) || 0));
    const svg = s('svg', { viewBox: '0 0 40 40', width: o.size, height: o.size, class: 'sc-ring',
      'aria-hidden': 'true' });
    const r = 20 - o.thickness / 2 - 0.5;
    const c = 2 * Math.PI * r;
    s('circle', { cx: 20, cy: 20, r, fill: 'none', stroke: 'rgba(255,255,255,.08)',
      'stroke-width': o.thickness }, svg);
    s('circle', { cx: 20, cy: 20, r, fill: 'none', stroke: o.color, 'stroke-width': o.thickness,
      'stroke-linecap': 'round', 'stroke-dasharray': (v * c) + ' ' + c,
      transform: 'rotate(-90 20 20)' }, svg);
    return svg;
  }

  /* ---------------------------------------------------------- gauge */

  function gauge(host, value, opts) {
    const o = Object.assign({ min: 0, max: 1, digits: 2, label: '', unit: '',
      stops: [[0, '#8a847a'], [0.35, '#cbb03c'], [0.55, '#e2892f'], [0.75, '#e05252']] }, opts);
    const v = Number(value);
    const t = Number.isFinite(v) ? Math.max(0, Math.min(1, (v - o.min) / (o.max - o.min))) : 0;
    const box = h('div', 'sc-gauge-box');
    const wrap = h('div', 'sc-gauge');
    box.appendChild(wrap);
    const svg = s('svg', { viewBox: '0 0 120 66', role: 'img', 'aria-label': o.label + ' ' + fmt(v, o.digits) }, wrap);

    const arc = (a0, a1) => {
      const p = (a) => [60 + 48 * Math.cos(Math.PI * (1 - a)), 62 - 48 * Math.sin(Math.PI * (1 - a))];
      const [x0, y0] = p(a0), [x1, y1] = p(a1);
      return 'M' + x0 + ' ' + y0 + ' A48 48 0 0 1 ' + x1 + ' ' + y1;
    };
    s('path', { d: arc(0, 1), stroke: 'rgba(255,255,255,.07)', 'stroke-width': 10, fill: 'none',
      'stroke-linecap': 'round' }, svg);
    o.stops.forEach(([from, color], i) => {
      const to = i + 1 < o.stops.length ? o.stops[i + 1][0] : 1;
      if (t <= from) return;
      s('path', { d: arc(from, Math.min(t, to)), stroke: color, 'stroke-width': 10, fill: 'none' }, svg);
    });
    // A tick on the arc marks the value; the number sits inside the bowl.
    const tip = [60 + 48 * Math.cos(Math.PI * (1 - t)), 62 - 48 * Math.sin(Math.PI * (1 - t))];
    s('circle', { cx: tip[0], cy: tip[1], r: 6.5, fill: '#f5efe6', stroke: 'rgba(0,0,0,.55)', 'stroke-width': 1.5 }, svg);

    const read = h('div', 'sc-gauge-read');
    read.appendChild(h('b', null, Number.isFinite(v) ? fmt(v, o.digits) : '-'));
    if (o.unit) read.appendChild(h('span', null, o.unit));
    wrap.appendChild(read);
    if (o.label) box.appendChild(h('div', 'sc-gauge-label', o.label));
    host.appendChild(box);
    return box;
  }

  /* ---------------------------------------------------------- meter */

  function meter(label, value, opts) {
    const o = Object.assign({ max: 1, digits: 2, color: '#e2892f', suffix: '' }, opts);
    const v = Number(value);
    const row = h('div', 'sc-meter');
    const top = h('div', 'sc-meter-top');
    top.appendChild(h('span', null, label));
    top.appendChild(h('b', null, Number.isFinite(v) ? fmt(v, o.digits) + o.suffix : 'n/a'));
    row.appendChild(top);
    const track = h('div', 'sc-meter-track');
    const fill = h('i');
    fill.style.width = (Number.isFinite(v) ? Math.max(0, Math.min(1, v / o.max)) * 100 : 0).toFixed(1) + '%';
    fill.style.background = o.color;
    track.appendChild(fill);
    row.appendChild(track);
    return row;
  }

  /* ---------------------------------------------------------- horizontal bars */

  function hbars(host, items, opts) {
    const o = Object.assign({ digits: undefined, unit: '', showShare: false }, opts);
    const max = o.max || Math.max(...items.map((it) => Number(it.value) || 0), 1);
    const total = items.reduce((a, it) => a + (Number(it.value) || 0), 0);
    const list = h('div', 'sc-hbars');
    items.forEach((it) => {
      const v = Number(it.value) || 0;
      const row = h('div', 'sc-hbar');
      row.appendChild(h('span', 'sc-hbar-label', it.label));
      const track = h('span', 'sc-hbar-track');
      const fill = h('i');
      fill.style.width = (v / max * 100).toFixed(1) + '%';
      fill.style.background = it.color || '#e2892f';
      track.appendChild(fill);
      row.appendChild(track);
      const val = h('span', 'sc-hbar-value', fmt(v, o.digits) + o.unit);
      row.appendChild(val);
      if (o.showShare) row.appendChild(h('span', 'sc-hbar-share', total ? (v / total * 100).toFixed(1) + '%' : '-'));
      tipped(row, it.tip || (it.label + ': ' + fmt(v, o.digits) + o.unit));
      list.appendChild(row);
    });
    host.appendChild(list);
    return list;
  }

  /* ---------------------------------------------------------- time axis */

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function monthTicks(dates) {
    const ticks = [];
    dates.forEach((d, i) => {
      if (i === 0 || d.slice(8, 10) === '01') {
        ticks.push({ i, label: MONTHS[Number(d.slice(5, 7)) - 1] + (i === 0 && d.slice(8, 10) !== '01' ? ' ' + Number(d.slice(8, 10)) : '') });
      }
    });
    if (dates.length <= 14) {
      return dates.map((d, i) => ({ i, label: d.slice(8, 10) + ' ' + MONTHS[Number(d.slice(5, 7)) - 1] }))
        .filter((_, i) => i % Math.ceil(dates.length / 7) === 0);
    }
    return ticks;
  }

  /* One bar per day across the whole window, quiet days included, so the
     spacing of activity is visible rather than implied. */
  function timeline(host, days, opts) {
    const o = Object.assign({ height: 90, value: (d) => d.value, color: () => '#e2892f',
      tip: (d) => d.date, label: 'Daily activity' }, opts);
    const n = days.length;
    const W = 600, H = o.height, top = 6, bottom = 18;
    const max = Math.max(...days.map((d) => Number(o.value(d)) || 0), 1e-9);
    const svg = s('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none',
      class: 'sc-timeline', role: 'img', 'aria-label': o.label });
    const step = W / Math.max(n, 1);
    const bw = Math.max(1, step * 0.72);

    s('line', { x1: 0, x2: W, y1: H - bottom + 0.5, y2: H - bottom + 0.5,
      stroke: 'rgba(255,255,255,.12)', 'stroke-width': 1 }, svg);

    days.forEach((d, i) => {
      const v = Number(o.value(d)) || 0;
      const x = i * step + (step - bw) / 2;
      if (v <= 0) {
        s('rect', { x, y: H - bottom - 1.5, width: bw, height: 1.5, fill: 'rgba(255,255,255,.10)' }, svg);
        const hit = s('rect', { x: i * step, y: top, width: step, height: H - bottom - top, fill: 'transparent' }, svg);
        tipped(hit, o.tip(d));
        return;
      }
      const hgt = Math.max(2.5, (v / max) * (H - top - bottom));
      const bar = s('rect', { x, y: H - bottom - hgt, width: bw, height: hgt, rx: Math.min(1.5, bw / 3),
        fill: o.color(d) }, svg);
      const hit = s('rect', { x: i * step, y: top, width: step, height: H - bottom - top, fill: 'transparent' }, svg);
      tipped(hit, o.tip(d));
      bar.setAttribute('class', 'sc-bar');
    });

    const axis = h('div', 'sc-axis');
    monthTicks(days.map((d) => d.date)).forEach((t) => {
      const lab = h('span', null, t.label);
      lab.style.left = ((t.i + 0.5) / Math.max(n, 1) * 100).toFixed(2) + '%';
      axis.appendChild(lab);
    });

    const box = h('div', 'sc-timeline-box');
    box.appendChild(svg);
    box.appendChild(axis);
    host.appendChild(box);
    return box;
  }

  /* Daily totals stacked by series (e.g. by classification). */
  function stacked(host, dates, series, opts) {
    const o = Object.assign({ height: 170, label: 'Daily detections' }, opts);
    const n = dates.length;
    const W = 900, H = o.height, bottom = 4;
    const totals = dates.map((_, i) => series.reduce((a, sr) => a + (sr.values[i] || 0), 0));
    const max = Math.max(...totals, 1);
    const svg = s('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none',
      class: 'sc-stacked', role: 'img', 'aria-label': o.label });
    const step = W / Math.max(n, 1);
    const bw = Math.max(1, step * 0.8);

    [0.25, 0.5, 0.75, 1].forEach((f) => {
      const y = H - bottom - f * (H - bottom - 4);
      s('line', { x1: 0, x2: W, y1: y, y2: y, stroke: 'rgba(255,255,255,.05)', 'stroke-width': 1 }, svg);
    });

    dates.forEach((date, i) => {
      let y = H - bottom;
      const parts = [];
      series.forEach((sr) => {
        const v = sr.values[i] || 0;
        if (!v) return;
        const hgt = (v / max) * (H - bottom - 4);
        y -= hgt;
        s('rect', { x: i * step + (step - bw) / 2, y, width: bw, height: Math.max(hgt, 0.5), fill: sr.color }, svg);
        parts.push(sr.label + ' ' + v);
      });
      const hit = s('rect', { x: i * step, y: 0, width: step, height: H, fill: 'transparent' }, svg);
      tipped(hit, date + ': ' + totals[i] + ' detections' + (parts.length ? ' | ' + parts.join(', ') : ''));
    });

    const axis = h('div', 'sc-axis');
    monthTicks(dates).forEach((t) => {
      const lab = h('span', null, t.label);
      lab.style.left = ((t.i + 0.5) / Math.max(n, 1) * 100).toFixed(2) + '%';
      axis.appendChild(lab);
    });

    const box = h('div', 'sc-timeline-box');
    const yscale = h('div', 'sc-yscale');
    yscale.appendChild(h('span', null, fmt(max)));
    yscale.appendChild(h('span', null, fmt(Math.round(max / 2))));
    yscale.appendChild(h('span', null, '0'));
    box.appendChild(yscale);
    box.appendChild(svg);
    box.appendChild(axis);
    host.appendChild(box);
    return box;
  }

  /* ---------------------------------------------------------- histogram */

  function histogram(host, counts, opts) {
    const o = Object.assign({ color: '#e2892f', height: 34, label: 'Distribution', edges: null }, opts);
    const W = 160, H = o.height;
    const max = Math.max(...counts, 1);
    const svg = s('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none', class: 'sc-hist',
      role: 'img', 'aria-label': o.label });
    const step = W / Math.max(counts.length, 1);
    counts.forEach((c, i) => {
      const hgt = c ? Math.max(1.5, (c / max) * (H - 2)) : 0;
      const bar = s('rect', { x: i * step + 0.6, y: H - hgt, width: Math.max(1, step - 1.2), height: hgt,
        fill: o.color, rx: 0.8 }, svg);
      if (o.edges) {
        tipped(bar, fmt(o.edges[i]) + ' to ' + fmt(o.edges[i + 1]) + ': ' + fmt(c) + ' rows');
      }
    });
    host.appendChild(svg);
    return svg;
  }

  /* ---------------------------------------------------------- dot map */

  /* Detections binned to a coarse grid and drawn at their coordinates. With
     enough data the dots trace India's outline on their own. */
  function dotmap(host, cells, opts) {
    const o = Object.assign({ bounds: [6.5, 68, 36, 97.5], label: 'Thermal footprint' }, opts);
    const [latMin, lonMin, latMax, lonMax] = o.bounds;
    const W = 300;
    const kx = Math.cos(((latMin + latMax) / 2) * Math.PI / 180);
    const H = Math.round(W * (latMax - latMin) / ((lonMax - lonMin) * kx));
    const svg = s('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'sc-dotmap', role: 'img', 'aria-label': o.label });
    const maxN = Math.max(...cells.map((c) => c.n), 1);
    const x = (lon) => (lon - lonMin) / (lonMax - lonMin) * W;
    const y = (lat) => (latMax - lat) / (latMax - latMin) * H;

    cells.slice().sort((a, b) => a.industrial - b.industrial).forEach((c) => {
      const r = 0.9 + Math.sqrt(c.n / maxN) * 4.6;
      const warm = c.industrial;
      const color = warm > 0.5 ? '#e05252' : warm > 0.2 ? '#e2892f' : warm > 0.05 ? '#d6b67a' : '#8b8f96';
      const dot = s('circle', { cx: x(c.lon).toFixed(1), cy: y(c.lat).toFixed(1), r: r.toFixed(2),
        fill: color, 'fill-opacity': (0.35 + 0.55 * Math.min(1, warm * 2 + 0.2)).toFixed(2) }, svg);
      tipped(dot, c.lat.toFixed(1) + ', ' + c.lon.toFixed(1) + ': ' + fmt(c.n) + ' detections, '
        + (c.industrial * 100).toFixed(0) + '% industrial');
    });
    host.appendChild(svg);
    return svg;
  }

  window.SatatCharts = {
    donut, ring, gauge, meter, hbars, timeline, stacked, histogram, dotmap, legend, tipped, fmt
  };
})();
