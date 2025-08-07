import os
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
import numpy as np
import osmnx as ox
import pystac_client
import stackstac
import rioxarray
import whitebox
from django.conf import settings
import re
import pandas as pd
from scipy.ndimage import distance_transform_edt
from typing import List, Dict, Any
import warnings
from rasterio.mask import mask
import threading

print("CONFIGURING: Setting environment for public cloud data access.")
os.environ['AWS_NO_SIGN_REQUEST'] = 'YES'
os.environ['GDAL_DISABLE_READDIR_ON_OPEN'] = 'EMPTY_DIR'

# --- Imports for Robust Validation and Error Handling ---
from pydantic import validate_call, FilePath, conlist, PositiveFloat, BaseModel
from .exceptions import ToolValidationError, ToolExecutionError

# --- WhiteboxTools Initialization ---
wbt = whitebox.WhiteboxTools()

# --- Thread-local context (unchanged) ---
_thread_local = threading.local()

def set_workflow_context(thread_id: str, place_name: str = None):
    _thread_local.thread_id = thread_id
    _thread_local.place_name = place_name

def get_workflow_context():
    thread_id = getattr(_thread_local, 'thread_id', None)
    place_name = getattr(_thread_local, 'place_name', None)
    return thread_id, place_name

# --- Helper functions ---
def get_output_filepath(filename: str) -> str:
    """Constructs a full, absolute path, defaulting vector files to the .gpkg format."""
    output_dir = settings.MEDIA_ROOT
    os.makedirs(output_dir, exist_ok=True)
    
    # --- UPDATED: Standardize on .gpkg for all intermediate vector files ---
    if filename.endswith(('.geojson', '.shp')):
        filename = re.sub(r'\.(geojson|shp)$', '.gpkg', filename)
    
    thread_id, place_name = get_workflow_context()
    if thread_id and place_name:
        clean_place = place_name.replace(' ', '_').replace(',', '').replace("'", "")
        prefixed_filename = f"{thread_id}_{clean_place}_{filename}"
        return os.path.join(output_dir, prefixed_filename)
    return os.path.join(output_dir, filename)

def get_bbox_from_place(place_name: str):
    try:
        gdf = ox.geocode_to_gdf(place_name)
        if gdf.empty:
            raise ValueError(f"Geocoding returned no results for '{place_name}'.")
        return gdf.total_bounds
    except Exception as e:
        raise ValueError(f"Geocoding failed for '{place_name}': {e}") from e

def _validate_and_read_vector(vector_path: str) -> gpd.GeoDataFrame:
    if not os.path.exists(vector_path):
        raise FileNotFoundError(f"Input vector file not found at '{vector_path}'.")
    
    if os.path.getsize(vector_path) == 0:
        raise ValueError(f"Vector file '{os.path.basename(vector_path)}' is empty and cannot be processed.")
    
    try:
        gdf = gpd.read_file(vector_path)
        if gdf.empty:
            raise ValueError(f"Vector file '{os.path.basename(vector_path)}' is empty.")
        if gdf.crs is None:
            gdf.crs = "EPSG:4326"
        return gdf
    except Exception as e:
        raise ValueError(f"Could not read vector file '{os.path.basename(vector_path)}': {e}") from e

# ==============================================================================
# --- 1. DATA ACQUISITION TOOLS ---
# ==============================================================================

class SimpleOSMTag(BaseModel):
    key: str
    value: str | list[str] # Allow a single value or a list of values for one key

@validate_call
def acquire_osm_data(place_name: str, tag: SimpleOSMTag) -> FilePath:
    """
    Acquires vector data from OSM for a SINGLE key-value tag pair.
    
    Args:
        place_name: The name of the place to query (e.g., "Delhi").
        tag: A dictionary with a single 'key' and a 'value' (string or list of strings).
    """
    tool_name = 'acquire_osm_data'
    try:
        # Convert our SimpleOSMTag model back into the dictionary osmnx expects
        tags_dict = {tag.key: tag.value}

        gdf = ox.features_from_place(place_name, tags_dict)
        if gdf.empty:
            raise ToolExecutionError(f"No features found for tag {tags_dict} in '{place_name}'.", tool_name=tool_name)
        
        feature_name = tag.key
        
        # Sanitize feature name for clean filenames
        sanitized_name = re.sub(r'[^a-zA-Z0-9_-]', '', feature_name)

        filename = f"osm_{sanitized_name}.geojson" # Use .geojson to trigger replacement
        filepath = get_output_filepath(filename)
        
        gdf.to_file(filepath, driver='GPKG')
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"OSM data acquisition failed: {e}", tool_name=tool_name) from e

