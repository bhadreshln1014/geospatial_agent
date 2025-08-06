import os
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_bounds
import numpy as np
import osmnx as ox
import pystac_client
import stackstac
import rioxarray  # Required for .rio accessor on xarray DataArrays
import whitebox
import requests
from django.conf import settings
import re
from scipy.ndimage import distance_transform_edt
from typing import List, Dict
# --- NEW IMPORTS ---
import warnings
from rasterio.mask import mask
import threading

# Thread-local storage for workflow context
_thread_local = threading.local()

def set_workflow_context(thread_id: str, place_name: str = None):
    """Set workflow context for current thread to enable proper file naming."""
    _thread_local.thread_id = thread_id
    _thread_local.place_name = place_name

def get_workflow_context():
    """Get current workflow context (thread_id, place_name)."""
    thread_id = getattr(_thread_local, 'thread_id', None)
    place_name = getattr(_thread_local, 'place_name', None)
    return thread_id, place_name

def find_layer_by_place_and_type(place_name: str, layer_type: str, output_dir: str) -> str:
    """
    Helper function to find layer files for specific place and layer type.
    Useful for multi-place comparisons.
    
    Args:
        place_name: Place name (e.g., "Chennai", "Mumbai")
        layer_type: Layer type (e.g., "slope", "proximity", "dem")
        output_dir: Directory to search in
    
    Returns:
        File path if found, None otherwise
    """
    import glob
    
    # Sanitize place name for filename matching
    clean_place = place_name.replace(' ', '_').replace(',', '').replace("'", "").replace('.', '')
    
    # Define patterns based on layer type
    if layer_type.lower() == "slope":
        patterns = [
            f"*_{clean_place}_*slope_reclass.tif",
            f"*_{clean_place}_*slope.tif",
            f"*{clean_place}*slope_reclass.tif",
            f"*{clean_place}*slope.tif"
        ]
    elif layer_type.lower() == "proximity":
        patterns = [
            f"*_{clean_place}_proximity*reclass.tif",
            f"*_{clean_place}_proximity*.tif",
            f"*{clean_place}*proximity*reclass.tif",
            f"*{clean_place}*proximity*.tif"
        ]
    elif layer_type.lower() == "dem":
        patterns = [
            f"*_{clean_place}_dem.tif",
            f"*{clean_place}*dem.tif"
        ]
    else:
        # Generic pattern
        patterns = [
            f"*_{clean_place}_*{layer_type}*.tif",
            f"*{clean_place}*{layer_type}*.tif"
        ]
    
    # Try each pattern
    for pattern in patterns:
        matches = glob.glob(os.path.join(output_dir, pattern))
        if matches:
            # Return most recent file
            return max(matches, key=os.path.getmtime)
    
    return None

def find_layer_by_place_direct(place_name: str, layer_type: str = None) -> str:
    """
    Simplified direct layer identification for comparison workflows.
    Since comparison workflows process places sequentially, we can directly
    identify layers by place name in the consistent filename structure.
    
    Args:
        place_name: Place name (e.g., "Chennai", "Mumbai", "Delhi")
        layer_type: Optional layer type filter (e.g., "slope_reclass", "proximity_reclass")
    
    Returns:
        File path if found, None otherwise
    """
    import glob
    
    output_dir = settings.MEDIA_ROOT
    
    # Sanitize place name - handle common variations
    clean_place = place_name.replace(' ', '_').replace(',', '').replace("'", "").replace('.', '')
    
    # For comparison workflows, files follow the pattern: {thread_id}_{place}_{layer_type}.tif
    if layer_type:
        # Look for specific layer type
        if "reclass" not in layer_type.lower():
            # Try both reclass and original versions
            patterns = [
                f"*_{clean_place}_*{layer_type}_reclass.tif",  # Reclassified (preferred)
                f"*_{clean_place}_*{layer_type}.tif",         # Original
                f"*{clean_place}*{layer_type}_reclass.tif",   # Alternative format
                f"*{clean_place}*{layer_type}.tif"            # Alternative format
            ]
        else:
            # Already includes reclass
            patterns = [
                f"*_{clean_place}_*{layer_type}.tif",
                f"*{clean_place}*{layer_type}.tif"
            ]
    else:
        # Return any layer for this place - useful for getting the most recent
        patterns = [f"*_{clean_place}_*.tif", f"*{clean_place}*.tif"]
    
    print(f"TOOL: Direct place lookup for '{place_name}' (layer: {layer_type})")
    
    # Try each pattern
    for pattern in patterns:
        matches = glob.glob(os.path.join(output_dir, pattern))
        print(f"TOOL: Pattern '{pattern}' -> {len(matches)} matches")
        if matches:
            # Return most recent file
            found_file = max(matches, key=os.path.getmtime)
            print(f"TOOL: Found direct match: {os.path.basename(found_file)}")
            return found_file
    
    print(f"TOOL: No direct match found for place '{place_name}'")
    return None

