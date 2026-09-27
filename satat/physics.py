"""Sub-pixel fire temperature and area from the two thermal channels.

FIRMS reports brightness temperatures, not fire temperatures. A 375 m VIIRS
pixel containing a 30 m flare at 1800 K and a 100 m stubble fire at 700 K can
report the same 340 K brightness temperature, and FRP alone cannot separate
them. The bi-spectral (Dozier) retrieval can: it treats the pixel as a hot
fraction *p* at temperature *T_fire* against a background, and solves the two
channel equations for both unknowns.

    L4_obs = p * B(λ4, T_fire) + (1 - p) * L4_background
    L5_obs = p * B(λ5, T_fire) + (1 - p) * L5_background

Eliminating *p* leaves one equation in *T_fire*, which is solved by bisection.

Honest limits, which the dashboard repeats rather than hides:

* VIIRS I4 saturates at 367 K. For a saturated pixel the retrieval returns a
  *lower bound* and the row is flagged ``i4_saturated``.
* The background is estimated from neighbouring detections, not from true
  non-fire pixels, so it is an approximation.
* MODIS rows use band 21/31 instead of I4/I5, with correspondingly coarser
  1 km geometry.

References: Dozier (1981); Giglio & Kendall (2001); Elvidge et al. (2013),
the VIIRS Nightfire method NOAA EOG's flare inventory is built on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from satat import config

# Minimum channel excess over background for a retrieval to mean anything.
# 3 K at 3.7 um is comfortably above VIIRS noise; 1 K at 11 um is the point
# below which the second equation stops constraining the temperature.
MIN_CH4_EXCESS_K = 3.0
MIN_CH5_EXCESS_K = 1.0

# Background at 3.7 um relative to 11 um over land: solar reflection lifts the
# shortwave channel by roughly this much during the day, very little at night.
DAY_BG_OFFSET_K = 8.0
NIGHT_BG_OFFSET_K = 1.0

# Planck constants in SI.
_H = 6.62607015e-34
_C = 2.99792458e8
_KB = 1.380649e-23


def planck_radiance(wavelength_um: float, temperature_k):
    """Spectral radiance, W m-2 sr-1 m-1, for a blackbody."""
    lam = wavelength_um * 1e-6
    t = np.asarray(temperature_k, dtype=float)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        numerator = 2.0 * _H * _C ** 2 / lam ** 5
        exponent = _H * _C / (lam * _KB * t)
        return numerator / (np.expm1(exponent))


def _residual(t_fire, l4_obs, l4_bg, l5_obs, l5_bg, wl4, wl5):
    """Channel-5 mismatch for a candidate fire temperature.

    ``p`` is fixed by the channel-4 equation; the residual is what channel 5
    then disagrees by. The root is the temperature that satisfies both.
    """
    b4 = planck_radiance(wl4, t_fire)
    denom = b4 - l4_bg
    if denom <= 0:
        return np.inf
    p = (l4_obs - l4_bg) / denom
    if p <= 0 or p > 1:
        # Outside the admissible range the residual has no meaning; the
        # search bounds are chosen so this should not be reached.
        return np.inf
    b5 = planck_radiance(wl5, t_fire)
    return p * (b5 - l5_bg) - (l5_obs - l5_bg)


def solve_subpixel(bt4, bt5, bg4, bg5, wl4, wl5):
    """Retrieve (T_fire in K, hot fraction p, status) for one pixel.

    The retrieval is only reported when the observation actually constrains
    it. Two unconstrained cases are common and were, in an earlier version of
    this code, silently returned as confident 2400 K "flares":

    ``below_background``  the 3.7 um channel is not meaningfully above the
                          background -- there is no hot spot to solve for
    ``weak_11um``         the 11 um channel shows no excess, so any
                          temperature from ~800 K upwards fits equally well.
                          The bi-spectral method has nothing to bite on and
                          the answer would be an artefact of the search range

    Returning ``nan`` for these is the point: a missing temperature is a fact
    about the observation, and the dashboard reports it as one.
    """
    if not np.isfinite([bt4, bt5, bg4, bg5]).all():
        return np.nan, np.nan, "no_data"

    if bt4 - bg4 < MIN_CH4_EXCESS_K:
        return np.nan, np.nan, "below_background"
    if bt5 - bg5 < MIN_CH5_EXCESS_K:
        return np.nan, np.nan, "weak_11um"

    l4_obs, l4_bg = planck_radiance(wl4, bt4), planck_radiance(wl4, bg4)
    l5_obs, l5_bg = planck_radiance(wl5, bt5), planck_radiance(wl5, bg5)

    # The fire cannot be cooler than the pixel's own brightness temperature:
    # below that the hot fraction would have to exceed the whole pixel. Making
    # that the lower search bound is what keeps the bracket valid -- with a
    # fixed lower bound the residual is undefined below bt4 and the solver
    # reported "no bracket" for perfectly ordinary fires.
    range_lo, range_hi = config.SOLVE_TEMP_RANGE_K
    lo, hi = max(range_lo, bt4 + 0.5), range_hi
    if lo >= hi:
        return np.nan, np.nan, "unconstrained"

    args = (l4_obs, l4_bg, l5_obs, l5_bg, wl4, wl5)

    f_lo, f_hi = _residual(lo, *args), _residual(hi, *args)
    if not np.isfinite(f_lo) or not np.isfinite(f_hi) or f_lo * f_hi > 0:
        return np.nan, np.nan, "no_bracket"

    for _ in range(60):                          # bisection to ~1e-12 relative
        mid = 0.5 * (lo + hi)
        f_mid = _residual(mid, *args)
        if not np.isfinite(f_mid):
            return np.nan, np.nan, "no_bracket"
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    t_fire = 0.5 * (lo + hi)

    # A root pinned against the top of the search range is the solver running
    # out of room, not a measurement.
    if t_fire >= range_hi - 0.01 * (range_hi - range_lo):
        return np.nan, np.nan, "unconstrained"

    b4 = planck_radiance(wl4, t_fire)
    if b4 <= l4_bg:
        return np.nan, np.nan, "no_solution"
    p = float((l4_obs - l4_bg) / (b4 - l4_bg))
    if not (0 < p <= 1):
        return np.nan, np.nan, "no_solution"

    return float(t_fire), p, "ok"


def temp_class(t_fire) -> str:
    """Bucket a retrieved temperature into a combustion regime."""
    if t_fire is None or not np.isfinite(t_fire):
        return "unknown"
    for threshold, name in config.TEMP_CLASS_BANDS:
        if t_fire >= threshold:
            return name
    return "biomass_like"


def channels_for(instrument: str):
    """Which two channels this row's instrument reports."""
    if str(instrument).upper().startswith("MODIS"):
        return config.MODIS_B21_UM, config.MODIS_B31_UM, "brightness", "bright_t31"
    return config.VIIRS_I4_UM, config.VIIRS_I5_UM, "bright_ti4", "bright_ti5"


