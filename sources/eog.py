"""NOAA / Colorado School of Mines EOG — global gas flare inventory.

EOG's VIIRS Nightfire processing yields a per-site annual inventory of gas
flares: location, detection frequency, average radiant heat and estimated
flared volume. It is the reference dataset for "this coordinate is a flare,
not a fire", which is precisely the distinction SATAT has to make.

Availability, honestly stated:

* The official host (``eogdata.mines.edu``) requires a free account and has
  been refusing connections from some networks; the adapter tries it, with the
  URL overridable through ``SATAT_EOG_URL``.
* Failing that, a file dropped at ``data/raw/eog_flares.csv`` (or ``.xlsx``)
  is imported. That is the normal path: download once from EOG with your
  account, drop it in, and it is picked up from then on.
* If neither is present the source reports ``unavailable`` and the dashboard
  shows the NOAA filter as not loaded. It never invents rows — a fabricated
  flare inventory would be worse than no flare inventory.

``sources/eog_columns.py`` documents the column names the importer accepts, so
any of EOG's yearly releases can be dropped in without editing code.
"""

from __future__ import annotations

import os
from pathlib import Path

from sources import schema
from sources._http import download

SOURCE = "eog"
LABEL = "NOAA EOG Global Flare Inventory"
SHORT = "NOAA EOG"
LICENSE = "Earth Observation Group, Payne Institute, Colorado School of Mines"
HOMEPAGE = "https://eogdata.mines.edu/products/vnf/"

# Any of these basenames is accepted; whichever exists first is used.
CANDIDATE_FILES = [
    "eog_flares.csv",
    "eog_flares.xlsx",
    "eog_flares.xls",
    "viirs_global_flaring.xlsx",
]

DEFAULT_URL = os.environ.get("SATAT_EOG_URL", "")

# EOG renames columns between releases; every alias we have seen maps here.
COLUMN_ALIASES = {
    "lat": ["latitude", "lat", "flare_lat", "Latitude", "Lat"],
    "lon": ["longitude", "lon", "flare_lon", "Longitude", "Lon"],
    "id": ["id_key", "flare_id", "id", "catalog_id", "ID"],
    "bcm": ["bcm", "bcm_2021", "bcm_2022", "bcm_2023", "flared_volume_bcm",
            "Flared volume (bcm)", "avg_bcm"],
    "temp": ["avg_temp_k", "temp_k", "avg_temp", "Temperature (K)"],
    "detections": ["clear_obs", "detection_freq", "n_detections", "count"],
    "rh": ["rh", "avg_rh_mw", "radiant_heat", "rhi"],
    "type": ["type", "flare_type", "industry", "Sector"],
    "country": ["country", "iso", "Country", "cnty"],
}


def _pick(rec: dict, key: str):
    for alias in COLUMN_ALIASES[key]:
        if alias in rec and rec[alias] not in (None, ""):
            return rec[alias]
    return None


def _existing_file(raw_dir: Path) -> Path | None:
    for name in CANDIDATE_FILES:
        p = Path(raw_dir) / name
        if p.exists():
            return p
    return None


def fetch(raw_dir: Path, force: bool = False) -> dict:
    raw_dir = Path(raw_dir)

    local = _existing_file(raw_dir)
    if local and not force:
        return {"status": "cached", "path": str(local), "bytes": local.stat().st_size}

    if DEFAULT_URL:
        suffix = ".xlsx" if DEFAULT_URL.lower().endswith((".xlsx", ".xls")) else ".csv"
        result = download(DEFAULT_URL, raw_dir / f"eog_flares{suffix}", timeout=180, force=force)
        if result["status"] in ("ok", "cached"):
            return result
        return {
            "status": "unavailable",
            "error": result.get("error", "download failed"),
            "hint": f"Set SATAT_EOG_URL, or drop a file at {raw_dir}/eog_flares.csv",
        }

    return {
        "status": "unavailable",
        "error": "no local file and SATAT_EOG_URL is not set",
        "hint": (
            "Download the flare inventory from https://eogdata.mines.edu/products/vnf/ "
            f"(free account) and save it as {raw_dir}/eog_flares.csv"
        ),
    }


def _read_records(path: Path):
    import pandas as pd

    if path.suffix.lower() in (".xlsx", ".xls"):
        frame = pd.read_excel(path)
    else:
        frame = pd.read_csv(path)
    return frame.to_dict(orient="records")


def load(raw_dir: Path):
    path = _existing_file(Path(raw_dir))
    if path is None:
        return schema.empty_frame()

    rows = []
    for n, rec in enumerate(_read_records(path)):
        lat, lon = _pick(rec, "lat"), _pick(rec, "lon")
        if lat is None or lon is None:
            continue

        country = _pick(rec, "country")
        if country and str(country).strip().upper() not in ("IND", "INDIA", "IN"):
            # Global inventories are filtered to India here; a file that has
            # already been subset simply has no country column.
            continue

        rows.append({
            "source": SOURCE,
            "source_id": str(_pick(rec, "id") or f"eog-{n}"),
            "name": str(_pick(rec, "type") or "Gas flare"),
            "ftype": "flare",
            "lat": lat,
            "lon": lon,
            "capacity_value": _pick(rec, "bcm"),
            "capacity_unit": "bcm_yr",
            "status": "operating",
            "subnational": "",
            "attrs": {
                "avg_temp_k": _pick(rec, "temp"),
                "detections": _pick(rec, "detections"),
                "radiant_heat_mw": _pick(rec, "rh"),
                "flare_type": _pick(rec, "type"),
            },
        })

    return schema.finalize(rows)