# Configure AWS for public data access (Copernicus DEM)
os.environ['AWS_NO_SIGN_REQUEST'] = 'YES'
# Additional rasterio environment configuration for S3 access
os.environ['GDAL_DISABLE_READDIR_ON_OPEN'] = 'EMPTY_DIR'
os.environ['CPL_VSIL_CURL_ALLOWED_EXTENSIONS'] = '.tif,.tiff'

# Initialize WhiteboxTools once
wbt = whitebox.WhiteboxTools()

# --- Helper Functions ---
def get_output_filepath(filename: str, thread_id: str = None, place_name: str = None) -> str:
    """Constructs a full, absolute path in the Django MEDIA_ROOT with optional thread/place prefixing."""
    output_dir = settings.MEDIA_ROOT
    os.makedirs(output_dir, exist_ok=True)
    
    # Use provided parameters or fall back to thread context
    if not thread_id or not place_name:
        context_thread_id, context_place_name = get_workflow_context()
        thread_id = thread_id or context_thread_id
        place_name = place_name or context_place_name
    
    # If thread_id and place_name are available, prefix the filename for better organization
    if thread_id and place_name:
        # Sanitize place name for filename usage
        clean_place = place_name.replace(' ', '_').replace(',', '').replace("'", "")
        prefixed_filename = f"{thread_id}_{clean_place}_{filename}"
        return os.path.join(output_dir, prefixed_filename)
    
    return os.path.join(output_dir, filename)

def get_bbox_from_place(place_name: str):
    """Geocodes a place name to get its bounding box."""
    print(f"TOOL: Attempting to geocode '{place_name}'...")
    gdf = ox.geocode_to_gdf(place_name)

    if gdf.empty:
        # This provides a clear error if the geocoder returns nothing.
        raise ValueError(f"Geocoding failed for '{place_name}'. The place was not found.")
    
    bounds = gdf.total_bounds
    print(f"TOOL: Geocoded '{place_name}' to bounding box: {bounds}")
    return bounds

def geocode_place(place_name: str):
    """Geocode a place name to get latitude and longitude."""
    gdf = ox.geocode_to_gdf(place_name)
    centroid = gdf.geometry.iloc[0].centroid
    return centroid.y, centroid.x  # lat, lon

# --- NEW: SPATIAL VALIDATION & PRE-PROCESSING HELPERS ---

def _validate_and_read_vector(vector_path: str) -> gpd.GeoDataFrame:
    """Centralized function to validate and read a vector file."""
    if not os.path.exists(vector_path):
        raise FileNotFoundError(f"Input file not found at '{vector_path}'.")
    
    # Check if file is empty
    if os.path.getsize(vector_path) == 0:
        raise ValueError(f"Input file '{vector_path}' is empty.")
    
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            # Add more specific error handling for different file formats
            gdf = gpd.read_file(vector_path)
    except Exception as e:
        # More detailed error information
        raise ValueError(f"Could not read vector file '{os.path.basename(vector_path)}': {str(e)}. "
                        f"File size: {os.path.getsize(vector_path)} bytes. "
                        f"File extension: {os.path.splitext(vector_path)[1]}")
    
    if gdf.empty:
        raise ValueError("The input vector file is empty and contains no features.")
    
    # Handle CRS more gracefully
    if gdf.crs is None:
        # For GeoJSON files, try to assign a default CRS
        if vector_path.lower().endswith('.geojson'):
            print(f"WARNING: GeoJSON file '{os.path.basename(vector_path)}' missing explicit CRS. Assuming EPSG:4326.")
            gdf.crs = "EPSG:4326"
        else:
            raise ValueError(f"The input vector file '{os.path.basename(vector_path)}' is missing CRS (projection) information.")
    
    # 🔑 Fix multipart geometry bug
    gdf["geometry"] = gdf["geometry"].buffer(0)  # repair invalids
    gdf = gdf.explode(index_parts=False, ignore_index=True)  # split multiparts
    
    print(f"TOOL: Successfully read vector file with {len(gdf)} features, CRS: {gdf.crs}")
    return gdf


