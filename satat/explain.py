"""Per-detection explanation.

A priority queue nobody can interrogate is a priority queue nobody will act
on. Every detection carries the signed contribution of each component that
produced its score, so the evidence panel shows *why* this row outranks the
one below it rather than just asserting that it does.
"""

from __future__ import annotations

import json

import pandas as pd

from satat import config

COMPONENT_LABELS = {
    "corroboration": "Registry corroboration",
    "physics": "Combustion temperature",
    "persistence": "Repeat detections",
    "nocturnal": "Burns at night",
    "intensity": "Thermal intensity",
}

COMPONENT_COLUMNS = {
    "corroboration": "corroboration_component",
    "physics": "physics_score",
    "persistence": "persistence_component",
    "nocturnal": "nocturnal_component",
    "intensity": "intensity_component",
}

COMPONENT_DETAIL = {
    "corroboration": lambda r: (
        f"{int(r['sources_confirming_count'])} of "
        f"{len(str(r['sources_loaded']).split('|')) if r['sources_loaded'] else 0} "
        f"registries place infrastructure within {config.CORROBORATION_RADIUS_KM:g} km"
    ),
    "physics": lambda r: (
        f"retrieved {r['est_temp_k']:.0f} K ({str(r['temp_class']).replace('_', ' ')})"
        if pd.notna(r["est_temp_k"]) else "temperature retrieval unavailable"
    ),
    "persistence": lambda r: f"seen on {int(r['recurrence_days'])} separate days",
    "nocturnal": lambda r: f"{r['night_fraction'] * 100:.0f}% of detections at night",
    "intensity": lambda r: f"FRP {r['frp']:.1f} MW, {r['frp_intensity_norm'] * 100:.0f}th percentile",
}


def add_explanations(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    weights = config.EVIDENCE_WEIGHTS

    records = []
    for _, row in df.iterrows():
        items = []
        for key, weight in weights.items():
            value = float(row[COMPONENT_COLUMNS[key]])
            items.append({
                "key": key,
                "label": COMPONENT_LABELS[key],
                "value": round(value, 3),
                "weight": weight,
                "contribution": round(value * weight, 4),
                "detail": COMPONENT_DETAIL[key](row),
            })

        if row.get("agri_penalty_applied"):
            items.append({
                "key": "agri_penalty",
                "label": "Crop-burning season",
                "value": 1.0,
                "weight": -0.45,
                "contribution": round(-0.45 * float(row["evidence_score"]), 4),
                "detail": f"inside {row['agri_season_region']} during its burning window",
            })

        items.sort(key=lambda d: abs(d["contribution"]), reverse=True)
        records.append(json.dumps(items))

    df["contributions"] = records
    return df
