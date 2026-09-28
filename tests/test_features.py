"""Feature maths: baselines, timing, seasonal context and score fusion."""

import numpy as np
import pandas as pd
import pytest

from satat import anomaly, baseline, classify, config, context, temporal


def frame(rows):
    df = pd.DataFrame(rows)
    df["grid_lat"] = df["latitude"].round(config.GRID_DECIMALS)
    df["grid_lon"] = df["longitude"].round(config.GRID_DECIMALS)
    return df


def test_robust_baseline_flags_the_outlier_not_the_crowd():
    """The old mean-ratio baseline scored a lone spike as normal.

    Five quiet detections and one large one in the same cell: the spike must
    come out abnormal, and the quiet ones must not.
    """
    rows = [{"latitude": 22.0, "longitude": 80.0, "frp": v}
            for v in (2.0, 2.1, 1.9, 2.0, 2.2, 40.0)]
    result = baseline.add_robust_baseline(frame(rows))

    assert result["thermal_abnormality"].iloc[-1] == pytest.approx(1.0)
    assert (result["thermal_abnormality"].iloc[:-1] < 0.2).all()
    assert result["baseline_level"].iloc[0] == "cell"


def test_baseline_falls_back_when_a_cell_is_too_thin():
    rows = [{"latitude": 22.0 + i * 0.01, "longitude": 80.0, "frp": 3.0 + i}
            for i in range(6)]
    result = baseline.add_robust_baseline(frame(rows))
    # Each cell holds one detection, so none can use a cell-level baseline.
    assert set(result["baseline_level"]) <= {"region", "scene"}


def test_identical_values_do_not_divide_by_zero():
    rows = [{"latitude": 22.0, "longitude": 80.0, "frp": 5.0} for _ in range(6)]
    result = baseline.add_robust_baseline(frame(rows))
    assert result["frp_robust_z"].notna().all()
    assert np.isfinite(result["frp_robust_z"]).all()


def _cell(day, dn="N", frp=3.0, lat=22.0, lon=80.0):
    return {"latitude": lat, "longitude": lon, "frp": frp, "daynight": dn,
            "acq_date": f"2026-08-{20 + day:02d}"}


def test_temporal_features_describe_a_continuous_night_source():
    rows = [_cell(d) for d in range(5)]
    result = temporal.add_temporal_features(pd.DataFrame(rows))

    assert result["recurrence_days"].iloc[0] == 5
    assert result["night_fraction"].iloc[0] == 1.0
    assert result["duty_cycle"].iloc[0] == pytest.approx(1.0)
    assert result["inter_arrival_regularity"].iloc[0] == pytest.approx(1.0)


def test_single_daytime_detection_looks_nothing_like_a_source():
    rows = [_cell(0, dn="D"), _cell(3, dn="D", lat=25.0)]
    result = temporal.add_temporal_features(pd.DataFrame(rows))
    assert (result["recurrence_days"] == 1).all()
    assert (result["night_fraction"] == 0.0).all()
    assert result["inter_arrival_regularity"].isna().all()


def test_new_source_flag_fires_only_at_the_end_of_the_window():
    rows = [_cell(0), _cell(1), _cell(4, lat=25.0)]
    result = temporal.add_temporal_features(pd.DataFrame(rows))
    late = result[result["latitude"] == 25.0].iloc[0]
    early = result[result["latitude"] == 22.0].iloc[0]
    assert bool(late["new_source"]) is True
    assert bool(early["new_source"]) is False
    assert bool(early["ceased"]) is True


def test_agricultural_context_is_region_and_season_bound():
    rows = pd.DataFrame([
        # Punjab in November: in season.
        {"latitude": 30.5, "longitude": 75.5, "acq_date": "2026-11-05"},
        # Punjab in August: out of season.
        {"latitude": 30.5, "longitude": 75.5, "acq_date": "2026-08-05"},
        # Jharkhand in November: out of region.
        {"latitude": 23.5, "longitude": 86.0, "acq_date": "2026-11-05"},
    ])
    result = context.agricultural_context(rows)
    assert list(result["agri_season_context"]) == [True, False, False]
    assert result["agri_season_region"].iloc[0] == "punjab_haryana_kharif"