def _background_table(df, bt5_col: str):
    """Estimate per-region background brightness temperatures.

    FIRMS ships only the pixels that triggered, so there are no true non-fire
    pixels to read a background off.

    The 11 um channel is the usable one: at 375 m a few-MW fire lifts it by
    only a couple of kelvin, so the lower quartile of nearby detections is a
    fair stand-in for the surface. The 3.7 um channel is not -- every
    detection is by definition hot there, and estimating a background from
    them would over-warm it by tens of kelvin and suppress every retrieval.
    It is derived from the 11 um background instead, using the standard
    day/night offset for land at these wavelengths.
    """
    work = df[["latitude", "longitude", "daynight", bt5_col]].copy()
    work["r_lat"] = work["latitude"].round(0)
    work["r_lon"] = work["longitude"].round(0)

    rows = []
    for (rlat, rlon, dn), grp in work.groupby(["r_lat", "r_lon", "daynight"], dropna=False):
        usable = grp.dropna(subset=[bt5_col])
        if usable.empty:
            continue
        bg5 = float(usable[bt5_col].quantile(0.25))
        rows.append({
            "r_lat": rlat, "r_lon": rlon, "daynight": dn,
            "bg5": bg5,
            "bg4": bg5 + (DAY_BG_OFFSET_K if str(dn).upper() == "D" else NIGHT_BG_OFFSET_K),
        })

    return pd.DataFrame(rows)