def _validate_and_read_raster(raster_path: str):
    """Centralized function to validate and read a raster file."""
    if not os.path.exists(raster_path):
        raise FileNotFoundError(f"Input file not found at '{raster_path}'.")
    
    # Return rasterio.open for use in with statements
    return rasterio.open(raster_path)

def _reproject_gdf_to_match(source_gdf: gpd.GeoDataFrame, target_crs_source_path: str) -> gpd.GeoDataFrame:
    """Helper to reproject a GeoDataFrame to match a target file's CRS."""
    with _validate_and_read_raster(target_crs_source_path) if target_crs_source_path.endswith(('.tif', '.tiff')) else warnings.catch_warnings():
        target_gdf = gpd.read_file(target_crs_source_path) if target_crs_source_path.endswith(('.shp', '.geojson', '.gpkg')) else None
        target_crs = rasterio.open(target_crs_source_path).crs if target_gdf is None else target_gdf.crs

    if source_gdf.crs != target_crs:
        print(f"CRS MISMATCH: Reprojecting source data to target CRS {target_crs.to_string()}.")
        return source_gdf.to_crs(target_crs)
    return source_gdf

# --- 1. DATA ACQUISITION TOOLS ---

def acquire_osm_data(place_name: str, tags: dict) -> str:
    """Acquires vector data from OpenStreetMap. Returns absolute filepath."""
    print(f"TOOL: Acquiring OSM data for '{place_name}' with tags: {tags}")
    try:
        gdf = ox.features_from_place(place_name, tags)
        if gdf.empty:
            return f"Error: No features found for tags {tags} in {place_name}."
        
        feature_name = list(tags.values())[0] if tags else 'features'
        filename = f"osm_{feature_name}.geojson"
        filepath = get_output_filepath(filename)  # Will use thread context automatically
        gdf.to_file(filepath, driver='GeoJSON')
        return filepath
    except Exception as e:
        return f"Error during OSM data acquisition: {e}"

