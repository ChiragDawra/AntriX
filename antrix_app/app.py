"""SATAT dashboard and data API.

Everything the browser shows comes from here, and everything here is also
available as CSV or GeoJSON, because a dashboard an investigator cannot get
their data out of is a demo, not a tool.
"""

from __future__ import annotations

import gzip
import io
import json
import os
from pathlib import Path

import pandas as pd
from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__)

BASE = Path(__file__).resolve().parent

# Multi-month snapshots ship gzipped; a plain CSV is still accepted.
DETECTIONS_FILE = next(
    (p for p in (BASE / "firms_final.csv.gz", BASE / "firms_final.csv") if p.exists()),
    BASE / "firms_final.csv.gz",
)
CLUSTERS_FILE = BASE / "clusters.csv"
FACILITIES_FILE = BASE / "facility_groups.csv"
SNAPSHOT_FILE = BASE / "data_snapshot.json"
MANIFEST_FILE = BASE / "registry_manifest.json"
REPORT_FILE = BASE / "analysis_report.json"
VALIDATION_FILE = BASE / "validation_report.json"

# Which commit this instance is actually running. Render sets
# RENDER_GIT_COMMIT automatically. Without this there is no way to tell a
# deployed fix from a deploy that silently never happened -- which is
# exactly what went wrong once: the fix was pushed, the service kept
# serving the previous build, and the only way to notice was diffing the
# served HTML byte for byte.
BUILD_COMMIT = (os.environ.get("RENDER_GIT_COMMIT") or "local")[:7]

SOURCE_KEYS = ["osm", "wri", "gem", "eog"]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

_cache: dict[str, tuple[float, object]] = {}


def _load(path: Path, loader):
    """Read a file once and keep it, re-reading only when it changes on disk.

    The previous version re-parsed a 166 KB CSV on every single API call,
    including the two calls the dashboard makes on every page load. Keying the
    cache on mtime means a pipeline rerun is still picked up without a restart.
    """
    if not path.exists():
        return None
    stamp = path.stat().st_mtime
    hit = _cache.get(str(path))
    if hit and hit[0] == stamp:
        return hit[1]
    value = loader(path)
    _cache[str(path)] = (stamp, value)
    return value


def detections() -> pd.DataFrame:
    df = _load(DETECTIONS_FILE, lambda p: pd.read_csv(p, low_memory=False))
    return df if df is not None else pd.DataFrame()


def clusters() -> pd.DataFrame:
    df = _load(CLUSTERS_FILE, pd.read_csv)
    return df if df is not None else pd.DataFrame()


def facilities() -> pd.DataFrame:
    df = _load(FACILITIES_FILE, pd.read_csv)
    return df if df is not None else pd.DataFrame()


def _read_json(path: Path, default):
    value = _load(path, lambda p: json.loads(p.read_text()))
    return value if value is not None else default


def snapshot() -> dict:
    return _read_json(SNAPSHOT_FILE, {"snapshot_id": "unknown", "generated_at": "unknown"})


def manifest() -> dict:
    return _read_json(MANIFEST_FILE, {"sources": {}})


def analysis_report() -> dict:
    return _read_json(REPORT_FILE, {})


def validation_report() -> dict:
    return _read_json(VALIDATION_FILE, {})


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------

