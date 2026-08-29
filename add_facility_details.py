import pandas as pd
import json
from math import radians, sin, cos, sqrt, atan2

df = pd.read_csv("firms_final.csv")

with open("osm_industrial.json") as f:
    osm = json.load(f)

# Check if tags exist
sample = osm["elements"][0]
print("Sample element keys:", sample.keys())
print("Sample tags:", sample.get("tags", "NO TAGS FOUND"))

industrial_points = []
for el in osm["elements"]:
    tags = el.get("tags", {})
    if el["type"] == "node":
        lat, lon = el["lat"], el["lon"]
    elif "center" in el:
        lat, lon = el["center"]["lat"], el["center"]["lon"]
    else:
        continue
    industrial_points.append((lat, lon, tags))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def facility_type(tags):
    if tags.get("power") == "plant":
        return "Thermal power plant"
    if tags.get("man_made") == "works":
        return "Industrial works"
    if tags.get("landuse") == "industrial":
        return "Industrial area"
    return "Industrial facility"

def nearest_facility_info(lat, lon):
    best = min(industrial_points, key=lambda p: haversine(lat, lon, p[0], p[1]))
    name = best[2].get("name", "Unnamed industrial facility")
    ftype = facility_type(best[2])
    return name, ftype

results = df.apply(lambda row: nearest_facility_info(row["latitude"], row["longitude"]), axis=1)
df["nearest_facility_name"] = [r[0] for r in results]
df["nearest_facility_type"] = [r[1] for r in results]

named_count = (df["nearest_facility_name"] != "Unnamed industrial facility").sum()
print(f"\nDetections with a named nearest facility: {named_count} / {len(df)}")
print(df[["dist_to_industrial_km","nearest_facility_name","nearest_facility_type"]].head(10))

df.to_csv("firms_final.csv", index=False)
print("\nSaved firms_final.csv with facility name/type")