"""Build one cross-referenced facility registry out of the four adapters.

Two artefacts come out of here:

``facilities.csv``       every source record, tagged with the facility group it
                         belongs to
``facility_groups.csv``  one row per real-world site, carrying which registries
                         see it (``sources_present``) and how many
                         (``source_agreement``)

The grouping is the point. A coordinate that OSM, WRI and GEM all place a
thermal plant at is a different quality of evidence from one only OSM's
``landuse=industrial`` polygon covers, and the classifier downstream is allowed
to say so.
"""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from sources import ADAPTERS, schema

EARTH_RADIUS_KM = 6371.0088

# Two records are the same site if they sit within this radius and their
# classes are compatible. 1.5 km is roughly the footprint of a large integrated
# steel works, and comfortably inside VIIRS's 375 m pixel neighbourhood.
MATCH_RADIUS_KM = 1.5
# A looser radius is allowed when the names clearly agree, because registries
# place large plants at their office, their gate or their stack.
NAME_MATCH_RADIUS_KM = 5.0
NAME_SIMILARITY = 0.82

# Which classes may be merged with which. Everything merges with the generic
# OSM classes; the specific ones only merge with themselves.
_COMPATIBLE = {
    "industrial_area": set(schema.FTYPES),
    "works": set(schema.FTYPES),
    "other": set(schema.FTYPES),
}

_NAME_NOISE = re.compile(
    r"\b(power|thermal|plant|station|ltd|limited|pvt|private|company|co|corp|"
    r"corporation|the|of|india|indian|unit|phase|works|steel|refinery|project)\b"
)


def _normalize_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", str(name).lower())
    n = _NAME_NOISE.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def _compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    return b in _COMPATIBLE.get(a, set()) or a in _COMPATIBLE.get(b, set())


class _Union:
    """Plain union-find; the registry is small enough that nothing fancier pays."""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[max(ri, rj)] = min(ri, rj)


def group_facilities(df: pd.DataFrame) -> pd.DataFrame:
    """Assign a ``facility_uid`` shared by every record describing one site."""
    if df.empty:
        df = df.copy()
        df["facility_uid"] = []
        return df

    from sklearn.neighbors import BallTree

    df = df.reset_index(drop=True).copy()
    coords = np.radians(df[["lat", "lon"]].to_numpy(dtype=float))
    tree = BallTree(coords, metric="haversine")

    names = [_normalize_name(n) for n in df["name"]]
    ftypes = df["ftype"].tolist()

    union = _Union(len(df))
    neighbours = tree.query_radius(coords, r=NAME_MATCH_RADIUS_KM / EARTH_RADIUS_KM)

    for i, idxs in enumerate(neighbours):
        for j in idxs:
            if j <= i:
                continue
            if not _compatible(ftypes[i], ftypes[j]):
                continue

            dist_km = _haversine_km(
                df.at[i, "lat"], df.at[i, "lon"], df.at[j, "lat"], df.at[j, "lon"]
            )

            if dist_km <= MATCH_RADIUS_KM:
                union.union(i, j)
                continue

            # Beyond the tight radius, only a strong name match merges.
            if names[i] and names[j]:
                if difflib.SequenceMatcher(None, names[i], names[j]).ratio() >= NAME_SIMILARITY:
                    union.union(i, j)

    roots = [union.find(i) for i in range(len(df))]
    order = {root: n for n, root in enumerate(sorted(set(roots)))}
    df["facility_uid"] = [f"F{order[r]:05d}" for r in roots]
    return df


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


# Which class wins when several registries disagree about what a site is.
_FTYPE_RANK = {
    "flare": 0, "refinery": 1, "steel": 2, "smelter": 3, "cement": 4,
    "power_plant": 5, "works": 6, "industrial_area": 7, "other": 8,
}


def build_groups(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse grouped source records into one row per real-world site."""
    if df.empty:
        return pd.DataFrame(columns=[
            "facility_uid", "name", "ftype", "lat", "lon", "sources_present",
            "source_agreement", "status", "capacity_value", "capacity_unit",
            "subnational", "record_count",
        ])

    out = []
    for uid, grp in df.groupby("facility_uid", sort=True):
        sources = sorted(set(grp["source"]))

        # Prefer the most specific class, and a name from a curated registry
        # over OSM's free-text tagging.
        ftype = min(grp["ftype"], key=lambda f: _FTYPE_RANK.get(f, 9))
        named = grp[grp["name"].str.strip() != ""]
        curated = named[named["source"] != "osm"]
        pick = curated if not curated.empty else named
        name = pick.iloc[0]["name"] if not pick.empty else ""

        operating = grp[grp["status"] == "operating"]
        status = "operating" if not operating.empty else grp.iloc[0]["status"]

        mw = grp[grp["capacity_unit"] == "MW"]["capacity_value"].dropna()
        ttpa = grp[grp["capacity_unit"] == "ttpa"]["capacity_value"].dropna()
        if not mw.empty:
            cap_value, cap_unit = float(mw.sum()), "MW"
        elif not ttpa.empty:
            cap_value, cap_unit = float(ttpa.max()), "ttpa"
        else:
            cap_value, cap_unit = float("nan"), ""

        subnational = next(
            (s for s in grp["subnational"] if str(s).strip()), ""
        )

        out.append({
            "facility_uid": uid,
            "name": name,
            "ftype": ftype,
            "lat": float(grp["lat"].mean()),
            "lon": float(grp["lon"].mean()),
            "sources_present": "|".join(sources),
            "source_agreement": len(sources),
            "status": status,
            "capacity_value": cap_value,
            "capacity_unit": cap_unit,
            "subnational": subnational,
            "record_count": int(len(grp)),
        })

    return pd.DataFrame(out)


def build(raw_dir: Path, out_dir: Path, fetch: bool = True, force: bool = False) -> dict:
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sources": {},
    }

    frames = []
    for adapter in ADAPTERS:
        fetch_result = adapter.fetch(raw_dir, force=force) if fetch else {"status": "skipped"}
        frame = adapter.load(raw_dir)
        frames.append(frame)

        manifest["sources"][adapter.SOURCE] = {
            "label": adapter.LABEL,
            "short": adapter.SHORT,
            "license": adapter.LICENSE,
            "homepage": adapter.HOMEPAGE,
            "fetch": fetch_result,
            "records": int(len(frame)),
            "status": "loaded" if len(frame) else fetch_result.get("status", "unavailable"),
            "by_type": frame["ftype"].value_counts().to_dict() if len(frame) else {},
            "hint": fetch_result.get("hint", ""),
        }

    combined = pd.concat(frames, ignore_index=True) if frames else schema.empty_frame()
    combined = group_facilities(combined)
    groups = build_groups(combined)

    combined.to_csv(out_dir / "facilities.csv", index=False)
    groups.to_csv(out_dir / "facility_groups.csv", index=False)

    manifest["total_records"] = int(len(combined))
    manifest["total_sites"] = int(len(groups))
    manifest["multi_source_sites"] = int((groups["source_agreement"] > 1).sum()) if len(groups) else 0
    (out_dir / "registry_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

    return manifest
