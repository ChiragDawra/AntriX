"""Final classification.

Five classes, not three. The two additions carry their weight:

``flare_signature``      a persistent, very-high-temperature point source --
                         the class NOAA EOG's inventory is built to catalogue,
                         reachable here from the physics even when that
                         inventory is not loaded
``agricultural_burning`` an explicit class for what used to be quietly binned
                         as "insufficient evidence", which mattered because it
                         is the single largest source of thermal detections
                         over India in October and November
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from satat import config

CLASSES = [
    "persistent_industrial_source",
    "industrial_fire",
    "flare_signature",
    "agricultural_burning",
    "insufficient_evidence",
]

CLASS_LABELS = {
    "persistent_industrial_source": "Persistent industrial source",
    "industrial_fire": "Industrial fire",
    "flare_signature": "Flare signature",
    "agricultural_burning": "Agricultural burning",
    "insufficient_evidence": "Insufficient evidence",
}


def classify(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    thresholds = config.CLASS_THRESHOLDS

    corroborated = df["sources_confirming_count"] > 0
    flare_like = (df["temp_class"] == "flare_like") & (df["recurrence_days"] >= 2)

    conditions = [
        # Nothing in any registry and nowhere near one: no industrial claim
        # can be made, whatever the thermal signal looks like. This rule is
        # inherited from the previous build and stays, because it is the one
        # that keeps the system from calling every wildfire a factory.
        (~corroborated) & (df["dist_to_industrial_km"] > 10) & df["agri_season_context"],
        (~corroborated) & (df["dist_to_industrial_km"] > 10),
        df["agri_penalty_applied"],
        flare_like & corroborated,
        (df["anomaly_probability"] >= thresholds["persistent_industrial_source"])
        & (df["recurrence_days"] >= 3),
        df["anomaly_probability"] >= thresholds["industrial_fire"],
    ]
    outcomes = [
        "agricultural_burning",
        "insufficient_evidence",
        "agricultural_burning",
        "flare_signature",
        "persistent_industrial_source",
        "industrial_fire",
    ]

    df["final_label"] = np.select(conditions, outcomes, default="insufficient_evidence")
    df["final_label_display"] = df["final_label"].map(CLASS_LABELS)

    df["evidence_level"] = pd.cut(
        df["evidence_score"],
        bins=[-0.01, 0.4, 0.7, 1.01],
        labels=["Low", "Moderate", "High"],
    ).astype(str)
    df.loc[df["final_label"] == "insufficient_evidence", "evidence_level"] = None

    return df
