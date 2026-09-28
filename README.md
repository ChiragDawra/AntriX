# SATAT

**Satellite-based Industrial Anomaly Tracking & Assessment**

SATAT turns NASA FIRMS satellite fire detections over India into a ranked,
evidence-backed list of industrial thermal sources worth investigating, and
says plainly when it cannot tell.

**Live:** <https://satat-arhc.onrender.com/> - Dashboard, Validation, Columns, API

Current snapshot: **45,498 detections** from four satellite sensors over
**120 days (2026-06-01 to 2026-09-28)**, cross-referenced against **3,838
facilities** from three independent registries.

Where a hotspot map shows a dot, SATAT shows a case:

1. **Which registries place industry there.** Distance to the nearest facility
   in OpenStreetMap, the WRI Global Power Plant Database and Global Energy
   Monitor, and which of them confirm it within 3 km.
2. **How hot it actually burned.** A sub-pixel temperature retrieval from the
   two thermal channels, so a small very hot source is told apart from a large
   cool one, and no temperature at all when the data do not constrain one.
3. **How it behaves over time.** For every 1 km cell: on how many of the 120
   days it burned, how much of that at night, whether it is new, stopped, or
   came back, and a day-by-day replay of the whole window.
4. **Why it ranks where it does.** An investigation priority with the signed
   contribution of each piece of evidence, and an explicit *insufficient
   evidence* class when nothing supports an industrial reading.

---

## The problem

VIIRS and MODIS flag hundreds to thousands of hot pixels over India every day.
A raw detection is a coordinate, a brightness temperature and a fire radiative
power (FRP). It does not say whether the source is a steel plant, a gas flare,
a forest fire or crop burning, whether it recurs, or whether anyone should
look at it. In October and November the signal is swamped by crop-residue
burning.

Checking each detection by hand does not scale. SATAT adds industrial context,
combustion physics, temporal behaviour and an explicit evidence trail on top
of the raw feed, and ranks the result.

---

## The website

Every page shares one top bar: logo, page links, the snapshot id and the
build that is running.

### Dashboard

- **Map** on satellite imagery (terrain optional). Detections are grouped
  into rings whose coloured arc shows the mix of classes inside; zoom in and
  they split into individual detections sized by FRP. Detections stacked on
  one spot list themselves in a popup.
- **Date window** in the top bar: two handles over a strip of detections per
  day, with 7 / 30 / 90-day presets. The map, feed, counts and exports all
  follow it.
- **Playback**: replays the window one day at a time. The day's detections
  glow, the previous week fades out behind them and earlier days remain as a
  faint trace, so a plant that burns every night reads as a steady pulse and
  a crop fire as a single flash. The feed becomes a live list for the day
  shown. Pause, stop, 1x/2x/4x, click the strip to jump, space to toggle.
- **Metric strip**: counts per class, detections confirmed by two or more
  registries, temperatures retrieved, registry sites, for the chosen window
  (or the day being played).
- **Registry filters** (OSM, WRI, GEM; NOAA EOG shown as not loaded, with the
  reason), **class chips**, facility-name search, sort (priority, evidence,
  temperature, FRP, most recent, corroboration), minimum priority, group by
  site, a per-browser watchlist.
- **Layers**: thermal density, all registry sites, NASA VIIRS true-colour
  imagery for the last day of the snapshot.
- **Detection case file** (click a card or a dot): priority gauge with
  anomaly probability, evidence score, model probability and unsupervised
  anomaly; *What produced this score*; per-registry distances with proximity
  bars and the matched site; retrieved temperature on a 400-2500 K scale with
  regime, hot area, abnormality and retrieval status; temporal tiles,
  lifecycle badges and a 120-day chart of the 1 km cell; a satellite
  close-up. The URL is shareable (`?detection=<id>`).
- **Site view** (click the matched site): days active out of 120, peak FRP
  and temperature, night share, a daily log of every day in the window
  (quiet days included), class and regime breakdowns, registry identity, the
  latest detections, and a CSV of everything seen there.
- **Export**: detections as CSV or GeoJSON, clusters, the facility registry,
  all filtered exactly like the screen.

### Validation, Columns, API

- **Validation** (`/validation`): classifier metrics, confusion matrix,
  retrieval coverage, detections per day, registry ablation, classification
  and combustion-regime breakdowns, registry composition, the features the
  model sees, and the limits of what any of it measures.
- **Columns** (`/data-dictionary`): every output column, what it means, and a
  live profile of how it is distributed in this snapshot.
- **API** (`/api/docs`): every endpoint and filter, with a *Try* button that
  calls the live service.

The dashboard works on phones (bottom sheet, two-row top bar). Basemap tiles,
imagery overlays and fonts are its only third-party requests, and none of them
is load-bearing: with all of them blocked, the detections, feed and case files
still work.

