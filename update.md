Of course. This is the definitive implementation plan, incorporating all the critical refinements suggested by the geospatial analyst persona. This code makes your application spatially robust and production-ready by addressing CRS handling, data validation, and improved error messaging, and adds the essential `clip_data` and `rasterize_vector` tools.

Here are the complete and final code changes for each file.

---

### **1. `tools.py` - The Most Critical Changes**

This file receives the most significant upgrades: new helper functions for validation and CRS, new tools for clipping and rasterizing, and enhanced error handling in existing tools.

```python
# --- START OF FILE tools.py ---

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
# --- NEW IMPORTS ---
import warnings
from rasterio.mask import mask

# Initialize WhiteboxTools once
wbt = whitebox.WhiteboxTools()

# --- Helper Functions (get_output_filepath, get_bbox_from_place, geocode_place are unchanged) ---
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

# --- NEW: SPATIAL VALIDATION & PRE-PROCESSING HELPERS ---

def _validate_and_read_vector(vector_path: str) -> gpd.GeoDataFrame:
    """Centralized function to validate and read a vector file."""
    if not os.path.exists(vector_path):
        raise FileNotFoundError(f"Input file not found at '{vector_path}'.")
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        gdf = gpd.read_file(vector_path)

    if gdf.empty:
        raise ValueError("The input vector file is empty and contains no features.")
    
    if gdf.crs is None:
        raise ValueError(f"The input vector file '{os.path.basename(vector_path)}' is missing CRS (projection) information. Please provide a file with a valid .prj file or embedded CRS.")
    
    return gdf

def _validate_and_read_raster(raster_path: str):
    """Centralized function to validate and read a raster file."""
    if not os.path.exists(raster_path):
        raise FileNotFoundError(f"Input file not found at '{raster_path}'.")
    
    with rasterio.open(raster_path) as src:
        if src.crs is None:
            raise ValueError(f"The input raster file '{os.path.basename(raster_path)}' is missing CRS (projection) information.")
        return src # Return the open rasterio object

def _reproject_gdf_to_match(source_gdf: gpd.GeoDataFrame, target_crs_source_path: str) -> gpd.GeoDataFrame:
    """Helper to reproject a GeoDataFrame to match a target file's CRS."""
    with _validate_and_read_raster(target_crs_source_path) if target_crs_source_path.endswith(('.tif', '.tiff')) else warnings.catch_warnings():
        target_gdf = gpd.read_file(target_crs_source_path) if target_crs_source_path.endswith(('.shp', '.geojson', '.gpkg')) else None
        target_crs = rasterio.open(target_crs_source_path).crs if target_gdf is None else target_gdf.crs

    if source_gdf.crs != target_crs:
        print(f"CRS MISMATCH: Reprojecting source data to target CRS {target_crs.to_string()}.")
        return source_gdf.to_crs(target_crs)
    return source_gdf

# --- 1. DATA ACQUISITION TOOLS (Unchanged) ---
# ... (acquire_osm_data, acquire_dem_data, acquire_bhuvan_data are the same) ...

# --- 2. VECTOR ANALYSIS TOOLS (Updated with Validation) ---

def filter_vector_by_attribute(vector_path: str, expression: str) -> str:
    """Filters a vector file based on an attribute query. E.g., 'area_sqkm > 5'. Returns new filepath."""
    try:
        gdf = _validate_and_read_vector(vector_path)
        filtered_gdf = gdf.query(expression)
        if filtered_gdf.empty:
            return f"Warning: No features remained after applying filter '{expression}'. The result is an empty layer."
        
        filepath = vector_path.replace('.geojson', '_filtered.geojson').replace('.shp', '_filtered.shp')
        filtered_gdf.to_file(filepath)
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

# --- 3. RASTER ANALYSIS TOOLS (Updated with Validation) ---

def calculate_slope(dem_path: str) -> str:
    """Calculates slope from a DEM using WhiteboxTools. Returns filepath of slope raster."""
    try:
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
        reclass_str = ";".join([f"{new};{low};{high}" for low, high, new in reclass_values])
        wbt.reclass(i=raster_path, output=filepath, reclass_vals=reclass_str)
        return filepath
    except Exception as e:
        return f"Error during raster reclassification: {e}"

def calculate_proximity_raster(vector_path: str, reference_raster_path: str) -> str:
    """Creates a raster showing Euclidean distance to vector features. Returns distance raster filepath."""
    try:
        gdf = _validate_and_read_vector(vector_path)
        with _validate_and_read_raster(reference_raster_path) as ref:
            meta = ref.meta.copy()
            # Reproject vector to match reference raster CRS
            gdf_proj = gdf.to_crs(ref.crs)

        mask = rasterize(shapes=[geom for geom in gdf_proj.geometry], out_shape=(meta['height'], meta['width']), transform=meta['transform'], fill=0, all_touched=True, dtype=np.uint8)
        proximity_data = distance_transform_edt(mask == 0)
        
        filename = f"proximity_{os.path.basename(vector_path).split('.')[0]}.tif"
        filepath = get_output_filepath(filename)
        meta.update(dtype='float32')
        with rasterio.open(filepath, 'w', **meta) as dst:
            dst.write(proximity_data.astype(np.float32), 1)
        return filepath
    except Exception as e:
        return f"Error during proximity calculation: {e}"

# --- 4. NEW SPATIAL UTILITY TOOLS ---

def clip_data(data_to_clip_path: str, clip_boundary_path: str) -> str:
    """Clips a vector or raster file to the extent of a boundary polygon. Returns new filepath."""
    try:
        clip_gdf = _validate_and_read_vector(clip_boundary_path)
        
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

# --- 5. SYNTHESIS & PUBLISHING TOOLS (Updated) ---

def perform_weighted_overlay(layer_weights: dict) -> str:
    """Performs a weighted sum of multiple pre-processed rasters. Returns final suitability raster filepath."""
    try:
        base_raster_path = list(layer_weights.keys())[0]
        with _validate_and_read_raster(base_raster_path) as src:
            final_raster = np.zeros(src.shape, dtype=np.float32)
            meta = src.meta.copy()
            target_crs = src.crs

        for path, weight in layer_weights.items():
            with _validate_and_read_raster(path) as lyr_src:
                if lyr_src.crs != target_crs:
                    # This is a critical check, but reprojection of rasters is complex.
                    # For now, we will error out. A more advanced implementation would reproject on the fly.
                    return f"Error: CRS mismatch in weighted overlay. Layer '{os.path.basename(path)}' does not match base layer CRS."
                final_raster += lyr_src.read(1) * weight
                
        filepath = get_output_filepath("suitability_map.tif")
        meta.update(dtype='float32')
        with rasterio.open(filepath, 'w', **meta) as dst:
            dst.write(final_raster, 1)
        return filepath
    except Exception as e:
        return f"Error during weighted overlay: {e}"

# ... (publish_to_geoserver is unchanged) ...
```

