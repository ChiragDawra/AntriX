import pandas as pd

df = pd.read_csv("firms_final.csv")

# Normalize FRP using percentile rank (robust to outliers, unlike min-max)
# frp_intensity_norm = fraction of all detections with FRP <= this one
df["frp_intensity_norm"] = df["frp"].rank(pct=True)

# Equal-weighted combination of three independent thermal/temporal signals
# Documented reasoning: until we have a validated ground-truth dataset to learn
# empirical weights, equal weighting across abnormality/persistence/intensity
# is the most defensible default (no signal is arbitrarily favored)
df["risk_score"] = (
    (1/3) * df["thermal_abnormality"] +
    (1/3) * df["persistence_norm"] +
    (1/3) * df["frp_intensity_norm"]
).clip(0, 1)

print(df[["frp","frp_intensity_norm","thermal_abnormality","persistence_norm","risk_score"]]
      .sort_values("frp", ascending=False).head(10))

df.to_csv("firms_final.csv", index=False)
print("\nSaved updated firms_final.csv with FRP-aware priority formula")