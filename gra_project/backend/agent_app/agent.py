from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool
from dotenv import load_dotenv

# Import our custom GIS tools
from .tools import (
    acquire_vector_data, 
    acquire_elevation_data, 
    acquire_generic_raster_data,
    acquire_bhuvan_data,
    perform_buffer_analysis, 
    perform_mca,
    publish_final_map,
    acquire_raster_wrapper,
    buffer_analysis_wrapper
)

@tool
def acquire_vector_data_tool(query: str) -> str:
    """Use to get vector features like points, lines, or polygons from OpenStreetMap. Provide a query describing what you want and where, e.g., 'restaurants in Palo Alto', 'parks in Davis', 'buildings in downtown', 'bars in the city center'. Returns a GeoJSON filepath."""
    return acquire_vector_data(query)

@tool
def acquire_elevation_data_tool(place_name: str) -> str:
    """Use to get a Digital Elevation Model (DEM) raster for a place using live Copernicus DEM data. Essential for analyzing slope and finding flat or steep areas. REQUIRES ONE PARAMETER: place_name (Name of the location to get elevation data for, e.g., 'Chennai'). Returns a GeoTIFF filepath."""
    return acquire_elevation_data(place_name)

@tool
def acquire_generic_raster_data_tool(args_string: str) -> str:
    """Use to get weather raster data using Open-Meteo API. REQUIRES: Single string argument in format 'place_name,raster_type' - place_name: Location name (e.g., 'Chennai'), raster_type: Either 'temperature' or 'precipitation'. Example usage: Call with "Chennai,temperature" or "Chennai,precipitation". Returns a GeoTIFF filepath."""
    return acquire_raster_wrapper(args_string)

@tool
def acquire_bhuvan_data_tool(place_name: str, layer_name: str) -> str:
    """Use to get vector data from ISRO's Bhuvan platform. Provide place_name and layer_name (e.g., 'LULC_1011_250K:lu250k_1011_b'). Returns a GeoJSON filepath."""
    return acquire_bhuvan_data(place_name, layer_name)

@tool
def perform_buffer_analysis_tool(args_string: str) -> str:
    """Use to create a buffer zone around vector features for proximity analysis. REQUIRES: Single string argument in format 'vector_filepath,distance_meters' - vector_filepath: Path to the GeoJSON file, distance_meters: Buffer distance in meters (e.g., 1000 for 1km buffer). Example usage: Call with "/path/to/file.geojson,500". Returns a new GeoJSON filepath with buffered features."""
    return buffer_analysis_wrapper(args_string)

@tool
def perform_multi_criteria_analysis_tool(config_json: str) -> str:
    """Use to combine all previously acquired data layers into a single suitability map. Provide a JSON string with the configuration, e.g.: '{"files": ["path1.geojson", "path2.tif"], "weights": [-0.5, 0.3], "output_name": "school_suitability"}'. Weights: positive = favorable, negative = unfavorable. Returns the final raster filepath."""
    return perform_mca(config_json)

@tool
def publish_final_map_tool(raster_filepath: str) -> str:
    """FINAL STEP: Publishes the completed suitability/analysis raster to GeoServer and returns WMS connection details. Provide the absolute filepath of the final raster. Returns JSON with wmsUrl, layerName, and bbox."""
    return publish_final_map(raster_filepath)

def setup_agent():
    """Sets up the LangChain agent with all the GIS tools."""
    load_dotenv()

    # Define the tools list
    tools = [
        acquire_vector_data_tool,
        acquire_elevation_data_tool, 
        acquire_generic_raster_data_tool,
        acquire_bhuvan_data_tool,
        perform_buffer_analysis_tool,
        perform_multi_criteria_analysis_tool,
        publish_final_map_tool,
    ]

    # This prompt is the agent's "brain" - Updated to include PublishFinalMap
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", """You are a world-class Geospatial Reasoning Agent. Your task is to solve user queries by acquiring and analyzing geospatial data, then publishing the results to a web map service.

        **IMPORTANT: Analyze the user's intent carefully:**
        - If they ask to "find" or "locate" features (e.g., "find schools in Chennai"), simply acquire the data and publish it
        - Only perform additional analysis (buffers, MCA) if explicitly requested or needed for suitability/risk analysis

        **Your Process:**

        **STEP 1: DATA ACQUISITION (Sequential - Execute ONE tool at a time)**
        Use the available tools to gather the necessary geospatial data:
        - acquire_vector_data_tool: Get OpenStreetMap features
        - acquire_elevation_data_tool: Get DEM data (requires place_name)
        - acquire_generic_raster_data_tool: Get weather data (requires "place_name,raster_type" format)
        - acquire_bhuvan_data_tool: Get vector data from Bhuvan
        - perform_buffer_analysis_tool: Create proximity zones (requires "vector_filepath,distance_meters" format)

        **STEP 2: ANALYSIS (if needed)**
        - Use perform_multi_criteria_analysis_tool ONLY for suitability/risk analysis with multiple criteria

        **STEP 3: PUBLICATION (MANDATORY FINAL STEP)**
        - ALWAYS use publish_final_map_tool as your final action
        - This tool publishes the map to GeoServer and returns WMS connection details

        **CRITICAL REQUIREMENTS:**
        1. Your final answer MUST be the JSON output from publish_final_map_tool
        2. Do not provide any commentary after calling publish_final_map_tool
        3. Always end with map publication - never skip this step
        4. Use absolute file paths when calling tools that require file inputs
        5. For simple "find X" queries, just acquire data and publish - no additional analysis needed
        6. Execute tools SEQUENTIALLY, not in parallel
        7. NEVER use placeholder paths - always use the actual file paths returned by previous tools
        8. When calling tools with multiple parameters, use the correct format:
           - acquire_generic_raster_data_tool: Use "place_name,raster_type" (e.g., "Chennai,temperature")
           - perform_buffer_analysis_tool: Use "vector_filepath,distance_meters" (e.g., "/path/file.geojson,1000")

        **Available Tools:**
        - acquire_vector_data_tool: Get OSM vector features
        - acquire_elevation_data_tool: Get DEM data using Copernicus
        - acquire_generic_raster_data_tool: Get weather data (temperature/precipitation)
        - acquire_bhuvan_data_tool: Get ISRO Bhuvan vector data
        - perform_buffer_analysis_tool: Create buffer zones (requires vector_filepath AND distance_meters)
        - perform_multi_criteria_analysis_tool: Combine layers into suitability map
        - publish_final_map_tool: Publish to GeoServer (MANDATORY FINAL STEP)

        **Examples:**
        - "Find schools in Chennai" → acquire_vector_data_tool → publish_final_map_tool
        - "Suitable areas for housing considering schools and elevation" → acquire_vector_data_tool + acquire_elevation_data_tool → perform_multi_criteria_analysis_tool → publish_final_map_tool

        Remember: Your workflow must ALWAYS end by calling publish_final_map_tool and returning its JSON output as your final answer.
        """),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    # Initialize the LLM (using llama3-70b for better function calling compatibility)
    llm = ChatGroq(model_name="llama3-70b-8192", temperature=0)

    # Create the agent and agent executor
    agent = create_tool_calling_agent(llm, tools, prompt_template)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    return agent_executor
