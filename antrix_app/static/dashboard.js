/* SATAT dashboard.

   Filtering happens twice on purpose. The browser filters the loaded
   snapshot so the map and feed react instantly, and the same filter state is
   serialised into the export URLs so the server reproduces exactly what is on
   screen. The two implementations are kept in step by `filterState()`, which
   is the only place that decides what a filter means.
*/

'use strict';

const CLASS_META = {
  persistent_industrial_source: { label: 'Persistent industrial source', short: 'Persistent', color: '#e2892f' },
  industrial_fire:              { label: 'Industrial fire',              short: 'Industrial fire', color: '#e05252' },
  flare_signature:              { label: 'Flare signature',              short: 'Flare', color: '#ff6b2c' },
  agricultural_burning:         { label: 'Agricultural burning',         short: 'Agricultural', color: '#7fa05a' },
  insufficient_evidence:        { label: 'Insufficient evidence',        short: 'Insufficient', color: '#9aa3b1' }
};

const CLASS_ORDER = [
  'persistent_industrial_source',
  'industrial_fire',
  'flare_signature',
  'agricultural_burning',
  'insufficient_evidence'
];

const SOURCE_ORDER = ['osm', 'wri', 'gem', 'eog'];

const TEMP_CLASS_LABEL = {
  flare_like: 'Flare-like',
  furnace_like: 'Furnace-like',
  mixed: 'Mixed combustion',
  biomass_like: 'Biomass-like',
  smouldering: 'Smouldering',
  unknown: 'Not retrieved'
};

const RETRIEVAL_NOTE = {
  weak_11um: 'The 11 µm channel shows no excess over background, so the bi-spectral solve is unconstrained. No temperature is reported rather than a fabricated one.',
  below_background: 'The 3.7 µm channel is not meaningfully above the local background - no hot component to solve for.',
  no_bracket: 'No physical solution inside the 400 to 2500 K search range.',
  unconstrained: 'The solution sat against the edge of the search range, which means the observation does not pin it down.',
  saturated_lower_bound: 'VIIRS I4 saturated at 367 K. The retrieved temperature is a floor, not an estimate - the true fire is at least this hot.',
  no_data: 'One of the two thermal channels is missing for this detection.'
};

const state = {
  rows: [],
  filtered: [],
  stats: {},
  sources: [],
  classes: new Set(CLASS_ORDER),
  sourceFilter: new Set(),
  minScore: 0,
  search: '',
  sort: 'risk_score',
  groupBySite: false,
  selected: null,
  watch: new Set(),
  watchOnly: false,
  days: [],          // every date in the snapshot, oldest first
  range: [0, 0],     // selected window, as indexes into days
  base: [],          // passes every filter but the window
  buckets: [],       // base, split by day
  dayAll: [],        // every row, split by day (for the metric strip)
  classTotals: {}
};

/* The watchlist is per-browser on purpose: SATAT has no accounts, and a list
   of sites someone is keeping an eye on does not belong on a shared server
   without one. It survives reloads and is exportable through the site CSV. */
const WATCH_KEY = 'satat.watchlist';

function loadWatch() {
  try {
    const raw = localStorage.getItem(WATCH_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch (e) {
    return new Set();   // private mode, blocked storage: the app still works
  }
}

function saveWatch() {
  try {
    localStorage.setItem(WATCH_KEY, JSON.stringify([...state.watch]));
  } catch (e) { /* nothing to do; the session still behaves correctly */ }
}

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

const num = (v, d = 2) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v)))
  ? '-' : Number(v).toFixed(d);


/* =========================================================
   MAP
========================================================= */

const map = L.map('map', {
  zoomControl: false,
  preferCanvas: true,        // the registry overlay is 3,800 vector circles
  attributionControl: true,
  maxZoom: 20
});

// Fit the country rather than hard-coding a zoom: a zoom level that frames
// India on a laptop shows a third of it on a phone.
const INDIA_BOUNDS = L.latLngBounds([[6.5, 68.0], [36.0, 97.5]]);

function frameIndia() {
  // fitBounds is a no-op on a container that has not been laid out yet, and
  // silently leaves the map at a world-scale zoom. Measuring first is what
  // makes the country actually fill the pane.
  map.invalidateSize();
  map.fitBounds(INDIA_BOUNDS, { padding: [14, 14] });
}

requestAnimationFrame(frameIndia);
window.addEventListener('resize', frameIndia);

L.control.zoom({ position: 'topright' }).addTo(map);

const basemaps = {
  dark: L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    { attribution: '© Esri, HERE, Garmin, © OpenStreetMap contributors', maxZoom: 20, maxNativeZoom: 16 }
  ),
  satellite: L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { attribution: '© Esri, Maxar, Earthstar Geographics', maxZoom: 20, maxNativeZoom: 18 }
  )
};
basemaps.satellite.addTo(map);
let activeBase = 'satellite';

/* NASA GIBS VIIRS corrected reflectance: the same imagery family the FIRMS
   detections come from, pinned to the snapshot's last day so the picture and
   the data always describe the same moment. */
function gibsUrl(date) {
  return 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/' +
    'VIIRS_NOAA20_CorrectedReflectance_TrueColor/default/' + date +
    '/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg';
}
let gibsLayer = null;

let heatLayer = null;
let heatOn = false;
let facilityLayer = null;

function radiusFor(frp) {
  const f = Number(frp) || 0;
  return Math.max(3.4, Math.min(11, 3.4 + Math.sqrt(f) * 1.5));
}

/* All detections as individual Leaflet layers, re-clustered on every filter
   change, was what made the dashboard lag with months of data. Now a
   Supercluster index is rebuilt in a fraction of a second when filters
   change, and only what is in view is drawn: clusters as small icons, single
   detections on one canvas. */

const PointCanvas = L.Layer.extend({
  initialize() {
    this._points = [];
    this._drawn = [];
  },

  onAdd(m) {
    this._canvas = L.DomUtil.create('canvas', 'pt-canvas leaflet-zoom-hide');
    m.getPanes().overlayPane.appendChild(this._canvas);
    m.on('moveend resize', this._reset, this);
    this._reset();
  },

  onRemove(m) {
    L.DomUtil.remove(this._canvas);
    m.off('moveend resize', this._reset, this);
  },

  setPoints(pts) {
    this._points = pts;
    this._draw();
  },

  // The canvas is a quarter-screen larger than the map on every side, so a
  // short pan does not reveal an empty edge before the redraw.
  _reset() {
    const m = this._map;
    const size = m.getSize();
    const pad = size.multiplyBy(0.25).round();
    this._origin = m.containerPointToLayerPoint(pad.multiplyBy(-1)).round();
    L.DomUtil.setPosition(this._canvas, this._origin);
    const w = size.x + pad.x * 2;
    const h = size.y + pad.y * 2;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this._canvas.width = Math.round(w * dpr);
    this._canvas.height = Math.round(h * dpr);
    this._canvas.style.width = w + 'px';
    this._canvas.style.height = h + 'px';
    this._dpr = dpr;
    this._draw();
  },

  // Points carry their zoom-0 pixel position, so placing 45k of them is a
  // multiply and a subtract each rather than a full projection.
  _draw() {
    const m = this._map;
    if (!m || !this._canvas || !this._origin) return;
    const ctx = this._canvas.getContext('2d');
    ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);
    ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);

    const scale = m.getZoomScale(m.getZoom(), 0);
    // Playback points shrink at country scale, or a day's thousand
    // detections merge into one blob; they reach full size by zoom 9.
    const zf = Math.min(1, Math.max(0.3, (m.getZoom() - 2) / 7));
    const po = m.getPixelOrigin();
    const ox = po.x + this._origin.x;
    const oy = po.y + this._origin.y;
    const drawn = [];

    for (let i = 0; i < this._points.length; i += 1) {
      const p = this._points[i];
      const x = p.x0 * scale - ox;
      const y = p.y0 * scale - oy;
      const r = p.zs ? Math.max(1.4, p.r * zf) : p.r;
      ctx.globalAlpha = p.alpha;
      ctx.fillStyle = p.color;
      if (p.dot) {
        ctx.fillRect(x - r, y - r, r * 2, r * 2);
        continue;
      }
      if (p.halo) {
        ctx.globalAlpha = p.alpha * 0.26;
        ctx.beginPath();
        ctx.arc(x, y, r * 2.2, 0, 6.2832);
        ctx.fill();
        ctx.globalAlpha = p.alpha;
      }
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 6.2832);
      ctx.fill();
      if (p.rim && r >= 3) {
        ctx.lineWidth = 1;
        ctx.strokeStyle = 'rgba(245, 239, 230, .9)';
        ctx.stroke();
      }
      if (p.row) drawn.push(x, y, Math.max(r, 4), i);
    }
    ctx.globalAlpha = 1;
    this._drawn = drawn;
  },

  // Nearest clickable point to a container pixel, within its radius plus slack.
  hit(containerPoint, slack) {
    if (!this._map || !this._drawn.length) return null;
    const lp = this._map.containerPointToLayerPoint(containerPoint);
    const cx = lp.x - this._origin.x;
    const cy = lp.y - this._origin.y;
    let best = null;
    let bestD = Infinity;
    const d = this._drawn;
    for (let k = 0; k < d.length; k += 4) {
      const dx = d[k] - cx;
      const dy = d[k + 1] - cy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist <= d[k + 2] + slack && dist < bestD) {
        bestD = dist;
        best = this._points[d[k + 3]].row;
      }
    }
    return best;
  }
});

