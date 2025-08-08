# --- START OF FILE views.py (Corrected) ---

from django.http import StreamingHttpResponse, JsonResponse, Http404, FileResponse
from django.views import View
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
import zipfile, json, os, shutil, geopandas as gpd, rasterio, rasterio.warp
from .exceptions import ToolValidationError, ToolExecutionError
from pydantic import ValidationError
from .agent import setup_planner_agent, get_tool_schemas_as_text, WorkflowPlan
from .models import AnalysisROI, AnalysisThread, ThreadMessage, UserDataLayer
from . import tools as gis_tools
from . import geoserver_utils
from django.http import JsonResponse
# Ensure all tools are registered
from .tools import get_data_from_ps4
from langchain_core.output_parsers import PydanticOutputParser

# --- Dynamically load the tool mapping from the registry ---
TOOL_MAPPING = gis_tools.TOOL_REGISTRY

class UploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    def post(self, request, *args, **kwargs):
        thread_id, layer_name, data_type, file_obj = request.data.get('thread_id'), request.data.get('name'), request.data.get('data_type'), request.FILES.get('file')
        if not all([thread_id, layer_name, data_type, file_obj]): return Response({"error": "Missing required fields"}, status=400)
        try: thread = AnalysisThread.objects.get(id=thread_id)
        except AnalysisThread.DoesNotExist: return Response({"error": "Thread not found"}, status=404)
        user_layer = UserDataLayer.objects.create(thread=thread, name=layer_name, data_type=data_type, file=file_obj)
        return Response({"message": "File uploaded", "layer_id": str(user_layer.id), "file_path": user_layer.file.url}, status=201)

class PlannerView(APIView):
    def post(self, request, *args, **kwargs):
        query, thread_id = request.data.get('query'), request.data.get('thread_id')
        if thread_id:
            try: thread = AnalysisThread.objects.get(id=thread_id)
            except AnalysisThread.DoesNotExist: return Response({"error": "Thread not found"}, status=404)
        else: thread = AnalysisThread.objects.create(title=query[:50])

        # --- START: ADDED ROI CONTEXT LOGIC ---
        roi_context_message = "No user-defined Region of Interest (ROI) has been provided. The analysis should cover the entire extent of the selected datasets unless a specific location name is mentioned in the query."
        try:
            if AnalysisROI.objects.filter(thread=thread).exists():
                roi_context_message = "A user-defined Region of Interest (ROI) has been provided. Your plan MUST use the `clip_data_to_roi` tool as the first step after loading any data layer to clip it to this ROI."
        except Exception as e:
            # If the database check fails, proceed without ROI context.
            print(f"Warning: Could not check for ROI. Proceeding without it. Error: {e}")
        # --- END: ADDED ROI CONTEXT LOGIC ---

        # Try to load info.json from PS4 directory
        ps4_info_path = os.path.join(settings.BASE_DIR, "PS4", "info.json")
        user_data_context = None
        try:
            with open(ps4_info_path, "r", encoding="utf-8") as f:
                user_data_context = f.read()
        except Exception:
            # Fallback to previous behavior if info.json is missing or unreadable
            user_layers = UserDataLayer.objects.filter(thread=thread)
            context_lines = [f"- Name: '{layer.name}', Type: {layer.data_type}, Reference ID: 'user_layer_{layer.id}'" for layer in user_layers]
            user_data_context = "\n".join(context_lines) if context_lines else "No user-provided layers are available."
        
        tool_list_str, parser = get_tool_schemas_as_text(), PydanticOutputParser(pydantic_object=WorkflowPlan)
        format_instructions = parser.get_format_instructions() + "\n\nIMPORTANT: Your output MUST be a single, valid JSON object."
        
        try:
            response_model = setup_planner_agent().invoke({"input": query, "user_data_context": user_data_context, "roi_context": roi_context_message, "tool_list_str": tool_list_str, "format_instructions": format_instructions})
            message = ThreadMessage.objects.create(thread=thread, user_query=query, agent_explanation=response_model.overall_reasoning, agent_workflow_plan=response_model.dict())
            return Response({"thread_id": str(thread.id), "plan_id": str(message.id), "workflow_plan": response_model.dict()})
        except Exception as e: return Response({"error": f"Failed to generate a plan: {str(e)}"}, status=500)

