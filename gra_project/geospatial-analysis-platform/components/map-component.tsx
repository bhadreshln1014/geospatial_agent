"use client"

import { useEffect, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Download, Map, Layers, Info, ExternalLink } from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { API_BASE_URL } from '@/lib/api'

// Dynamically import Leaflet components to avoid SSR issues
const MapContainer = dynamic(() => import('react-leaflet').then((mod) => mod.MapContainer), { ssr: false })
const TileLayer = dynamic(() => import('react-leaflet').then((mod) => mod.TileLayer), { ssr: false })

interface MapResult {
  url: string;
  type: 'vector' | 'raster';
  bbox: [number, number, number, number] | null;
  name: string;
}

interface MapComponentProps {
  mapResult?: MapResult
  isVisible?: boolean
}

export default function MapComponent({ mapResult, isVisible = true }: MapComponentProps) {
  const { toast } = useToast()
  const [mapLoaded, setMapLoaded] = useState(false)
  const mapRef = useRef<any>(null)
  const layerRef = useRef<any>(null)

  useEffect(() => {
    // Import Leaflet CSS dynamically
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
    document.head.appendChild(link)

    setMapLoaded(true)

    return () => {
      if (document.head.contains(link)) {
        document.head.removeChild(link)
      }
    }
  }, [])

  useEffect(() => {
    const renderLayer = async () => {
      if (!mapRef.current) return

      // Clear previous layer
      if (layerRef.current) {
        mapRef.current.removeLayer(layerRef.current)
        layerRef.current = null
      }

      if (mapResult && mapResult.url) {
        const fileUrl = `${API_BASE_URL}${mapResult.url}`

        try {
          if (mapResult.type === 'vector') {
            // Import Leaflet for vector rendering
            const L = (await import('leaflet')).default
            
            const response = await fetch(fileUrl)
            const data = await response.json()
            const geoJsonLayer = L.geoJSON(data, {
              style: () => ({ color: "#ff7800", weight: 5, opacity: 0.8, fillOpacity: 0.2 })
            })
            geoJsonLayer.addTo(mapRef.current)
            layerRef.current = geoJsonLayer
          } else if (mapResult.type === 'raster') {
            // For now, just show a placeholder for raster data
            const L = (await import('leaflet')).default
            
            if (mapResult.bbox) {
              const [south, west, north, east] = mapResult.bbox
              const bounds = L.latLngBounds([south, west], [north, east])
              const rectangle = L.rectangle(bounds, {
                color: '#ff7800',
                weight: 2,
                fillOpacity: 0.2
              })
              rectangle.addTo(mapRef.current)
              layerRef.current = rectangle
              
              // Add popup with raster info
              rectangle.bindPopup(`Raster Layer: ${mapResult.name}<br/>Click to download: <a href="${fileUrl}" target="_blank">Download</a>`)
            }
          }

          // Zoom to layer bounds if available
          if (mapResult.bbox) {
            const [south, west, north, east] = mapResult.bbox
            mapRef.current.fitBounds([[south, west], [north, east]])
          }
        } catch (error) {
          console.error('Error loading layer:', error)
        }
      }
    }

    renderLayer()
  }, [mapResult])

  const handleDownload = () => {
    if (!mapResult) return

    const fileUrl = `${API_BASE_URL}${mapResult.url}`
    const link = document.createElement('a')
    link.href = fileUrl
    link.download = mapResult.name
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    toast({
      title: "Download Started",
      description: `Downloading ${mapResult.name}`,
    })
  }

  const handleOpenExternal = () => {
    if (!mapResult) return
    
    const fileUrl = `${API_BASE_URL}${mapResult.url}`
    window.open(fileUrl, '_blank')
  }

  if (!mapLoaded) {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <div className="text-center">
          <div className="h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-2"></div>
          <p className="text-sm text-muted-foreground">Loading map...</p>
        </div>
      </div>
    )
  }

  if (!mapResult) {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <div className="text-center space-y-2">
          <Map className="h-12 w-12 text-muted-foreground mx-auto" />
          <h3 className="text-lg font-medium">No Map Data</h3>
          <p className="text-sm text-muted-foreground">Execute a workflow to see map results</p>
        </div>
      </div>
    )
  }

  return (
    <Card className="h-full border-0 shadow-none">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <CardTitle className="text-lg flex items-center gap-2">
              <Map className="h-5 w-5" />
              Map Viewer
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant={mapResult.type === 'vector' ? 'default' : 'secondary'}>
                {mapResult.type.toUpperCase()}
              </Badge>
              <span className="text-sm text-muted-foreground">{mapResult.name}</span>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleDownload}>
              <Download className="h-4 w-4 mr-1" />
              Download
            </Button>
            <Button variant="outline" size="sm" onClick={handleOpenExternal}>
              <ExternalLink className="h-4 w-4 mr-1" />
              Open
            </Button>
          </div>
        </div>
      </CardHeader>
      <Separator />
      <CardContent className="p-0 h-[calc(100%-80px)]">
        {mapLoaded && (
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
        )}
      </CardContent>
    </Card>
  )
}