const clusterLayer = L.layerGroup().addTo(map);
const points = new PointCanvas().addTo(map);
let highlight = null;
let index = null;

const CLASS_INDEX = Object.fromEntries(CLASS_ORDER.map((k, i) => [k, i]));

function rebuildIndex() {
  // Zoom 3 already shows all of India, and past 17 detections are drawn
  // individually, so only those levels are indexed.
  index = new Supercluster({
    radius: 48,
    minZoom: 3,
    maxZoom: 17,
    map: (p) => {
      const counts = [0, 0, 0, 0, 0];
      counts[p.k] = 1;
      return { k0: counts[0], k1: counts[1], k2: counts[2], k3: counts[3], k4: counts[4] };
    },
    reduce: (acc, p) => {
      acc.k0 += p.k0; acc.k1 += p.k1; acc.k2 += p.k2; acc.k3 += p.k3; acc.k4 += p.k4;
    }
  });
  index.load(state.filtered.map((row, i) => ({
    type: 'Feature',
    properties: { i, k: CLASS_INDEX[row.final_label] ?? 4 },
    geometry: { type: 'Point', coordinates: [row.longitude, row.latitude] }
  })));
}

function clusterIcon(p) {
  const n = p.point_count;
  let acc = 0;
  const stops = [];
  CLASS_ORDER.forEach((key, i) => {
    const c = p['k' + i];
    if (!c) return;
    const from = acc / n * 360;
    acc += c;
    stops.push(CLASS_META[key].color + ' ' + from.toFixed(1) + 'deg ' + (acc / n * 360).toFixed(1) + 'deg');
  });
  const size = n < 10 ? 30 : n < 100 ? 36 : n < 1000 ? 42 : 48;
  const label = n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : String(n);
  return L.divIcon({
    html: '<div class="cl" style="width:' + size + 'px;height:' + size + 'px;background:conic-gradient(' +
      stops.join(',') + ')"><span>' + label + '</span></div>',
    className: 'satat-cluster',
    iconSize: [size, size]
  });
}

function pointFor(row) {
  const meta = CLASS_META[row.final_label] || CLASS_META.insufficient_evidence;
  // A light rim and a near-solid fill keep every class, grey included,
  // visible on both the imagery and the dark basemap.
  return { x0: row._x, y0: row._y, r: radiusFor(row.frp), color: meta.color, alpha: 0.9, rim: true, row };
}

function renderView() {
  if (play.active) return;
  clusterLayer.clearLayers();
  if (!index) { points.setPoints([]); return; }

  const b = map.getBounds().pad(0.3);
  const box = [Math.max(-180, b.getWest()), Math.max(-85, b.getSouth()),
    Math.min(180, b.getEast()), Math.min(85, b.getNorth())];
  const features = index.getClusters(box, Math.round(map.getZoom()));
  const singles = [];

  features.forEach((f) => {
    const [lon, lat] = f.geometry.coordinates;
    if (f.properties.cluster) {
      const marker = L.marker([lat, lon], { icon: clusterIcon(f.properties), keyboard: false });
      marker.on('click', () => openCluster(f.properties.cluster_id, lat, lon));
      clusterLayer.addLayer(marker);
    } else {
      singles.push(pointFor(state.filtered[f.properties.i]));
    }
  });

  // Draw the unconfirmed first, so industrial readings sit on top.
  singles.sort((a, b2) => (CLASS_INDEX[b2.row.final_label] ?? 4) - (CLASS_INDEX[a.row.final_label] ?? 4));
  points.setPoints(singles);
}

/* A cluster zooms in until it splits. Detections stacked on one spot never
   split, so at that point the cluster lists them instead. */
function openCluster(id, lat, lon) {
  const next = index.getClusterExpansionZoom(id);
  if (next <= 18 && map.getZoom() < 17) {
    map.setView([lat, lon], next);
    return;
  }
  const rows = index.getLeaves(id, 60).map((l) => state.filtered[l.properties.i])
    .sort((a, b) => Number(b.risk_score) - Number(a.risk_score));
  const box = el('div', 'leafpop');
  box.appendChild(el('h4', null, rows.length + ' detections at this spot'));
  rows.slice(0, 12).forEach((row) => {
    const meta = CLASS_META[row.final_label] || CLASS_META.insufficient_evidence;
    const btn = el('button');
    const dot = el('span', 'dot');
    dot.style.background = meta.color;
    btn.append(dot, el('span', 'd', row.acq_date), el('span', 'nm', row.nearest_facility_name || 'Unnamed site'),
      el('span', 'r', num(row.risk_score)));
    btn.addEventListener('click', () => { map.closePopup(); openDetail(row.detection_id); });
    box.appendChild(btn);
  });
  L.popup({ className: 'satat-popup', maxWidth: 300 }).setLatLng([lat, lon]).setContent(box).openOn(map);
}

function setHighlight(row) {
  if (highlight) { map.removeLayer(highlight); highlight = null; }
  if (!row) return;
  highlight = L.circleMarker([row.latitude, row.longitude], {
    radius: 14, color: '#fff4e6', weight: 2, fill: false, interactive: false, dashArray: '3 3'
  }).addTo(map);
}

map.on('moveend', renderView);

map.on('click', (e) => {
  const row = points.hit(e.containerPoint, L.Browser.mobile ? 12 : 5);
  if (!row) return;
  if (play.running) pausePlay();
  openDetail(row.detection_id);
});

let hoverPending = false;
map.on('mousemove', (e) => {
  if (hoverPending) return;
  hoverPending = true;
  requestAnimationFrame(() => {
    hoverPending = false;
    map.getContainer().classList.toggle('pt-hover', !!points.hit(e.containerPoint, 5));
  });
});

function refreshHeat() {
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }
  if (!heatOn) return;
  const rows = play.active ? playRows() : state.filtered;
  heatLayer = L.heatLayer(rows.map((r) => [r.latitude, r.longitude, Math.min(1, (Number(r.frp) || 0) / 20)]), {
    radius: 22, blur: 18, maxZoom: 10, minOpacity: 0.25,
    gradient: { 0.2: '#5a4a3a', 0.45: '#7fa05a', 0.7: '#e2892f', 1: '#ff6b2c' }
  }).addTo(map);
}


/* =========================================================
   FILTERING
========================================================= */

function filterState() {
  return {
    classes: [...state.classes],
    sources: [...state.sourceFilter],
    minScore: state.minScore,
    search: state.search.trim().toLowerCase()
  };
}

/* Two sets come out of this. `base` passes every filter except the date
   window; it feeds the timeline histogram and playback. `filtered` is base
   inside the window; it feeds the map, feed and exports. */
function applyFilters() {
  const f = filterState();
  const [lo, hi] = state.range;
  const buckets = Array.from({ length: state.days.length }, () => []);
  const base = [];
  const filtered = [];

  state.rows.forEach((row) => {
    if (!state.classes.has(row.final_label)) return;
    if ((Number(row.risk_score) || 0) < f.minScore) return;
    if (f.sources.length) {
      const confirming = String(row.sources_confirming || '').split('|');
      if (!f.sources.some((s) => confirming.includes(s))) return;
    }
    if (state.watchOnly && !state.watch.has(row.facility_uid)) return;
    if (f.search && !String(row.nearest_facility_name || '').toLowerCase().includes(f.search)) return;

    base.push(row);
    if (row._d >= 0) buckets[row._d].push(row);
    if (row._d >= lo && row._d <= hi) filtered.push(row);
  });

  const key = state.sort;
  filtered.sort((a, b) => {
    if (key === 'acq_date') return b._d - a._d;
    const av = Number(a[key]); const bv = Number(b[key]);
    // Rows with no value for the sort key belong at the bottom, not the top.
    if (Number.isNaN(av) && Number.isNaN(bv)) return 0;
    if (Number.isNaN(av)) return 1;
    if (Number.isNaN(bv)) return -1;
    return bv - av;
  });

  state.base = base;
  state.buckets = buckets;
  state.filtered = filtered;

  rebuildIndex();
  if (play.active) renderFrame(); else renderView();
  refreshHeat();

  renderTimeline();
  renderMetrics();
  renderFeed();
  renderChips();
  updateExportLinks();
}

