#!/usr/bin/env python3
"""
Test script to verify the geospatial agent implementation.
Run this script to test individual components before full integration.
"""

import os
import sys
import django
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# Now we can import Django components
from agent_app.tools import (
    acquire_vector_data,
    acquire_elevation_data,
    acquire_generic_raster_data,
    acquire_bhuvan_data,
    perform_buffer_analysis,
    perform_mca,
    publish_final_map
)
from agent_app.callbacks import WorkflowLoggingCallbackHandler
from agent_app.agent import setup_agent


def test_individual_tools():
    """Test individual tools to ensure they work correctly."""
    print("=" * 60)
    print("TESTING INDIVIDUAL TOOLS")
    print("=" * 60)
    
    # Test 1: Vector data acquisition
    print("\n1. Testing AcquireVectorData...")
    try:
        result = acquire_vector_data("schools in Palo Alto")
        print(f"   ✅ Vector data acquired: {result}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 2: Generic raster data (weather)
    print("\n2. Testing AcquireGenericRasterData (Temperature)...")
    try:
        result = acquire_generic_raster_data("Palo Alto", "temperature")
        print(f"   ✅ Temperature data acquired: {result}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 3: Elevation data (this might take longer)
    print("\n3. Testing AcquireElevationData...")
    try:
        result = acquire_elevation_data("Palo Alto")
        print(f"   ✅ Elevation data acquired: {result}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 4: Bhuvan data (might fail if service is down)
    print("\n4. Testing AcquireBhuvanData...")
    try:
        result = acquire_bhuvan_data("Delhi", "LULC_1011_250K:lu250k_1011_b")
        print(f"   ✅ Bhuvan data acquired: {result}")
    except Exception as e:
        print(f"   ❌ Error: {e}")


def test_callback_handler():
    """Test the callback handler."""
    print("\n" + "=" * 60)
    print("TESTING CALLBACK HANDLER")
    print("=" * 60)
    
    try:
        handler = WorkflowLoggingCallbackHandler()
        
        # Simulate some callbacks
        handler.on_llm_start({}, ["test prompt"])
        handler.on_tool_start({"name": "TestTool"}, "test_input")
        handler.on_tool_end("test_output")
        
        summary = handler.get_summary()
        print(f"   ✅ Callback handler working. Summary: {summary}")
    except Exception as e:
        print(f"   ❌ Error: {e}")


def test_agent_setup():
    """Test agent setup."""
    print("\n" + "=" * 60)
    print("TESTING AGENT SETUP")
    print("=" * 60)
    
    try:
        agent = setup_agent()
        print("   ✅ Agent setup successful")
        
        # Test that all tools are available
        tool_names = [tool.name for tool in agent.tools if hasattr(agent, 'tools')]
        print(f"   ✅ Available tools: {tool_names}")
    except Exception as e:
        print(f"   ❌ Error: {e}")


def test_mca_integration():
    """Test multi-criteria analysis with some sample data."""
    print("\n" + "=" * 60)
    print("TESTING MCA INTEGRATION")
    print("=" * 60)
    
    try:
        # First, create some sample data
        vector_file = acquire_vector_data("schools in Palo Alto")
        temp_file = acquire_generic_raster_data("Palo Alto", "temperature")
        
        if not vector_file.startswith("Error") and not temp_file.startswith("Error"):
            # Test MCA
            mca_config = {
                "files": [vector_file, temp_file],
                "weights": [0.6, 0.4],
                "output_name": "test_suitability"
            }
            
            result = perform_mca(str(mca_config).replace("'", '"'))
            print(f"   ✅ MCA completed: {result}")
            
            # Test publishing
            if not result.startswith("Error"):
                publish_result = publish_final_map(result)
                print(f"   ✅ Map publishing result: {publish_result}")
        else:
            print("   ⚠️  Skipping MCA test due to data acquisition issues")
    except Exception as e:
        print(f"   ❌ Error: {e}")


def main():
    """Run all tests."""
    print("🚀 Starting Geospatial Agent Implementation Tests")
    print("This will test all components before full integration.\n")
    
    # Test individual components
    test_individual_tools()
    test_callback_handler()
    test_agent_setup()
    test_mca_integration()
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print("✅ If you see mostly green checkmarks above, the implementation is working!")
    print("❌ If you see red X marks, check the error messages for troubleshooting.")
    print("⚠️  Some services (like Bhuvan) might be temporarily unavailable.")
    print("\nNext steps:")
    print("1. Start Django server: python manage.py runserver")
    print("2. Test the streaming endpoint with a sample query")
    print("3. Check that GeoServer is running for map publishing")


if __name__ == "__main__":
    main()
