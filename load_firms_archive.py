"""Build firms_raw.csv from FIRMS "Download" archives instead of the live API.

The API route (fetch_data_v3.py) is capped at a few days per request. For a
multi-month window, FIRMS hands out zip files from its download tool, one per
sensor, each holding a science-quality ``fire_archive_*`` file for the older
months and a ``fire_nrt_*`` file for the recent ones.

    python load_firms_archive.py                 # every zip in data/firms/
    python load_firms_archive.py path/to/dir     # zips somewhere else

Two differences from the API output are normalised here so the rest of the
pipeline never has to know which route the data came in by:

* The download tool uses MODIS column names for VIIRS too (``brightness`` /
  ``bright_t31``). The physics stage reads VIIRS I4/I5 as ``bright_ti4`` /
  ``bright_ti5``, so VIIRS rows are renamed.
* Where archive and NRT overlap for the same sensor, the archive row wins: it
  is the reprocessed, science-quality version of the same observation.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = ROOT / "data" / "firms"

# Download-tool product codes -> the source_sensor names the API route uses,
# with _SP for standard (archive) processing so provenance survives.
SENSORS = {
    "J2V-C2": "VIIRS_NOAA21",
    "J1V-C2": "VIIRS_NOAA20",
    "SV-C2": "VIIRS_SNPP",
    "M-C61": "MODIS",
}

KEY = ["latitude", "longitude", "acq_date", "acq_time", "satellite"]


def read_zip(path: Path) -> pd.DataFrame:
    match = re.search(r"DL_FIRE_(.+?)_\d+\.zip$", path.name)
    if not match or match.group(1) not in SENSORS:
        raise ValueError(f"{path.name}: not a recognised FIRMS download")
    sensor = SENSORS[match.group(1)]

    frames = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".csv"):
                continue
            kind = "SP" if name.startswith("fire_archive") else "NRT"
            with archive.open(name) as handle:
                df = pd.read_csv(handle)
            df["source_sensor"] = f"{sensor}_{kind}"
            df["_archive"] = kind == "SP"
            frames.append(df)
            print(f"  {name}: {len(df):>6} rows  "
                  f"{df['acq_date'].min()} -> {df['acq_date'].max()}")

    df = pd.concat(frames, ignore_index=True)

    if sensor.startswith("VIIRS"):
        df = df.rename(columns={"brightness": "bright_ti4", "bright_t31": "bright_ti5"})

    df = df.sort_values("_archive", ascending=False)
    before = len(df)
    df = df.drop_duplicates(subset=KEY, keep="first")
    if before != len(df):
        print(f"  archive/NRT overlap: kept archive for {before - len(df)} rows")
    return df.drop(columns="_archive")


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    zips = sorted(folder.glob("DL_FIRE_*.zip"))
    if not zips:
        sys.exit(f"No DL_FIRE_*.zip files in {folder}")

    frames = []
    for path in zips:
        print(path.name)
        frames.append(read_zip(path))

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.rename(columns={"type": "firms_type"})
    combined.to_csv(ROOT / "firms_raw.csv", index=False)

    print(f"\nSaved firms_raw.csv: {len(combined)} rows, "
          f"{combined['acq_date'].min()} -> {combined['acq_date'].max()}")
    print(combined["source_sensor"].value_counts().to_string())


if __name__ == "__main__":
    main()
