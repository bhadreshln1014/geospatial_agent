#!/usr/bin/env python3
"""
Test script to verify bbox calculation fix in publish_final_map
"""
import os
import sys
import json

# Add the Django backend to Python path
sys.path.append('/mnt/e/geospatial_agent/gra_project/backend')

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from agent_app.tools import publish_final_map

def test_bbox_calculation():
    """Test that publish_final_map returns correct bbox for Chennai schools"""
    
    # Test file path
    test_file = '/mnt/e/geospatial_agent/gra_project/backend/output/Chennai_school.geojson'
    
    if not os.path.exists(test_file):
        print(f"❌ Test file not found: {test_file}")
        return False
    
    print(f"🧪 Testing bbox calculation for: {test_file}")
    
    # Call publish_final_map
    result = publish_final_map(test_file)
    
    try:
        result_data = json.loads(result)
        bbox = result_data.get('bbox', [])
        
        print(f"📊 Result: {result}")
        print(f"📍 Bbox: {bbox}")
        
        # Check if bbox looks like Chennai coordinates (roughly 80°E, 13°N)
        if len(bbox) == 4:
            lon_min, lat_min, lon_max, lat_max = bbox
            
            # Chennai is roughly around 80.0-80.3°E, 12.8-13.2°N
            if 79.5 <= lon_min <= 81.0 and 79.5 <= lon_max <= 81.0 and 12.0 <= lat_min <= 14.0 and 12.0 <= lat_max <= 14.0:
                print("✅ Bbox appears to be correct for Chennai region")
                return True
            else:
                print(f"❌ Bbox does not look like Chennai coordinates")
                print(f"   Expected: ~80°E, ~13°N")
                print(f"   Got: {lon_min}°E-{lon_max}°E, {lat_min}°N-{lat_max}°N")
                return False
        else:
            print(f"❌ Invalid bbox format: {bbox}")
            return False
            
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse result as JSON: {e}")
        print(f"   Raw result: {result}")
        return False

if __name__ == "__main__":
    print("🔧 Testing bbox calculation fix...")
    success = test_bbox_calculation()
    if success:
        print("\n🎉 Test passed! The bbox calculation fix works correctly.")
    else:
        print("\n💥 Test failed! There may still be an issue with bbox calculation.")
