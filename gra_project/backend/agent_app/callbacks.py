from langchain.callbacks.base import BaseCallbackHandler
from typing import Dict, List, Any, Optional
import uuid


class WorkflowLoggingCallbackHandler(BaseCallbackHandler):
    """
    Custom callback handler to capture agent workflow and reasoning logs.
    """
    
    def __init__(self):
        """Initialize the callback handler with empty logs."""
        self.workflow_log = []
        self.reasoning_log = []
        self.is_thinking = False
        
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        """Called when LLM starts generating."""
        self.is_thinking = True
        
    def on_llm_end(self, response, **kwargs: Any) -> None:
        """Called when LLM finishes generating."""
        if self.is_thinking:
            # Extract the thought/reasoning from the response
            thought = ""
            if hasattr(response, 'generations'):
                for generation in response.generations:
                    for gen in generation:
                        if hasattr(gen, 'text'):
                            thought += gen.text
                        elif hasattr(gen, 'message') and hasattr(gen.message, 'content'):
                            thought += gen.message.content
            elif hasattr(response, 'content'):
                thought = response.content
            else:
                thought = str(response)
            
            if thought.strip():
                self.reasoning_log.append({
                    'type': 'reasoning',
                    'content': thought.strip(),
                    'timestamp': kwargs.get('timestamp', None)
                })
            
            self.is_thinking = False
            
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> None:
        """Called when a tool starts executing."""
        tool_name = serialized.get('name', 'Unknown Tool')
        
        # Try to parse the input string to get arguments
        tool_args = input_str
        try:
            # If input_str is JSON-like, try to parse it
            if input_str.startswith('{') and input_str.endswith('}'):
                import json
                tool_args = json.loads(input_str)
            elif '=' in input_str:
                # Handle key=value format
                tool_args = dict(item.split('=', 1) for item in input_str.split(',') if '=' in item)
        except:
            # If parsing fails, keep original string
            pass
        
        # Create workflow entry
        workflow_entry = {
            'tool_name': tool_name,
            'args': tool_args,
            'run_id': kwargs.get('run_id', str(uuid.uuid4())),
            'timestamp': kwargs.get('timestamp', None)
        }
        
        self.workflow_log.append(workflow_entry)
        
    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Called when a tool finishes executing."""
        if self.workflow_log:
            # Add output to the most recent workflow entry
            self.workflow_log[-1]['output'] = output
            self.workflow_log[-1]['end_timestamp'] = kwargs.get('timestamp', None)
            
    def on_tool_error(self, error: Exception, **kwargs: Any) -> None:
        """Called when a tool encounters an error."""
        if self.workflow_log:
            # Add error to the most recent workflow entry
            self.workflow_log[-1]['error'] = str(error)
            self.workflow_log[-1]['end_timestamp'] = kwargs.get('timestamp', None)
            
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the logged workflow and reasoning."""
        return {
            'workflow_log': self.workflow_log,
            'reasoning_log': self.reasoning_log,
            'total_tools_used': len(self.workflow_log),
            'total_reasoning_steps': len(self.reasoning_log)
        }
        
    def clear_logs(self):
        """Clear all logs."""
        self.workflow_log = []
        self.reasoning_log = []
        self.is_thinking = False
