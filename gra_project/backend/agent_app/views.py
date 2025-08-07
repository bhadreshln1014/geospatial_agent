from django.http import StreamingHttpResponse, JsonResponse, Http404, FileResponse
from django.views import View
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
import zipfile
import json
import os
import shutil
import geopandas as gpd
import rasterio
import rasterio.warp
from .agent import setup_planner_agent
from .models import AnalysisThread, ThreadMessage, UserDataLayer
from . import tools as gis_tools
from . import geoserver_utils
from django.http import JsonResponse

# --- LAZY AGENT & TOOL SETUP ---
_PLANNER_AGENT = None

def get_planner_agent(user_data_context: str):
    """
    Returns a planner agent configured with the specific user data context.
    This is no longer a simple singleton, as the context changes per request.
    """
    return setup_planner_agent(user_data_context)

TOOL_MAPPING = {
    "acquire_osm_data": gis_tools.acquire_osm_data,
    "acquire_dem_data": gis_tools.acquire_dem_data,
    "acquire_bhuvan_data": gis_tools.acquire_bhuvan_data,
    "filter_vector_by_attribute": gis_tools.filter_vector_by_attribute,
    "perform_buffer": gis_tools.perform_buffer,
    "calculate_slope": gis_tools.calculate_slope,
    "reclassify_raster": gis_tools.reclassify_raster,
    "calculate_proximity_raster": gis_tools.calculate_proximity_raster,
    "clip_data": gis_tools.clip_data,
    "rasterize_vector": gis_tools.rasterize_vector,
    "perform_weighted_overlay": gis_tools.perform_weighted_overlay,
    "compare_places_analysis": gis_tools.compare_places_analysis,
}

class UploadView(APIView):
    """Handles uploading of user-provided data layers, including zipped shapefiles."""
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        thread_id = request.data.get('thread_id')
        layer_name = request.data.get('name')
        data_type = request.data.get('data_type')
        file_obj = request.FILES.get('file')

        if not all([thread_id, layer_name, data_type, file_obj]):
            return Response({"error": "Missing required fields: thread_id, name, data_type, file"}, status=400)

        try:
            thread = AnalysisThread.objects.get(id=thread_id)
        except AnalysisThread.DoesNotExist:
            return Response({"error": "AnalysisThread not found"}, status=404)

        # Handle Zipped Shapefiles
        if file_obj.name.endswith('.zip'):
            if data_type != 'vector':
                return Response({"error": "ZIP uploads are only supported for vector data (Shapefiles)."}, status=400)
            
            zip_ref = zipfile.ZipFile(file_obj)
            shp_files = [f for f in zip_ref.namelist() if f.endswith('.shp')]
            if not shp_files:
                return Response({"error": "The uploaded ZIP archive does not contain a .shp file."}, status=400)

            # Create a unique directory for extraction to avoid conflicts
            extraction_dir_name = os.path.splitext(file_obj.name)[0]
            extraction_path = os.path.join(settings.MEDIA_ROOT, 'user_uploads', str(thread.id), extraction_dir_name)
            os.makedirs(extraction_path, exist_ok=True)
            zip_ref.extractall(extraction_path)
            
            # The main file path we save points to the extracted .shp file
            main_file_path = os.path.join(extraction_path, shp_files[0])
            relative_path = os.path.relpath(main_file_path, settings.MEDIA_ROOT)

            user_layer = UserDataLayer.objects.create(
                thread=thread, name=layer_name, data_type=data_type, file=relative_path
            )
            msg = "Shapefile uploaded and extracted successfully"
        else:
            # Handle single file uploads (GeoJSON, GeoTIFF, etc.)
            user_layer = UserDataLayer.objects.create(
                thread=thread, name=layer_name, data_type=data_type, file=file_obj
            )
            msg = "File uploaded successfully"

        return Response({
            "message": msg,
            "layer_id": user_layer.id,
            "layer_name": user_layer.name,
            "file_path": user_layer.file.url
        }, status=201)

