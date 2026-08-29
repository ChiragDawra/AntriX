import pandas as pd
import joblib

df = pd.read_csv("firms_labeled.csv")
model = joblib.load("antrix_model_v2.pkl")

features = ["frp", "bright_ti4", "bright_ti5", "scan", "track"]
X = df[features].fillna(0)

proba = model.predict_proba(X)
classes = model.classes_
industrial_idx = list(classes).index("industrial")
df["ml_industrial_confidence"] = proba[:, industrial_idx]

def rule_score(row):
    if row["dist_to_industrial_km"] < 2 and row["recurrence_days"] >= 2:
        return 1.0
    elif row["dist_to_industrial_km"] < 2:
        return 0.6
    else:
        return 0.0

df["rule_score"] = df.apply(rule_score, axis=1)
df["final_confidence"] = (0.6 * df["rule_score"]) + (0.4 * df["ml_industrial_confidence"])

def final_label(score):
    if score >= 0.7:
        return "industrial"
    elif score >= 0.3:
        return "possible_industrial"
    else:
        return "unknown_other"

df["final_label"] = df["final_confidence"].apply(final_label)

print(df["final_label"].value_counts())
print("\nSample high-confidence industrial fires:")
print(df[df["final_label"]=="industrial"][["latitude","longitude","final_confidence"]].head(10))

df.to_csv("firms_final.csv", index=False)
print("\nSaved to firms_final.csv")