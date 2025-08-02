'use client'
import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix for default markers in react-leaflet
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

interface MapViewerProps {
  outputFiles: string[];
}

export default function MapViewer({ outputFiles }: MapViewerProps) {
  const [geoJsonData, setGeoJsonData] = useState<any>(null);
  const [mapCenter, setMapCenter] = useState<[number, number]>([37.4419, -122.1430]); // Palo Alto default

  useEffect(() => {
    // Load the first GeoJSON file for display
    const geoJsonFile = outputFiles.find(file => file.endsWith('.geojson'));
    console.log('MapViewer: outputFiles:', outputFiles);
    console.log('MapViewer: geoJsonFile found:', geoJsonFile);
    
    if (geoJsonFile) {
      const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
      const fetchUrl = `${apiBaseUrl}/output/${geoJsonFile}`;
      console.log('MapViewer: Fetching from:', fetchUrl);
      
      fetch(fetchUrl)
        .then(response => {
          console.log('MapViewer: Response status:', response.status);
          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }
          return response.json();
        })
        .then(data => {
          console.log('MapViewer: GeoJSON data loaded:', data);
          setGeoJsonData(data);
          // Center map on the data bounds if available
          if (data.features && data.features.length > 0) {
            const bounds = L.geoJSON(data).getBounds();
            setMapCenter([bounds.getCenter().lat, bounds.getCenter().lng]);
            console.log('MapViewer: Map centered on:', bounds.getCenter());
          }
        })
        .catch(error => {
          console.error('MapViewer: Error loading GeoJSON:', error);
        });
    } else {
      console.log('MapViewer: No GeoJSON file found in outputFiles');
    }
  }, [outputFiles]);

  return (
    <MapContainer
      center={mapCenter}
      zoom={12}
      style={{ height: '300px', width: '100%' }}
      className="rounded-lg"
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      {geoJsonData && (
        <GeoJSON
          data={geoJsonData}
          style={{
            color: '#3388ff',
            weight: 2,
            fillOpacity: 0.6
          }}
        />
      )}
    </MapContainer>
  );
}
