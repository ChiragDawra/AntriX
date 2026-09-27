"""Spatio-temporal clustering of detections into candidate sites.

Same union-find over a spatial grid as before, kept because it is the right
shape for the problem, but the cluster summary now carries the new evidence:
which registries confirm the site, what temperature class dominates it, and
whether it is newly active.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from satat.geo import haversine_km

SPATIAL_THRESHOLD_KM = 3.0
TEMPORAL_THRESHOLD_DAYS = 5
MIN_CLUSTER_SIZE = 2
_GRID_SIZE_DEG = 0.05


def add_clusters(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    dates = pd.to_datetime(df["acq_date"])
    lats = df["latitude"].to_numpy(dtype=float)
    lons = df["longitude"].to_numpy(dtype=float)
    days = (dates - dates.min()).dt.days.to_numpy()
    n = len(df)

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Bucket by coarse grid so only nearby pairs are ever compared.
    buckets: dict[tuple[int, int], list[int]] = {}
    for i in range(n):
        key = (round(lats[i] / _GRID_SIZE_DEG), round(lons[i] / _GRID_SIZE_DEG))
        buckets.setdefault(key, []).append(i)

    for (gx, gy), idxs in buckets.items():
        neighbours = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbours.extend(buckets.get((gx + dx, gy + dy), []))
        neighbours = sorted(set(neighbours))
        for i in idxs:
            for j in neighbours:
                if j <= i:
                    continue
                if abs(days[i] - days[j]) > TEMPORAL_THRESHOLD_DAYS:
                    continue
                if haversine_km(lats[i], lons[i], lats[j], lons[j]) <= SPATIAL_THRESHOLD_KM:
                    union(i, j)

    roots = pd.Series([find(i) for i in range(n)])
    counts = roots.value_counts()
    keep = counts[counts >= MIN_CLUSTER_SIZE].index.tolist()
    mapping = {root: f"C{idx + 1}" for idx, root in enumerate(keep)}
    df["cluster_id"] = roots.map(mapping).to_numpy()

    rows = []
    for cid, sub in df.dropna(subset=["cluster_id"]).groupby("cluster_id"):
        top = sub.loc[sub["risk_score"].idxmax()]
        sub_dates = pd.to_datetime(sub["acq_date"])
        confirming = sorted({
            s for entry in sub["sources_confirming"].fillna("")
            for s in str(entry).split("|") if s
        })

        rows.append({
            "cluster_id": cid,
            "count": int(len(sub)),
            "centroid_lat": round(float(sub["latitude"].mean()), 5),
            "centroid_lon": round(float(sub["longitude"].mean()), 5),
            "first_date": sub_dates.min().strftime("%Y-%m-%d"),
            "last_date": sub_dates.max().strftime("%Y-%m-%d"),
            "persistence_days": int((sub_dates.max() - sub_dates.min()).days + 1),
            "max_frp": round(float(sub["frp"].max()), 2),
            "avg_frp": round(float(sub["frp"].mean()), 2),
            "max_priority": round(float(sub["risk_score"].max()), 3),
            "max_fusion": round(float(sub["fusion_score"].max()), 3),
            "dominant_label": sub["final_label"].mode()[0],
            "dominant_temp_class": sub["temp_class"].mode()[0],
            "max_est_temp_k": (
                round(float(sub["est_temp_k"].max()), 1)
                if sub["est_temp_k"].notna().any() else None
            ),
            "sources_confirming": "|".join(confirming),
            "sources_confirming_count": len(confirming),
            "new_source": bool(sub["new_source"].any()),
            "industrial_context": top["industrial_context"],
            "nearest_facility_name": top["nearest_facility_name"],
            "nearest_facility_type": top["nearest_facility_type"],
            "facility_uid": top["facility_uid"],
            "dist_to_industrial_km": round(float(top["dist_to_industrial_km"]), 2),
        })

    clusters = pd.DataFrame(rows).sort_values("max_priority", ascending=False)
    return df, clusters.reset_index(drop=True)
