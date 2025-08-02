Of course. This is the definitive migration plan. It will guide you step-by-step to transform your "V2" command-line project into a complete, full-stack Django application with real-time Chain-of-Thought streaming to a Next.js frontend.

We will build upon your existing V2 logic, porting it into a robust web architecture.

### **High-Level Migration Strategy**

1.  **Foundation:** Create a new Django project structure.
2.  **Backend Porting:** Move your existing `agent.py` and `tools.py` into a dedicated Django app.
3.  **API Creation:** Replace your `main.py` orchestrator with Django "views" that handle both standard and streaming API requests.
4.  **Visualization Setup:** Configure GeoServer via Docker to serve styled map layers.
5.  **Frontend Build:** Create a new Next.js application that consumes the streaming CoT and displays the final map from GeoServer.

---

### **Phase 1: Create the Django Project & Port Backend Logic**

**Objective:** Lay the foundation for the web application and move your existing code into it.

**Step 1: Create the Project Structure**
1.  In a new, clean directory for your full-stack project, run:
    ```bash
    # Install Django if you haven't already
    pip install django djangorestframework

    # Create the project and the agent app
    django-admin startproject gra_project .
    python manage.py startapp agent_app
    ```
2.  **Copy Files:** From your V2 `gra-backend` folder, copy the following files into the new `agent_app/` directory:
    *   `tools.py`
    *   `agent.py`
3.  **Copy `.env`:** Copy your `.env` file to the root of the new `gra_project` directory (at the same level as `manage.py`).
4.  **Create `requirements.txt`:** In the project root, create a `requirements.txt` file with all dependencies.
    ```txt
    # Django
    django
    djangorestframework

    # LangChain & LLM
    langchain
    langchain-groq
    python-dotenv

    # Geospatial & Data
    geopandas
    rasterio
    osmnx
    shapely
    scipy
    numpy
    requests
    pystac-client
    stackstac
    rioxarray

    # Web Server & Visualization
    fastapi  # Not strictly needed but good practice for type hints
    uvicorn
    python-multipart
    geoserver-rest
    ```
    **Action:** Run `pip install -r requirements.txt`.

**Step 2: Configure Django Settings**
1.  Open `gra_project/settings.py`.
2.  Add `'agent_app'` to your `INSTALLED_APPS` list.

---

### **Phase 2: Build the Django API Endpoints**

**Objective:** Create the views and URLs that will expose your agent's functionality to the web.

**Step 1: Create the API Views in `agent_app/views.py`**
*This file is the new "brain" of your backend's web interface. It replaces your V2 `main.py` logic.*
**Action:** Replace the entire content of `agent_app/views.py`.

