import pandas as pd

MAP_KEY = "c0e49cbebb6c9efa4d70669ffaed45a1"
SOURCE = "VIIRS_SNPP_NRT"
DAY_RANGE = 5

AREA = "68,8,90,32"  # covers most of India

url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{AREA}/{DAY_RANGE}"

df = pd.read_csv(url)
print("Rows fetched:", len(df))
df.to_csv("firms_raw.csv", index=False)
print("Saved to firms_raw.csv")