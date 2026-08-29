"""
Builds a small India outline for the dashboard's point-in-country filter.

Why this exists:

The dashboard used to fetch the India boundary at page load from
raw.githubusercontent.com (~6.6 MB). That fetch sat inside the same
Promise.all as the detection data, so nothing rendered until it
finished -- on a slow connection, or if GitHub throttled the request,
the map and feed stayed completely empty. An external, unpinned URL in
the critical render path is also a poor dependency for a live demo.

This script dissolves the local 21 MB india_states.geojson down to a
single simplified outline (a few hundred KB) that ships with the app
and is served locally, so the map has no external dependency.

Run once; re-run only if india_states.geojson changes.

Output: antrix_app/static/india_boundary.json
"""

import json
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "antrix_app" / "templates" / "india_states.geojson"
OUT_DIR = ROOT / "antrix_app" / "static"
OUT_FILE = OUT_DIR / "india_boundary.json"

# ~0.01 degrees is roughly 1 km: far finer than the 375 m-1 km satellite
# pixels being filtered, so simplification cannot change which detections
# fall inside the country.
SIMPLIFY_TOLERANCE = 0.01


def main():
    print(f"Reading {SOURCE.name} ({SOURCE.stat().st_size / 1e6:.1f} MB)...")
    with open(SOURCE) as f:
        collection = json.load(f)

    print(f"Dissolving {len(collection['features'])} state polygons...")
    geometries = [shape(feat["geometry"]) for feat in collection["features"]]
    country = unary_union(geometries)

    simplified = country.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)

    feature = {
        "type": "Feature",
        "properties": {"name": "India"},
        "geometry": mapping(simplified),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w") as f:
        json.dump(feature, f, separators=(",", ":"))

    size_kb = OUT_FILE.stat().st_size / 1024
    print(f"Wrote {OUT_FILE.relative_to(ROOT)} ({size_kb:.0f} KB)")
    print(f"Geometry: {simplified.geom_type}")


if __name__ == "__main__":
    main()
