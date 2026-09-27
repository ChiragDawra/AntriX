"""The one facility schema every adapter must produce."""

from __future__ import annotations

import json
import math

import pandas as pd

FACILITY_COLUMNS = [
    "facility_uid",      # assigned by the registry builder after cross-source matching
    "source",            # osm | wri | gem | eog
    "source_id",         # stable id inside that source
    "name",
    "ftype",             # normalized class: power_plant, steel, refinery, flare, industrial_area, ...
    "lat",
    "lon",
    "capacity_value",    # numeric capacity in the source's native unit
    "capacity_unit",     # MW | ttpa | bcm_yr | ""
    "status",            # operating | construction | announced | retired | unknown
    "subnational",
    "attrs",             # JSON blob of source-specific extras
]

# The dashboard, the classifier and the corroboration logic all key off this
# coarse class rather than a source's own vocabulary.
FTYPES = [
    "power_plant",
    "steel",
    "refinery",
    "flare",
    "cement",
    "smelter",
    "works",
    "industrial_area",
    "other",
]

# Generous India bounding box. FIRMS is pulled over "68,8,90,32"; the registry
# box is wider so a detection near the border still finds its facility.
INDIA_BBOX = (6.0, 66.0, 38.0, 98.0)  # lat_min, lon_min, lat_max, lon_max


def in_india(lat: float, lon: float) -> bool:
    lat_min, lon_min, lat_max, lon_max = INDIA_BBOX
    return (
        lat is not None
        and lon is not None
        and not (math.isnan(lat) or math.isnan(lon))
        and lat_min <= lat <= lat_max
        and lon_min <= lon <= lon_max
    )


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=FACILITY_COLUMNS)


def finalize(rows: list[dict]) -> pd.DataFrame:
    """Coerce adapter output into the shared schema.

    Adapters build plain dicts; this is the single place that enforces column
    order, types and the India filter, so a new adapter cannot quietly emit a
    different shape.
    """
    if not rows:
        return empty_frame()

    df = pd.DataFrame(rows)

    for col in FACILITY_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col not in ("lat", "lon", "capacity_value") else float("nan")

    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["capacity_value"] = pd.to_numeric(df["capacity_value"], errors="coerce")

    df = df[df.apply(lambda r: in_india(r["lat"], r["lon"]), axis=1)]

    df["attrs"] = df["attrs"].apply(
        lambda v: v if isinstance(v, str) else json.dumps(v or {}, default=str)
    )
    for col in ("name", "ftype", "status", "subnational", "source", "source_id",
                "capacity_unit"):
        df[col] = df[col].fillna("").astype(str)

    return df[FACILITY_COLUMNS].reset_index(drop=True)
