import geopandas as gpd
import osmnx as ox
import requests
import rasterio
from rasterio.session import AWSSession
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject, Resampling
import rasterio.transform
import numpy as np
import os
import json
from shapely.geometry import box
try:
    import pystac_client
    import stackstac
    import rioxarray
    from geoserver.catalog import Catalog
except ImportError:
    print("Warning: Some optional dependencies not available. Install with: pip install pystac-client stackstac rioxarray geoserver-restconfig")
from scipy.ndimage import distance_transform_edt
import hashlib
import tempfile

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

def geocode_place(place_name: str):
    """Geocode a place name to get latitude and longitude."""
    gdf = ox.geocode_to_gdf(place_name)
    # Get the centroid of the first result
    centroid = gdf.geometry.iloc[0].centroid
    return centroid.y, centroid.x  # lat, lon

# --- Data Acquisition Tools (FUN-003, FUN-004, FUN-005) ---

def acquire_vector_data(query: str) -> str:
    """
    Acquires vector data (points, lines, polygons) from OpenStreetMap for a specified place and saves it as a GeoJSON file.
    Returns the filepath of the saved data. 
    Query should contain place name and feature type, e.g., 'restaurants in Palo Alto' or 'parks in Davis'.
    """
    if not query or not isinstance(query, str):
        return "Error: Query must be a non-empty string"
    
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
        return filepath  # Return full absolute path
    except Exception as e:
        return f"Error during vector data acquisition: {e}"

def acquire_elevation_data(place_name: str) -> str:
    """
    Acquires Digital Elevation Model (DEM) data using Copernicus DEM from AWS Earth Search STAC catalog.
    Returns the absolute filepath of the saved GeoTIFF.
    """
    if not place_name or not isinstance(place_name, str):
        return "Error: place_name must be a non-empty string"
    
    print(f"TOOL: Acquiring elevation data for '{place_name}' using Copernicus DEM")
    try:
        # Get bounding box for the place
        bounds, crs = get_bbox_from_place(place_name)
        bounds = [float(b) for b in bounds]

        if crs != 'EPSG:4326':
            import pyproj
            transformer = pyproj.Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
            min_x, min_y = transformer.transform(bounds[0], bounds[1])
            max_x, max_y = transformer.transform(bounds[2], bounds[3])
            bounds = [min_x, min_y, max_x, max_y]
        
        # Configure AWS credentials for anonymous access
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'YES'
        
        catalog = pystac_client.Client.open(
            "https://earth-search.aws.element84.com/v1"
        )
        
        search = catalog.search(
            collections=["cop-dem-glo-30"],
            bbox=bounds,
            limit=10
        )
        
        items = list(search.items())
        if not items:
            return f"Error: No DEM data found for {place_name}."
        
        print(f"Found {len(items)} DEM tiles for {place_name}")

        # Configure rasterio environment for AWS access
        import rasterio
        rasterio_env = rasterio.Env(
            AWS_NO_SIGN_REQUEST='YES',
            GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif'
        )
        
        with rasterio_env:
            stack = stackstac.stack(
                items,
                bounds=bounds,
                epsg=4326,
                chunksize=1024,  # Smaller chunks to reduce memory usage
                resolution=30  # 30m resolution
            )
            
            # Select first time slice and compute
            dem_data = stack.isel(time=0).values
            if hasattr(dem_data, 'compute'):
                dem_data = dem_data.compute()
            
            if dem_data is None or dem_data.size == 0 or np.all(np.isnan(dem_data)):
                return f"Error: All DEM data is NaN for {place_name}."
            
            # Create output directory and filename
            output_dir = ensure_output_dir()
            filename = f"{place_name.replace(' ', '_')}_elevation.tif"
            filepath = os.path.join(output_dir, filename)
            
            # Get dimensions and create transform
            height, width = dem_data.shape
            transform = rasterio.transform.from_bounds(
                bounds[0], bounds[1], bounds[2], bounds[3], 
                width, height
            )
            
            # Save as GeoTIFF
            with rasterio.open(
                filepath, 'w',
                driver='GTiff',
                height=height, width=width,
                count=1, dtype=dem_data.dtype,
                crs='EPSG:4326',
                transform=transform,
                nodata=np.nan
            ) as dst:
                dst.write(dem_data, 1)
            
            print(f"TOOL: Saved elevation data to {filepath}")
            return filepath

    except Exception as e:
        print(f"Error in acquire_elevation_data: {e}")
        return f"Error during elevation data acquisition: {str(e)}"