@validate_call
def acquire_dem_data(place_name: str) -> FilePath:
    """Acquire a DEM raster for the given place name using Copernicus DEM."""
    tool_name = 'acquire_dem_data'
    try:
        bounds = list(get_bbox_from_place(place_name))
        catalog = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
        search = catalog.search(collections=["cop-dem-glo-30"], bbox=bounds)
        items = list(search.items())
        if not items:
            raise ToolExecutionError(f"No DEM data found for '{place_name}'.", tool_name=tool_name)

        stack = stackstac.stack(items, assets=["data"], bounds_latlon=bounds, resolution=30, epsg=4326)
        dem = stack.mean(dim="time").compute()
        
        filepath = get_output_filepath("dem.tif")
        dem.rio.write_crs("EPSG:4326", inplace=True)
        dem.rio.to_raster(filepath)
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"DEM acquisition failed: {e}", tool_name=tool_name) from e

# ==============================================================================
# --- 2. VECTOR ANALYSIS TOOLS ---
# ==============================================================================

@validate_call
def filter_vector_by_attribute(vector_path: FilePath, expression: str) -> FilePath:
    """Filters a vector file based on an attribute query, with robust type handling."""
    tool_name = 'filter_vector_by_attribute'
    try:
        gdf = _validate_and_read_vector(vector_path)
        print(f"TOOL: Pre-emptively converting columns to numeric for query: {expression}")
        
        # --- NEW: Future-proof numeric conversion ---
        for col in gdf.columns:
            if gdf[col].dtype == 'object' and col != 'geometry':
                try:
                    # Attempt conversion, but continue if it fails (i.e., it's a true string column)
                    gdf[col] = pd.to_numeric(gdf[col])
                except (ValueError, TypeError):
                    continue # Leave the column as is

        filtered_gdf = gdf.query(expression)
        
        if filtered_gdf.empty:
            raise ToolExecutionError("No features remained after applying the filter.", tool_name=tool_name)
        
        filepath = str(vector_path).replace('.gpkg', '_filtered.gpkg')
        filtered_gdf.to_file(filepath, driver='GPKG')
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Failed to filter vector data. Check query syntax. Details: {e}", tool_name=tool_name) from e
    
@validate_call
def perform_buffer(vector_path: FilePath, distance_meters: PositiveFloat) -> FilePath:
    """Creates a buffer zone around vector features."""
    tool_name = 'perform_buffer'
    try:
        gdf = _validate_and_read_vector(vector_path)
        utm_crs = gdf.estimate_utm_crs()
        if utm_crs is None:
            raise ToolExecutionError("Could not determine a suitable UTM projection.", tool_name=tool_name)
        
        gdf_proj = gdf.to_crs(utm_crs)
        gdf_proj['geometry'] = gdf_proj.buffer(distance_meters)
        gdf_buffered = gdf_proj.to_crs(gdf.crs)
        
        # --- FIXED: Use .gpkg for consistent filename replacement ---
        filepath = str(vector_path).replace(".gpkg", f"_buffer_{distance_meters}m.gpkg")
        gdf_buffered.to_file(filepath, driver='GPKG')
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Buffer analysis failed: {e}", tool_name=tool_name) from e