def apply_filters(df: pd.DataFrame, args) -> pd.DataFrame:
    """Apply the query-string filters shared by the JSON and CSV endpoints.

    One implementation for both so an exported CSV always matches what the
    screen is showing -- the thing an investigator is most likely to assume
    and least likely to check.
    """
    if df.empty:
        return df

    out = df

    labels = args.get("label", "").strip()
    if labels:
        wanted = {v.strip() for v in labels.split(",") if v.strip()}
        out = out[out["final_label"].isin(wanted)]

    risk = args.get("risk", "").strip()
    if risk:
        wanted = {v.strip() for v in risk.split(",") if v.strip()}
        out = out[out["risk_level"].isin(wanted)]

    temp = args.get("temp_class", "").strip()
    if temp:
        wanted = {v.strip() for v in temp.split(",") if v.strip()}
        out = out[out["temp_class"].isin(wanted)]

    # Source filter: keep detections corroborated by ANY of the named
    # registries. Selecting all four is not the same as no filter -- it
    # excludes detections no registry corroborates at all.
    sources = args.get("sources", "").strip()
    if sources:
        wanted = [s.strip() for s in sources.split(",") if s.strip() in SOURCE_KEYS]
        if wanted:
            confirming = out["sources_confirming"].fillna("")
            mask = False
            for source in wanted:
                mask = mask | confirming.str.split("|").apply(lambda v: source in v)
            out = out[mask]

    for field, column in (("min_score", "risk_score"), ("min_fusion", "fusion_score")):
        value = args.get(field)
        if value not in (None, ""):
            try:
                out = out[out[column] >= float(value)]
            except ValueError:
                pass

    date_from, date_to = args.get("from"), args.get("to")
    if date_from:
        out = out[out["acq_date"] >= date_from]
    if date_to:
        out = out[out["acq_date"] <= date_to]

    bbox = args.get("bbox", "").strip()
    if bbox:
        try:
            lon_min, lat_min, lon_max, lat_max = (float(v) for v in bbox.split(","))
            out = out[
                out["latitude"].between(lat_min, lat_max)
                & out["longitude"].between(lon_min, lon_max)
            ]
        except ValueError:
            pass

    query = args.get("q", "").strip().lower()
    if query:
        out = out[out["nearest_facility_name"].fillna("").str.lower().str.contains(query)]

    return out


def _csv_response(df: pd.DataFrame, filename: str) -> Response:
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _geojson(df: pd.DataFrame, lat_col="latitude", lon_col="longitude") -> dict:
    features = []
    for record in df.to_dict(orient="records"):
        lat, lon = record.pop(lat_col, None), record.pop(lon_col, None)
        if lat is None or lon is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": record,
        })
    return {"type": "FeatureCollection", "features": features}


# --------------------------------------------------------------------------
# Page data: summaries the reference pages draw as charts
# --------------------------------------------------------------------------

def _per_snapshot(key: str, compute):
    """Cache a derived value until the detections file changes."""
    stamp = DETECTIONS_FILE.stat().st_mtime if DETECTIONS_FILE.exists() else 0.0
    hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    value = compute()
    _cache[key] = (stamp, value)
    return value


INDUSTRIAL_LABELS = ("persistent_industrial_source", "industrial_fire", "flare_signature")


def daily_by_class() -> dict:
    def compute():
        df = detections()
        if df.empty:
            return {"dates": [], "series": {}}
        table = df.groupby(["acq_date", "final_label"]).size().unstack(fill_value=0)
        days = pd.date_range(df["acq_date"].min(), df["acq_date"].max(), freq="D").strftime("%Y-%m-%d")
        table = table.reindex(days, fill_value=0)
        return {"dates": list(days),
                "series": {label: [int(v) for v in table[label]] for label in table.columns}}
    return _per_snapshot("daily_by_class", compute)