def acquire_dem_data(place_name: str) -> str:
    """Acquire a DEM raster for the given place name using Copernicus DEM."""

    try:
        # Geocode place to bounding box
        print(f"TOOL: Attempting to geocode '{place_name}'...")
        bounds = list(get_bbox_from_place(place_name))
        print(f"TOOL: Geocoded '{place_name}' to bounding box: {bounds}")

        # Buffer if too small
        min_deg = 0.1  # ~10 km buffer in degrees
        if (bounds[2] - bounds[0]) < min_deg:
            bounds[0] -= min_deg / 2
            bounds[2] += min_deg / 2
        if (bounds[3] - bounds[1]) < min_deg:
            bounds[1] -= min_deg / 2
            bounds[3] += min_deg / 2
        print(f"TOOL: Expanded bounding box (if needed): {bounds}")

        # Query Copernicus DEM
        catalog = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
        search = catalog.search(collections=["cop-dem-glo-30"], bbox=bounds)
        items = list(search.items())
        if not items:
            return f"Error: No DEM data found for {place_name}."

        stack = stackstac.stack(
            items,
            assets=["data"],
            bounds_latlon=bounds,
            resolution=30,
            epsg=4326
        )
        dem = stack.mean(dim="time").compute()
        print(f"TOOL: Created DEM raster with final shape: {dem.shape}")

        # Guard against tiny DEMs
        if dem.shape[1] < 50 or dem.shape[2] < 50:
            print(f"WARNING: DEM for {place_name} is very small ({dem.shape}). Consider expanding bounds further.")

        # Write output
        filepath = get_output_filepath("dem.tif")
        dem.rio.write_crs("EPSG:4326", inplace=True)
        dem.rio.to_raster(filepath)
        return filepath

    except Exception as e:
        return f"Error in acquire_dem_data: {e}"


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
        gdf = _validate_and_read_vector(vector_path)
        
        print(f"TOOL: Original filter expression: {expression}")
        print(f"Available columns: {list(gdf.columns)}")
        
        # Check if the expression is trying to filter by a boolean condition
        # Handle common issues with pandas queries
        if "==" in expression or "!=" in expression or ">" in expression or "<" in expression:
            # This looks like a proper comparison expression
            fixed_expression = expression.replace(" = ", " == ")
            fixed_expression = fixed_expression.replace("'", '"')
        else:
            # Handle cases where expression might be just a column name or boolean value
            # Try to interpret as a boolean column filter
            if expression.lower() in ['true', 'false']:
                return f"Error: Boolean literal '{expression}' cannot be used directly. Please specify a column condition like 'column_name == True'."
            
            # Check if it's a column name that contains boolean values
            if expression in gdf.columns:
                # If it's a boolean column, filter for True values
                if gdf[expression].dtype == 'bool':
                    fixed_expression = f"{expression} == True"
                else:
                    return f"Error: Column '{expression}' is not boolean. Please specify a condition like '{expression} > 0'."
            else:
                # Try the original expression but with standard fixes
                fixed_expression = expression.replace(" = ", " == ")
                fixed_expression = fixed_expression.replace("'", '"')
        
        print(f"TOOL: Applying filter expression: {fixed_expression}")
        
        try:
            filtered_gdf = gdf.query(fixed_expression)
        except Exception as query_error:
            # If query fails, try alternative approaches
            print(f"Query failed: {query_error}. Trying alternative filtering...")
            
            # Try to parse simple conditions manually
            if " == " in fixed_expression:
                parts = fixed_expression.split(" == ")
                if len(parts) == 2:
                    col_name = parts[0].strip().strip('"').strip("'")  # Remove quotes from column name
                    value = parts[1].strip().strip('"').strip("'")     # Remove quotes from value
                    
                    print(f"Parsed: column='{col_name}', value='{value}'")
                    
                    if col_name in gdf.columns:
                        # Check for null/None values in the column to avoid comparison issues
                        if gdf[col_name].isna().all():
                            return f"Warning: Column '{col_name}' contains only null values. Cannot filter."
                        
                        # Filter out null values first
                        valid_data = gdf[gdf[col_name].notna()]
                        
                        if value.lower() == 'true':
                            filtered_gdf = valid_data[valid_data[col_name] == True]
                        elif value.lower() == 'false':
                            filtered_gdf = valid_data[valid_data[col_name] == False]
                        elif value.lower() == 'null' or value.lower() == 'none':
                            filtered_gdf = gdf[gdf[col_name].isna()]
                        else:
                            # Try to convert value to appropriate type
                            try:
                                if value.replace('.', '').replace('-', '').isdigit():
                                    value = float(value) if '.' in value else int(value)
                                filtered_gdf = valid_data[valid_data[col_name] == value]
                            except:
                                # String comparison
                                filtered_gdf = valid_data[valid_data[col_name] == value]
                    else:
                        available_cols = [col for col in gdf.columns if col.lower() == col_name.lower()]
                        if available_cols:
                            suggestion = available_cols[0]
                            return f"Error: Column '{col_name}' not found. Did you mean '{suggestion}'? Available columns: {list(gdf.columns)}"
                        else:
                            return f"Error: Column '{col_name}' not found in the data. Available columns: {list(gdf.columns)}"
                else:
                    raise query_error
            else:
                raise query_error
        
        if filtered_gdf.empty:
            return f"Warning: No features remained after applying filter '{fixed_expression}'. The result is an empty layer."
        
        filepath = vector_path.replace('.geojson', '_filtered.geojson').replace('.shp', '_filtered.shp')
        filtered_gdf.to_file(filepath)
        print(f"TOOL: Filtered {len(gdf)} features down to {len(filtered_gdf)} features.")
        return filepath
    except Exception as e:
        return f"Error during vector filtering: {e}"

def perform_buffer(vector_filepath: str, distance_meters: float) -> str:
    """Creates a buffer zone around vector features. Returns new absolute filepath."""
    try:
        gdf = _validate_and_read_vector(vector_filepath)
        # Estimate UTM CRS for accurate meter-based buffering
        utm_crs = gdf.estimate_utm_crs()
        if utm_crs is None:
            return "Error: Could not determine a suitable UTM projection for buffering. The data may be in an unusual location."
        
        gdf_proj = gdf.to_crs(utm_crs)
        gdf_proj['geometry'] = gdf_proj.buffer(distance_meters)
        gdf_buffered = gdf_proj.to_crs(gdf.crs)
        
        filepath = vector_filepath.replace(".geojson", f"_buffer_{distance_meters}m.geojson").replace(".shp", f"_buffer_{distance_meters}m.shp")
        gdf_buffered.to_file(filepath)
        return filepath
    except Exception as e:
        return f"Error during buffer analysis: {e}"

# --- 3. RASTER ANALYSIS TOOLS ---

