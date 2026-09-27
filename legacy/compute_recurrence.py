import pandas as pd

fires = pd.read_csv("firms_with_distance.csv")

fires["grid_lat"] = fires["latitude"].round(2)
fires["grid_lon"] = fires["longitude"].round(2)

recurrence = fires.groupby(["grid_lat","grid_lon"])["acq_date"].nunique().reset_index()
recurrence = recurrence.rename(columns={"acq_date":"recurrence_days"})

fires = fires.merge(recurrence, on=["grid_lat","grid_lon"], how="left")

print(fires[["latitude","longitude","dist_to_industrial_km","recurrence_days"]])
fires.to_csv("firms_with_features.csv", index=False)
print("Saved to firms_with_features.csv")