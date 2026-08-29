import pandas as pd
import folium

df = pd.read_csv("firms_final.csv")

m = folium.Map(location=[22, 79], zoom_start=5, tiles="CartoDB positron")

colors = {
    "industrial": "red",
    "possible_industrial": "orange",
    "unknown_other": "gray"
}

for _, row in df.iterrows():
    folium.CircleMarker(
        location=[row["latitude"], row["longitude"]],
        radius=5 if row["final_label"]=="industrial" else 3,
        color=colors.get(row["final_label"], "blue"),
        fill=True,
        fill_opacity=0.75,
        popup=(f"<b>{row['final_label']}</b><br>"
               f"Confidence: {row['final_confidence']:.2f}<br>"
               f"Dist to industry: {row['dist_to_industrial_km']:.1f} km<br>"
               f"Recurrence: {row['recurrence_days']} days<br>"
               f"FRP: {row['frp']}")
    ).add_to(m)

legend_html = '''
<div style="position: fixed; bottom: 30px; left: 30px; z-index:9999; background:white; padding:10px; border-radius:5px; box-shadow:0 0 5px gray;">
<b>AntriX Classification</b><br>
<span style="color:red;">●</span> Industrial<br>
<span style="color:orange;">●</span> Possible Industrial<br>
<span style="color:gray;">●</span> Other/Unclassified
</div>
'''
m.get_root().html.add_child(folium.Element(legend_html))

m.save("antrix_map_final.html")
print("Saved to antrix_map_final.html")