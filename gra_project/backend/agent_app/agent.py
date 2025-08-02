from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import Tool
from dotenv import load_dotenv

# Import our custom GIS tools
from .tools import (
    acquire_vector_data, 
    acquire_elevation_data, 
    acquire_generic_raster_data,
    perform_buffer_analysis, 
    perform_mca
)

def setup_agent():
    """Sets up the LangChain agent with all the GIS tools."""
    load_dotenv()

    # Define the tools for the agent
    tools = [
        Tool(
            name="AcquireVectorData",
            func=acquire_vector_data,
            description="""Use to get vector features like points, lines, or polygons from OpenStreetMap. Provide a query describing what you want and where, e.g., 'restaurants in Palo Alto', 'parks in Davis', 'buildings in downtown', 'bars in the city center'. Returns a GeoJSON filepath."""
        ),
        Tool(
            name="AcquireElevationData",
            func=acquire_elevation_data,
            description="""Use to get a Digital Elevation Model (DEM) raster for a place. Essential for analyzing slope and finding flat or steep areas. Returns a GeoTIFF filepath."""
        ),
        Tool(
            name="AcquireGenericRasterData",
            func=acquire_generic_raster_data,
            description="""Use to get specific raster data like 'landcover' or 'population_density'. Provide place name, asset_type ('landcover' or 'population_density'), and a date_range ('YYYY-MM-DD/YYYY-MM-DD'). Returns a GeoTIFF filepath."""
        ),
        Tool(
            name="PerformBufferAnalysis",
            func=perform_buffer_analysis,
            description="""Use to create a buffer zone around vector features for simple proximity checks. Provide the vector filepath and a distance in meters. Returns a new GeoJSON filepath."""
        ),
        Tool(
            name="PerformMultiCriteriaAnalysis",
            func=perform_mca,
            description="""THE FINAL STEP for any suitability/risk analysis. Combines all previously acquired data layers into a single map.
            Provide a JSON string with the configuration, e.g.:
            '{{"files": ["path1.geojson", "path2.tif"], "weights": [-0.5, 0.3], "output_name": "school_suitability"}}'
            
            Weights: positive = favorable, negative = unfavorable
            Returns the final raster filepath."""
        ),
    ]

    # This prompt is the agent's "brain" - Version 2 with two-step reasoning
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", """You are a world-class Geospatial Reasoning Agent. Your task is to solve user queries by first creating a structured workflow plan and then explaining how you would execute it.

        **Your Process is a strict two-step sequence:**

        **STEP 1: FORMULATE THE PLAN**
        First, based on the user's query, create a complete, step-by-step workflow plan.
        This plan MUST be a valid JSON array of objects. Each object represents a single tool call and must have two keys:
        1. "tool_name": The exact name of the tool to be called (e.g., "AcquireVectorData", "AcquireElevationData", "PerformMultiCriteriaAnalysis").
        2. "parameters": A dictionary of all parameters required by that tool.
        
        For any step that requires a filepath from a previous step, use the placeholder '##PREVIOUS_STEP_X##' where X is the 1-based index of the step that generates the file.
        
        Example workflow plan format:
        [
          {{
            "tool_name": "AcquireVectorData",
            "parameters": {{
              "query": "schools in Palo Alto"
            }}
          }},
          {{
            "tool_name": "AcquireVectorData", 
            "parameters": {{
              "query": "bars in Palo Alto"
            }}
          }},
          {{
            "tool_name": "AcquireElevationData",
            "parameters": {{
              "place_name": "Palo Alto"
            }}
          }},
          {{
            "tool_name": "PerformMultiCriteriaAnalysis",
            "parameters": {{
              "mca_config": "{{\\"files\\": [\\"##PREVIOUS_STEP_1##\\", \\"##PREVIOUS_STEP_2##\\", \\"##PREVIOUS_STEP_3##\\"], \\"weights\\": [0.2, -0.5, 0.3], \\"output_name\\": \\"school_suitability\\"}}"
            }}
          }}
        ]

        **STEP 2: EXPLANATION**
        After providing the JSON plan, briefly explain what each step accomplishes and why the weights were chosen.

        **CRITICAL:** Your response must start with valid JSON and end with a brief explanation. Do not include any other text before the JSON.
        """),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    
    # Initialize the LLM (Groq is extremely fast and great for this)
    llm = ChatGroq(model_name="llama3-70b-8192", temperature=0)

    # Create the agent and agent executor
    agent = create_tool_calling_agent(llm, tools, prompt_template)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    return agent_executor
