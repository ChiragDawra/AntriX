from flask import Flask, render_template, jsonify
import pandas as pd
import json
import os

app = Flask(__name__)

SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), "data_snapshot.json")


def load_snapshot():
    """Provenance for the data this instance is serving (written by run_pipeline.py)."""
    try:
        with open(SNAPSHOT_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"snapshot_id": "unknown", "generated_at": "unknown"}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/detections")
def detections():
    df = pd.read_csv("firms_final.csv")
    df = df.fillna(0)
    cols = ["latitude","longitude","final_label","fusion_score",
            "dist_to_industrial_km","recurrence_days","frp","acq_date",
            "facility_proximity_score","persistence_score","thermal_intensity_score",
            "risk_score","risk_level","thermal_abnormality","persistence_norm",
            "industrial_context","nearest_facility_lat","nearest_facility_lon",
            "frp_intensity_norm","nearest_facility_name","nearest_facility_type",
            "cluster_id","industrial_evidence_score","evidence_level"]
    records = df[cols].to_dict(orient="records")
    return jsonify(records)

@app.route("/api/clusters")
def clusters():
    df = pd.read_csv("clusters.csv")
    return jsonify(df.to_dict(orient="records"))

@app.route("/api/stats")
def stats():
    df = pd.read_csv("firms_final.csv")
    counts = df["final_label"].value_counts().to_dict()
    snapshot = load_snapshot()
    return jsonify({
        "total": len(df),
        "industrial_fire": counts.get("industrial_fire", 0),
        "persistent_industrial_source": counts.get("persistent_industrial_source", 0),
        "insufficient_evidence": counts.get("insufficient_evidence", 0),
        "snapshot_id": snapshot.get("snapshot_id"),
        "generated_at": snapshot.get("generated_at"),
        "date_range": snapshot.get("date_range"),
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=not os.environ.get("PORT"))