class PlannerView(APIView):
    """Handles the planning stage: User Query -> AI-Generated Workflow Plan."""
    def post(self, request, *args, **kwargs):
        query = request.data.get('query')
        thread_id = request.data.get('thread_id')

        # Ensure a thread exists
        if thread_id:
            thread = AnalysisThread.objects.get(id=thread_id)
        else:
            thread = AnalysisThread.objects.create(title=query[:50])
        
        # NEW: Fetch and Format User Data Context
        user_layers = UserDataLayer.objects.filter(thread=thread)
        if user_layers:
            context_lines = [
                f"- Name: '{layer.name}', Type: {layer.data_type}, Reference ID: 'user_layer_{layer.id}'"
                for layer in user_layers
            ]
            user_data_context = "\n".join(context_lines)
        else:
            user_data_context = "No user-provided layers are available for this analysis."

        # Call the agent with the dynamic context
        planner_agent = get_planner_agent(user_data_context)
        response_model = planner_agent.invoke({"input": query})
        
        message = ThreadMessage.objects.create(
            thread=thread,
            user_query=query,
            agent_explanation=response_model.overall_reasoning,
            agent_workflow_plan=response_model.dict()
        )
        
        return Response({
            "thread_id": str(thread.id),
            "plan_id": str(message.id),
            "workflow_plan": response_model.dict()
        })

class ExecutorView(APIView):
    """Handles the execution stage: User-Approved Plan -> Streaming Log & Final Map."""
    
    def post(self, request, *args, **kwargs):
        """Accept execution parameters and store them for streaming."""
        thread_id = request.data.get('thread_id')
        message_id = request.data.get('message_id')
        edited_plan_dict = request.data.get('workflow_plan')

        try:
            message = ThreadMessage.objects.get(id=message_id)
            if edited_plan_dict:
                message.user_edited_workflow_plan = edited_plan_dict
                message.save()
            
            return Response({"status": "Execution started", "message_id": message_id})
        except ThreadMessage.DoesNotExist:
            return Response({"error": "Message not found"}, status=404)

class ConvertGpkgView(APIView):
    """Converts a GeoPackage file to a GeoJSON object."""

    def post(self, request, *args, **kwargs):
        source_file_path = request.data.get('source_path') # e.g., 'user_uploads/some_file.gpkg'
        if not source_file_path:
            return Response({"error": "source_path is required"}, status=400)

        full_source_path = os.path.join(settings.MEDIA_ROOT, source_file_path)
        if not os.path.exists(full_source_path):
            return Response({"error": "Source file not found"}, status=404)

        try:
            # Read the GeoPackage file with GeoPandas
            gdf = gpd.read_file(full_source_path)
            # Convert the GeoDataFrame to a GeoJSON string, then parse it into a Python dict
            geojson_data = json.loads(gdf.to_json())
            
            # Return the GeoJSON dictionary
            return JsonResponse(geojson_data)

        except Exception as e:
            return Response({"error": f"Failed to convert GeoPackage: {str(e)}"}, status=500)
        
