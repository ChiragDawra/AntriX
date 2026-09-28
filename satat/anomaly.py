"""Scoring: interpretable evidence, weak-supervised ML, and unsupervised outliers.

Three scores are produced deliberately, because they fail in different ways:

``evidence_score``        a weighted sum of named, arguable signals. Fully
                          explainable, but only as good as its weights.
``ml_industrial_prob``    a calibrated RandomForest over the physics and
                          temporal features. Learns interactions the weights
                          cannot express, but inherits any bias in the labels.
``unsupervised_anomaly``  IsolationForest + LOF. Owes nothing to the labels at
                          all, so it can surface a site the other two agree to
                          ignore.

The old pipeline's weakness was circularity: it labelled a detection
"industrial" when it was near an OSM polygon and recurred, trained a model on
those labels, and then used the model's output as evidence that the detection
was industrial. Here the weak labels come from a *different* signal than the
model's features -- registry corroboration and season decide the label, while
the model only sees thermal physics and timing -- so the model has something
real to learn instead of a restatement of its own input.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from satat import config

ML_FEATURES = [
    "frp",
    "frp_robust_z",
    "est_temp_k_filled",
    "hot_fraction_log",
    "recurrence_days",
    "night_fraction",
    "duty_cycle",
    "frp_shift",
]

UNSUPERVISED_FEATURES = ML_FEATURES + ["dist_log_km", "corroboration_score"]


def _prepare_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric, finite, model-ready view of the feature columns."""
    work = df.copy()

    # A failed temperature retrieval is informative (usually a weak or
    # saturated pixel), so it gets the scene median rather than being dropped.
    temp = work["est_temp_k"]
    work["est_temp_k_filled"] = temp.fillna(temp.median() if temp.notna().any() else 800.0)

    hot = work["hot_fraction"].fillna(0.0).clip(lower=0)
    work["hot_fraction_log"] = np.log10(hot + 1e-6)

    dist = work["dist_to_industrial_km"].replace([np.inf, -np.inf], np.nan).fillna(999.0)
    work["dist_log_km"] = np.log10(dist.clip(lower=0.01))

    for col in set(ML_FEATURES + UNSUPERVISED_FEATURES):
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)

    return work


def add_evidence_score(df: pd.DataFrame) -> pd.DataFrame:
    """The interpretable score, and the per-component values behind it."""
    df = df.copy()

    # Physics component: how far into the industrial-combustion band the
    # retrieved temperature sits. A flare-like 1600 K scores 1.0; a
    # biomass-like 700 K scores near 0.
    temp = df["est_temp_k"]
    physics = ((temp - 800.0) / 700.0).clip(0, 1)
    # No retrieval, no physics evidence either way -> neutral-low, not zero,
    # so a saturated bright pixel is not punished for saturating.
    physics = physics.fillna(0.25)
    df["physics_score"] = physics.round(4)

    df["corroboration_component"] = df["corroboration_score"]
    df["persistence_component"] = df["persistence_norm"]
    df["nocturnal_component"] = df["nocturnal_score"]
    df["intensity_component"] = df["frp_intensity_norm"]

    w = config.EVIDENCE_WEIGHTS
    score = (
        w["corroboration"] * df["corroboration_component"]
        + w["physics"] * df["physics_score"]
        + w["persistence"] * df["persistence_component"]
        + w["nocturnal"] * df["nocturnal_component"]
        + w["intensity"] * df["intensity_component"]
    )

    # Seasonal correction: inside a stubble-burning belt in season, with a
    # biomass-like temperature and nothing in the registries, the industrial
    # reading is the less likely one.
    agri_penalty = (
        df["agri_season_context"]
        & (df["temp_class"].isin(["biomass_like", "smouldering", "unknown"]))
        & (df["corroboration_score"] < 0.3)
    )
    df["agri_penalty_applied"] = agri_penalty
    score = score.mask(agri_penalty, score * 0.55)

    df["evidence_score"] = score.clip(0, 1).round(4)
    df["industrial_evidence_score"] = df["evidence_score"]
    return df


def _weak_labels(df: pd.DataFrame) -> pd.Series:
    """Confident positives and negatives; everything else is left unlabelled.

    Only rows the registries and the calendar are unambiguous about are used
    for training. Training on the uncertain middle is what made the previous
    model learn its own input back.
    """
    positive = (
        (df["dist_to_industrial_km"] <= config.ONSITE_RADIUS_KM)
        & (df["sources_confirming_count"] >= 2)
        & (~df["agri_season_context"])
    )
    negative = (
        (df["dist_to_industrial_km"] > 10.0)
        & (df["sources_confirming_count"] == 0)
    )

    labels = pd.Series(np.nan, index=df.index)
    labels[positive] = 1.0
    labels[negative] = 0.0
    return labels


def cell_groups(df: pd.DataFrame) -> np.ndarray:
    """One group id per grid cell, for cross-validation.

    Every detection in a cell shares its recurrence, duty cycle and night
    fraction. Split by row and a plant seen on sixty days lands in train and
    test at once, and the score measures memory of that plant, not skill.
    """
    lat = df["latitude"].round(config.GRID_DECIMALS).astype(str)
    lon = df["longitude"].round(config.GRID_DECIMALS).astype(str)
    return pd.factorize(lat + ":" + lon)[0]


def group_folds(y: np.ndarray, groups: np.ndarray, max_folds: int = 5):
    """Stratified folds that never split a grid cell across train and test."""
    from sklearn.model_selection import StratifiedGroupKFold

    per_class = min(len(np.unique(groups[y == 1])), len(np.unique(groups[y == 0])))
    folds = max(2, min(max_folds, per_class))
    return StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=42)