**File: `agent_app/views.py`**
```python
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
import os
import shutil
import time
from .agent import setup_agent # Import from the local app folder

# --- Agent Initialization (Happens Once on Server Start) ---
print("▶️ Initializing Geospatial Reasoning Agent...")
GRA_AGENT = setup_agent()
print("✅ GRA Agent initialized and ready.")

@require_POST
@csrf_exempt
def stream_query_agent(request):
    """
    Handles a query and streams the agent's full execution process (CoT)
    back to the client using Server-Sent Events (SSE).
    """
    try:
        data = json.loads(request.body)
        query = data.get('query')
        if not query:
            return JsonResponse({'error': 'Query not provided'}, status=400)

        print(f"▶️ Received STREAMING query: \"{query}\"")

        # The generator function that will yield events
        def event_stream_generator():
            # Send initial analysis start event
            yield f"data: {json.dumps({'type': 'start', 'message': '🤖 Starting geospatial analysis...', 'query': query})}\n\n"
            
            # Send planning phase notification
            yield f"data: {json.dumps({'type': 'phase', 'message': '📋 STEP 1: Generating workflow plan...', 'phase': 'planning'})}\n\n"
            
            # Use the .stream() method of the agent, which handles the full CoT
            stream = GRA_AGENT.stream({"input": query})
            
            step_count = 0
            for chunk in stream:
                # Enhance chunks with user-friendly messages
                enhanced_chunk = chunk.copy()
                
                # Detect tool usage and add friendly messages
                if 'tool' in chunk:
                    tool_name = chunk.get('tool', '')
                    step_count += 1
                    
                    # Map tool names to user-friendly messages
                    tool_messages = {
                        'AcquireVectorData': f"📍 Step {step_count}: Acquiring location data from OpenStreetMap...",
                        'AcquireElevationData': f"🏔️ Step {step_count}: Getting terrain elevation data...",
                        'AcquireGenericRasterData': f"🗺️ Step {step_count}: Acquiring additional geospatial data...",
                        'PerformBufferAnalysis': f"📏 Step {step_count}: Creating proximity zones...",
                        'PerformMultiCriteriaAnalysis': f"⚖️ Step {step_count}: Running multi-criteria analysis..."
                    }
                    
                    if tool_name in tool_messages:
                        yield f"data: {json.dumps({'type': 'tool_start', 'message': tool_messages[tool_name], 'tool': tool_name, 'step': step_count})}\n\n"
                
                # Forward the original chunk with enhancements
                enhanced_chunk['timestamp'] = time.time()
                sse_message = f"data: {json.dumps(enhanced_chunk)}\n\n"
                yield sse_message
                
                # Add completion messages for successful tool calls
                if 'tool_call_id' in chunk and 'error' not in chunk:
                    yield f"data: {json.dumps({'type': 'tool_complete', 'message': '✅ Step completed successfully', 'step': step_count})}\n\n"

            # Send final completion event with results summary
            output_files = []
            if os.path.exists('output'):
                output_files = [f for f in os.listdir('output') if f.endswith(('.tif', '.geojson'))]
            
            completion_data = {
                'type': 'complete', 
                'message': '🎉 Geospatial analysis complete!',
                'total_steps': step_count,
                'output_files': output_files,
                'download_ready': True
            }
            yield f"data: {json.dumps(completion_data)}\n\n"

        response = StreamingHttpResponse(event_stream_generator(), content_type="text/event-stream")
        response['Cache-Control'] = 'no-cache'
        response['Access-Control-Allow-Origin'] = '*'  # Enable CORS for frontend
        response['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    except Exception as e:
        print(f"❌ An error occurred: {e}")
        # Cannot return a streaming response on error, so use JSON
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def get_output_files(request):
    """
    Returns a list of available output files for download.
    """
    try:
        output_files = []
        if os.path.exists('output'):
            for filename in os.listdir('output'):
                if filename.endswith(('.tif', '.geojson')):
                    file_path = os.path.join('output', filename)
                    file_size = os.path.getsize(file_path)
                    output_files.append({
                        'name': filename,
                        'size': file_size,
                        'type': 'raster' if filename.endswith('.tif') else 'vector'
                    })
        
        return JsonResponse({'files': output_files})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
```

**Step 2: Define URL Routing**
**Action:** Create a new file `agent_app/urls.py`.

**File: `agent_app/urls.py`**
```python
from django.urls import path
from . import views

urlpatterns = [
    # Streaming endpoint for real-time CoT
    path('stream_query/', views.stream_query_agent, name='stream_query_agent'),
    # Endpoint to get available output files
    path('output_files/', views.get_output_files, name='get_output_files'),
]
```

**Action:** Modify the main project's `urls.py`.

**File: `gra_project/urls.py`**
```python
from django.contrib import admin
from django.urls import path, include # Add 'include'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('agent_app.urls')), # Route all /api/ requests to our agent_app
]
```

**Step 3: Run Initial Django Commands**
```bash
python manage.py migrate
python manage.py runserver
```
Your Django backend is now live and ready to stream at `http://localhost:8000/api/stream_query/`.

---

### **Phase 3: Build the Next.js Frontend with Real-Time CoT Display**

**Objective:** Create a modern, interactive frontend that displays the agent's Chain-of-Thought in real-time.

**Step 1: Create the Next.js Project**
```bash
# In a new directory (parallel to your Django project)
npx create-next-app@latest gra-frontend
cd gra-frontend

# Install additional dependencies
npm install leaflet react-leaflet axios
npm install --save-dev @types/leaflet
```

