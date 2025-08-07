# --- START OF FILE views.py ---

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
from .models import AnalysisThread, ThreadMessage, UserDataLayer
from . import tools as gis_tools
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
            response_model = setup_planner_agent().invoke({"input": query, "user_data_context": user_data_context, "tool_list_str": tool_list_str, "format_instructions": format_instructions})
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
        except ThreadMessage.DoesNotExist: return Response({"error": "Message not found"}, status=404)

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
            
            try:
                for i, step in enumerate(plan):
                    step_num, tool_name, params = i + 1, step['tool_name'], {}
                    
                    def resolve_value(value):
                        if isinstance(value, str):
                            if value.startswith("##step_"):
                                step_num = int(value.split('_')[1].split('##')[0])
                                return step_outputs.get(step_num, "")
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
                            # Already correct
                            pass
                        else:
                            raise ValueError(f"Invalid reclass_values format: {reclass_raw}")

                    yield f"data: {json.dumps({'type': 'log', 'content': f'▶️ Step {step_num}: Executing `{tool_name}`...'})}\n\n"
                    if tool_name not in TOOL_MAPPING: raise NotImplementedError(f"Tool '{tool_name}' not defined.")
                    
                    result = TOOL_MAPPING[tool_name](**params)
                    step_outputs[step_num], final_content = result, result if isinstance(result, dict) else os.path.basename(str(result))
                    yield f"data: {json.dumps({'type': 'log', 'content': f'✅ Step {step_num} complete. Output: {final_content}'})}\n\n"
                    if i == len(plan) - 1: message.final_map_result = {'final_output': result}
            except (ToolValidationError, ToolExecutionError) as e:
                error_message = f"❌ FAILED at Step {locals().get('step_num', '?')} ({e.tool_name}): {e.message}"
                log_entry = {'type': 'error', 'content': error_message}
                yield f"data: {json.dumps(log_entry)}\n\n"
                message.save(); return
            except Exception as e:
                error_message = f"❌ UNEXPECTED error at Step {locals().get('step_num', '?')} ({locals().get('tool_name', '?')}): {str(e)}"
                log_entry = {'type': 'error', 'content': error_message}
                yield f"data: {json.dumps(log_entry)}\n\n"
                message.save(); return
            
            message.save()
            final_output = message.final_map_result.get('final_output') if message.final_map_result else None

            if isinstance(final_output, dict):
                yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished!', 'stats_result': final_output})}\n\n"
            elif isinstance(final_output, str) and os.path.exists(final_output):
                relative_path = os.path.relpath(final_output, settings.MEDIA_ROOT)
                file_url, file_type = request.build_absolute_uri(f"/media/{relative_path.replace(os.path.sep, '/')}"), 'raster' if relative_path.lower().endswith('.tif') else 'vector'
                metadata, bbox = {}, None
                try:
                    if file_type == 'vector':
                        gdf = gpd.read_file(final_output); b = gdf.to_crs(epsg=4326).total_bounds; bbox = [b[1], b[0], b[3], b[2]]
                        metadata.update({'crs': gdf.crs.to_string(), 'feature_count': len(gdf)})
                    else:
                        with rasterio.open(final_output) as src:
                            b = rasterio.warp.transform_bounds(src.crs, 'EPSG:4326', *src.bounds); bbox = [b[1], b[0], b[3], b[2]]
                            band = src.read(1); metadata.update({'crs': src.crs.to_string(), 'resolution': src.res, 'min_value': float(band.min()), 'max_value': float(band.max())})
                except Exception as e: print(f"Could not calculate BBOX/Metadata: {e}")
                
                map_data = {"url": file_url, "type": file_type, "bbox": bbox, "name": os.path.basename(relative_path), "metadata": metadata}
                yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished!', 'map_result': map_data})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'complete', 'content': 'Workflow Finished! No map output was generated.'})}\n\n"
        
        return create_sse_response(event_stream_generator())

class ServeMediaView(View):
    def get(self, request, file_path, *args, **kwargs):
        full_path = os.path.join(settings.MEDIA_ROOT, file_path)
        if not os.path.abspath(full_path).startswith(os.path.abspath(settings.MEDIA_ROOT)): raise Http404
        if os.path.exists(full_path): return FileResponse(open(full_path, 'rb'))
        else: raise Http404

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