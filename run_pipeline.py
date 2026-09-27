#!/usr/bin/env python3
"""Run SATAT end to end.

    python run_pipeline.py                  # everything, then serve
    python run_pipeline.py --no-serve       # everything, no web app
    python run_pipeline.py --skip-fetch     # reuse the FIRMS pull already on disk
    python run_pipeline.py --refresh-registry   # re-download the four registries

Stages:

    1. FIRMS pull            fetch_data_v3.py   -> firms_raw.csv
    2. Cleaning              clean_detections.py-> firms_clean.csv
    3. Facility registry     build_registry.py  -> data/registry/
    4. Analysis              run_analysis.py    -> firms_final.csv, clusters.csv
    5. Evaluation            evaluate.py        -> validation_report.json
    6. Serve                 antrix_app/app.py

Stage 3 is cached: the registries change on a monthly release cycle, not a
daily one, so it only re-downloads when asked.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "antrix_app"


def run(script: str, *args: str) -> None:
    label = " ".join([script, *args])
    print(f"\n{'=' * 64}\n  {label}\n{'=' * 64}")
    result = subprocess.run([sys.executable, script, *args], cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"\nPipeline stopped: {label} exited with code {result.returncode}")


def main() -> None:
    argv = sys.argv[1:]
    serve = "--no-serve" not in argv

    if "--skip-fetch" in argv:
        if not (ROOT / "firms_raw.csv").exists():
            sys.exit("--skip-fetch given but firms_raw.csv does not exist.")
        print("Skipping the FIRMS pull; reusing firms_raw.csv")
    else:
        run("fetch_data_v3.py")

    run("clean_detections.py")

    registry_args = ["--force"] if "--refresh-registry" in argv else []
    if not (ROOT / "data" / "registry" / "facilities.csv").exists():
        print("\nNo facility registry yet -- building it.")
    run("build_registry.py", *registry_args)

    run("run_analysis.py")
    run("evaluate.py")

    print(
        "\nDone. Commit antrix_app/ so a deployed instance serves this same "
        "snapshot -- otherwise local and hosted quietly disagree about how "
        "many detections exist."
    )

    if serve:
        print("\nStarting the dashboard on http://localhost:5000  (Ctrl+C to stop)")
        subprocess.run([sys.executable, "app.py"], cwd=APP_DIR)
    else:
        print("Skipped serving. Start it with: cd antrix_app && python app.py")


if __name__ == "__main__":
    main()
