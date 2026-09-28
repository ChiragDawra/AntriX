"""Global Energy Monitor trackers.

Three GEM trackers matter for industrial thermal activity in India:

    Global Coal Plant Tracker        1977 units   (coal combustion)
    Global Oil & Gas Plant Tracker    115 units   (gas/oil combustion)
    Global Steel Plant Tracker        180 plants  (blast furnaces, EAF, DRI,
                                                   coking and sinter plants)

GEM distributes these under CC BY 4.0. The canonical downloads sit behind a
registration form, so the adapter pulls the archived Zenodo copies, which are
the same workbooks with a citable DOI.
"""

from __future__ import annotations

from pathlib import Path

from sources import schema
from sources._http import download

SOURCE = "gem"
LABEL = "Global Energy Monitor"
SHORT = "GEM"
LICENSE = "CC BY 4.0 - Global Energy Monitor"
HOMEPAGE = "https://globalenergymonitor.org/projects/"

# (filename, zenodo url, sheet, ftype)
TRACKERS = [
    (
        "gem_coal_plant_tracker.xlsx",
        "https://zenodo.org/records/20843067/files/GEM_GCPT.xlsx?download=1",
        "Units",
        "power_plant",
    ),
    (
        "gem_oil_gas_plant_tracker.xlsx",
        "https://zenodo.org/records/20843067/files/GEM_GOGPT.xlsx?download=1",
        "Gas & Oil Units",
        "power_plant",
    ),
    (
        "gem_steel_plant_tracker.xlsx",
        "https://zenodo.org/records/16893375/files/"
        "Global-Steel-Plant-Tracker-April-2024-Standard-Copy-V1.xlsx?download=1",
        "Steel Plants",
        "steel",
    ),
]

# GEM status vocabulary is per-tracker and fine-grained; collapse it to the
# four states the dashboard actually filters on.
_STATUS = {
    "operating": "operating",
    "operating pre-retirement": "operating",
    "construction": "construction",
    "permitted": "announced",
    "pre-permit": "announced",
    "announced": "announced",
    "proposed": "announced",
    "shelved": "announced",
    "mothballed": "retired",
    "retired": "retired",
    "cancelled": "cancelled",
}


def fetch(raw_dir: Path, force: bool = False) -> dict:
    raw_dir = Path(raw_dir)
    results = {}
    for filename, url, _sheet, _ftype in TRACKERS:
        results[filename] = download(url, raw_dir / filename, timeout=180, force=force)

    ok = [f for f, r in results.items() if r["status"] in ("ok", "cached")]
    status = "ok" if len(ok) == len(TRACKERS) else ("partial" if ok else "unavailable")
    return {"status": status, "parts": results, "loaded": len(ok), "expected": len(TRACKERS)}


def _sheet_rows(path: Path, sheet: str):
    """Yield dict rows from one worksheet, keyed by its header row."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        return
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(it)]
    for row in it:
        yield dict(zip(header, row))


def _first(rec: dict, *keys, default=None):
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return default


def _split_coordinates(value):
    """Steel tracker stores one 'lat, lon' string instead of two columns."""
    if not value:
        return None, None
    parts = str(value).split(",")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None, None


def load(raw_dir: Path):
    raw_dir = Path(raw_dir)
    rows = []

    for filename, _url, sheet, ftype in TRACKERS:
        path = raw_dir / filename
        if not path.exists():
            continue

        for rec in _sheet_rows(path, sheet):
            country = _first(rec, "Country/Area", "Country", default="")
            if str(country).strip() != "India":
                continue

            lat = _first(rec, "Latitude")
            lon = _first(rec, "Longitude")
            if lat is None:
                lat, lon = _split_coordinates(_first(rec, "Coordinates"))

            raw_status = str(
                _first(rec, "Status", "Capacity operating status", default="unknown")
            ).strip().lower()

            name = _first(
                rec, "Plant name", "Plant name (English)", "Unit name", default=""
            )
            unit = _first(rec, "Unit name", default="")

            capacity = _first(
                rec,
                "Capacity (MW)",
                "Nominal crude steel capacity (ttpa)",
                "Nominal iron capacity (ttpa)",
            )
            unit_label = "MW" if "Capacity (MW)" in rec and rec.get("Capacity (MW)") else "ttpa"

            source_id = str(
                _first(rec, "GEM unit ID", "GEM unit/phase ID", "Plant ID",
                       "GEM location ID", default=f"{filename}:{name}:{unit}")
            )

            attrs = {
                "tracker": filename.replace("gem_", "").replace(".xlsx", ""),
                "unit": str(unit or ""),
                "owner": str(_first(rec, "Owner", "Owner(s)", default="") or ""),
                "parent": str(_first(rec, "Parent", "Parent(s)", default="") or ""),
                "start_year": _first(rec, "Start year", "Start date", default=""),
                "raw_status": raw_status,
            }
            if ftype == "steel":
                attrs["bf_capacity_ttpa"] = _first(rec, "Nominal BF capacity (ttpa)", default="")
                attrs["dri_capacity_ttpa"] = _first(rec, "Nominal DRI capacity (ttpa)", default="")
                attrs["coking_capacity_ttpa"] = _first(rec, "Coking plant capacity (ttpa)", default="")
                attrs["sinter_capacity_ttpa"] = _first(rec, "Sinter plant capacity (ttpa)", default="")
            else:
                attrs["fuel"] = str(_first(rec, "Fuel", "Coal type", default="") or "")
                attrs["technology"] = str(
                    _first(rec, "Combustion technology", "Turbine/Engine Technology", default="") or ""
                )
                attrs["annual_co2_mt"] = _first(rec, "Annual CO2 (million tonnes / annum)", default="")

            rows.append({
                "source": SOURCE,
                "source_id": source_id,
                "name": str(name or ""),
                "ftype": ftype,
                "lat": lat,
                "lon": lon,
                "capacity_value": capacity,
                "capacity_unit": unit_label,
                "status": _STATUS.get(raw_status, "unknown"),
                "subnational": str(
                    _first(rec, "Subnational unit (province, state)",
                           "Subnational unit (province/state)", "State/Province",
                           default="") or ""
                ),
                "attrs": attrs,
            })

    return schema.finalize(rows)