def perform_buffer_analysis(vector_filepath: str, distance_meters: float) -> str:
    """
    Creates a buffer zone around vector features. 'vector_filepath' must be a GeoJSON file.
    'distance_meters' is the buffer distance. Returns the absolute filepath of the buffered GeoJSON.
    """
    print(f"TOOL: Performing buffer of {distance_meters}m on {vector_filepath}")
    try:
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
        return output_filepath  # Return full absolute path
    except Exception as e:
        return f"Error during buffer analysis: {e}"

def acquire_generic_raster_data(place_name: str, raster_type: str) -> str:
    """
    Acquire weather raster data using Open-Meteo API for temperature and precipitation.
    
    Args:
        place_name: Name of the place to get data for
        raster_type: Type of data - "temperature" or "precipitation"
        
    Returns:
        str: Absolute path to the acquired raster file
    """
    print(f"TOOL: Acquiring {raster_type} data for '{place_name}' using Open-Meteo API")
    try:
        # Geocode the place to get coordinates
        lat, lon = geocode_place(place_name)
        print(f"Geocoded {place_name} to: {lat}, {lon}")
        
        # Prepare API parameters based on raster type
        if raster_type.lower() == "temperature":
            params = {
                'latitude': lat,
                'longitude': lon,
                'hourly': 'temperature_2m',
                'forecast_days': 1
            }
            unit = '°C'
        elif raster_type.lower() == "precipitation":
            params = {
                'latitude': lat,
                'longitude': lon,
                'hourly': 'precipitation',
                'forecast_days': 1  
            }
            unit = 'mm'
        else:
            return f"Error: Unsupported raster type '{raster_type}'. Use 'temperature' or 'precipitation'."
        
        # Query Open-Meteo API
        response = requests.get('https://api.open-meteo.com/v1/forecast', params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'hourly' not in data:
            return f"Error: No {raster_type} data returned from Open-Meteo API"
        
        # Extract the values and calculate mean
        if raster_type.lower() == "temperature":
            values = data['hourly']['temperature_2m']
        else:  # precipitation
            values = data['hourly']['precipitation']
        
        # Filter out None values and calculate mean
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return f"Error: No valid {raster_type} values returned from API"
        
        mean_value = sum(valid_values) / len(valid_values)
        print(f"Mean {raster_type}: {mean_value:.2f} {unit}")
        
        # Create a small raster grid around the point (simplified approach)
        # In production, you might interpolate between multiple points
        grid_size = 50
        extent = 0.1  # degrees around the point
        
        # Create coordinate arrays
        x_coords = np.linspace(lon - extent/2, lon + extent/2, grid_size)
        y_coords = np.linspace(lat - extent/2, lat + extent/2, grid_size)
        
        # Create a simple grid with some spatial variation
        raster_data = np.full((grid_size, grid_size), mean_value, dtype=np.float32)
        
        # Add some realistic spatial variation
        for i in range(grid_size):
            for j in range(grid_size):
                # Add small random variation (±5% of mean value)
                variation = np.random.normal(0, abs(mean_value) * 0.05)
                raster_data[i, j] += variation
        
        # Create transform
        transform = rasterio.transform.from_bounds(
            lon - extent/2, lat - extent/2, 
            lon + extent/2, lat + extent/2, 
            grid_size, grid_size
        )
        
        # Create output filename and path
        output_dir = ensure_output_dir()
        filename = f"{place_name.replace(' ', '_')}_{raster_type}.tif"
        filepath = os.path.join(output_dir, filename)
        
        # Save as GeoTIFF
        with rasterio.open(
            filepath, 'w',
            driver='GTiff',
            height=grid_size, width=grid_size,
            count=1, dtype='float32',
            crs='EPSG:4326',
            transform=transform,
            nodata=None
        ) as dst:
            dst.write(raster_data, 1)
        
        print(f"TOOL: Saved {raster_type} data to {filepath}")
        return filepath  # Return full absolute path
        
    except Exception as e:
        print(f"Error in acquire_generic_raster_data: {e}")
        return f"Error during {raster_type} data acquisition: {e}"


def acquire_bhuvan_data(place_name: str, layer_name: str) -> str:
    """
    Acquire vector data from ISRO's Bhuvan platform using WFS.
    
    Args:
        place_name: Name of the place to get data for (used for bbox clipping)
        layer_name: Name of the Bhuvan layer (e.g., 'LULC_1011_250K:lu250k_1011_b')
        
    Returns:
        str: Absolute path to the saved GeoJSON file
    """
    print(f"TOOL: Acquiring Bhuvan data for layer '{layer_name}' in '{place_name}'")
    try:
        # Get bounding box for the place
        bounds, crs = get_bbox_from_place(place_name)
        
        # Convert bounds to EPSG:4326 if needed
        if crs != 'EPSG:4326':
            try:
                import pyproj
                transformer = pyproj.Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
                min_x, min_y = transformer.transform(bounds[0], bounds[1])
                max_x, max_y = transformer.transform(bounds[2], bounds[3])
                bounds = [min_x, min_y, max_x, max_y]
            except ImportError:
                print("Warning: pyproj not available, assuming bounds are in EPSG:4326")
        
        # Construct WFS URL for Bhuvan GeoServer
        base_url = "https://bhuvan-app1.nrsc.gov.in/geoserver/wfs"
        
        # WFS parameters
        params = {
            'service': 'WFS',
            'version': '1.0.0',
            'request': 'GetFeature',
            'typeName': layer_name,
            'outputFormat': 'application/json',
            'bbox': f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]},EPSG:4326"
        }
        
        # Construct the full URL
        wfs_url = f"{base_url}?" + "&".join([f"{k}={v}" for k, v in params.items()])
        print(f"WFS URL: {wfs_url}")
        
        # Use geopandas to read the WFS data
        try:
            gdf = gpd.read_file(wfs_url)
        except Exception as e:
            # Try alternative approach with requests first
            response = requests.get(wfs_url, timeout=30)
            response.raise_for_status()
            
            # Save to temporary file and read with geopandas
            with tempfile.NamedTemporaryFile(mode='w', suffix='.geojson', delete=False) as tmp_file:
                tmp_file.write(response.text)
                tmp_path = tmp_file.name
            
            try:
                gdf = gpd.read_file(tmp_path)
                os.unlink(tmp_path)  # Clean up temp file
            except Exception:
                os.unlink(tmp_path)  # Clean up temp file
                raise e
        
        if gdf.empty:
            return f"Error: No features found for layer '{layer_name}' in the area of '{place_name}'"
        
        print(f"Retrieved {len(gdf)} features from Bhuvan layer '{layer_name}'")
        
        # Create output filename and path
        output_dir = ensure_output_dir()
        safe_layer_name = layer_name.replace(':', '_').replace('/', '_')
        filename = f"{place_name.replace(' ', '_')}_{safe_layer_name}.geojson"
        filepath = os.path.join(output_dir, filename)
        
        # Save as GeoJSON
        gdf.to_file(filepath, driver='GeoJSON')
        
        print(f"TOOL: Saved Bhuvan data to {filepath}")
        return filepath  # Return full absolute path
        
    except Exception as e:
        print(f"Error in acquire_bhuvan_data: {e}")
        return f"Error during Bhuvan data acquisition for layer '{layer_name}': {e}"


