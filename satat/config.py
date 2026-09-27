"""Every threshold the analysis depends on, in one place.

Tuning constants scattered through a pipeline are how a project stops being
reproducible. If a number decides an outcome, it lives here with the reason it
has the value it has.
"""

# ---------------------------------------------------------------- geometry
# ~1.1 km at Indian latitudes: the cell size used for recurrence, baselines
# and cross-sensor dedup, so all three agree on "the same place".
GRID_DECIMALS = 2

# A detection is corroborated by a registry if that registry places a facility
# within this radius. 375 m VIIRS pixels plus registry coordinate error (GEM
# and WRI both publish "approximate" locations) make anything tighter false
# precision.
CORROBORATION_RADIUS_KM = 3.0
# Inside this radius the detection is effectively on the site.
ONSITE_RADIUS_KM = 1.0

# ---------------------------------------------------------------- physics
# Channel centres, micrometres.
VIIRS_I4_UM = 3.74
VIIRS_I5_UM = 11.45
MODIS_B21_UM = 3.96
MODIS_B31_UM = 11.03

# VIIRS I4 saturates here; above it the retrieved temperature is a lower bound.
VIIRS_I4_SATURATION_K = 367.0

# Sub-pixel temperature classes. Gas flares burn ~1600-2000 K, steel and
# cement furnaces ~1200-1700 K, open biomass burning ~600-900 K. These bands
# are what let SATAT separate a flare from a stubble fire on physics rather
# than on how close the nearest factory happens to be.
TEMP_CLASS_BANDS = [
    (1400.0, "flare_like"),
    (1100.0, "furnace_like"),
    (800.0, "mixed"),
    (500.0, "biomass_like"),
    (0.0, "smouldering"),
]

# The lower end is deliberately below flaming combustion: a retrieval that
# lands near 450 K describes a large, cool, smouldering area (a landfill face,
# a burnt field still glowing), which is a real and useful answer -- and a
# very different one from a 1600 K flare.
SOLVE_TEMP_RANGE_K = (400.0, 2500.0)

# ---------------------------------------------------------------- temporal
# FIRMS is pulled over a 5-day window; persistence normalises against it.
OBSERVATION_WINDOW_DAYS = 5

# Industrial sources run at night as readily as by day. Agricultural and
# wildfire burning is overwhelmingly a daytime activity, so a high night
# fraction is industrial evidence in its own right.
NIGHT_FRACTION_STRONG = 0.6

# ---------------------------------------------------------------- context
# Crop-residue burning: state-level boxes and the months they burn in. During
# these windows a thermal detection in these boxes is presumed agricultural
# unless the physics and the registries say otherwise.
AGRI_BURN_REGIONS = [
    # name, lat_min, lon_min, lat_max, lon_max, months
    ("punjab_haryana_rabi", 29.0, 73.8, 32.6, 76.9, {4, 5}),
    ("punjab_haryana_kharif", 29.0, 73.8, 32.6, 76.9, {10, 11}),
    ("indo_gangetic_up", 25.0, 77.0, 29.5, 84.0, {10, 11, 4, 5}),
    ("central_india_kharif", 18.0, 74.0, 24.0, 84.0, {10, 11}),
]

# ---------------------------------------------------------------- scoring
# Weights for the interpretable evidence score. They sum to 1.0 and are stated
# here rather than buried in a formula so a reviewer can argue with them.
EVIDENCE_WEIGHTS = {
    "corroboration": 0.30,   # how many independent registries place infrastructure here
    "physics": 0.25,         # sub-pixel temperature consistent with industrial combustion
    "persistence": 0.20,     # returns across days
    "nocturnal": 0.10,       # burns at night
    "intensity": 0.15,       # FRP relative to the scene
}

CLASS_THRESHOLDS = {
    "persistent_industrial_source": 0.62,
    "industrial_fire": 0.42,
}

RISK_LEVELS = [(0.75, "Critical"), (0.55, "High"), (0.35, "Moderate"), (0.0, "Low")]
