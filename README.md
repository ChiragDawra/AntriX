# SATAT

**Satellite-based Industrial Anomaly Tracking & Assessment**

SATAT turns NASA FIRMS thermal detections over India into a ranked, evidence-
backed list of industrial sites worth investigating — and, just as importantly,
says plainly when it cannot tell.

It does three things a hotspot map does not:

1. **Cross-references four independent facility registries** (OpenStreetMap,
   WRI Global Power Plant Database, Global Energy Monitor, NOAA EOG flare
   inventory) instead of trusting one. Every detection carries which registries
   corroborate it.
2. **Retrieves sub-pixel combustion temperature** from the two thermal channels,
   so a 1600 K gas flare is separated from a 700 K stubble fire on physics
   rather than on how close the nearest factory happens to be.
3. **Reports its own limits.** Where the observation does not constrain a
   temperature, no temperature is reported. Where no registry lists anything
   nearby, no industrial claim is made.

---

## The problem

A VIIRS overpass can return thousands of thermal detections a day over India. A
single detection does not tell an investigator whether it is near industry,
whether it recurs, how hot it actually burned, or whether anyone should care.
In October and November the signal is swamped by crop-residue burning.

Manual triage does not scale. SATAT adds spatial corroboration, combustion
physics, temporal behaviour and an explicit evidence trail on top of the raw
feed.

---

## Architecture

```text
  NASA FIRMS                 OSM        WRI GPPD      GEM trackers    NOAA EOG
  VIIRS + MODIS           Overpass    (1,589 IND)   (2,272 IND)      flares
       │                      └───────────┬──────────────┴──────────────┘
       │                                  │
 clean_detections.py                build_registry.py
 confidence · India clip ·      normalise · cross-source match ·
 cross-sensor dedup             3,838 distinct sites, 363 multi-source
       │                                  │
       └───────────────┬──────────────────┘
                       │
                  satat/ pipeline
                       │
   physics.py     bi-spectral Dozier retrieval  -> temperature, hot area
   temporal.py    recurrence, night fraction, duty cycle, change points
   baseline.py    robust median/MAD baselines   -> abnormality
   context.py     crop-burning region × season mask
   join.py        per-registry distance         -> corroboration score
   anomaly.py     evidence score + calibrated ML + IsolationForest/LOF
   classify.py    five classes, with explicit insufficient-evidence
   explain.py     signed per-component contributions
   cluster.py     spatio-temporal clustering
                       │
        firms_final.csv · clusters.csv · data_snapshot.json
                       │
         Flask dashboard + JSON/CSV/GeoJSON API
```

---

## The four registries

| Source | What it contributes | India records | Licence |
| --- | --- | --- | --- |
| **OpenStreetMap** (Overpass) | Long-tail coverage: unnamed industrial estates, foundries, works. Area geometry. Inconsistent, which is why it is cross-checked. | 16,299 | ODbL 1.0 |
| **WRI Global Power Plant Database** | Every commissioned power plant with capacity, fuel, owner, commissioning year. | 1,589 | CC BY 4.0 |
| **Global Energy Monitor** | Coal, oil & gas and steel plant trackers — capacity, operating status, blast-furnace / DRI / coking capacity. Country-wide, unlike OSM. | 2,272 | CC BY 4.0 |
| **NOAA EOG global flare inventory** | Per-site catalogued gas flares with flared volume and radiant heat. | requires a free account — see below | EOG, Colorado School of Mines |

Co-located records from different registries are collapsed into one
`facility_uid`, so a site three registries agree on is visibly different
evidence from a lone OSM polygon.

### NOAA EOG, honestly

EOG's download host requires a free account and is not always reachable. The
adapter tries it, and otherwise imports a file you drop at
`data/raw/eog_flares.csv` (or `.xlsx`) — any recent EOG release; the column
aliases it accepts are listed in `sources/eog.py`.

If neither is available the source reports `unavailable`, the dashboard shows
the NOAA filter greyed out with the reason, and the corroboration score
normalises over the registries that *did* load, so nobody's score is penalised
for a missing source. **No rows are ever invented to fill the gap.** The
flare-detection capability itself does not depend on it: `flare_signature` is
reached from the retrieved temperature, using the same physics EOG's Nightfire
method is built on.

---

## What makes the abnormality analysis more than a threshold

**Sub-pixel temperature (`satat/physics.py`).** FIRMS reports brightness
temperature, not fire temperature. A 375 m pixel containing a 30 m flare at
1800 K and a 100 m stubble fire at 700 K can report the same brightness
temperature. Treating the pixel as a hot fraction *p* at temperature *T* against
a background gives two equations in two unknowns; eliminating *p* leaves one
equation solved by bisection. Validated against synthetic pixels in
`tests/test_physics.py`, which recover the input temperature to within 2%.

The retrieval refuses to answer when the observation does not constrain it —
the 11 µm channel flat against background, or the solution pinned to the edge
of the search range. An earlier version returned those as confident 2400 K
"flares"; now they are reported as `weak_11um` and carry no temperature.