### **2. `agent.py` - Teaching the Agent New Skills**

We need to add the new tools to the agent's context and provide it with strategic rules on how to use them.

```python
# --- START OF FILE agent.py ---

# ... (imports and Pydantic models are unchanged) ...

# --- MODIFY THIS FUNCTION ---
def get_tool_schemas_as_text() -> str:
    """
    Introspects the tools.py module to generate a precise, machine-readable
    description of all available tools, including their exact parameter names and types.
    """
    tool_functions = [
        gis_tools.acquire_osm_data,
        gis_tools.acquire_dem_data,
        gis_tools.acquire_bhuvan_data,
        gis_tools.filter_vector_by_attribute,
        gis_tools.perform_buffer,
        gis_tools.calculate_slope,
        gis_tools.reclassify_raster,
        gis_tools.calculate_proximity_raster,
        # --- ADD NEW TOOLS ---
        gis_tools.clip_data,
        gis_tools.rasterize_vector,
        # --- END OF ADDITION ---
        gis_tools.perform_weighted_overlay,
        gis_tools.publish_to_geoserver
    ]
    
    # ... (rest of the function is unchanged) ...

# --- MODIFY THIS FUNCTION ---
def setup_planner_agent(user_data_context: str = "No user-provided layers are available."):
    """Sets up the LLM agent to ONLY generate a JSON workflow plan."""
    
    tool_list_str = get_tool_schemas_as_text()
    parser = PydanticOutputParser(pydantic_object=WorkflowPlan)
    format_instructions = parser.get_format_instructions().replace('{', '{{').replace('}', '}}')
    
    # --- PROMPT IS SIGNIFICANTLY UPGRADED ---
    system_prompt = f"""You are an Expert Geospatial Workflow Planner. Your SOLE purpose is to convert a user's query into a structured, robust, and spatially correct JSON workflow.

**Core Mission:** Create a plan that will not fail due to common GIS errors. Prioritize spatial correctness.

**Your Process:**
1.  **Deconstruct Goal:** Understand the user's objective.
2.  **Inventory Data:** Check for user-provided layers. Use them in preference to public data if they fit the goal.
3.  **Formulate Strategy (CRITICAL):**
    -   **CRS First:** Assume all layers might have different Coordinate Reference Systems (CRS). Your plan must handle this.
    -   **AOI Clipping:** If the user provides a boundary (Area of Interest) and asks for analysis on public data (e.g., OSM), your FIRST step after acquiring the public data MUST be to use the `clip_data` tool to clip it to the user's boundary. This is essential for efficiency and relevance.
    -   **Raster/Vector Conversion:** If a vector layer (like a 'no-go zone') needs to be included in a raster-based weighted overlay, you MUST use the `rasterize_vector` tool to convert it first.
4.  **Build Plan:** Select tools step-by-step to execute the strategy.

**Rules for User Data:**
-   Use the layer's **Reference ID** (e.g., "user_layer_abc-123") as the parameter value.

**Available User-Provided Layers:**
{user_data_context}

**Available Tools:**
{tool_list_str}

{format_instructions}"""
    
    llm = ChatGroq(model_name="llama3-70b-8192", temperature=0)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}")
    ])
    
    chain = prompt | llm | parser
    return chain
```