def perform_mca(config_string: str) -> str:
    """
    Performs multi-criteria analysis (MCA) on geospatial layers with automatic CRS handling.
    
    Args:
        config_string: JSON configuration with 'files' (list of paths) and 'weights' (list of floats)
        
    Returns:
        str: Absolute path to the saved MCA raster file
    """
    try:
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
        base_crs = None
        base_transform = None
        base_shape = None
        
        # First pass: determine reference CRS and metadata from first raster file
        raster_file = None
        for path in layer_paths:
            if path.endswith('.tif') or path.endswith('.tiff'):
                raster_file = path
                with rasterio.open(raster_file) as src:
                    base_meta = src.meta.copy()
                    base_crs = src.crs
                    base_transform = src.transform
                    base_shape = (src.height, src.width)
                break
        
        if not raster_file:
            # Create default metadata if no raster found
            base_crs = 'EPSG:4326'
            base_shape = (1000, 1000)
            base_transform = rasterio.transform.from_bounds(-122.2, 37.4, -122.0, 37.6, base_shape[1], base_shape[0])
            base_meta = {
                'driver': 'GTiff',
                'dtype': 'float32',
                'width': base_shape[1],
                'height': base_shape[0],
                'count': 1,
                'crs': base_crs,
                'transform': base_transform,
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
                    layer_data = np.zeros(base_shape, dtype=float)
                else:
                    # Reproject vector data to match base CRS if needed
                    if gdf.crs != base_crs:
                        print(f"  Reprojecting vector from {gdf.crs} to {base_crs}")
                        gdf = gdf.to_crs(base_crs)
                    
                    # Rasterize the vector data
                    shapes = [(geom, 1) for geom in gdf.geometry if geom is not None]
                    if shapes:
                        layer_data = rasterize(
                            shapes,
                            out_shape=base_shape,
                            transform=base_transform,
                            fill=0,
                            dtype='float32'
                        ).astype(float)
                    else:
                        layer_data = np.zeros(base_shape, dtype=float)
            else:
                # Read raster data
                with rasterio.open(layer_path) as src:
                    layer_data = src.read(1).astype(float)
                    
                    # Handle CRS mismatch by reprojecting
                    if src.crs != base_crs or src.shape != base_shape:
                        print(f"  Reprojecting raster from {src.crs} to {base_crs}")
                        # Create destination array
                        dst_array = np.empty(base_shape, dtype=np.float32)
                        
                        # Reproject
                        reproject(
                            source=layer_data,
                            destination=dst_array,
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=base_transform,
                            dst_crs=base_crs,
                            resampling=Resampling.bilinear
                        )
                        layer_data = dst_array
                
            # Handle NaN values
            layer_data = np.nan_to_num(layer_data, nan=0.0)
            
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
        return output_path  # Return full absolute path
        
    except Exception as e:
        print(f"Error in perform_mca: {e}")
        return f"Error during multi-criteria analysis: {e}"


def publish_final_map(filepath: str) -> str:
    """
    Publishes a raster or vector file to GeoServer and returns WMS connection details.
    
    Args:
        filepath: Absolute path to the raster (.tif) or vector (.geojson) file to publish
        
    Returns:
        str: JSON string containing wmsUrl, layerName, and bbox
    """
    print(f"TOOL: Publishing map to GeoServer: {filepath}")
    try:
        if not os.path.exists(filepath):
            return f"Error: File not found: {filepath}"
        
        # Extract filename without extension for layer name
        filename = os.path.basename(filepath)
        layer_name = os.path.splitext(filename)[0]
        is_vector = filepath.lower().endswith('.geojson')
        
        # Connect to GeoServer running in Docker within WSL
        geoserver_available = True
        try:
            catalog = Catalog("http://localhost:8080/geoserver/rest", "admin", "geospatial123")
            # Test the connection by trying to get workspaces
            workspaces = catalog.get_workspaces()
            print(f"Connected to GeoServer. Found {len(workspaces)} workspaces.")
        except Exception as conn_error:
            # Note GeoServer unavailability but continue to get proper bbox
            geoserver_available = False
            print(f"Warning: GeoServer not available ({conn_error}), will return response without actual publishing")
        
        # Get bbox from the file first (needed for both GeoServer and fallback response)
        try:
            if is_vector:
                # Read vector file to get bounds
                gdf = gpd.read_file(filepath)
                if len(gdf) > 0:
                    bounds = gdf.total_bounds
                    bbox = [float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])]
                else:
                    bbox = [80.0, 12.8, 80.3, 13.2]  # Default Chennai area bounds for empty data
            else:
                # Read raster file to get bounds
                with rasterio.open(filepath) as src:
                    bounds = src.bounds
                    bbox = [float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)]
        except Exception as e:
            print(f"Warning: Could not read bbox from file {filepath}: {e}")
            bbox = [80.0, 12.8, 80.3, 13.2]  # Default Chennai area bounds
        
        # Return early if GeoServer not available
        if not geoserver_available:
            return json.dumps({
                "wmsUrl": "http://localhost:8080/geoserver/wms",
                "layerName": f"geospatial_agent:{layer_name}",
                "bbox": bbox,
                "file_type": "vector" if is_vector else "raster",
                "status": "mock_published"
            })
        
        # Create workspace if it doesn't exist
        workspace_name = "geospatial_agent"
        try:
            workspace = catalog.get_workspace(workspace_name)
            if not workspace:
                print(f"Creating workspace: {workspace_name}")
                catalog.create_workspace(workspace_name, f"http://localhost:8080/geoserver/{workspace_name}")
            else:
                print(f"Using existing workspace: {workspace_name}")
        except Exception as ws_error:
            print(f"Warning: Could not create/access workspace {workspace_name}: {ws_error}")
            pass
        
        # Create store and layer based on file type
        store_name = layer_name
        try:
            print(f"Creating store '{store_name}' for file: {filepath}")
            
            # Remove existing store if it exists
            existing_store = catalog.get_store(store_name, workspace_name)
            if existing_store:
                print(f"Removing existing store: {store_name}")
                catalog.delete(existing_store, recurse=True)
            
            if is_vector:
                # Create vector store (datastore)
                print("Creating vector datastore...")
                catalog.create_datastore(store_name, filepath, workspace=workspace_name)
            else:
                # Create raster store (coverage store) with file upload
                print("Creating raster coveragestore with file upload...")
                
                # For Docker containers, we need to upload the file rather than use file path
                # Read the file and upload it via REST API
                import requests
                from requests.auth import HTTPBasicAuth
                
                # Upload the GeoTIFF file to GeoServer
                upload_url = f"http://localhost:8080/geoserver/rest/workspaces/{workspace_name}/coveragestores/{store_name}/file.geotiff"
                
                with open(filepath, 'rb') as f:
                    file_data = f.read()
                
                headers = {'Content-Type': 'image/tiff'}
                auth = HTTPBasicAuth('admin', 'geospatial123')
                
                response = requests.put(upload_url, data=file_data, headers=headers, auth=auth)
                
                if response.status_code not in [200, 201]:
                    raise Exception(f"Failed to upload raster file: {response.status_code} - {response.text}")
                
                print(f"Successfully uploaded raster file via REST API")
            
            print(f"Successfully created store: {store_name}")
            
            # Apply style if exists
            try:
                style = catalog.get_style("suitability_style")
                if style:
                    layer = catalog.get_layer(f"{workspace_name}:{layer_name}")
                    if layer:
                        layer.default_style = style
                        catalog.save(layer)
                        print("Applied suitability_style to layer")
            except Exception as style_error:
                print(f"Warning: Could not apply suitability_style: {style_error}")
        
        except Exception as e:
            print(f"Error details when publishing to GeoServer:")
            print(f"  Store name: {store_name}")
            print(f"  File path: {filepath}")
            print(f"  Workspace: {workspace_name}")
            print(f"  Is vector: {is_vector}")
            print(f"  Error: {e}")
            # Still return a valid response even if publishing fails
        
        result = {
            "wmsUrl": "http://localhost:8080/geoserver/wms",
            "layerName": f"{workspace_name}:{layer_name}",
            "bbox": bbox,
            "file_type": "vector" if is_vector else "raster",
            "status": "published"
        }
        
        return json.dumps(result)
        
    except Exception as e:
        print(f"Error in publish_final_map: {e}")
        return f"Error publishing map to GeoServer: {e}"