class ExecutorStreamView(View):
    """Handles Server-Sent Events streaming for execution logs."""
    
    def get(self, request, *args, **kwargs):
        """Stream execution logs via Server-Sent Events."""
        thread_id = request.GET.get('thread_id')
        message_id = request.GET.get('message_id')
        
        def error_stream_generator(error_message):
            """Generate error message for EventSource."""
            yield f"data: {json.dumps({'type': 'error', 'content': error_message})}\n\n"
        
        def create_sse_response(generator):
            """Create SSE response with proper headers."""
            response = StreamingHttpResponse(generator, content_type="text/event-stream")
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'  # For nginx
            response['Access-Control-Allow-Origin'] = '*'  # Add CORS for EventSource
            response['Access-Control-Allow-Headers'] = 'Cache-Control'
            return response
        
        if not thread_id or not message_id:
            return create_sse_response(error_stream_generator("thread_id and message_id are required"))

        try:
            message = ThreadMessage.objects.get(id=message_id)
        except ThreadMessage.DoesNotExist:
            return create_sse_response(error_stream_generator("Message not found"))

        # Use the edited plan if available, otherwise use the original
        plan_dict = message.user_edited_workflow_plan or message.agent_workflow_plan
        if not plan_dict:
            return create_sse_response(error_stream_generator("No workflow plan found"))
            
        plan = plan_dict.get('plan', [])

        def event_stream_generator():
            """
            This generator executes the plan step-by-step and streams logs.
            It uses a dynamic parameter resolution system, avoiding hardcoded logic.
            """
            logs = []
            step_outputs = {}
            final_result = None

            # Clean output directory and set workflow context
            output_dir = settings.MEDIA_ROOT
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
            os.makedirs(output_dir)

            place_name = None
            if plan:
                # Find the first mention of 'place_name' to set context
                for step in plan:
                    for param in step.get('parameters', []):
                        if param.get('name') == 'place_name':
                            place_name = param.get('value')
                            break
                    if place_name:
                        break
            
            from .tools import set_workflow_context
            set_workflow_context(thread_id, place_name)
            print(f"WORKFLOW: Set context - Thread ID: {thread_id}, Place: {place_name}")

            try:
                for i, step in enumerate(plan):
                    step_num = i + 1
                    tool_name = step['tool_name']
                    raw_parameters = step.get('parameters', [])
                    params_for_call = {}

                    # --- DYNAMIC PARAMETER RESOLUTION ---
                    for param_detail in raw_parameters:
                        if not isinstance(param_detail, dict):
                            continue
                        
                        param_name = param_detail.get('name')
                        raw_value = param_detail.get('value')
                        
                        if param_name is None:
                            continue

                        # Helper function to resolve step/user layer references
                        def resolve_value(value):
                            if isinstance(value, str):
                                if value.startswith("##step_"):
                                    ref_step = int(value.split('_')[1])
                                    if ref_step not in step_outputs:
                                        raise KeyError(f"Invalid reference: Step {ref_step} has not been executed or produced no output.")
                                    return step_outputs[ref_step]
                                
                                elif value.startswith("user_layer_"):
                                    layer_id = value.replace("user_layer_", "")
                                    try:
                                        user_layer = UserDataLayer.objects.get(id=layer_id)
                                        return user_layer.file.path
                                    except UserDataLayer.DoesNotExist:
                                        raise FileNotFoundError(f"User layer with reference '{value}' not found.")
                            return value

                        # Resolve the parameter value. If it's a list, resolve any references inside it.
                        resolved_value = None
                        if isinstance(raw_value, list):
                            resolved_list = []
                            for item in raw_value:
                                # For weighted_overlay, resolve raster_path references within the list
                                if isinstance(item, dict) and 'raster_path' in item:
                                    resolved_item = item.copy()
                                    resolved_item['raster_path'] = resolve_value(item['raster_path'])
                                    resolved_list.append(resolved_item)
                                else:
                                    resolved_list.append(item) # Assumes other list items are literals
                            resolved_value = resolved_list
                        else:
                            resolved_value = resolve_value(raw_value)
                        
                        params_for_call[param_name] = resolved_value
                    
                    # --- RESILIENT RECLASSIFICATION LOGIC (from previous fix) ---
                    if tool_name == "reclassify_raster" and 'reclass_values' not in params_for_call:
                        for param_detail in raw_parameters:
                            if isinstance(param_detail, dict) and 'reclassification' in param_detail and param_detail['reclassification']:
                                raw_rules = param_detail['reclassification']
                                formatted_rules = [
                                    [rule.get('from_val'), rule.get('to_val'), rule.get('output_val'), rule.get('label', '')]
                                    for rule in raw_rules
                                ]
                                params_for_call['reclass_values'] = formatted_rules
                                break
                    
                    log_entry = {'type': 'log', 'content': f'▶️ Step {step_num}: Executing `{tool_name}`...'}
                    yield f"data: {json.dumps(log_entry)}\n\n"
                    
                    if tool_name not in TOOL_MAPPING:
                        raise NotImplementedError(f"Tool '{tool_name}' is not defined in TOOL_MAPPING.")
                        
                    tool_function = TOOL_MAPPING[tool_name]
                    result = tool_function(**params_for_call)

                    if isinstance(result, str) and result.lower().startswith("error:"):
                        raise Exception(result)

                    step_outputs[step_num] = result
                    log_entry = {'type': 'log', 'content': f'✅ Step {step_num} complete. Output: {os.path.basename(str(result))}'}
                    yield f"data: {json.dumps(log_entry)}\n\n"
                    
                    if i == len(plan) - 1:
                        final_result = result

            except Exception as e:
                step_num = locals().get('step_num', '?')
                tool_name = locals().get('tool_name', '?')
                error_message = f"❌ Workflow FAILED at Step {step_num} ({tool_name}): {str(e)}"
                log_entry = {'type': 'error', 'content': error_message}
                yield f"data: {json.dumps(log_entry)}\n\n"
                message.execution_log = logs + [log_entry]
                message.save()
                return

            message.execution_log = logs
            message.final_map_result = {'final_file_path': final_result} if final_result else None
            message.save()
            
            # ###############################################################
            # ### START: MODIFIED FINAL MESSAGE AND VISUALIZATION BLOCK   ###
            # ###############################################################
            if final_result and isinstance(final_result, str) and os.path.exists(final_result):
                try:
                    # --- PATH 1: Handle GeoJSON by sending data directly to the frontend ---
                    if final_result.lower().endswith('.geojson'):
                        yield f"data: {json.dumps({'type': 'log', 'content': 'Reading GeoJSON result to send to client...'})}\n\n"
                        
                        # Read the GeoJSON file content
                        with open(final_result, 'r') as f:
                            geojson_data = json.load(f)

                        # Calculate BBOX for Leaflet using GeoPandas
                        gdf = gpd.read_file(final_result)
                        b = gdf.to_crs(epsg=4326).total_bounds
                        bbox = [b[1], b[0], b[3], b[2]] # Format: [south, west, north, east]

                        # Prepare the payload for direct rendering on the client
                        direct_map_data = {
                            "type": 'vector',
                            "data": geojson_data,  # Embed the actual GeoJSON data
                            "bbox": bbox,
                            "name": os.path.basename(final_result),
                            "service_type": "geojson" # Special type to signal the frontend
                        }
                        
                        message.final_map_result = direct_map_data
                        message.save()
                        yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished! GeoJSON data sent to client.', 'map_result': direct_map_data})}\n\n"

                    # --- PATH 2: Handle Rasters and other formats by publishing to GeoServer ---
                    else:
                        base_name = os.path.splitext(os.path.basename(final_result))[0]
                        layer_name = f"{message.thread.id}_{base_name}".replace('-', '_')

                        if final_result.lower().endswith(('.tif', '.tiff')):
                            file_type = 'raster'
                            yield f"data: {json.dumps({'type': 'log', 'content': f'Publishing raster layer to GeoServer as `{layer_name}`...'})}\n\n"
                            qualified_layer_name = geoserver_utils.publish_geotiff(final_result, layer_name)
                            service_type = 'WMS'
                        else: # Handle other types like GPKG
                            file_type = 'vector'
                            yield f"data: {json.dumps({'type': 'log', 'content': f'Publishing vector layer to GeoServer as `{layer_name}`...'})}\n\n"
                            qualified_layer_name = geoserver_utils.publish_gpkg(final_result, layer_name)
                            service_type = 'WMS'
                        
                        # Calculate BBOX for Leaflet
                        bbox = None
                        if file_type == 'vector':
                            gdf = gpd.read_file(final_result)
                            b = gdf.to_crs(epsg=4326).total_bounds
                            bbox = [b[1], b[0], b[3], b[2]]
                        else: # raster
                            with rasterio.open(final_result) as src:
                                b = rasterio.warp.transform_bounds(src.crs, 'EPSG:4326', *src.bounds)
                                bbox = [b[1], b[0], b[3], b[2]]

                        geoserver_map_data = {
                            "service_type": service_type,
                            "layer_name": qualified_layer_name,
                            "geoserver_url": settings.GEOSERVER_SETTINGS['URL'],
                            "bbox": bbox,
                            "name": os.path.basename(final_result)
                        }
                        
                        message.final_map_result = geoserver_map_data
                        message.save()
                        yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished! Layer published to GeoServer.', 'map_result': geoserver_map_data})}\n\n"

                except Exception as e:
                    error_message = f"❌ FAILED during final result processing: {str(e)}"
                    yield f"data: {json.dumps({'type': 'error', 'content': error_message})}\n\n"
            
            # Handle case where the final result is a JSON object (e.g., from a statistics tool)
            elif final_result and isinstance(final_result, dict):
                message.final_map_result = {'stats_result': final_result}
                message.save()
                yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished!', 'stats_result': final_result})}\n\n"
            
            # Handle case where there is no final output
            else:
                yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished! No map output was generated.'})}\n\n"
        
        return create_sse_response(event_stream_generator())



