"""What every emitted column means.

Kept as data rather than prose so the same definitions serve the
/data-dictionary page, the CSV export documentation and anyone reading the
source.
"""

COLUMNS = [
    ("Identity", [
        ("detection_id", "Stable 12-character id: MD5 of coordinates, date and acquisition time. The same pixel on the same day keeps the same id across pipeline runs."),
        ("latitude, longitude", "Centre of the satellite pixel, WGS84 decimal degrees."),
        ("acq_date, acq_time", "Acquisition date and UTC time (HHMM) reported by FIRMS."),
        ("daynight", "D or N — whether the overpass was in daylight or darkness."),
        ("satellite, instrument, source_sensor", "Which platform saw it: VIIRS on SNPP / NOAA-20 / NOAA-21, or MODIS."),
        ("confidence", "FIRMS confidence. VIIRS reports l/n/h; MODIS reports 0-100."),
        ("scan, track", "Pixel footprint in km along-scan and along-track. Used to convert the retrieved hot fraction into an area."),
        ("grid_lat, grid_lon", "Coordinates rounded to 2 decimals (~1.1 km). The cell used for recurrence, baselines and dedup."),
    ]),
    ("Radiometry", [
        ("frp", "Fire Radiative Power in megawatts, as reported by FIRMS."),
        ("bright_ti4, bright_ti5", "VIIRS I-band brightness temperatures (K) at 3.74 um and 11.45 um."),
        ("brightness, bright_t31", "MODIS equivalents at 3.96 um and 11.03 um."),
    ]),
    ("Sub-pixel physics", [
        ("est_temp_k", "Retrieved fire temperature (K) from the bi-spectral Dozier solve. Empty when the observation does not constrain it — see retrieval_status."),
        ("hot_fraction", "Fraction of the pixel occupied by the hot component."),
        ("est_area_m2", "Hot area in square metres: hot_fraction times the pixel footprint."),
        ("pixel_area_m2", "Footprint of the satellite pixel itself."),
        ("temp_class", "flare_like (>=1400 K), furnace_like (>=1100 K), mixed (>=800 K), biomass_like (>=500 K), smouldering (<500 K), or unknown."),
        ("retrieval_status", "ok, weak_11um (11 um channel shows no excess, temperature unconstrained), below_background, no_bracket, unconstrained, saturated_lower_bound, or no_data."),
        ("i4_saturated, temp_is_lower_bound", "True when VIIRS I4 hit its 367 K ceiling, in which case the retrieved temperature is a floor, not an estimate."),
    ]),
    ("Baseline and abnormality", [
        ("baseline_frp", "Median FRP of the comparison group this detection is measured against."),
        ("baseline_level", "Which group that was: cell (~1.1 km), region (~11 km) or scene. The tightest group with at least four samples wins."),
        ("frp_robust_z", "(FRP - median) / (1.4826 x MAD) against that baseline. Robust to the single outlier that would distort a mean."),
        ("thermal_abnormality", "frp_robust_z rescaled to 0-1, saturating at 3 sigma."),
        ("frp_intensity_norm", "Percentile rank of this FRP among all detections in the snapshot."),
    ]),
    ("Temporal behaviour", [
        ("recurrence_days", "Distinct days this grid cell was detected during the window."),
        ("detections_in_cell", "Total detections in the cell, across all overpasses."),
        ("night_fraction", "Share of this cell's detections that were at night. Industry runs after dark; agricultural burning largely does not."),
        ("duty_cycle", "Share of the observation window on which the cell was alight."),
        ("inter_arrival_regularity", "1.0 for evenly spaced returns, 0.0 for erratic. Empty with fewer than three visits."),
        ("frp_shift", "Normalised size of the largest step change in the cell's daily mean FRP — a cheap change-point statistic."),
        ("persistence_norm, nocturnal_score", "recurrence_days and night_fraction rescaled to 0-1 for scoring."),
        ("new_source, ceased, reactivated", "Lifecycle flags: first seen in the last two days; active early then dark; or active across a span with a gap in it."),
        ("active_span_days, observation_window_days", "First-to-last-detection span, and the length of the window being analysed."),
    ]),
    ("Facility registry", [
        ("dist_to_industrial_km", "Distance to the nearest registered site, in km, across all four registries."),
        ("dist_osm_km, dist_wri_km, dist_gem_km, dist_eog_km", "Distance to the nearest facility in each registry separately. Empty when that registry is not loaded."),
        ("count_osm_3km, count_wri_3km, count_gem_3km, count_eog_3km", "How many facilities from each registry sit within 3 km."),
        ("sources_loaded", "Which registries were available for this run."),
        ("sources_confirming, sources_confirming_count", "Which registries place infrastructure within 3 km of this detection, and how many."),
        ("corroboration_score", "0-1. Each loaded registry votes 1.0 within 1 km, 0.6 within 3 km, 0 beyond, normalised by the number of loaded registries."),
        ("facility_uid", "Id of the cross-source facility group — one id per real-world site, however many registries list it."),
        ("nearest_facility_name, nearest_facility_type", "Identity of that site. Names prefer a curated registry over OSM free-text."),
        ("nearest_facility_lat, nearest_facility_lon", "Coordinates of the matched site."),
        ("facility_sources, facility_source_agreement", "Which registries list this site, and how many."),
        ("facility_status", "operating, construction, announced, retired or unknown, as the registries report it."),
        ("facility_capacity_value, facility_capacity_unit", "Plant capacity — MW for power, ttpa for steel."),
        ("industrial_context", "Plain-language reading of the distance."),
    ]),
    ("Seasonal context", [
        ("agri_season_context", "True inside a crop-residue burning belt during its burning months."),
        ("agri_season_region", "Which belt and season matched."),
        ("agri_penalty_applied", "True when the seasonal correction reduced the evidence score: in-season, biomass-like temperature, and nothing in the registries."),
    ]),
    ("Scores", [
        ("corroboration_component, physics_score, persistence_component, nocturnal_component, intensity_component", "The five inputs to the evidence score, each 0-1."),
        ("evidence_score", "Weighted sum of those five — the interpretable score. Weights live in satat/config.py."),
        ("ml_industrial_prob", "Calibrated RandomForest probability, trained only on rows the registries and calendar are unambiguous about."),
        ("unsupervised_anomaly", "IsolationForest and LOF, rank-averaged. Owes nothing to the labels."),
        ("anomaly_probability / fusion_score", "0.55 evidence + 0.30 model + 0.15 unsupervised, renormalised if a component is unavailable."),
        ("risk_score", "Investigation priority: a different question from 'is this industrial'. Weights anomaly probability, abnormality, persistence and intensity, with a bonus for newly appeared sources."),
        ("risk_level", "Critical / High / Moderate / Low banding of risk_score."),
    ]),
    ("Classification", [
        ("final_label", "persistent_industrial_source, industrial_fire, flare_signature, agricultural_burning or insufficient_evidence."),
        ("final_label_display", "The same, formatted for display."),
        ("evidence_level", "High / Moderate / Low banding of evidence_score. Empty for insufficient_evidence."),
        ("contributions", "JSON array of the signed contribution each component made to this row's score, with a human-readable detail string."),
        ("method_version", "Version of the analysis that produced the row."),
        ("cluster_id", "Spatio-temporal cluster this detection belongs to; empty for singletons."),
    ]),
]
