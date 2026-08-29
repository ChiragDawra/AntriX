"""
Cleans raw FIRMS detections before the analysis pipeline runs.

Two problems this fixes in firms_raw.csv:

1. LOW-CONFIDENCE NOISE
   FIRMS ships a per-detection confidence. VIIRS reports it as
   l/n/h (low/nominal/high); MODIS reports 0-100. Low-confidence
   detections were previously fed straight into labeling and the
   RandomForest, adding noise to both.

2. CROSS-SENSOR DOUBLE COUNTING
   fetch_data_v3.py pulls several satellites (SNPP, NOAA-20,
   NOAA-21, MODIS). When two of them pass over the same fire on
   the same day, that single fire appears as multiple rows. This
   inflated detection counts (notably in dense industrial belts
   like Jharkhand) and also inflated recurrence, since
   compute_recurrence.py counts distinct days per grid cell.

3. OUT-OF-COUNTRY DETECTIONS
   The FIRMS query is a bounding box, so it also returns fires in
   Pakistan, Bangladesh, Myanmar, Nepal and Sri Lanka. The
   dashboard filtered these out in the browser but the summary
   counts did not, so the header total disagreed with the number
   of points actually plotted. Filtering here makes every number
   downstream -- stats, map, clusters -- refer to the same set.

Input:  firms_raw.csv
Output: firms_clean.csv
"""

import json
from pathlib import Path

import pandas as pd
from shapely.geometry import shape
from shapely.prepared import prep
from shapely.geometry import Point

BOUNDARY_FILE = (
    Path(__file__).resolve().parent
    / "antrix_app" / "static" / "india_boundary.json"
)

# Matches the grid used by compute_recurrence.py so that dedup and
# recurrence agree on what "the same place" means (~1.1 km).
GRID_DECIMALS = 2

# MODIS confidence is 0-100; anything below this is dropped.
MODIS_MIN_CONFIDENCE = 50

# VIIRS confidence classes to drop.
VIIRS_DROP_CLASSES = {"l"}

# Preference order when collapsing duplicates of the same fire.
CONFIDENCE_RANK = {"h": 3, "n": 2, "l": 1}
SENSOR_RANK = {
    "VIIRS_NOAA21_NRT": 4,   # newest VIIRS
    "VIIRS_NOAA20_NRT": 3,
    "VIIRS_SNPP_NRT": 2,
    "MODIS_NRT": 1,          # 1 km pixel, coarsest
}


def confidence_rank(value):
    """Rank a FIRMS confidence value so VIIRS and MODIS are comparable."""
    text = str(value).strip().lower()
    if text in CONFIDENCE_RANK:
        return CONFIDENCE_RANK[text]
    try:
        # MODIS numeric 0-100 -> same 1-3 scale as VIIRS.
        numeric = float(text)
    except ValueError:
        return 0
    if numeric >= 80:
        return 3
    if numeric >= 50:
        return 2
    return 1


def keep_confidence(value):
    text = str(value).strip().lower()
    if text in CONFIDENCE_RANK:
        return text not in VIIRS_DROP_CLASSES
    try:
        return float(text) >= MODIS_MIN_CONFIDENCE
    except ValueError:
        # Unknown format: keep rather than silently discard data.
        return True


def filter_to_india(fires):
    """
    Keep only detections inside the Indian land boundary.

    Returns the frame unchanged (with a warning) if the boundary file
    has not been generated yet, so the pipeline still runs.
    """
    if not BOUNDARY_FILE.exists():
        print(
            f"WARNING: {BOUNDARY_FILE.name} missing -- skipping country "
            "filter. Run build_india_boundary.py to enable it."
        )
        return fires

    with open(BOUNDARY_FILE) as f:
        india = prep(shape(json.load(f)["geometry"]))

    inside = fires.apply(
        lambda r: india.contains(Point(r["longitude"], r["latitude"])),
        axis=1,
    )
    return fires[inside].copy()


def main():
    fires = pd.read_csv("firms_raw.csv")
    start_rows = len(fires)
    print(f"Raw detections: {start_rows}")

    # --- 1. confidence filter -------------------------------------
    fires = fires[fires["confidence"].apply(keep_confidence)].copy()
    after_confidence = len(fires)
    print(
        f"Dropped {start_rows - after_confidence} low-confidence "
        f"detections -> {after_confidence} remain"
    )

    # --- 2. restrict to India -------------------------------------
    fires = filter_to_india(fires)
    after_country = len(fires)
    print(
        f"Dropped {after_confidence - after_country} detections outside "
        f"India -> {after_country} remain"
    )

    # --- 3. cross-sensor dedup ------------------------------------
    fires["_conf_rank"] = fires["confidence"].apply(confidence_rank)
    fires["_sensor_rank"] = fires["source_sensor"].map(SENSOR_RANK).fillna(0)
    fires["_grid_lat"] = fires["latitude"].round(GRID_DECIMALS)
    fires["_grid_lon"] = fires["longitude"].round(GRID_DECIMALS)

    # Best row per (place, day): strongest confidence, then strongest
    # thermal signal, then the finest-resolution sensor.
    fires = fires.sort_values(
        ["_conf_rank", "frp", "_sensor_rank"], ascending=False
    )
    deduped = fires.drop_duplicates(
        subset=["_grid_lat", "_grid_lon", "acq_date"], keep="first"
    )

    removed = after_country - len(deduped)
    print(
        f"Collapsed {removed} cross-sensor duplicate detections "
        f"-> {len(deduped)} unique fire-days"
    )

    deduped = deduped.drop(
        columns=["_conf_rank", "_sensor_rank", "_grid_lat", "_grid_lon"]
    ).sort_values(["acq_date", "latitude", "longitude"])

    deduped.to_csv("firms_clean.csv", index=False)
    print(
        f"\nSaved firms_clean.csv: {start_rows} raw -> {len(deduped)} clean "
        f"({start_rows - len(deduped)} removed)"
    )
    print(f"Date range: {deduped['acq_date'].min()} to {deduped['acq_date'].max()}")
    print("Detections per sensor:")
    print(deduped["source_sensor"].value_counts().to_string())


if __name__ == "__main__":
    main()
