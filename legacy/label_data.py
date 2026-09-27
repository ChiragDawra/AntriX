import pandas as pd

fires = pd.read_csv("firms_with_features.csv")

def label_row(row):
    if row["dist_to_industrial_km"] < 2 and row["recurrence_days"] >= 2:
        return "industrial"
    elif row["dist_to_industrial_km"] < 2:
        return "possible_industrial"
    else:
        return "unknown_other"

fires["label"] = fires.apply(label_row, axis=1)

print(fires[["latitude","longitude","dist_to_industrial_km","recurrence_days","label"]])
fires.to_csv("firms_labeled.csv", index=False)
print("Saved to firms_labeled.csv")