"""Stage order for the analysis.

Each stage takes the frame and returns it with new columns. Nothing rewrites a
column another stage owns, so reading this function top to bottom tells you
exactly where any output came from.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from satat import METHOD_VERSION, anomaly, baseline, classify, context, explain, join, physics, temporal

# Columns the dashboard and the CSV export are contracted to receive. Anything
# not on this list is internal.
OUTPUT_COLUMNS = [
    # identity and geometry
    "detection_id", "latitude", "longitude", "acq_date", "acq_time", "daynight",
    "satellite", "instrument", "source_sensor", "confidence", "scan", "track",
    "grid_lat", "grid_lon",
    # raw radiometry
    "frp", "bright_ti4", "bright_ti5", "brightness", "bright_t31",
    # physics
    "est_temp_k", "hot_fraction", "est_area_m2", "pixel_area_m2", "temp_class",
    "i4_saturated", "temp_is_lower_bound", "retrieval_status",
    # baseline
    "baseline_frp", "baseline_level", "frp_robust_z", "thermal_abnormality",
    "frp_intensity_norm",
    # temporal
    "recurrence_days", "detections_in_cell", "night_fraction", "duty_cycle",
    "inter_arrival_regularity", "frp_shift", "persistence_norm", "nocturnal_score",
    "new_source", "ceased", "reactivated", "active_span_days",
    "observation_window_days",
    # registry
    "dist_to_industrial_km", "dist_osm_km", "dist_wri_km", "dist_gem_km",
    "dist_eog_km", "count_osm_3km", "count_wri_3km", "count_gem_3km",
    "count_eog_3km", "sources_loaded", "sources_confirming",
    "sources_confirming_count", "corroboration_score", "facility_uid",
    "nearest_facility_name", "nearest_facility_type", "nearest_facility_lat",
    "nearest_facility_lon", "facility_sources", "facility_source_agreement",
    "facility_status", "facility_capacity_value", "facility_capacity_unit",
    "facility_subnational", "industrial_context",
    # context
    "agri_season_context", "agri_season_region", "agri_penalty_applied",
    # scores
    "corroboration_component", "physics_score", "persistence_component",
    "nocturnal_component", "intensity_component", "evidence_score",
    "industrial_evidence_score", "ml_industrial_prob", "unsupervised_anomaly",
    "anomaly_probability", "fusion_score", "risk_score", "risk_level",
    # classification and provenance
    "final_label", "final_label_display", "evidence_level", "contributions",
    "method_version", "cluster_id",
]


def run(detections: pd.DataFrame, registry_dir: Path, model_path=None,
        only_sources: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    report = {"method_version": METHOD_VERSION, "input_rows": int(len(detections))}

    df = detections.copy()
    df["detection_id"] = [
        # Stable across runs: same pixel, same day, same id.
        hashlib.md5(
            f"{r.latitude:.5f}:{r.longitude:.5f}:{r.acq_date}:{r.acq_time}".encode()
        ).hexdigest()[:12]
        for r in df.itertuples(index=False)
    ]

    df = physics.add_subpixel_features(df)
    df = temporal.add_temporal_features(df)
    df = baseline.add_robust_baseline(df)
    df = context.agricultural_context(df)

    df, registry_manifest = join.add_registry_features(df, registry_dir, only_sources)
    report["registry"] = {
        source: info["records"]
        for source, info in registry_manifest.get("sources", {}).items()
    }

    df = anomaly.add_evidence_score(df)
    df, ml_report = anomaly.add_ml_probability(df, model_path=model_path)
    report["model"] = ml_report

    df = anomaly.add_unsupervised_anomaly(df)
    df = anomaly.fuse(df)
    df = classify.classify(df)
    df = explain.add_explanations(df)

    df["method_version"] = METHOD_VERSION

    report["retrieval_success_rate"] = round(float(df["est_temp_k"].notna().mean()), 4)
    report["label_counts"] = df["final_label"].value_counts().to_dict()
    report["temp_class_counts"] = df["temp_class"].value_counts().to_dict()
    report["multi_source_confirmed"] = int((df["sources_confirming_count"] >= 2).sum())

    return df, report


def select_output(df: pd.DataFrame) -> pd.DataFrame:
    """Project to the contracted output columns, tolerating missing ones."""
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[OUTPUT_COLUMNS]


def write_snapshot(df: pd.DataFrame, path: Path, report: dict) -> dict:
    digest = hashlib.md5(
        pd.util.hash_pandas_object(df[["detection_id", "risk_score"]], index=False).values
    ).hexdigest()[:8]

    snapshot = {
        "snapshot_id": digest,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "total_detections": int(len(df)),
        "date_range": [str(df["acq_date"].min()), str(df["acq_date"].max())],
        "method_version": METHOD_VERSION,
        "registry": report.get("registry", {}),
        "model": {
            k: v for k, v in report.get("model", {}).items()
            if k in ("trained", "cv_auc", "n_positive", "n_negative", "cv_folds", "reason")
        },
        "retrieval_success_rate": report.get("retrieval_success_rate"),
    }
    Path(path).write_text(json.dumps(snapshot, indent=2))
    return snapshot