Two limits, stated up front. FIRMS publishes the two I-band channels; EOG's
Nightfire uses several short-wave M-bands that constrain high temperatures far
better, and VIIRS I4 saturates at 367 K, above which the retrieval returns a
floor. The hottest sources are therefore the ones SATAT is least able to pin
down from this feed, and a given snapshot can legitimately contain zero
`flare_signature` detections.

**Robust baselines (`satat/baseline.py`).** The previous build divided each
detection's FRP by the *mean* FRP of its grid cell. With one detection in a
cell, a detection is its own baseline and its abnormality is always zero.
Median and MAD, with a cell → region → scene fallback and a floor on the
spread, fix both that and the opposite failure where measurement noise reads
as a multi-sigma event.

**Temporal signature (`satat/temporal.py`).** Night fraction, duty cycle,
inter-arrival regularity and a change-point statistic. A flare burns day and
night, every overpass; a stubble fire burns once, in the afternoon.

**Seasonal context (`satat/context.py`).** Crop-residue belts and the months
they burn in. Without it the system reports an industrial emergency across
Punjab every November.

**Three scores, fused (`satat/anomaly.py`).** An interpretable weighted
evidence score, a calibrated RandomForest, and an unsupervised
IsolationForest/LOF pair that owes nothing to the labels. The weak labels come
from registry corroboration and the calendar, while the model only sees
physics and timing — so it has something real to learn instead of a
restatement of its own input.

**Explanations (`satat/explain.py`).** Every detection carries the signed
contribution each component made to its score, rendered in the evidence panel.

---

## Classification

| Class | Reached when |
| --- | --- |
| `persistent_industrial_source` | High anomaly probability, three or more distinct days |
| `industrial_fire` | Above the industrial threshold, registry-corroborated |
| `flare_signature` | Flare-range retrieved temperature, recurring, corroborated |
| `agricultural_burning` | In a crop-burning belt in season, biomass-range temperature, no registry support |
| `insufficient_evidence` | Nothing in any registry within 10 km — whatever the thermal signal looks like |

That last rule is deliberate and inherited from the earlier build: without a
facility, there is no industrial claim to make.

---

## Measured, not asserted

`/validation` recomputes everything from the current snapshot.

SATAT has no field-verified ground truth — nobody has visited these
coordinates. What is measurable is whether thermal physics and timing *alone*
predict something they were never shown: whether a detection sits on a site two
or more independent registries agree exists.

On the September 2026 snapshot: **ROC AUC 0.815**, recall 0.802, precision
0.436, five-fold out-of-fold.

The registry ablation, same detections scored against different subsets:

| Registries | Corroborated | Median distance to a registered site |
| --- | --- | --- |
| OSM | 334 | 22.6 km |
| WRI | 126 | 14.2 km |
| GEM | 217 | 13.6 km |
| OSM + WRI + GEM | **427** | **4.9 km** |

No single source gets close. That is the argument for cross-referencing four of
them, stated as a measurement.

---

## Running it

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export FIRMS_MAP_KEY=your_key      # https://firms.modaps.eosdis.nasa.gov/api/

python run_pipeline.py             # fetch → clean → registry → analyse → evaluate → serve
```

Individually:

```bash
python fetch_data_v3.py            # NASA FIRMS, 5-day window over India
python clean_detections.py         # confidence filter, India clip, dedup
python build_registry.py           # the four registries -> data/registry/
python run_analysis.py             # physics, timing, scoring, classification
python evaluate.py                 # cross-validation + ablation
cd antrix_app && python app.py     # dashboard on :5000
```

`build_registry.py` caches its downloads; pass `--force` to refresh, or
`--no-fetch` to build from what is already in `data/raw/`.

### Tests

```bash
pytest                             # 57 tests
playwright install chromium        # once, for the browser tests
```

Covers the retrieval against synthetic pixels of known temperature, the
cross-source matching, the feature maths, every API filter and export, and the
dashboard under real phone emulation — a resized desktop window does not
reproduce what a phone does, and two layout bugs in an earlier build only
appeared under proper device emulation.

---

## API

Full reference at `/api/docs`. Everything on screen is available as CSV and
GeoJSON, filtered identically — the server reuses one filter implementation, so
an export always matches the screen it came from.

```bash
curl "localhost:5000/api/export/detections.csv?label=persistent_industrial_source&sources=gem,wri&min_score=0.5"
curl "localhost:5000/api/sources"                    # per-registry status and licensing
curl "localhost:5000/api/site/F00123"                # one facility's full history
```

`/data-dictionary` documents every emitted column.

---

## Repository

```text
satat/              analysis package — one stage per file, one author per column
sources/            registry adapters, one per upstream dataset
antrix_app/         Flask app, dashboard, API
tests/              pytest suite including Playwright browser tests
legacy/             the v2 script chain this replaced, kept for provenance
data/registry/      the built registry (committed; raw downloads are not)
IMPROVEMENTS.md     the upgrade plan this build worked through
```

---

## Attribution

- NASA FIRMS (VIIRS/MODIS) — NASA EOSDIS
- OpenStreetMap contributors — ODbL 1.0
- WRI Global Power Plant Database — CC BY 4.0
- Global Energy Monitor trackers — CC BY 4.0
- NOAA EOG / Payne Institute, Colorado School of Mines
- Basemaps: Esri; imagery overlay: NASA EOSDIS GIBS
