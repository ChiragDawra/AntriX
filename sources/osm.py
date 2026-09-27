"""OpenStreetMap industrial features, via the Overpass API.

OSM is the only one of the four registries with *area* geometry and long-tail
coverage: small foundries, brick kilns and unnamed industrial estates that no
commercial tracker lists. It is also the least consistent, which is exactly why
it is cross-checked against the three curated registries rather than trusted
alone.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from sources import schema

SOURCE = "osm"
LABEL = "OpenStreetMap (Overpass)"
SHORT = "OSM"
LICENSE = "ODbL 1.0 — © OpenStreetMap contributors"
HOMEPAGE = "https://www.openstreetmap.org/copyright"
FILENAME = "osm_industrial.json"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Industrial belts, queried one bbox at a time because a single India-wide
# Overpass query for these tags times out.
REGIONS = {
    "bokaro_jamshedpur": "22.5,85.5,24.5,87.0",
    "chennai_ennore": "12.5,79.5,14.0,80.5",
    "mumbai_industrial": "18.5,72.5,19.5,73.5",
    "odisha_mining": "20.5,84.0,22.5,86.5",
    "chhattisgarh_steel": "20.5,81.0,22.5,83.5",
    "ncr_delhi": "27.5,76.5,29.0,78.0",
    "gujarat_refineries": "21.0,68.5,23.5,73.0",
    "vizag_paradip": "17.0,81.5,21.0,87.0",
}

# Tags worth pulling. The first six were in the original query; refineries,
# flares, cement works and smelters were added because those are precisely the
# facilities that produce a persistent high-temperature signature.
TAG_QUERIES = [
    'way["landuse"="industrial"]',
    'way["man_made"="works"]',
    'node["man_made"="works"]',
    'way["power"="plant"]',
    'way["man_made"="petroleum_well"]',
    'node["man_made"="flare"]',
    'way["industrial"="refinery"]',
    'way["industrial"="factory"]',
]


def _ftype(tags: dict) -> str:
    """Map OSM tags to our coarse facility class, most specific first."""
    product = " ".join(
        str(tags.get(k, "")).lower()
        for k in ("product", "works", "industrial", "industry", "craft", "name")
    )

    if tags.get("man_made") == "flare" or "flare" in product:
        return "flare"
    if "refinery" in product or tags.get("industrial") == "refinery":
        return "refinery"
    if "steel" in product or "ispat" in product or "foundry" in product:
        return "steel"
    if "cement" in product or "clinker" in product:
        return "cement"
    if "smelter" in product or "aluminium" in product or "aluminum" in product:
        return "smelter"
    if tags.get("power") == "plant":
        return "power_plant"
    if tags.get("man_made") == "works":
        return "works"
    if tags.get("landuse") == "industrial":
        return "industrial_area"
    return "other"


def fetch(raw_dir: Path, force: bool = False) -> dict:
    """Re-run the Overpass queries.

    Slow (minutes, with a mandatory pause between regions to stay inside
    Overpass's fair-use policy), so an existing extract is reused unless
    ``force`` is set.
    """
    raw_dir = Path(raw_dir)
    dest = raw_dir / FILENAME

    if dest.exists() and not force:
        return {"status": "cached", "path": str(dest), "bytes": dest.stat().st_size}

    elements, failed = [], []
    body = "\n      ".join(f"{q}({{bbox}});" for q in TAG_QUERIES)

    for name, bbox in REGIONS.items():
        query = f"[out:json][timeout:90];\n    (\n      {body.format(bbox=bbox)}\n    );\n    out center;"
        try:
            r = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": "SATAT-Registry/1.0"},
                timeout=120,
            )
            r.raise_for_status()
            elements.extend(r.json()["elements"])
        except Exception as exc:
            failed.append(f"{name}: {type(exc).__name__}")
        time.sleep(15)

    if not elements:
        return {"status": "unavailable", "path": None, "error": "; ".join(failed)}

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"elements": elements}))
    return {
        "status": "ok",
        "path": str(dest),
        "bytes": dest.stat().st_size,
        "failed_regions": failed,
    }


def load(raw_dir: Path):
    path = Path(raw_dir) / FILENAME
    if not path.exists():
        return schema.empty_frame()

    data = json.loads(path.read_text())
    rows = []

    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        # Ways carry a computed 'center' (out center); nodes carry lat/lon.
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None or lon is None:
            continue

        rows.append({
            "source": SOURCE,
            "source_id": f"{el.get('type')}/{el.get('id')}",
            "name": tags.get("name", ""),
            "ftype": _ftype(tags),
            "lat": lat,
            "lon": lon,
            "capacity_value": None,
            "capacity_unit": "",
            "status": "unknown",
            "subnational": tags.get("addr:state", ""),
            "attrs": {
                k: v for k, v in tags.items()
                if k in ("landuse", "man_made", "power", "industrial", "product",
                         "operator", "plant:source", "plant:output:electricity")
            },
        })

    return schema.finalize(rows)
