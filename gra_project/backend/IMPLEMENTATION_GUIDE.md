# Geospatial Reasoning Agent - Live Data Implementation

This implementation provides a production-ready geospatial analysis system with live data sources, workflow logging, and automatic map publishing to GeoServer.

## 🚀 Key Features

### Live Data Sources
- **Copernicus DEM**: Real elevation data via STAC catalog
- **Open-Meteo API**: Live weather data (temperature, precipitation)
- **ISRO Bhuvan**: Indian geospatial data via WFS
- **OpenStreetMap**: Vector features via OSMnx

### Advanced Capabilities
- **Automatic CRS handling**: All layers reprojected to common coordinate system
- **Workflow logging**: Complete audit trail of agent decisions and tool usage
- **Streaming responses**: Real-time progress updates via Server-Sent Events
- **GeoServer integration**: Automatic map publishing with WMS endpoints

## 📁 File Structure

```
agent_app/
├── tools.py          # Live data acquisition and analysis tools
├── callbacks.py      # Workflow logging callback handler
├── agent.py          # LangChain agent with enhanced system prompt
├── views.py          # Django streaming views with callback integration
└── tests/
    ├── test_implementation.py    # Component testing
    └── test_django_views.py     # Django endpoint testing
```

## 🛠️ Tools Overview

### Data Acquisition Tools

#### `acquire_elevation_data(place_name: str) -> str`
- **Purpose**: Get Digital Elevation Model data
- **Source**: Copernicus DEM via AWS Earth Search STAC catalog
- **Returns**: Absolute path to GeoTIFF file
- **Example**: `acquire_elevation_data("Palo Alto")`

#### `acquire_generic_raster_data(place_name: str, raster_type: str) -> str`
- **Purpose**: Get weather data (temperature/precipitation)
- **Source**: Open-Meteo API (free, no API key required)
- **Parameters**: 
  - `place_name`: Location name
  - `raster_type`: "temperature" or "precipitation"
- **Returns**: Absolute path to GeoTIFF file
- **Example**: `acquire_generic_raster_data("Chennai", "temperature")`

#### `acquire_bhuvan_data(place_name: str, layer_name: str) -> str`
- **Purpose**: Get vector data from ISRO's Bhuvan platform
- **Source**: Bhuvan GeoServer WFS service
- **Parameters**:
  - `place_name`: Location for bounding box
  - `layer_name`: Bhuvan layer (e.g., "LULC_1011_250K:lu250k_1011_b")
- **Returns**: Absolute path to GeoJSON file
- **Example**: `acquire_bhuvan_data("Delhi", "LULC_1011_250K:lu250k_1011_b")`

#### `acquire_vector_data(query: str) -> str`
- **Purpose**: Get OpenStreetMap vector features
- **Source**: OSMnx library
- **Parameters**: Natural language query (e.g., "schools in Palo Alto")
- **Returns**: Absolute path to GeoJSON file

### Analysis Tools

#### `perform_buffer_analysis(vector_filepath: str, distance_meters: float) -> str`
- **Purpose**: Create buffer zones around features
- **Returns**: Absolute path to buffered GeoJSON file

#### `perform_mca(config_string: str) -> str`
- **Purpose**: Multi-criteria analysis with automatic CRS handling
- **Parameters**: JSON config with files, weights, and output name
- **Features**: 
  - Automatic reprojection of mismatched CRS
  - Handles mixed vector/raster inputs
  - Normalizes all inputs to 0-1 range before weighting
- **Returns**: Absolute path to final suitability raster

#### `publish_final_map(filepath: str) -> str`
- **Purpose**: Publish raster to GeoServer and get WMS details
- **Returns**: JSON with wmsUrl, layerName, bbox, and status

## 🔧 Setup Instructions

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Django Settings
Ensure `MEDIA_ROOT` is set in `settings.py`:
```python
MEDIA_ROOT = os.path.join(BASE_DIR, 'output')
```

### 3. Set Environment Variables
Create `.env` file with:
```
GROQ_API_KEY=your_groq_api_key_here
```

### 4. Start GeoServer (Optional)
For map publishing functionality:
```bash
# Download and start GeoServer on localhost:8080
# Default credentials: admin/geoserver
```

### 5. Run Django Server
```bash
python manage.py runserver
```

## 🧪 Testing

### Test Individual Components
```bash
cd /path/to/backend
python test_implementation.py
```

### Test Django Endpoints
```bash
# Start Django server first
python manage.py runserver

# In another terminal
python test_django_views.py
```

## 📡 API Usage

### Streaming Analysis Endpoint
```bash
curl -X POST http://localhost:8000/agent_app/stream_query_agent/ \
  -H "Content-Type: application/json" \
  -d '{"query": "Find suitable areas for affordable housing in Palo Alto"}'
```

### Response Format
The endpoint returns Server-Sent Events with the following event types:
- `start`: Analysis beginning
- `phase`: Current processing phase
- `tool_execution`: Tool being executed
- `thought`: Agent reasoning
- `message`: General messages
- `complete`: Final results with workflow summary

### Final Response Structure
```json
{
  "type": "complete",
  "message": "🎉 Geospatial analysis complete! Map published to GeoServer.",
  "total_steps": 5,
  "output_files": ["palo_alto_schools.geojson", "suitability_map.tif"],
  "workflow_log": [...],
  "reasoning_log": [...],
  "final_map_result": "{\"wmsUrl\": \"...\", \"layerName\": \"...\", \"bbox\": [...]}"
}
```

## 🐛 Troubleshooting

### Common Issues

1. **Import Errors**: Ensure all dependencies are installed
   ```bash
   pip install pystac-client stackstac rioxarray pyproj geoserver-restconfig
   ```

2. **STAC/DEM Data Issues**: 
   - Check internet connection
   - Verify place name geocoding works
   - Some areas might not have DEM coverage

3. **Open-Meteo API Issues**:
   - API is free but has rate limits
   - Check if place name can be geocoded

4. **Bhuvan Service Issues**:
   - Service might be temporarily down
   - Try different layer names
   - Check if place is within India

5. **GeoServer Publishing Issues**:
   - Ensure GeoServer is running on localhost:8080
   - Check default credentials (admin/geoserver)
   - Function will return mock response if GeoServer unavailable

## 🔄 Workflow Example

For query: "Find suitable housing areas in Palo Alto"

1. **AcquireVectorData**: Get schools (positive factor)
2. **AcquireVectorData**: Get noisy venues like bars (negative factor)  
3. **AcquireElevationData**: Get elevation data (flat areas preferred)
4. **PerformMultiCriteriaAnalysis**: Combine with weights [0.3, -0.4, 0.3]
5. **PublishFinalMap**: Publish to GeoServer and return WMS details

## 📊 Monitoring and Logging

The `WorkflowLoggingCallbackHandler` captures:
- **Workflow Log**: All tool executions with inputs/outputs
- **Reasoning Log**: Agent's decision-making process
- **Timing Information**: Execution timestamps
- **Error Handling**: Graceful failure handling with descriptive messages

This provides complete auditability and debugging capabilities for complex geospatial analyses.
