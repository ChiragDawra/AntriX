import pandas as pd

df = pd.read_csv("firms_final.csv")

print("Total rows:", len(df))
print("Rows with missing dist_to_industrial_km:", df["dist_to_industrial_km"].isna().sum())
print("Rows with missing nearest_facility_name:", df["nearest_facility_name"].isna().sum())
print()

zero_score = df[df["facility_proximity_score"] == 0]
nonzero_score = df[df["facility_proximity_score"] > 0]

print(f"Rows with facility_proximity_score == 0: {len(zero_score)}")
print(f"  -> dist_to_industrial_km range: {zero_score['dist_to_industrial_km'].min():.2f} to {zero_score['dist_to_industrial_km'].max():.2f} km")
print(f"  -> any below 5km (would indicate a bug)?: {(zero_score['dist_to_industrial_km'] < 5).sum()} rows")
print()
print(f"Rows with facility_proximity_score > 0: {len(nonzero_score)}")
print(f"  -> dist_to_industrial_km range: {nonzero_score['dist_to_industrial_km'].min():.2f} to {nonzero_score['dist_to_industrial_km'].max():.2f} km")
print(f"  -> any at/above 5km (would indicate a bug)?: {(nonzero_score['dist_to_industrial_km'] >= 5).sum()} rows")