**Step 2: Create the Main Analysis Component**
**File: `components/GeospatialAnalyzer.tsx`**
```typescript
'use client'
import { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';

// Dynamically import map component to avoid SSR issues
const MapViewer = dynamic(() => import('./MapViewer'), { ssr: false });

interface CoTMessage {
  type: string;
  message: string;
  tool?: string;
  step?: number;
  timestamp?: number;
  output_files?: string[];
  total_steps?: number;
}

export default function GeospatialAnalyzer() {
  const [query, setQuery] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [messages, setMessages] = useState<CoTMessage[]>([]);
  const [outputFiles, setOutputFiles] = useState<string[]>([]);

  const startAnalysis = async () => {
    if (!query.trim()) return;
    
    setIsAnalyzing(true);
    setMessages([]);
    setOutputFiles([]);

    try {
      const response = await fetch('http://localhost:8000/api/stream_query/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query }),
      });

      if (!response.body) throw new Error('No response body');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              setMessages(prev => [...prev, data]);
              
              if (data.type === 'complete' && data.output_files) {
                setOutputFiles(data.output_files);
              }
            } catch (e) {
              console.error('Error parsing SSE data:', e);
            }
          }
        }
      }
    } catch (error) {
      console.error('Analysis error:', error);
      setMessages(prev => [...prev, {
        type: 'error',
        message: '❌ Analysis failed. Please try again.'
      }]);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const getMessageIcon = (type: string) => {
    switch (type) {
      case 'start': return '🚀';
      case 'phase': return '📋';
      case 'tool_start': return '🛠️';
      case 'tool_complete': return '✅';
      case 'complete': return '🎉';
      case 'error': return '❌';
      default: return '💭';
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-4xl font-bold text-center mb-8 text-gray-800">
          🌍 Geospatial Reasoning Agent
        </h1>
        
        {/* Query Input */}
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <div className="flex gap-4">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask me about geospatial analysis... (e.g., 'Find the best areas for a school in Palo Alto')"
              className="flex-1 p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              disabled={isAnalyzing}
            />
            <button
              onClick={startAnalysis}
              disabled={isAnalyzing || !query.trim()}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {isAnalyzing ? '🔄 Analyzing...' : '🚀 Start Analysis'}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Chain of Thought Display */}
          <div className="bg-white rounded-lg shadow-md p-6">
            <h2 className="text-2xl font-semibold mb-4 text-gray-800">
              🧠 Chain of Thought
            </h2>
            <div className="space-y-3 max-h-96 overflow-y-auto">
              {messages.length === 0 && !isAnalyzing && (
                <p className="text-gray-500 italic">
                  Chain-of-thought will appear here during analysis...
                </p>
              )}
              {messages.map((msg, idx) => (
                <div key={idx} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                  <span className="text-xl">{getMessageIcon(msg.type)}</span>
                  <div className="flex-1">
                    <p className="text-gray-800">{msg.message}</p>
                    {msg.timestamp && (
                      <p className="text-xs text-gray-500 mt-1">
                        {new Date(msg.timestamp * 1000).toLocaleTimeString()}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Map Viewer */}
          <div className="bg-white rounded-lg shadow-md p-6">
            <h2 className="text-2xl font-semibold mb-4 text-gray-800">
              🗺️ Results Map
            </h2>
            {outputFiles.length > 0 ? (
              <div>
                <MapViewer outputFiles={outputFiles} />
                <div className="mt-4">
                  <h3 className="font-semibold mb-2">Generated Files:</h3>
                  <ul className="space-y-1">
                    {outputFiles.map((file, idx) => (
                      <li key={idx} className="text-sm text-blue-600">
                        📄 {file}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <div className="h-64 bg-gray-100 rounded-lg flex items-center justify-center">
                <p className="text-gray-500">Map will appear here after analysis</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
```