@validate_call
def calculate_vector_area(vector_path: FilePath, area_unit: str = 'sqm') -> FilePath:
    """Calculates the area of each polygon and adds it as a new column."""
    tool_name = 'calculate_vector_area'
    try:
        gdf = _validate_and_read_vector(vector_path)
        utm_crs = gdf.estimate_utm_crs()
        if utm_crs is None:
            raise ToolExecutionError("Could not determine a suitable UTM projection for area calculation.", tool_name=tool_name)
        
        gdf_proj = gdf.to_crs(utm_crs)
        area_sqm = gdf_proj.geometry.area
        
        if area_unit == 'sqkm':
            gdf['area_sqkm'] = area_sqm / 1_000_000
        else:
            gdf['area_sqm'] = area_sqm
        
        # --- FIXED: Use .gpkg for consistent filename replacement ---
        filepath = str(vector_path).replace('.gpkg', '_with_area.gpkg')
        gdf.to_file(filepath, driver='GPKG')
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Failed to calculate vector area: {e}", tool_name=tool_name) from e

# ==============================================================================
# --- 3. RASTER ANALYSIS TOOLS ---
# ==============================================================================

@validate_call
def calculate_slope(dem_path: FilePath) -> FilePath:
    """Calculates slope from a DEM."""
    tool_name = 'calculate_slope'
    try:
        filepath = str(dem_path).replace('.tif', '_slope.tif')
        wbt.slope(dem=str(dem_path), output=filepath)
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Slope calculation failed: {e}", tool_name=tool_name) from e

@validate_call
def reclassify_raster(raster_path: FilePath, reclass_values: List[List[Any]]) -> FilePath:
    """Reclassifies a raster, automatically handling 'null'/'None' for open-ended ranges."""
    tool_name = 'reclassify_raster'
    try:
        filepath = str(raster_path).replace('.tif', '_reclass.tif')
        reclass_items = []
        for row in reclass_values:
            if len(row) >= 3:
                low, high, new = row[0], row[1], row[2]
                # --- Resilient handling of null for "infinity" ---
                if high is None or str(high).lower() == 'null':
                    high = 999999
                reclass_items.append(f"{new};{low};{high}")
        
        if not reclass_items:
            raise ToolValidationError("Reclassification values list was empty or invalid.", tool_name=tool_name)
        
        reclass_str = ";".join(reclass_items)
        wbt.reclass(i=str(raster_path), output=filepath, reclass_vals=reclass_str)
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Raster reclassification failed: {e}", tool_name=tool_name) from e

@validate_call
def calculate_proximity_raster(vector_path: FilePath, reference_raster_path: FilePath) -> FilePath:
    """Creates a raster showing Euclidean distance to vector features."""
    tool_name = 'calculate_proximity_raster'
    try:
        gdf = _validate_and_read_vector(vector_path)
        with rasterio.open(reference_raster_path) as ref:
            meta = ref.meta.copy()
            gdf_proj = gdf.to_crs(ref.crs)
            mask_array = rasterize(
                shapes=[geom for geom in gdf_proj.geometry], 
                out_shape=(meta['height'], meta['width']), 
                transform=meta['transform'], fill=0, all_touched=True, dtype=np.uint8
            )
            proximity_data = distance_transform_edt(mask_array == 0)
        
        feature_name = os.path.basename(str(vector_path)).split('.')[0]
        filename = f"proximity_{feature_name}.tif"
        filepath = get_output_filepath(filename)
        
        meta.update(dtype='float32')
        with rasterio.open(filepath, 'w', **meta) as dst:
            dst.write(proximity_data.astype(np.float32), 1)
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Proximity calculation failed: {e}", tool_name=tool_name) from e

# ==============================================================================
# --- 4. SPATIAL UTILITY TOOLS ---
# ==============================================================================

