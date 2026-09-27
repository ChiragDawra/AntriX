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
  insufficient_evidence:        { label: 'Insufficient evidence',        short: 'Insufficient', color: '#656e7d' }
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
  below_background: 'The 3.7 µm channel is not meaningfully above the local background — no hot component to solve for.',
  no_bracket: 'No physical solution inside the 400–2500 K search range.',
  unconstrained: 'The solution sat against the edge of the search range, which means the observation does not pin it down.',
  saturated_lower_bound: 'VIIRS I4 saturated at 367 K. The retrieved temperature is a floor, not an estimate — the true fire is at least this hot.',
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
  watchOnly: false
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
  ? '—' : Number(v).toFixed(d);


/* =========================================================
   MAP
========================================================= */

const map = L.map('map', {
  zoomControl: false,
  preferCanvas: true,        // 400+ vector markers stay smooth
  attributionControl: true
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
basemaps.dark.addTo(map);
let activeBase = 'dark';

/* NASA GIBS VIIRS corrected reflectance: the same imagery family the FIRMS
   detections come from, pinned to the snapshot's last day so the picture and
   the data always describe the same moment. */
function gibsUrl(date) {
  return 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/' +
    'VIIRS_NOAA20_CorrectedReflectance_TrueColor/default/' + date +
    '/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg';
}
let gibsLayer = null;

const markerLayer = L.markerClusterGroup({
  maxClusterRadius: 44,
  spiderfyOnMaxZoom: true,
  showCoverageOnHover: false,
  disableClusteringAtZoom: 11,
  iconCreateFunction(cluster) {
    const n = cluster.getChildCount();
    const size = n < 10 ? 28 : n < 50 ? 34 : 40;
    return L.divIcon({
      html: '<div style="width:' + size + 'px;height:' + size + 'px;border-radius:50%;' +
        'background:rgba(21,25,32,.92);border:1px solid #323a45;color:#e7eaef;' +
        'display:grid;place-items:center;font-family:\'IBM Plex Mono\',monospace;' +
        'font-size:' + (n < 100 ? 12 : 11) + 'px">' + n + '</div>',
      className: '',
      iconSize: [size, size]
    });
  }
}).addTo(map);

let heatLayer = null;
let facilityLayer = null;
const markerById = new Map();

function radiusFor(frp) {
  const f = Number(frp) || 0;
  return Math.max(3.4, Math.min(11, 3.4 + Math.sqrt(f) * 1.5));
}

function drawMarkers(rows) {
  markerLayer.clearLayers();
  markerById.clear();

  const markers = rows.map((row) => {
    const meta = CLASS_META[row.final_label] || CLASS_META.insufficient_evidence;
    const marker = L.circleMarker([row.latitude, row.longitude], {
      radius: radiusFor(row.frp),
      color: meta.color,
      weight: 1.2,
      opacity: 0.95,
      fillColor: meta.color,
      fillOpacity: row.final_label === 'insufficient_evidence' ? 0.22 : 0.5
    });
    marker.on('click', () => openDetail(row.detection_id));
    markerById.set(row.detection_id, marker);
    return marker;
  });

  markerLayer.addLayers(markers);
}

function buildHeat(rows) {
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }
  const points = rows.map((r) => [r.latitude, r.longitude, Math.min(1, (Number(r.frp) || 0) / 20)]);
  heatLayer = L.heatLayer(points, {
    radius: 22, blur: 18, maxZoom: 10, minOpacity: 0.25,
    gradient: { 0.2: '#3b4252', 0.45: '#7fa05a', 0.7: '#e2892f', 1: '#ff6b2c' }
  });
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

function applyFilters() {
  const f = filterState();

  state.filtered = state.rows.filter((row) => {
    if (!state.classes.has(row.final_label)) return false;
    if ((Number(row.risk_score) || 0) < f.minScore) return false;

    if (f.sources.length) {
      const confirming = String(row.sources_confirming || '').split('|').filter(Boolean);
      if (!f.sources.some((s) => confirming.includes(s))) return false;
    }

    if (state.watchOnly && !state.watch.has(row.facility_uid)) return false;

    if (f.search) {
      const name = String(row.nearest_facility_name || '').toLowerCase();
      if (!name.includes(f.search)) return false;
    }
    return true;
  });

  const key = state.sort;
  state.filtered.sort((a, b) => {
    if (key === 'acq_date') return String(b.acq_date).localeCompare(String(a.acq_date));
    const av = Number(a[key]); const bv = Number(b[key]);
    // Rows with no value for the sort key belong at the bottom, not the top.
    if (Number.isNaN(av) && Number.isNaN(bv)) return 0;
    if (Number.isNaN(av)) return 1;
    if (Number.isNaN(bv)) return -1;
    return bv - av;
  });

  drawMarkers(state.filtered);
  buildHeat(state.filtered);
  if ($('#t-heat').getAttribute('aria-pressed') === 'true' && heatLayer) heatLayer.addTo(map);

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
  const qs = params.toString();
  return qs ? '?' + qs : '';
}

function updateExportLinks() {
  const qs = exportQuery();
  $('#ex-csv').href = '/api/export/detections.csv' + qs;
  $('#ex-geojson').href = '/api/export/detections.geojson' + qs;
}


/* =========================================================
   RENDER — metrics, sources, chips, feed
========================================================= */

function renderMetrics() {
  const s = state.stats;
  // Phone columns are ~108px wide, so the desktop wording would be clipped
  // mid-word. Shorter labels are used rather than smaller text.
  const narrow = window.innerWidth <= 860;
  const cells = [
    ['persistent_industrial_source', narrow ? 'Persistent' : 'Persistent source', s.persistent_industrial_source],
    ['industrial_fire', narrow ? 'Industrial' : 'Industrial fire', s.industrial_fire],
    ['flare_signature', narrow ? 'Flare' : 'Flare signature', s.flare_signature],
    ['agricultural_burning', narrow ? 'Agri' : 'Agricultural', s.agricultural_burning],
    ['insufficient_evidence', narrow ? 'Insuff.' : 'Insufficient', s.insufficient_evidence]
  ];

  const host = $('#metrics');
  host.innerHTML = '';

  cells.forEach(([key, label, value]) => {
    const cell = el('div', 'metric');
    cell.appendChild(el('div', 'v', value === undefined ? '—' : String(value)));
    const k = el('div', 'k');
    const dot = el('span', 'dot');
    dot.style.background = CLASS_META[key].color;
    k.appendChild(dot);
    k.appendChild(document.createTextNode(label));
    cell.appendChild(k);
    host.appendChild(cell);
  });

  const extra = [
    [s.multi_source_confirmed, narrow ? '2+ sources' : 'Confirmed 2+ sources'],
    [s.temperature_retrieved, narrow ? 'Temp.' : 'Temp. retrieved'],
    [s.registry_sites, narrow ? 'Sites' : 'Registry sites']
  ];
  extra.forEach(([value, label]) => {
    const cell = el('div', 'metric');
    cell.appendChild(el('div', 'v', value === undefined ? '—' : String(value)));
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
      btn.title = info.label + ' — ' + info.records + ' records · ' + info.license;
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
  state.rows.forEach((r) => { counts[r.final_label] = (counts[r.final_label] || 0) + 1; });

  host.innerHTML = '';
  CLASS_ORDER.forEach((key) => {
    if (!counts[key]) return;
    const meta = CLASS_META[key];
    const chip = el('button', 'chip');
    chip.setAttribute('aria-pressed', String(state.classes.has(key)));

    const dot = el('span', 'dot');
    dot.style.background = meta.color;
    chip.appendChild(dot);
    chip.appendChild(document.createTextNode(meta.short));
    chip.appendChild(el('span', 'n', String(counts[key])));

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
    cell.title = key.toUpperCase() + (confirming.includes(key) ? ' — confirms'
      : loaded.includes(key) ? ' — no facility within 3 km' : ' — registry not loaded');
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

  const rows = state.groupBySite ? groupBySite(state.filtered) : state.filtered;

  $('#feedcount').textContent = state.groupBySite
    ? rows.length + ' sites · ' + state.filtered.length + ' detections'
    : state.filtered.length + ' of ' + state.rows.length + ' detections';

  if (!rows.length) {
    host.appendChild(el('div', 'empty', 'No detections match these filters.'));
    return;
  }

  const fragment = document.createDocumentFragment();

  rows.slice(0, 400).forEach((row) => {
    const meta = CLASS_META[row.final_label] || CLASS_META.insufficient_evidence;
    const item = el('button', 'item');
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

    item.addEventListener('click', () => openDetail(row.detection_id));
    fragment.appendChild(item);
  });

  host.appendChild(fragment);

  if (rows.length > 400) {
    host.appendChild(el('div', 'empty',
      'Showing the 400 highest-ranked. Export the CSV for all ' + rows.length + '.'));
  }
}


/* =========================================================
   DETAIL
========================================================= */

let contextMap = null;

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

function openDetail(id) {
  const row = state.rows.find((r) => r.detection_id === id);
  if (!row) return;

  state.selected = id;
  document.querySelectorAll('.item').forEach((node) => {
    node.setAttribute('aria-selected', String(node.dataset.id === id));
  });

  const meta = CLASS_META[row.final_label] || CLASS_META.insufficient_evidence;
  $('#d-title').textContent = row.nearest_facility_name || 'Unnamed site';
  $('#d-title').style.color = 'var(--text)';
  $('#d-sub').innerHTML = '';
  const sub = $('#d-sub');
  const clsSpan = el('span', null, meta.label);
  clsSpan.style.color = meta.color;
  sub.appendChild(clsSpan);
  sub.appendChild(document.createTextNode(
    ' · ' + row.acq_date + ' ' + String(row.acq_time).padStart(4, '0') + ' UTC' +
    ' · ' + Number(row.latitude).toFixed(4) + ', ' + Number(row.longitude).toFixed(4)
  ));

  $('#d-export').onclick = () => {
    if (row.facility_uid) window.location.href = '/api/export/site/' + row.facility_uid + '.csv';
  };
  $('#d-export').disabled = !row.facility_uid;

  const body = $('#d-body');
  body.innerHTML = '';

  /* --- priority --- */
  const scoreBlock = block('Investigation priority');
  const thermo = el('div', 'thermo');
  const big = el('div', 'big', num(row.risk_score));
  thermo.appendChild(big);
  thermo.appendChild(el('div', 'unit', '/ 1.00'));
  const rl = el('div', 'cls');
  rl.appendChild(el('div', 'label', 'Risk level'));
  rl.appendChild(el('div', 'num', row.risk_level || '—'));
  thermo.appendChild(rl);
  scoreBlock.appendChild(thermo);
  scoreBlock.appendChild(kvList([
    ['Anomaly probability', num(row.anomaly_probability)],
    ['Evidence score', num(row.evidence_score) + ' (' + (row.evidence_level || 'n/a') + ')'],
    ['Model probability', row.ml_industrial_prob === '' ? 'not trained' : num(row.ml_industrial_prob)],
    ['Unsupervised anomaly', num(row.unsupervised_anomaly)]
  ]));
  body.appendChild(scoreBlock);

  /* --- contributions --- */
  let contributions = [];
  try { contributions = JSON.parse(row.contributions || '[]'); } catch (e) { contributions = []; }

  if (contributions.length) {
    const cBlock = block('What produced this score');
    const maxAbs = Math.max(...contributions.map((c) => Math.abs(c.contribution)), 0.001);

    contributions.forEach((c) => {
      const wrap = el('div', 'contrib');
      const top = el('div', 'top');
      top.appendChild(el('span', null, c.label));
      top.appendChild(el('span', 'w', (c.contribution >= 0 ? '+' : '') + c.contribution.toFixed(3)));
      wrap.appendChild(top);

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
    if (confirming.includes(key)) cell.className = 'hit';
    if (!isLoaded) cell.className = 'na';
    cell.appendChild(el('div', 's', key === 'eog' ? 'NOAA' : key.toUpperCase()));
    cell.appendChild(el('div', 'd',
      !isLoaded ? 'n/a' : (distance === '' || distance === null ? '—' : num(distance, 1) + ' km')));
    matrix.appendChild(cell);
  });
  rBlock.appendChild(matrix);

  const siteLink = el('button', 'sitelink', row.nearest_facility_name || '—');
  siteLink.addEventListener('click', () => openSite(row.facility_uid));
  siteLink.disabled = !row.facility_uid;

  rBlock.appendChild(kvList([
    ['Matched site', ''],
    ['Site type', String(row.nearest_facility_type || '—').replace(/_/g, ' ')],
    ['Listed by', String(row.facility_sources || '—').toUpperCase().replace(/\|/g, ' · ')],
    ['Operating status', row.facility_status || 'unknown'],
    ['Capacity', row.facility_capacity_value === '' || !row.facility_capacity_value
      ? '—' : num(row.facility_capacity_value, 0) + ' ' + (row.facility_capacity_unit || '')],
    ['Corroboration score', num(row.corroboration_score)]
  ]));
  // Swap the placeholder cell for the clickable site name.
  const firstValue = rBlock.querySelector('.kv dd');
  if (firstValue) { firstValue.textContent = ''; firstValue.appendChild(siteLink); }

  rBlock.appendChild(el('div', 'note', row.industrial_context || ''));
  body.appendChild(rBlock);

  /* --- physics --- */
  const pBlock = block('Sub-pixel combustion physics');
  if (row.est_temp_k !== '' && row.est_temp_k !== null) {
    const t = Number(row.est_temp_k);
    const thermoRow = el('div', 'thermo');
    const tv = el('div', 'big', Math.round(t));
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

    pBlock.appendChild(kvList([
      ['Hot area', row.est_area_m2 === '' ? '—' : num(row.est_area_m2, 0) + ' m²'],
      ['Fire radiative power', num(row.frp, 2) + ' MW'],
      ['Retrieval', row.retrieval_status || '—']
    ]));

    if (row.temp_is_lower_bound === true || row.temp_is_lower_bound === 'True') {
      pBlock.appendChild(el('div', 'note warn', RETRIEVAL_NOTE.saturated_lower_bound));
    }
  } else {
    pBlock.appendChild(kvList([
      ['Fire radiative power', num(row.frp, 2) + ' MW'],
      ['Retrieval', row.retrieval_status || '—']
    ]));
    pBlock.appendChild(el('div', 'note',
      RETRIEVAL_NOTE[row.retrieval_status] ||
      'The bi-spectral retrieval did not converge for this pixel.'));
  }
  body.appendChild(pBlock);

  /* --- behaviour --- */
  const tBlock = block('Temporal behaviour');
  tBlock.appendChild(kvList([
    ['Distinct days detected', String(row.recurrence_days || 0)],
    ['Detections in cell', String(row.detections_in_cell || 0)],
    ['Night fraction', num(row.night_fraction)],
    ['Duty cycle', num(row.duty_cycle)],
    ['FRP vs local baseline', num(row.thermal_abnormality)],
    ['Lifecycle', [
      row.new_source === true || row.new_source === 'True' ? 'newly appeared' : null,
      row.reactivated === true || row.reactivated === 'True' ? 'reactivated' : null,
      row.ceased === true || row.ceased === 'True' ? 'ceased' : null
    ].filter(Boolean).join(', ') || 'steady']
  ]));

  const series = cellSeries(row);
  if (series.length > 1) tBlock.appendChild(sparkline(series));

  if (row.agri_season_context === true || row.agri_season_context === 'True') {
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

  $('#detail').hidden = false;
  if (window.innerWidth <= 860) $('#sidepane').classList.add('open');

  // Leaflet needs the container to have its final size before it initialises.
  requestAnimationFrame(() => {
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
        radius: 5, color: '#5aa2e8', weight: 1.5, fillOpacity: 0.3, fillColor: '#5aa2e8'
      }).addTo(contextMap).bindTooltip(row.nearest_facility_name || 'Registered site');
    }
    contextMap.invalidateSize();
  });

  const marker = markerById.get(id);
  if (marker) map.setView([row.latitude, row.longitude], Math.max(map.getZoom(), 9));

  // Deep link, so a detection can be sent to someone rather than described.
  const url = new URL(window.location);
  url.searchParams.set('detection', id);
  history.replaceState(null, '', url);
}

/* Daily FRP for the grid cell this detection sits in — the series the
   persistence and change-point features are computed from. */
function cellSeries(row) {
  const lat = Math.round(row.latitude * 100) / 100;
  const lon = Math.round(row.longitude * 100) / 100;
  const byDate = new Map();
  state.rows.forEach((r) => {
    if (Math.round(r.latitude * 100) / 100 !== lat) return;
    if (Math.round(r.longitude * 100) / 100 !== lon) return;
    const key = r.acq_date;
    byDate.set(key, Math.max(byDate.get(key) || 0, Number(r.frp) || 0));
  });
  return [...byDate.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

function sparkline(series) {
  const w = 360, h = 44, pad = 4;
  const max = Math.max(...series.map((s) => s[1]), 1);
  const stepX = series.length > 1 ? (w - pad * 2) / (series.length - 1) : 0;

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
  svg.setAttribute('class', 'spark');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Daily peak FRP for this cell');

  const points = series.map((s, i) => [
    pad + i * stepX,
    h - pad - (s[1] / max) * (h - pad * 2)
  ]);

  const path = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  path.setAttribute('points', points.map((p) => p.join(',')).join(' '));
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', '#e2892f');
  path.setAttribute('stroke-width', '1.4');
  svg.appendChild(path);

  points.forEach(([x, y], i) => {
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', '2');
    c.setAttribute('fill', '#e2892f');
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = series[i][0] + ' — ' + series[i][1].toFixed(2) + ' MW';
    c.appendChild(title);
    svg.appendChild(c);
  });

  return svg;
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

  const site = await fetch('/api/site/' + uid).then((r) => r.json());
  if (site.error) return;

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

  const idBlock = block('Registry identity');
  idBlock.appendChild(kvList([
    ['Listed by', String(identity.sources_present || '—').toUpperCase().replace(/\|/g, ' · ')],
    ['Sources agreeing', String(identity.source_agreement || 0)],
    ['Type', String(identity.ftype || '—').replace(/_/g, ' ')],
    ['Operating status', identity.status || 'unknown'],
    ['Capacity', identity.capacity_value
      ? num(identity.capacity_value, 0) + ' ' + (identity.capacity_unit || '') : '—'],
    ['Coordinates', identity.lat
      ? Number(identity.lat).toFixed(4) + ', ' + Number(identity.lon).toFixed(4) : '—'],
    ['Registry records', String(identity.record_count || 0)]
  ]));
  body.appendChild(idBlock);

  if (summary.detections) {
    const actBlock = block('Thermal activity in this window');
    actBlock.appendChild(kvList([
      ['Detections', String(summary.detections)],
      ['Days active', String(summary.days_active)],
      ['First seen', summary.first_seen],
      ['Last seen', summary.last_seen],
      ['Peak FRP', num(summary.max_frp, 2) + ' MW'],
      ['Peak retrieved temperature', summary.max_temp_k ? Math.round(summary.max_temp_k) + ' K' : 'not retrieved'],
      ['Night fraction', num(summary.night_fraction)],
      ['Highest priority', num(summary.max_risk)]
    ]));
    body.appendChild(actBlock);

    const dayBlock = block('Daily activity');
    const max = Math.max(...site.daily.map((d) => d.max_frp), 1);
    const bars = el('div', 'daybars');
    const labels = el('div', 'daylabels');

    site.daily.forEach((day) => {
      const col = el('div', 'col');
      const fill = el('i', day.night === day.detections ? 'night' : null);
      fill.style.height = Math.max(3, (day.max_frp / max) * 100) + '%';
      fill.title = day.date + ' — ' + day.detections + ' detections, peak '
        + day.max_frp.toFixed(2) + ' MW';
      col.appendChild(fill);
      bars.appendChild(col);
      labels.appendChild(el('span', null, day.date.slice(5)));
    });

    dayBlock.appendChild(bars);
    dayBlock.appendChild(labels);
    dayBlock.appendChild(el('div', 'note',
      'Bar height is that day\'s peak FRP. Purple means every detection that day was at night.'));
    body.appendChild(dayBlock);

    const listBlock = block('Detections at this site');
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
  } else {
    const none = block('Thermal activity in this window');
    none.appendChild(el('div', 'note', 'No detections attributed to this site in the current snapshot.'));
    body.appendChild(none);
  }

  $('#detail').hidden = true;
  $('#site').hidden = false;
}

function closeSite() {
  $('#site').hidden = true;
}

function closeDetail() {
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
      // Keep detections above the newly added tile layer.
      markerLayer.bringToFront();
    });
  });

  const toggle = (node, handler) => node.addEventListener('click', () => {
    const on = node.getAttribute('aria-pressed') !== 'true';
    node.setAttribute('aria-pressed', String(on));
    handler(on);
  });

  toggle($('#t-heat'), (on) => {
    if (!heatLayer) buildHeat(state.filtered);
    if (on) heatLayer.addTo(map); else map.removeLayer(heatLayer);
  });
  toggle($('#t-facilities'), toggleFacilities);
  toggle($('#t-gibs'), (on) => {
    if (!gibsLayer) {
      const day = (state.stats.date_range && state.stats.date_range[1]) || '2026-08-28';
      gibsLayer = L.tileLayer(gibsUrl(day), {
        attribution: 'NASA EOSDIS GIBS', maxNativeZoom: 8, maxZoom: 20, opacity: 0.75
      });
    }
    if (on) { gibsLayer.addTo(map); markerLayer.bringToFront(); }
    else map.removeLayer(gibsLayer);
  });

  $('#search').addEventListener('input', (e) => {
    state.search = e.target.value;
    applyFilters();
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
    applyFilters();
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
  });

  const layerToggle = $('#maptools-toggle');
  layerToggle.addEventListener('click', () => {
    const panel = $('#maptools');
    const open = !panel.classList.contains('open');
    panel.classList.toggle('open', open);
    layerToggle.setAttribute('aria-expanded', String(open));
  });

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

async function boot() {
  const [stats, sources, rows] = await Promise.all([
    fetch('/api/stats').then((r) => r.json()),
    fetch('/api/sources').then((r) => r.json()),
    fetch('/api/detections').then((r) => r.json())
  ]);

  state.watch = loadWatch();
  state.stats = stats;
  state.sources = sources.sources || [];
  state.rows = rows;

  $('#p-snap').textContent = stats.snapshot_id || '—';
  $('#p-range').textContent = stats.date_range
    ? stats.date_range[0] + ' → ' + stats.date_range[1] : '—';
  $('#p-method').textContent = 'v' + (stats.method_version || '—');
  $('#p-build').textContent = stats.build || '—';

  renderMetrics();
  renderSources();
  renderWatchCount();
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
