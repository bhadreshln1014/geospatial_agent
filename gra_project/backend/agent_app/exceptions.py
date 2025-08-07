"""
Custom exceptions for the GIS workflow system to ensure clear, predictable error handling.
"""

class ToolError(Exception):
    """Base class for all tool-related exceptions."""
    def __init__(self, message, tool_name="Unknown"):
        self.message = message
        self.tool_name = tool_name
        super().__init__(self.message)

class ToolValidationError(ToolError):
    """Raised for validation errors before a tool executes (e.g., bad parameters, file not found)."""
    pass

class ToolExecutionError(ToolError):
    """Raised for errors that occur during the execution of a tool."""
    pass
