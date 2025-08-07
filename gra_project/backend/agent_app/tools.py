# --- START OF FILE tools.py (Definitive Final Version with Environment Isolation) ---

import os
import subprocess
import json
import requests
import shutil
from pydantic import validate_call, FilePath, conlist, PositiveFloat, BaseModel
from typing import List, Any, Dict
from .exceptions import ToolValidationError, ToolExecutionError
import threading
import re
import rioxarray
from django.conf import settings
import whitebox
import rasterio
import numpy as np

# Initialize WhiteboxTools at module level
wbt = whitebox.WhiteboxTools()
wbt.verbose = False  # Disable verbose output

def load_dataset_metadata():
    info_path = os.path.join(settings.BASE_DIR, "PS-4", "info.json")
    with open(info_path, 'r') as f:
        return json.load(f)

# --- 1. CRITICAL ENVIRONMENT CONFIGURATION ---
print("CONFIGURING: Setting environment for public cloud data access.")
os.environ['AWS_NO_SIGN_REQUEST'] = 'YES'
os.environ['GDAL_DISABLE_READDIR_ON_OPEN'] = 'EMPTY_DIR'

# --- 2. TOOL REGISTRY SETUP ---
TOOL_REGISTRY = {}
def register_tool(func):
    TOOL_REGISTRY[func.__name__] = func
    return func

# --- 3. CONTEXT AND HELPER FUNCTIONS ---
_thread_local = threading.local()
def set_workflow_context(thread_id: str, place_name: str = None):
    _thread_local.thread_id, _thread_local.place_name = thread_id, place_name

def get_workflow_context():
    from django.conf import settings
    thread_id = getattr(_thread_local, 'thread_id', 'default_thread')
    place_name_raw = getattr(_thread_local, 'place_name', 'default_place')
    place_name = re.sub(r'[^a-zA-Z0-9_-]', '', str(place_name_raw).replace(' ', '_'))
    output_dir = os.path.join(settings.MEDIA_ROOT, f"{thread_id}_{place_name}")
    os.makedirs(output_dir, exist_ok=True)
    return thread_id, place_name, output_dir

def get_output_filepath(filename: str) -> str:
    _, _, output_dir = get_workflow_context()
    return os.path.join(output_dir, filename)

