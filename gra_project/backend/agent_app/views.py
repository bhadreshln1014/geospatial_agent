from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
import os
import time
from .agent import setup_agent # Import from the local app folder
from .callbacks import WorkflowLoggingCallbackHandler

# --- Agent Initialization (Lazy Loading) ---
GRA_AGENT = None

def get_agent():
    """Initialize agent only when first needed (lazy loading)"""
    global GRA_AGENT
    if GRA_AGENT is None:
        print("▶️ Initializing Geospatial Reasoning Agent...")
        GRA_AGENT = setup_agent()
        print("✅ GRA Agent initialized and ready.")
    return GRA_AGENT

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
            # Get the agent (initializes on first use)
            agent = get_agent()
            
            # Create the workflow logging callback handler
            callback_handler = WorkflowLoggingCallbackHandler()
            
            # Send initial analysis start event
            yield f"data: {json.dumps({'type': 'start', 'message': '🤖 Starting geospatial analysis...', 'query': query})}\n\n"
            
            # Send planning phase notification
            yield f"data: {json.dumps({'type': 'phase', 'message': '📋 Analyzing requirements and acquiring data...', 'phase': 'planning'})}\n\n"
            
            # Use the .stream() method of the agent with callback handler
            stream = agent.stream({"input": query}, config={'callbacks': [callback_handler]})
            
            step_count = 0
            final_result = None
            
            for chunk in stream:
                try:
                    print(f"DEBUG: Chunk type: {type(chunk)}, Content: {chunk}")
                    
                    # Handle different types of chunks from LangChain
                    if isinstance(chunk, dict):
                        # Process dictionary chunks
                        enhanced_chunk = {}
                        
                        # Safely extract serializable data from chunk
                        for key, value in chunk.items():
                            try:
                                if hasattr(value, 'content'):  # AIMessage or similar
                                    content = str(value.content)
                                    enhanced_chunk[key] = content
                                    # Check if this contains the final JSON result
                                    if key == 'output' and 'wmsUrl' in content:
                                        final_result = content
                                elif hasattr(value, 'dict'):  # Pydantic models
                                    enhanced_chunk[key] = value.dict()
                                elif isinstance(value, (str, int, float, bool, type(None))):
                                    enhanced_chunk[key] = value
                                    # Check if this is the final JSON result
                                    if isinstance(value, str) and 'wmsUrl' in value:
                                        final_result = value
                                elif isinstance(value, list):
                                    # Handle lists (like actions, steps, messages)
                                    enhanced_chunk[key] = f"[{len(value)} items]"
                                else:
                                    # Convert to string for non-serializable objects
                                    enhanced_chunk[key] = str(value)
                            except Exception as e:
                                # Skip problematic values
                                enhanced_chunk[key] = f"<{type(value).__name__}>"
                                continue
                        
                        # Send reasoning or action messages only if we have useful content
                        if enhanced_chunk and any(isinstance(v, str) and len(v) > 10 for v in enhanced_chunk.values()):
                            enhanced_chunk['timestamp'] = time.time()
                            
                            # Detect tool execution from content
                            content_str = str(enhanced_chunk)
                            if any(tool in content_str for tool in ['AcquireVectorData', 'AcquireElevationData', 'AcquireGenericRasterData', 'AcquireBhuvanData', 'PerformBufferAnalysis', 'PerformMultiCriteriaAnalysis', 'PublishFinalMap']):
                                step_count += 1
                                yield f"data: {json.dumps({'type': 'tool_execution', 'message': f'🛠️ Step {step_count}: Executing geospatial operation...', 'step': step_count, 'timestamp': time.time()})}\n\n"
                            
                            yield f"data: {json.dumps({'type': 'thought', 'message': enhanced_chunk, 'timestamp': time.time()})}\n\n"
                    
                    else:
                        # Handle non-dict chunks (like AIMessage objects)
                        content = ""
                        if hasattr(chunk, 'content'):
                            content = chunk.content
                        elif hasattr(chunk, 'text'):
                            content = chunk.text
                        else:
                            content = str(chunk)
                        
                        if content and content.strip():  # Only send non-empty content
                            # Check if this is the final JSON result
                            if 'wmsUrl' in content:
                                final_result = content
                            
                            # Check if this looks like a tool execution
                            if any(tool in content for tool in ['AcquireVectorData', 'AcquireElevationData', 'AcquireGenericRasterData', 'AcquireBhuvanData', 'PerformBufferAnalysis', 'PerformMultiCriteriaAnalysis', 'PublishFinalMap']):
                                step_count += 1
                                yield f"data: {json.dumps({'type': 'tool_start', 'message': f'🛠️ Step {step_count}: Executing geospatial tool...', 'step': step_count, 'timestamp': time.time()})}\n\n"
                            
                            message_data = {
                                'type': 'message',
                                'message': content,
                                'timestamp': time.time()
                            }
                            yield f"data: {json.dumps(message_data)}\n\n"
                        
                except Exception as e:
                    print(f"Error processing chunk: {e}")
                    # Send error message to frontend but continue processing
                    error_data = {
                        'type': 'error',
                        'message': f'Stream processing issue (continuing...): {str(e)}',
                        'timestamp': time.time()
                    }
                    yield f"data: {json.dumps(error_data)}\n\n"

            # Get workflow summary from callback handler
            workflow_summary = callback_handler.get_summary()
            
            # Clean workflow and reasoning logs for JSON serialization
            clean_workflow_log = []
            for entry in workflow_summary.get('workflow_log', []):
                clean_entry = {}
                for key, value in entry.items():
                    try:
                        # Test if value is JSON serializable
                        json.dumps(value)
                        clean_entry[key] = value
                    except (TypeError, ValueError):
                        # Convert non-serializable values to strings
                        clean_entry[key] = str(value)
                clean_workflow_log.append(clean_entry)
            
            clean_reasoning_log = []
            for entry in workflow_summary.get('reasoning_log', []):
                clean_entry = {}
                for key, value in entry.items():
                    try:
                        # Test if value is JSON serializable
                        json.dumps(value)
                        clean_entry[key] = value
                    except (TypeError, ValueError):
                        # Convert non-serializable values to strings
                        clean_entry[key] = str(value)
                clean_reasoning_log.append(clean_entry)
            
            # Send final completion event with results summary
            from django.conf import settings
            output_dir = settings.MEDIA_ROOT  # Use Django's configured media root
            output_files = []
            if os.path.exists(output_dir):
                output_files = [f for f in os.listdir(output_dir) if f.endswith(('.tif', '.geojson'))]
            
            completion_data = {
                'type': 'complete', 
                'message': '🎉 Geospatial analysis complete! Map published to GeoServer.',
                'total_steps': step_count,
                'output_files': output_files,
                'workflow_log': clean_workflow_log,
                'reasoning_log': clean_reasoning_log,
                'final_map_result': final_result,
                'download_ready': True
            }
            
            # Final safety check for JSON serialization
            try:
                json.dumps(completion_data)
                yield f"data: {json.dumps(completion_data)}\n\n"
            except (TypeError, ValueError) as e:
                # Fallback response if there are still serialization issues
                fallback_data = {
                    'type': 'complete',
                    'message': '🎉 Geospatial analysis complete! Map published to GeoServer.',
                    'total_steps': step_count,
                    'output_files': output_files,
                    'final_map_result': final_result,
                    'download_ready': True,
                    'serialization_warning': f'Some data excluded due to serialization issues: {str(e)}'
                }
                yield f"data: {json.dumps(fallback_data)}\n\n"

        response = StreamingHttpResponse(event_stream_generator(), content_type="text/event-stream")
        response['Cache-Control'] = 'no-cache'
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
        from django.conf import settings
        output_dir = settings.MEDIA_ROOT  # Use Django's configured media root
        output_files = []
        if os.path.exists(output_dir):
            for filename in os.listdir(output_dir):
                if filename.endswith(('.tif', '.geojson')):
                    file_path = os.path.join(output_dir, filename)
                    file_size = os.path.getsize(file_path)
                    output_files.append({
                        'name': filename,
                        'size': file_size,
                        'type': 'raster' if filename.endswith('.tif') else 'vector'
                    })
        
        return JsonResponse({'files': output_files})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
