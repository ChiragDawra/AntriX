#!/usr/bin/env python3
"""Measure the system instead of asserting things about it.

Produces validation_report.json, which the /validation page renders:

* cross-validated classifier metrics with a confusion matrix, computed on
  out-of-fold predictions with whole grid cells held out, so no detection is
  scored by a model that saw that site
* an ablation over the four registries, showing what each one adds to the
  corroboration evidence rather than claiming that more sources is better
* registry overlap: how much of each source is confirmed by another

Run after run_analysis.py:
    python evaluate.py
"""

import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from satat import anomaly, pipeline

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "data" / "registry"
APP_DIR = ROOT / "antrix_app"
SOURCES = ["osm", "wri", "gem", "eog"]


def classifier_metrics(df: pd.DataFrame) -> dict:
    """Out-of-fold precision/recall for the weak-label classifier."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_predict
    from sklearn.metrics import (
        average_precision_score, confusion_matrix, precision_recall_fscore_support,
        roc_auc_score,
    )

    work = anomaly._prepare_matrix(df)
    labels = anomaly._weak_labels(work)
    mask = labels.notna()

    positives = int((labels == 1).sum())
    negatives = int((labels == 0).sum())
    if positives < 10 or negatives < 10:
        return {"available": False, "reason": "not enough confidently-labelled rows"}

    X = work.loc[mask, anomaly.ML_FEATURES].to_numpy(dtype=float)
    y = labels[mask].to_numpy()
    groups = anomaly.cell_groups(work)[mask.to_numpy()]

    cv = anomaly.group_folds(y, groups)
    splits = list(cv.split(X, y, groups))
    model = RandomForestClassifier(
        n_estimators=300, min_samples_leaf=3, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )
    proba = cross_val_predict(model, X, y, cv=splits, method="predict_proba")[:, 1]
    predicted = (proba >= 0.5).astype(int)

    precision, recall, f1, _ = precision_recall_fscore_support(
        y, predicted, average="binary", zero_division=0
    )
    tn, fp, fn, tp = confusion_matrix(y, predicted, labels=[0, 1]).ravel()

    return {
        "available": True,
        "n_positive": positives,
        "n_negative": negatives,
        "positive_cells": int(len(np.unique(groups[y == 1]))),
        "negative_cells": int(len(np.unique(groups[y == 0]))),
        "folds": len(splits),
        "grouping": "grid_cell",
        "roc_auc": round(float(roc_auc_score(y, proba)), 4),
        "average_precision": round(float(average_precision_score(y, proba)), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "confusion": {"tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)},
        "features": anomaly.ML_FEATURES,
        "note": (
            "Labels are weak: positives are detections on a site at least two "
            "registries agree on, outside crop-burning season; negatives are "
            "more than 10 km from anything any registry lists. The model never "
            "sees distance or corroboration as a feature, only thermal physics "
            "and timing, so these numbers measure whether the physics and the "
            "registries agree -- not accuracy against field-verified truth, "
            "which SATAT does not have."
        ),
    }


def ablation(detections: pd.DataFrame) -> list[dict]:
    """What each registry, and each combination, contributes."""
    rows = []
    subsets = [["osm"], ["wri"], ["gem"], ["eog"], ["osm", "wri"], ["osm", "gem"],
                ["wri", "gem"], ["osm", "wri", "gem"], SOURCES]

    for subset in subsets:
        df, report = pipeline.run(detections, REGISTRY, only_sources=subset)
        counts = report["label_counts"]
        rows.append({
            "sources": subset,
            "label": " + ".join(s.upper() for s in subset),
            "corroborated": int((df["sources_confirming_count"] >= 1).sum()),
            "multi_confirmed": int((df["sources_confirming_count"] >= 2).sum()),
            "industrial_total": int(
                counts.get("industrial_fire", 0)
                + counts.get("persistent_industrial_source", 0)
                + counts.get("flare_signature", 0)
            ),
            "persistent": int(counts.get("persistent_industrial_source", 0)),
            "insufficient": int(counts.get("insufficient_evidence", 0)),
            "median_distance_km": round(float(df["dist_to_industrial_km"].median()), 3),
            "cv_auc": report["model"].get("cv_auc"),
        })
    return rows


def registry_overlap() -> dict:
    """How much of each registry another registry independently confirms."""
    facilities = pd.read_csv(REGISTRY / "facilities.csv")
    groups = pd.read_csv(REGISTRY / "facility_groups.csv")

    per_source = {}
    for source in SOURCES:
        subset = facilities[facilities["source"] == source]
        if subset.empty:
            per_source[source] = {"records": 0, "sites": 0, "confirmed_by_other": 0}
            continue
        uids = set(subset["facility_uid"])
        shared = groups[groups["facility_uid"].isin(uids) & (groups["source_agreement"] > 1)]
        per_source[source] = {
            "records": int(len(subset)),
            "sites": int(subset["facility_uid"].nunique()),
            "confirmed_by_other": int(len(shared)),
        }

    pairs = {}
    for a, b in combinations(SOURCES, 2):
        uids_a = set(facilities[facilities["source"] == a]["facility_uid"])
        uids_b = set(facilities[facilities["source"] == b]["facility_uid"])
        pairs[f"{a}+{b}"] = int(len(uids_a & uids_b))

    return {"per_source": per_source, "pairs": pairs,
            "total_sites": int(len(groups)),
            "multi_source_sites": int((groups["source_agreement"] > 1).sum())}


def main() -> None:
    detections = pd.read_csv(ROOT / "firms_clean.csv")
    final = pd.read_csv(ROOT / "firms_final.csv")

    print("Cross-validating the classifier...")
    metrics = classifier_metrics(final)

    print("Running the registry ablation (9 configurations)...")
    ablation_rows = ablation(detections)

    print("Measuring registry overlap...")
    overlap = registry_overlap()

    retrieval = final["retrieval_status"].value_counts().to_dict()

    report = {
        "classifier": metrics,
        "ablation": ablation_rows,
        "overlap": overlap,
        "retrieval_status": {k: int(v) for k, v in retrieval.items()},
        "retrieval_rate": round(float(final["est_temp_k"].notna().mean()), 4),
        "temp_class_counts": final["temp_class"].value_counts().to_dict(),
        "label_counts": final["final_label"].value_counts().to_dict(),
        "detections": int(len(final)),
    }

    (ROOT / "validation_report.json").write_text(json.dumps(report, indent=2, default=str))
    import shutil
    shutil.copy(ROOT / "validation_report.json", APP_DIR / "validation_report.json")

    if metrics.get("available"):
        print(f"\nClassifier: AUC {metrics['roc_auc']:.3f}  "
              f"precision {metrics['precision']:.3f}  recall {metrics['recall']:.3f}")
    print("\nAblation:")
    for row in ablation_rows:
        print(f"  {row['label']:<22} corroborated {row['corroborated']:>4}  "
              f"industrial {row['industrial_total']:>4}  "
              f"median dist {row['median_distance_km']:>7.2f} km")
    print(f"\nRegistry: {overlap['total_sites']} sites, "
          f"{overlap['multi_source_sites']} seen by more than one source")
    print("\nWrote validation_report.json")


if __name__ == "__main__":
    main()