function exportQuery() {
  const params = new URLSearchParams();
  if (state.classes.size !== CLASS_ORDER.length) params.set('label', [...state.classes].join(','));
  if (state.sourceFilter.size) params.set('sources', [...state.sourceFilter].join(','));
  if (state.minScore > 0) params.set('min_score', String(state.minScore));
  if (state.search.trim()) params.set('q', state.search.trim());
  if (state.range[0] > 0) params.set('from', state.days[state.range[0]]);
  if (state.range[1] < state.days.length - 1) params.set('to', state.days[state.range[1]]);
  const qs = params.toString();
  return qs ? '?' + qs : '';
}

function updateExportLinks() {
  const qs = exportQuery();
  $('#ex-csv').href = '/api/export/detections.csv' + qs;
  $('#ex-geojson').href = '/api/export/detections.geojson' + qs;
}


/* =========================================================
   TIME WINDOW
========================================================= */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const shortDate = (d) => (d ? MONTHS[Number(d.slice(5, 7)) - 1] + ' ' + Number(d.slice(8, 10)) : '-');
const TL = { bars: [], head: null };

function buildTimeline() {
  const svg = $('#tb-hist');
  const n = state.days.length;
  svg.setAttribute('viewBox', '0 0 ' + n + ' 20');
  svg.innerHTML = '';
  const NS = 'http://www.w3.org/2000/svg';
  TL.bars = state.days.map((day, i) => {
    if (i > 0 && day.slice(8, 10) === '01') {
      const line = document.createElementNS(NS, 'line');
      line.setAttribute('class', 'm');
      line.setAttribute('x1', i); line.setAttribute('x2', i);
      line.setAttribute('y1', 0); line.setAttribute('y2', 20);
      svg.appendChild(line);
    }
    const bar = document.createElementNS(NS, 'rect');
    bar.setAttribute('class', 'b');
    bar.setAttribute('x', i + 0.12);
    bar.setAttribute('width', 0.76);
    bar.dataset.i = String(i);
    svg.appendChild(bar);
    return bar;
  });
  TL.head = document.createElementNS(NS, 'rect');
  TL.head.setAttribute('class', 'head');
  TL.head.setAttribute('width', 0.5);
  TL.head.setAttribute('y', -1);
  TL.head.setAttribute('height', 22);
  TL.head.style.display = 'none';
  svg.appendChild(TL.head);

  svg.addEventListener('click', (e) => {
    const i = Number(e.target.dataset && e.target.dataset.i);
    if (!play.active || Number.isNaN(i)) return;
    play.day = Math.max(state.range[0], Math.min(state.range[1], i));
    renderFrame();
  });

  const max = Math.max(n - 1, 0);
  ['#tb-from', '#tb-to'].forEach((sel) => { $(sel).max = String(max); });
  $('#tb-from').value = String(state.range[0]);
  $('#tb-to').value = String(state.range[1]);
}

/* Bar heights follow every filter except the window itself, so the strip
   shows where activity is before a window is chosen. */
function renderTimeline() {
  const counts = state.buckets.map((b) => b.length);
  const max = Math.max(...counts, 1);
  const [lo, hi] = state.range;
  const d = play.active ? play.day : -1;
  TL.bars.forEach((bar, i) => {
    const h = counts[i] ? Math.max(1.2, Math.sqrt(counts[i] / max) * 19) : 0.4;
    bar.setAttribute('y', 20 - h);
    bar.setAttribute('height', h);
    let cls = 'b';
    if (i >= lo && i <= hi) cls += play.active ? (i < d ? ' past' : i === d ? ' now' : '') : ' in';
    bar.setAttribute('class', cls);
    C.tipped(bar, state.days[i] + ': ' + counts[i] + ' detection' + (counts[i] === 1 ? '' : 's'));
  });
  if (play.active) {
    TL.head.style.display = '';
    TL.head.setAttribute('x', d + 0.25);
  } else {
    TL.head.style.display = 'none';
  }
  renderTimeLabel();
}

function renderTimeLabel() {
  const [lo, hi] = state.range;
  const n = state.days.length;
  const sel = $('#tb-sel');
  sel.style.left = 'calc(7px + (100% - 14px) * ' + (n > 1 ? lo / (n - 1) : 0) + ')';
  sel.style.right = 'calc(7px + (100% - 14px) * ' + (n > 1 ? 1 - hi / (n - 1) : 0) + ')';

  if (play.active) {
    const day = state.days[play.day];
    const count = (state.buckets[play.day] || []).length;
    $('#tb-dates').textContent = shortDate(day) + ' ' + day.slice(0, 4);
    $('#tb-meta').textContent = 'day ' + (play.day - lo + 1) + ' of ' + (hi - lo + 1) + ' · ' + count + ' seen';
  } else {
    $('#tb-dates').textContent = shortDate(state.days[lo]) + ' - ' + shortDate(state.days[hi]);
    $('#tb-meta').textContent = (hi - lo + 1) + ' days · ' + state.filtered.length.toLocaleString() + ' detections';
  }
}

const refilterWindow = debounce(() => applyFilters(), 140);

function setRange(lo, hi, preset) {
  const n = state.days.length;
  lo = Math.max(0, Math.min(n - 1, lo));
  hi = Math.max(lo, Math.min(n - 1, hi));
  state.range = [lo, hi];
  $('#tb-from').value = String(lo);
  $('#tb-to').value = String(hi);
  $('#tb-preset').value = preset || (lo === 0 && hi === n - 1 ? 'all' : 'custom');
  if (play.active) play.day = Math.max(lo, Math.min(hi, play.day));
}

function wireTimebar() {
  const from = $('#tb-from');
  const to = $('#tb-to');
  const onSlide = (moved) => {
    let lo = Number(from.value);
    let hi = Number(to.value);
    if (lo > hi) { if (moved === from) lo = hi; else hi = lo; }
    setRange(lo, hi);
    // Labels and the highlighted strip follow the thumb at once; the map
    // waits for the drag to pause.
    TL.bars.forEach((bar, i) => {
      bar.classList.toggle('in', i >= lo && i <= hi && !play.active);
    });
    renderTimeLabel();
    refilterWindow();
  };
  from.addEventListener('input', () => onSlide(from));
  to.addEventListener('input', () => onSlide(to));

  // Whichever thumb is nearer the pointer goes on top, so both stay
  // grabbable when they meet.
  $('#tb-track').addEventListener('pointerdown', (e) => {
    const rect = from.getBoundingClientRect();
    const n = state.days.length;
    const at = ((e.clientX - rect.left - 7) / Math.max(1, rect.width - 14)) * (n - 1);
    const nearFrom = Math.abs(at - Number(from.value)) <= Math.abs(at - Number(to.value));
    from.style.zIndex = nearFrom ? '3' : '2';
    to.style.zIndex = nearFrom ? '2' : '3';
  });

  $('#tb-preset').addEventListener('change', (e) => {
    const n = state.days.length;
    const v = e.target.value;
    if (v === 'all') setRange(0, n - 1, 'all');
    else if (v !== 'custom') setRange(n - Number(v), n - 1, v);
    applyFilters();
  });

  $('#tb-play').addEventListener('click', () => (play.running ? pausePlay() : startPlay()));
  $('#tb-stop').addEventListener('click', stopPlay);
  $('#tb-speed').addEventListener('click', () => {
    play.speed = play.speed >= 4 ? 1 : play.speed * 2;
    $('#tb-speed').textContent = play.speed + 'x';
  });
}


/* =========================================================
   PLAYBACK

   The window replayed one day at a time: the current day's detections glow,
   the previous week fades out behind them, and everything earlier in the
   window stays as a faint trace, so a site that burns every night reads as
   a steady pulse and a crop fire as a single flash.
========================================================= */

const play = { active: false, running: false, day: 0, speed: 1, timer: null };
const TRAIL_DAYS = 6;
const DAY_MS = 700;

function playRows() {
  return state.buckets[play.day] || [];
}

function startPlay() {
  const [lo, hi] = state.range;
  if (!play.active) {
    play.active = true;
    play.day = lo;
    $('#timebar').classList.add('playing');
    closeDetail();
  } else if (play.day >= hi) {
    play.day = lo;
  }
  play.running = true;
  $('#tb-play').setAttribute('aria-pressed', 'true');
  $('#tb-play').setAttribute('aria-label', 'Pause playback');
  renderFrame();
  scheduleTick();
}

function scheduleTick() {
  clearTimeout(play.timer);
  play.timer = setTimeout(() => {
    if (!play.running) return;
    if (play.day >= state.range[1]) { pausePlay(); return; }
    play.day += 1;
    renderFrame();
    scheduleTick();
  }, DAY_MS / play.speed);
}

function pausePlay() {
  play.running = false;
  clearTimeout(play.timer);
  $('#tb-play').setAttribute('aria-pressed', 'false');
  $('#tb-play').setAttribute('aria-label', 'Resume playback');
}

function stopPlay() {
  pausePlay();
  play.active = false;
  $('#timebar').classList.remove('playing');
  $('#tb-play').setAttribute('aria-label', 'Play day by day');
  renderView();
  refreshHeat();
  renderTimeline();
  renderMetrics();
  renderChips();
  renderFeed();
}

