import requests
import json

overpass_url = "https://overpass-api.de/api/interpreter"
headers = {"User-Agent": "AntriX-Project/1.0"}

regions = {
    "gujarat": "20.5,69.5,23.5,73.5",
    "vizag_paradip": "17.0,82.0,20.5,87.0",
    "bokaro_jamshedpur": "22.5,85.5,24.5,87.0",
    "chennai_ennore": "12.5,79.5,14.0,80.5",
    "mumbai_industrial": "18.5,72.5,19.5,73.5"
}

all_elements = []

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

print("Total elements:", len(all_elements))

with open("osm_industrial.json", "w") as f:
    json.dump({"elements": all_elements}, f)
print("Saved to osm_industrial.json")