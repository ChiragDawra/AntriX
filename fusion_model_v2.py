import pandas as pd
import joblib

df = pd.read_csv("firms_labeled.csv")
model = joblib.load("antrix_model_v2.pkl")

features = ["frp", "bright_ti4", "bright_ti5", "scan", "track"]
X = df[features].fillna(0)

proba = model.predict_proba(X)
classes = model.classes_
industrial_idx = list(classes).index("industrial")
df["ml_thermal_score"] = proba[:, industrial_idx]

# Break rule score into explicit named components (evidence items)
def facility_component(row):
    if row["dist_to_industrial_km"] < 2:
        return 0.35
    elif row["dist_to_industrial_km"] < 5:
        return 0.15
    return 0.0

def persistence_component(row):
    if row["recurrence_days"] >= 3:
        return 0.30
    elif row["recurrence_days"] == 2:
        return 0.20
    return 0.0

df["facility_proximity_score"] = df.apply(facility_component, axis=1)
df["persistence_score"] = df.apply(persistence_component, axis=1)
df["thermal_intensity_score"] = df["ml_thermal_score"] * 0.35

df["fusion_score"] = (df["facility_proximity_score"] + df["persistence_score"] + df["thermal_intensity_score"]).clip(0, 1)

def final_label(score):
    if score >= 0.6:
        return "industrial"
    elif score >= 0.3:
        return "possible_industrial"
    else:
        return "unknown_other"

df["final_label"] = df["fusion_score"].apply(final_label)

print(df["final_label"].value_counts())
df.to_csv("firms_final.csv", index=False)
print("Saved to firms_final.csv")