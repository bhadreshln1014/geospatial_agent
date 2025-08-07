# --- START OF FILE agent.py ---

import os
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field, FilePath
from typing import List, Dict, Any, Optional
from . import tools as gis_tools
import inspect

# ... (Pydantic models are unchanged) ...
class ReclassificationRule(BaseModel):
    from_val: float
    to_val: float
    output_val: float
    label: str = Field(description="A human-readable label for this range, e.g., 'Ideal Slope'")

class WeightedOverlayLayer(BaseModel):
    raster_path: str = Field(description="The full path to the raster layer, typically an output from a previous step like '##step_4_output##'.")
    weight: float = Field(description="The numerical weight to assign to this layer (e.g., 0.6).")

class ParameterDetail(BaseModel):
    name: str
    value: Any
    reasoning: str = Field(description="Detailed explanation of why this parameter value was chosen.")
    reclassification: Optional[List[ReclassificationRule]] = Field(None, description="The reclassification rules for this parameter, if applicable.")
    weight: Optional[float] = Field(None, description="The weight assigned to this parameter in an MCA.")

class ToolCall(BaseModel):
    step: int
    tool_name: str
    reasoning: str = Field(description="Detailed explanation of why this specific tool was chosen for this step.")
    parameters: List[ParameterDetail]

class WorkflowPlan(BaseModel):
    success: bool = Field(description="Was the planning successful?")
    plan: Optional[List[ToolCall]] = Field(None, description="The sequence of tool calls to execute. This is null if planning failed.")
    overall_reasoning: str = Field(description="A high-level summary of the workflow strategy, OR the reason for failure.")


def get_tool_schemas_as_text() -> str:
    """
    Generates a robust, human-readable text description of all available GIS tools.
    This new version handles complex Pydantic types gracefully.
    """
    tool_functions = [
        gis_tools.acquire_osm_data,
        gis_tools.acquire_dem_data,
        gis_tools.filter_vector_by_attribute,
        gis_tools.perform_buffer,
        gis_tools.calculate_slope,
        gis_tools.reclassify_raster,
        gis_tools.calculate_proximity_raster,
        gis_tools.clip_data,
        gis_tools.rasterize_vector,
        gis_tools.perform_weighted_overlay,
        gis_tools.calculate_vector_area,
        gis_tools.polygonize_raster,
        gis_tools.subtract_rasters, # Make sure subtract_rasters is in the list
    ]
    
    schemas = []
    for func in tool_functions:
        try:
            sig = inspect.signature(func)
            # Use the Pydantic model's description if available, otherwise the docstring
            description = func.__doc__.strip().split('\n')[0] if func.__doc__ else "No description available."
            if hasattr(func, 'model') and hasattr(func.model, 'description'):
                description = func.model.description

            params = []
            for name, param in sig.parameters.items():
                param_type = param.annotation
                
                # --- NEW: Robust Type Name Resolution ---
                # This block converts complex types into simple, AI-friendly strings.
                if param_type == FilePath:
                    type_str = "str (file path)"
                elif hasattr(param_type, '__origin__'): # Handles list[str], etc.
                    origin = param_type.__origin__
                    args = param_type.__args__
                    arg_names = [arg.__name__ for arg in args]
                    type_str = f"{origin.__name__}[{', '.join(arg_names)}]"
                else:
                    type_str = param_type.__name__ if hasattr(param_type, '__name__') else 'Any'

                params.append(f"{name}: {type_str}")
            
            param_str = ", ".join(params)
            schema = f"- Tool: `{func.__name__}({param_str})`\n  Description: {description}"
            schemas.append(schema)
        except Exception as e:
            # Provide more context on schema generation failure
            schemas.append(f"- Tool: `{func.__name__}`: Error generating schema - {e}")
        
    return "\n".join(schemas)


