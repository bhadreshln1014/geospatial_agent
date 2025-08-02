# GeoServer Integration Setup

## Current Status
Your geospatial agent is currently running in **development mode** with mock GeoServer integration. The `PublishFinalMap` tool returns realistic mock data including:

- WMS URL
- Layer name
- Bounding box (extracted from actual raster data)
- Mock publication status

## To Enable Real GeoServer Integration

### 1. Install Docker GeoServer (Recommended)

**Option A: Run directly on Windows with Docker Desktop**
```powershell
# Run GeoServer container on Windows
docker run -d --name geoserver-geospatial ^
  -p 8080:8080 ^
  -e GEOSERVER_ADMIN_PASSWORD=geospatial123 ^
  -e INSTALL_EXTENSIONS=true ^
  -e STABLE_EXTENSIONS=wps,csw ^
  -v geoserver-data:/opt/geoserver/data_dir ^
  kartoza/geoserver:2.23.0

# Check if container is running
docker ps | findstr geoserver
```

**Option B: Run in WSL with Docker**
```bash
# Run GeoServer container in WSL
docker run -d --name geoserver-geospatial \
  -p 8080:8080 \
  -e GEOSERVER_ADMIN_PASSWORD=geospatial123 \
  -e INSTALL_EXTENSIONS=true \
  -e STABLE_EXTENSIONS=wps,csw \
  -v geoserver-data:/opt/geoserver/data_dir \
  kartoza/geoserver:2.23.0

# Check if container is running
docker ps | grep geoserver
```

### 2. Install Python GeoServer Client
```bash
cd /mnt/e/geospatial_agent/gra_project/backend
pip install geoserver-restconfig
```

### 3. Update Connection Details

**If running Docker on Windows (Option A):**
```python
# GeoServer connection details - Docker on Windows
geoserver_url = "http://172.25.128.1:8080/geoserver"  # Windows host IP from WSL
username = "admin"
password = "geospatial123"  # Custom password set in Docker
workspace = "geospatial_agent"
```

**If running Docker in WSL (Option B):**
```python
# GeoServer connection details - Docker in WSL
geoserver_url = "http://localhost:8080/geoserver"  # Local WSL Docker
username = "admin"
password = "geospatial123"  # Custom password set in Docker
workspace = "geospatial_agent"
```

### 4. Docker Management Commands

**Start/Stop GeoServer:**
```bash
# Start the container
docker start geoserver-geospatial

# Stop the container
docker stop geoserver-geospatial

# View logs
docker logs geoserver-geospatial

# Remove container (if you want to start fresh)
docker rm -f geoserver-geospatial
```

**Access GeoServer:**
- **Web Interface:** http://localhost:8080/geoserver (or http://172.25.128.1:8080/geoserver from WSL if on Windows)
- **Username:** admin
- **Password:** geospatial123

### 5. Create Suitability Style (Optional)
To apply custom styling to your published maps:

1. Access GeoServer web interface: http://localhost:8080/geoserver
2. Go to Styles → Add new style
3. Name it `suitability_style`
4. Add your SLD (Styled Layer Descriptor) content

## Development vs Production Mode

### Development Mode (Current)
- ✅ Full geospatial analysis pipeline works
- ✅ All tools return real file paths
- ✅ Mock GeoServer data with extracted bounds
- ✅ Frontend displays mock publication status
- ⚠️ No actual map server integration

### Production Mode (With GeoServer)
- ✅ Everything from development mode
- ✅ Real GeoServer publication
- ✅ WMS layer serving
- ✅ Style application
- ✅ Layer management

## Testing Your Setup

Run this sample query to test the full pipeline:
```
"Find suitable areas for affordable housing in Chennai considering proximity to schools and hospitals"
```

Expected behavior:
1. **Data Acquisition**: Schools, hospitals, elevation data
2. **Analysis**: Multi-criteria analysis
3. **Publication**: Mock or real GeoServer publication
4. **Frontend**: Visual feedback with appropriate status indicators

## Troubleshooting

### Docker GeoServer Issues

**Container won't start:**
```bash
# Check Docker status
docker ps -a | grep geoserver

# View container logs
docker logs geoserver-geospatial

# Restart container
docker restart geoserver-geospatial
```

**Port 8080 already in use:**
```bash
# Find what's using port 8080
sudo netstat -tulpn | grep :8080

# Use different port (change both sides)
docker run -p 8081:8080 ... geoserver-geospatial
```

**Connection from WSL fails:**
- Verify Docker is running: `docker ps`
- Test port: `curl -I http://localhost:8080/geoserver` (if in WSL)
- Test port: `curl -I http://172.25.128.1:8080/geoserver` (if Docker on Windows)

### Python Client Issues
If you see `ModuleNotFoundError: No module named 'geoserver'`:
- The system falls back to mock mode automatically
- Install `geoserver-restconfig` to enable real integration:
```bash
pip install geoserver-restconfig
```

### Network Issues
**Auto-detection not working:**
- The code automatically detects Docker location
- Manually override in `tools.py` if needed:
```python
# Force localhost (Docker in WSL)
geoserver_url = "http://localhost:8080/geoserver"

# Force Windows host (Docker on Windows)
geoserver_url = "http://172.25.128.1:8080/geoserver"
```

The system gracefully handles all error cases and provides meaningful feedback to users.