class ExecutorView(APIView):
    def post(self, request, *args, **kwargs):
        message_id, plan_dict = request.data.get('message_id'), request.data.get('workflow_plan')
        try:
            message = ThreadMessage.objects.get(id=message_id)
            if plan_dict: message.user_edited_workflow_plan = plan_dict; message.save()
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
    def get(self, request, *args, **kwargs):
        message_id = request.GET.get('message_id')
        def create_sse_response(generator):
            response = StreamingHttpResponse(generator, content_type="text/event-stream")
            response['Cache-Control']='no-cache'; response['X-Accel-Buffering']='no'; response['Access-Control-Allow-Origin']='*';
            return response
        try: message = ThreadMessage.objects.get(id=message_id)
        except ThreadMessage.DoesNotExist: return create_sse_response(iter([f"data: {json.dumps({'type': 'error', 'content': 'Message not found'})}\n\n"]))
        
        plan = (message.user_edited_workflow_plan or message.agent_workflow_plan).get('plan')
        if not plan: return create_sse_response(iter([f"data: {json.dumps({'type': 'error', 'content': 'No workflow plan found'})}\n\n"]))

        def event_stream_generator():
            step_outputs = {}
            place_name = next((p['value'] for s in plan for p in s['parameters'] if p['name'] == 'place_name'), "default_place")
            gis_tools.set_workflow_context(str(message.thread.id), place_name)
            
            final_result = None # Variable to hold the final result after the loop

            try:
                for i, step in enumerate(plan):
                    step_num, tool_name, params = i + 1, step['tool_name'], {}
                    
                    def resolve_value(value):
                        if isinstance(value, str):
                            if value.startswith("##step_"):
                                resolve_step_num = int(value.split('_')[1].split('##')[0])
                                return step_outputs.get(resolve_step_num, "")
                            if value.startswith("user_layer_"):
                                layer_id = value.replace("user_layer_", "")
                                try:
                                    return UserDataLayer.objects.get(id=layer_id).file.path
                                except UserDataLayer.DoesNotExist:
                                    raise ValueError(f"User layer {layer_id} not found")
                        elif isinstance(value, list) and all(isinstance(item, dict) for item in value):
                            return [
                                gis_tools.WeightedOverlayInput(
                                    raster_path=resolve_value(item['raster_path']),
                                    weight=float(item['weight'])
                                ) 
                                for item in value
                            ]
                        return value
                    
                    for p_detail in step.get('parameters', []): params[p_detail['name']] = resolve_value(p_detail['value'])
                    if tool_name == "reclassify_raster":
                        reclass_raw = params.get('reclass_values', [])
                        if isinstance(reclass_raw, list) and all(isinstance(item, dict) for item in reclass_raw):
                            params['reclass_values'] = [
                                [float(item['from_val']), float(item['to_val']), float(item['output_val'])]
                                for item in reclass_raw
                            ]
                        elif isinstance(reclass_raw, list) and all(isinstance(item, list) for item in reclass_raw):
                            pass
                        else:
                            raise ValueError(f"Invalid reclass_values format: {reclass_raw}")

                    yield f"data: {json.dumps({'type': 'log', 'content': f'▶️ Step {step_num}: Executing `{tool_name}`...'})}\n\n"
                    if tool_name not in TOOL_MAPPING: raise NotImplementedError(f"Tool '{tool_name}' not defined.")
                    
                    result = TOOL_MAPPING[tool_name](**params)
                    step_outputs[step_num] = result
                    final_result = result # Update final_result in each iteration
                    
                    log_content = os.path.basename(str(result)) if isinstance(result, str) else result
                    yield f"data: {json.dumps({'type': 'log', 'content': f'✅ Step {step_num} complete. Output: {log_content}'})}\n\n"

            except (ToolValidationError, ToolExecutionError) as e:
                error_message = f"❌ FAILED at Step {locals().get('step_num', '?')} ({e.tool_name}): {e.message}"
                yield f"data: {json.dumps({'type': 'error', 'content': error_message})}\n\n"; return
            except Exception as e:
                error_message = f"❌ UNEXPECTED error at Step {locals().get('step_num', '?')} ({locals().get('tool_name', '?')}): {str(e)}"
                yield f"data: {json.dumps({'type': 'error', 'content': error_message})}\n\n"; return
            
            # --- START: CORRECTED FINAL MESSAGE AND VISUALIZATION BLOCK ---
            try:
                # Case 1: The final result is a file path (string)
                if isinstance(final_result, str) and os.path.exists(final_result):
                    if final_result.lower().endswith('.geojson'):
                        yield f"data: {json.dumps({'type': 'log', 'content': 'Reading GeoJSON result to send to client...'})}\n\n"
                        with open(final_result, 'r') as f: geojson_data = json.load(f)
                        gdf = gpd.read_file(final_result); b = gdf.to_crs(epsg=4326).total_bounds; bbox = [b[1], b[0], b[3], b[2]]
                        map_data = {"type": 'vector', "data": geojson_data, "bbox": bbox, "name": os.path.basename(final_result), "service_type": "geojson"}
                        message.final_map_result = map_data; message.save()
                        yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished! GeoJSON data sent to client.', 'map_result': map_data})}\n\n"
                    else:
                        base_name = os.path.splitext(os.path.basename(final_result))[0]
                        layer_name = f"{message.thread.id}_{base_name}".replace('-', '_')
                        service_type = 'WMS' # Default service type
                        
                        if final_result.lower().endswith(('.tif', '.tiff')):
                            file_type = 'raster'
                            yield f"data: {json.dumps({'type': 'log', 'content': f'Publishing raster layer to GeoServer as `{layer_name}`...'})}\n\n"
                            qualified_layer_name = geoserver_utils.publish_geotiff(final_result, layer_name)
                        else:
                            file_type = 'vector'
                            yield f"data: {json.dumps({'type': 'log', 'content': f'Publishing vector layer to GeoServer as `{layer_name}`...'})}\n\n"
                            qualified_layer_name = geoserver_utils.publish_gpkg(final_result, layer_name)
                        
                        bbox = None
                        if file_type == 'vector':
                            gdf = gpd.read_file(final_result); b = gdf.to_crs(epsg=4326).total_bounds; bbox = [b[1], b[0], b[3], b[2]]
                        else:
                            with rasterio.open(final_result) as src: b = rasterio.warp.transform_bounds(src.crs, 'EPSG:4326', *src.bounds); bbox = [b[1], b[0], b[3], b[2]]
                        
                        map_data = {"service_type": service_type, "layer_name": qualified_layer_name, "geoserver_url": settings.GEOSERVER_SETTINGS['URL'], "bbox": bbox, "name": os.path.basename(final_result)}
                        message.final_map_result = map_data; message.save()
                        yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished! Layer published to GeoServer.', 'map_result': map_data})}\n\n"
                
                # Case 2: The final result is a dictionary (e.g., statistics)
                elif isinstance(final_result, dict):
                    message.final_map_result = {'stats_result': final_result}
                    message.save()
                    yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished!', 'stats_result': final_result})}\n\n"
                
                # Case 3: No valid output was generated
                else:
                    yield f"data: {json.dumps({'type': 'complete', 'content': 'Workflow Finished! No map output was generated.'})}\n\n"
            
            except Exception as e:
                error_message = f"❌ FAILED during final result processing: {str(e)}"
                yield f"data: {json.dumps({'type': 'error', 'content': error_message})}\n\n"
            # --- END: CORRECTED FINAL MESSAGE AND VISUALIZATION BLOCK ---

        return create_sse_response(event_stream_generator())