### **3. `views.py` - Handling More Specific Errors**

The changes here are minor but important for UX. We will catch specific exceptions to provide better feedback.

```python
# --- START OF FILE views.py ---

# ... (imports are unchanged) ...

# --- TOOL_MAPPING: Add the new tools ---
TOOL_MAPPING = {
    "acquire_osm_data": gis_tools.acquire_osm_data,
    "acquire_dem_data": gis_tools.acquire_dem_data,
    "acquire_bhuvan_data": gis_tools.acquire_bhuvan_data,
    "filter_vector_by_attribute": gis_tools.filter_vector_by_attribute,
    "perform_buffer": gis_tools.perform_buffer,
    "calculate_slope": gis_tools.calculate_slope,
    "reclassify_raster": gis_tools.reclassify_raster,
    "calculate_proximity_raster": gis_tools.calculate_proximity_raster,
    # --- ADD NEW TOOLS ---
    "clip_data": gis_tools.clip_data,
    "rasterize_vector": gis_tools.rasterize_vector,
    # --- END OF ADDITION ---
    "perform_weighted_overlay": gis_tools.perform_weighted_overlay,
    "publish_to_geoserver": gis_tools.publish_to_geoserver,
}

# ... (UploadView and PlannerView are unchanged from our last version) ...

# --- ExecutorView: Minor change to error handling ---
class ExecutorView(APIView):
    # ... (post method setup is unchanged) ...
    def post(self, request, *args, **kwargs):
        # ...
        def event_stream_generator():
            # ...
            try:
                # ... (the main loop is unchanged) ...
            except Exception as e:
                # --- IMPROVED ERROR LOGGING ---
                error_message = f"❌ Workflow FAILED at Step {step_num} ({tool_name}): {str(e)}"
                if isinstance(e, FileNotFoundError):
                    error_message += " This might be due to an issue with a previous step's output."
                elif isinstance(e, ValueError):
                    error_message += " This often indicates a data validation issue, like a missing CRS or an empty file."
                
                log_entry = {'type': 'error', 'content': error_message}
                # ... (rest of the error handling is unchanged) ...
        # ...
```

### **4. Frontend (`page.tsx`) - Supporting GeoPackage**

As discussed, this is a very simple but important change.

```tsx
// In page.tsx, inside the Upload Dialog form

<div className="space-y-2">
  <Label htmlFor="file">File</Label>
  {/* --- MODIFY THIS LINE --- */}
  <Input id="file" name="file" type="file" accept=".zip,.geojson,.tif,.tiff,.gpkg" required />
  <p className="text-xs text-muted-foreground">
    Upload GeoJSON, GeoTIFF, GeoPackage, or a ZIP containing a Shapefile.
  </p>
</div>
```

With these comprehensive changes, your application is now significantly more robust. It actively prevents common spatial errors, handles a wider range of user data, and has the intelligence to perform more complex, real-world workflows correctly.