def calculate_slope(dem_path: str) -> str:
    """Calculates slope from a DEM using WhiteboxTools. Returns filepath of slope raster."""
    try:
        # Validate and potentially fix CRS issues
        with rasterio.open(dem_path) as src:
            if src.crs is None:
                print(f"WARNING: DEM file '{os.path.basename(dem_path)}' missing CRS. Attempting to fix by setting EPSG:4326...")
                # Create a temporary file with CRS properly set
                temp_dem_path = dem_path.replace('.tif', '_with_crs.tif')
                
                # Read the data and set CRS
                with rasterio.open(dem_path) as src_no_crs:
                    data = src_no_crs.read()
                    profile = src_no_crs.profile.copy()
                    profile.update(crs='EPSG:4326')
                
                # Write with CRS
                with rasterio.open(temp_dem_path, 'w', **profile) as dst:
                    dst.write(data)
                
                # Use the temporary file for slope calculation
                dem_path = temp_dem_path
        
        _validate_and_read_raster(dem_path) # Just validates the raster
        filepath = dem_path.replace('.tif', '_slope.tif')
        wbt.slope(dem=dem_path, output=filepath)
        return filepath
    except Exception as e:
        return f"Error during slope calculation: {e}"

def reclassify_raster(raster_path: str, reclass_values: list) -> str:
    """Reclassifies a raster based on a list of ranges. E.g., [[0, 10, 1], [10, 20, 0]]. Returns new filepath."""
    try:
        _validate_and_read_raster(raster_path)
        filepath = raster_path.replace('.tif', '_reclass.tif')
        # WhiteboxTools reclass format: "new_value;start;end"
        reclass_items = []
        for row in reclass_values:
            if len(row) >= 3:
                low, high, new = row[0], row[1], row[2]
                reclass_items.append(f"{new};{low};{high}")
        
        if not reclass_items:
            return "Error: Reclassification values were provided in an invalid format."
            
        reclass_str = ";".join(reclass_items)
        wbt.reclass(i=raster_path, output=filepath, reclass_vals=reclass_str)
        return filepath
    except Exception as e:
        return f"Error during raster reclassification: {e}"

def calculate_proximity_raster(vector_path: str, reference_raster_path: str) -> str:
    """Creates a raster showing Euclidean distance to vector features. Returns distance raster filepath."""
    try:
        if not os.path.exists(reference_raster_path):
            return f"Error: Reference raster not found at {reference_raster_path}"
        if not reference_raster_path.lower().endswith(('.tif', '.tiff')):
            return f"Error: Reference raster must be a .tif file, got {os.path.basename(reference_raster_path)}"
        
        print(f"TOOL: Starting proximity calculation")
        print(f"TOOL: Vector path: {vector_path}")
        print(f"TOOL: Reference raster path: {reference_raster_path}")
        
        # Validate inputs exist
        if not os.path.exists(vector_path):
            return f"Error: Vector file not found: {vector_path}"
            
        print(f"TOOL: Vector file size: {os.path.getsize(vector_path)} bytes")
        
        # Read vector with improved error handling
        gdf = _validate_and_read_vector(vector_path)
        print(f"TOOL: Successfully loaded vector with {len(gdf)} features")
        
        with _validate_and_read_raster(reference_raster_path) as ref:
            meta = ref.meta.copy()
            print(f"TOOL: Reference raster - Shape: {ref.shape}, CRS: {ref.crs}")
            
            # Reproject vector to match reference raster CRS
            print(f"TOOL: Reprojecting vector from {gdf.crs} to {ref.crs}")
            gdf_proj = gdf.to_crs(ref.crs)
            
            # Create the rasterization mask
            print(f"TOOL: Creating rasterization mask...")
            mask = rasterize(
                shapes=[geom for geom in gdf_proj.geometry], 
                out_shape=(meta['height'], meta['width']), 
                transform=meta['transform'], 
                fill=0, 
                all_touched=True, 
                dtype=np.uint8
            )
            
            print(f"TOOL: Calculating proximity...")
            proximity_data = distance_transform_edt(mask == 0)
            
            # Extract feature type from vector filename for better naming
            vector_basename = os.path.basename(vector_path).split('.')[0]
            feature_parts = vector_basename.split('_')
            if len(feature_parts) >= 3:
                feature_name = '_'.join(feature_parts[2:])  # Skip thread_id and place parts
            else:
                feature_name = vector_basename
            
            filename = f"proximity_{feature_name}.tif"
            filepath = get_output_filepath(filename)
            
            print(f"TOOL: Writing proximity raster to: {filepath}")
            meta.update(dtype='float32')
            
            with rasterio.open(filepath, 'w', **meta) as dst:
                dst.write(proximity_data.astype(np.float32), 1)
            
            print(f"TOOL: Proximity calculation complete: {filepath}")
            return filepath
            
    except Exception as e:
        print(f"TOOL: Error in proximity calculation: {str(e)}")
        return f"Error during proximity calculation: {e}"


