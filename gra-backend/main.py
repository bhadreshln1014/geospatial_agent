import sys
import os
import json
from agent import setup_agent
from tools import (
    acquire_vector_data, acquire_elevation_data, acquire_generic_raster_data,
    perform_buffer_analysis, perform_mca
)

# A mapping from tool names the LLM uses to the actual Python functions
# This allows our script to execute the plan.
AVAILABLE_TOOLS = {
    "AcquireVectorData": acquire_vector_data,
    "AcquireElevationData": acquire_elevation_data,
    "AcquireGenericRasterData": acquire_generic_raster_data,
    "PerformBufferAnalysis": perform_buffer_analysis,
    "PerformMultiCriteriaAnalysis": perform_mca
}

def execute_workflow(workflow_plan: list) -> str:
    """
    Executes the workflow plan step by step, handling dependencies and parameter substitution.
    Returns the filepath of the final result.
    """
    print("\n" + "▶️" * 15 + " EXECUTING WORKFLOW " + "▶️" * 15 + "\n")
    
    step_outputs = {}  # Store outputs from each step for dependency resolution
    
    for step_index, step in enumerate(workflow_plan, 1):
        tool_name = step.get("tool_name")
        parameters = step.get("parameters", {})
        
        print(f"--- Step {step_index}: Executing tool '{tool_name}' ---")
        
        # Resolve parameter dependencies (replace ##PREVIOUS_STEP_X## placeholders)
        resolved_parameters = {}
        for param_name, param_value in parameters.items():
            if isinstance(param_value, str) and "##PREVIOUS_STEP_" in param_value:
                # Extract step number from placeholder
                import re
                matches = re.findall(r'##PREVIOUS_STEP_(\d+)##', param_value)
                for match in matches:
                    step_num = int(match)
                    if step_num in step_outputs:
                        param_value = param_value.replace(f"##PREVIOUS_STEP_{step_num}##", step_outputs[step_num])
                    else:
                        print(f"  ⚠️  WARNING: Step {step_num} output not found for parameter {param_name}")
            resolved_parameters[param_name] = param_value
        
        print(f"  > Calling tool with parameters: {resolved_parameters}")
        
        # Execute the tool
        if tool_name in AVAILABLE_TOOLS:
            try:
                tool_function = AVAILABLE_TOOLS[tool_name]
                
                # Call the function with unpacked parameters
                if len(resolved_parameters) == 1:
                    # Single parameter function
                    result = tool_function(list(resolved_parameters.values())[0])
                else:
                    # Multiple parameter function - use **kwargs
                    result = tool_function(**resolved_parameters)
                
                # Store the result for future steps
                step_outputs[step_index] = result
                print(f"  > Step {step_index} successful. Output: {result}\n")
                
            except Exception as e:
                print(f"  ❌ Step {step_index} failed: {e}\n")
                return f"Error executing step {step_index}: {e}"
        else:
            print(f"  ❌ Unknown tool: {tool_name}\n")
            return f"Error: Unknown tool '{tool_name}'"
    
    # Return the output of the final step
    final_result_path = step_outputs.get(len(workflow_plan), "No output from final step.")
    return final_result_path


def main():
    """
    Main function for the two-step Geospatial Reasoning Agent.
    1. Generates a JSON workflow plan.
    2. Executes that plan.
    """
    os.makedirs("output", exist_ok=True)

    if len(sys.argv) < 2:
        print("="*50)
        print("Geospatial Reasoning Agent (GRA) - Version 2")
        print("="*50)
        print("Usage: python main.py \"Your geospatial query in quotes\"")
        print("\nExample: python main.py \"Find the best areas for a new school in Palo Alto, CA. It should be away from bars and on flat land.\"")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    print(f"Processing query: \"{query}\"\n")

    try:
        # --- STEP 1: GENERATE THE PLAN ---
        print("=" * 20 + " STEP 1: GENERATING PLAN " + "=" * 20 + "\n")
        
        gra_agent = setup_agent()
        plan_response = gra_agent.invoke({"input": query})
        plan_str = plan_response['output']
        
        # Extract JSON from the response (it should be at the beginning)
        plan_json_str = plan_str.split('\n\n')[0].strip()  # Take first part before explanation
        
        try:
            workflow_plan = json.loads(plan_json_str)
        except json.JSONDecodeError:
            # If direct parsing fails, try to find JSON in the response
            import re
            json_match = re.search(r'\[.*\]', plan_str, re.DOTALL)
            if json_match:
                plan_json_str = json_match.group(0)
                workflow_plan = json.loads(plan_json_str)
            else:
                raise json.JSONDecodeError("No valid JSON found", plan_str, 0)
        
        print("\n✅ WORKFLOW PLAN GENERATED SUCCESSFULLY:")
        print(json.dumps(workflow_plan, indent=2))  # Pretty-print the JSON plan

        # --- STEP 2: EXECUTE THE PLAN ---
        final_map_path = execute_workflow(workflow_plan)

        print("\n" + "✅" * 25)
        print("✅ Agent workflow complete!")
        print(f"✅ Final map saved to: {final_map_path}")
        print("✅ You can now open this file in a GIS software like QGIS.")
        print("✅ The generated JSON workflow plan is a key deliverable.")
        print("✅" * 25)

    except json.JSONDecodeError as e:
        print("\n❌ CRITICAL ERROR: The LLM did not return a valid JSON plan. Please try rephrasing your query.")
        print(f"LLM Output:\n---\n{plan_str}\n---")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
