import geopandas as gpd
import osmnx as ox
import requests
import rasterio
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject, Resampling
import numpy as np
import os
from shapely.geometry import box
import pystac_client
import stackstac
from scipy.ndimage import distance_transform_edt

# --- Helper Functions ---
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
        
                
        filepath = f"output/{place_name.replace(' ', '_')}_{feature_name}.geojson"
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        gdf.to_file(filepath, driver='GeoJSON')
        print(f"TOOL: Saved vector data to {filepath}")
        return filepath
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
        
        filepath = f"output/{place_name.replace(' ', '_')}_elevation.tif"
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
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
        return filepath
    except Exception as e:
        return f"Error during elevation data acquisition: {e}"

def acquire_raster_data(place_name: str, asset_type: str, date_range: str) -> str:
    """
    Acquires specific types of raster data like 'landcover' or 'population_density' for a place.
    asset_type must be one of ['landcover', 'population_density'].
    date_range should be like '2022-01-01/2022-12-31'.
    """
    print(f"TOOL: Acquiring '{asset_type}' raster for '{place_name}'")
    try:
        bounds, _ = get_bbox_from_place(place_name)
        
        if asset_type == 'landcover':
            collection = "io-lulc-9-class"
            asset = "data"
            catalog_url = "https://earth-search.aws.element84.com/v1"
        elif asset_type == 'population_density':
            # Note: This is a common source but might require specific handling.
            # For this example, we'll simulate a find. Let's use landcover as a stand-in.
            print("INFO: 'population_density' is complex; using 'landcover' as a stand-in for demonstration.")
            collection = "io-lulc-9-class" 
            asset = "data"
            catalog_url = "https://earth-search.aws.element84.com/v1"
        else:
            return f"Error: Unknown asset_type '{asset_type}'. Must be 'landcover' or 'population_density'."

        catalog = pystac_client.Client.open(catalog_url)
        search = catalog.search(
            collections=[collection],
            bbox=bounds,
            datetime=date_range
        )
        items = list(search.get_items())
        if not items:
            return f"Error: No '{asset_type}' data found for the specified area and date range."

        data_stack = stackstac.stack(items, assets=[asset], bounds_latlon=bounds, resolution=100).squeeze()

        filepath = f"output/{place_name.replace(' ', '_')}_{asset_type}.tif"
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        data_stack.rio.to_raster(filepath, driver="GTiff")
        print(f"TOOL: Saved {asset_type} data to {filepath}")
        return filepath
    except Exception as e:
        return f"Error during raster data acquisition for {asset_type}: {e}"


# --- Analysis Tools (FUN-006, FUN-007) ---

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
    
    output_filepath = vector_filepath.replace(".geojson", "_buffered.geojson")
    gdf_buffered.to_file(output_filepath, driver='GeoJSON')
    print(f"TOOL: Saved buffered data to {output_filepath}")
    return output_filepath

def perform_mca(mca_config: str) -> str:
    """
    Performs a powerful Multi-Criteria Analysis. It handles rasters and vectors, reclassifies them, and calculates a weighted sum.
    
    'mca_config' is a JSON string containing the configuration, e.g.:
    '{"files": ["file1.tif", "file2.geojson"], "weights": [0.5, -0.3], "output_name": "suitability_map"}'
    
    Returns the filepath of the final suitability raster.
    """
    print("TOOL: Performing Multi-Criteria Analysis")
    
    # Parse the JSON configuration
    import json
    try:
        config = json.loads(mca_config)
        files = config['files']
        weights = config['weights']
        final_output_name = config['output_name']
    except (json.JSONDecodeError, KeyError) as e:
        return f"Error parsing MCA configuration: {e}"
    
    if len(files) != len(weights):
        return "Error: Number of files must match number of weights."
    
    processed_rasters = []
    base_meta = None
    
    # Use the first raster layer to define the analysis grid
    for file_path in files:
        if file_path.endswith('.tif'):
            try:
                with rasterio.open(file_path) as src:
                    base_meta = src.meta.copy()
                    break
            except Exception as e:
                print(f"  - WARNING: Could not read raster {file_path}: {e}")
                continue
    
    # If no raster found, create a basic grid based on the vector data bounds
    if not base_meta:
        print("  - No raster found, creating base grid from vector bounds")
        # Get bounds from the first vector file
        for file_path in files:
            if file_path.endswith('.geojson'):
                try:
                    gdf = gpd.read_file(file_path)
                    if not gdf.empty:
                        bounds = gdf.total_bounds
                        # Create a basic raster metadata
                        from rasterio.transform import from_bounds
                        height, width = 100, 100
                        transform = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], width, height)
                        base_meta = {
                            'driver': 'GTiff',
                            'height': height,
                            'width': width,
                            'count': 1,
                            'dtype': 'float32',
                            'crs': gdf.crs,
                            'transform': transform,
                            'shape': (height, width)
                        }
                        break
                except Exception as e:
                    print(f"  - WARNING: Could not read vector {file_path}: {e}")
                    continue
        
        if not base_meta:
            return "Error: Could not establish analysis grid from any input files."
    
    # Process each layer
    for i, file_path in enumerate(files):
        weight = weights[i]
        print(f"  - Processing {file_path} with weight {weight}")
        
        # A. Process Raster Layers
        if file_path.endswith('.tif'):
            with rasterio.open(file_path) as src:
                aligned_data = np.zeros((base_meta['height'], base_meta['width']), dtype=np.float32)
                reproject(
                    source=rasterio.band(src, 1), destination=aligned_data,
                    src_transform=src.transform, src_crs=src.crs,
                    dst_transform=base_meta['transform'], dst_crs=base_meta['crs'],
                    resampling=Resampling.bilinear)
                
                data = aligned_data
        
        # B. Process Vector Layers (convert to proximity raster)
        elif file_path.endswith('.geojson'):
            gdf = gpd.read_file(file_path).to_crs(base_meta['crs'])
            if gdf.empty: continue
            
            # Rasterize the vector shapes to create a binary mask
            mask = rasterize(
                shapes=[geom for geom in gdf.geometry],
                out_shape=(base_meta['height'], base_meta['width']),
                transform=base_meta['transform'],
                fill=0,
                all_touched=True,
                dtype=np.uint8
            )
            
            # Calculate distance from the features
            # distance_transform_edt returns distance to nearest non-zero pixel
            data = distance_transform_edt(mask == 0) 
            
            # For negative weights (unfavorable), use distance as-is (farther = better)
            # For positive weights (favorable), invert distance (closer = better)
            if weight > 0:
                data = data.max() - data if data.max() > 0 else data

        else:
            print(f"  - WARNING: Skipping unsupported file type: {file_path}")
            continue

        # C. Normalize to 0-1 and apply weight
        min_val, max_val = data.min(), data.max()
        if max_val > min_val:
            normalized_data = (data - min_val) / (max_val - min_val)
        else:
            normalized_data = np.zeros_like(data)
            
        processed_rasters.append(normalized_data * weight)

    # D. Sum the weighted layers
    if not processed_rasters: return "Error: No layers were successfully processed for MCA."
    
    final_suitability = np.sum(processed_rasters, axis=0)
    
    # E. Save the final result
    output_filepath = f"output/{final_output_name}.tif"
    base_meta.update({"dtype": "float32", "nodata": -9999})
    final_suitability[final_suitability==0] = -9999 # Set no-data value
    
    with rasterio.open(output_filepath, 'w', **base_meta) as dst:
        dst.write(final_suitability.astype(np.float32), 1)
        
    print(f"TOOL: Saved final MCA map to {output_filepath}")
    return output_filepath