@validate_call
def clip_data(data_to_clip_path: FilePath, clip_boundary_path: FilePath) -> FilePath:
    """Clips a vector or raster file to the extent of a boundary polygon."""
    tool_name = 'clip_data'
    try:
        clip_gdf = _validate_and_read_vector(clip_boundary_path)
        if not any(g_type in ['Polygon', 'MultiPolygon'] for g_type in clip_gdf.geometry.geom_type.unique()):
            raise ToolValidationError("Clipping boundary must contain Polygon geometries.", tool_name=tool_name)

        if str(data_to_clip_path).endswith('.gpkg'):
            data_gdf = _validate_and_read_vector(data_to_clip_path)
            clipped_gdf = gpd.clip(data_gdf.to_crs(clip_gdf.crs), clip_gdf)
            if clipped_gdf.empty:
                raise ToolExecutionError("Clip operation resulted in an empty layer.", tool_name=tool_name)
            # --- FIXED: Use .gpkg for consistent filename replacement ---
            filepath = str(data_to_clip_path).replace('.gpkg', '_clipped.gpkg')
            clipped_gdf.to_file(filepath, driver='GPKG')
            return filepath
        
        elif str(data_to_clip_path).endswith(('.tif', '.tiff')):
            with rasterio.open(data_to_clip_path) as src:
                out_image, out_transform = mask(src, clip_gdf.to_crs(src.crs).geometry, crop=True)
                out_meta = src.meta.copy()
            out_meta.update({"driver": "GTiff", "height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform})
            filepath = str(data_to_clip_path).replace('.tif', '_clipped.tif')
            with rasterio.open(filepath, "w", **out_meta) as dest:
                dest.write(out_image)
            return filepath
        else:
            raise ToolValidationError(f"Unsupported file type for clipping.", tool_name=tool_name)
    except Exception as e:
        raise ToolExecutionError(f"Clipping operation failed: {e}", tool_name=tool_name) from e

@validate_call
def rasterize_vector(vector_path: FilePath, reference_raster_path: FilePath, burn_value: float = 1.0) -> FilePath:
    """Converts a vector file into a raster grid matching a reference raster."""
    tool_name = 'rasterize_vector'
    try:
        gdf = _validate_and_read_vector(vector_path)
        with rasterio.open(reference_raster_path) as ref:
            meta = ref.meta.copy()
            gdf_proj = gdf.to_crs(ref.crs)

        shapes = ((geom, burn_value) for geom in gdf_proj.geometry)
        filepath = get_output_filepath(f"rasterized_{os.path.basename(str(vector_path)).split('.')[0]}.tif")
        
        with rasterio.open(filepath, 'w+', **meta) as out:
            out_arr = out.read(1)
            rasterized_arr = rasterize(shapes=shapes, fill=0, out=out_arr, transform=out.transform)
            out.write(rasterized_arr, 1)
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Rasterization failed: {e}", tool_name=tool_name) from e

@validate_call
def subtract_rasters(raster_a: FilePath, raster_b: FilePath) -> FilePath:
    """
    Subtracts the pixel values of one raster from another (A - B).
    Both rasters must have the same shape and CRS.
    """
    tool_name = 'subtract_rasters'
    try:
        with rasterio.open(raster_a) as src_a, rasterio.open(raster_b) as src_b:
            if src_a.crs != src_b.crs or src_a.shape != src_b.shape:
                raise ToolValidationError("Input rasters for subtraction must have the same CRS and dimensions.", tool_name=tool_name)
            
            data_a = src_a.read(1).astype(np.float32)
            data_b = src_b.read(1).astype(np.float32)
            
            meta = src_a.meta.copy()
            result_data = data_a - data_b

        # Use the context to name the file, as it doesn't belong to one place
        thread_id, _ = get_workflow_context()
        filename = f"{thread_id}_subtraction_result.tif"
        filepath = os.path.join(settings.MEDIA_ROOT, filename)
        
        meta.update(dtype='float32')
        with rasterio.open(filepath, 'w', **meta) as dst:
            dst.write(result_data, 1)
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Raster subtraction failed: {e}", tool_name=tool_name) from e

@validate_call
def polygonize_raster(raster_path: FilePath, value_to_polygonize: int) -> FilePath:
    """Converts pixels of a specific value from a raster into vector polygons."""
    tool_name = 'polygonize_raster'
    try:
        with rasterio.open(raster_path) as src:
            image = src.read(1)
            mask_array = image == value_to_polygonize
            results = [{'properties': {'raster_val': v}, 'geometry': s}
                       for i, (s, v) in enumerate(rasterio.features.shapes(image, mask=mask_array, transform=src.transform))]

        if not results:
            raise ToolExecutionError(f"No pixels with value '{value_to_polygonize}' found.", tool_name=tool_name)

        gdf = gpd.GeoDataFrame.from_features(results, crs=src.crs)
        
        # --- FIXED: Output as GeoPackage for consistency ---
        filepath = str(raster_path).replace('.tif', '_polygons.gpkg')
        gdf.to_file(filepath, driver='GPKG')
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Failed to polygonize raster: {e}", tool_name=tool_name) from e

# ==============================================================================
# --- 5. SYNTHESIS & PUBLISHING TOOLS ---
# ==============================================================================

class WeightedOverlayInput(BaseModel):
    raster_path: FilePath
    weight: PositiveFloat

@validate_call
def perform_weighted_overlay(layer_weights: conlist(WeightedOverlayInput, min_length=1)) -> FilePath:
    """Performs a weighted sum of multiple rasters using a validated list of inputs."""
    tool_name = 'perform_weighted_overlay'
    try:
        base_raster_path = layer_weights[0].raster_path
        with rasterio.open(base_raster_path) as src:
            final_raster = np.zeros(src.shape, dtype=np.float32)
            meta = src.meta.copy()
            target_crs, target_shape = src.crs, src.shape

        for layer in layer_weights:
            with rasterio.open(layer.raster_path) as lyr_src:
                if lyr_src.crs != target_crs:
                    raise ToolExecutionError(f"CRS mismatch in layer {os.path.basename(str(layer.raster_path))}", tool_name=tool_name)
                if lyr_src.shape != target_shape:
                    raise ToolExecutionError(f"Shape mismatch in layer {os.path.basename(str(layer.raster_path))}", tool_name=tool_name)
                
                final_raster += lyr_src.read(1).astype(np.float32) * layer.weight
        
        filepath = get_output_filepath("suitability_map.tif")
        meta.update(dtype='float32')
        with rasterio.open(filepath, 'w', **meta) as dst:
            dst.write(final_raster, 1)
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Weighted overlay failed: {e}", tool_name=tool_name) from e

@validate_call
def multiply_rasters(**kwargs: FilePath) -> FilePath:
    """
    Multiplies any number of provided rasters together. This tool is extremely
    flexible and accepts multiple keyword arguments, as long as each argument's
    value is a valid file path to a raster.

    Example valid calls from the AI:
    - multiply_rasters(raster_a='path1.tif', raster_b='path2.tif')
    - multiply_rasters(suitable_land='path1.tif', transport='path2.tif', clinics='path3.tif')
    """
    tool_name = 'multiply_rasters'
    try:
        # --- NEW: The **kwargs approach makes input handling extremely robust ---
        # `kwargs` is now a dictionary of all named arguments passed to the function.
        # Because of the `**kwargs: FilePath` type hint, Pydantic has already
        # validated that EVERY value in this dictionary is a valid, existing file path.
        
        files_to_multiply = list(kwargs.values())

        if len(files_to_multiply) < 2:
            raise ToolValidationError("This tool requires at least two raster files to multiply.", tool_name=tool_name)
        # --- End of new logic ---

        # The rest of the function proceeds as before
        with rasterio.open(files_to_multiply[0]) as src:
            final_raster = src.read(1).astype(np.float32)
            meta, target_crs, target_shape = src.meta.copy(), src.crs, src.shape

        for raster_path in files_to_multiply[1:]:
            with rasterio.open(raster_path) as src:
                if src.crs != target_crs or src.shape != target_shape:
                    raise ToolValidationError("All input rasters must have the same CRS and dimensions.", tool_name=tool_name)
                final_raster *= src.read(1).astype(np.float32)
        
        filepath = get_output_filepath("boolean_suitability_map.tif")
        meta.update(dtype='float32')
        with rasterio.open(filepath, 'w', **meta) as dst:
            dst.write(final_raster, 1)
        return filepath
    except Exception as e:
        raise ToolExecutionError(f"Raster multiplication failed: {e}", tool_name=tool_name) from e