# --- 4. NEW SPATIAL UTILITY TOOLS ---

def clip_data(data_to_clip_path: str, clip_boundary_path: str) -> str:
    """Clips a vector or raster file to the extent of a boundary polygon. Returns new filepath."""
    try:
        clip_gdf = _validate_and_read_vector(clip_boundary_path)
        
        geom_types = clip_gdf.geometry.geom_type.unique()
        if not any(g_type in ['Polygon', 'MultiPolygon'] for g_type in geom_types):
            return f"Error: Clipping boundary file must contain Polygon geometries, but found only: {list(geom_types)}"

        if data_to_clip_path.endswith(('.geojson', '.shp', '.gpkg')):
            data_gdf = _validate_and_read_vector(data_to_clip_path)
            # Reproject data to match clipping boundary's CRS
            data_gdf_proj = data_gdf.to_crs(clip_gdf.crs)
            clipped_gdf = gpd.clip(data_gdf_proj, clip_gdf)
            
            if clipped_gdf.empty:
                return "Warning: The clip operation resulted in an empty layer. The layers may not overlap."

            filepath = data_to_clip_path.replace('.', '_clipped.')
            clipped_gdf.to_file(filepath)
            return filepath
        
        elif data_to_clip_path.endswith(('.tif', '.tiff')):
            with _validate_and_read_raster(data_to_clip_path) as src:
                # Reproject clipping boundary to match raster's CRS
                clip_gdf_proj = clip_gdf.to_crs(src.crs)
                out_image, out_transform = mask(src, clip_gdf_proj.geometry, crop=True)
                out_meta = src.meta.copy()
            
            out_meta.update({"driver": "GTiff", "height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform})
            filepath = data_to_clip_path.replace('.', '_clipped.')
            with rasterio.open(filepath, "w", **out_meta) as dest:
                dest.write(out_image)
            return filepath
        else:
            return f"Error: Unsupported file type for clipping: {os.path.basename(data_to_clip_path)}"
    except Exception as e:
        return f"Error during clipping: {e}"

def rasterize_vector(vector_path: str, reference_raster_path: str, burn_value: float = 1) -> str:
    """Converts a vector file into a raster grid matching a reference raster. Returns new filepath."""
    try:
        if not os.path.exists(reference_raster_path):
            return f"Error: Reference raster not found at {reference_raster_path}"
        if not reference_raster_path.lower().endswith(('.tif', '.tiff')):
            return f"Error: Reference raster must be a .tif file, got {os.path.basename(reference_raster_path)}"

        gdf = _validate_and_read_vector(vector_path)
        with _validate_and_read_raster(reference_raster_path) as ref:
            meta = ref.meta.copy()
            gdf_proj = gdf.to_crs(ref.crs)

        shapes = ((geom, burn_value) for geom in gdf_proj.geometry)
        filepath = get_output_filepath(f"rasterized_{os.path.basename(vector_path).split('.')[0]}.tif")
        
        with rasterio.open(filepath, 'w+', **meta) as out:
            out_arr = out.read(1)
            rasterized_arr = rasterize(shapes=shapes, fill=0, out=out_arr, transform=out.transform)
            out.write(rasterized_arr, 1)
        return filepath
    except Exception as e:
        return f"Error during rasterization: {e}"

# --- 5. SYNTHESIS & PUBLISHING TOOLS ---

def perform_weighted_overlay(layer_weights: List[Dict]) -> str:
    """
    Performs a weighted sum of multiple rasters. The input MUST be a list of objects, 
    each specifying a raster_path and its numerical weight.
    Example: list of dicts with raster_path and weight keys
    
    Args:
        layer_weights: List of dictionaries with raster_path and weight keys
    
    Returns:
        Path to the final weighted overlay raster
    """
    try:
        if not layer_weights:
            return "Error: Input 'layer_weights' list cannot be empty for weighted overlay."

        print(f"TOOL: Performing weighted overlay with {len(layer_weights)} layers")
        
        # Validate and process each layer
        validated_layers = []
        for i, layer in enumerate(layer_weights):
            if not isinstance(layer, dict):
                return f"Error: Layer {i+1} must be a dictionary with raster_path and weight keys."
            
            if 'raster_path' not in layer:
                return f"Error: Layer {i+1} missing required raster_path key."
            if 'weight' not in layer:
                return f"Error: Layer {i+1} missing required weight key."
            
            raster_path = layer['raster_path']
            weight = layer['weight']
            
            # Validate weight is numeric
            try:
                weight = float(weight)
                if weight < 0:
                    return f"Error: Weight for layer {i+1} must be non-negative, got {weight}"
            except (ValueError, TypeError):
                return f"Error: Weight for layer {i+1} must be a number, got '{weight}' ({type(weight)})"
            
            # Validate raster path exists
            if not os.path.exists(raster_path):
                return f"Error: Raster file not found: {raster_path}"
            
            validated_layers.append({'raster_path': raster_path, 'weight': weight})
            print(f"TOOL: Layer {i+1}: {os.path.basename(raster_path)} (weight: {weight})")

        # Read base raster metadata and initialize final raster
        base_raster_path = validated_layers[0]['raster_path']
        try:
            with rasterio.open(base_raster_path) as src:
                final_raster = np.zeros(src.shape, dtype=np.float32)
                meta = src.meta.copy()
                target_crs = src.crs
                target_shape = src.shape
                print(f"TOOL: Base raster shape: {src.shape}, CRS: {target_crs}")
        except Exception as e:
            return f"Error reading base raster '{os.path.basename(base_raster_path)}': {e}"

        # Process each layer
        for layer in validated_layers:
            raster_path = layer['raster_path']
            weight = layer['weight']
            
            try:
                with rasterio.open(raster_path) as lyr_src:
                    if lyr_src.crs != target_crs:
                        print(f"WARNING: CRS mismatch for {os.path.basename(raster_path)}. Expected {target_crs}, got {lyr_src.crs}")
                        return f"Error: CRS mismatch in weighted overlay. Layer '{os.path.basename(raster_path)}' does not match base layer CRS."
                    
                    layer_data = lyr_src.read(1)
                    if layer_data.shape != target_shape:
                        return f"Error: Shape mismatch in weighted overlay. Layer '{os.path.basename(raster_path)}' shape {layer_data.shape} does not match base shape {target_shape}."
                    
                    # Add weighted layer to final result
                    layer_data = layer_data.astype(np.float32)
                    final_raster += layer_data * weight
                    print(f"TOOL: Added layer {os.path.basename(raster_path)} (weight: {weight})")
            except Exception as e:
                return f"Error processing layer '{os.path.basename(raster_path)}': {e}"
                
        # Write the final result
        filepath = get_output_filepath("suitability_map.tif")  # Will use thread context automatically
        meta.update(dtype='float32')
        try:
            with rasterio.open(filepath, 'w', **meta) as dst:
                dst.write(final_raster, 1)
            print(f"TOOL: Weighted overlay complete. Output saved to: {filepath}")
            return filepath
        except Exception as e:
            return f"Error writing output file '{filepath}': {e}"
    except Exception as e:
        return f"Error during weighted overlay: {e}"

def compare_places_analysis(places: list, layer_type: str, comparison_method: str = "difference") -> str:
    """
    Compares the same layer type across multiple places.
    
    Args:
        places: List of place names to compare (e.g., ["Chennai", "Mumbai", "Delhi"])
        layer_type: Type of layer to compare (e.g., "slope", "proximity", "dem")
        comparison_method: How to compare - "difference", "ratio", "overlay"
    
    Returns:
        Path to comparison result raster
    """
    try:
        print(f"TOOL: Comparing {layer_type} layers across places: {places}")
        
        output_dir = settings.MEDIA_ROOT
        
        # Find layer files for each place using direct identification
        place_files = {}
        for place in places:
            # Try direct lookup first (simpler and faster for comparison workflows)
            file_path = find_layer_by_place_direct(place, layer_type)
            if not file_path:
                # Fallback to pattern-based lookup
                file_path = find_layer_by_place_and_type(place, layer_type, output_dir)
            
            if file_path:
                place_files[place] = file_path
                print(f"TOOL: Found {layer_type} for {place}: {os.path.basename(file_path)}")
            else:
                return f"Error: Could not find {layer_type} layer for place '{place}'"
        
        if len(place_files) < 2:
            return f"Error: Need at least 2 places for comparison, found {len(place_files)}"
        
        # Load the rasters
        raster_data = {}
        base_meta = None
        
        for place, file_path in place_files.items():
            with _validate_and_read_raster(file_path) as src:
                raster_data[place] = src.read(1).astype(np.float32)
                if base_meta is None:
                    base_meta = src.meta.copy()
                    base_shape = raster_data[place].shape
                    base_crs = src.crs
                else:
                    # Check compatibility
                    if raster_data[place].shape != base_shape:
                        print(f"WARNING: Shape mismatch for {place}. Expected {base_shape}, got {raster_data[place].shape}")
                    if src.crs != base_crs:
                        print(f"WARNING: CRS mismatch for {place}. Expected {base_crs}, got {src.crs}")
        
        # Perform comparison based on method
        if comparison_method == "difference":
            # Calculate difference between first two places
            place_names = list(place_files.keys())
            result_data = raster_data[place_names[0]] - raster_data[place_names[1]]
            comparison_name = f"{place_names[0]}_minus_{place_names[1]}"
            
        elif comparison_method == "ratio":
            # Calculate ratio between first two places
            place_names = list(place_files.keys())
            denominator = raster_data[place_names[1]]
            # Avoid division by zero
            denominator[denominator == 0] = 0.001
            result_data = raster_data[place_names[0]] / denominator
            comparison_name = f"{place_names[0]}_ratio_{place_names[1]}"
            
        elif comparison_method == "overlay":
            # Create a multi-band overlay showing all places
            place_names = list(place_files.keys())
            # For simplicity, average all rasters
            result_data = np.mean([raster_data[place] for place in place_names], axis=0)
            comparison_name = f"{'_'.join(place_names)}_overlay"
            
        else:
            return f"Error: Unknown comparison method '{comparison_method}'. Use 'difference', 'ratio', or 'overlay'."
        
        # Save result
        filename = f"comparison_{layer_type}_{comparison_name}.tif"
        filepath = get_output_filepath(filename)
        
        base_meta.update(dtype='float32')
        with rasterio.open(filepath, 'w', **base_meta) as dst:
            dst.write(result_data.astype(np.float32), 1)
        
        print(f"TOOL: Multi-place comparison complete. Output saved to: {filepath}")
        return filepath
        
    except Exception as e:
        return f"Error during multi-place comparison: {e}"

def perform_sequential_comparison_workflow(places: list, layer_types: list, weights: dict = None) -> str:
    """
    DEPRECATED: This tool is being phased out in favor of explicit agent-driven workflows.
    The agent should create explicit, sequential plans for comparisons instead of using this "magical" tool.
    
    Optimized tool for comparison workflows that processes places sequentially.
    Takes advantage of the fact that each place is processed independently and completely.
    
    Args:
        places: List of places to compare (e.g., ["Chennai", "Mumbai"])
        layer_types: List of layer types to include (e.g., ["slope_reclass", "proximity_reclass"])
        weights: Optional weights for weighted overlay {layer_type: weight}
    
    Returns:
        Path to final comparison result
    """
    print("WARNING: perform_sequential_comparison_workflow is deprecated. Agent should create explicit workflows instead.")
    
    try:
        print(f"TOOL: Sequential comparison workflow for places: {places}, layers: {layer_types}")
        
        if len(places) < 2:
            return "Error: Need at least 2 places for comparison"
        
        # Build layer_weights dictionary for weighted overlay using direct place references
        if weights is None:
            # Default equal weights
            weight_per_layer = 1.0 / len(layer_types) if layer_types else 1.0
            weights = {layer: weight_per_layer for layer in layer_types}
        
        # Build layers list for new perform_weighted_overlay format
        layers = []
        for place in places:
            place_weight = 1.0 / len(places)  # Equal weight per place
            for layer_type in layer_types:
                # Try to find the layer file using the direct lookup
                file_path = find_layer_by_place_direct(place, layer_type)
                if file_path:
                    layer_weight = weights.get(layer_type, 0) * place_weight
                    if layer_weight > 0:
                        layers.append({
                            'raster_path': file_path,
                            'weight': layer_weight
                        })
                else:
                    return f"Error: Could not find {layer_type} layer for place '{place}'"
        
        print(f"TOOL: Generated layers list for comparison: {len(layers)} layers")
        
        # Use the new weighted overlay function format
        return perform_weighted_overlay(layers)
        
    except Exception as e:
        return f"Error during sequential comparison workflow: {e}"

