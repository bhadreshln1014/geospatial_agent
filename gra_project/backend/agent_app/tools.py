import geopandas as gpd
import osmnx as ox
import requests
import rasterio
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject, Resampling
import numpy as np
import os
import json
from shapely.geometry import box
import pystac_client
import stackstac
from scipy.ndimage import distance_transform_edt

# --- Helper Functions ---
def get_output_dir():
    """Get the correct output directory path, Django-aware."""
    try:
        from django.conf import settings
        if hasattr(settings, 'MEDIA_ROOT'):
            return settings.MEDIA_ROOT
    except:
        pass
    # Fallback to relative path
    return 'output'

def ensure_output_dir():
    """Ensure the output directory exists."""
    output_dir = get_output_dir()
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    return output_dir

def get_bbox_from_place(place_name: str):
    """Geocodes a place name to get its bounding box and CRS."""
    gdf = ox.geocode_to_gdf(place_name)
    return gdf.total_bounds, gdf.crs

# --- Data Acquisition Tools (FUN-003, FUN-004, FUN-005) ---

def acquire_vector_data(query: str) -> str:
    """
    Acquires vector data (points, lines, polygons) from OpenStreetMap for a specified place and saves it as a GeoJSON file.
    Returns the filepath of the saved data. 
    Query should contain place name and feature type, e.g., 'restaurants in Palo Alto' or 'parks in Davis'.
    """
    print(f"TOOL: Acquiring vector data for query: '{query}'")
    try:
        # Parse the query to extract place and feature type
        query_lower = query.lower()
        
        # Common feature mappings
        feature_mappings = {
            'restaurant': {'amenity': 'restaurant'},
            'restaurants': {'amenity': 'restaurant'},
            'bar': {'amenity': 'bar'},
            'bars': {'amenity': 'bar'},
            'school': {'amenity': 'school'},
            'schools': {'amenity': 'school'},
            'park': {'leisure': 'park'},
            'parks': {'leisure': 'park'},
            'building': {'building': True},
            'buildings': {'building': True},
            'residential': {'building': 'residential'},
            'industrial': {'landuse': 'industrial'},
            'hospital': {'amenity': 'hospital'},
            'hospitals': {'amenity': 'hospital'},
        }
        
        # Find the feature type in the query
        tags_dict = None
        feature_name = None
        for feature, tags in feature_mappings.items():
            if feature in query_lower:
                tags_dict = tags
                feature_name = feature
                break
        
        if not tags_dict:
            # Default to buildings if no specific feature found
            tags_dict = {'building': True}
            feature_name = 'building'
        
        # Extract place name (assume it comes after "in")
        if ' in ' in query_lower:
            place_name = query.split(' in ')[-1].strip()
        else:
            # Fallback: use the whole query as place name
            place_name = query.strip()
        
        print(f"TOOL: Parsed place: '{place_name}', tags: {tags_dict}")
        gdf = ox.features_from_place(place_name, tags_dict)
        if gdf.empty:
            return f"Error: No features found for tags {tags_dict} in {place_name}."
        
        # Use Django-aware output directory
        output_dir = ensure_output_dir()
        filename = f"{place_name.replace(' ', '_')}_{feature_name}.geojson"
        filepath = os.path.join(output_dir, filename)
        gdf.to_file(filepath, driver='GeoJSON')
        print(f"TOOL: Saved vector data to {filepath}")
        return filename  # Return just filename for frontend compatibility
    except Exception as e:
        return f"Error during vector data acquisition: {e}"

