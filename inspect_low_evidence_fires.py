import pandas as pd

df = pd.read_csv("firms_final.csv")

subset = df[(df["final_label"] == "industrial_fire") & (df["evidence_level"] == "Low")]
print(f"Total Low-evidence industrial_fire rows: {len(subset)}\n")

cols = ["latitude","longitude","frp","ml_thermal_score","thermal_intensity_score",
        "dist_to_industrial_km","facility_proximity_score","recurrence_days",
        "industrial_evidence_score","evidence_level","final_label",
        "nearest_facility_name","nearest_facility_type"]

near = subset[subset["dist_to_industrial_km"] < 1].sort_values("dist_to_industrial_km")
mid = subset[(subset["dist_to_industrial_km"] >= 2) & (subset["dist_to_industrial_km"] < 3)].sort_values("dist_to_industrial_km")
far = subset[(subset["dist_to_industrial_km"] >= 4) & (subset["dist_to_industrial_km"] < 5)].sort_values("dist_to_industrial_km")

print("=== <1 km example ===")
print(near[cols].head(1).to_string(index=False) if len(near) else "None found in this band")
print("\n=== 2-3 km example ===")
print(mid[cols].head(1).to_string(index=False) if len(mid) else "None found in this band")
print("\n=== 4-5 km example ===")
print(far[cols].head(1).to_string(index=False) if len(far) else "None found in this band")