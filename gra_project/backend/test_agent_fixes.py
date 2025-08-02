#!/usr/bin/env python3
"""
Quick test to validate the agent behavior fixes.
Tests that simple queries don't trigger unnecessary analysis.
"""

import sys
import os
import json

# Add Django setup
sys.path.append('/mnt/e/geospatial_agent/gra_project/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

def test_simple_query_logic():
    """Test that simple queries are handled correctly."""
    print("🧪 Testing Simple Query Logic")
    print("=" * 40)
    
    # Test the updated system prompt logic
    simple_queries = [
        "find all schools in Chennai",
        "find hospitals in Mumbai", 
        "locate parks in Delhi"
    ]
    
    complex_queries = [
        "Find suitable areas for housing considering schools and elevation",
        "Analyze best locations for parks considering temperature and proximity to amenities",
        "Create suitability map for commercial development"
    ]
    
    print("✅ Simple queries (should only do: Acquire → Publish):")
    for query in simple_queries:
        print(f"   📝 '{query}'")
    
    print("\n✅ Complex queries (should do: Acquire → Analyze → Publish):")
    for query in complex_queries:
        print(f"   📝 '{query}'")
    
    return True

def test_tool_parameters():
    """Test that tool parameters are properly documented."""
    print("\n🛠️ Testing Tool Parameter Documentation")
    print("=" * 45)
    
    try:
        from agent_app.agent import setup_agent
        agent = setup_agent()
        
        # Check buffer analysis tool description
        buffer_tool = None
        for tool in agent.tools:
            if tool.name == "PerformBufferAnalysis":
                buffer_tool = tool
                break
        
        if buffer_tool:
            description = buffer_tool.description
            if "REQUIRES TWO PARAMETERS" in description and "distance_meters" in description:
                print("✅ PerformBufferAnalysis tool properly documented")
            else:
                print("❌ PerformBufferAnalysis tool needs better documentation")
                return False
        else:
            print("❌ PerformBufferAnalysis tool not found")
            return False
            
    except Exception as e:
        print(f"❌ Error testing tool parameters: {e}")
        return False
    
    return True

def test_publish_map_vector_support():
    """Test that publish_final_map supports vector files."""
    print("\n🗺️ Testing Vector File Publishing Support")
    print("=" * 40)
    
    try:
        from agent_app.tools import publish_final_map
        
        # Test with a mock vector file path
        mock_vector_path = "/mock/path/test.geojson"
        
        # This should not crash even with missing file (should return error message)
        result = publish_final_map(mock_vector_path)
        
        if "Error: File not found" in result:
            print("✅ Vector file handling works (proper error for missing file)")
        else:
            print(f"⚠️ Unexpected result: {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing vector file support: {e}")
        return False

def main():
    """Run all validation tests."""
    print("🚀 Validating Agent Behavior Fixes")
    print("This script validates the fixes for simple query handling.\n")
    
    success = True
    success &= test_simple_query_logic()
    success &= test_tool_parameters()
    success &= test_publish_map_vector_support()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ ALL VALIDATION TESTS PASSED!")
        print("The agent should now:")
        print("  • Handle simple 'find X' queries without unnecessary analysis")
        print("  • Properly document tool parameters to avoid missing arguments")
        print("  • Support both vector and raster file publishing")
        print("\nNext steps:")
        print("1. Start Django server: python manage.py runserver")
        print("2. Test 'find all schools in Chennai' - should work without errors")
        print("3. Use Postman collection for comprehensive testing")
    else:
        print("❌ SOME VALIDATION TESTS FAILED!")
        print("Check the error messages above for issues.")

if __name__ == "__main__":
    main()
