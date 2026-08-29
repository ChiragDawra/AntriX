import pandas as pd

MAP_KEY = "c0e49cbebb6c9efa4d70669ffaed45a1"
DAY_RANGE = 5
AREA = "68,8,90,32"

sources = ["VIIRS_SNPP_NRT", "MODIS_NRT", "VIIRS_NOAA20_NRT"]
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