def acquire_elevation_data(place_name: str) -> str:
    """
    Acquires Digital Elevation Model (DEM) data for a given place and saves it as a GeoTIFF.
    Returns the filepath of the saved raster.
    """
    print(f"TOOL: Acquiring elevation data for '{place_name}'")
    try:
        bounds, crs = get_bbox_from_place(place_name)
        
        # Create a simple synthetic DEM for demonstration purposes
        # In a real implementation, you might use NASA SRTM or other sources
        print("INFO: Creating synthetic elevation data for demonstration")
        
        # Create a simple elevation grid (higher elevation in center, lower at edges)
        import numpy as np
        from rasterio.transform import from_bounds
        
        # Grid size
        height, width = 100, 100
        
        # Create coordinate arrays
        x = np.linspace(0, 1, width)
        y = np.linspace(0, 1, height)
        X, Y = np.meshgrid(x, y)
        
        # Create a simple synthetic elevation surface (bell curve)
        center_x, center_y = 0.5, 0.5
        elevation = 100 * np.exp(-((X - center_x)**2 + (Y - center_y)**2) * 10)
        elevation = elevation + np.random.normal(0, 5, elevation.shape)  # Add some noise
        
        # Create transform
        transform = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], width, height)
        
        # Use Django-aware output directory
        output_dir = ensure_output_dir()
        filename = f"{place_name.replace(' ', '_')}_elevation.tif"
        filepath = os.path.join(output_dir, filename)
        
        # Save as GeoTIFF
        with rasterio.open(
            filepath, 'w',
            driver='GTiff',
            height=height, width=width,
            count=1, dtype=elevation.dtype,
            crs='EPSG:4326',
            transform=transform
        ) as dst:
            dst.write(elevation, 1)
        
        print(f"TOOL: Saved synthetic elevation data to {filepath}")
        return filename  # Return just filename for frontend compatibility
    except Exception as e:
        return f"Error during elevation data acquisition: {e}"



def perform_buffer_analysis(vector_filepath: str, distance_meters: float) -> str:
    """
    Creates a buffer zone around vector features. 'vector_filepath' must be a GeoJSON file.
    'distance_meters' is the buffer distance. Returns the filepath of the buffered GeoJSON.
    """
    print(f"TOOL: Performing buffer of {distance_meters}m on {vector_filepath}")
    gdf = gpd.read_file(vector_filepath)
    gdf_proj = gdf.to_crs(gdf.estimate_utm_crs())
    gdf_proj['geometry'] = gdf_proj.buffer(distance_meters)
    gdf_buffered = gdf_proj.to_crs(gdf.crs)
    
    # Create output in the Django output directory
    output_dir = ensure_output_dir()
    input_basename = os.path.basename(vector_filepath)
    output_filename = input_basename.replace(".geojson", "_buffered.geojson")
    output_filepath = os.path.join(output_dir, output_filename)
    gdf_buffered.to_file(output_filepath, driver='GeoJSON')
    print(f"TOOL: Saved buffered data to {output_filepath}")
    return output_filename  # Return just filename for frontend compatibility

def acquire_generic_raster_data(description: str) -> str:
    """
    Acquire generic raster data (like temperature, precipitation, etc.).
    Currently generates synthetic data for demonstration purposes.
    
    Args:
        description: Natural language description of the raster data needed
        
    Returns:
        str: Path to the acquired raster file
    """
    # Generate synthetic raster data based on description
    # This is a placeholder - in production, this would connect to real data sources
    
    width, height = 100, 100
    
    # Create synthetic data based on description keywords
    if any(word in description.lower() for word in ['temperature', 'temp', 'heat']):
        # Temperature-like data (15-35°C range)
        data = np.random.uniform(15, 35, (height, width))
        data_type = 'temperature'
    elif any(word in description.lower() for word in ['precipitation', 'rainfall', 'rain']):
        # Precipitation-like data (0-200mm range)
        data = np.random.uniform(0, 200, (height, width))
        data_type = 'precipitation'
    elif any(word in description.lower() for word in ['population', 'density']):
        # Population density-like data
        data = np.random.uniform(0, 5000, (height, width))
        data_type = 'population_density'
    else:
        # Generic normalized data (0-1 range)
        data = np.random.uniform(0, 1, (height, width))
        data_type = 'generic_raster'
    
    # Create output filename
    clean_desc = "_".join(description.lower().split()[:3])  # First 3 words
    output_dir = ensure_output_dir()
    output_path = os.path.join(output_dir, f"{clean_desc}_{data_type}.tif")
    
    # Default geospatial metadata (would be location-specific in production)
    transform = rasterio.transform.from_bounds(-122.5, 37.2, -122.0, 37.7, width, height)
    
    meta = {
        'driver': 'GTiff',
        'dtype': 'float32',
        'width': width,
        'height': height,
        'count': 1,
        'crs': 'EPSG:4326',
        'transform': transform,
        'nodata': None
    }
    
    # Save the raster
    with rasterio.open(output_path, 'w', **meta) as dst:
        dst.write(data.astype('float32'), 1)
    
    print(f"✅ Generic raster data created: {output_path}")
    return os.path.basename(output_path)  # Return just filename for frontend compatibility


