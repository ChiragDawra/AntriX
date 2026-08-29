import pandas as pd
import numpy as np
from math import radians, sin, cos, sqrt, atan2

SPATIAL_THRESHOLD_KM = 3.0
TEMPORAL_THRESHOLD_DAYS = 5
MIN_CLUSTER_SIZE = 2

df = pd.read_csv("firms_final.csv")
df["acq_date"] = pd.to_datetime(df["acq_date"])
n = len(df)
lats = df["latitude"].values
lons = df["longitude"].values
dates = df["acq_date"].values

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1))*np.cos(np.radians(lat2))*np.sin(dlon/2)**2
    return R * 2 * np.arcsin(np.sqrt(a))

parent = list(range(n))
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[ra] = rb

grid_size = 0.05
buckets = {}
for i in range(n):
    key = (round(lats[i] / grid_size), round(lons[i] / grid_size))
    buckets.setdefault(key, []).append(i)

checked_pairs = 0
for (gx, gy), idxs in buckets.items():
    neighbor_idxs = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            neighbor_idxs.extend(buckets.get((gx+dx, gy+dy), []))
    neighbor_idxs = list(set(neighbor_idxs))
    for i in idxs:
        for j in neighbor_idxs:
            if j <= i:
                continue
            checked_pairs += 1
            dist = haversine_km(lats[i], lons[i], lats[j], lons[j])
            if dist <= SPATIAL_THRESHOLD_KM:
                day_diff = abs((dates[i] - dates[j]).astype('timedelta64[D]').astype(int))
                if day_diff <= TEMPORAL_THRESHOLD_DAYS:
                    union(i, j)

print(f"Checked {checked_pairs} candidate pairs")

roots = [find(i) for i in range(n)]
df["_root"] = roots

root_counts = df["_root"].value_counts()
cluster_roots = root_counts[root_counts >= MIN_CLUSTER_SIZE].index.tolist()
root_to_cid = {r: f"C{idx+1}" for idx, r in enumerate(cluster_roots)}
df["cluster_id"] = df["_root"].map(root_to_cid)

print(f"\nTotal detections: {n}")
print(f"Detections in clusters (size>={MIN_CLUSTER_SIZE}): {df['cluster_id'].notna().sum()}")
print(f"Number of clusters: {len(cluster_roots)}")
print(f"Singleton detections: {df['cluster_id'].isna().sum()}")

df.drop(columns=["_root"]).to_csv("firms_final.csv", index=False)

cluster_rows = []
for cid in df["cluster_id"].dropna().unique():
    sub = df[df["cluster_id"] == cid]
    top = sub.loc[sub["risk_score"].idxmax()]
    cluster_rows.append({
        "cluster_id": cid,
        "count": len(sub),
        "centroid_lat": sub["latitude"].mean(),
        "centroid_lon": sub["longitude"].mean(),
        "first_date": sub["acq_date"].min().strftime("%Y-%m-%d"),
        "last_date": sub["acq_date"].max().strftime("%Y-%m-%d"),
        "persistence_days": (sub["acq_date"].max() - sub["acq_date"].min()).days + 1,
        "max_frp": round(sub["frp"].max(), 2),
        "avg_frp": round(sub["frp"].mean(), 2),
        "max_priority": round(sub["risk_score"].max(), 2),
        "max_fusion": round(sub["fusion_score"].max(), 2),
        "dominant_label": sub["final_label"].mode()[0],
        "industrial_context": top["industrial_context"],
        "nearest_facility_name": top["nearest_facility_name"],
        "nearest_facility_type": top["nearest_facility_type"],
        "dist_to_industrial_km": round(top["dist_to_industrial_km"], 2)
    })

clusters_df = pd.DataFrame(cluster_rows)
clusters_df.to_csv("clusters.csv", index=False)
print(f"\nSaved clusters.csv with {len(clusters_df)} clusters")
print(clusters_df[["cluster_id","count","first_date","last_date","max_frp","max_priority","dominant_label"]].head(10))