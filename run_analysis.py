#!/usr/bin/env python3
"""Run the SATAT v3 analysis over cleaned FIRMS detections.

    python run_analysis.py                 # firms_clean.csv -> firms_final.csv + clusters.csv
    python run_analysis.py --input X.csv   # analyse a different cleaned file

Expects the facility registry to exist (python build_registry.py).
"""

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

from satat import cluster, pipeline

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "data" / "registry"
APP_DIR = ROOT / "antrix_app"


def main() -> None:
    args = sys.argv[1:]
    src = Path(args[args.index("--input") + 1]) if "--input" in args else ROOT / "firms_clean.csv"

    if not src.exists():
        sys.exit(f"Missing {src.name}. Run: python clean_detections.py")
    if not (REGISTRY / "facilities.csv").exists():
        sys.exit("Missing facility registry. Run: python build_registry.py")

    detections = pd.read_csv(src)
    print(f"Analysing {len(detections)} cleaned detections with the four-source registry\n")

    df, report = pipeline.run(
        detections, REGISTRY, model_path=ROOT / "satat_model_v3.pkl"
    )
    df, clusters = cluster.add_clusters(df)

    out = pipeline.select_output(df)
    out.to_csv(ROOT / "firms_final.csv", index=False)
    clusters.to_csv(ROOT / "clusters.csv", index=False)

    snapshot = pipeline.write_snapshot(out, ROOT / "data_snapshot.json", report)
    (ROOT / "analysis_report.json").write_text(json.dumps(report, indent=2, default=str))

    print("Registry records used:")
    for source, count in report["registry"].items():
        print(f"  {source:<5} {count:>6}")

    model = report["model"]
    if model.get("trained"):
        print(f"\nModel: cross-validated AUC {model['cv_auc']:.3f} over "
              f"{model['cv_folds']} folds "
              f"({model['n_positive']} positives / {model['n_negative']} negatives)")
    else:
        print(f"\nModel: not trained -- {model.get('reason')}")

    print(f"\nSub-pixel temperature retrieved for "
          f"{report['retrieval_success_rate'] * 100:.1f}% of detections")
    print("Temperature classes:")
    for name, count in report["temp_class_counts"].items():
        print(f"  {name:<16} {count:>5}")

    print("\nClassification:")
    for name, count in report["label_counts"].items():
        print(f"  {name:<32} {count:>5}")

    print(f"\n{report['multi_source_confirmed']} detections confirmed by 2+ registries")
    print(f"{len(clusters)} clusters")

    # Months of detections make firms_final.csv tens of MB; the app ships it
    # gzipped (pandas reads .gz transparently) so the repo and deploy stay small.
    out.to_csv(APP_DIR / "firms_final.csv.gz", index=False, compression="gzip")
    (APP_DIR / "firms_final.csv").unlink(missing_ok=True)
    for f in ("clusters.csv", "data_snapshot.json", "analysis_report.json"):
        shutil.copy(ROOT / f, APP_DIR / f)
    print(f"\nSnapshot {snapshot['snapshot_id']} copied into {APP_DIR.name}/")


if __name__ == "__main__":
    main()
