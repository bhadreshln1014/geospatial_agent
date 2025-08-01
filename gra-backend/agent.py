from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import Tool
from dotenv import load_dotenv

# Import our custom GIS tools
from tools import (
    acquire_vector_data, 
    acquire_elevation_data, 
    acquire_raster_data,
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
            func=acquire_raster_data,
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

    # This prompt is the agent's "brain"
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", """You are a world-class Geospatial Reasoning Agent. Your task is to solve user queries by creating analytical maps.

        **Your Process:**
        1.  **Deconstruct & Plan:** Break down the user's request into a clear, step-by-step plan. Identify the geographic area, the goal (e.g., find suitable locations), and all criteria (e.g., near X, away from Y, on flat land).
        2.  **Acquire All Data First:** Use the 'Acquire' tools to gather every single data layer needed for the analysis. Do not proceed to analysis until all data is acquired.
        3.  **Perform Final Analysis with MCA:** Use the `PerformMultiCriteriaAnalysis` tool **once** at the very end. Provide a JSON string with:
           - "files": list of ALL acquired filepaths
           - "weights": list of weights (positive for favorable, negative for unfavorable)
           - "output_name": simple name for the output map
           Example: '{{"files": ["bars.geojson", "elevation.tif"], "weights": [-0.5, 0.3], "output_name": "school_suitability"}}'
        4.  **Final Answer:** Your final answer must be ONLY the filepath of the map created by `PerformMultiCriteriaAnalysis`. Do not add any other text.
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
