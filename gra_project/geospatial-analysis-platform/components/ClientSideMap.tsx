"use client"

import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { MapContainer, TileLayer } from 'react-leaflet'
import { AlertTriangle, Loader2 } from 'lucide-react'

// --- START: CORRECTED ICON SETUP ---
// Import the icon images directly. This ensures we get the correct URL paths.
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

// Configure Leaflet's default icon paths.
// This is the correct way to do it in a modern bundler environment like Next.js.
L.Icon.Default.mergeOptions({
  iconUrl: markerIcon.src,
  iconRetinaUrl: markerIcon2x.src,
  shadowUrl: markerShadow.src
});
// --- END: CORRECTED ICON SETUP ---


// The updated MapResult interface supports both direct data and GeoServer layers
interface MapResult {
  url?: string | null;      // For GeoServer layers
  type: 'vector' | 'raster';
  bbox: [number, number, number, number] | null;
  name: string;
  data?: any;               // For direct GeoJSON data
  service_type?: 'WMS' | 'geojson'; // Identifies the rendering method
  geoserver_url?: string;   // For GeoServer layers
  layer_name?: string;      // For GeoServer layers
}

interface ClientSideMapProps {
  mapResult?: MapResult | null
  onError?: (error: string) => void
}

export default function ClientSideMap({ mapResult, onError }: ClientSideMapProps) {
  const mapRef = useRef<L.Map | null>(null);
  const overlayLayerRef = useRef<L.Layer | null>(null); // To hold the current overlay
  const [isLoading, setIsLoading] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // Function to remove the previous layer before adding a new one
    const cleanupLayer = () => {
      if (overlayLayerRef.current) {
        map.removeLayer(overlayLayerRef.current);
        overlayLayerRef.current = null;
      }
    };

    if (!mapResult) {
      cleanupLayer();
      return;
    }

    const loadData = async () => {
      setIsLoading(true);
      setMapError(null);
      cleanupLayer();

      try {
        // --- PATH 1: Render vector data directly from GeoJSON object ---
        if (mapResult.type === 'vector' && mapResult.service_type === 'geojson' && mapResult.data) {
          const geoJsonLayer = L.geoJSON(mapResult.data, {
            style: { color: "#ff7800", weight: 3, opacity: 0.8, fillOpacity: 0.3 }
          }).addTo(map);
          overlayLayerRef.current = geoJsonLayer; // Store reference for cleanup

        // --- PATH 2: Render raster/vector data from GeoServer WMS service ---
        } else if (mapResult.service_type === 'WMS') {
          if (!mapResult.geoserver_url || !mapResult.layer_name) {
            throw new Error('GeoServer URL and layer name are required for WMS layers.');
          }
          const wmsLayer = L.tileLayer.wms(mapResult.geoserver_url, {
            layers: mapResult.layer_name,
            format: 'image/png',
            transparent: true,
            version: '1.1.1'
          }).addTo(map);
          overlayLayerRef.current = wmsLayer; // Store reference for cleanup
        
        // --- Fallback for unexpected formats ---
        } else {
            throw new Error(`Unsupported map result format or missing data. Service type: ${mapResult.service_type}`);
        }

        // Fit map to the layer's bounding box (this works for both paths)
        if (mapResult.bbox) {
          map.fitBounds([
            [mapResult.bbox[0], mapResult.bbox[1]], // [south, west]
            [mapResult.bbox[2], mapResult.bbox[3]]  // [north, east]
          ]);
        }
      } catch (error: any) {
        console.error("Map rendering error:", error);
        setMapError(error.message);
        if (onError) onError(error.message);
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
  }, [mapResult, onError]); // Re-run this effect whenever mapResult or the error handler changes

  return (
    <div className="relative h-full w-full">
      {isLoading && (
        <div className="absolute inset-0 bg-white/80 flex items-center justify-center z-[1000]">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      )}
      {mapError && (
          <div className="absolute inset-0 bg-red-50 flex items-center justify-center z-[1000] p-4">
              <div className="text-center">
                  <AlertTriangle className="h-8 w-8 text-red-600 mx-auto mb-2" />
                  <p className="font-semibold text-red-700">Map Error</p>
                  <p className="text-sm text-red-600">{mapError}</p>
              </div>
          </div>
      )}
      <MapContainer 
        center={[20.5937, 78.9629]} 
        zoom={5} 
        style={{ height: '100%', width: '100%' }}
        ref={mapRef}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
      </MapContainer>
    </div>
  );
}