function renderFrame() {
  const [lo] = state.range;
  const d = play.day;
  const pts = [];

  for (let k = lo; k < d; k += 1) {
    const age = d - k;
    const bucket = state.buckets[k] || [];
    if (age > TRAIL_DAYS) {
      for (const row of bucket) pts.push({ x0: row._x, y0: row._y, r: 1.2, color: '#e8d6b6', alpha: 0.15, dot: true });
    } else {
      const fade = 0.8 * (1 - age / (TRAIL_DAYS + 1));
      for (const row of bucket) {
        const meta = CLASS_META[row.final_label] || CLASS_META.insufficient_evidence;
        pts.push({ x0: row._x, y0: row._y, r: radiusFor(row.frp) * 0.8, color: meta.color, alpha: fade, zs: true });
      }
    }
  }
  // Today last, on top: brighter, larger, haloed, and clickable.
  (state.buckets[d] || []).forEach((row) => {
    const meta = CLASS_META[row.final_label] || CLASS_META.insufficient_evidence;
    pts.push({ x0: row._x, y0: row._y, r: radiusFor(row.frp) + 1.5, color: meta.color, alpha: 0.97,
      halo: true, rim: true, zs: true, row });
  });

  clusterLayer.clearLayers();
  points.setPoints(pts);
  if (heatOn) refreshHeat();
  renderTimeline();
  renderMetrics();
  renderChips();
  renderFeed();
}


/* =========================================================
   RENDER - metrics, sources, chips, feed
========================================================= */

/* Counts for what is on screen: the window, or during playback the day
   being shown. Class filters do not apply, so the strip always shows the
   whole picture for that period. */
function periodRows() {
  if (play.active) return state.dayAll[play.day] || [];
  const [lo, hi] = state.range;
  const out = [];
  for (let k = lo; k <= hi; k += 1) {
    const bucket = state.dayAll[k];
    for (let j = 0; j < bucket.length; j += 1) out.push(bucket[j]);
  }
  return out;
}

function renderMetrics() {
  const rows = periodRows();
  const counts = {};
  let multi = 0;
  let temp = 0;
  rows.forEach((r) => {
    counts[r.final_label] = (counts[r.final_label] || 0) + 1;
    if (String(r.sources_confirming || '').split('|').filter(Boolean).length >= 2) multi += 1;
    if (r.est_temp_k !== '' && r.est_temp_k !== null) temp += 1;
  });

  // Phone columns are ~108px wide, so the desktop wording would be clipped
  // mid-word. Shorter labels are used rather than smaller text.
  const narrow = window.innerWidth <= 860;
  const cells = [
    ['persistent_industrial_source', narrow ? 'Persistent' : 'Persistent source'],
    ['industrial_fire', narrow ? 'Industrial' : 'Industrial fire'],
    ['flare_signature', narrow ? 'Flare' : 'Flare signature'],
    ['agricultural_burning', narrow ? 'Agri' : 'Agricultural'],
    ['insufficient_evidence', narrow ? 'Insuff.' : 'Insufficient']
  ];

  const host = $('#metrics');
  host.innerHTML = '';

  cells.forEach(([key, label]) => {
    const cell = el('div', 'metric');
    cell.appendChild(el('div', 'v', (counts[key] || 0).toLocaleString()));
    const k = el('div', 'k');
    const dot = el('span', 'dot');
    dot.style.background = CLASS_META[key].color;
    k.appendChild(dot);
    k.appendChild(document.createTextNode(label));
    cell.appendChild(k);
    host.appendChild(cell);
  });

  const extra = [
    [multi, narrow ? '2+ sources' : 'Confirmed 2+ sources'],
    [temp, narrow ? 'Temp.' : 'Temp. retrieved'],
    [state.stats.registry_sites, narrow ? 'Sites' : 'Registry sites']
  ];
  extra.forEach(([value, label]) => {
    const cell = el('div', 'metric');
    cell.appendChild(el('div', 'v', value === undefined ? '-' : Number(value).toLocaleString()));
    cell.appendChild(el('div', 'k', label));
    host.appendChild(cell);
  });
}

function renderSources() {
  const host = $('#source-grid');
  host.innerHTML = '';

  SOURCE_ORDER.forEach((key) => {
    const info = state.sources.find((s) => s.key === key) || { key, short: key.toUpperCase(), status: 'unavailable' };
    const loaded = info.status === 'loaded';

    const btn = el('button', 'source');
    btn.setAttribute('aria-pressed', String(state.sourceFilter.has(key)));
    if (!loaded) {
      btn.disabled = true;
      btn.title = info.hint || 'This registry is not loaded for the current snapshot.';
    } else {
      btn.title = info.label + ' - ' + info.records + ' records · ' + info.license;
    }

    const top = el('div', 'top');
    const dot = el('span', 'status-dot ' + (loaded ? 'loaded' : 'unavailable'));
    top.appendChild(dot);
    top.appendChild(el('span', 'name', info.short || key.toUpperCase()));
    top.appendChild(el('span', 'count num', loaded ? String(info.detections_confirmed) : 'n/a'));
    btn.appendChild(top);

    btn.appendChild(el('div', 'meta', loaded
      ? info.records.toLocaleString() + ' facilities'
      : 'not loaded'));

    btn.addEventListener('click', () => {
      if (state.sourceFilter.has(key)) state.sourceFilter.delete(key);
      else state.sourceFilter.add(key);
      btn.setAttribute('aria-pressed', String(state.sourceFilter.has(key)));
      applyFilters();
    });

    host.appendChild(btn);
  });
}

function renderChips() {
  const host = $('#class-chips');
  const counts = {};
  periodRows().forEach((r) => { counts[r.final_label] = (counts[r.final_label] || 0) + 1; });

  host.innerHTML = '';
  CLASS_ORDER.forEach((key) => {
    if (!state.classTotals[key]) return;
    const meta = CLASS_META[key];
    const chip = el('button', 'chip');
    chip.setAttribute('aria-pressed', String(state.classes.has(key)));

    const dot = el('span', 'dot');
    dot.style.background = meta.color;
    chip.appendChild(dot);
    chip.appendChild(document.createTextNode(meta.short));
    chip.appendChild(el('span', 'n', String(counts[key] || 0)));

    chip.addEventListener('click', () => {
      if (state.classes.has(key)) state.classes.delete(key);
      else state.classes.add(key);
      // Never leave every class off: that shows an empty screen with no
      // obvious way back.
      if (state.classes.size === 0) CLASS_ORDER.forEach((k) => state.classes.add(k));
      applyFilters();
    });

    host.appendChild(chip);
  });
}

function sourceBar(row) {
  const confirming = String(row.sources_confirming || '').split('|').filter(Boolean);
  const loaded = String(row.sources_loaded || '').split('|').filter(Boolean);
  const bar = el('div', 'srcbar');
  SOURCE_ORDER.forEach((key) => {
    const cell = el('i');
    if (confirming.includes(key)) cell.className = 'on';
    else if (!loaded.includes(key)) cell.className = 'off-src';
    cell.title = key.toUpperCase() + (confirming.includes(key) ? ' - confirms'
      : loaded.includes(key) ? ' - no facility within 3 km' : ' - registry not loaded');
    bar.appendChild(cell);
  });
  return bar;
}

/* One row per site instead of per detection.

   A steel plant seen on five consecutive days is five detections and one
   problem. Grouped mode answers "which sites need attention", ungrouped
   answers "what exactly was observed" -- investigators want both, at
   different moments. */
function groupBySite(rows) {
  const groups = new Map();

  rows.forEach((row) => {
    const key = row.facility_uid || ('loose:' + row.grid_lat + ',' + row.grid_lon);
    const existing = groups.get(key);
    if (!existing) {
      groups.set(key, { lead: row, count: 1, days: new Set([row.acq_date]) });
      return;
    }
    existing.count += 1;
    existing.days.add(row.acq_date);
    if (Number(row.risk_score) > Number(existing.lead.risk_score)) existing.lead = row;
  });

  return [...groups.values()]
    .map((g) => ({ ...g.lead, _group_count: g.count, _group_days: g.days.size }))
    .sort((a, b) => Number(b.risk_score) - Number(a.risk_score));
}

