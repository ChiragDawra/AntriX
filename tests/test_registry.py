"""Registry schema, cross-source matching and the adapters' contract."""

import json

import pandas as pd
import pytest

from sources import ADAPTERS, registry, schema


def test_every_adapter_exposes_the_same_surface():
    for adapter in ADAPTERS:
        assert isinstance(adapter.SOURCE, str)
        assert adapter.LABEL and adapter.SHORT and adapter.LICENSE
        assert callable(adapter.fetch) and callable(adapter.load)


def test_finalize_enforces_schema_and_drops_out_of_country():
    frame = schema.finalize([
        {"source": "test", "source_id": "1", "name": "Inside", "ftype": "steel",
         "lat": 22.0, "lon": 80.0, "attrs": {"a": 1}},
        {"source": "test", "source_id": "2", "name": "Outside", "ftype": "steel",
         "lat": 51.5, "lon": -0.12, "attrs": {}},
    ])

    assert list(frame.columns) == schema.FACILITY_COLUMNS
    assert len(frame) == 1
    assert frame.iloc[0]["name"] == "Inside"
    # attrs must survive as a JSON string, not a dict, so the CSV round-trips.
    assert json.loads(frame.iloc[0]["attrs"]) == {"a": 1}


def test_finalize_on_empty_input():
    frame = schema.finalize([])
    assert frame.empty
    assert list(frame.columns) == schema.FACILITY_COLUMNS


def _facility(source, sid, name, ftype, lat, lon):
    return {"facility_uid": "", "source": source, "source_id": sid, "name": name,
            "ftype": ftype, "lat": lat, "lon": lon, "capacity_value": float("nan"),
            "capacity_unit": "", "status": "operating", "subnational": "", "attrs": "{}"}


def test_colocated_records_from_different_sources_become_one_site():
    frame = pd.DataFrame([
        _facility("wri", "w1", "Vijayanagar Power", "power_plant", 15.170, 76.640),
        _facility("gem", "g1", "Vijayanagar plant", "power_plant", 15.172, 76.642),
        _facility("osm", "o1", "", "industrial_area", 15.171, 76.641),
    ])

    grouped = registry.group_facilities(frame)
    assert grouped["facility_uid"].nunique() == 1

    groups = registry.build_groups(grouped)
    assert groups.iloc[0]["source_agreement"] == 3
    assert set(groups.iloc[0]["sources_present"].split("|")) == {"gem", "osm", "wri"}
    # The specific class wins over OSM's generic industrial_area.
    assert groups.iloc[0]["ftype"] == "power_plant"
    # And the name comes from a curated registry, not from blank OSM tags.
    assert groups.iloc[0]["name"] != ""


def test_distant_facilities_stay_separate():
    frame = pd.DataFrame([
        _facility("gem", "g1", "Plant A", "steel", 22.0, 80.0),
        _facility("gem", "g2", "Plant B", "steel", 23.0, 81.0),
    ])
    grouped = registry.group_facilities(frame)
    assert grouped["facility_uid"].nunique() == 2


def test_incompatible_types_do_not_merge_even_when_colocated():
    frame = pd.DataFrame([
        _facility("gem", "g1", "Steel works", "steel", 22.0000, 80.0000),
        _facility("eog", "e1", "Flare", "flare", 22.0005, 80.0005),
    ])
    grouped = registry.group_facilities(frame)
    assert grouped["facility_uid"].nunique() == 2


def test_name_match_merges_beyond_the_tight_radius():
    """Registries place big plants at the gate, the office or the stack."""
    frame = pd.DataFrame([
        _facility("wri", "w1", "Tata Steel Jamshedpur Works", "steel", 22.800, 86.200),
        _facility("gem", "g1", "Tata Steel Jamshedpur plant", "steel", 22.825, 86.215),
    ])
    grouped = registry.group_facilities(frame)
    assert grouped["facility_uid"].nunique() == 1


def test_built_registry_is_present_and_consistent(root):
    path = root / "data" / "registry"
    if not (path / "facilities.csv").exists():
        pytest.skip("registry not built")

    facilities = pd.read_csv(path / "facilities.csv")
    groups = pd.read_csv(path / "facility_groups.csv")
    manifest = json.loads((path / "registry_manifest.json").read_text())

    assert set(facilities["facility_uid"]) == set(groups["facility_uid"])
    assert groups["source_agreement"].min() >= 1
    assert groups["source_agreement"].max() <= 4
    assert manifest["total_sites"] == len(groups)
    # Every source in the manifest reports a status, including failures.
    for info in manifest["sources"].values():
        assert info["status"] in ("loaded", "unavailable", "partial", "cached", "skipped")
