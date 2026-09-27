"""Robust FRP baselines.

The previous implementation divided each detection's FRP by the *mean* FRP of
its grid cell. With one or two detections per cell -- the common case -- a
detection is its own baseline, so the ratio is 1.0 and the "abnormality" is
always zero. Where a cell did have several detections, a single strong event
dragged the mean up and suppressed its own score.

Median and MAD fix both problems, and a three-level fallback (cell, then
0.5-degree region, then the whole scene) means a cell with a single detection
is still measured against something real.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Scale factor making the MAD a consistent estimator of sigma for normal data.
_MAD_TO_SIGMA = 1.4826
_MIN_CELL_SAMPLES = 4

# Floor on the baseline spread, in MW. Where a cell's detections happen to be
# nearly identical the MAD collapses toward zero and ordinary measurement
# noise starts reading as a multi-sigma anomaly. FIRMS FRP is not precise to
# better than a few tenths of a megawatt, so the spread is never allowed
# below that.
_MIN_SIGMA_MW = 0.5


def _mad(values: np.ndarray) -> float:
    med = np.median(values)
    return float(np.median(np.abs(values - med)))


def add_robust_baseline(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    frp = df["frp"].astype(float)

    scene_med = float(frp.median())
    scene_sigma = max(_mad(frp.to_numpy()) * _MAD_TO_SIGMA, _MIN_SIGMA_MW)

    region = pd.DataFrame({
        "r_lat": df["latitude"].round(1),
        "r_lon": df["longitude"].round(1),
        "frp": frp,
    })
    region_stats = region.groupby(["r_lat", "r_lon"])["frp"].agg(
        r_med="median", r_n="size",
        r_mad=lambda s: _mad(s.to_numpy()) * _MAD_TO_SIGMA,
    ).reset_index()

    cell_stats = df.groupby(["grid_lat", "grid_lon"])["frp"].agg(
        c_med="median", c_n="size",
        c_mad=lambda s: _mad(s.to_numpy()) * _MAD_TO_SIGMA,
    ).reset_index()

    df["r_lat"] = df["latitude"].round(1)
    df["r_lon"] = df["longitude"].round(1)
    df = df.merge(region_stats, on=["r_lat", "r_lon"], how="left")
    df = df.merge(cell_stats, on=["grid_lat", "grid_lon"], how="left")

    # Use the tightest baseline that has enough samples behind it.
    use_cell = df["c_n"] >= _MIN_CELL_SAMPLES
    use_region = (~use_cell) & (df["r_n"] >= _MIN_CELL_SAMPLES)

    baseline = pd.Series(scene_med, index=df.index)
    sigma = pd.Series(scene_sigma, index=df.index)
    level = pd.Series("scene", index=df.index)

    baseline = baseline.mask(use_region, df["r_med"]).mask(use_cell, df["c_med"])
    sigma = sigma.mask(use_region, df["r_mad"]).mask(use_cell, df["c_mad"])
    level = level.mask(use_region, "region").mask(use_cell, "cell")

    # A degenerate MAD (every value identical) would divide by zero, and a
    # near-degenerate one would turn noise into a finding.
    sigma = sigma.fillna(scene_sigma).replace(0, np.nan).fillna(scene_sigma)
    sigma = sigma.clip(lower=_MIN_SIGMA_MW)

    df["baseline_frp"] = baseline
    df["baseline_level"] = level
    df["frp_robust_z"] = ((df["frp"] - baseline) / sigma).clip(-10, 25)
    # 0-1 abnormality: 3 sigma above the local baseline saturates the scale.
    df["thermal_abnormality"] = (df["frp_robust_z"] / 3.0).clip(0, 1)
    df["frp_intensity_norm"] = df["frp"].rank(pct=True)

    return df.drop(columns=["r_lat", "r_lon", "r_med", "r_n", "r_mad",
                            "c_med", "c_n", "c_mad"])
