import pandas as pd
import json
from math import radians, sin, cos, sqrt, atan2

df = pd.read_csv("firms_final.csv")

with open("osm_industrial.json") as f:
    osm = json.load(f)

industrial_points = []
for el in osm["elements"]:
    if el["type"] == "node":
        industrial_points.append((el["lat"], el["lon"]))
    elif "center" in el:
        industrial_points.append((el["center"]["lat"], el["center"]["lon"]))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def nearest_point(lat, lon):
    best = min(industrial_points, key=lambda p: haversine(lat, lon, p[0], p[1]))
    return best[0], best[1]

results = df.apply(lambda row: nearest_point(row["latitude"], row["longitude"]), axis=1)
df["nearest_facility_lat"] = [r[0] for r in results]
df["nearest_facility_lon"] = [r[1] for r in results]

df.to_csv("firms_final.csv", index=False)
print("Saved nearest_facility_lat/lon to firms_final.csv")
print(df[["latitude","longitude","dist_to_industrial_km","nearest_facility_lat","nearest_facility_lon"]].head())