class ThreadListView(APIView):
    """Handles listing and creating analysis threads."""
    
    def get(self, request, *args, **kwargs):
        """List all analysis threads."""
        threads = AnalysisThread.objects.all().order_by('-created_at')
        data = []
        for thread in threads:
            data.append({
                'id': str(thread.id),
                'title': thread.title,
                'created_at': thread.created_at.isoformat(),
            })
        return Response(data)
    
    def post(self, request, *args, **kwargs):
        """Create a new analysis thread."""
        title = request.data.get('title', 'New Analysis')
        thread = AnalysisThread.objects.create(title=title)
        return Response({
            'id': str(thread.id),
            'title': thread.title,
            'created_at': thread.created_at.isoformat(),
        }, status=201)


class ThreadDetailView(APIView):
    """Handles individual thread operations."""
    
    def get(self, request, thread_id, *args, **kwargs):
        """Get details for a specific thread."""
        try:
            thread = AnalysisThread.objects.get(id=thread_id)
            return Response({
                'id': str(thread.id),
                'title': thread.title,
                'created_at': thread.created_at.isoformat(),
            })
        except AnalysisThread.DoesNotExist:
            return Response({"error": "Thread not found"}, status=404)


class ThreadMessagesView(APIView):
    """Handles thread messages."""
    
    def get(self, request, thread_id, *args, **kwargs):
        """Get all messages for a thread."""
        try:
            thread = AnalysisThread.objects.get(id=thread_id)
            messages = ThreadMessage.objects.filter(thread=thread).order_by('timestamp')
            data = []
            for message in messages:
                data.append({
                    'id': str(message.id),
                    'user_query': message.user_query,
                    'agent_explanation': message.agent_explanation,
                    'agent_workflow_plan': message.agent_workflow_plan,
                    'execution_log': message.execution_log,
                    'final_map_result': message.final_map_result,
                    'timestamp': message.timestamp.isoformat(),
                })
            return Response(data)
        except AnalysisThread.DoesNotExist:
            return Response({"error": "Thread not found"}, status=404)


class ThreadLayersView(APIView):
    """Handles data layers for a thread."""
    
    def get(self, request, thread_id, *args, **kwargs):
        """Get all data layers for a thread."""
        try:
            thread = AnalysisThread.objects.get(id=thread_id)
            layers = UserDataLayer.objects.filter(thread=thread)
            data = []
            for layer in layers:
                data.append({
                    'id': str(layer.id),
                    'name': layer.name,
                    'data_type': layer.data_type,
                    'file_path': layer.file.url if layer.file else None,
                    'thread_id': str(layer.thread.id),
                })
            return Response(data)
        except AnalysisThread.DoesNotExist:
            return Response({"error": "Thread not found"}, status=404)
