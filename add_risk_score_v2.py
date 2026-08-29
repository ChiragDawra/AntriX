import pandas as pd

df = pd.read_csv("firms_final.csv")

# Thermal abnormality: how much does this FRP deviate from the baseline
# FRP typically seen at THIS specific grid cell across the observation window
df["grid_lat"] = df["latitude"].round(2)
df["grid_lon"] = df["longitude"].round(2)

baseline = df.groupby(["grid_lat","grid_lon"])["frp"].mean().reset_index()
baseline = baseline.rename(columns={"frp":"baseline_frp"})
df = df.merge(baseline, on=["grid_lat","grid_lon"], how="left")

# Deviation ratio, normalized 0-1 (capped at 3x baseline = max abnormality)
df["frp_deviation_ratio"] = (df["frp"] / df["baseline_frp"]).fillna(1.0)
df["thermal_abnormality"] = ((df["frp_deviation_ratio"] - 1) / 2).clip(0, 1)

df["persistence_norm"] = (df["recurrence_days"] / 5.0).clip(0, 1)

# Honest, defensible formula - only using evidence we actually have
# Spatial growth & facility criticality explicitly NOT included (no data yet) - documented as future work
df["risk_score"] = (0.60 * df["thermal_abnormality"] + 0.40 * df["persistence_norm"]).clip(0, 1)

def risk_level(score):
    if score >= 0.6: return "Critical"
    elif score >= 0.4: return "High"
    elif score >= 0.2: return "Moderate"
    else: return "Low"

df["risk_level"] = df["risk_score"].apply(risk_level)

print(df["risk_level"].value_counts())
df.to_csv("firms_final.csv", index=False)
print("Saved with revised risk_score")