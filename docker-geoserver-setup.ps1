# GeoServer Docker Setup Script for Windows
# Run this in PowerShell as Administrator

Write-Host "🐳 Setting up GeoServer with Docker on Windows..." -ForegroundColor Green

# Check if Docker is available
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker is not installed. Please install Docker Desktop first." -ForegroundColor Red
    Write-Host "📋 Download from: https://www.docker.com/products/docker-desktop" -ForegroundColor Yellow
    exit 1
}

# Stop and remove existing container if it exists
$existing = docker ps -a --filter "name=geoserver-geospatial" --format "{{.Names}}"
if ($existing) {
    Write-Host "🔄 Stopping existing GeoServer container..." -ForegroundColor Yellow
    docker stop geoserver-geospatial | Out-Null
    docker rm geoserver-geospatial | Out-Null
}

# Pull the latest GeoServer image
Write-Host "📥 Pulling GeoServer Docker image..." -ForegroundColor Cyan
docker pull kartoza/geoserver:2.23.0

# Run GeoServer container
Write-Host "🚀 Starting GeoServer container..." -ForegroundColor Green
docker run -d --name geoserver-geospatial `
  -p 8080:8080 `
  -e GEOSERVER_ADMIN_PASSWORD=geospatial123 `
  -e INSTALL_EXTENSIONS=true `
  -e STABLE_EXTENSIONS=wps,csw,importer,gdal,ogr `
  -e ENABLE_JSONP=true `
  -e MAX_FILTER_RULES=20 `
  -e OPTIMIZE_LINE_WIDTH=false `
  -e FOOTPRINTS_DATA_DIR=/opt/footprints_dir `
  -e GEOWEBCACHE_CACHE_DIR=/opt/geowebcache `
  -e GEOSERVER_DATA_DIR=/opt/geoserver/data_dir `
  -e GEOSERVER_FILEBROWSER_HIDEFS=false `
  -e TOMCAT_EXTRAS=false `
  -v geoserver-data:/opt/geoserver/data_dir `
  -v geoserver-cache:/opt/geowebcache `
  --restart unless-stopped `
  kartoza/geoserver:2.23.0

# Wait for container to start
Write-Host "⏳ Waiting for GeoServer to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Check if container is running
$running = docker ps --filter "name=geoserver-geospatial" --format "{{.Names}}"
if ($running) {
    Write-Host "✅ GeoServer is running successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "🌐 Access URLs:" -ForegroundColor Cyan
    Write-Host "   - Local: http://localhost:8080/geoserver" -ForegroundColor White
    Write-Host "   - From WSL: http://172.25.128.1:8080/geoserver" -ForegroundColor White
    Write-Host ""
    Write-Host "🔐 Login Credentials:" -ForegroundColor Cyan
    Write-Host "   - Username: admin" -ForegroundColor White
    Write-Host "   - Password: geospatial123" -ForegroundColor White
    Write-Host ""
    Write-Host "🛠️  Management Commands:" -ForegroundColor Cyan
    Write-Host "   - Stop:    docker stop geoserver-geospatial" -ForegroundColor White
    Write-Host "   - Start:   docker start geoserver-geospatial" -ForegroundColor White
    Write-Host "   - Logs:    docker logs geoserver-geospatial" -ForegroundColor White
    Write-Host "   - Remove:  docker rm -f geoserver-geospatial" -ForegroundColor White
    Write-Host ""
    Write-Host "📊 Container Status:" -ForegroundColor Cyan
    docker ps | findstr geoserver
} else {
    Write-Host "❌ Failed to start GeoServer container" -ForegroundColor Red
    Write-Host "📋 Check logs with: docker logs geoserver-geospatial" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "🎉 GeoServer setup complete! Your geospatial agent can now publish maps." -ForegroundColor Green
