# --- START OF FILE geoserver_utils.py ---
from django.http import HttpResponse
import requests
import os
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

# Load GeoServer configuration from Django settings
GS_CONFIG = settings.GEOSERVER_SETTINGS
REST_URL = f"{GS_CONFIG['URL']}/rest"
AUTH = (GS_CONFIG['USER'], GS_CONFIG['PASSWORD'])
WORKSPACE = GS_CONFIG['WORKSPACE']

def set_default_style(layer_name: str):
    """
    Assigns a generic default style to a newly published vector layer.
    This is CRITICAL for WFS services to work correctly.
    """
    # GeoServer has built-in generic styles for point, line, and polygon
    # We will just assign the generic 'polygon' style as a robust default.
    style_name = "polygon" 
    
    headers = {'Content-type': 'application/xml'}
    # This is the XML payload to tell GeoServer to set the default style
    data = f"<layer><defaultStyle><name>{style_name}</name></defaultStyle></layer>"
    
    # The layer name needs to be prefixed with the workspace for this API endpoint
    qualified_layer_name = f"{WORKSPACE}:{layer_name}"
    url = f"{REST_URL}/layers/{qualified_layer_name}"
    
    print(f"Attempting to set default style '{style_name}' for layer '{qualified_layer_name}'...")
    response = requests.put(url, data=data, auth=AUTH, headers=headers)
    response.raise_for_status()
    print(f"Successfully set default style for '{qualified_layer_name}'.")


def publish_geotiff(file_path: str, layer_name: str):
    """Uploads a GeoTIFF and publishes it as a WMS layer."""
    headers = {'Content-type': 'image/tiff'}
    url = f"{REST_URL}/workspaces/{WORKSPACE}/coveragestores/{layer_name}/file.geotiff"
    
    with open(file_path, 'rb') as f:
        response = requests.put(url, data=f, auth=AUTH, headers=headers)
        response.raise_for_status() 
    
    print(f"GeoTIFF '{layer_name}' published successfully to GeoServer.")
    return f"{WORKSPACE}:{layer_name}"

def publish_gpkg(file_path: str, layer_name: str):
    """Uploads a GeoPackage, publishes it, and sets its default style."""
    headers = {'Content-type': 'application/x-gpkg'}
    url = f"{REST_URL}/workspaces/{WORKSPACE}/datastores/{layer_name}/file.gpkg"

    with open(file_path, 'rb') as f:
        response = requests.put(url, data=f, auth=AUTH, headers=headers)
        response.raise_for_status()

    print(f"GeoPackage '{layer_name}' data store created successfully.")
    
    # --- ADDED: This is the crucial new step ---
    # After uploading, we must tell GeoServer to set a style for the layer.
    try:
        set_default_style(layer_name)
    except Exception as e:
        print(f"WARNING: Could not set default style for {layer_name}. WFS may not work. Error: {e}")

    return f"{WORKSPACE}:{layer_name}"

@csrf_exempt
def wms_proxy(request):
    """
    Proxies WMS requests from the frontend to GeoServer to avoid CORS/ORB issues.
    """
    # Get the base GeoServer WMS endpoint from settings
    geoserver_url = f"{settings.GEOSERVER_SETTINGS['URL']}/geospatial_agent/wms"

    # Forward all query params from the incoming request
    resp = requests.get(geoserver_url, params=request.GET.dict(), stream=True)
    print("Proxying to:", resp.url)

    # Pass through the content type from GeoServer (usually image/png)
    return HttpResponse(
        resp.content,
        content_type=resp.headers.get('Content-Type', 'image/png'),
        status=resp.status_code
    )
