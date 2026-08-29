import requests
import json

overpass_url = "https://overpass-api.de/api/interpreter"

bbox = "20.9,72.5,21.3,72.9"

query = f"""
[out:json][timeout:60];
(
  way["landuse"="industrial"]({bbox});
  way["man_made"="works"]({bbox});
  node["man_made"="works"]({bbox});
  way["power"="plant"]({bbox});
);
out center;
"""

headers = {"User-Agent": "AntriX-Project/1.0"}

print("Querying Overpass directly...")
response = requests.post(overpass_url, data={"data": query}, headers=headers, timeout=60)
print("Status code:", response.status_code)
print("Response text (first 300 chars):", response.text[:300])

data = response.json()
print("Elements found:", len(data["elements"]))

with open("osm_industrial.json", "w") as f:
    json.dump(data, f)
print("Saved to osm_industrial.json")