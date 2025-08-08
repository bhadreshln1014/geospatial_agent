// --- START OF FILE RoiMap.tsx (Final Version) ---
"use client"

import { useRef } from 'react';
import L from 'leaflet';
import { MapContainer, TileLayer, FeatureGroup } from 'react-leaflet';
import { EditControl } from 'react-leaflet-draw';

import 'leaflet/dist/leaflet.css';
import 'leaflet-draw/dist/leaflet.draw.css';

// Leaflet icon fix
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: require('leaflet/dist/images/marker-icon-2x.png').default,
  iconUrl: require('leaflet/dist/images/marker-icon.png').default,
  shadowUrl: require('leaflet/dist/images/marker-shadow.png').default,
});

interface RoiMapProps {
  onRoiSelected: (roi: any | null) => void;
}

export default function RoiMap({ onRoiSelected }: RoiMapProps) {
  const featureGroupRef = useRef<L.FeatureGroup>(null);

  const handleCreate = (e: any) => {
    console.log("SUCCESS: 'handleCreate' fired inside RoiMap.tsx");
    const layer = e.layer;
    if (layer) {
      onRoiSelected(layer.toGeoJSON());
    }
  };

  const handleEdit = (e: any) => {
    const layers = e.layers.getLayers();
    if (layers.length > 0) {
      const editedLayer = layers[0];
      onRoiSelected(editedLayer.toGeoJSON());
    }
  };

  const handleDelete = () => {
    onRoiSelected(null);
  };

  return (
    <MapContainer
      center={[20.5937, 78.9629]}
      zoom={5}
      style={{ height: '60vh', width: '100%', borderRadius: '5px' }}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      
      <FeatureGroup ref={featureGroupRef}>
        <EditControl
          position="topright"
          onCreated={handleCreate}
          onEdited={handleEdit}
          onDeleted={handleDelete}
          draw={{
            polygon: { allowIntersection: false, showArea: true },
            rectangle: false, circle: false, circlemarker: false,
            marker: false, polyline: false,
          }}
          edit={{ featureGroup: featureGroupRef.current! }}
        />
      </FeatureGroup>
    </MapContainer>
  );
}