class ThreadListView(APIView):
    def get(self, request, *args, **kwargs):
        threads = AnalysisThread.objects.all().order_by('-created_at')
        return Response([{'id': str(t.id), 'title': t.title, 'created_at': t.created_at.isoformat()} for t in threads])
    
    def post(self, request, *args, **kwargs):
        thread = AnalysisThread.objects.create(title=request.data.get('title', 'New Analysis'))
        return Response({'id': str(thread.id), 'title': thread.title, 'created_at': thread.created_at.isoformat()}, status=201)

class ThreadDetailView(APIView):
    def get(self, request, thread_id, *args, **kwargs):
        try:
            thread = AnalysisThread.objects.get(id=thread_id)
            return Response({'id': str(thread.id), 'title': thread.title, 'created_at': thread.created_at.isoformat()})
        except AnalysisThread.DoesNotExist:
            return Response({"error": "Thread not found"}, status=404)

class ThreadMessagesView(APIView):
    def get(self, request, thread_id, *args, **kwargs):
        try:
            thread = AnalysisThread.objects.get(id=thread_id)
            messages = ThreadMessage.objects.filter(thread=thread).order_by('timestamp')
            data = [{'id': str(m.id), 'user_query': m.user_query, 'agent_explanation': m.agent_explanation, 'agent_workflow_plan': m.agent_workflow_plan, 'execution_log': m.execution_log, 'final_map_result': m.final_map_result, 'timestamp': m.timestamp.isoformat()} for m in messages]
            return Response(data)
        except AnalysisThread.DoesNotExist:
            return Response({"error": "Thread not found"}, status=404)

class ThreadLayersView(APIView):
    def get(self, request, thread_id, *args, **kwargs):
        try:
            thread = AnalysisThread.objects.get(id=thread_id)
            layers = UserDataLayer.objects.filter(thread=thread)
            data = [{'id': str(layer.id), 'name': layer.name, 'data_type': layer.data_type, 'file_path': layer.file.url if layer.file else None} for layer in layers]
            return Response(data)
        except AnalysisThread.DoesNotExist:
            return Response({"error": "Thread not found"}, status=404)

class RoiView(APIView):
    def post(self, request, *args, **kwargs):
        thread_id = request.data.get('thread_id')
        roi_geometry = request.data.get('roi')
        if not thread_id or not roi_geometry:
            return Response({"error": "thread_id and roi are required"}, status=400)
        try:
            thread = AnalysisThread.objects.get(id=thread_id)
        except AnalysisThread.DoesNotExist:
            return Response({"error": "Thread not found"}, status=404)
        geometry_data = roi_geometry.get('geometry')
        if not geometry_data:
            return Response({"error": "Invalid GeoJSON."}, status=400)
        roi, created = AnalysisROI.objects.update_or_create(
            thread=thread,
            defaults={'geometry': geometry_data}
        )
        message = "ROI created" if created else "ROI updated"
        return Response({"message": f"{message} successfully"}, status=201 if created else 200)

    def delete(self, request, *args, **kwargs):
        thread_id = request.data.get('thread_id')
        if not thread_id:
            return Response({"error": "thread_id is required"}, status=400)
        try:
            AnalysisROI.objects.get(thread__id=thread_id).delete()
            return Response({"message": "ROI deleted successfully"}, status=200)
        except AnalysisROI.DoesNotExist:
            return Response({"message": "No ROI found to delete"}, status=200)