# --- 4. THE QGIS PROCESS BRIDGE (DEFINITIVE PATH-CLEANING ISOLATION) ---
def run_qgis_process(algorithm_name: str, params: dict, output_filename_prefix: str) -> str:
    tool_name = algorithm_name
    
    # --- FINAL FIX: Surgically clean the PATH variable ---
    
    # Get the path to the virtual environment, if it's active.
    venv_path = os.environ.get('VIRTUAL_ENV')
    original_path = os.environ.get('PATH', '')
    
    # If a venv is active, filter its 'bin' directory out of the PATH string.
    # This forces the subprocess to find the system's python, not the venv's.
    if venv_path and f"{venv_path}/bin" in original_path:
        path_list = original_path.split(os.pathsep)
        filtered_paths = [p for p in path_list if not p.startswith(f"{venv_path}/bin")]
        clean_path = os.pathsep.join(filtered_paths)
    else:
        clean_path = original_path

    # Create a minimal environment using the cleaned PATH.
    qgis_env = {
        'PATH': clean_path,
        'HOME': os.environ.get('HOME'),
        'QGIS_PREFIX_PATH': '/usr',
        'QT_QPA_PLATFORM': 'offscreen',
    }

    # Address the XDG_RUNTIME_DIR warning and permissions issue.
    runtime_dir = f'/tmp/qgis_runtime_{os.getuid()}'
    os.makedirs(runtime_dir, mode=0o700, exist_ok=True)
    qgis_env['XDG_RUNTIME_DIR'] = runtime_dir
    
    # Clean out any keys that might have a 'None' value.
    qgis_env = {k: v for k, v in qgis_env.items() if v is not None}

    output_param_candidates = ['OUTPUT', 'OUTPUT_LAYER', 'OUTPUT_RASTER']
    output_param_name = next((p for p in output_param_candidates if p in params), 'OUTPUT')
    
    is_raster_output = "raster" in algorithm_name.lower() or output_param_name == 'OUTPUT_RASTER'
    if not is_raster_output:
        input_param_name = next((p for p in ['INPUT', 'INPUT_RASTER', 'INPUT_LAYER'] if p in params), None)
        if input_param_name and isinstance(params.get(input_param_name), str):
            if params[input_param_name].lower().endswith(('.tif', '.tiff')):
                is_raster_output = True
    
    ext = ".tif" if is_raster_output else ".gpkg"
    output_path = get_output_filepath(f"{output_filename_prefix}{ext}")
    params[output_param_name] = output_path
    
    command = ['qgis_process', 'run', algorithm_name, '--']
    for key, value in params.items():
        # Check if the value is a list (for multi-input parameters like 'LAYERS')
        if isinstance(value, list):
            # If it's a list, iterate and append each item separately
            for item in value:
                command.append(f"{key}={item}")
        else:
            # If it's not a list, append as a single key=value pair
            command.append(f"{key}={value}")
    
    try:
        print(f"Executing QGIS Command: {' '.join(command)}")
        print(f"Using DEFINITIVELY CLEANED environment with PATH: {qgis_env.get('PATH')}")
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=qgis_env
        )
        print(f"QGIS STDOUT: {result.stdout}")
        
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
             raise ToolExecutionError(f"QGIS ran but produced an empty/missing output file. Check logs. STDOUT: {result.stdout}", tool_name)
        return output_path
    except FileNotFoundError:
        raise ToolExecutionError("The 'qgis_process' command was not found. Is QGIS installed and in your PATH?", tool_name)
    except subprocess.CalledProcessError as e:
        raise ToolExecutionError(f"QGIS algorithm '{algorithm_name}' failed. Error: {e.stderr}", tool_name)

@register_tool
@validate_call
def acquire_data_from_url(url: str, file_name: str) -> FilePath:
    """
    Downloads a file from a URL. This is the fallback for data acquisition.

    When to Use:
    - This tool should ONLY be used when a required dataset (e.g., a specific
      district boundary, a different DEM) is NOT available in the local PS4
      data library (as described in info.json).
    - If a user asks for analysis on a specific area like a district, but no
      boundary file for that district is in the available datasets, you MUST
      use this tool to attempt to download it.

    Important Note:
    - If a user does not provide a URL, you should construct a plausible
      placeholder URL from a known public data source and state in your
      reasoning that the user needs to verify it.
    """
    output_path = get_output_filepath(file_name)
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(output_path, 'wb') as f:
            shutil.copyfileobj(r.raw, f)
    return output_path

@register_tool
@validate_call
def reclassify_raster(raster_path: FilePath, reclass_values: List[List[Any]]) -> FilePath:
    """
    Changes raster pixel values based on a table of rules. Analogy: Sorting pixels into new bins.

    When to Use:
    - **Suitability Modeling (Creating Binary Rasters):** To convert a continuous raster
      (like slope from 0-90 degrees) into a binary one where 1 means 'Suitable' and
      0 means 'Unsuitable'. For example, if suitable slope is < 15 degrees, you
      would reclassify values from 0-15 to 1, and 15-90 to 0.
    - **Normalization for Weighted Overlay:** To convert several input rasters with
      different value ranges (e.g., elevation, rainfall) to a common, consistent
      scale (e.g., 1 to 10) before using the `perform_weighted_overlay` tool.

    Important Note:
    - The `reclass_values` parameter MUST be a list of lists. Each inner list must
      contain exactly three numbers: `[minimum_value, maximum_value, new_output_value]`.
    """
    qgis_table_list = [item for sublist in reclass_values for item in sublist]
    
    # 2. Convert the list of numbers into a single, comma-separated string.
    #    This is the format that the qgis_process command-line tool expects.
    #    Example: [0, 5, 10] becomes "0,5,10"
    qgis_table_str = ','.join(map(str, qgis_table_list))

    # 3. Build the parameters dictionary using the correctly formatted string.
    params = {
        'INPUT_RASTER': str(raster_path),
        'RASTER_BAND': 1,
        'TABLE': qgis_table_str, # <-- Pass the string, not the list
        'NO_DATA': -9999.0,
        'RANGE_BOUNDARIES': 0,
        'USE_NODATA': False,
        'DATA_TYPE': 5,
        'OUTPUT': ''
    }

    input_basename = os.path.splitext(os.path.basename(str(raster_path)))[0]
    output_prefix = f'reclassified_{input_basename}'
    
    return run_qgis_process('native:reclassifybytable', params, output_prefix)

