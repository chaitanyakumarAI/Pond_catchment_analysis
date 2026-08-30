document.addEventListener('DOMContentLoaded', () => {
  // Initialize Leaflet Map
  const map = L.map('map').setView([21.25, 81.29], 13);

  // Add Dark Matter / CartoDB Base Map
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19
  }).addTo(map);

  let catchmentLayerGroup = L.layerGroup().addTo(map);

  // UI Elements
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const fileNameDisplay = document.getElementById('fileNameDisplay');
  const btnAnalyze = document.getElementById('btnAnalyze');
  const btnSample = document.getElementById('btnSample');
  const uploadForm = document.getElementById('uploadForm');
  const loaderOverlay = document.getElementById('loaderOverlay');
  const mapStatusText = document.getElementById('mapStatusText');
  const resultsContainer = document.getElementById('resultsContainer');

  // Drag and Drop behavior
  dropZone.addEventListener('click', () => fileInput.click());
  
  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
    });
  });

  dropZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      fileInput.files = files;
      handleFileSelected(files[0]);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      handleFileSelected(fileInput.files[0]);
    }
  });

  function handleFileSelected(file) {
    const name = file.name;
    const ext = name.split('.').pop().toLowerCase();
    if (ext === 'kml' || ext === 'kmz') {
      fileNameDisplay.textContent = `Selected: ${name}`;
      btnAnalyze.disabled = false;
    } else {
      alert("Invalid file type! Please select a .KML or .KMZ file.");
      fileInput.value = '';
      fileNameDisplay.textContent = '';
      btnAnalyze.disabled = true;
    }
  }

  // Handle Form Submit (File Upload Analysis)
  uploadForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return;

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    performAnalysis('/analyzeContour', {
      method: 'POST',
      body: formData
    });
  });

  // Handle Sample Button
  btnSample.addEventListener('click', () => {
    performAnalysis('/api/sample', { method: 'POST' });
  });

  // Fetch & Perform Analysis
  async function performAnalysis(url, fetchOptions) {
    showLoader(true);
    mapStatusText.textContent = "Analyzing contour map terrain & delineating catchment...";

    try {
      const response = await fetch(url, fetchOptions);
      const json = await response.json();

      if (!response.ok || !json.success) {
        throw new Error(json.error || "Analysis failed.");
      }

      renderAnalysisResults(json.data);
      mapStatusText.textContent = `Analysis Complete: ${json.data.input_file_info.filename}`;
    } catch (err) {
      alert("Error: " + err.message);
      mapStatusText.textContent = "Analysis failed. Please try another KML/KMZ file.";
    } finally {
      showLoader(false);
    }
  }

  function showLoader(show) {
    loaderOverlay.style.display = show ? 'flex' : 'none';
  }

  // Render Map & Dashboard Metrics
  function renderAnalysisResults(data) {
    catchmentLayerGroup.clearLayers();

    const pond = data.pond_location;
    const catchment = data.catchment_summary;
    const runoff = data.water_harvesting_estimates;
    const terrain = data.terrain_statistics;
    const geojson = data.geojson_layers;

    // Update Dashboard Metrics
    document.getElementById('valAreaHa').textContent = `${catchment.area_hectares} ha`;
    document.getElementById('valAreaM2').textContent = `${catchment.area_m2.toLocaleString()} m² / ${catchment.area_acres} acres`;
    
    document.getElementById('valPondCoords').textContent = `${pond.latitude}, ${pond.longitude}`;
    document.getElementById('valPondElev').textContent = `Elev: ${pond.elevation_m}m | Suitability: ${pond.suitability_score_pct}%`;
    
    document.getElementById('valRunoffM3').textContent = `${runoff.estimated_annual_runoff_m3.toLocaleString()} m³`;
    document.getElementById('valRunoffLiters').textContent = `${(runoff.estimated_annual_runoff_liters / 1e6).toFixed(1)} Million Liters`;

    document.getElementById('valPondCap').textContent = `${runoff.recommended_pond_capacity_m3.toLocaleString()} m³`;
    document.getElementById('valPondDims').textContent = `Size: ${runoff.recommended_dimensions_m} (Depth ${runoff.recommended_pond_depth_m}m)`;

    document.getElementById('valElevRange').textContent = `${terrain.min_elevation_m}m — ${terrain.max_elevation_m}m`;
    document.getElementById('valSlope').textContent = `${terrain.avg_slope_deg}°`;
    document.getElementById('valCoverage').textContent = `${terrain.map_width_meters}m x ${terrain.map_height_meters}m`;
    document.getElementById('valContours').textContent = `${data.input_file_info.contour_count} contours`;

    // Render JSON Pre
    document.getElementById('jsonPre').textContent = JSON.stringify(data, null, 2);
    resultsContainer.style.display = 'flex';

    // Map Overlays
    // 1. Add Catchment Boundary Polygon Layer
    if (geojson && geojson.catchment_boundary) {
      const catchmentPoly = L.geoJSON(geojson.catchment_boundary, {
        style: {
          color: '#06B6D4',
          weight: 3,
          fillColor: '#06B6D4',
          fillOpacity: 0.25,
          dashArray: '4, 4'
        }
      }).bindPopup(`
        <div style="color: #111827;">
          <h4 style="margin-bottom: 4px; color: #06B6D4;">Delineated Catchment Basin</h4>
          <p><b>Area:</b> ${catchment.area_hectares} ha (${catchment.area_m2.toLocaleString()} m²)</p>
          <p><b>Est. Annual Runoff:</b> ${runoff.estimated_annual_runoff_m3.toLocaleString()} m³</p>
        </div>
      `);
      catchmentLayerGroup.addLayer(catchmentPoly);
      map.fitBounds(catchmentPoly.getBounds(), { padding: [40, 40] });
    }

    // 2. Add Optimal Pond Site Marker Layer
    if (geojson && geojson.pond_point) {
      const pondMarker = L.circleMarker([pond.latitude, pond.longitude], {
        radius: 12,
        fillColor: '#10B981',
        color: '#FFFFFF',
        weight: 3,
        opacity: 1,
        fillOpacity: 0.9
      }).bindPopup(`
        <div style="color: #111827;">
          <h4 style="margin-bottom: 4px; color: #10B981;">Optimal Farm Pond Site</h4>
          <p><b>Coordinates:</b> ${pond.latitude}, ${pond.longitude}</p>
          <p><b>Elevation:</b> ${pond.elevation_m} meters</p>
          <p><b>Suitability Index:</b> ${pond.suitability_score_pct}%</p>
          <p><b>Recommended Sizing:</b> ${runoff.recommended_dimensions_m}</p>
        </div>
      `).openPopup();

      catchmentLayerGroup.addLayer(pondMarker);
    }
  }

  // Toggle JSON Response view
  const toggleJson = document.getElementById('toggleJson');
  const jsonBody = document.getElementById('jsonBody');
  toggleJson.addEventListener('click', () => {
    const isHidden = jsonBody.style.display === 'none';
    jsonBody.style.display = isHidden ? 'block' : 'none';
    toggleJson.querySelector('.toggle-icon').style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
  });
});
