#!/usr/bin/env python3
"""
Runs the full AntriX processing pipeline end-to-end and (by default) launches
the web app at the end.

Assumes you've already fetched the raw data yourself:
    - firms_raw.csv        (python fetch_data_v3.py)
    - osm_industrial.json  (python fetch_osm_v3.py)

Usage:
    python run_pipeline.py            # run pipeline, then start the web app
    python run_pipeline.py --no-serve # run pipeline only, skip starting the app
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "antrix_app"

REQUIRED_INPUTS = ["firms_raw.csv", "osm_industrial.json"]

# Order matters: each step reads columns written by the ones before it.
PIPELINE = [
    "compute_distance.py",          # firms_raw.csv + osm_industrial.json -> firms_with_distance.csv
    "compute_recurrence.py",        # firms_with_distance.csv             -> firms_with_features.csv
    "label_data.py",                # firms_with_features.csv             -> firms_labeled.csv
    "train_model_v2.py",            # firms_labeled.csv                   -> antrix_model_v2.pkl
    "fusion_model_v2.py",           # firms_labeled.csv + model           -> firms_final.csv
    "add_facility_details.py",      # firms_final.csv + osm_industrial.json -> firms_final.csv
    "add_nearest_facility_coords.py",
    "add_risk_score_v2.py",         # -> thermal_abnormality, persistence_norm
    "fix_priority_formula.py",      # -> final risk_score / frp_intensity_norm
    "fix_classification_logic.py",  # -> industrial_context
    "reclassify_v3.py",             # -> final_label / evidence_level (final classification)
    "compute_clusters.py",          # -> firms_final.csv + clusters.csv
]


def run_step(script: str) -> None:
    print(f"\n=== {script} ===")
    result = subprocess.run([sys.executable, script], cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"\nPipeline stopped: {script} exited with code {result.returncode}")


def main() -> None:
    serve = "--no-serve" not in sys.argv

    missing = [f for f in REQUIRED_INPUTS if not (ROOT / f).exists()]
    if missing:
        sys.exit(
            "Missing input file(s): " + ", ".join(missing) +
            "\nFetch them first, e.g.:\n"
            "  python fetch_data_v3.py\n"
            "  python fetch_osm_v3.py"
        )

    for script in PIPELINE:
        run_step(script)

    print("\nPipeline complete: firms_final.csv and clusters.csv are up to date.")

    for f in ("firms_final.csv", "clusters.csv"):
        shutil.copy(ROOT / f, APP_DIR / f)
    print(f"Copied firms_final.csv and clusters.csv into {APP_DIR}/")

    if serve:
        print("\nStarting web app at http://localhost:5000 (Ctrl+C to stop)...")
        subprocess.run([sys.executable, "app.py"], cwd=APP_DIR)
    else:
        print("Skipping app start (--no-serve). Run it with: cd antrix_app && python app.py")


if __name__ == "__main__":
    main()