@register_tool
@validate_call
def perform_buffer(vector_path: FilePath, distance_meters: PositiveFloat) -> FilePath:
    """
    Creates a buffer zone around vector features. Analogy: Drawing a 'halo' or 'zone of influence'.

    When to Use:
    - **Proximity Analysis:** Answering questions like "Find all areas within 500 meters of a river"
      or "Identify properties within 1km of a proposed highway."
    - **Defining Influence or Exclusion Zones:** Creating a protection zone around a sensitive
      feature or an influence area around a commercial location.

    Important Note:
    - The buffer `distance_meters` is specified in meters.
    - This tool automatically dissolves overlapping buffers into a single polygon feature.
    """
    params = {'INPUT': str(vector_path), 'DISTANCE': float(distance_meters), 'SEGMENTS': 8, 'DISSOLVE': True, 'OUTPUT': ''}
    return run_qgis_process('native:buffer', params, f'buffer_{distance_meters}m')

@register_tool
@validate_call
def clip_data(data_to_clip_path: FilePath, clip_boundary_path: FilePath) -> FilePath:
    """
    Spatially cuts a dataset using another's boundary. Analogy: A 'cookie cutter'.

    When to Use:
    - **Scoping Analysis (Most Common Use):** To limit a large, statewide dataset (like
      `Assam_LULC`) to a smaller, specific area of interest (like a district boundary
      that you downloaded).
    - **Intersection for Damage Assessment:** To find the geographic overlap between an
      asset layer (e.g., buildings, LULC) and a hazard layer (e.g., flood boundary).

    Important Note:
    - This tool is smart: it automatically detects if the `data_to_clip_path` is a
      raster or a vector and uses the correct underlying QGIS algorithm.
    - The `clip_boundary_path` must always be a vector layer.
    """
    if str(data_to_clip_path).lower().endswith(('.tif', '.tiff')):
        params = {'INPUT': str(data_to_clip_path), 'MASK': str(clip_boundary_path), 'OUTPUT': ''}
        return run_qgis_process('gdal:cliprasterbymasklayer', params, 'clipped_raster')
    else:
        params = {'INPUT': str(data_to_clip_path), 'OVERLAY': str(clip_boundary_path), 'OUTPUT': ''}
        return run_qgis_process('native:clip', params, 'clipped_vector')

@register_tool
@validate_call
def multiply_rasters(**kwargs: FilePath) -> FilePath:
    """
    Multiplies pixel values of rasters together. This is for Boolean 'AND' logic.

    When to Use:
    - This is the primary tool to combine criteria in a **Boolean Suitability Analysis**.
    - It should be used *after* you have created several binary (0/1) suitability maps
      using the `reclassify_raster` tool. The output will be 1 only in pixels
      where *all* input rasters were also 1, finding areas that meet every condition.

    Important Note:
    - This tool treats all inputs equally. If you need to assign different levels
      of importance, you MUST use `perform_weighted_overlay` instead.
    """
    rasters = list(kwargs.values())
    expr = ' * '.join([f'"{chr(ord("a") + i)}@1"' for i in range(len(rasters))])
    params = {'EXPRESSION': expr, 'LAYERS': [str(p) for p in rasters], 'OUTPUT': ''}
    return run_qgis_process('qgis:rastercalculator', params, 'multiplied_rasters')

class WeightedOverlayInput(BaseModel):
    raster_path: FilePath
    weight: float