function renderFeed() {
  const host = $('#feed');
  host.innerHTML = '';

  // During playback the feed is the day being shown, highest priority first:
  // a live log that turns over as the days advance.
  const source = play.active
    ? playRows().slice().sort((a, b) => Number(b.risk_score) - Number(a.risk_score))
    : state.filtered;
  const rows = state.groupBySite ? groupBySite(source) : source;
  const limit = play.active ? 120 : 400;
  const count = $('#feedcount');

  count.classList.toggle('live', play.active);
  if (play.active) {
    count.textContent = 'Live · ' + shortDate(state.days[play.day]) + ' · ' +
      (state.groupBySite ? rows.length + ' sites · ' : '') + source.length + ' detections';
  } else {
    count.textContent = state.groupBySite
      ? rows.length + ' sites · ' + state.filtered.length + ' detections'
      : state.filtered.length + ' of ' + state.base.length + ' detections';
  }

  if (!rows.length) {
    host.appendChild(el('div', 'empty', play.active
      ? 'Nothing detected on this day with the current filters.'
      : 'No detections match these filters.'));
    return;
  }

  const fragment = document.createDocumentFragment();

  rows.slice(0, limit).forEach((row) => {
    const meta = CLASS_META[row.final_label] || CLASS_META.insufficient_evidence;
    const item = el('button', play.active ? 'item fresh' : 'item');
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', String(state.selected === row.detection_id));
    item.dataset.id = row.detection_id;

    const line1 = el('div', 'line1');
    const dot = el('span', 'dot');
    dot.style.background = meta.color;
    line1.appendChild(dot);
    const cls = el('span', 'cls', meta.label);
    cls.style.color = meta.color;
    line1.appendChild(cls);

    const rank = el('span', 'rank');
    rank.appendChild(document.createTextNode(num(row.risk_score)));
    rank.appendChild(el('small', null, ' pri'));
    line1.appendChild(rank);
    item.appendChild(line1);

    item.appendChild(el('div', 'site', row.nearest_facility_name || 'Unnamed site'));

    const facts = el('div', 'facts');
    const add = (k, v) => {
      const span = el('span');
      span.appendChild(el('b', null, v));
      span.appendChild(document.createTextNode(' ' + k));
      facts.appendChild(span);
    };
    add('MW', num(row.frp, 1));
    add('km', num(row.dist_to_industrial_km, 1));
    add('days', String(row.recurrence_days || 0));
    if (row.est_temp_k !== '' && row.est_temp_k !== null) add('K', num(row.est_temp_k, 0));
    if (row._group_count > 1) add('detections', String(row._group_count));
    facts.appendChild(el('span', null, String(row.acq_date || '')));
    item.appendChild(facts);

    item.appendChild(sourceBar(row));

    item.addEventListener('click', () => {
      if (play.running) pausePlay();
      openDetail(row.detection_id);
    });
    fragment.appendChild(item);
  });

  host.appendChild(fragment);

  if (rows.length > limit) {
    host.appendChild(el('div', 'empty', play.active
      ? 'Showing the ' + limit + ' highest-ranked for this day.'
      : 'Showing the 400 highest-ranked. Export the CSV for all ' + rows.length + '.'));
  }
}


/* =========================================================
   DETAIL
========================================================= */

let contextMap = null;
const C = window.SatatCharts;
const detailCache = new Map();
let detailToken = 0;

const RISK_COLOR = { Critical: '#e05252', High: '#e2892f', Moderate: '#cbb03c', Low: '#6b7484' };
const REGIME_COLOR = {
  flare_like: '#ff6b2c', furnace_like: '#e05252', mixed: '#e2892f',
  biomass_like: '#7fa05a', smouldering: '#d6b67a', unknown: '#59616e'
};

const isTrue = (v) => v === true || v === 'True' || v === 'true';

function block(labelText) {
  const b = el('div', 'block');
  b.appendChild(el('span', 'label', labelText));
  return b;
}

function kvList(pairs) {
  const dl = el('dl', 'kv');
  pairs.forEach(([k, v]) => {
    dl.appendChild(el('dt', null, k));
    dl.appendChild(el('dd', null, v));
  });
  return dl;
}

function badge(text, color) {
  const b = el('span', 'badge');
  if (color) {
    const d = el('span', 'dot');
    d.style.background = color;
    b.appendChild(d);
  }
  b.appendChild(document.createTextNode(text));
  return b;
}

function tiles(items, cls) {
  const wrap = el('div', 'tiles' + (cls ? ' ' + cls : ''));
  items.forEach(([value, label, ring, color]) => {
    const t = el('div', 'tile');
    const text = el('div');
    text.style.minWidth = '0';
    text.appendChild(el('div', 'tv', value));
    text.appendChild(el('div', 'tk', label));
    t.appendChild(text);
    if (ring !== undefined && ring !== null && ring !== '' && Number.isFinite(Number(ring))) {
      t.appendChild(C.ring(Number(ring), { size: 30, thickness: 6, color: color || '#e2892f' }));
    }
    wrap.appendChild(t);
  });
  return wrap;
}

/* Every date in the snapshot window, so timelines show quiet days too. */
function windowDays() {
  const range = state.stats.date_range;
  if (!range) return [];
  const out = [];
  const day = new Date(range[0] + 'T00:00:00Z');
  const end = new Date(range[1] + 'T00:00:00Z');
  while (day <= end) {
    out.push(day.toISOString().slice(0, 10));
    day.setUTCDate(day.getUTCDate() + 1);
  }
  return out;
}

async function fetchDetection(id) {
  if (detailCache.has(id)) return detailCache.get(id);
  const response = await fetch('/api/detection/' + encodeURIComponent(id));
  if (!response.ok) throw new Error('HTTP ' + response.status);
  const record = await response.json();
  detailCache.set(id, record);
  return record;
}

/* The map only carries what it draws; the full evidence record is fetched
   when a detection is opened. The panel opens at once with what is known and
   fills in when the record arrives. */
async function openDetail(id) {
  const lite = state.rows.find((r) => r.detection_id === id);
  if (!lite) return;

  state.selected = id;
  document.querySelectorAll('.item').forEach((node) => {
    node.setAttribute('aria-selected', String(node.dataset.id === id));
  });

  const meta = CLASS_META[lite.final_label] || CLASS_META.insufficient_evidence;
  $('#d-title').textContent = lite.nearest_facility_name || 'Unnamed site';
  $('#d-title').style.color = 'var(--text)';
  setDetailSub(lite, meta);

  $('#d-export').onclick = () => {
    if (lite.facility_uid) window.location.href = '/api/export/site/' + lite.facility_uid + '.csv';
  };
  $('#d-export').disabled = !lite.facility_uid;

  const body = $('#d-body');
  body.innerHTML = '';
  body.appendChild(el('div', 'loading', 'Loading the evidence for this detection...'));
  $('#detail').hidden = false;
  if (window.innerWidth <= 860) $('#sidepane').classList.add('open');

  // Deep link, so a detection can be sent to someone rather than described.
  const url = new URL(window.location);
  url.searchParams.set('detection', id);
  history.replaceState(null, '', url);

  map.setView([lite.latitude, lite.longitude], Math.max(map.getZoom(), 9));
  setHighlight(lite);

  const token = ++detailToken;
  let row;
  try {
    row = await fetchDetection(id);
  } catch (err) {
    if (token !== detailToken) return;
    body.innerHTML = '';
    body.appendChild(el('div', 'loading', 'Could not load this detection: ' + err.message));
    return;
  }
  if (token !== detailToken) return;
  setDetailSub(row, meta);
  renderDetail(row, meta);
}

function setDetailSub(row, meta) {
  const sub = $('#d-sub');
  sub.innerHTML = '';
  const clsSpan = el('span', null, meta.label);
  clsSpan.style.color = meta.color;
  sub.appendChild(clsSpan);
  const time = row.acq_time === undefined || row.acq_time === '' ? ''
    : ' ' + String(row.acq_time).padStart(4, '0') + ' UTC';
  sub.appendChild(document.createTextNode(
    ' · ' + row.acq_date + time +
    ' · ' + Number(row.latitude).toFixed(4) + ', ' + Number(row.longitude).toFixed(4)
  ));
}