def test_evidence_weights_sum_to_one():
    assert sum(config.EVIDENCE_WEIGHTS.values()) == pytest.approx(1.0)


def _scored(**overrides):
    row = {
        "est_temp_k": 1500.0, "temp_class": "flare_like",
        "corroboration_score": 0.8, "persistence_norm": 0.8,
        "nocturnal_score": 0.9, "frp_intensity_norm": 0.7,
        "agri_season_context": False, "agri_season_region": "",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_agricultural_penalty_only_applies_when_all_three_conditions_hold():
    in_season_biomass_unconfirmed = anomaly.add_evidence_score(_scored(
        temp_class="biomass_like", est_temp_k=700.0,
        agri_season_context=True, corroboration_score=0.1,
    ))
    assert bool(in_season_biomass_unconfirmed["agri_penalty_applied"].iloc[0]) is True

    # Same season and temperature, but the registries confirm a facility.
    confirmed = anomaly.add_evidence_score(_scored(
        temp_class="biomass_like", est_temp_k=700.0,
        agri_season_context=True, corroboration_score=0.7,
    ))
    assert bool(confirmed["agri_penalty_applied"].iloc[0]) is False


def test_fusion_redistributes_weight_when_a_component_is_missing():
    df = anomaly.add_evidence_score(_scored())
    df["ml_industrial_prob"] = np.nan
    df["unsupervised_anomaly"] = np.nan
    df["thermal_abnormality"] = 0.5
    df["new_source"] = False

    fused = anomaly.fuse(df)
    # With both learned components unavailable the blend is the evidence
    # score alone, not the evidence score diluted toward zero.
    assert fused["anomaly_probability"].iloc[0] == pytest.approx(
        df["evidence_score"].iloc[0], abs=1e-4
    )


def test_classification_requires_registry_support():
    df = anomaly.add_evidence_score(_scored(corroboration_score=0.0))
    df["sources_confirming_count"] = 0
    df["dist_to_industrial_km"] = 50.0
    df["recurrence_days"] = 5
    df["anomaly_probability"] = 0.9
    df["agri_penalty_applied"] = False

    labelled = classify.classify(df)
    # However hot and however persistent: with nothing in any registry there
    # is no industrial claim to make.
    assert labelled["final_label"].iloc[0] == "insufficient_evidence"


def _long_cell(day, lat=22.0):
    date = (pd.Timestamp("2026-06-01") + pd.Timedelta(days=day)).strftime("%Y-%m-%d")
    return {"latitude": lat, "longitude": 80.0, "frp": 3.0, "daynight": "N", "acq_date": date}


def test_persistence_does_not_saturate_over_a_long_window():
    """Over 120 days, five sightings is not the same as being always on."""
    rows = [_long_cell(d) for d in (0, 10, 20, 30, 40)]
    rows += [_long_cell(d, lat=25.0) for d in range(0, 120, 4)]
    result = temporal.add_temporal_features(pd.DataFrame(rows))
    sparse = result[result["latitude"] == 22.0]["persistence_norm"].iloc[0]
    dense = result[result["latitude"] == 25.0]["persistence_norm"].iloc[0]
    assert sparse < 0.5
    assert dense == pytest.approx(1.0)


def test_a_cloudy_week_is_not_a_reactivation_over_months():
    steady = [_long_cell(d) for d in range(0, 120, 3)]          # 2-day gaps
    paused = [_long_cell(d, lat=25.0) for d in list(range(0, 40, 2)) + list(range(80, 120, 2))]
    result = temporal.add_temporal_features(pd.DataFrame(steady + paused))
    assert not bool(result[result["latitude"] == 22.0]["reactivated"].iloc[0])
    assert bool(result[result["latitude"] == 25.0]["reactivated"].iloc[0])


def test_cross_validation_never_splits_a_grid_cell():
    df = pd.DataFrame({
        "latitude": [22.001, 22.002, 22.5, 22.5, 23.0, 23.0, 24.0, 24.0] * 3,
        "longitude": [80.0] * 24,
    })
    groups = anomaly.cell_groups(df)
    y = np.array([1, 1, 0, 0, 1, 1, 0, 0] * 3)
    cv = anomaly.group_folds(y, groups)
    for train, test in cv.split(np.zeros((len(y), 1)), y, groups):
        assert not set(groups[train]) & set(groups[test])
