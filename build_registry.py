#!/usr/bin/env python3
"""Build the four-source facility registry.

    python build_registry.py              # fetch what is missing, then build
    python build_registry.py --no-fetch   # build from whatever is already in data/raw
    python build_registry.py --force      # re-download every source

Outputs into data/registry/:
    facilities.csv          one row per source record, tagged with facility_uid
    facility_groups.csv     one row per real-world site
    registry_manifest.json  per-source status, counts and licensing
"""

import json
import shutil
import sys
from pathlib import Path

from sources import registry

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "registry"
APP_DIR = ROOT / "antrix_app"


def main() -> None:
    do_fetch = "--no-fetch" not in sys.argv
    force = "--force" in sys.argv

    RAW.mkdir(parents=True, exist_ok=True)

    # The original pull lives at the repo root; seed data/raw from it so a
    # first run does not sit through a fresh Overpass crawl.
    legacy_osm = ROOT / "osm_industrial.json"
    if legacy_osm.exists() and not (RAW / "osm_industrial.json").exists():
        shutil.copy(legacy_osm, RAW / "osm_industrial.json")
        print(f"Seeded data/raw/osm_industrial.json from {legacy_osm.name}")

    manifest = registry.build(RAW, OUT, fetch=do_fetch, force=force)

    print("\nRegistry built.")
    for name, info in manifest["sources"].items():
        state = info["status"]
        line = f"  {info['short']:<10} {state:<12} {info['records']:>6} records"
        if state != "loaded" and info.get("hint"):
            line += f"\n      {info['hint']}"
        print(line)

    print(f"\n  {manifest['total_records']} source records -> "
          f"{manifest['total_sites']} distinct sites "
          f"({manifest['multi_source_sites']} confirmed by more than one registry)")

    for f in ("facility_groups.csv", "registry_manifest.json"):
        shutil.copy(OUT / f, APP_DIR / f)
    print(f"\nCopied registry into {APP_DIR}/ for the dashboard.")


if __name__ == "__main__":
    main()
