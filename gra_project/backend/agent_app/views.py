# views.py

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

# --- NEW: Import custom exceptions and Pydantic's own validation error ---
from .exceptions import ToolValidationError, ToolExecutionError
from pydantic import ValidationError

from .agent import setup_planner_agent, get_tool_schemas_as_text, WorkflowPlan
from .models import AnalysisThread, ThreadMessage, UserDataLayer
from . import tools as gis_tools
from langchain_core.output_parsers import PydanticOutputParser

# ... (get_planner_agent and TOOL_MAPPING remain unchanged) ...
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
    "filter_vector_by_attribute": gis_tools.filter_vector_by_attribute,
    "perform_buffer": gis_tools.perform_buffer,
    "calculate_slope": gis_tools.calculate_slope,
    "reclassify_raster": gis_tools.reclassify_raster,
    "calculate_proximity_raster": gis_tools.calculate_proximity_raster,
    "clip_data": gis_tools.clip_data,
    "rasterize_vector": gis_tools.rasterize_vector,
    "perform_weighted_overlay": gis_tools.perform_weighted_overlay,
    "calculate_vector_area": gis_tools.calculate_vector_area,
    "polygonize_raster": gis_tools.polygonize_raster,
    "subtract_rasters": gis_tools.subtract_rasters,
    "multiply_rasters": gis_tools.multiply_rasters,
}


class UploadView(APIView):
    # This view remains unchanged
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
    """
    Handles the planning stage: User Query -> AI-Generated Workflow Plan.
    This version constructs all necessary inputs for the prompt template.
    """
    def post(self, request, *args, **kwargs):
        query = request.data.get('query')
        thread_id = request.data.get('thread_id')

        # Ensure a thread exists
        if thread_id:
            try:
                thread = AnalysisThread.objects.get(id=thread_id)
            except AnalysisThread.DoesNotExist:
                return Response({"error": "Thread not found"}, status=404)
        else:
            thread = AnalysisThread.objects.create(title=query[:50])
        
        # --- NEW: Assemble all variables required by the prompt template ---
        
        # 1. Get user data context
        user_layers = UserDataLayer.objects.filter(thread=thread)
        if user_layers:
            context_lines = [
                f"- Name: '{layer.name}', Type: {layer.data_type}, Reference ID: 'user_layer_{layer.id}'"
                for layer in user_layers
            ]
            user_data_context = "\n".join(context_lines)
        else:
            user_data_context = "No user-provided layers are available for this analysis."

        # 2. Get the tool schemas as text
        tool_list_str = get_tool_schemas_as_text()

        # 3. Get the formatting instructions from the parser
        parser = PydanticOutputParser(pydantic_object=WorkflowPlan)
        format_instructions = parser.get_format_instructions() + "\n\nIMPORTANT: Your output MUST be a single, valid JSON object."

        try:
            # Get the planner agent (which is now just a chain)
            planner_agent = setup_planner_agent()
            
            # --- NEW: Invoke the chain with ALL required variables ---
            response_model = planner_agent.invoke({
                "input": query,
                "user_data_context": user_data_context,
                "tool_list_str": tool_list_str,
                "format_instructions": format_instructions
            })
            
            # Save the successful plan to the database
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
        except Exception as e:
            # This will now catch genuine LLM or parsing errors
            return Response({"error": f"Failed to generate a plan: {str(e)}"}, status=500)

class ExecutorView(APIView):
    # This view remains unchanged
    def post(self, request, *args, **kwargs):
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