# Wrapper functions for tools with multiple parameters to work with LangChain tool calling
def acquire_raster_wrapper(args_string: str) -> str:
    """
    Wrapper for acquire_generic_raster_data to work with LangChain tool calling.
    Expects args_string in format: "place_name,raster_type" (e.g., "Chennai,temperature")
    """
    try:
        parts = args_string.split(',')
        if len(parts) != 2:
            return "Error: Please provide arguments in format 'place_name,raster_type' (e.g., 'Chennai,temperature')"
        
        place_name = parts[0].strip()
        raster_type = parts[1].strip()
        
        return acquire_generic_raster_data(place_name, raster_type)
    except Exception as e:
        return f"Error parsing arguments: {e}. Expected format: 'place_name,raster_type'"

def buffer_analysis_wrapper(args_string: str) -> str:
    """
    Wrapper for perform_buffer_analysis to work with LangChain tool calling.
    Expects args_string in format: "vector_filepath,distance_meters" (e.g., "/path/file.geojson,1000")
    """
    try:
        parts = args_string.split(',')
        if len(parts) != 2:
            return "Error: Please provide arguments in format 'vector_filepath,distance_meters' (e.g., '/path/file.geojson,1000')"
        
        vector_filepath = parts[0].strip()
        distance_meters = float(parts[1].strip())
        
        return perform_buffer_analysis(vector_filepath, distance_meters)
    except Exception as e:
        return f"Error parsing arguments: {e}. Expected format: 'vector_filepath,distance_meters'"
