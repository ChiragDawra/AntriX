import pandas as pd
import folium

fires = pd.read_csv("firms_labeled.csv")

m = folium.Map(location=[22, 79], zoom_start=5)

colors = {
    "industrial": "red",
    "possible_industrial": "orange",
    "unknown_other": "gray"
}

for _, row in fires.iterrows():
    folium.CircleMarker(
        location=[row["latitude"], row["longitude"]],
        radius=4,
        color=colors.get(row["label"], "blue"),
        fill=True,
        fill_opacity=0.7,
        popup=f"{row['label']} | dist:{row['dist_to_industrial_km']:.1f}km | recur:{row['recurrence_days']}"
    ).add_to(m)

m.save("antrix_map.html")
print("Saved to antrix_map.html")