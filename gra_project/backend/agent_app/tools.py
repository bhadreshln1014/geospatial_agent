import os
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_bounds
import numpy as np
import osmnx as ox
import pystac_client
import stackstac
import whitebox
import requests
from django.conf import settings
from geoserver.catalog import Catalog
import re
from scipy.ndimage import distance_transform_edt

# Initialize WhiteboxTools once
wbt = whitebox.WhiteboxTools()

# --- Helper Functions ---
def get_output_filepath(filename: str) -> str:
    """Constructs a full, absolute path in the Django MEDIA_ROOT."""
    output_dir = settings.MEDIA_ROOT
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, filename)

def get_bbox_from_place(place_name: str):
    """Geocodes a place name to get its bounding box."""
    return ox.geocode_to_gdf(place_name).total_bounds

def geocode_place(place_name: str):
    """Geocode a place name to get latitude and longitude."""
    gdf = ox.geocode_to_gdf(place_name)
    centroid = gdf.geometry.iloc[0].centroid
    return centroid.y, centroid.x  # lat, lon

# --- 1. DATA ACQUISITION TOOLS ---

def acquire_osm_data(place_name: str, tags: dict) -> str:
    """Acquires vector data from OpenStreetMap. Returns absolute filepath."""
    print(f"TOOL: Acquiring OSM data for '{place_name}' with tags: {tags}")
    try:
        gdf = ox.features_from_place(place_name, tags)
        if gdf.empty:
            return f"Error: No features found for tags {tags} in {place_name}."
        
        feature_name = list(tags.values())[0] if tags else 'features'
        filename = f"osm_{place_name.replace(' ', '_')}_{feature_name}.geojson"
        filepath = get_output_filepath(filename)
        gdf.to_file(filepath, driver='GeoJSON')
        return filepath
    except Exception as e:
        return f"Error during OSM data acquisition: {e}"

def acquire_dem_data(place_name: str) -> str:
    """Acquires Copernicus DEM data for a place. Returns absolute filepath."""
    print(f"TOOL: Acquiring DEM data for '{place_name}'")
    try:
        bounds = get_bbox_from_place(place_name)
        catalog = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
        search = catalog.search(collections=["cop-dem-glo-30"], bbox=bounds)
        items = list(search.items())
        if not items:
            return f"Error: No DEM data found for {place_name}."
        stack = stackstac.stack(items, assets=["data"], bounds_latlon=bounds, resolution=30)
        dem = stack.mean(dim="time").compute()
        filepath = get_output_filepath(f"dem_{place_name.replace(' ', '_')}.tif")
        dem.rio.to_raster(filepath)
        return filepath
    except Exception as e:
        return f"Error during DEM acquisition: {e}"

def acquire_bhuvan_data(place_name: str, layer_name: str) -> str:
    """Acquires vector data from ISRO's Bhuvan WFS service. Returns absolute filepath."""
    print(f"TOOL: Acquiring Bhuvan layer '{layer_name}' for '{place_name}'")
    try:
        bounds = get_bbox_from_place(place_name)
        wfs_url = "https://bhuvan-app1.nrsc.gov.in/geoserver/wfs"
        params = {'service': 'WFS', 'version': '1.0.0', 'request': 'GetFeature', 'typeName': layer_name, 'outputFormat': 'application/json', 'bbox': f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]},EPSG:4326"}
        gdf = gpd.read_file(wfs_url, params=params)
        if gdf.empty:
            return f"Error: No Bhuvan data found for layer {layer_name}."
        
        filename = f"bhuvan_{layer_name.replace(':', '_')}.geojson"
        filepath = get_output_filepath(filename)
        gdf.to_file(filepath, driver='GeoJSON')
        return filepath
    except Exception as e:
        return f"Error during Bhuvan data acquisition: {e}"

# --- 2. VECTOR ANALYSIS TOOLS ---

def filter_vector_by_attribute(vector_path: str, expression: str) -> str:
    """Filters a vector file based on an attribute query. E.g., 'area_sqkm > 5'. Returns new filepath."""
    try:
        gdf = gpd.read_file(vector_path)
        filtered_gdf = gdf.query(expression)
        if filtered_gdf.empty:
            return f"Error: No features remained after applying filter '{expression}'."
        filepath = vector_path.replace('.geojson', '_filtered.geojson')
        filtered_gdf.to_file(filepath, driver='GeoJSON')
        return filepath
    except Exception as e:
        return f"Error during vector filtering: {e}"

