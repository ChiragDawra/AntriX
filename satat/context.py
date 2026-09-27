"""Regional and seasonal context.

Without this the pipeline confidently reports an industrial emergency across
Punjab every November, because stubble burning produces tens of thousands of
genuine, persistent, high-FRP detections in a belt that also happens to be
full of OSM ``landuse=industrial`` polygons.
"""

from __future__ import annotations

import pandas as pd

from satat import config


def agricultural_context(df: pd.DataFrame) -> pd.DataFrame:
    """Flag detections inside a crop-residue burning region during its season."""
    df = df.copy()
    month = pd.to_datetime(df["acq_date"], errors="coerce").dt.month

    flag = pd.Series(False, index=df.index)
    region_name = pd.Series("", index=df.index)

    for name, lat_min, lon_min, lat_max, lon_max, months in config.AGRI_BURN_REGIONS:
        in_box = (
            df["latitude"].between(lat_min, lat_max)
            & df["longitude"].between(lon_min, lon_max)
        )
        in_season = month.isin(months)
        hit = in_box & in_season
        region_name = region_name.mask(hit & (region_name == ""), name)
        flag |= hit

    df["agri_season_context"] = flag
    df["agri_season_region"] = region_name
    return df