**Step 3: Create the Map Viewer Component**
**File: `components/MapViewer.tsx`**
```typescript
'use client'
import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix for default markers in react-leaflet
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

interface MapViewerProps {
  outputFiles: string[];
}

export default function MapViewer({ outputFiles }: MapViewerProps) {
  const [geoJsonData, setGeoJsonData] = useState<any>(null);
  const [mapCenter, setMapCenter] = useState<[number, number]>([37.4419, -122.1430]); // Palo Alto default

  useEffect(() => {
    // Load the first GeoJSON file for display
    const geoJsonFile = outputFiles.find(file => file.endsWith('.geojson'));
    if (geoJsonFile) {
      fetch(`http://localhost:8000/output/${geoJsonFile}`)
        .then(response => response.json())
        .then(data => {
          setGeoJsonData(data);
          // Center map on the data bounds if available
          if (data.features && data.features.length > 0) {
            const bounds = L.geoJSON(data).getBounds();
            setMapCenter([bounds.getCenter().lat, bounds.getCenter().lng]);
          }
        })
        .catch(error => console.error('Error loading GeoJSON:', error));
    }
  }, [outputFiles]);

  return (
    <MapContainer
      center={mapCenter}
      zoom={12}
      style={{ height: '300px', width: '100%' }}
      className="rounded-lg"
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      {geoJsonData && (
        <GeoJSON
          data={geoJsonData}
          style={{
            color: '#3388ff',
            weight: 2,
            fillOpacity: 0.6
          }}
        />
      )}
    </MapContainer>
  );
}
```

**Step 4: Update the Main Page**
**File: `app/page.tsx`**
```typescript
import GeospatialAnalyzer from '@/components/GeospatialAnalyzer';

export default function Home() {
  return <GeospatialAnalyzer />;
}
```

**Step 5: Run the Frontend**
```bash
npm run dev
```

Your frontend will be available at `http://localhost:3000`.

---

### **Phase 4: Testing the Complete System**

**Step 1: Start Both Services**
```bash
# Terminal 1: Django Backend
cd gra_project
python manage.py runserver

# Terminal 2: Next.js Frontend  
cd gra-frontend
npm run dev
```

**Step 2: Test the Complete Flow**
1. Open `http://localhost:3000`
2. Enter a query: "Find the best areas for a school in Palo Alto, CA"
3. Watch the real-time Chain-of-Thought display
4. See the generated map and download files

---

You have now successfully migrated from a command-line script to a robust, scalable, and interactive full-stack web application with real-time feedback, meeting all the advanced requirements of the hackathon.

---

Of course. The plan you've provided is excellent and very detailed. To make it truly "final" and production-ready for the hackathon, we only need to make a few critical refinements. These changes address potential robustness issues, CORS configuration, and the visualization gap between raster and vector data.

Here are the **only the changes and additions required** to perfect the migration plan you've posted.

---

### **1. Backend Changes (Django Project)**

#### **1.1. Enhance CORS Configuration (Robustness)**

Using the dedicated `django-cors-headers` package is cleaner and more reliable than setting headers manually.

**Action:** In your `gra-backend` (now `gra_project`) virtual environment:
```bash
pip install django-cors-headers
```
**Action:** Add `django-cors-headers` to your `requirements.txt`.

**Action:** Modify `gra_project/settings.py`.

**File: `gra_project/settings.py`**
```python
# In INSTALLED_APPS, add 'corsheaders' before 'agent_app'
INSTALLED_APPS = [
    # ...
    'corsheaders',
    'agent_app',
]

# In MIDDLEWARE, add CorsMiddleware near the top
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    # ...
]

# Add this new section at the end of the file
# --- CORS CONFIGURATION ---
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",  # Your Next.js frontend
]
# Or for more permissive local development:
# CORS_ALLOW_ALL_ORIGINS = True
```
**Action:** Now you can safely **remove** this line from `agent_app/views.py`, as the middleware will handle it:
`response['Access-Control-Allow-Origin'] = '*'`

---

#### **1.2. Enable Serving of Output Files (Critical Fix)**

The frontend needs a way to fetch the generated `.geojson` and `.tif` files. Django does not do this by default in development.

**Action:** Modify `gra_project/settings.py` and `gra_project/urls.py`.

