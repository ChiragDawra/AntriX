import pandas as pd

df = pd.read_csv("firms_final.csv")

MAX_EVIDENCE = 0.35 + 0.35
df["industrial_evidence_score"] = (
    (df["facility_proximity_score"] + df["thermal_intensity_score"]) / MAX_EVIDENCE
).clip(0, 1)

def evidence_tier(score):
    if score >= 0.7: return "High"
    elif score >= 0.4: return "Moderate"
    else: return "Low"

df["evidence_level"] = df["industrial_evidence_score"].apply(evidence_tier)

def classify(row):
    if row["facility_proximity_score"] == 0:
        return "insufficient_evidence"
    if row["recurrence_days"] >= 3:
        return "persistent_industrial_source"
    else:
        return "industrial_fire"

before = df["final_label"].value_counts()
df["final_label"] = df.apply(classify, axis=1)
after = df["final_label"].value_counts()

print("BEFORE (old 3-category system):")
print(before)
print("\nAFTER (new classification tree):")
print(after)
print("\nEvidence level breakdown within each new category:")
print(df.groupby("final_label")["evidence_level"].value_counts())

df.loc[df["final_label"] == "insufficient_evidence", "evidence_level"] = None

df.to_csv("firms_final.csv", index=False)
print("\nSaved firms_final.csv with new classification")