def perform_mca(config_string: str) -> str:
    """
    Performs multi-criteria analysis (MCA) on geospatial layers.
    
    Args:
        config_string: JSON configuration with 'files' (list of paths) and 'weights' (list of floats)
        
    Returns:
        str: Path to the saved MCA raster file
    """
    config = json.loads(config_string)
    layer_paths = config['files']  # Changed from 'layer_paths' to 'files'
    weights = config['weights']
    
    # Validate inputs
    if len(layer_paths) != len(weights) or len(layer_paths) == 0:
        raise ValueError("Number of layers must match number of weights and be > 0")
    
    # Normalize weights to sum to 1
    total_weight = sum(abs(w) for w in weights)  # Use absolute values to avoid zero sum
    if total_weight == 0:
        total_weight = 1  # Prevent division by zero
    normalized_weights = [w / total_weight for w in weights]
    
    weighted_arrays = []
    base_meta = None
    
    # First, find a raster file to get the reference metadata
    raster_file = None
    for path in layer_paths:
        if path.endswith('.tif') or path.endswith('.tiff'):
            raster_file = path
            break
    
    if raster_file:
        with rasterio.open(raster_file) as src:
            base_meta = src.meta.copy()
    else:
        # Create default metadata if no raster found
        base_meta = {
            'driver': 'GTiff',
            'dtype': 'float32',
            'width': 1000,
            'height': 1000,
            'count': 1,
            'crs': 'EPSG:4326',
            'transform': rasterio.transform.from_bounds(-122.2, 37.4, -122.0, 37.6, 1000, 1000),
            'nodata': None
        }
        
    for i, (layer_path, weight) in enumerate(zip(layer_paths, normalized_weights)):
        print(f"Processing layer {i+1}: {layer_path} (weight: {weight:.3f})")
        
        if layer_path.endswith('.geojson'):
            # Convert vector to raster
            print(f"  Converting vector to raster...")
            gdf = gpd.read_file(layer_path)
            
            if len(gdf) == 0:
                # Empty dataset - create zero array
                layer_data = np.zeros((base_meta['height'], base_meta['width']), dtype=float)
            else:
                # Rasterize the vector data
                shapes = [(geom, 1) for geom in gdf.geometry]
                layer_data = rasterize(
                    shapes,
                    out_shape=(base_meta['height'], base_meta['width']),
                    transform=base_meta['transform'],
                    fill=0,
                    dtype='float32'
                ).astype(float)
        else:
            # Read raster data
            with rasterio.open(layer_path) as src:
                layer_data = src.read(1).astype(float)
            
        # Normalize to 0-1 range (handle edge cases)
        min_val, max_val = layer_data.min(), layer_data.max()
        if max_val > min_val:
            normalized_data = (layer_data - min_val) / (max_val - min_val)
        else:
            # If all values are the same, set to 0.5 (neutral)
            normalized_data = np.full_like(layer_data, 0.5)
        
        # Apply weight
        weighted_layer = normalized_data * weight
        weighted_arrays.append(weighted_layer)
    
    # Sum all weighted layers
    mca_result = np.sum(weighted_arrays, axis=0)
    
    # Determine output path
    base_filename = "_".join(config.get('output_name', 'mca_result').split())
    output_dir = ensure_output_dir()
    output_path = os.path.join(output_dir, f"{base_filename}.tif")
    
    # Update metadata for output
    base_meta.update({
        'dtype': 'float32',
        'nodata': None
    })
    
    # Save MCA result
    with rasterio.open(output_path, 'w', **base_meta) as dst:
        dst.write(mca_result.astype('float32'), 1)
    
    print(f"✅ MCA complete! Saved to: {output_path}")
    return os.path.basename(output_path)  # Return just filename for frontend compatibility
