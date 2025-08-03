from django.http import StreamingHttpResponse, JsonResponse
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
import json
import os
import shutil
from .agent import setup_planner_agent
from .models import AnalysisThread, ThreadMessage
from . import tools as gis_tools

# --- LAZY AGENT & TOOL SETUP ---
_PLANNER_AGENT = None

def get_planner_agent():
    """Lazy initialization of the planner agent."""
    global _PLANNER_AGENT
    if _PLANNER_AGENT is None:
        _PLANNER_AGENT = setup_planner_agent()
    return _PLANNER_AGENT

TOOL_MAPPING = {
    "acquire_osm_data": gis_tools.acquire_osm_data,
    "acquire_dem_data": gis_tools.acquire_dem_data,
    "acquire_bhuvan_data": gis_tools.acquire_bhuvan_data,
    "filter_vector_by_attribute": gis_tools.filter_vector_by_attribute,
    "perform_buffer": gis_tools.perform_buffer,
    "calculate_slope": gis_tools.calculate_slope,
    "reclassify_raster": gis_tools.reclassify_raster,
    "calculate_proximity_raster": gis_tools.calculate_proximity_raster,
    "perform_weighted_overlay": gis_tools.perform_weighted_overlay,
    "publish_to_geoserver": gis_tools.publish_to_geoserver,
}

class PlannerView(APIView):
    """Handles the planning stage: User Query -> AI-Generated Workflow Plan."""
    def post(self, request, *args, **kwargs):
        query = request.data.get('query')
        thread_id = request.data.get('thread_id')

        thread = AnalysisThread.objects.get(id=thread_id) if thread_id else AnalysisThread.objects.create(title=query[:50])
        
        response_model = get_planner_agent().invoke({"input": query})
        
        message = ThreadMessage.objects.create(
            thread=thread,
            user_query=query,
            agent_explanation=response_model.overall_reasoning,
            agent_workflow_plan=response_model.dict()
        )
        
        return Response({
            "thread_id": thread.id,
            "plan_id": message.id,
            "workflow_plan": response_model.dict()
        })

class ExecutorView(APIView):
    """Handles the execution stage: User-Approved Plan -> Streaming Log & Final Map."""
    def post(self, request, *args, **kwargs):
        plan_id = request.data.get('plan_id')
        edited_plan_dict = request.data.get('workflow_plan')

        message = ThreadMessage.objects.get(id=plan_id)
        message.user_edited_workflow_plan = edited_plan_dict
        message.save()
        
        plan = edited_plan_dict.get('plan', [])

        def event_stream_generator():
            logs = []
            step_outputs = {}
            final_result = None

            # Clean output directory before starting
            output_dir = settings.MEDIA_ROOT
            if os.path.exists(output_dir): shutil.rmtree(output_dir)
            os.makedirs(output_dir)

            try:
                for i, step in enumerate(plan):
                    step_num = i + 1
                    tool_name = step['tool_name']
                    params_list = step['parameters']
                    params_for_call = {p['name']: p['value'] for p in params_list}

                    for key, value in params_for_call.items():
                        if isinstance(value, str) and value.startswith("##step_"):
                            ref_step = int(value.split('_')[1])
                            params_for_call[key] = step_outputs[ref_step]
                    
                    log_entry = {'type': 'log', 'content': f'▶️ Step {step_num}: Executing `{tool_name}`...'}
                    logs.append(log_entry)
                    yield f"data: {json.dumps(log_entry)}\n\n"
                    
                    tool_function = TOOL_MAPPING[tool_name]
                    result = tool_function(**params_for_call)

                    if isinstance(result, str) and result.lower().startswith("error:"):
                        raise Exception(result)

                    step_outputs[step_num] = result
                    log_entry = {'type': 'log', 'content': f'✅ Step {step_num} complete. Output: {result}'}
                    logs.append(log_entry)
                    yield f"data: {json.dumps(log_entry)}\n\n"
                    
                    if i == len(plan) - 1:
                        final_result = result

            except Exception as e:
                log_entry = {'type': 'error', 'content': f'❌ Workflow FAILED at Step {step_num} ({tool_name}): {e}'}
                logs.append(log_entry)
                yield f"data: {json.dumps(log_entry)}\n\n"
                message.execution_log = logs
                message.save()
                return

            message.execution_log = logs
            message.final_map_result = final_result
            message.save()
            
            yield f"data: {json.dumps({'type': 'complete', 'content': '🎉 Workflow Finished!', 'map_result': final_result})}\n\n"
        
        return StreamingHttpResponse(event_stream_generator(), content_type="text/event-stream")