---

## Current snapshot

| | |
| --- | --- |
| Window | 2026-06-01 to 2026-09-28 (120 days) |
| Sensors | VIIRS on NOAA-21, NOAA-20, Suomi NPP; MODIS on Terra and Aqua |
| Raw detections | 81,926 |
| After cleaning | 45,498 unique fire-days |
| Registry | 20,160 source records -> 3,838 sites, 363 listed by two or more registries |
| Sites with detections | 2,362 |
| Confirmed by 2+ registries | 5,003 detections |
| Temperature retrieved | 26,029 (57.2%) |
| Classes | persistent industrial 2,881 · industrial fire 7,803 · flare 1 · agricultural 0 · insufficient evidence 34,813 |
| Priority | Critical 663 · High 3,344 · Moderate 13,491 · Low 28,000 |

No agricultural burning appears because June to September falls outside the
configured crop-burning months (April-May, October-November).

---

## Architecture

```text
 NASA FIRMS downloads          OpenStreetMap   WRI GPPD    GEM trackers   NOAA EOG
 data/firms/DL_FIRE_*.zip        (Overpass)    (1,589)      (2,272)      (not loaded)
 VIIRS x3 + MODIS                     └────────────┬──────────┴─────────────┘
        │                                          │
 load_firms_archive.py                      build_registry.py
 (or fetch_data_v3.py for the live API)     normalise · cross-source match
        │                                   3,838 sites, 363 multi-source
 clean_detections.py                               │
 confidence · India clip · cross-sensor dedup      │
        └──────────────────┬───────────────────────┘
                           │
                     satat/ pipeline
   physics.py    bi-spectral Dozier retrieval      -> temperature, hot area
   baseline.py   robust median/MAD baselines        -> abnormality
   temporal.py   recurrence, night fraction, duty cycle, change points,
                 lifecycle flags scaled to the window
   context.py    crop-burning region x season mask
   join.py       per-registry distance              -> corroboration score
   anomaly.py    evidence score + calibrated Random Forest + IsolationForest/LOF
   classify.py   five classes, including insufficient evidence
   explain.py    signed per-component contributions
   cluster.py    spatio-temporal clusters (3 km, 5 days)
                           │
   antrix_app/firms_final.csv.gz · clusters.csv · data_snapshot.json
   analysis_report.json · validation_report.json (evaluate.py)
                           │
   Flask: dashboard + Validation / Columns / API pages + JSON/CSV/GeoJSON API
```

---

## The registries

| Source | What it contributes | India records | Status | Licence |
| --- | --- | --- | --- | --- |
| **OpenStreetMap** (Overpass) | Long-tail coverage: industrial estates, works, foundries, power plants, refineries, with area geometry. Queried over eight industrial belts (Bokaro-Jamshedpur, Chennai-Ennore, Mumbai, Odisha mining, Chhattisgarh steel, NCR Delhi, Gujarat refineries, Vizag-Paradip), not the whole country. | 16,299 | loaded | ODbL 1.0 |
| **WRI Global Power Plant Database** | Every commissioned power plant with capacity and fuel. | 1,589 | loaded | CC BY 4.0 |
| **Global Energy Monitor** | Coal Plant, Oil & Gas Plant and Steel Plant trackers, with operating status and capacity. | 2,272 | loaded | CC BY 4.0 |
| **NOAA EOG flare inventory** | Catalogued gas flares. | 0 | **not loaded** (see below) | EOG, Colorado School of Mines |

Co-located records from different registries collapse into one
`facility_uid`, so a site three registries agree on is visibly different
evidence from a lone OSM polygon.

**NOAA EOG.** Its download host requires a free account. The adapter tries
`SATAT_EOG_URL`, and otherwise imports a file dropped at
`data/raw/eog_flares.csv` (or `.xlsx`). Without either the source reports
`unavailable`, the dashboard greys it out with the reason, and the
corroboration score normalises over the registries that did load, so no score
is lowered by a missing source. No rows are invented to fill the gap.

---

## The analysis

**Sub-pixel temperature (`satat/physics.py`).** FIRMS reports brightness
temperature, not fire temperature: a 375 m pixel containing a small 1,800 K
flare and one containing a large 700 K fire can look the same. Treating the
pixel as a hot fraction at temperature *T* against a background gives two
equations in two unknowns, solved by bisection. The retrieval refuses to
answer when the observation does not constrain it (`weak_11um`, `no_bracket`,
`below_background`), and flags a floor rather than a value when VIIRS I4
saturates at 367 K (`saturated_lower_bound`). In this snapshot it returns a
temperature for 57% of detections. Validated against synthetic pixels in
`tests/test_physics.py`.

