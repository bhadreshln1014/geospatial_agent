# Postman Testing Guide for Geospatial Reasoning Agent

## 🚀 Quick Setup

### 1. Import Collections and Environment
1. Open Postman
2. Click **Import** 
3. Import these files:
   - `Geospatial_Agent_Tests.postman_collection.json`
   - `Geospatial_Agent_Environment.postman_environment.json`
4. Select the **Geospatial Agent Environment** from the environment dropdown

### 2. Start Django Server
```bash
cd /mnt/e/geospatial_agent/gra_project/backend
python manage.py runserver
```

### 3. Run Tests
- **Individual Tests**: Click on any request and hit **Send**
- **Full Test Suite**: Click **Run Collection** to run all tests

## 📋 Test Collection Overview

### Core Functionality Tests

#### 1. **Simple Suitability Analysis**
- **Purpose**: Tests basic multi-criteria analysis workflow
- **Query**: "Find suitable areas for affordable housing in Palo Alto"
- **Expected Tools**: AcquireVectorData, PerformMultiCriteriaAnalysis, PublishFinalMap
- **Success Criteria**: 
  - Status 200
  - Streaming events received
  - Final map result with WMS URL

#### 2. **Weather Analysis Query**
- **Purpose**: Tests Open-Meteo API integration
- **Query**: "Analyze temperature patterns in Chennai"
- **Expected Tools**: AcquireGenericRasterData (temperature)
- **Success Criteria**: Temperature data acquisition confirmed

#### 3. **Elevation Analysis Query**
- **Purpose**: Tests Copernicus DEM data acquisition
- **Query**: "Find flat areas in Davis using elevation data"
- **Expected Tools**: AcquireElevationData
- **Success Criteria**: DEM data acquisition confirmed

#### 4. **Bhuvan Data Query (India)**
- **Purpose**: Tests ISRO Bhuvan platform integration
- **Query**: "Analyze land use patterns in Delhi using Bhuvan LULC data"
- **Expected Tools**: AcquireBhuvanData
- **Note**: May fail if Bhuvan service is unavailable

#### 5. **Complex Multi-Source Analysis**
- **Purpose**: Tests full workflow with multiple data sources
- **Query**: "Create comprehensive suitability map for parks in San Francisco"
- **Expected Tools**: Multiple data acquisition tools + MCA + PublishFinalMap
- **Success Criteria**: Multiple tools executed, final map published

### Utility Tests

#### 6. **Get Output Files**
- **Purpose**: Lists generated files from previous analyses
- **Method**: GET request
- **Success Criteria**: JSON response with file list

### Error Handling Tests

#### 7. **Error Handling Test**
- **Purpose**: Tests empty query handling
- **Expected**: 400 error or graceful handling

#### 8. **Invalid JSON Test**
- **Purpose**: Tests malformed request handling
- **Expected**: 400/500 error

## 🔍 Understanding the Responses

### Streaming Response Format
The agent returns Server-Sent Events (SSE) with these event types:

```
data: {"type": "start", "message": "🤖 Starting geospatial analysis...", "query": "..."}

data: {"type": "phase", "message": "📋 Analyzing requirements...", "phase": "planning"}

data: {"type": "tool_execution", "message": "🛠️ Step 1: Executing geospatial operation...", "step": 1}

data: {"type": "thought", "message": {...}, "timestamp": 1691234567.89}

data: {"type": "complete", "message": "🎉 Analysis complete!", "final_map_result": "...", "workflow_log": [...]}
```

### Final Completion Event Structure
```json
{
  "type": "complete",
  "message": "🎉 Geospatial analysis complete! Map published to GeoServer.",
  "total_steps": 3,
  "output_files": ["chennai_hospitals.geojson", "suitability_map.tif"],
  "workflow_log": [
    {
      "tool_name": "AcquireVectorData",
      "args": "hospitals in Chennai",
      "output": "/path/to/file.geojson"
    }
  ],
  "reasoning_log": [...],
  "final_map_result": "{\"wmsUrl\": \"http://localhost:8080/geoserver/wms\", \"layerName\": \"geospatial:layer_name\", \"bbox\": [...]}",
  "download_ready": true
}
```

## 🧪 Automated Test Validation

Each test includes automated validations:

- ✅ **HTTP Status Checks**: Ensures proper response codes
- ✅ **Content-Type Validation**: Verifies streaming headers
- ✅ **Event Stream Parsing**: Validates SSE format
- ✅ **Tool Execution Detection**: Confirms expected tools were used
- ✅ **Completion Verification**: Ensures analysis finished successfully
- ✅ **Final Result Validation**: Checks for WMS URL in final response

## 🐛 Troubleshooting Common Issues

### 1. Connection Refused
**Issue**: `Connection refused` or `ECONNREFUSED`
**Solution**: 
- Ensure Django server is running: `python manage.py runserver`
- Check that server is on port 8000
- Verify environment variables are set correctly

### 2. Timeout Errors
**Issue**: Requests timeout after 30 seconds
**Solution**:
- Increase timeout in Postman settings
- Some operations (especially DEM data) can take several minutes
- Check internet connection for external API calls

### 3. Tool Execution Failures
**Issue**: Tools return error messages
**Solutions**:
- **OSM Data**: Check place name spelling and availability
- **Open-Meteo**: Verify internet connection, API might have rate limits
- **Copernicus DEM**: Area might not have coverage, check coordinates
- **Bhuvan**: Service may be temporarily down

### 4. GeoServer Publishing Issues
**Issue**: "401 Unauthorized" when publishing to GeoServer
**Solutions**:
- Start GeoServer: Download from [geoserver.org](http://geoserver.org)
- Default URL: `http://localhost:8080/geoserver`
- Default credentials: `admin/geoserver`
- Agent will return mock response if GeoServer unavailable

### 5. JSON Serialization Errors
**Issue**: "Object not JSON serializable"
**Solution**: Recent fix should handle this - restart Django server

## 📊 Performance Expectations

### Typical Response Times:
- **Vector Data (OSM)**: 5-15 seconds
- **Weather Data (Open-Meteo)**: 2-5 seconds  
- **Elevation Data (Copernicus DEM)**: 30-120 seconds
- **Bhuvan Data**: 10-30 seconds (if available)
- **Multi-Criteria Analysis**: 5-10 seconds
- **GeoServer Publishing**: 2-5 seconds

### Data Volume Expectations:
- Vector files: 1KB - 10MB (depending on area and feature density)
- Raster files: 100KB - 50MB (depending on resolution and area)
- Total analysis: Multiple files totaling 1-100MB

## 🎯 Success Indicators

A successful test should show:
1. ✅ **Status 200** for all requests
2. ✅ **Multiple streaming events** received
3. ✅ **Tool execution messages** for expected tools
4. ✅ **Completion event** with final map result
5. ✅ **Valid WMS URL** in final result
6. ✅ **Generated files** visible in output files endpoint

## 📝 Test Results Logging

Postman Console will show:
- Individual test results (✅ pass / ❌ fail)
- Event counts and types received
- Tool execution confirmations
- Performance timing information
- Any error messages or warnings

Use **View** → **Show Postman Console** to monitor detailed test execution.
