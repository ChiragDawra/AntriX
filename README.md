# AntriX 🇮🇳

## Satellite-based Industrial Anomaly Tracking & Assessment

> **An India-focused satellite intelligence system for detecting, contextualizing, classifying and prioritizing industrial thermal anomalies.**

AntriX fuses **NASA FIRMS (VIIRS/MODIS) satellite fire-detection data** with **OpenStreetMap industrial facility data** to turn a raw stream of thermal detections into a small, ranked set of locations that actually deserve investigation — separating genuine **industrial fires/flaring** from wildfire/agricultural burns and one-off noise.

---

## 🚨 Problem

A satellite thermal sensor can throw off thousands of detections a day. A single detection, by itself, doesn't tell an investigator:

- Whether it's near an industrial facility at all
- Whether it's a one-time event or something recurring
- How strong the thermal signal actually is
- Whether there's enough context to trust a label
- Which detections deserve a human look first

Manually triaging thousands of raw points doesn't scale. AntriX adds **industrial context, spatial reasoning, temporal persistence and evidence-based prioritization** on top of the raw satellite feed.

---

## 💡 What It Does

```text
NASA FIRMS (VIIRS/MODIS)        OSM Overpass (industrial facilities)
        │                                   │
        └───────────────┬───────────────────┘
                         ▼
              Distance + Recurrence
                         │
                         ▼
                Feature Engineering
                         │
                         ▼
          RandomForest Thermal Evidence (ML)
                         │
                         ▼
          Rule-based Contextual Fusion
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
      Industrial Fire      Persistent Industrial Source
              │                     │
              └──────────┬──────────┘
                         │
                         ▼
           Risk Score / Investigation Priority
                         │
                         ▼
          Spatio-temporal Clustering
                         │
                         ▼
           Interactive Leaflet Dashboard
```

The goal isn't just detecting hotspots — it's producing **context-rich, investigation-ready records**.

---

## 🇮🇳 Geographic Scope

Focused on **India**: OSM industrial-facility pull, FIRMS detection window, and the dashboard's state boundaries (`india_states.geojson`) are all India-scoped. The approach generalizes, but the current build and demo target India specifically.

---

## 🛰️ Data Sources

**NASA FIRMS (VIIRS/MODIS)** — `fetch_data_v3.py`. Lat/lon, acquisition date/time, FRP (Fire Radiative Power), brightness, satellite/sensor → `firms_raw.csv`.

**OpenStreetMap (Overpass API)** — `fetch_osm_v3.py`. Industrial facility location, type, name where available → `osm_industrial.json`.

**Historical recurrence** — `compute_recurrence.py` tracks whether a grid cell keeps lighting up across multiple days, separating a one-time anomaly from persistent activity.

---

## 🔥 Core Intelligence — Three Signals, Fused

```text
             THERMAL
        FRP / brightness / abnormality
                   │
SPATIAL ─────── AntriX ─────── TEMPORAL
Facility           │            Recurrence /
distance           │            persistence
                   ▼
           Contextual Evidence
```

1. **Thermal** — FRP deviation from local baseline, brightness channels, ML-scored abnormality.
2. **Spatial** — distance from detection to nearest known industrial facility (`compute_distance.py`).
3. **Temporal** — does similar activity recur at/near the same location across days (`compute_recurrence.py`, `compute_clusters.py`)?

---

## 🧠 Classification

`final_label` in `firms_final.csv` is one of:

- 🔴 **`industrial_fire`** — near an industrial facility, but not yet persistent enough to call it a standing source.
- 🟢 **`persistent_industrial_source`** — thermal activity recurring near a facility across multiple observation days.
- 🟣 **`insufficient_evidence`** — not enough industrial context to classify confidently (e.g. no nearby facility) — deliberately *not* forced into a positive label.

## 🤖 Machine Learning

A **RandomForest classifier** (`train_model_v2.py` → `antrix_model_v2.pkl`) trained on FRP/brightness/scan/track features scores thermal evidence. It's treated as one **evidence signal** feeding `fusion_model_v2.py`, not the sole decision-maker — deterministic rules (facility proximity, recurrence) sit alongside it in `fix_classification_logic.py` / `reclassify_v3.py`. Keeps the final call interpretable instead of a black-box prediction.

## 🎯 Investigation Priority

Classification (*what is it?*) and priority (*what do I look at first?*) are separate layers. `add_risk_score_v2.py` + `fix_priority_formula.py` combine thermal abnormality, persistence and FRP strength into `risk_score` / `risk_level` (Critical/High/Moderate/Low) for triage — independent of `final_label`.

## 🗺️ Interactive Dashboard

Flask + Leaflet (`antrix_app/`), with `leaflet.markercluster` for detection clustering and `turf.js` for spatial helpers. Shows location, facility proximity, thermal stats, recurrence, classification, evidence level and risk — one map instead of raw tables.

---

## 🛠️ Tech Stack

| Layer | Tools |
|---|---|
| Data | NASA FIRMS API (VIIRS/MODIS), OSM Overpass API |
| Processing | pandas, numpy, geopandas, osmnx |
| ML | scikit-learn (RandomForest), joblib |
| Backend | Flask |
| Geospatial / Frontend | Leaflet.js, Leaflet.markercluster, Turf.js, GeoJSON |
| Static reporting | Folium, Jupyter |

---

## 📁 Repository Structure

