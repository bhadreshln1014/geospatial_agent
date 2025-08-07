"use client"

import { useRef } from 'react';
import L from 'leaflet';
import { MapContainer, TileLayer, FeatureGroup } from 'react-leaflet';
import { EditControl } from 'react-leaflet-draw';

// Import the CSS for the drawing tools
import 'leaflet-draw/dist/leaflet.draw.css';

// Fix for Leaflet icons with bundlers
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: require('leaflet/dist/images/marker-icon-2x.png').default,
  iconUrl: require('leaflet/dist/images/marker-icon.png').default,
  shadowUrl: require('leaflet/dist/images/marker-shadow.png').default,
});

interface RoiMapProps {
  // The callback now sends a GeoJSON Polygon object
  onRoiSelected: (roiGeoJson: any) => void;
}

export default function RoiMap({ onRoiSelected }: RoiMapProps) {
  const featureGroupRef = useRef<L.FeatureGroup>(null);

  const handleCreate = (e: any) => {
    const layer = e.layer;
    if (layer && featureGroupRef.current) {
      // Clear previous drawings
      featureGroupRef.current.clearLayers();
      // Add the new layer
      featureGroupRef.current.addLayer(layer);

      // --- CHANGE: Convert the drawn layer to a GeoJSON object ---
      const geoJson = layer.toGeoJSON();
      
      // Send the entire GeoJSON object back to the parent component
      onRoiSelected(geoJson);
    }
  };

  return (
    <MapContainer 
      center={[20.5937, 78.9629]} // Centered on India
      zoom={5} 
      style={{ height: '500px', width: '100%' }}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      
      <FeatureGroup ref={featureGroupRef}>
        <EditControl
          position="topright"
          onCreated={handleCreate}
          draw={{
            // --- CHANGE: Enable polygon drawing, disable rectangle ---
            polygon: true,
            rectangle: false,
            // ---
            circle: false,
            circlemarker: false,
            marker: false,
            polyline: false,
          }}
          edit={{
            edit: false,
            remove: true,
          }}
        />
      </FeatureGroup>
    </MapContainer>
  );
}
