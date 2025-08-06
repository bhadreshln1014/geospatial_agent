# --- START OF FILE agent.py ---

import os
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
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


# ... (get_tool_schemas_as_text is unchanged) ...
def get_tool_schemas_as_text() -> str:
    tool_functions = [
        gis_tools.acquire_osm_data,
        gis_tools.acquire_dem_data,
        gis_tools.acquire_bhuvan_data,
        gis_tools.filter_vector_by_attribute,
        gis_tools.perform_buffer,
        gis_tools.calculate_slope,
        gis_tools.reclassify_raster,
        gis_tools.calculate_proximity_raster,
        gis_tools.clip_data,
        gis_tools.rasterize_vector,
        gis_tools.compare_places_analysis,
        gis_tools.perform_weighted_overlay,
    ]
    
    schemas = []
    for func in tool_functions:
        try:
            sig = inspect.signature(func)
            docstring = func.__doc__.strip().split('\n')[0] if func.__doc__ else "No description available."
            
            params = []
            for name, param in sig.parameters.items():
                param_type = param.annotation if param.annotation != inspect.Parameter.empty else 'Any'
                params.append(f"{name}: {param_type}")
            
            param_str = ", ".join(params)
            schema = f"- Tool: `{func.__name__}({param_str})`\n  Description: {docstring}"
            schemas.append(schema)
        except Exception as e:
            schemas.append(f"- Tool: `{func.__name__}`: Error generating schema - {e}")
        
    return "\n".join(schemas)


def setup_planner_agent(user_data_context: str = "No user-provided layers are available."):
    """Sets up the LLM agent to ONLY generate a JSON workflow plan."""
    
    tool_list_str = get_tool_schemas_as_text()
    parser = PydanticOutputParser(pydantic_object=WorkflowPlan)
    # Add explicit JSON output instructions
    format_instructions = (
        parser.get_format_instructions() +
        "\n\nIMPORTANT: Output MUST be valid JSON with double-quoted properties. "
        "All step references must use ##step_N_output## format."
    )

    llm = ChatGroq(model_name="deepseek-r1-distill-llama-70b", temperature=0)

    # Build the system prompt with .format() first
    system_prompt_template = """You are an Expert Geospatial Workflow Planner. Your SOLE purpose is to convert a user's query into a structured, robust, and spatially correct JSON workflow.

**Core Mission:** Create a plan that will not fail due to common GIS errors. Prioritize spatial correctness and support multi-place analysis. The final output of a workflow is the file path of the last generated layer.

**Your Process:**
1.  **Deconstruct Goal:** Understand the user's objective. Identify if this is single-place or multi-place analysis.
2.  **Inventory Data:** Check for user-provided layers. Use them in preference to public data if they fit the goal.
3.  **Formulate Strategy (CRITICAL):**
    -   **AOI Clipping (IMPORTANT):** The `clip_data` tool requires a valid polygon boundary.
        - **USE** this tool ONLY if the user has explicitly provided a boundary layer (e.g., a 'user_layer_...' reference that is a polygon).
        - **NEVER** use point data (like the output from `acquire_osm_data`) as a `clip_boundary_path`. This is a critical error.
        - If the user's query does not include a specific boundary polygon, you MUST skip the clipping step entirely.
    -   **Grid Definition (Raster Creation):** Any tool that creates a new raster from vector data 
        (e.g., `calculate_proximity_raster`, `rasterize_vector`) 
        REQUIRES a `reference_raster_path` that is a valid raster file 
        (GeoTIFF: `.tif`). 
        - NEVER pass a vector file (.geojson, .shp) as `reference_raster_path`.
        - If no raster is yet available in the workflow, you MUST first 
          call `acquire_dem_data` for the place to generate a DEM and use it.
        - Valid sources for `reference_raster_path` include outputs from 
          `acquire_dem_data`, `calculate_slope`, or other raster-producing tools. 
        This ensures the proximity or rasterization tool has the correct grid definition.
    -   **Reclassification Rules:** When defining reclassification rules for an open-ended range (e.g., 'greater than 1000'), you MUST use a very large number like `999999` for the `to_val` instead of `null`. The `to_val` field cannot be null.
    -   **Raster/Vector Conversion:** If a vector layer needs to be included in a raster-based weighted overlay, you MUST use the `rasterize_vector` tool to convert it first.
    -   **Explicit Multi-Place Workflows:** When asked to compare places, formulate a plan that runs the entire analysis workflow for each place sequentially. The final step should be to use the `compare_places_analysis` tool on the final suitability maps from each sub-workflow.
    -   **Weighted Overlay Format:** The `perform_weighted_overlay` tool requires a list of objects with raster_path and weight keys. Example: [{{"raster_path": "##step_4_output##", "weight": 0.6}}, {{"raster_path": "##step_8_output##", "weight": 0.4}}]
    -   **Step Referencing:** When a tool's input is the output of a previous step, you MUST use the `##step_N_output##` reference format for the parameter value.
4.  **Build Plan:** Select tools step-by-step to execute the strategy.

**Rules for User Data:**
-   Use the layer's **Reference ID** (e.g., "user_layer_abc-123") as the parameter value.

**Available User-Provided Layers:**
{user_data_context}

**Available Tools:**
{tool_list_str}

{format_instructions}""".format(
        user_data_context=user_data_context,
        tool_list_str=tool_list_str,
        format_instructions=format_instructions
    )
    # Now escape for LangChain prompt parsing
    system_prompt_template = system_prompt_template.replace("{", "{{").replace("}", "}}")

    # Create prompt template with ONLY the user input variable
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt_template),
        ("human", "{input}")
    ])

    chain = prompt | llm | parser
    return chain