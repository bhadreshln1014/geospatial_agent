#!/usr/bin/env python3
"""
Quick validation script to test the fixed JSON serialization issues.
"""

import json
import sys
import os

# Add Django setup
sys.path.append('/mnt/e/geospatial_agent/gra_project/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from agent_app.callbacks import WorkflowLoggingCallbackHandler

def test_json_serialization():
    """Test that our callback handler data is JSON serializable."""
    print("🧪 Testing JSON Serialization Fixes")
    print("=" * 40)
    
    # Create callback handler
    handler = WorkflowLoggingCallbackHandler()
    
    # Simulate some workflow steps
    handler.on_llm_start({}, ["test prompt"])
    handler.on_tool_start({"name": "AcquireVectorData"}, "hospitals in Chennai")
    handler.on_tool_end("/path/to/file.geojson")
    handler.on_llm_end(type('MockResponse', (), {'content': 'Some reasoning text'})())
    
    # Get summary
    summary = handler.get_summary()
    
    try:
        # Test direct serialization
        json_str = json.dumps(summary)
        print("✅ Basic summary serialization: PASS")
        
        # Test the cleaned version (as used in views.py)
        clean_workflow_log = []
        for entry in summary.get('workflow_log', []):
            clean_entry = {}
            for key, value in entry.items():
                try:
                    json.dumps(value)
                    clean_entry[key] = value
                except (TypeError, ValueError):
                    clean_entry[key] = str(value)
            clean_workflow_log.append(clean_entry)
        
        json.dumps(clean_workflow_log)
        print("✅ Cleaned workflow log serialization: PASS")
        
        # Test completion data structure
        completion_data = {
            'type': 'complete',
            'message': '🎉 Analysis complete!',
            'total_steps': 2,
            'output_files': ['test.geojson'],
            'workflow_log': clean_workflow_log,
            'reasoning_log': summary.get('reasoning_log', []),
            'final_map_result': '{"wmsUrl": "test"}',
            'download_ready': True
        }
        
        json.dumps(completion_data)
        print("✅ Full completion data serialization: PASS")
        
        print("\n🎉 All JSON serialization tests PASSED!")
        print("The fixes should resolve the streaming response issues.")
        
    except Exception as e:
        print(f"❌ JSON serialization test FAILED: {e}")
        return False
    
    return True

def test_simple_tool_call():
    """Test a simple tool to ensure it works."""
    print("\n🛠️ Testing Simple Tool Call")
    print("=" * 30)
    
    try:
        from agent_app.tools import geocode_place
        lat, lon = geocode_place("Chennai")
        print(f"✅ Geocoding test: Chennai -> {lat:.2f}, {lon:.2f}")
        
        # Test that we can create completion data with this
        result_data = {
            'location': 'Chennai',
            'coordinates': [lat, lon],
            'status': 'success'
        }
        
        json.dumps(result_data)
        print("✅ Tool result serialization: PASS")
        
    except Exception as e:
        print(f"❌ Tool test failed: {e}")
        return False
    
    return True

def main():
    """Run validation tests."""
    print("🚀 Validating Geospatial Agent Fixes")
    print("This script tests the JSON serialization fixes.\n")
    
    success = True
    success &= test_json_serialization()
    success &= test_simple_tool_call()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ ALL TESTS PASSED!")
        print("The streaming endpoint should now work correctly.")
        print("\nNext steps:")
        print("1. Start Django server: python manage.py runserver")
        print("2. Import Postman collection and run tests")
        print("3. Try the 'Simple Suitability Analysis' test first")
    else:
        print("❌ SOME TESTS FAILED!")
        print("Check the error messages above for troubleshooting.")

if __name__ == "__main__":
    main()
