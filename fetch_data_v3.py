import os

import pandas as pd

# NASA FIRMS key. Set FIRMS_MAP_KEY in the environment:
#
#     export FIRMS_MAP_KEY=your_key_here
#
# The literal below is the team's existing shared key, kept as a
# fallback so a fresh clone still runs. It IS in git history, so
# rotate it at https://firms.modaps.eosdis.nasa.gov/api/ and drop
# this fallback before the repo goes public.
FALLBACK_MAP_KEY = "c0e49cbebb6c9efa4d70669ffaed45a1"
MAP_KEY = os.environ.get("FIRMS_MAP_KEY") or FALLBACK_MAP_KEY

if MAP_KEY == FALLBACK_MAP_KEY:
    print("NOTE: using the committed FIRMS key; set FIRMS_MAP_KEY to override.")

DAY_RANGE = 5
AREA = "68,8,90,32"

sources = [
    "VIIRS_SNPP_NRT",
    "MODIS_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",   # newest VIIRS platform: extra daily revisit
]
all_dfs = []

for src in sources:
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{src}/{AREA}/{DAY_RANGE}"
    try:
        df = pd.read_csv(url)
        df["source_sensor"] = src
        all_dfs.append(df)
        print(f"{src}: {len(df)} rows")
    except Exception as e:
        print(f"{src}: FAILED - {e}")

combined = pd.concat(all_dfs, ignore_index=True)
print("Total combined rows:", len(combined))
combined.to_csv("firms_raw.csv", index=False)
print("Saved to firms_raw.csv")