**Robust baselines (`satat/baseline.py`).** Median and MAD per 1 km cell, with
region and scene fallbacks and a floor on the spread, give each detection a
robust z-score against its own place.

**Temporal signature (`satat/temporal.py`).** Distinct days, night fraction,
duty cycle, inter-arrival regularity and a change-point statistic per 1 km
cell. Thresholds scale with the window: persistence saturates at 15 distinct
days, and the new / ceased / reactivated flags use fractions of the window,
so four months of cloudy spells do not read as constant reactivation.

**Seasonal context (`satat/context.py`).** Crop-residue belts and their
burning months, so the system does not report an industrial emergency across
Punjab every November.

**Three scores, fused (`satat/anomaly.py`).**
- *Evidence score*: a fixed, arguable weighted sum: registry corroboration
  0.30, combustion physics 0.25, persistence 0.20, intensity 0.15, night 0.10.
- *Model probability*: a calibrated Random Forest trained on weak labels from
  registry distance and the calendar, while seeing only physics and timing
  (FRP, robust z, temperature, hot fraction, recurrence, night fraction, duty
  cycle, change-point shift). It has something real to learn instead of a
  restatement of its own input.
- *Unsupervised anomaly*: Isolation Forest and LOF, rank-averaged, owing
  nothing to the labels.
- *Anomaly probability* = 0.55 evidence + 0.30 model + 0.15 unsupervised.

**Investigation priority.** A different question from "is it industrial":
0.45 anomaly probability + 0.25 abnormality + 0.20 persistence + 0.10
intensity, plus 0.05 for a newly appeared source. Bands: Critical 0.75,
High 0.55, Moderate 0.35, Low below.

**Explanations (`satat/explain.py`).** Every detection carries the signed
contribution of each component, shown as *What produced this score*.

---

## Classification

Evaluated in order; the first matching rule wins. "Near a registry" means at
least one registry has a facility within 3 km.

| Class | Reached when |
| --- | --- |
| `agricultural_burning` | Not near a registry, nearest site over 10 km, inside a crop-burning region in season; or the seasonal penalty applied (in season, biomass-range or unknown temperature, weak corroboration) |
| `insufficient_evidence` | Not near a registry and nearest site over 10 km, whatever the thermal signal looks like |
| `flare_signature` | Flare-range temperature (1,400 K or more) on two or more days, near a registry |
| `persistent_industrial_source` | Anomaly probability 0.62 or more, on three or more distinct days |
| `industrial_fire` | Anomaly probability 0.42 or more |
| `insufficient_evidence` | Otherwise |

Without a facility nearby there is no industrial claim to make, however hot
the detection. The most intense detection in the current snapshot (407.8 MW,
retrieved 1,704 K) is classed *insufficient evidence* for exactly that reason.

---

## Measured, not asserted

`/validation` is recomputed by `evaluate.py` from the current snapshot.

SATAT has **no field-verified ground truth**: nobody has visited these
coordinates to confirm what was burning. What can be measured is whether
thermal physics and timing *alone* predict something they were never shown:
whether a detection sits on a site two or more independent registries agree
exists. Positives: within 1 km of the matched site, with two or more
registries within 3 km, out of crop season (2,822 detections in 248 grid
cells). Negatives: more than 10 km from any registered site (23,873 detections
in 19,189 cells).

Cross-validation holds out **whole 1 km grid cells**, so no site is scored by
a model that trained on its other detections. Over four months that matters:
splitting by row let the same plant sit in training and testing at once and
inflated the AUC to 0.99.

| Metric | Value |
| --- | --- |
| ROC AUC | **0.951** |
| Average precision | 0.659 |
| Precision / recall (threshold 0.5) | 0.579 / 0.729 |
| F1 | 0.645 |

These numbers measure agreement between the physics and the registries, not
accuracy against confirmed industrial activity.

Registry ablation, the same detections scored against different registries:

| Registries | Detections corroborated | Median distance to a registered site |
| --- | --- | --- |
| OSM | 8,052 | 138.8 km |
| WRI | 3,226 | 19.6 km |
| GEM | 6,662 | 23.7 km |
| OSM + WRI + GEM | **11,740** | **11.1 km** |

No single source comes close, which is the case for cross-referencing them,
stated as a measurement.

---

## Running it

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Multi-month data (what the live site uses): put the FIRMS download zips
# (DL_FIRE_*.zip, one per sensor) in data/firms/, then
python run_pipeline.py --from-archive