class ExecutorStreamView(View):
    """Handles Server-Sent Events streaming with robust error handling."""
    
    def get(self, request, *args, **kwargs):
        thread_id = request.GET.get('thread_id')
        message_id = request.GET.get('message_id')
        
        def error_stream_generator(error_message):
            yield f"data: {json.dumps({'type': 'error', 'content': error_message})}\n\n"
        
        def create_sse_response(generator):
            response = StreamingHttpResponse(generator, content_type="text/event-stream")
            response['Cache-Control'] = 'no-cache'; response['X-Accel-Buffering'] = 'no'
            response['Access-Control-Allow-Origin'] = '*'; response['Access-Control-Allow-Headers'] = 'Cache-Control'
            return response
        
        if not thread_id or not message_id:
            return create_sse_response(error_stream_generator("thread_id and message_id are required"))

        try:
            message = ThreadMessage.objects.get(id=message_id)
        except ThreadMessage.DoesNotExist:
            return create_sse_response(error_stream_generator("Message not found"))

        plan_dict = message.user_edited_workflow_plan or message.agent_workflow_plan
        if not plan_dict or not plan_dict.get('plan'):
            return create_sse_response(error_stream_generator("No workflow plan found"))
            
        plan = plan_dict['plan']

        def event_stream_generator():
            logs, step_outputs, final_result = [], {}, None
            output_dir = settings.MEDIA_ROOT
            if os.path.exists(output_dir): shutil.rmtree(output_dir)
            os.makedirs(output_dir)
            place_name = next((p.get('value') for s in plan for p in s.get('parameters', []) if p.get('name') == 'place_name'), None)
            from .tools import set_workflow_context
            set_workflow_context(thread_id, place_name)

            try:
                for i, step in enumerate(plan):
                    step_num = i + 1
                    tool_name, raw_parameters = step['tool_name'], step.get('parameters', [])
                    params_for_call = {}

                    # --- DEFINITIVE PARAMETER RESOLUTION LOGIC ---
                    for param_detail in raw_parameters:
                        if not isinstance(param_detail, dict): continue
                        param_name, raw_value = param_detail.get('name'), param_detail.get('value')
                        if param_name is None: continue
                        
                        def resolve_value(value):
                            if isinstance(value, str):
                                if value.startswith("##step_"):
                                    ref_step = int(value.split('_')[1])
                                    if ref_step not in step_outputs: raise KeyError(f"Invalid reference: Step {ref_step} has not been executed or produced no output.")
                                    return step_outputs[ref_step]
                                elif value.startswith("user_layer_"):
                                    layer_id = value.replace("user_layer_", "")
                                    try: return UserDataLayer.objects.get(id=layer_id).file.path
                                    except UserDataLayer.DoesNotExist: raise FileNotFoundError(f"User layer '{value}' not found.")
                            return value

                        if isinstance(raw_value, list):
                            resolved_list = []
                            for item in raw_value:
                                if isinstance(item, dict) and 'raster_path' in item:
                                    resolved_item = item.copy()
                                    resolved_item['raster_path'] = resolve_value(item['raster_path'])
                                    resolved_list.append(resolved_item)
                                else:
                                    # --- THIS IS THE CRITICAL FIX ---
                                    # This correctly handles simple lists of values, like for multiply_rasters
                                    resolved_list.append(resolve_value(item))
                            params_for_call[param_name] = resolved_list
                        else:
                            params_for_call[param_name] = resolve_value(raw_value)
                    
                    # Resilient Reclassification Adapter
                    if tool_name == "reclassify_raster" and 'reclass_values' in params_for_call:
                        reclass_param = params_for_call['reclass_values']
                        if isinstance(reclass_param, list) and all(isinstance(item, dict) for item in reclass_param):
                            formatted_rules = [[r.get('from_val'), r.get('to_val'), r.get('output_val')] for r in reclass_param]
                            params_for_call['reclass_values'] = formatted_rules

                    log_entry = {'type': 'log', 'content': f'▶️ Step {step_num}: Executing `{tool_name}`...'}
                    yield f"data: {json.dumps(log_entry)}\n\n"
                    
                    if tool_name not in TOOL_MAPPING:
                        raise NotImplementedError(f"Tool '{tool_name}' is not defined in TOOL_MAPPING.")
                    
                    tool_function = TOOL_MAPPING[tool_name]
                    try:
                        result = tool_function(**params_for_call)
                    except ValidationError as e:
                        error_details = e.errors()[0]
                        param, msg = error_details['loc'][0], error_details['msg']
                        raise ToolValidationError(f"Invalid parameter '{param}': {msg}", tool_name=tool_name)
                    
                    step_outputs[step_num] = result
                    log_entry = {'type': 'log', 'content': f'✅ Step {step_num} complete. Output: {os.path.basename(str(result))}'}
                    yield f"data: {json.dumps(log_entry)}\n\n"
                    
                    if i == len(plan) - 1: final_result = result
            
            # --- Exception handling block is unchanged and correct ---
            except (ToolValidationError, ToolExecutionError) as e:
                step_num, tool_name_err = (locals().get('step_num', '?'), e.tool_name)
                error_message = f"❌ Workflow FAILED at Step {step_num} ({tool_name_err}): {e.message}"
                log_entry = {'type': 'error', 'content': error_message}
                yield f"data: {json.dumps(log_entry)}\n\n"
                message.execution_log = logs + [log_entry]; message.save()
                return
            except Exception as e:
                step_num, tool_name_err = (locals().get('step_num', '?'), locals().get('tool_name', 'Unknown'))
                error_message = f"❌ An unexpected system error occurred at Step {step_num} ({tool_name_err}): {str(e)}"
                log_entry = {'type': 'error', 'content': error_message}
                yield f"data: {json.dumps(log_entry)}\n\n"
                message.execution_log = logs + [log_entry]; message.save()
                return

            # --- Successful completion logic is unchanged and correct ---
            message.execution_log = logs
            message.final_map_result = {'final_file_path': final_result} if final_result else None
            message.save()
            if final_result and isinstance(final_result, str) and os.path.exists(final_result):
                relative_path = os.path.relpath(final_result, settings.MEDIA_ROOT)
                file_url = f"/media/{relative_path.replace(os.path.sep, '/')}"
                file_type = 'raster' if relative_path.lower().endswith(('.tif', '.tiff')) else 'vector'
                bbox = None
                try:
                    if file_type == 'vector':
                        gdf = gpd.read_file(final_result); gdf_wgs84 = gdf.to_crs(epsg=4326)
                        bounds = gdf_wgs84.total_bounds; bbox = [bounds[1], bounds[0], bounds[3], bounds[2]]
                    else:
                        with rasterio.open(final_result) as src:
                            bounds = src.bounds; b = rasterio.warp.transform_bounds(src.crs, 'EPSG:4326', *bounds)
                            bbox = [b[1], b[0], b[3], b[2]]
                except Exception as bbox_error: print(f"Could not calculate BBOX for {final_result}: {bbox_error}")
                final_map_data = {"url": file_url, "type": file_type, "bbox": bbox, "name": os.path.basename(relative_path)}
                yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished!', 'map_result': final_map_data})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished! No map output was generated.'})}\n\n"
        
        return create_sse_response(event_stream_generator())
# --- All other views (ServeMediaView, ThreadListView, etc.) remain unchanged ---
# ... (rest of your views.py) ...
class ServeMediaView(View):
    """A view to securely serve files from the MEDIA_ROOT."""
    def get(self, request, file_path, *args, **kwargs):
        full_path = os.path.join(settings.MEDIA_ROOT, file_path)
        
        # Security check to prevent directory traversal attacks
        if not os.path.abspath(full_path).startswith(os.path.abspath(settings.MEDIA_ROOT)):
            raise Http404("Forbidden")

        if os.path.exists(full_path):
            return FileResponse(open(full_path, 'rb'))
        else:
            raise Http404("File not found")


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