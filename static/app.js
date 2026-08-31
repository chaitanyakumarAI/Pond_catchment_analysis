document.addEventListener('DOMContentLoaded', () => {
  // Initialize Leaflet Map
  const map = L.map('map').setView([21.25, 81.29], 13);

  // Base Map Tile Layers (Lightweight CDN Tiles)
  const streetMap = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19
  });

  const terrainMap = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenTopoMap (CC-BY-SA)',
    maxZoom: 17
  });

  const satelliteMap = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
    maxZoom: 18
  });

  // Default to Street Map
  streetMap.addTo(map);

  // Add Layer Control widget (Street, Terrain Topo, Satellite)
  const baseMaps = {
    "🗺️ Standard Street": streetMap,
    "🏔️ Terrain Topo": terrainMap,
    "🛰️ Satellite View": satelliteMap
  };

  L.control.layers(baseMaps, null, { position: 'topright' }).addTo(map);

  let layerGroup = L.layerGroup().addTo(map);
  let globalAnalysisData = null;
  let activeRank = 1;

  // DOM Elements
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const fileNameDisplay = document.getElementById('fileNameDisplay');
  const btnAnalyze = document.getElementById('btnAnalyze');
  const btnSample = document.getElementById('btnSample');
  const uploadForm = document.getElementById('uploadForm');
  const loaderOverlay = document.getElementById('loaderOverlay');
  const resultsContainer = document.getElementById('resultsContainer');
  const mapStatusText = document.getElementById('mapStatusText');
  const candidateTabs = document.getElementById('candidateTabs');

  // Drag and Drop Logic
  dropZone.addEventListener('click', () => fileInput.click());

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });

  ['dragleave', 'dragend'].forEach(evt => {
    dropZone.addEventListener(evt, () => dropZone.classList.remove('drag-over'));
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      handleFileSelected();
    }
  });

  fileInput.addEventListener('change', handleFileSelected);

  function handleFileSelected() {
    if (fileInput.files.length > 0) {
      const file = fileInput.files[0];
      fileNameDisplay.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      btnAnalyze.disabled = false;
    }
  }

  // Handle Form Submit (Upload File)
  uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return;

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    await runAnalysis('/analyzeContour', {
      method: 'POST',
      body: formData
    }, fileInput.files[0].name);
  });

  // Handle Run Sample Map
  btnSample.addEventListener('click', async () => {
    await runAnalysis('/api/sample', { method: 'GET' }, 'contours_1m.kml (Sample Map)');
  });

  // Perform Analysis API Call
  async function runAnalysis(endpoint, options, filename) {
    loaderOverlay.style.display = 'flex';
    mapStatusText.textContent = `Analyzing ${filename}...`;

    try {
      const response = await fetch(endpoint, options);
      const result = await response.json();

      if (!response.ok || !result.success) {
        throw new Error(result.error || 'Failed to analyze contour map.');
      }

      globalAnalysisData = result.data;
      renderAnalysisResults(result.data, filename);
      mapStatusText.textContent = `Analysis Complete: ${filename} (${result.data.total_catchments_detected || 1} catchments detected)`;
    } catch (err) {
      alert(`Error: ${err.message}`);
      mapStatusText.textContent = 'Analysis Failed.';
    } finally {
      loaderOverlay.style.display = 'none';
    }
  }

  // Render Analysis Results & Map Layers
  function renderAnalysisResults(data, filename) {
    resultsContainer.style.display = 'block';
    layerGroup.clearLayers();

    const candidates = data.all_candidate_sites || [
      {
        rank: 1,
        is_primary: true,
        pond_location: data.pond_location,
        catchment_summary: data.catchment_summary,
        water_harvesting_estimates: data.water_harvesting_estimates,
        color: '#10B981'
      }
    ];

    // Render Tabs for Candidate Catchments
    candidateTabs.innerHTML = '';
    candidates.forEach((cand) => {
      const btn = document.createElement('button');
      btn.className = `tab-btn ${cand.rank === 1 ? 'active' : ''}`;
      btn.style.borderColor = cand.color;
      btn.innerHTML = `<span class="tab-badge" style="background:${cand.color}">#${cand.rank}</span> Site #${cand.rank} (${cand.catchment_summary.area_hectares} ha)`;
      btn.addEventListener('click', () => switchCandidate(cand.rank));
      candidateTabs.appendChild(btn);
    });

    // Populate Map Layers from GeoJSON
    if (data.geojson_layers && data.geojson_layers.features) {
      L.geoJSON(data.geojson_layers, {
        style: (feature) => {
          const color = feature.properties.color || '#06B6D4';
          return {
            color: color,
            weight: 2.5,
            opacity: 0.9,
            fillColor: color,
            fillOpacity: 0.25,
            dashArray: '5, 5'
          };
        },
        pointToLayer: (feature, latlng) => {
          const color = feature.properties.color || '#10B981';
          return L.circleMarker(latlng, {
            radius: 9,
            fillColor: color,
            color: '#FFFFFF',
            weight: 3,
            opacity: 1,
            fillOpacity: 0.95
          }).bindPopup(`
            <div style="font-family: Inter, sans-serif;">
              <h4 style="margin:0 0 4px; color:${color};">Candidate Site #${feature.properties.rank}</h4>
              <b>Elevation:</b> ${feature.properties.elevation_m} m<br>
              <b>Catchment:</b> ${feature.properties.area_ha} Hectares<br>
              <b>Suitability:</b> ${feature.properties.suitability_score}%
            </div>
          `);
        }
      }).addTo(layerGroup);
    }

    // Set map view to primary pond
    const primaryPond = data.pond_location;
    map.setView([primaryPond.latitude, primaryPond.longitude], 14);

    // Populate Sidebar Metrics for Rank 1
    displayCandidateMetrics(candidates[0]);

    // Terrain Stats
    const stats = data.terrain_statistics || {};
    document.getElementById('valElevRange').textContent = `${stats.min_elevation_m || 0}m - ${stats.max_elevation_m || 0}m`;
    document.getElementById('valSlope').textContent = `${stats.avg_slope_deg || 0}°`;
    document.getElementById('valCoverage').textContent = `${stats.map_width_meters || 0}m x ${stats.map_height_meters || 0}m`;
    document.getElementById('valContours').textContent = `${data.input_file_info ? data.input_file_info.contour_count : '2,711'} lines`;

    // JSON Collapsible
    document.getElementById('jsonPre').textContent = JSON.stringify(data, null, 2);
  }

  // Switch Active Sub-Catchment Tab
  function switchCandidate(rank) {
    activeRank = rank;
    const candidates = globalAnalysisData.all_candidate_sites || [];
    const selected = candidates.find(c => c.rank === rank) || candidates[0];

    // Update Tab UI
    document.querySelectorAll('.tab-btn').forEach((btn, idx) => {
      if (idx + 1 === rank) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    displayCandidateMetrics(selected);

    // Pan Map to Selected Site
    if (selected.pond_location) {
      map.panTo([selected.pond_location.latitude, selected.pond_location.longitude]);
    }
  }

  function displayCandidateMetrics(cand) {
    document.getElementById('selectedSiteTitle').innerHTML = `<i class="fa-solid fa-chart-pie"></i> Catchment #${cand.rank} Overview`;
    document.getElementById('valAreaHa').textContent = `${cand.catchment_summary.area_hectares} ha`;
    document.getElementById('valAreaM2').textContent = `${cand.catchment_summary.area_m2.toLocaleString()} m² / ${cand.catchment_summary.area_acres} acres`;

    const loc = cand.pond_location;
    document.getElementById('valPondCoords').textContent = `${loc.latitude}, ${loc.longitude}`;
    document.getElementById('valPondElev').textContent = `Elev: ${loc.elevation_m}m | Score: ${loc.suitability_score_pct}%`;

    const water = cand.water_harvesting_estimates;
    document.getElementById('valRunoffM3').textContent = `${water.estimated_annual_runoff_m3.toLocaleString()} m³`;
    document.getElementById('valRunoffLiters').textContent = `${(water.estimated_annual_runoff_liters / 1000000).toFixed(2)} Million Liters`;

    document.getElementById('valPondCap').textContent = `${water.recommended_pond_capacity_m3.toLocaleString()} m³`;
    document.getElementById('valPondDims').textContent = `${water.recommended_dimensions_m} (${water.recommended_pond_depth_m}m depth)`;
  }

  // Collapsible JSON Toggle
  document.getElementById('toggleJson').addEventListener('click', () => {
    const jsonBody = document.getElementById('jsonBody');
    const isHidden = jsonBody.style.display === 'none';
    jsonBody.style.display = isHidden ? 'block' : 'none';
  });
});
