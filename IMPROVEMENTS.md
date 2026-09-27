# SATAT — SIH Upgrade Plan

Status: `[x]` done and verified · `[~]` partly done · `[ ]` not started

Baseline before this work: FIRMS + OSM only, a single-ratio "thermal
abnormality", no export, purple-gradient glassmorphism UI, no source
provenance, no test suite.

Verification is recorded per item. Nothing is marked `[x]` on the strength of
"the code looks right".

---

## A. Four-source facility registry

- [x] **A1** `sources/` package with one normalized facility schema
      — `sources/schema.py`; enforced by `schema.finalize()`, covered by
      `tests/test_registry.py::test_finalize_enforces_schema_and_drops_out_of_country`
- [x] **A2** OSM adapter, with refinery / flare / cement / smelter tags added
      to the original six — **16,299 India records**
- [x] **A3** WRI Global Power Plant Database, live pull from the WRI repo
      — **1,589 India plants** with capacity, fuel, owner, commissioning year
- [x] **A4** GEM adapter — coal, oil & gas and steel trackers via their Zenodo
      releases — **2,272 India records** (1,977 coal units, 115 gas/oil, 180
      steel plants)
- [x] **A5** NOAA EOG adapter — tries the official host, imports a local drop,
      otherwise reports `unavailable` with the reason. The host is currently
      unreachable from this network (TCP connect timeout), so the dashboard
      shows the NOAA filter disabled and says why. **No rows invented.**
- [x] **A6** `build_registry.py` → `facilities.csv`, `facility_groups.csv`,
      `registry_manifest.json` with per-source status, counts and licensing
- [x] **A7** Cross-source matching — **20,160 source records → 3,838 distinct
      sites, 363 confirmed by more than one registry**. Tested for merge,
      non-merge, type incompatibility and name-based matching beyond the tight
      radius.

## B. Detection ↔ registry join

- [x] **B1** Per-source distances via a BallTree. The old code ran 7M
      interpreted haversine calls per pipeline run and scaled quadratically;
      this is one vectorised query per source.
- [x] **B2** `sources_confirming` + `corroboration_score`, normalised over the
      registries that actually loaded so a missing source penalises nobody
- [x] **B3** Matched-facility attributes attached — the evidence panel now
      names *ArcelorMittal Nippon Steel Hazira Plant, 9,600 ttpa, operating*
      instead of "near industrial zone"

## C. Abnormality engine v3

- [x] **C1** Robust median/MAD baselines with cell → region → scene fallback
      and a floor on the spread. Tested: a lone spike among five quiet
      detections now scores 1.0 where the old mean-ratio scored it 0.
- [x] **C2** Bi-spectral sub-pixel temperature and area (Dozier). Recovers
      synthetic fires from 600 K to 1800 K to within 2%
      (`tests/test_physics.py`). Two bugs found and fixed while testing: a
      fixed lower search bound that reported ordinary fires as `no_bracket`,
      and a mutated loop variable that marked every solution `unconstrained`.
- [x] **C3** Night fraction, duty cycle, inter-arrival regularity, CUSUM shift
- [x] **C4** Crop-residue region × season mask, applied only when the
      temperature is biomass-like *and* no registry corroborates
- [x] **C5** IsolationForest + LOF, rank-averaged
- [x] **C6** Calibrated fusion — evidence 0.55 / model 0.30 / unsupervised
      0.15, with weight redistributed rather than zero-filled when a component
      is unavailable
- [x] **C7** Signed per-component contributions on every detection, rendered as
      bars with a plain-language reason for each
- [x] **C8** `new_source` / `reactivated` / `ceased`
- [x] **C9** `method_version` and `snapshot_id` on every row

Also done, not in the original plan:

- [x] The retrieval now **declines to answer** when the observation does not
      constrain it (`weak_11um`, `below_background`, `no_bracket`,
      `saturated_lower_bound`). An earlier version returned those as confident
      2400 K flares.
- [x] Two new classes: `flare_signature` and `agricultural_burning`

## D. Export & API

- [x] **D1** `/api/export/detections.csv` honouring every filter. One filter
      implementation serves the JSON and the CSV, and a test asserts they
      return the same rows.
- [x] **D2** `/api/export/clusters.csv`, `/api/export/facilities.csv`
- [x] **D3** `/api/export/detections.geojson`
- [x] **D4** `/api/export/site/<facility_uid>.csv` — the investigation packet
      for one plant
- [x] **D5** `/api/docs`
- [x] **D6** `/api/sources` — status, counts, licensing, and the reason for any
      registry that did not load

## E. UI

- [x] **E1** New token set: graphite surfaces, one thermal-amber accent, no
      gradient, no glow, no glassmorphism
- [x] **E2** Mono tabular numerics throughout, real label hierarchy
- [x] **E3** Flat surfaces, single hairline weight
- [x] **E4** Four source toggles with live counts and a disabled state that
      explains itself
- [x] **E5** Evidence panel: contribution bars, corroboration matrix with
      per-registry distances, temperature scale, FRP sparkline
- [x] **E6** Export menu wired to the CSV and GeoJSON endpoints
- [x] **E7** Visible focus rings, aria roles, keyboard feed navigation,
      `/` to search, Escape to close
- [x] **E8** Verified under **real iPhone 13 device emulation** — no
      horizontal scroll, 38px minimum tap targets, collapsible layer panel,
      bottom sheet
- [x] **E9** Canvas renderer, feed capped at 400 rows, DOMContentLoaded under
      4 s asserted in a test

Also done:

- [x] Deep links — `?detection=<id>` opens that detection, so one can be sent
      to someone rather than described

## F. Credibility extras

- [x] **F1** `/validation` — five-fold out-of-fold metrics with a confusion
      matrix (**AUC 0.815**, recall 0.802) and a nine-configuration registry
      ablation showing the median detection move from **22.6 km to 4.9 km**
      from a registered site
- [x] **F2** Per-site view: registry identity, daily activity bars, full
      detection history, site CSV — `/api/site/<uid>`
- [x] **F3** Watchlist, per-browser, with a feed filter. Survives reload;
      tested.
- [x] **F4** Every third-party host blocked in a test — detections, feed and
      evidence panel all still work; only basemap tiles are lost
- [x] **F5** `/data-dictionary` — every emitted column
- [x] **F6** **57 tests**: physics against synthetic pixels, registry matching,
      feature maths, every API filter and export, and ten browser tests
- [x] **F7** README rewritten around the multi-source architecture

## Housekeeping

- [x] The 13-script chain that each rewrote `firms_final.csv` moved to
      `legacy/` with an explanation; `satat/` replaces it with named stages
- [x] `run_pipeline.py` rewritten for the new stage order
- [x] `requirements.txt` split: full for the pipeline, minimal for deployment
- [x] Response caching keyed on file mtime — the app no longer re-parses the
      detections CSV on every request

---

## Known limits, stated deliberately

1. **NOAA EOG is not loaded.** Its host refuses connections from this network
   and the download needs a free account. The adapter imports a dropped file
   the moment one exists.
2. **No field-verified ground truth.** The validation page measures whether
   physics and timing predict multi-registry agreement, and says so rather
   than quoting an accuracy figure it cannot support.
3. **High temperatures are the hardest to retrieve.** FIRMS publishes two
   I-band channels; EOG's Nightfire uses several short-wave M-bands. With I4
   saturating at 367 K, a snapshot can legitimately contain zero
   `flare_signature` detections.