def add_ml_probability(df: pd.DataFrame, model_path=None) -> tuple[pd.DataFrame, dict]:
    """Calibrated probability that a detection is an industrial thermal source."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_predict
    from sklearn.metrics import roc_auc_score

    work = _prepare_matrix(df)
    labels = _weak_labels(work)
    train_mask = labels.notna()

    X_all = work[ML_FEATURES].to_numpy(dtype=float)
    report = {
        "trained": False,
        "n_positive": int((labels == 1).sum()),
        "n_negative": int((labels == 0).sum()),
    }

    # Both classes, and enough of each, or there is nothing to learn.
    if report["n_positive"] < 10 or report["n_negative"] < 10:
        df = df.copy()
        df["ml_industrial_prob"] = np.nan
        report["reason"] = "not enough confidently-labelled rows to train"
        return df, report

    X = X_all[train_mask.to_numpy()]
    y = labels[train_mask].to_numpy()
    groups = cell_groups(work)[train_mask.to_numpy()]

    base = RandomForestClassifier(
        n_estimators=300, min_samples_leaf=3, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )
    cv = group_folds(y, groups)
    splits = list(cv.split(X, y, groups))

    # Honest metric first: out-of-fold predictions, before the model ever sees
    # the full training set, with whole grid cells held out together.
    oof = cross_val_predict(base, X, y, cv=splits, method="predict_proba")[:, 1]
    report["cv_auc"] = float(roc_auc_score(y, oof)) if len(set(y)) > 1 else float("nan")
    report["cv_folds"] = len(splits)
    report["cv_grouping"] = "grid_cell"

    model = CalibratedClassifierCV(base, method="isotonic", cv=splits)
    model.fit(X, y)

    df = df.copy()
    df["ml_industrial_prob"] = np.round(model.predict_proba(X_all)[:, 1], 4)

    fitted = RandomForestClassifier(
        n_estimators=300, min_samples_leaf=3, class_weight="balanced",
        random_state=42, n_jobs=-1,
    ).fit(X, y)
    report["feature_importance"] = dict(
        zip(ML_FEATURES, np.round(fitted.feature_importances_, 4).tolist())
    )
    report["trained"] = True

    if model_path:
        import joblib
        joblib.dump({"model": model, "features": ML_FEATURES}, model_path)
        report["model_path"] = Path(model_path).name

    return df, report


def add_unsupervised_anomaly(df: pd.DataFrame) -> pd.DataFrame:
    """Label-free outlier score: IsolationForest and LOF, rank-averaged."""
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.preprocessing import StandardScaler

    work = _prepare_matrix(df)
    X = StandardScaler().fit_transform(work[UNSUPERVISED_FEATURES].to_numpy(dtype=float))

    df = df.copy()
    if len(df) < 20:
        df["unsupervised_anomaly"] = np.nan
        return df

    forest = IsolationForest(n_estimators=300, contamination="auto", random_state=42)
    # Lower decision_function means more anomalous; negate so high = anomalous.
    iso = -forest.fit(X).decision_function(X)

    neighbours = min(20, max(5, len(df) // 10))
    lof_model = LocalOutlierFactor(n_neighbors=neighbours)
    lof_model.fit_predict(X)
    lof = -lof_model.negative_outlier_factor_

    # Rank-average rather than value-average: the two scores are on different,
    # unbounded scales, and only their ordering is comparable.
    iso_rank = pd.Series(iso).rank(pct=True)
    lof_rank = pd.Series(lof).rank(pct=True)
    df["unsupervised_anomaly"] = np.round(((iso_rank + lof_rank) / 2).to_numpy(), 4)
    return df


# How the three scores combine. Evidence leads because it is the one a human
# can audit; the model refines it; the unsupervised score is a minority vote
# that can only nudge a detection up or down the queue, never decide it.
FUSION_WEIGHTS = {"evidence": 0.55, "ml": 0.30, "unsupervised": 0.15}


def fuse(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    ml = df["ml_industrial_prob"]
    uns = df["unsupervised_anomaly"]

    # A component that could not be computed is dropped from the blend and its
    # weight redistributed, instead of being silently treated as a zero.
    parts, weights = [df["evidence_score"]], [FUSION_WEIGHTS["evidence"]]
    if ml.notna().any():
        parts.append(ml.fillna(df["evidence_score"]))
        weights.append(FUSION_WEIGHTS["ml"])
    if uns.notna().any():
        parts.append(uns.fillna(0.5))
        weights.append(FUSION_WEIGHTS["unsupervised"])

    total = sum(weights)
    blended = sum(w * p for w, p in zip(weights, parts)) / total

    df["anomaly_probability"] = blended.clip(0, 1).round(4)
    df["fusion_score"] = df["anomaly_probability"]        # name kept for the dashboard

    # Investigation priority is not the same question as "is this industrial".
    # It asks what deserves a human first: a confident industrial reading that
    # is also abnormally hot, persistent, and newly appeared.
    priority = (
        0.45 * df["anomaly_probability"]
        + 0.25 * df["thermal_abnormality"]
        + 0.20 * df["persistence_norm"]
        + 0.10 * df["frp_intensity_norm"]
    )
    priority = priority + 0.05 * df["new_source"].astype(float)

    df["risk_score"] = priority.clip(0, 1).round(4)
    df["risk_level"] = pd.cut(
        df["risk_score"],
        bins=[-0.01] + [t for t, _ in reversed(config.RISK_LEVELS)][1:] + [1.01],
        labels=[name for _, name in reversed(config.RISK_LEVELS)],
    ).astype(str)

    return df