```text
AntriX/
├── run_pipeline.py           # runs the whole processing chain + starts the web app
├── fetch_data*.py            # NASA FIRMS ingestion (v1-v3)
├── fetch_osm*.py              # OSM Overpass ingestion (v1-v3)
├── compute_distance.py       # fire -> nearest industrial facility distance
├── compute_recurrence.py     # per-grid-cell recurrence over time
├── compute_clusters.py       # spatio-temporal clustering
├── label_data.py              # rule-based labeling
├── train_model*.py           # RandomForest training (v1-v2)
├── fusion_model*.py          # ML + rule score fusion (v1-v2)
├── add_risk_score*.py / fix_priority_formula.py   # risk_score / risk_level
├── add_facility_details.py / add_nearest_facility_coords.py
├── fix_classification_logic.py / reclassify_v3.py  # final_label / evidence_level
├── make_map*.py               # standalone Folium HTML maps
├── *.csv, *.json, *.pkl       # pipeline data artifacts + trained model
├── cache/                     # cached API responses
└── antrix_app/
    ├── app.py                 # Flask API serving detections/clusters/stats
    ├── firms_final.csv, clusters.csv
    └── templates/
        ├── index.html         # Leaflet dashboard
        └── ANTRIX_Visual_Intelligence_Report.ipynb
```

Scripts with `_v2`/`_v3` suffixes supersede earlier same-name scripts (kept for history) — `run_pipeline.py` always runs the latest of each.

---

## 🚀 Installation & Run

### Requirements

Python 3.9+. macOS ships a system-managed Python that blocks `pip install` directly — use a venv.

### 1. Set up environment

```bash
python3 -m venv venv
source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Run every command below with this venv activated.

### 2. Get a NASA FIRMS API key

`fetch_data_v2.py` / `fetch_data_v3.py` use a FIRMS `MAP_KEY` hardcoded in the script. Get a free key at https://firms.modaps.eosdis.nasa.gov/api/ and drop it into the script before running. (Don't commit your own key to a public repo — see **Security** below.)

### 3. Fetch raw data

```bash
python fetch_data_v3.py    # NASA FIRMS fire detections -> firms_raw.csv
python fetch_osm_v3.py     # OSM industrial facilities  -> osm_industrial.json
```

### 4. Run the pipeline + web app in one command

```bash
python run_pipeline.py
```

Runs distance → recurrence → labeling → ML training → fusion scoring → facility enrichment → risk scoring → classification → clustering, copies results into `antrix_app/`, and starts Flask at **http://localhost:5000**.

`python run_pipeline.py --no-serve` runs the pipeline only.

<details>
<summary>Pipeline steps in order (see <code>run_pipeline.py</code>)</summary>

```bash
python compute_distance.py
python compute_recurrence.py
python label_data.py
python train_model_v2.py
python fusion_model_v2.py
python add_facility_details.py
python add_nearest_facility_coords.py
python add_risk_score_v2.py
python fix_priority_formula.py
python fix_classification_logic.py
python reclassify_v3.py
python compute_clusters.py
```

Optional sanity checks: `check_labels.py`, `verify_facility_data_integrity.py`, `inspect_low_evidence_fires.py`.

</details>

### 5. Run the web app on its own

Once `firms_final.csv` / `clusters.csv` exist in `antrix_app/` (done automatically by `run_pipeline.py`):

```bash
cd antrix_app
python app.py
```

Open **http://localhost:5000**. Endpoints:

- `GET /api/detections` — full fire records with scores/labels
- `GET /api/clusters` — clustered hotspot groups
- `GET /api/stats` — counts by classification

### 6. (optional) Static map / report

```bash
python make_map_v2.py
jupyter notebook antrix_app/templates/ANTRIX_Visual_Intelligence_Report.ipynb
```

### 🏁 Quick Start (data already generated)

```bash
cd antrix_app
python3 -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install flask pandas gunicorn
python app.py
```

`firms_final.csv` / `clusters.csv` already sit in `antrix_app/` from the last pipeline run — no need to re-fetch or re-train for a demo.

---

## ⚠️ Data & Operational Considerations

AntriX is a **decision-support / investigation-prioritization** tool, not a verdict machine. A classification isn't proof of an incident on its own — satellite readings are affected by cloud cover, sensor limitations, revisit frequency, spatial resolution and geolocation uncertainty. Treat output as a ranked queue for human verification, not an automated finding.

---

## 🔐 Security

- `fetch_data_v2.py` / `fetch_data_v3.py` currently hardcode the FIRMS `MAP_KEY` in source. Before pushing to a public repo, move it to an environment variable (`.env`, git-ignored) and read it with `os.environ`.
- Don't commit API keys, tokens or credentials.
- Add `venv/`, `cache/`, `__pycache__/`, `.env` to `.gitignore` (see below).

---

## 🌍 Future Scope

Additional sensors, more frequent ingestion, expanded industrial datasets, better temporal modelling, automated alerting, cloud/edge deployment, multi-region coverage.

---

## 👥 Project Information

**Project:** AntriX
**Focus:** India 🇮🇳
**Domain:** Satellite Intelligence / Geospatial Analytics / Machine Learning

---

## 📄 License

Add a license here before public distribution. Until then, don't assume the code is freely reusable.

---

**From satellite observations to investigation-ready intelligence. 🇮🇳**