def perform_buffer(vector_filepath: str, distance_meters: float) -> str:
    """Creates a buffer zone around vector features. Returns new absolute filepath."""
    try:
        gdf = gpd.read_file(vector_filepath)
        gdf_proj = gdf.to_crs(gdf.estimate_utm_crs())
        gdf_proj['geometry'] = gdf_proj.buffer(distance_meters)
        gdf_buffered = gdf_proj.to_crs(gdf.crs)
        filepath = vector_filepath.replace(".geojson", f"_buffer_{distance_meters}m.geojson")
        gdf_buffered.to_file(filepath, driver='GeoJSON')
        return filepath
    except Exception as e:
        return f"Error during buffer analysis: {e}"

# --- 3. RASTER ANALYSIS TOOLS ---

def calculate_slope(dem_path: str) -> str:
    """Calculates slope from a DEM using WhiteboxTools. Returns filepath of slope raster."""
    try:
        filepath = dem_path.replace('.tif', '_slope.tif')
        wbt.slope(dem=dem_path, output=filepath)
        return filepath
    except Exception as e:
        return f"Error during slope calculation: {e}"

def reclassify_raster(raster_path: str, reclass_values: list) -> str:
    """Reclassifies a raster based on a list of ranges. E.g., [[0, 10, 1], [10, 20, 0]]. Returns new filepath."""
    try:
        filepath = raster_path.replace('.tif', '_reclass.tif')
        reclass_str = ";".join([f"{new};{low};{high}" for high, low, new in reclass_values])
        wbt.reclass(i=raster_path, output=filepath, reclass_vals=reclass_str)
        return filepath
    except Exception as e:
        return f"Error during raster reclassification: {e}"

def calculate_proximity_raster(vector_path: str, reference_raster_path: str) -> str:
    """Creates a raster showing Euclidean distance to vector features. Returns distance raster filepath."""
    try:
        with rasterio.open(reference_raster_path) as ref:
            meta = ref.meta.copy()

        gdf = gpd.read_file(vector_path).to_crs(meta['crs'])
        mask = rasterize(shapes=[geom for geom in gdf.geometry], out_shape=(meta['height'], meta['width']), transform=meta['transform'], fill=0, all_touched=True, dtype=np.uint8)
        proximity_data = distance_transform_edt(mask == 0)
        
        filename = f"proximity_{os.path.basename(vector_path).split('.')[0]}.tif"
        filepath = get_output_filepath(filename)
        meta.update(dtype='float32')
        with rasterio.open(filepath, 'w', **meta) as dst:
            dst.write(proximity_data.astype(np.float32), 1)
        return filepath
    except Exception as e:
        return f"Error during proximity calculation: {e}"

# --- 4. SYNTHESIS & PUBLISHING TOOLS ---

def perform_weighted_overlay(layer_weights: dict) -> str:
    """Performs a weighted sum of multiple pre-processed rasters. Returns final suitability raster filepath."""
    try:
        base_raster_path = list(layer_weights.keys())[0]
        with rasterio.open(base_raster_path) as src:
            final_raster = np.zeros(src.shape, dtype=np.float32)
            meta = src.meta.copy()

        for path, weight in layer_weights.items():
            with rasterio.open(path) as src:
                # Add reprojection logic here if needed for robustness
                final_raster += src.read(1) * weight
                
        filepath = get_output_filepath("suitability_map.tif")
        meta.update(dtype='float32')
        with rasterio.open(filepath, 'w', **meta) as dst:
            dst.write(final_raster, 1)
        return filepath
    except Exception as e:
        return f"Error during weighted overlay: {e}"

def publish_to_geoserver(raster_path: str, layer_name: str) -> dict:
    """Publishes a final raster map to GeoServer. Returns map info dictionary."""
    try:
        sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '_', layer_name).lower()
        cat = Catalog("http://localhost:8080/geoserver/rest/", "admin", "geoserver")
        ws = cat.get_workspace("gra") or cat.create_workspace("gra", "http://geospatial-reasoning-agent.org/gra")
        cat.create_geotiff_layer(
            layer_name=sanitized_name, path=raster_path, workspace="gra",
            overwrite=True, style="suitability_style"
        )
        layer = cat.get_layer(sanitized_name)
        bbox = layer.resource.native_bbox
        return {
            "wmsUrl": "http://localhost:8080/geoserver/gra/wms",
            "layerName": f"gra:{sanitized_name}",
            "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
        }
    except Exception as e:
        return {"error": f"Failed to publish to GeoServer: {e}"}