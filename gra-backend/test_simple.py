#!/usr/bin/env python3

import os
from tools import acquire_vector_data, acquire_elevation_data

def test_basic_functions():
    """Test the basic functions without the agent"""
    
    print("Testing acquire_vector_data...")
    try:
        result1 = acquire_vector_data("bars in Palo Alto")
        print(f"Result 1: {result1}")
    except Exception as e:
        print(f"Error in acquire_vector_data: {e}")
    
    print("\nTesting acquire_elevation_data...")
    try:
        result2 = acquire_elevation_data("Palo Alto")
        print(f"Result 2: {result2}")
    except Exception as e:
        print(f"Error in acquire_elevation_data: {e}")

if __name__ == "__main__":
    # Create output directory
    os.makedirs("output", exist_ok=True)
    test_basic_functions()
