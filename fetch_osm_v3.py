import requests
import json
import time

overpass_url = "https://overpass-api.de/api/interpreter"
headers = {"User-Agent": "AntriX-Project/1.0"}

regions = {
    "bokaro_jamshedpur": "22.5,85.5,24.5,87.0",
    "chennai_ennore": "12.5,79.5,14.0,80.5",
    "mumbai_industrial": "18.5,72.5,19.5,73.5",
    "odisha_mining": "20.5,84.0,22.5,86.5",
    "chhattisgarh_steel": "20.5,81.0,22.5,83.5",
    "ncr_delhi": "27.5,76.5,29.0,78.0"
}

with open("osm_industrial.json") as f:
    existing = json.load(f)
all_elements = existing["elements"]
print("Starting with existing:", len(all_elements))

for name, bbox in regions.items():
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
    print(f"Querying {name}...")
    r = requests.post(overpass_url, data={"data": query}, headers=headers, timeout=60)
    if r.status_code == 200:
        data = r.json()
        all_elements.extend(data["elements"])
        print(f"  {name}: {len(data['elements'])} features")
    else:
        print(f"  {name}: FAILED status {r.status_code}")
    time.sleep(15)

print("Total elements:", len(all_elements))
with open("osm_industrial.json", "w") as f:
    json.dump({"elements": all_elements}, f)
print("Saved to osm_industrial.json")