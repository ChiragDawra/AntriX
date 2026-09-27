import pandas as pd

df = pd.read_csv("firms_final.csv")

# Risk score: how urgently should this be investigated
# Based on: FRP (intensity), recurrence (persistence/growing pattern), fusion_score (classification confidence)
df["frp_norm"] = (df["frp"] - df["frp"].min()) / (df["frp"].max() - df["frp"].min())
df["recurrence_norm"] = df["recurrence_days"] / 5.0

df["risk_score"] = (0.4 * df["fusion_score"] + 0.35 * df["frp_norm"] + 0.25 * df["recurrence_norm"]).clip(0, 1)

def risk_level(score):
    if score >= 0.65: return "Critical"
    elif score >= 0.45: return "High"
    elif score >= 0.25: return "Moderate"
    else: return "Low"

df["risk_level"] = df["risk_score"].apply(risk_level)

print(df["risk_level"].value_counts())
df.to_csv("firms_final.csv", index=False)
print("Saved with risk_score")