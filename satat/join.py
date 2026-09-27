"""Join detections to the four-source facility registry.

The single most important change from the earlier build: "distance to the
nearest industrial thing" is no longer one number from one source. Each
registry is queried separately, so the evidence panel can say *which*
registries see infrastructure at a location, and the classifier can weigh a
site that three independent registries agree on differently from a lone OSM
polygon someone drew round a warehouse.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from satat import config
from satat.geo import NearestFacility

SOURCE_ORDER = ["osm", "wri", "gem", "eog"]


def load_registry(registry_dir: Path):
    registry_dir = Path(registry_dir)
    facilities = pd.read_csv(registry_dir / "facilities.csv")
    groups = pd.read_csv(registry_dir / "facility_groups.csv")
    manifest_path = registry_dir / "registry_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    return facilities, groups, manifest


def add_registry_features(df: pd.DataFrame, registry_dir: Path,
                          only_sources: list[str] | None = None) -> pd.DataFrame:
    """Attach per-registry distances and the corroboration score.

    ``only_sources`` restricts the join to a subset of registries. That is what
    the ablation in ``evaluate.py`` uses to answer "what does adding GEM
    actually buy us?" with a number instead of an assertion.
    """
    facilities, groups, manifest = load_registry(registry_dir)
    df = df.copy()

    if only_sources is not None:
        keep = set(only_sources)
        facilities = facilities[facilities["source"].isin(keep)]
        kept_uids = set(facilities["facility_uid"])
        groups = groups[groups["facility_uid"].isin(kept_uids)].reset_index(drop=True)

    lats = df["latitude"].to_numpy(dtype=float)
    lons = df["longitude"].to_numpy(dtype=float)

    loaded_sources = []
    per_source_dist = {}

    for source in SOURCE_ORDER:
        if only_sources is not None and source not in set(only_sources):
            df[f"dist_{source}_km"] = np.nan
            df[f"count_{source}_3km"] = 0
            continue
        subset = facilities[facilities["source"] == source]
        index = NearestFacility(subset["lat"], subset["lon"])
        dist, _ = index.query(lats, lons)

        df[f"dist_{source}_km"] = np.where(np.isfinite(dist), np.round(dist, 3), np.nan)
        df[f"count_{source}_3km"] = index.count_within(lats, lons, config.CORROBORATION_RADIUS_KM)

        if not index.empty:
            loaded_sources.append(source)
            per_source_dist[source] = dist

    # Corroboration: a source votes fully when the detection is effectively on
    # site, partially when it is within the wider radius. Normalising by the
    # number of *loaded* sources means an unavailable registry lowers nobody's
    # score -- it simply does not vote.
    votes = np.zeros(len(df))
    confirming = [[] for _ in range(len(df))]

    for source in loaded_sources:
        dist = per_source_dist[source]
        onsite = dist <= config.ONSITE_RADIUS_KM
        near = (dist <= config.CORROBORATION_RADIUS_KM) & ~onsite
        votes += np.where(onsite, 1.0, np.where(near, 0.6, 0.0))
        for i in np.flatnonzero(dist <= config.CORROBORATION_RADIUS_KM):
            confirming[i].append(source)

    df["sources_loaded"] = "|".join(loaded_sources)
    df["sources_confirming"] = ["|".join(c) for c in confirming]
    df["sources_confirming_count"] = [len(c) for c in confirming]
    df["corroboration_score"] = (
        votes / max(len(loaded_sources), 1)
    ).clip(0, 1).round(4)

    # Nearest *site* (a facility group, not a single source record) supplies
    # the human-readable identity shown in the evidence panel.
    site_index = NearestFacility(groups["lat"], groups["lon"])
    site_dist, site_idx = site_index.query(lats, lons)
    have_site = site_idx >= 0

    if groups.empty:
        # An ablation run can legitimately have no sites at all (a registry
        # that did not load). Everything downstream must still get its
        # columns, filled with "no match" rather than crashing.
        picked = pd.DataFrame({
            col: [None] * len(df) for col in
            ("facility_uid", "name", "ftype", "lat", "lon", "sources_present",
             "source_agreement", "status", "capacity_value", "capacity_unit",
             "subnational")
        })
    else:
        picked = groups.iloc[np.where(have_site, site_idx, 0)].reset_index(drop=True)

    df["dist_to_industrial_km"] = np.round(site_dist, 3)
    df["facility_uid"] = np.where(have_site, picked["facility_uid"], "")
    df["nearest_facility_name"] = np.where(
        have_site & picked["name"].astype(str).str.strip().ne(""),
        picked["name"], "Unnamed industrial feature",
    )
    df["nearest_facility_type"] = np.where(have_site, picked["ftype"], "")
    df["nearest_facility_lat"] = np.where(have_site, picked["lat"], np.nan)
    df["nearest_facility_lon"] = np.where(have_site, picked["lon"], np.nan)
    df["facility_sources"] = np.where(have_site, picked["sources_present"], "")
    df["facility_source_agreement"] = np.where(have_site, picked["source_agreement"], 0)
    df["facility_status"] = np.where(have_site, picked["status"], "")
    df["facility_capacity_value"] = np.where(have_site, picked["capacity_value"], np.nan)
    df["facility_capacity_unit"] = np.where(have_site, picked["capacity_unit"], "")
    df["facility_subnational"] = np.where(have_site, picked["subnational"], "")

    df["industrial_context"] = np.select(
        [df["dist_to_industrial_km"] <= config.ONSITE_RADIUS_KM,
         df["dist_to_industrial_km"] <= config.CORROBORATION_RADIUS_KM,
         df["dist_to_industrial_km"] <= 10],
        ["On a registered industrial site",
         "Within the site's immediate surroundings",
         "Near industrial activity"],
        default="No registered industrial site nearby",
    )

    df["registry_sites"] = len(groups)
    return df, manifest
