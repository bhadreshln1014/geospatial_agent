// components/ClientSideMap.tsx
"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import "leaflet/dist/leaflet.css";
import L from "leaflet";

// Dynamically import React-Leaflet so it only runs client-side
const MapContainer = dynamic(() => import("react-leaflet").then(m => m.MapContainer), { ssr: false });
const TileLayer = dynamic(() => import("react-leaflet").then(m => m.TileLayer), { ssr: false });
const WMSTileLayer = dynamic(() => import("react-leaflet").then(m => m.WMSTileLayer), { ssr: false });
const GeoJSON = dynamic(() => import("react-leaflet").then(m => m.GeoJSON), { ssr: false });

interface MapProps {
  mapResult: {
    service_type: "WMS" | "geojson";
    layer_name?: string;
    geoserver_url?: string;
    bbox?: [number, number, number, number];
    name?: string;
    data?: any;
  };
}

export default function ClientSideMap({ mapResult }: MapProps) {
  const [geoJsonData, setGeoJsonData] = useState<any>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const map = L.map(document.createElement("div"));
      if (!map.getPane("wmsPane")) {
        map.createPane("wmsPane");
        const pane = map.getPane("wmsPane");
        if (pane) {
          pane.style.zIndex = "650"; // Higher than tile layers (~200)
          pane.style.pointerEvents = "none"; // Allow clicks to pass through
        }
      }
      map.remove(); // Clean up dummy map
    }
  }, []);

  useEffect(() => {
    if (mapResult.service_type === "geojson" && mapResult.data) {
      setGeoJsonData(mapResult.data);
    }
  }, [mapResult]);

  if (!mapResult) return <p>No map data available.</p>;

  return (
    <div style={{ height: "500px", width: "100%" }}>
      <MapContainer
        style={{ height: "100%", width: "100%" }}
        bounds={mapResult.bbox ? [[mapResult.bbox[0], mapResult.bbox[1]], [mapResult.bbox[2], mapResult.bbox[3]]] : undefined}
        scrollWheelZoom={true}
      >
        {/* Base Map */}
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* WMS Layer */}
        {mapResult.service_type === "WMS" && mapResult.layer_name && (() => {
          const proxyUrl = `/api/wms-proxy/`;
          return (
            <WMSTileLayer
              url={
      mapResult.geoserver_url
        ? `${mapResult.geoserver_url}/wms`
        : "/api/wms-proxy/"
    }
              params={{
                layers: mapResult.layer_name,
                transparent: true,
                format: 'image/png',
              }}
            />
          );
        })()}

        {/* GeoJSON Layer */}
        {mapResult.service_type === "geojson" && geoJsonData && (
          <GeoJSON data={geoJsonData} style={{ color: "blue" }} />
        )}
      </MapContainer>
    </div>
  );
}