@register_tool
@validate_call
def perform_weighted_overlay(layer_weights: List[WeightedOverlayInput]) -> str:
    """
    Robust weighted overlay with dimension checking and resampling.
    """
    # Input validation
    if not layer_weights:
        raise ToolValidationError("At least one input layer required", "perform_weighted_overlay")

    total_weight = sum(item.weight for item in layer_weights)
    if not 0.99 <= total_weight <= 1.01:
        raise ToolValidationError(f"Weights must sum to 1.0 (got {total_weight})", 
                               "perform_weighted_overlay")

    output_path = get_output_filepath("weighted_overlay.tif")

    try:
        # First check all rasters have same dimensions
        with rasterio.open(layer_weights[0].raster_path) as src:
            base_shape = src.shape
            base_transform = src.transform
            base_crs = src.crs
            meta = src.meta.copy()

        # Resample any mismatched rasters
        resampled_paths = []
        for i, item in enumerate(layer_weights):
            with rasterio.open(item.raster_path) as src:
                if src.shape != base_shape or src.transform != base_transform:
                    resampled_path = get_output_filepath(f"resampled_{i}.tif")
                    resampled_paths.append(resampled_path)
                    
                    wbt.resample(
                        inputs=item.raster_path,
                        output=resampled_path,
                        cell_size=base_transform[0],  # Use base raster's resolution
                        base=layer_weights[0].raster_path  # Match to first raster
                    )
                    item.raster_path = resampled_path

        # Perform weighted sum
        result = np.zeros(base_shape, dtype=np.float32)
        for item in layer_weights:
            with rasterio.open(item.raster_path) as src:
                data = src.read(1)
                data[data == src.nodata] = 0  # Handle nodata
                result += data.astype(np.float32) * item.weight

        # Write output
        meta.update(dtype=rasterio.float32)
        with rasterio.open(output_path, 'w', **meta) as dst:
            dst.write(result, 1)

        # Cleanup temporary files
        for path in resampled_paths:
            if os.path.exists(path):
                os.remove(path)

        return output_path

    except Exception as e:
        raise ToolExecutionError(
            f"Weighted overlay failed: {str(e)}", 
            "perform_weighted_overlay"
        )

@register_tool
@validate_call
def calculate_vector_area(vector_path: FilePath) -> Dict[str, Any]:
    """
    Calculates summary statistics (like area) for a vector layer. Does NOT produce a map.

    When to Use:
    - This should be the **FINAL step** of any workflow that answers a question like
      **"How much...?"** or asks for a number instead of a map.
    - Example: After clipping agricultural land to a flood boundary, use this tool on the
      result to calculate the total affected area in square meters.

    Important Note:
    - The output of this tool is a JSON object containing statistics, not a new map file.
      It is a terminal step for a quantitative analysis.
    """
    params = {'INPUT_LAYER': str(vector_path)}
    command = ['qgis_process', 'run', 'native:vectorlayerstatistics', '--json', json.dumps(params)]
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
    return json.loads(result.stdout)

