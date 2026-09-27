"""API contract: filters, exports and graceful behaviour on missing data."""

import csv
import io
import json

import pytest


def test_index_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"SATAT" in response.data


@pytest.mark.parametrize("path", ["/validation", "/data-dictionary", "/api/docs"])
def test_secondary_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_stats_reports_provenance(client):
    data = client.get("/api/stats").get_json()
    for key in ("total", "snapshot_id", "method_version", "build", "date_range"):
        assert key in data
    assert data["total"] > 0


def test_sources_lists_all_four_registries_with_status(client):
    data = client.get("/api/sources").get_json()
    keys = [s["key"] for s in data["sources"]]
    assert keys == ["osm", "wri", "gem", "eog"]
    for source in data["sources"]:
        assert source["status"] in ("loaded", "unavailable", "partial")
        # An unavailable source must explain itself rather than just vanish.
        if source["status"] != "loaded":
            assert source["hint"]


def test_detections_carry_the_evidence_columns(client):
    rows = client.get("/api/detections").get_json()
    assert rows
    required = {
        "detection_id", "final_label", "risk_score", "sources_confirming",
        "sources_loaded", "corroboration_score", "contributions",
        "est_temp_k", "temp_class", "retrieval_status",
    }
    assert required <= set(rows[0])


def test_label_filter(client):
    rows = client.get("/api/detections?label=industrial_fire").get_json()
    assert rows
    assert {r["final_label"] for r in rows} == {"industrial_fire"}


def test_source_filter_keeps_only_corroborated_rows(client):
    rows = client.get("/api/detections?sources=gem").get_json()
    assert rows
    for row in rows:
        assert "gem" in str(row["sources_confirming"]).split("|")


def test_min_score_filter(client):
    rows = client.get("/api/detections?min_score=0.6").get_json()
    assert all(float(r["risk_score"]) >= 0.6 for r in rows)


def test_bbox_filter(client):
    rows = client.get("/api/detections?bbox=80,20,90,28").get_json()
    for row in rows:
        assert 20 <= float(row["latitude"]) <= 28
        assert 80 <= float(row["longitude"]) <= 90


def test_export_csv_matches_the_json_for_the_same_filter(client):
    """An export that disagrees with the screen it came from is a trap."""
    query = "label=industrial_fire&min_score=0.4"
    rows = client.get(f"/api/detections?{query}").get_json()

    response = client.get(f"/api/export/detections.csv?{query}")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]

    parsed = list(csv.DictReader(io.StringIO(response.data.decode())))
    assert len(parsed) == len(rows)
    assert {r["detection_id"] for r in parsed} == {r["detection_id"] for r in rows}


def test_export_csv_carries_every_column_not_just_the_map_ones(client):
    response = client.get("/api/export/detections.csv?min_score=0.7")
    header = response.data.decode().splitlines()[0].split(",")
    assert "method_version" in header
    assert "inter_arrival_regularity" in header
    assert "count_gem_3km" in header


def test_geojson_export_is_valid(client):
    response = client.get("/api/export/detections.geojson?label=industrial_fire")
    payload = json.loads(response.data)
    assert payload["type"] == "FeatureCollection"
    assert payload["features"]
    geometry = payload["features"][0]["geometry"]
    assert geometry["type"] == "Point"
    assert len(geometry["coordinates"]) == 2


def test_single_detection_parses_its_contributions(client):
    first = client.get("/api/detections").get_json()[0]
    detail = client.get(f"/api/detection/{first['detection_id']}").get_json()
    assert isinstance(detail["contributions"], list)
    assert detail["contributions"]
    assert {"label", "contribution", "detail"} <= set(detail["contributions"][0])


def test_unknown_detection_is_a_404_not_a_crash(client):
    assert client.get("/api/detection/doesnotexist").status_code == 404


def test_site_export(client):
    rows = client.get("/api/detections").get_json()
    uid = next((r["facility_uid"] for r in rows if r["facility_uid"]), None)
    if not uid:
        pytest.skip("no facility matches in this snapshot")
    response = client.get(f"/api/export/site/{uid}.csv")
    assert response.status_code == 200
    assert len(response.data.decode().splitlines()) > 1


def test_clusters_and_facilities(client):
    clusters = client.get("/api/clusters").get_json()
    assert clusters and "cluster_id" in clusters[0]
    assert "sources_confirming" in clusters[0]

    facilities = client.get("/api/facilities?source=gem&limit=5").get_json()
    assert len(facilities) <= 5
    for site in facilities:
        assert "gem" in str(site["sources_present"]).split("|")