function renderDetail(row, meta) {
  const body = $('#d-body');
  body.innerHTML = '';

  /* --- priority --- */
  const scoreBlock = block('Investigation priority');
  const top = el('div', 'case-top');
  const gaugeHost = el('div');
  C.gauge(gaugeHost, row.risk_score, { label: 'Priority score', digits: 2 });
  top.appendChild(gaugeHost);

  const right = el('div');
  const badges = el('div', 'badges');
  badges.appendChild(badge(row.risk_level || 'n/a', RISK_COLOR[row.risk_level]));
  badges.appendChild(badge(meta.label, meta.color));
  if (row.evidence_level) badges.appendChild(badge(row.evidence_level + ' evidence'));
  right.appendChild(badges);
  right.appendChild(C.meter('Anomaly probability', row.anomaly_probability, { color: '#e2892f' }));
  right.appendChild(C.meter('Evidence score', row.evidence_score, { color: '#d6b67a' }));
  right.appendChild(C.meter('Model probability', row.ml_industrial_prob === '' ? NaN : row.ml_industrial_prob, { color: '#e05252' }));
  right.appendChild(C.meter('Unsupervised anomaly', row.unsupervised_anomaly, { color: '#b5532a' }));
  top.appendChild(right);
  scoreBlock.appendChild(top);
  body.appendChild(scoreBlock);

  /* --- contributions --- */
  let contributions = row.contributions;
  if (typeof contributions === 'string') {
    try { contributions = JSON.parse(contributions || '[]'); } catch (e) { contributions = []; }
  }
  if (!Array.isArray(contributions)) contributions = [];

  if (contributions.length) {
    const cBlock = block('What produced this score');
    const maxAbs = Math.max(...contributions.map((c) => Math.abs(c.contribution)), 0.001);

    contributions.forEach((c) => {
      const wrap = el('div', 'contrib');
      const head = el('div', 'top');
      head.appendChild(el('span', null, c.label));
      head.appendChild(el('span', 'w', (c.contribution >= 0 ? '+' : '') + c.contribution.toFixed(3)));
      wrap.appendChild(head);

      const bar = el('div', 'bar');
      const fill = el('i', c.contribution < 0 ? 'neg' : null);
      fill.style.width = (Math.abs(c.contribution) / maxAbs * 100).toFixed(1) + '%';
      bar.appendChild(fill);
      wrap.appendChild(bar);

      wrap.appendChild(el('div', 'detail', c.detail || ''));
      cBlock.appendChild(wrap);
    });
    body.appendChild(cBlock);
  }

  /* --- registry corroboration --- */
  const rBlock = block('Registry corroboration');
  const matrix = el('div', 'srcmatrix');
  const confirming = String(row.sources_confirming || '').split('|').filter(Boolean);
  const loadedSources = String(row.sources_loaded || '').split('|').filter(Boolean);

  SOURCE_ORDER.forEach((key) => {
    const cell = el('div');
    const distance = row['dist_' + key + '_km'];
    const isLoaded = loadedSources.includes(key);
    const known = isLoaded && distance !== '' && distance !== null;
    if (confirming.includes(key)) cell.className = 'hit';
    if (!isLoaded) cell.className = 'na';
    cell.appendChild(el('div', 's', key === 'eog' ? 'NOAA' : key.toUpperCase()));
    cell.appendChild(el('div', 'd', !isLoaded ? 'n/a' : (known ? num(distance, 1) + ' km' : '-')));
    if (known) {
      // Proximity bar: full within the site, empty at 10 km.
      const prox = el('span', 'prox');
      prox.style.display = 'block';
      const fill = el('i');
      fill.style.width = (Math.max(0, 1 - Number(distance) / 10) * 100).toFixed(0) + '%';
      if (!confirming.includes(key)) fill.style.background = 'var(--dim-2)';
      prox.appendChild(fill);
      cell.appendChild(prox);
      C.tipped(cell, key.toUpperCase() + ': nearest listed facility ' + num(distance, 2) + ' km away'
        + (confirming.includes(key) ? ', inside the 3 km corroboration radius' : ''));
    }
    matrix.appendChild(cell);
  });
  rBlock.appendChild(matrix);

  const siteLink = el('button', 'sitelink', row.nearest_facility_name || '-');
  siteLink.addEventListener('click', () => openSite(row.facility_uid));
  siteLink.disabled = !row.facility_uid;

  rBlock.appendChild(kvList([
    ['Matched site', ''],
    ['Site type', String(row.nearest_facility_type || '-').replace(/_/g, ' ')],
    ['Listed by', String(row.facility_sources || '-').toUpperCase().replace(/\|/g, ' · ')],
    ['Operating status', row.facility_status || 'unknown'],
    ['Capacity', row.facility_capacity_value === '' || !row.facility_capacity_value
      ? '-' : num(row.facility_capacity_value, 0) + ' ' + (row.facility_capacity_unit || '')],
    ['Corroboration score', num(row.corroboration_score)]
  ]));
  const firstValue = rBlock.querySelector('.kv dd');
  if (firstValue) { firstValue.textContent = ''; firstValue.appendChild(siteLink); }

  rBlock.appendChild(el('div', 'note', row.industrial_context || ''));
  body.appendChild(rBlock);

  /* --- physics --- */
  const pBlock = block('Sub-pixel combustion physics');
  const hasTemp = row.est_temp_k !== '' && row.est_temp_k !== null;
  if (hasTemp) {
    const t = Number(row.est_temp_k);
    const thermoRow = el('div', 'thermo');
    const tv = el('div', 'big', String(Math.round(t)));
    tv.style.color = REGIME_COLOR[row.temp_class] || 'var(--accent)';
    thermoRow.appendChild(tv);
    thermoRow.appendChild(el('div', 'unit', 'K'));
    const tc = el('div', 'cls');
    tc.appendChild(el('div', 'label', 'Regime'));
    tc.appendChild(el('div', 'num', TEMP_CLASS_LABEL[row.temp_class] || row.temp_class));
    thermoRow.appendChild(tc);
    pBlock.appendChild(thermoRow);

    const scale = el('div', 'scale');
    const pin = el('div', 'pin');
    pin.style.left = Math.max(0, Math.min(99, (t - 400) / 2100 * 100)).toFixed(1) + '%';
    scale.appendChild(pin);
    pBlock.appendChild(scale);

    const ticks = el('div', 'scale-ticks');
    ['400 K', '900 K', '1400 K', '2500 K'].forEach((label) => ticks.appendChild(el('span', null, label)));
    pBlock.appendChild(ticks);
  }

  const physicsTiles = tiles([
    [num(row.frp, 1) + ' MW', 'Radiative power'],
    [hasTemp && row.est_area_m2 !== '' ? num(row.est_area_m2, 0) + ' m²' : 'n/a', 'Hot area'],
    [num(row.thermal_abnormality), 'Above local baseline', row.thermal_abnormality, '#e05252'],
    [num(row.frp_intensity_norm), 'FRP percentile', row.frp_intensity_norm, '#e2892f']
  ]);
  physicsTiles.style.marginTop = hasTemp ? '10px' : '0';
  pBlock.appendChild(physicsTiles);

  const status = el('div', 'chipset');
  status.appendChild(badge('Retrieval: ' + (row.retrieval_status || 'n/a'),
    row.retrieval_status === 'ok' ? '#4e9e6a' : '#c8973a'));
  pBlock.appendChild(status);

  if (hasTemp && isTrue(row.temp_is_lower_bound)) {
    pBlock.appendChild(el('div', 'note warn', RETRIEVAL_NOTE.saturated_lower_bound));
  } else if (!hasTemp) {
    pBlock.appendChild(el('div', 'note',
      RETRIEVAL_NOTE[row.retrieval_status] ||
      'The bi-spectral retrieval did not converge for this pixel.'));
  }
  body.appendChild(pBlock);

  /* --- behaviour --- */
  const tBlock = block('Temporal behaviour');
  tBlock.appendChild(tiles([
    [String(row.recurrence_days || 0), 'Distinct days'],
    [String(row.detections_in_cell || 0), 'Detections in cell'],
    [num(row.night_fraction), 'Night share', row.night_fraction, '#d6b67a'],
    [num(row.duty_cycle), 'Duty cycle', row.duty_cycle, '#e2892f']
  ], 'four'));

  const life = el('div', 'chipset');
  const flags = [
    [isTrue(row.new_source), 'Newly appeared', '#e05252'],
    [isTrue(row.reactivated), 'Reactivated', '#e2892f'],
    [isTrue(row.ceased), 'Ceased', '#9aa3b1']
  ].filter((f) => f[0]);
  if (flags.length) flags.forEach((f) => life.appendChild(badge(f[1], f[2])));
  else life.appendChild(badge('Steady over the window', '#4e9e6a'));
  tBlock.appendChild(life);

  const days = cellDays(row);
  if (days.some((d) => d.value > 0)) {
    const caption = el('span', 'label', 'Daily peak FRP in this 1 km cell');
    caption.style.cssText = 'display:block;margin:12px 0 6px';
    tBlock.appendChild(caption);
    const holder = el('div', 'daylog');
    C.timeline(holder, days, {
      value: (d) => d.value,
      color: (d) => (d.date === row.acq_date ? '#ff6b2c' : '#e2892f'),
      tip: (d) => (d.count
        ? d.date + ': ' + d.count + ' detection' + (d.count > 1 ? 's' : '') + ', peak ' + d.value.toFixed(1) + ' MW'
        : d.date + ': nothing detected'),
      label: 'Daily peak FRP in this cell'
    });
    tBlock.appendChild(holder);
    const legendRow = el('div', 'daylog-legend');
    [['#e2892f', 'Detected'], ['#ff6b2c', 'This detection'], ['rgba(255,255,255,.25)', 'Quiet day']].forEach(([c, t]) => {
      const span = el('span');
      const i = el('i');
      i.style.background = c;
      span.append(i, document.createTextNode(t));
      legendRow.appendChild(span);
    });
    tBlock.appendChild(legendRow);
  }

  if (isTrue(row.agri_season_context)) {
    tBlock.appendChild(el('div', 'note warn',
      'Inside a crop-residue burning belt during its burning season. The evidence score is discounted accordingly unless the registries or the temperature say otherwise.'));
  }
  body.appendChild(tBlock);

  /* --- context imagery --- */
  const iBlock = block('Ground context');
  const holder = el('div');
  holder.id = 'd-context';
  iBlock.appendChild(holder);
  iBlock.appendChild(el('div', 'note',
    'Esri World Imagery at the detection coordinate. Imagery date differs from the detection date.'));
  body.appendChild(iBlock);

  // Leaflet needs the container to have its final size before it initialises.
  requestAnimationFrame(() => {
    if (!document.body.contains(holder)) return;
    if (contextMap) { contextMap.remove(); contextMap = null; }
    contextMap = L.map(holder, {
      center: [row.latitude, row.longitude], zoom: 15,
      zoomControl: false, attributionControl: false,
      dragging: false, scrollWheelZoom: false, doubleClickZoom: false
    });
    L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 19 }
    ).addTo(contextMap);
    L.circleMarker([row.latitude, row.longitude], {
      radius: 9, color: meta.color, weight: 2, fill: false
    }).addTo(contextMap);

    if (row.nearest_facility_lat) {
      L.circleMarker([row.nearest_facility_lat, row.nearest_facility_lon], {
        radius: 5, color: '#f5efe6', weight: 1.5, fillOpacity: 0.35, fillColor: '#d6b67a'
      }).addTo(contextMap).bindTooltip(row.nearest_facility_name || 'Registered site');
    }
    contextMap.invalidateSize();
  });
}