def footprint(step: float = 0.5) -> list[dict]:
    def compute():
        df = detections()
        if df.empty:
            return []
        work = pd.DataFrame({
            "lat": (df["latitude"] // step) * step + step / 2,
            "lon": (df["longitude"] // step) * step + step / 2,
            "ind": df["final_label"].isin(INDUSTRIAL_LABELS),
        })
        grouped = work.groupby(["lat", "lon"])["ind"].agg(["size", "mean"]).reset_index()
        return [{"lat": float(r.lat), "lon": float(r.lon), "n": int(r.size),
                 "industrial": round(float(r.mean), 3)}
                for r in grouped.itertuples(index=False)]
    return _per_snapshot("footprint", compute)


def column_profiles() -> dict:
    """Fill rate plus a histogram or top values for every column."""
    import numpy as np

    def compute():
        df = detections()
        out = {}
        for col in df.columns:
            series = df[col]
            text = series.astype(str).str.strip()
            present = series.notna() & text.ne("") & text.ne("nan")
            profile = {"fill": round(float(present.mean()), 4) if len(df) else 0.0}
            values = series[present]

            if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series) \
                    and values.nunique() > 6:
                numeric = values.astype(float)
                numeric = numeric[np.isfinite(numeric)]
                lo, hi = numeric.quantile(0.01), numeric.quantile(0.99)
                clipped = numeric.clip(lo, hi)
                counts, edges = np.histogram(clipped, bins=18)
                profile.update({
                    "kind": "numeric", "hist": counts.tolist(),
                    "edges": [round(float(e), 4) for e in edges],
                    "min": round(float(numeric.min()), 4),
                    "median": round(float(numeric.median()), 4),
                    "max": round(float(numeric.max()), 4),
                })
            else:
                top = values.astype(str).value_counts().head(5)
                profile.update({
                    "kind": "categorical", "distinct": int(values.nunique()),
                    "top": [[str(k)[:40], int(v)] for k, v in top.items()],
                })
            out[col] = profile
        return out
    return _per_snapshot("column_profiles", compute)


@app.context_processor
def _shared_page_context():
    return {"snapshot": snapshot(), "build": BUILD_COMMIT}


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


def _finite(value):
    """Replace inf/NaN (which JSON.parse rejects) with None, recursively."""
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


@app.route("/validation")
def validation():
    df = detections()
    report = validation_report()
    return render_template(
        "validation.html",
        report=analysis_report(),
        validation=report,
        manifest=manifest(),
        page_data=_finite({
            "daily": daily_by_class(),
            "footprint": footprint(),
            "labels": df["final_label"].value_counts().to_dict() if not df.empty else {},
            "feature_importance": analysis_report().get("model", {}).get("feature_importance", {}),
            "ablation": report.get("ablation", []),
            "retrieval": report.get("retrieval_status", {}),
            "regimes": report.get("temp_class_counts", {}),
        }),
    )


@app.route("/data-dictionary")
def data_dictionary():
    from data_dictionary import COLUMNS
    return render_template(
        "data_dictionary.html", columns=COLUMNS,
        page_data={"profiles": column_profiles(), "rows": int(len(detections()))},
    )


@app.route("/api/docs")
def api_docs():
    df = detections()
    return render_template(
        "api_docs.html",
        page_data={
            "detections": int(len(df)),
            "sites": int(df["facility_uid"].replace("", pd.NA).nunique()) if not df.empty else 0,
            "clusters": int(len(clusters())),
            "facilities": int(len(facilities())),
        },
    )


# --------------------------------------------------------------------------
# JSON API
# --------------------------------------------------------------------------

# Columns the map and feed need. Sending the full 90-column frame would more
# than triple the payload for data the browser never reads.
MAP_COLUMNS = [
    "detection_id", "latitude", "longitude", "acq_date", "acq_time", "daynight",
    "frp", "final_label", "final_label_display", "fusion_score", "risk_score",
    "risk_level", "evidence_score", "evidence_level", "thermal_abnormality",
    "persistence_norm", "frp_intensity_norm", "recurrence_days", "night_fraction",
    "duty_cycle", "est_temp_k", "temp_class", "est_area_m2", "retrieval_status",
    "temp_is_lower_bound", "dist_to_industrial_km", "dist_osm_km", "dist_wri_km",
    "dist_gem_km", "dist_eog_km", "sources_loaded", "sources_confirming",
    "sources_confirming_count",
    "corroboration_score", "nearest_facility_name", "nearest_facility_type",
    "nearest_facility_lat", "nearest_facility_lon", "facility_uid",
    "facility_sources", "facility_source_agreement", "facility_status",
    "facility_capacity_value", "facility_capacity_unit", "industrial_context",
    "agri_season_context", "new_source", "ceased", "reactivated",
    "ml_industrial_prob", "unsupervised_anomaly", "anomaly_probability",
    "contributions", "cluster_id", "instrument", "source_sensor",
]


@app.route("/api/detections")
def api_detections():
    df = apply_filters(detections(), request.args)
    if df.empty:
        return jsonify([])
    cols = [c for c in MAP_COLUMNS if c in df.columns]
    return jsonify(df[cols].fillna("").to_dict(orient="records"))


# What the dashboard draws before anything is clicked. A multi-month snapshot
# is tens of thousands of rows, so the map gets these fields only, as columns
# plus value rows instead of repeated keys, and the full record is fetched
# per detection when one is opened.
MAP_FIELDS = [
    "detection_id", "latitude", "longitude", "acq_date", "frp", "final_label",
    "risk_score", "evidence_score", "corroboration_score", "est_temp_k",
    "recurrence_days", "dist_to_industrial_km", "nearest_facility_name",
    "facility_uid", "sources_confirming",
]
MAP_ROUNDING = {
    "latitude": 5, "longitude": 5, "frp": 2, "risk_score": 3, "evidence_score": 3,
    "corroboration_score": 3, "est_temp_k": 0, "dist_to_industrial_km": 2,
}
# Heavily repeated strings travel once, in a lookup table, and rows carry an
# index into it. A site seen 700 times would otherwise send its name 700 times.
MAP_DICTIONARY = ["acq_date", "final_label", "nearest_facility_name", "facility_uid",
                  "sources_confirming"]


def _map_payload() -> tuple[bytes, bytes]:
    def compute():
        df = detections()
        cols = [c for c in MAP_FIELDS if c in df.columns]
        frame = df[cols].copy()
        for col, digits in MAP_ROUNDING.items():
            if col in frame.columns:
                frame[col] = frame[col].round(digits)

        dictionaries = {}
        for col in MAP_DICTIONARY:
            if col in frame.columns:
                codes, uniques = pd.factorize(frame[col].fillna(""))
                frame[col] = codes
                dictionaries[col] = [str(u) for u in uniques]

        rows = frame.astype(object).where(frame.notna(), None).values.tolist()
        loaded = str(df["sources_loaded"].iloc[0]) if "sources_loaded" in df.columns and len(df) else ""
        raw = json.dumps(
            {"columns": cols, "dictionaries": dictionaries, "rows": rows,
             "sources_loaded": loaded},
            separators=(",", ":"), default=str,
        ).encode()
        return raw, gzip.compress(raw, 6)

    return _per_snapshot("map_payload", compute)


@app.route("/api/map")
def api_map():
    raw, packed = _map_payload()
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        response = Response(packed, mimetype="application/json")
        response.headers["Content-Encoding"] = "gzip"
    else:
        response = Response(raw, mimetype="application/json")
    response.headers["Vary"] = "Accept-Encoding"
    return response


@app.route("/api/clusters")
def api_clusters():
    df = clusters()
    return jsonify(df.fillna("").to_dict(orient="records") if not df.empty else [])


@app.route("/api/facilities")
def api_facilities():
    df = facilities()
    if df.empty:
        return jsonify([])

    source = request.args.get("source", "").strip()
    if source:
        df = df[df["sources_present"].fillna("").str.split("|").apply(lambda v: source in v)]

    bbox = request.args.get("bbox", "").strip()
    if bbox:
        try:
            lon_min, lat_min, lon_max, lat_max = (float(v) for v in bbox.split(","))
            df = df[df["lat"].between(lat_min, lat_max) & df["lon"].between(lon_min, lon_max)]
        except ValueError:
            pass

    limit = int(request.args.get("limit", 4000))
    return jsonify(df.head(limit).fillna("").to_dict(orient="records"))


@app.route("/api/sources")
def api_sources():
    """Per-registry status: what loaded, what did not, and why."""
    info = manifest()
    df = detections()

    out = []
    for key in SOURCE_KEYS:
        entry = info.get("sources", {}).get(key, {})
        confirmed = 0
        if not df.empty and "sources_confirming" in df.columns:
            confirmed = int(
                df["sources_confirming"].fillna("")
                .str.split("|").apply(lambda v: key in v).sum()
            )
        out.append({
            "key": key,
            "label": entry.get("label", key.upper()),
            "short": entry.get("short", key.upper()),
            "status": entry.get("status", "unavailable"),
            "records": entry.get("records", 0),
            "license": entry.get("license", ""),
            "homepage": entry.get("homepage", ""),
            "hint": entry.get("hint", ""),
            "by_type": entry.get("by_type", {}),
            "detections_confirmed": confirmed,
        })

    return jsonify({
        "sources": out,
        "built_at": info.get("built_at"),
        "total_sites": info.get("total_sites", 0),
        "multi_source_sites": info.get("multi_source_sites", 0),
        "total_records": info.get("total_records", 0),
    })


@app.route("/api/detection/<detection_id>")
def api_detection(detection_id):
    df = detections()
    if df.empty or "detection_id" not in df.columns:
        return jsonify({"error": "no data"}), 404

    match = df[df["detection_id"] == detection_id]
    if match.empty:
        return jsonify({"error": "not found"}), 404

    record = match.iloc[0].fillna("").to_dict()
    try:
        record["contributions"] = json.loads(record.get("contributions") or "[]")
    except (TypeError, ValueError):
        record["contributions"] = []
    return jsonify(record)


@app.route("/api/site/<facility_uid>")
def api_site(facility_uid):
    """One facility: who lists it, and everything seen there.

    The dashboard answers "what is this detection?"; this answers "what has
    been happening at this plant?", which is the question an inspector
    actually opens a case file with.
    """
    df = detections()
    sites = facilities()
    if df.empty or "facility_uid" not in df.columns:
        return jsonify({"error": "no data"}), 404

    site = sites[sites["facility_uid"] == facility_uid]
    subset = df[df["facility_uid"] == facility_uid]
    if site.empty and subset.empty:
        return jsonify({"error": "not found"}), 404

    identity = site.iloc[0].fillna("").to_dict() if not site.empty else {}

    # One entry for every day of the snapshot window, quiet days included.
    # Listing only the days with detections made a site seen on the 1st and
    # the 20th look like it burned two days running.
    window = [str(df["acq_date"].min()), str(df["acq_date"].max())]
    daily = []
    if not subset.empty:
        by_day = {day: rows for day, rows in subset.groupby("acq_date")}
        for stamp in pd.date_range(window[0], window[1], freq="D"):
            day = stamp.strftime("%Y-%m-%d")
            rows = by_day.get(day)
            if rows is None:
                daily.append({"date": day, "detections": 0, "max_frp": 0.0,
                              "max_risk": 0.0, "max_temp_k": None, "night": 0})
                continue
            daily.append({
                "date": day,
                "detections": int(len(rows)),
                "max_frp": round(float(rows["frp"].max()), 2),
                "max_risk": round(float(rows["risk_score"].max()), 3),
                "max_temp_k": (
                    round(float(rows["est_temp_k"].max()), 1)
                    if rows["est_temp_k"].notna().any() else None
                ),
                "night": int((rows["daynight"].astype(str).str.upper() == "N").sum()),
            })

    summary = {}
    if not subset.empty:
        summary = {
            "detections": int(len(subset)),
            "days_active": int(subset["acq_date"].nunique()),
            "first_seen": str(subset["acq_date"].min()),
            "last_seen": str(subset["acq_date"].max()),
            "max_frp": round(float(subset["frp"].max()), 2),
            "max_risk": round(float(subset["risk_score"].max()), 3),
            "max_temp_k": (
                round(float(subset["est_temp_k"].max()), 1)
                if subset["est_temp_k"].notna().any() else None
            ),
            "labels": subset["final_label"].value_counts().to_dict(),
            "temp_classes": subset["temp_class"].value_counts().to_dict(),
            "night_fraction": round(float(
                (subset["daynight"].astype(str).str.upper() == "N").mean()
            ), 3),
            "window_days": len(daily),
        }

    latest = subset.sort_values(["acq_date", "acq_time"], ascending=False)
    return jsonify({
        "facility_uid": facility_uid,
        "identity": identity,
        "summary": summary,
        "window": window,
        "daily": daily,
        "detections": latest.head(200)[
            [c for c in ("detection_id", "acq_date", "acq_time", "daynight", "frp",
                         "est_temp_k", "temp_class", "final_label", "risk_score")
             if c in subset.columns]
        ].fillna("").to_dict(orient="records"),
    })


@app.route("/api/stats")
def api_stats():
    df = detections()
    counts = df["final_label"].value_counts().to_dict() if not df.empty else {}
    snap = snapshot()
    info = manifest()
    report = analysis_report()

    return jsonify({
        "total": int(len(df)),
        "industrial_fire": counts.get("industrial_fire", 0),
        "persistent_industrial_source": counts.get("persistent_industrial_source", 0),
        "flare_signature": counts.get("flare_signature", 0),
        "agricultural_burning": counts.get("agricultural_burning", 0),
        "insufficient_evidence": counts.get("insufficient_evidence", 0),
        "multi_source_confirmed": int(
            (df["sources_confirming_count"] >= 2).sum()
        ) if "sources_confirming_count" in df.columns else 0,
        "temperature_retrieved": int(
            df["est_temp_k"].notna().sum()
        ) if "est_temp_k" in df.columns else 0,
        "registry_sites": info.get("total_sites", 0),
        "registry_sources_loaded": sum(
            1 for s in info.get("sources", {}).values() if s.get("status") == "loaded"
        ),
        "snapshot_id": snap.get("snapshot_id"),
        "generated_at": snap.get("generated_at"),
        "date_range": snap.get("date_range"),
        "method_version": snap.get("method_version", ""),
        "model_auc": report.get("model", {}).get("cv_auc"),
        "build": BUILD_COMMIT,
    })


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------

@app.route("/api/export/detections.csv")
def export_detections():
    df = apply_filters(detections(), request.args)
    snap = snapshot().get("snapshot_id", "unknown")
    return _csv_response(df, f"satat_detections_{snap}.csv")


@app.route("/api/export/clusters.csv")
def export_clusters():
    snap = snapshot().get("snapshot_id", "unknown")
    return _csv_response(clusters(), f"satat_clusters_{snap}.csv")


@app.route("/api/export/facilities.csv")
def export_facilities():
    df = facilities()
    source = request.args.get("source", "").strip()
    if source and not df.empty:
        df = df[df["sources_present"].fillna("").str.split("|").apply(lambda v: source in v)]
    return _csv_response(df, "satat_facilities.csv")


@app.route("/api/export/detections.geojson")
def export_geojson():
    df = apply_filters(detections(), request.args)
    snap = snapshot().get("snapshot_id", "unknown")
    payload = json.dumps(_geojson(df.fillna("")), default=str)
    return Response(
        payload,
        mimetype="application/geo+json",
        headers={
            "Content-Disposition": f'attachment; filename="satat_detections_{snap}.geojson"'
        },
    )


@app.route("/api/export/site/<facility_uid>.csv")
def export_site(facility_uid):
    """Every detection attributed to one facility: the investigation packet."""
    df = detections()
    if df.empty or "facility_uid" not in df.columns:
        return jsonify({"error": "no data"}), 404
    subset = df[df["facility_uid"] == facility_uid]
    if subset.empty:
        return jsonify({"error": "not found"}), 404
    return _csv_response(subset, f"satat_site_{facility_uid}.csv")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=not os.environ.get("PORT"))
