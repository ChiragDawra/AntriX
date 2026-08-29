import osmnx as ox
import geopandas as gpd

# Same bounding box as FIRMS: west,south,east,north = 68,20,73,24
north, south, east, west = 24, 20, 73, 68

tags = {
    "landuse": "industrial",
    "man_made": ["works", "petroleum_well"],
    "power": "plant",
    "industrial": True
}

print("Fetching OSM industrial features... this may take 1-2 min")

gdf = ox.features_from_bbox((west, south, east, north), tags)

print("Features found:", len(gdf))
print(gdf[["geometry"]].head())

gdf.to_file("osm_industrial.geojson", driver="GeoJSON")
print("Saved to osm_industrial.geojson")