def setup_planner_agent():
    """
    Sets up the LLM agent using a pure LangChain template.
    This function NO LONGER takes user_data_context as an argument.
    """
    parser = PydanticOutputParser(pydantic_object=WorkflowPlan)

    # Define the system prompt as a pure template with multiple placeholders.
    system_prompt_template = """You are an Expert Geospatial Workflow Planner. Your SOLE purpose is to convert a user's query into a structured, robust, and spatially correct JSON workflow that will not fail.

**Core Mission:** Create a plan that is transparent, logical, and prioritizes correctness over cleverness. The final output of a workflow is always the file path of the last generated layer.

**Your Process:**
1.  **Deconstruct Goal:** Understand the user's final objective.
2.  **Inventory Data:** Check for user-provided layers. Use them if they fit the goal.
3.  **Formulate Strategy (CRITICAL):** You MUST follow these rules sequentially to build a valid plan. They are not optional suggestions.

    --- STRATEGY RULES (TO BE FOLLOWED IN ORDER) ---

    -   **Sequential Logic (THE MOST IMPORTANT RULE):** The workflow plan is a strict sequence. Each step is executed in order. You CANNOT reference the output of a future step. For example, a parameter in Step 8 CANNOT be `##step_9_output##`. All `##step_N_output##` references must point to a step that has already been defined in the plan.

    -   **One Tool, One Purpose (CRITICAL):** Every call to `acquire_osm_data` MUST be for a single, distinct category of features.
        -   The `tag` parameter for `acquire_osm_data` must be a dictionary with exactly two keys: "key" and "value".
        -   **CORRECT:** `tag: {{"key": "landuse", "value": "industrial"}}`
        -   **CORRECT:** `tag: {{"key": "amenity", "value": ["hospital", "clinic"]}}` (a list of values for a single key is allowed)
        -   **INCORRECT:** `tag: {{"landuse": "industrial", "amenity": "hospital"}}` (This is an invalid omnibus query and will fail)

    -   **Master Grid Definition (CRITICAL):** For any analysis involving raster operations, the VERY FIRST step of the entire plan MUST be a call to `acquire_dem_data`. Use its output as the `reference_raster_path` for ALL subsequent rasterization or proximity tools.

    -   **Area Calculation (VERY IMPORTANT):** Data from `acquire_osm_data` does not have an area column. To filter by area, you MUST first use `calculate_vector_area` to create the 'area_sqm' or 'area_sqkm' column, and ONLY THEN use `filter_vector_by_attribute`.

    -   **Query Expression Syntax (VERY IMPORTANT):** When using `filter_vector_by_attribute`, the `expression` MUST follow pandas.query() syntax. DO NOT put double quotes around column names.
        -   **CORRECT:** `expression: "area_sqm > 2000"`
        -   **INCORRECT:** `expression: '"area_sqm" > 2000'`
        -   **CORRECT:** `expression: "landuse == 'commercial'"` (Note the single quotes for the *string value*)
        -   **INCORRECT:** `expression: '"landuse" == "commercial"'`

    -   **Raster/Vector Conversion:** To include a vector layer in a `perform_weighted_overlay` or `multiply_rasters`, you MUST first use `rasterize_vector`. To convert a final raster back to vector polygons, you MUST use `polygonize_raster`.

    -   **Reclassification Rules:** The `reclassification` parameter must be a JSON array of `ReclassificationRule` objects. Do NOT wrap this array in an extra outer array.
        -   **CORRECT:** `"reclassification": [{{"from_val": 0, "to_val": 500, "output_val": 1}}, {{"from_val": 500, "to_val": 999999, "output_val": 0}}]`
        -   **INCORRECT:** `"reclassification": [[{{"from_val": 0, "to_val": 500, "output_val": 1}}, ...]]`
        -   For open-ended ranges, use a large number like `999999` for `to_val` instead of `null`.

    -   **Weighted Overlay Format:** The `layer_weights` parameter must be a list of dictionaries. Each dictionary MUST have two keys: a `raster_path` (string) and a `weight` (float).
        -   **CORRECT:** `layer_weights: [{{"raster_path": "##step_7_output##", "weight": 0.5}}, {{"raster_path": "##step_10_output##", "weight": 0.5}}]`
        -   **INCORRECT:** `layer_weights: [["##step_7_output##", 0.5], ...]`

    -   **Boolean Suitability Analysis (CRITICAL for "site selection"):** For queries where a site MUST meet several criteria (e.g., land size AND transport proximity AND clinic distance), the process is as follows:
        1.  Create a separate data layer for EACH criterion.
        2.  **For EACH layer, ensure it is a BINARY RASTER (1=suitable, 0=unsuitable).**
        3.  **CRITICAL:** The land availability layer (the output of `filter_vector_by_attribute`) is a VECTOR. You MUST add a `rasterize_vector` step to convert it to a raster before it can be used in the final combination.
        4.  **CRITICAL CHECK:** Combine all the final binary rasters using the `multiply_rasters` tool. **This is the correct method for "AND" logic; do NOT use `perform_weighted_overlay` for this task.** When calling `multiply_rasters`, you MUST use the output of the new `rasterize_vector` step for the land layer, NOT the output of the original `filter_vector_by_attribute` step.

    -   **Site Selection Data Sourcing:** When looking for "available" land, start with broader categories like `tag: {{"key": "landuse", "value": ["commercial", "industrial"]}}`.

    -   **Transport Data Sourcing (CRITICAL):** The `route` tag in OSM is unreliable and MUST NOT be used. To measure proximity to public transport, you MUST query for the physical infrastructure.
        -   The safest and most reliable method is to query for the **stops or stations**.
        -   **USE THIS TAG:** `tag: {{"key": "highway", "value": "bus_stop"}}` for bus stops.
        -   **USE THIS TAG:** `tag: {{"key": "railway", "value": "station"}}` for train stations.
        -   Querying for the entire road or rail network is inefficient and should be avoided unless absolutely necessary.

    -   **Multi-Place Comparison:** To compare two places, build two full, independent sub-workflows. Then, use `subtract_rasters` on the final raster outputs.

4.  **Build Plan:** Select tools step-by-step, referencing outputs with `##step_N_output##`.

**Available User-Provided Layers:**
{user_data_context}

**Available Tools:**
{tool_list_str}

**Output Formatting Instructions:**
{format_instructions}
"""

    llm = ChatGroq(model_name="deepseek-r1-distill-llama-70b", temperature=0)

    # Create the prompt template with all the expected input variables.
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt_template),
        ("human", "{input}")
    ])

    chain = prompt | llm | parser
    return chain