@register_tool
def get_data_from_ps4(data_name: str) -> str: # <--- RENAMED from 'dataset_name' to 'data_name'
    """
    Retrieves a dataset from the local data library using its specified `name`.

    When to Use:
    - This should **ALWAYS be your first choice** for getting data. Before trying to
      download anything with `acquire_data_from_url`, you MUST check if a suitable
      dataset is already available by inspecting the 'Available Datasets' list.

    Important Note:
    - The `data_name` parameter must exactly match the `name` attribute of a dataset
      listed in the `info.json` file.
    - If a dataset with the specified name is not found, this tool will fail. Your
      plan should anticipate this and use `acquire_data_from_url` as a fallback.
    """
    from django.conf import settings
    
    # 1. Load the metadata manifest
    try:
        all_datasets = load_dataset_metadata()
    except Exception as e:
        raise ToolExecutionError(f"Fatal error: Could not load or parse info.json. {e}", "get_data_from_ps4")

    # 2. Find the requested dataset's information in the manifest
    target_dataset_info = next((item for item in all_datasets if item.get('name') == data_name), None)

    if not target_dataset_info:
        raise ToolValidationError(
            f"The dataset '{data_name}' is not listed in the info.json manifest. Cannot proceed.",
            "get_data_from_ps4"
        )
    
    # 3. Get the authoritative file type from the manifest
    file_type = target_dataset_info.get('file_type')
    if not file_type:
        raise ToolValidationError(
            f"The dataset '{data_name}' in info.json is missing the required 'file_type' attribute.",
            "get_data_from_ps4"
        )
        
    base_ps4_dir = os.path.join(settings.BASE_DIR, "PS-4")

    # 4. Use the file_type to determine the search strategy
    if file_type == 'vector':
        # For vectors, the 'name' is the folder name.
        folder_path = os.path.join(base_ps4_dir, data_name)
        if not os.path.isdir(folder_path):
            raise ToolExecutionError(f"Vector dataset '{data_name}' not found. Expected a folder at: {folder_path}", "get_data_from_ps4")
        
        for fname in os.listdir(folder_path):
            if fname.lower().endswith('.shp'):
                return os.path.join(folder_path, fname)
        
        raise ToolExecutionError(f"Vector folder '{data_name}' exists but contains no .shp file.", "get_data_from_ps4")

    elif file_type == 'raster':
        # For rasters, the 'name' is the base filename.
        raster_extensions = ['.tif', '.tiff', '.img', '.jp2']
        for ext in raster_extensions:
            file_path = os.path.join(base_ps4_dir, f"{data_name}{ext}")
            if os.path.isfile(file_path):
                return file_path
        
        raise ToolExecutionError(f"Raster dataset '{data_name}' not found. Searched for files like '{data_name}.tif' in the PS4 directory.", "get_data_from_ps4")

    else:
        # Handle unknown file types
        raise ToolValidationError(
            f"Unsupported file_type '{file_type}' for dataset '{data_name}' in info.json.",
            "get_data_from_ps4"
        )

@register_tool
@validate_call
def select_and_rasterize_vector(
    vector_path: FilePath,
    attribute_name: str,
    attribute_value: str,
    reference_raster_path: FilePath
) -> FilePath:
    """
    Selects vector features by attribute and converts them into a binary raster.

    This tool is essential for using vector data (like land use polygons) as a
    criterion in a raster-based suitability analysis. It first selects all features
    matching a query (e.g., attribute 'LULC_TYPE' = 'Forest') and then creates a
    raster where pixels inside these selected polygons have a value of 1, and all
    other pixels have a value of 0.

    When to Use:
    - When a suitability criterion is based on vector data (e.g., land use, soil type).
    - Use this to create a binary raster (1=suitable, 0=unsuitable) from a vector
      layer before combining it with other raster criteria in `perform_weighted_overlay`.

    Important Note:
    - The `reference_raster_path` is used to match the output raster's cell size,
      extent, and CRS, ensuring all layers align perfectly.
    """
    # Step 1: Select features by attribute
    selected_vector_path = run_qgis_process(
        'native:extractbyattribute',
        {
            'INPUT': str(vector_path),
            'FIELD': attribute_name,
            'OPERATOR': 0,  # 0 corresponds to '='
            'VALUE': attribute_value,
            'OUTPUT': ''
        },
        'selected_vector'
    )

    # Step 2: Rasterize the selected vector features
    rasterized_path = run_qgis_process(
        'gdal:rasterize',
        {
            'INPUT': selected_vector_path,
            'FIELD': '',  # We are not burning an attribute value, just a fixed value
            'BURN': 1,    # The value to burn into the raster for the selected features
            'UNITS': 1,   # 1 = Pixels
            'WIDTH': 0,   # These are determined by the reference layer
            'HEIGHT': 0,  # These are determined by the reference layer
            'EXTENT': str(reference_raster_path), # Match the extent of another raster
            'NODATA': 0,  # Pixels outside the polygons will be 0
            'DATA_TYPE': 5, # 5 = Float32
            'OUTPUT': ''
        },
        'rasterized_vector'
    )
    return rasterized_path