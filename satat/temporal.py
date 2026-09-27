"""Temporal signature of each grid cell.

A steel furnace, a gas flare and a stubble fire all show up as a hot pixel.
They differ in *when* and *how often*:

* a flare burns continuously, day and night, every overpass
* a furnace campaign runs for days with a regular rhythm
* a stubble fire burns once, in the afternoon, and is gone

These features carry that difference into the classifier, and they are what
the lifecycle flags (new / reactivated / ceased) are derived from.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from satat import config


def _regularity(days: np.ndarray) -> float:
    """1.0 for perfectly evenly spaced returns, 0.0 for erratic ones.

    Needs at least three visits: with two you have one gap and nothing to
    compare it against, so the feature is undefined rather than guessed.
    """
    if len(days) < 3:
        return np.nan
    gaps = np.diff(np.sort(days))
    if gaps.mean() == 0:
        return np.nan
    cv = gaps.std() / gaps.mean()
    return float(np.clip(1.0 - cv, 0.0, 1.0))


def _cusum_shift(values: np.ndarray) -> float:
    """Largest standardized mean shift between a prefix and the rest.

    A cheap change-point statistic: it answers "did this site's output step up
    or down partway through the window?" without fitting anything.
    """
    if len(values) < 4:
        return 0.0
    spread = values.std()
    if spread == 0:
        return 0.0
    best = 0.0
    for split in range(1, len(values)):
        left, right = values[:split], values[split:]
        if len(left) < 1 or len(right) < 1:
            continue
        shift = abs(right.mean() - left.mean()) / spread
        best = max(best, shift)
    return float(min(best, 4.0) / 4.0)


def add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    """Attach per-cell temporal features to every detection."""
    df = df.copy()
    df["grid_lat"] = df["latitude"].round(config.GRID_DECIMALS)
    df["grid_lon"] = df["longitude"].round(config.GRID_DECIMALS)

    dates = pd.to_datetime(df["acq_date"], errors="coerce")
    df["_day"] = (dates - dates.min()).dt.days.astype(float)
    window_last = df["_day"].max()
    window_days = max(float(window_last) + 1, 1.0)

    df["is_night"] = (df["daynight"].astype(str).str.upper() == "N").astype(int)

    rows = []
    for (glat, glon), grp in df.groupby(["grid_lat", "grid_lon"], sort=False):
        days = grp["_day"].dropna().to_numpy()
        unique_days = np.unique(days)
        daily_frp = grp.groupby("_day")["frp"].mean().sort_index().to_numpy()

        first_seen, last_seen = unique_days.min(), unique_days.max()

        rows.append({
            "grid_lat": glat,
            "grid_lon": glon,
            "recurrence_days": int(len(unique_days)),
            "detections_in_cell": int(len(grp)),
            "night_fraction": float(grp["is_night"].mean()),
            # Share of the observed window on which this cell was alight.
            "duty_cycle": float(len(unique_days) / window_days),
            "inter_arrival_regularity": _regularity(unique_days),
            "frp_shift": _cusum_shift(daily_frp),
            "first_seen_day": float(first_seen),
            "last_seen_day": float(last_seen),
            "active_span_days": float(last_seen - first_seen + 1),
        })

    cells = pd.DataFrame(rows)

    # Lifecycle. "New" means the cell only started appearing in the last two
    # days of the window; "ceased" means it was active early and has been dark
    # since. Both are investigation triggers in their own right: a new
    # persistent source is an unpermitted start-up, a ceased one is a shutdown.
    cells["new_source"] = (
        (cells["first_seen_day"] >= window_last - 1) & (cells["recurrence_days"] >= 1)
    )
    cells["ceased"] = (
        (cells["last_seen_day"] <= window_last - 3) & (cells["recurrence_days"] >= 2)
    )
    cells["reactivated"] = (
        (cells["active_span_days"] > cells["recurrence_days"] + 1)
        & (cells["recurrence_days"] >= 2)
    )

    df = df.drop(columns=[c for c in cells.columns
                          if c in df.columns and c not in ("grid_lat", "grid_lon")])
    df = df.merge(cells, on=["grid_lat", "grid_lon"], how="left")

    df["persistence_norm"] = (
        df["recurrence_days"] / config.OBSERVATION_WINDOW_DAYS
    ).clip(0, 1)
    df["nocturnal_score"] = df["night_fraction"].clip(0, 1)
    df["observation_window_days"] = window_days

    return df.drop(columns=["_day"])
