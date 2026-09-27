"""World Resources Institute — Global Power Plant Database.

~35k plants worldwide, ~1.6k in India, with capacity, primary fuel, owner and
commissioning year. Published by WRI under CC BY 4.0.
"""

from __future__ import annotations

import csv
from pathlib import Path

from sources import schema
from sources._http import download

SOURCE = "wri"
LABEL = "WRI Global Power Plant DB"
SHORT = "WRI"
LICENSE = "CC BY 4.0 — World Resources Institute"
HOMEPAGE = "https://datasets.wri.org/dataset/globalpowerplantdatabase"
URL = (
    "https://raw.githubusercontent.com/wri/global-power-plant-database/"
    "master/output_database/global_power_plant_database.csv"
)
FILENAME = "wri_global_power_plant_database.csv"

# WRI's fuel vocabulary -> our coarse class. Only combustion plants can plausibly
# produce a thermal signature, but the non-combustion ones stay in the registry
# so that a detection next to a solar park can be explained as *not* industrial.
_THERMAL_FUELS = {"Coal", "Gas", "Oil", "Petcoke", "Biomass", "Waste", "Cogeneration"}


def fetch(raw_dir: Path, force: bool = False) -> dict:
    return download(URL, Path(raw_dir) / FILENAME, force=force)


def load(raw_dir: Path):
    path = Path(raw_dir) / FILENAME
    if not path.exists():
        return schema.empty_frame()

    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            if rec.get("country") != "IND":
                continue
            fuel = (rec.get("primary_fuel") or "").strip()
            rows.append({
                "source": SOURCE,
                "source_id": rec.get("gppd_idnr") or "",
                "name": rec.get("name") or "",
                "ftype": "power_plant",
                "lat": rec.get("latitude"),
                "lon": rec.get("longitude"),
                "capacity_value": rec.get("capacity_mw"),
                "capacity_unit": "MW",
                "status": "operating",   # WRI only publishes commissioned plants
                "subnational": "",
                "attrs": {
                    "primary_fuel": fuel,
                    "thermal_fuel": fuel in _THERMAL_FUELS,
                    "owner": rec.get("owner") or "",
                    "commissioning_year": rec.get("commissioning_year") or "",
                    "url": rec.get("url") or "",
                },
            })
    return schema.finalize(rows)