/* Daily peak FRP for the grid cell this detection sits in, across the whole
   window: the series the persistence and change-point features come from. */
function cellDays(row) {
  const lat = Math.round(row.latitude * 100) / 100;
  const lon = Math.round(row.longitude * 100) / 100;
  const byDate = new Map();
  state.rows.forEach((r) => {
    if (r.grid_lat !== lat || r.grid_lon !== lon) return;
    const cur = byDate.get(r.acq_date) || { value: 0, count: 0 };
    cur.value = Math.max(cur.value, Number(r.frp) || 0);
    cur.count += 1;
    byDate.set(r.acq_date, cur);
  });
  return windowDays().map((date) => Object.assign({ date, value: 0, count: 0 }, byDate.get(date)));
}

/* =========================================================
   SITE VIEW
========================================================= */

function watchButtonLabel(uid) {
  return state.watch.has(uid) ? '★ Watching' : '☆ Watch';
}

function renderWatchCount() {
  $('#watch-count').textContent = String(state.watch.size);
}

async function openSite(uid) {
  if (!uid) return;

  let site;
  try {
    site = await fetch('/api/site/' + encodeURIComponent(uid)).then((r) => r.json());
  } catch (e) {
    return;
  }
  if (!site || site.error) return;

  const identity = site.identity || {};
  const summary = site.summary || {};

  $('#s-title').textContent = identity.name || 'Unnamed site';
  $('#s-sub').textContent = [
    String(identity.ftype || '').replace(/_/g, ' '),
    identity.subnational,
    identity.status
  ].filter(Boolean).join(' · ');

  const watchBtn = $('#s-watch');
  watchBtn.textContent = watchButtonLabel(uid);
  watchBtn.setAttribute('aria-pressed', String(state.watch.has(uid)));
  watchBtn.onclick = () => {
    if (state.watch.has(uid)) state.watch.delete(uid); else state.watch.add(uid);
    saveWatch();
    watchBtn.textContent = watchButtonLabel(uid);
    watchBtn.setAttribute('aria-pressed', String(state.watch.has(uid)));
    renderWatchCount();
    if (state.watchOnly) applyFilters();
  };

  $('#s-export').onclick = () => { window.location.href = '/api/export/site/' + uid + '.csv'; };

  const body = $('#s-body');
  body.innerHTML = '';

  if (summary.detections) {
    const windowLength = summary.window_days || site.daily.length || 1;

    const actBlock = block('Thermal activity in this window');
    actBlock.appendChild(tiles([
      [String(summary.detections), 'Detections'],
      [summary.days_active + ' / ' + windowLength, 'Days active', summary.days_active / windowLength, '#e2892f'],
      [num(summary.max_frp, 1) + ' MW', 'Peak FRP'],
      [summary.max_temp_k ? Math.round(summary.max_temp_k) + ' K' : 'n/a', 'Peak temperature'],
      [num(summary.night_fraction), 'Night share', summary.night_fraction, '#d6b67a'],
      [num(summary.max_risk), 'Highest priority', summary.max_risk, '#e05252']
    ]));
    const seen = el('div', 'note');
    seen.style.marginTop = '8px';
    seen.textContent = 'First seen ' + summary.first_seen + ', last seen ' + summary.last_seen + '.';
    actBlock.appendChild(seen);
    body.appendChild(actBlock);

    const dayBlock = block('Daily log');
    const log = el('div', 'daylog');
    C.timeline(log, site.daily, {
      value: (d) => d.max_frp,
      color: (d) => (d.detections && d.night === d.detections ? '#d6b67a' : '#e2892f'),
      tip: (d) => (d.detections
        ? d.date + ': ' + d.detections + ' detection' + (d.detections > 1 ? 's' : '')
          + ', peak ' + d.max_frp.toFixed(1) + ' MW' + (d.night ? ', ' + d.night + ' at night' : '')
        : d.date + ': nothing detected'),
      label: 'Daily peak FRP at this site'
    });
    dayBlock.appendChild(log);
    const legendRow = el('div', 'daylog-legend');
    [['#e2892f', 'Day or mixed'], ['#d6b67a', 'Night only'], ['rgba(255,255,255,.25)', 'Quiet day']].forEach(([c, t]) => {
      const span = el('span');
      const i = el('i');
      i.style.background = c;
      span.append(i, document.createTextNode(t));
      legendRow.appendChild(span);
    });
    dayBlock.appendChild(legendRow);
    dayBlock.appendChild(el('div', 'note',
      'Every day of the window is shown, quiet ones included, so gaps in activity are real gaps. Bar height is that day\'s peak FRP.'));
    body.appendChild(dayBlock);

    const mixBlock = block('What was seen here');
    const two = el('div', 'two-col');
    const labelsHost = el('div');
    C.donut(labelsHost, CLASS_ORDER.filter((k) => (summary.labels || {})[k]).map((k) => ({
      label: CLASS_META[k].short, value: summary.labels[k], color: CLASS_META[k].color
    })), { size: 104, thickness: 16, sub: 'detections', label: 'Classification at this site' });
    two.appendChild(labelsHost);
    const regimeHost = el('div');
    const regimes = Object.entries(summary.temp_classes || {}).sort((a, b) => b[1] - a[1]);
    if (regimes.length) {
      C.hbars(regimeHost, regimes.map(([k, v]) => ({
        label: TEMP_CLASS_LABEL[k] || k, value: v, color: REGIME_COLOR[k] || '#e2892f'
      })));
    }
    two.appendChild(regimeHost);
    mixBlock.appendChild(two);
    body.appendChild(mixBlock);
  } else {
    const none = block('Thermal activity in this window');
    none.appendChild(el('div', 'note', 'No detections attributed to this site in the current snapshot.'));
    body.appendChild(none);
  }

  const idBlock = block('Registry identity');
  idBlock.appendChild(kvList([
    ['Listed by', String(identity.sources_present || '-').toUpperCase().replace(/\|/g, ' · ')],
    ['Sources agreeing', String(identity.source_agreement || 0)],
    ['Type', String(identity.ftype || '-').replace(/_/g, ' ')],
    ['Operating status', identity.status || 'unknown'],
    ['Capacity', identity.capacity_value
      ? num(identity.capacity_value, 0) + ' ' + (identity.capacity_unit || '') : '-'],
    ['Coordinates', identity.lat
      ? Number(identity.lat).toFixed(4) + ', ' + Number(identity.lon).toFixed(4) : '-'],
    ['Registry records', String(identity.record_count || 0)]
  ]));
  body.appendChild(idBlock);

  if (site.detections && site.detections.length) {
    const listBlock = block('Latest detections at this site');
    site.detections.slice(0, 40).forEach((detection) => {
      const meta = CLASS_META[detection.final_label] || CLASS_META.insufficient_evidence;
      const row = el('button', 'item');
      row.style.borderBottom = '1px solid var(--line)';

      const line = el('div', 'line1');
      const dot = el('span', 'dot');
      dot.style.background = meta.color;
      line.appendChild(dot);
      line.appendChild(el('span', 'cls', detection.acq_date + ' ' +
        String(detection.acq_time).padStart(4, '0') + ' ' + detection.daynight));
      line.appendChild(el('span', 'rank', num(detection.risk_score)));
      row.appendChild(line);

      const facts = el('div', 'facts');
      facts.appendChild(el('span', null, num(detection.frp, 1) + ' MW'));
      if (detection.est_temp_k !== '' && detection.est_temp_k !== null) {
        facts.appendChild(el('span', null, Math.round(detection.est_temp_k) + ' K'));
      }
      facts.appendChild(el('span', null, meta.short));
      row.appendChild(facts);

      row.addEventListener('click', () => {
        $('#site').hidden = true;
        openDetail(detection.detection_id);
      });
      listBlock.appendChild(row);
    });
    body.appendChild(listBlock);
  }

  $('#detail').hidden = true;
  $('#site').hidden = false;
}

function closeSite() {
  $('#site').hidden = true;
}

