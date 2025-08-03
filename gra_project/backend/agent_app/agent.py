import os
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from . import tools as gis_tools
import inspect

# --- Pydantic Models for Structured Output ---
class ReclassificationRule(BaseModel):
    from_val: float
    to_val: float
    output_val: float
    label: str = Field(description="A human-readable label for this range, e.g., 'Ideal Slope'")

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

def get_tool_signatures() -> str:
    """
    A helper function to generate a plain text description of available tools
    and their function signatures for the LLM prompt.
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
        gis_tools.perform_weighted_overlay,
        gis_tools.publish_to_geoserver
    ]
    
    signatures = []
    for func in tool_functions:
        try:
            # Get the function signature and the first line of the docstring
            docstring = func.__doc__
            if docstring:
                docstring = docstring.strip().split('\n')[0]
            else:
                docstring = "No description available"
            signatures.append(f"- `{func.__name__}`: {docstring}")
        except Exception as e:
            signatures.append(f"- `{func.__name__}`: Error getting signature - {e}")
        
    return "\n".join(signatures)

# --- NEW: Function to Generate a Strict Tool Schema ---
def get_tool_schemas_as_text() -> str:
    """
    Introspects the tools.py module to generate a precise, machine-readable
    description of all available tools, including their exact parameter names and types.
    This becomes the "single source of truth" for the Planner Agent.
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
        gis_tools.perform_weighted_overlay,
        gis_tools.publish_to_geoserver
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

def setup_planner_agent():
    """Sets up the LLM agent to ONLY generate a JSON workflow plan."""
    
    # Generate the plain text list of available tools
    tool_list_str = get_tool_schemas_as_text()
    
    # Create the parser first
    parser = PydanticOutputParser(pydantic_object=WorkflowPlan)
    
    # Get format instructions and escape template variables
    format_instructions = parser.get_format_instructions()
    # Escape any curly braces in the format instructions to prevent template conflicts
    format_instructions = format_instructions.replace('{', '{{').replace('}', '}}')
    
    # Create the system prompt with format instructions already included
    system_prompt = f"""You are an Expert Geospatial Workflow Planner. Your SOLE purpose is to convert a user's query into a structured JSON object conforming to the 'WorkflowPlan' schema. You DO NOT execute tools; you only create the plan.

**Your Process:**
1. **Analyze and Deconstruct:** Deeply understand the user's goal, all criteria (including numerical ranges), and the location.
2. **Check Capabilities:** Compare the required steps against your list of available tools below.
3. **Formulate the Output:**
   - **If you can solve the query:** Set `success` to `true`. Formulate a step-by-step `plan`, providing detailed reasoning for every tool choice, parameter, weight, and reclassification. Use `##step_N_output##` placeholders to link steps.
   - **If you CANNOT solve the query:** Set `success` to `false`. Set `plan` to `null`. Your `overall_reasoning` MUST clearly explain why the query cannot be solved (e.g., "I do not have a tool for network routing.").

**CRITICAL:** Do not try to make up tools. If a capability is missing from the list below, you must report the failure.

**Available Tools:**
{tool_list_str}

{format_instructions}"""
    
    # Create the LLM
    llm = ChatGroq(model_name="deepseek-r1-distill-llama-70b", temperature=0)
    
    # Create the prompt template
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}")
    ])
    
    # Create and return the chain
    chain = prompt | llm | parser
    return chain