import whitebox
import os

print("--- WhiteboxTools Installation Test ---")

try:
    # 1. Initialize the WhiteboxTools class.
    # This step is where the library finds the executable you downloaded.
    print("Initializing WhiteboxTools...")
    wbt = whitebox.WhiteboxTools()
    print("Initialization successful.")

    # 2. Get the version of the WhiteboxTools executable.
    # This is a simple, fast command that confirms the Python wrapper
    # can successfully communicate with the underlying binary.
    print("\nFetching WhiteboxTools version...")
    version_info = wbt.version()
    
    if version_info:
        print("✅ SUCCESS: WhiteboxTools is working correctly!")
        print(f"\nVersion Information:\n{version_info}")
    else:
        print("❌ FAILURE: Could not get version information. The tool ran but returned no output.")

    # 3. (Optional) Test a simple tool with a dummy file
    print("\nTesting a simple tool (MaxElevation)...")
    # Create a dummy file path
    dummy_file = "dummy_dem.tif" 
    
    # We don't actually need to create the file. The tool will fail,
    # but the error message will prove the executable was called.
    try:
        wbt.max_elevation_deviation(dem=dummy_file, output="dummy_output.tif")
    except Exception as e:
        error_str = str(e)
        if "FileNotFoundError" in error_str or "Error" in error_str:
            print("✅ SUCCESS: The tool executable was called correctly (it failed as expected because the input file doesn't exist).")
        else:
             print(f"❌ FAILURE: The tool call failed with an unexpected error: {e}")

except Exception as e:
    print("\n" + "="*40)
    print("❌ CRITICAL FAILURE: Could not initialize or run WhiteboxTools.")
    print(f"Error details: {e}")
    print("\nTroubleshooting:")
    print("1. Ensure you have run 'python -c \"import whitebox; whitebox.download_wbt()\"' in your terminal.")
    print("2. Check your internet connection and firewall settings.")
    print("3. Make sure you have the necessary permissions to write to your user home directory.")
    print("="*40)