function closeDetail() {
  detailToken += 1;
  setHighlight(null);
  $('#detail').hidden = true;
  const url = new URL(window.location);
  url.searchParams.delete('detection');
  history.replaceState(null, '', url);
  state.selected = null;
  document.querySelectorAll('.item').forEach((n) => n.setAttribute('aria-selected', 'false'));
  if (contextMap) { contextMap.remove(); contextMap = null; }
}


/* =========================================================
   FACILITY OVERLAY
========================================================= */

async function toggleFacilities(on) {
  if (!on) {
    if (facilityLayer) { map.removeLayer(facilityLayer); facilityLayer = null; }
    return;
  }
  if (facilityLayer) { facilityLayer.addTo(map); return; }

  const response = await fetch('/api/facilities?limit=4000');
  const sites = await response.json();

  facilityLayer = L.layerGroup(sites.map((site) => L.circleMarker([site.lat, site.lon], {
    radius: site.source_agreement > 1 ? 4 : 2.6,
    color: site.source_agreement > 1 ? '#5aa2e8' : '#3d5670',
    weight: 1,
    fillOpacity: 0.25,
    fillColor: '#5aa2e8'
  }).bindTooltip(
    (site.name || 'Unnamed site') + ' · ' + String(site.ftype).replace(/_/g, ' ') +
    ' · ' + String(site.sources_present).toUpperCase().replace(/\|/g, ' ')
  ))).addTo(map);
}


/* =========================================================
   WIRING
========================================================= */

function wireControls() {
  document.querySelectorAll('#maptools .seg button').forEach((btn) => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.base;
      if (key === activeBase) return;
      map.removeLayer(basemaps[activeBase]);
      basemaps[key].addTo(map);
      activeBase = key;
      document.querySelectorAll('#maptools .seg button').forEach((b) => {
        b.setAttribute('aria-pressed', String(b.dataset.base === key));
      });
    });
  });

  const toggle = (node, handler) => node.addEventListener('click', () => {
    const on = node.getAttribute('aria-pressed') !== 'true';
    node.setAttribute('aria-pressed', String(on));
    handler(on);
  });

  toggle($('#t-heat'), (on) => {
    heatOn = on;
    refreshHeat();
  });
  toggle($('#t-facilities'), toggleFacilities);
  toggle($('#t-gibs'), (on) => {
    if (!gibsLayer) {
      const day = (state.stats.date_range && state.stats.date_range[1]) || '2026-08-28';
      gibsLayer = L.tileLayer(gibsUrl(day), {
        attribution: 'NASA EOSDIS GIBS', maxNativeZoom: 8, maxZoom: 20, opacity: 0.75
      });
    }
    if (on) gibsLayer.addTo(map);
    else map.removeLayer(gibsLayer);
  });

  // Every filter change re-clusters the whole snapshot, so typing and
  // dragging wait for a pause instead of redrawing on each keystroke.
  const refilter = debounce(applyFilters, 180);

  $('#search').addEventListener('input', (e) => {
    state.search = e.target.value;
    refilter();
  });

  $('#sort').addEventListener('change', (e) => {
    state.sort = e.target.value;
    applyFilters();
  });

  const groupToggle = $('#group-toggle');
  groupToggle.addEventListener('click', () => {
    state.groupBySite = !state.groupBySite;
    groupToggle.setAttribute('aria-pressed', String(state.groupBySite));
    renderFeed();
  });

  $('#minscore').addEventListener('input', (e) => {
    state.minScore = Number(e.target.value);
    $('#minscore-v').textContent = state.minScore.toFixed(2);
    refilter();
  });

  $('#d-back').addEventListener('click', closeDetail);
  $('#s-back').addEventListener('click', closeSite);

  const watchFilter = $('#watch-filter');
  watchFilter.addEventListener('click', () => {
    state.watchOnly = !state.watchOnly;
    watchFilter.setAttribute('aria-pressed', String(state.watchOnly));
    applyFilters();
  });

  const exportBtn = $('#export-btn');
  const exportMenu = $('#export-menu');
  exportBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = exportMenu.hidden;
    exportMenu.hidden = !open;
    exportBtn.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('click', () => {
    exportMenu.hidden = true;
    exportBtn.setAttribute('aria-expanded', 'false');
  });
  exportMenu.addEventListener('click', (e) => e.stopPropagation());

  // Keyboard: the feed is a listbox, so arrows move and Enter opens.
  $('#feed').addEventListener('keydown', (e) => {
    const items = [...document.querySelectorAll('.item')];
    if (!items.length) return;
    const current = items.findIndex((n) => n.dataset.id === state.selected);

    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = e.key === 'ArrowDown'
        ? Math.min(items.length - 1, current + 1)
        : Math.max(0, current - 1);
      openDetail(items[next].dataset.id);
      items[next].scrollIntoView({ block: 'nearest' });
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!$('#site').hidden) closeSite();
      else if (!$('#detail').hidden) closeDetail();
    }
    if (e.key === '/' && document.activeElement !== $('#search')) {
      e.preventDefault();
      $('#search').focus();
    }
    // Space plays and pauses, unless a control that wants it has focus.
    const tag = document.activeElement ? document.activeElement.tagName : '';
    if (e.key === ' ' && !['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(tag)) {
      e.preventDefault();
      if (play.running) pausePlay(); else startPlay();
    }
  });

  const layerToggle = $('#maptools-toggle');
  layerToggle.addEventListener('click', () => {
    const panel = $('#maptools');
    const open = !panel.classList.contains('open');
    panel.classList.toggle('open', open);
    layerToggle.setAttribute('aria-expanded', String(open));
  });

  wireTimebar();
  wireResize();
  wireSheet();
}

function wireResize() {
  const handle = $('#resize');
  const pane = $('#sidepane');
  let dragging = false;

  handle.addEventListener('mousedown', (e) => { dragging = true; e.preventDefault(); });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const width = Math.min(760, Math.max(330, window.innerWidth - e.clientX));
    pane.style.width = width + 'px';
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    map.invalidateSize();
  });
}

function wireSheet() {
  const pane = $('#sidepane');
  const grab = $('#sheetgrab');
  let startY = null;

  grab.addEventListener('click', () => pane.classList.toggle('open'));

  grab.addEventListener('touchstart', (e) => { startY = e.touches[0].clientY; }, { passive: true });
  grab.addEventListener('touchmove', (e) => {
    if (startY === null) return;
    const dy = e.touches[0].clientY - startY;
    if (Math.abs(dy) < 28) return;
    pane.classList.toggle('open', dy < 0);
    startY = null;
  }, { passive: true });
}


/* =========================================================
   BOOT
========================================================= */

/* /api/map sends columns once, value rows, and lookup tables for repeated
   strings. Rebuild plain row objects here so the rest of the file is
   unaware of the transport format. */
function decodeMap(payload, dayIndex) {
  const cols = payload.columns;
  const dicts = cols.map((c) => (payload.dictionaries || {})[c] || null);
  const loaded = payload.sources_loaded || '';
  const crs = L.CRS.EPSG3857;
  return payload.rows.map((values) => {
    const row = { sources_loaded: loaded };
    for (let i = 0; i < cols.length; i += 1) {
      const v = values[i];
      row[cols[i]] = dicts[i] ? dicts[i][v] : (v === null ? '' : v);
    }
    row.grid_lat = Math.round(row.latitude * 100) / 100;
    row.grid_lon = Math.round(row.longitude * 100) / 100;
    row._d = dayIndex.has(row.acq_date) ? dayIndex.get(row.acq_date) : -1;
    // Zoom-0 pixel position: the canvas layer scales this instead of
    // projecting every point on every frame.
    const px = crs.latLngToPoint(L.latLng(row.latitude, row.longitude), 0);
    row._x = px.x;
    row._y = px.y;
    return row;
  });
}

function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

async function boot() {
  const [stats, sources, payload] = await Promise.all([
    fetch('/api/stats').then((r) => r.json()),
    fetch('/api/sources').then((r) => r.json()),
    fetch('/api/map').then((r) => r.json())
  ]);

  state.watch = loadWatch();
  state.stats = stats;
  state.sources = sources.sources || [];
  state.days = windowDays();
  const dayIndex = new Map(state.days.map((d, i) => [d, i]));
  state.rows = decodeMap(payload, dayIndex);
  state.range = [0, Math.max(state.days.length - 1, 0)];
  state.dayAll = Array.from({ length: state.days.length }, () => []);
  state.rows.forEach((r) => {
    if (r._d >= 0) state.dayAll[r._d].push(r);
    state.classTotals[r.final_label] = (state.classTotals[r.final_label] || 0) + 1;
  });

  renderSources();
  renderWatchCount();
  buildTimeline();
  frameIndia();
  applyFilters();
  wireControls();

  const requested = new URLSearchParams(window.location.search).get('detection');
  if (requested && state.rows.some((r) => r.detection_id === requested)) {
    openDetail(requested);
  }
}

boot().catch((err) => {
  console.error(err);
  $('#feed').appendChild(el('div', 'empty', 'Could not load detections: ' + err.message));
});
