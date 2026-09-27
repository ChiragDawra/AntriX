import pandas as pd

df = pd.read_csv("firms_final.csv")

def corrected_label(row):
    # HARD RULE: cannot be labeled industrial/possible_industrial with zero
    # facility-proximity evidence, no matter how high persistence/thermal score is.
    # Without a nearby facility, there is no industrial claim to make.
    if row["facility_proximity_score"] == 0:
        return "unknown_other"
    if row["fusion_score"] >= 0.6:
        return "industrial"
    elif row["fusion_score"] >= 0.3:
        return "possible_industrial"
    else:
        return "unknown_other"

before = df["final_label"].value_counts()
df["final_label"] = df.apply(corrected_label, axis=1)
after = df["final_label"].value_counts()

print("BEFORE:\n", before)
print("\nAFTER:\n", after)

# Add explicit industrial context field for UI transparency
def industrial_context(row):
    if row["dist_to_industrial_km"] < 2:
        return "Within known industrial zone"
    elif row["dist_to_industrial_km"] < 5:
        return "Adjacent to industrial zone"
    else:
        return "No nearby industrial zone"

df["industrial_context"] = df.apply(industrial_context, axis=1)

df.to_csv("firms_final.csv", index=False)
print("\nSaved corrected firms_final.csv")