def add_subpixel_features(df):
    """Retrieve sub-pixel temperature, hot fraction and area for every row."""
    df = df.copy()

    viirs = ~df["instrument"].astype(str).str.upper().str.startswith("MODIS")

    # The two instruments report different channels under different column
    # names; unify them before the retrieval so there is one code path.
    df["bt4_obs"] = np.where(viirs, df.get("bright_ti4"), df.get("brightness"))
    df["bt5_obs"] = np.where(viirs, df.get("bright_ti5"), df.get("bright_t31"))
    df["wl4_um"] = np.where(viirs, config.VIIRS_I4_UM, config.MODIS_B21_UM)
    df["wl5_um"] = np.where(viirs, config.VIIRS_I5_UM, config.MODIS_B31_UM)

    backgrounds = _background_table(df, "bt5_obs")
    df["r_lat"] = df["latitude"].round(0)
    df["r_lon"] = df["longitude"].round(0)
    df = df.merge(backgrounds, on=["r_lat", "r_lon", "daynight"], how="left")

    scene_bg5 = float(pd.to_numeric(df["bt5_obs"], errors="coerce").quantile(0.25))
    df["bg5"] = df["bg5"].fillna(scene_bg5)
    fallback_bg4 = pd.Series(
        scene_bg5 + np.where(df["daynight"].astype(str).str.upper() == "D",
                             DAY_BG_OFFSET_K, NIGHT_BG_OFFSET_K),
        index=df.index,
    )
    df["bg4"] = df["bg4"].fillna(fallback_bg4)

    temps, fractions, statuses = [], [], []
    for row in df.itertuples(index=False):
        t, p, status = solve_subpixel(
            float(row.bt4_obs) if pd.notna(row.bt4_obs) else np.nan,
            float(row.bt5_obs) if pd.notna(row.bt5_obs) else np.nan,
            float(row.bg4), float(row.bg5),
            float(row.wl4_um), float(row.wl5_um),
        )
        temps.append(t)
        fractions.append(p)
        statuses.append(status)

    df["est_temp_k"] = np.round(temps, 1)
    df["hot_fraction"] = fractions
    df["retrieval_status"] = statuses

    # FIRMS gives the along-scan and along-track pixel dimensions in km, so the
    # hot area is the retrieved fraction of the actual pixel footprint.
    pixel_area_m2 = (
        pd.to_numeric(df["scan"], errors="coerce").fillna(0.375)
        * pd.to_numeric(df["track"], errors="coerce").fillna(0.375)
        * 1e6
    )
    df["est_area_m2"] = np.round(df["hot_fraction"] * pixel_area_m2, 1)
    df["pixel_area_m2"] = np.round(pixel_area_m2, 1)

    df["temp_class"] = [temp_class(t) for t in df["est_temp_k"]]
    df["i4_saturated"] = viirs & (
        pd.to_numeric(df["bt4_obs"], errors="coerce") >= config.VIIRS_I4_SATURATION_K
    )
    df["temp_is_lower_bound"] = df["i4_saturated"] & df["est_temp_k"].notna()
    df.loc[df["i4_saturated"], "retrieval_status"] = "saturated_lower_bound"

    return df.drop(columns=["bt4_obs", "bt5_obs", "wl4_um", "wl5_um", "r_lat", "r_lon"])
