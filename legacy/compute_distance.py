import pandas as pd
import json
from math import radians, sin, cos, sqrt, atan2

fires = pd.read_csv("firms_clean.csv")

with open("osm_industrial.json") as f:
    osm = json.load(f)

industrial_points = []
for el in osm["elements"]:
    if el["type"] == "node":
        industrial_points.append((el["lat"], el["lon"]))
    elif "center" in el:
        industrial_points.append((el["center"]["lat"], el["center"]["lon"]))

print("Industrial points loaded:", len(industrial_points))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def nearest_dist(lat, lon):
    return min(haversine(lat, lon, p[0], p[1]) for p in industrial_points)

fires["dist_to_industrial_km"] = fires.apply(
    lambda row: nearest_dist(row["latitude"], row["longitude"]), axis=1
)

print(fires[["latitude","longitude","dist_to_industrial_km"]])
fires.to_csv("firms_with_distance.csv", index=False)
print("Saved to firms_with_distance.csv")