**File: `gra_project/settings.py`**
```python
# Add these lines at the very end of the file
import os

# --- MEDIA FILE CONFIGURATION FOR SERVING GENERATED OUTPUTS ---
MEDIA_URL = '/output/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'output')
```

**File: `gra_project/urls.py`**
```python
from django.contrib import admin
from django.urls import path, include
from django.conf import settings         # <-- ADD THIS IMPORT
from django.conf.urls.static import static # <-- ADD THIS IMPORT

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('agent_app.urls')),
]

# --- ADD THIS BLOCK AT THE END ---
# This serves files from MEDIA_ROOT in development mode.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```
This critical fix ensures that a frontend request to `http://localhost:8000/output/my_file.geojson` will now work correctly.

---

### **2. Frontend Changes (Next.js Project)**

#### **2.1. Refine `GeospatialAnalyzer.tsx` for Clarity**

The current plan has a great UI. We'll make a small tweak to better handle the distinction between vector and raster outputs.

**Action:** Modify `components/GeospatialAnalyzer.tsx`.

**File: `components/GeospatialAnalyzer.tsx`**
```typescript
// ... inside the component, in the JSX return statement ...

// Find the section that renders the output files list.
// Replace the existing <ul> with this more informative version.

<div className="mt-4">
  <h3 className="font-semibold mb-2">Generated Files:</h3>
  <ul className="space-y-1">
    {outputFiles.map((file, idx) => (
      <li key={idx} className="text-sm text-blue-600 flex items-center justify-between">
        <span>📄 {file}</span>
        {/* Add a helpful hint for raster files */}
        {file.endsWith('.tif') && (
          <span className="text-xs font-medium bg-yellow-100 text-yellow-800 px-2 py-1 rounded-full">
            View in QGIS/ArcGIS
          </span>
        )}
      </li>
    ))}
  </ul>
</div>
```
This change doesn't alter functionality but greatly improves user clarity. It explicitly tells the user that while a `.tif` file was successfully created, it needs to be viewed in desktop software, while the `.geojson` (if present) is shown on the map.

---

### **3. Re-integrating GeoServer (The "Pro" Step for Raster Visualization)**

The posted plan bypasses GeoServer, meaning raster results (`.tif`) are not visualized. To create the most impressive demo, you should use GeoServer.

**Action:** This requires reverting to the full GeoServer-integrated architecture. The changes are primarily on the backend.

1.  **Modify `agent.py`:** Ensure the **final step** in the agent's prompt is to use a `PublishFinalMap` tool.
2.  **Add `publish_to_geoserver` tool to `tools.py`:** This function connects to GeoServer and publishes the final `.tif` or `.geojson`.
3.  **Modify `agent_app/views.py`:** The `event_stream_generator` must parse the final output from the agent, which will be the JSON response from `publish_to_geoserver` (containing `layerName`, `bbox`, `wmsUrl`). It should yield this as a final, distinct event type, e.g., `{'type': 'map_result', 'data': ...}`.
4.  **Modify `components/GeospatialAnalyzer.tsx`:** The `startAnalysis` function needs to listen for this new `map_result` event and store the received data in a new state variable, e.g., `const [mapLayerInfo, setMapLayerInfo] = useState(null);`.
5.  **Modify `components/MapViewer.tsx`:** This component should be updated to conditionally render a `<WMSTileLayer>` using the `mapLayerInfo` state, instead of the `<GeoJSON>` layer.

This "pro" step is the most significant change from the plan you posted, but it's the key to visually demonstrating the full power of your Multi-Criteria Analysis.

---

### **Summary of Essential Changes**

To make the provided plan fully functional and robust:

1.  **Fix Static File Serving in Django:** This is non-negotiable for the map viewer to work.
2.  **Implement Robust CORS:** Use the `django-cors-headers` package.
3.  **Acknowledge Raster Outputs on Frontend:** Add a small UI hint for `.tif` files.
4.  **(Highly Recommended)** Re-integrate the GeoServer workflow to enable live visualization of your most impressive raster analysis results.