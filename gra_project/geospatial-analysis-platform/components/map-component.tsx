"use client"

import { Suspense, useEffect, useState } from 'react'
import dynamic from 'next/dynamic'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Download, Map, ExternalLink, AlertTriangle } from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { API_BASE_URL } from '@/lib/api'
// ADD THIS IMPORT AT THE TOP
import ClientSideMap from './ClientSideMap'

interface MapResult {
  url: string
  type: 'vector' | 'raster'
  bbox?: [number, number, number, number] | null
  name: string
}

interface MapComponentProps {
  mapResult?: MapResult | null
  isVisible?: boolean
}

export default function MapComponent({ mapResult, isVisible = true }: MapComponentProps) {
  const { toast } = useToast()
  const [isClient, setIsClient] = useState(false)
  const [hasError, setHasError] = useState(false)

  useEffect(() => {
    setIsClient(true)
    console.log('MapComponent received mapResult:', mapResult)
    setHasError(false)
  }, [mapResult])

  const handleDownload = () => {
    if (!mapResult?.name || !mapResult?.url) {
      toast({
        title: "Download Error",
        description: "No file available for download",
        variant: "destructive"
      })
      return
    }

    try {
      const fileUrl = `${API_BASE_URL}${mapResult.url}`
      const link = document.createElement('a')
      link.href = fileUrl
      link.download = mapResult.name
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      
      toast({
        title: "Download Started",
        description: `Downloading ${mapResult.name}`,
      })
    } catch (error) {
      console.error('Download error:', error)
      toast({
        title: "Download Failed",
        description: "Could not download the file",
        variant: "destructive"
      })
    }
  }

  const handleOpenExternal = () => {
    if (!mapResult?.url) {
      toast({
        title: "Error",
        description: "No file URL available",
        variant: "destructive"
      })
      return
    }

    try {
      const fileUrl = `${API_BASE_URL}${mapResult.url}`
      window.open(fileUrl, '_blank', 'noopener,noreferrer')
    } catch (error) {
      console.error('External open error:', error)
      toast({
        title: "Error",
        description: "Could not open the file",
        variant: "destructive"
      })
    }
  }

  const handleMapError = (error: string) => {
    console.error('Map error:', error)
    setHasError(true)
    toast({
      title: "Map Display Error",
      description: error,
      variant: "destructive"
    })
  }

  if (!isVisible) return null

  if (!mapResult) {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <div className="text-center space-y-4">
          <Map className="h-16 w-16 text-muted-foreground mx-auto" />
          <div className="space-y-2">
            <h3 className="text-lg font-medium">No Map Data</h3>
            <p className="text-sm text-muted-foreground">Execute a workflow to see map results</p>
          </div>
        </div>
      </div>
    )
  }

  if (hasError) {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <div className="text-center space-y-4">
          <AlertTriangle className="h-16 w-16 text-red-500 mx-auto" />
          <div className="space-y-2">
            <h3 className="text-lg font-medium">Map Display Error</h3>
            <p className="text-sm text-muted-foreground">
              Unable to display {mapResult?.name || 'the map file'}
            </p>
            <div className="flex gap-2 justify-center">
              <Button 
                variant="outline" 
                size="sm" 
                onClick={() => setHasError(false)}
              >
                Retry
              </Button>
              {mapResult?.url && (
                <Button 
                  variant="outline" 
                  size="sm" 
                  onClick={handleOpenExternal}
                >
                  <ExternalLink className="h-4 w-4 mr-1" />
                  Open File
                </Button>
              )}
            </div>
          </div>
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
              <Badge variant={mapResult?.type === 'vector' ? 'default' : 'secondary'}>
                {mapResult?.type?.toUpperCase() || 'UNKNOWN'}
              </Badge>
              <span className="text-sm text-muted-foreground">
                {mapResult?.name || 'Unnamed Layer'}
              </span>
              {mapResult?.bbox && (
                <Badge variant="outline" className="text-xs">
                  Georeferenced
                </Badge>
              )}
            </div>
          </div>
          <div className="flex gap-2">
            <Button 
              variant="outline" 
              size="sm" 
              onClick={handleDownload}
              disabled={!mapResult?.name || !mapResult?.url}
            >
              <Download className="h-4 w-4 mr-1" />
              Download
            </Button>
            <Button 
              variant="outline" 
              size="sm" 
              onClick={handleOpenExternal}
              disabled={!mapResult?.url}
            >
              <ExternalLink className="h-4 w-4 mr-1" />
              Open
            </Button>
          </div>
        </div>
      </CardHeader>
      <Separator />
      <CardContent className="p-0 h-[calc(100%-80px)]">
        <Suspense fallback={
          <div className="h-full w-full flex items-center justify-center">
            <div className="text-center space-y-2">
              <div className="h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
              <p className="text-sm text-muted-foreground">Loading map...</p>
            </div>
          </div>
        }>
          {isClient && mapResult && (
            <ClientSideMap 
              mapResult={mapResult} 
              onError={handleMapError}
            />
          )}
        </Suspense>
      </CardContent>
    </Card>
  )
}
