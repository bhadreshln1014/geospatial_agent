#!/bin/bash

# GeoServer Docker Setup Script for Geospatial Agent
# This script sets up GeoServer using Docker with optimal configuration

echo "🐳 Setting up GeoServer with Docker..."

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "📋 Installation guide: https://docs.docker.com/get-docker/"
    exit 1
fi

# Stop and remove existing container if it exists
if docker ps -a | grep -q geoserver-geospatial; then
    echo "🔄 Stopping existing GeoServer container..."
    docker stop geoserver-geospatial 2>/dev/null
    docker rm geoserver-geospatial 2>/dev/null
fi

# Pull the latest GeoServer image
echo "📥 Pulling GeoServer Docker image..."
docker pull kartoza/geoserver:2.23.0

# Run GeoServer container
echo "🚀 Starting GeoServer container..."
docker run -d --name geoserver-geospatial \
  -p 8080:8080 \
  -e GEOSERVER_ADMIN_PASSWORD=geospatial123 \
  -e INSTALL_EXTENSIONS=true \
  -e STABLE_EXTENSIONS=wps,csw,importer,gdal,ogr \
  -e ENABLE_JSONP=true \
  -e MAX_FILTER_RULES=20 \
  -e OPTIMIZE_LINE_WIDTH=false \
  -e FOOTPRINTS_DATA_DIR=/opt/footprints_dir \
  -e GEOWEBCACHE_CACHE_DIR=/opt/geowebcache \
  -e GEOSERVER_DATA_DIR=/opt/geoserver/data_dir \
  -e GEOSERVER_FILEBROWSER_HIDEFS=false \
  -e TOMCAT_EXTRAS=false \
  -v geoserver-data:/opt/geoserver/data_dir \
  -v geoserver-cache:/opt/geowebcache \
  --restart unless-stopped \
  kartoza/geoserver:2.23.0

# Wait for container to start
echo "⏳ Waiting for GeoServer to start..."
sleep 10

# Check if container is running
if docker ps | grep -q geoserver-geospatial; then
    echo "✅ GeoServer is running successfully!"
    echo ""
    echo "🌐 Access URLs:"
    echo "   - From WSL: http://localhost:8080/geoserver"
    echo "   - From Windows: http://172.25.132.15:8080/geoserver"
    echo ""
    echo "🔐 Login Credentials:"
    echo "   - Username: admin"
    echo "   - Password: geospatial123"
    echo ""
    echo "🛠️  Management Commands:"
    echo "   - Stop:    docker stop geoserver-geospatial"
    echo "   - Start:   docker start geoserver-geospatial"
    echo "   - Logs:    docker logs geoserver-geospatial"
    echo "   - Remove:  docker rm -f geoserver-geospatial"
    echo ""
    echo "📊 Container Status:"
    docker ps | grep geoserver-geospatial
else
    echo "❌ Failed to start GeoServer container"
    echo "📋 Check logs with: docker logs geoserver-geospatial"
    exit 1
fi

echo ""
echo "🎉 GeoServer setup complete! Your geospatial agent can now publish maps."