# Or the live FIRMS API (last few days)
export FIRMS_MAP_KEY=your_key      # https://firms.modaps.eosdis.nasa.gov/api/
python run_pipeline.py
```

The dashboard starts on <http://localhost:5001>. `--no-serve` skips it,
`--skip-fetch` reuses `firms_raw.csv`, `--refresh-registry` re-downloads the
registries.

Individually:

```bash
python load_firms_archive.py       # data/firms/*.zip -> firms_raw.csv
python fetch_data_v3.py            # or: the FIRMS API, a few days over India
python clean_detections.py         # confidence filter, India clip, dedup
python build_registry.py           # the registries -> data/registry/ (--force, --no-fetch)
python run_analysis.py             # physics, timing, scoring, classification
python evaluate.py                 # grouped cross-validation + ablation
cd antrix_app && python app.py     # dashboard on :5001 (PORT overrides)
```

Environment variables: `FIRMS_MAP_KEY` (API route), `SATAT_EOG_URL` (NOAA
EOG), `PORT`, `SATAT_WARM=0` (skip the start-up cache warm-up).

### Tests

```bash
playwright install chromium        # once, for the browser tests
pytest                             # 65 tests
```

They cover the retrieval against synthetic pixels of known temperature, the
cross-source matching, the feature maths including long-window behaviour, the
grouped cross-validation, every API filter and export, the compact map
payload, the site daily log, the date window and playback, and the dashboard
under real phone emulation.

---

## API

Read-only, no key. Full reference with live *Try* buttons at `/api/docs`.

| Endpoint | Returns |
| --- | --- |
| `/api/detections` | Filtered detections with the evidence columns |
| `/api/detection/<id>` | One detection, every column, contributions parsed |
| `/api/site/<facility_uid>` | One facility: identity, summary, a daily log for every day of the window, latest detections |
| `/api/map` | The compact, column-oriented payload the map draws (gzipped) |
| `/api/clusters` | Spatio-temporal clusters |
| `/api/facilities` | The cross-referenced registry (`source`, `bbox`, `limit`) |
| `/api/sources` | Per-registry status, record counts and licences |
| `/api/stats` | Snapshot id, date range, counts, method version, running build |
| `/api/export/detections.csv` · `.geojson` | Every column, filtered |
| `/api/export/clusters.csv` · `/api/export/facilities.csv` | Clusters; registry |
| `/api/export/site/<facility_uid>.csv` | Every detection at one site |

Filters for detections and their exports: `label`, `sources`, `risk`,
`temp_class`, `min_score`, `min_fusion`, `from`, `to`, `bbox`, `q`. The server
uses one filter implementation for JSON and exports, so a download always
matches the screen it came from.

```bash
curl "https://satat-arhc.onrender.com/api/export/detections.csv?label=persistent_industrial_source&sources=gem,wri&min_score=0.5" -o sites.csv
curl "https://satat-arhc.onrender.com/api/site/F00071"      # ArcelorMittal Nippon Steel Hazira
```

---

## Performance

- The map loads one gzipped, column-oriented payload (about 1.5 MB for 45k
  detections) with repeated strings sent once; full records load per click.
- Clustering uses a Supercluster index rebuilt in a fraction of a second when
  filters change, and only what is in view is drawn (clusters as icons,
  single detections on one canvas). Pan and zoom redraw in about 20 ms and a
  playback frame in about 10 ms.
- The server parses the snapshot and builds its page summaries in a
  background thread at start-up, so the first visitor after a deploy does not
  wait for them.

---

## Deployment

The live site runs on Render from `main` (`antrix_app/`, `gunicorn app:app`).
The top bar and `/api/stats` show the commit that is actually running:

```bash
curl -s https://satat-arhc.onrender.com/api/stats | grep -o '"build":"[^"]*"'
```

If it is not the commit you expect, the deploy has not happened yet.

---

## Repository

```text
satat/               analysis package: one stage per file, one author per column
sources/             registry adapters, one per upstream dataset
antrix_app/          Flask app: dashboard, reference pages, API
  templates/         index (dashboard), validation, data_dictionary, api_docs,
                     _base / _appbar (shared shell)
  static/            dashboard.js, charts.js, shell/pages/charts CSS, vendor/
data/firms/          FIRMS download archives the snapshot was built from
data/registry/       the built registry (committed; raw downloads are not)
tests/               pytest suite including Playwright browser tests
legacy/              the earlier script chain, kept for provenance
DEMO_FACT_SHEET.md   current facts for presenting the project
IMPROVEMENTS.md      the upgrade plan the v3 build worked through
```

---

## Attribution

- NASA FIRMS (VIIRS, MODIS) - NASA EOSDIS
- OpenStreetMap contributors - ODbL 1.0
- WRI Global Power Plant Database - CC BY 4.0
- Global Energy Monitor trackers - CC BY 4.0
- NOAA EOG / Payne Institute, Colorado School of Mines
- Basemaps: Esri; imagery overlay: NASA EOSDIS GIBS
- Map libraries: Leaflet, Leaflet.heat, Supercluster (ISC, Mapbox)
