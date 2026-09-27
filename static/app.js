document.addEventListener('DOMContentLoaded', () => {
  // ── Map & base layers ───────────────────────────────────────────────────
  const map = L.map('map', { zoomControl: false }).setView([21.25, 81.29], 14);
  L.control.zoom({ position: 'bottomleft' }).addTo(map);

  const streetMap = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors', maxZoom: 19
  });
  const terrainMap = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenTopoMap (CC-BY-SA)', maxZoom: 17
  });
  const satelliteMap = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
    maxZoom: 18
  });
  satelliteMap.addTo(map);

  const coverageLayer = L.layerGroup().addTo(map);   // dashed data footprint
  const drawnItems = new L.FeatureGroup().addTo(map); // user-selected land area
  const layerGroup = L.layerGroup().addTo(map);      // analysis results
  const labelLayer = L.layerGroup().addTo(map);      // permanent volume labels

  L.control.layers(
    { '🗺️ Standard Street': streetMap, '🏔️ Terrain Topo': terrainMap, '🛰️ Satellite View': satelliteMap },
    { 'Data coverage': coverageLayer, 'Selected land': drawnItems, 'Ponds & catchments': layerGroup, 'Volume labels': labelLayer },
    { position: 'topright' }
  ).addTo(map);
  L.control.scale({ imperial: false }).addTo(map);

  // Legend
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => {
    const div = L.DomUtil.create('div', 'map-legend');
    div.innerHTML = `
      <b>Legend</b>
      <div><span class="lg lg-cov"></span> Contour data coverage</div>
      <div><span class="lg lg-sel"></span> Selected land area</div>
      <div><span class="lg lg-cat"></span> Catchment (drains to pond)</div>
      <div><span class="lg lg-pond"></span> Pond footprint (to scale)</div>
      <div><span class="lg lg-site"></span> Pond site</div>`;
    return div;
  };
  legend.addTo(map);

  // ── Drawing tools (Leaflet.draw) ────────────────────────────────────────
  const shapeStyle = { color: '#FFFFFF', weight: 3, dashArray: null, fillColor: '#FFFFFF', fillOpacity: 0.06 };
  const rectDrawer = new L.Draw.Rectangle(map, { shapeOptions: shapeStyle, showArea: true, metric: true });
  const polyDrawer = new L.Draw.Polygon(map, { shapeOptions: shapeStyle, showArea: true, metric: true, allowIntersection: false });

  // ── State ───────────────────────────────────────────────────────────────
  let globalAnalysisData = null;
  let selectedPolygon = null;     // [[lon,lat],...] closed ring, or null = whole map
  let wholeMapMode = false;
  let uploadedFile = null;        // File object when the user uses their own KML/KMZ
  let lastPayload = null;         // what produced the current result (for plots / 3D)
  let activeRank = 1;

  // DOM
  const $ = (id) => document.getElementById(id);
  const loaderOverlay = $('loaderOverlay');
  const resultsContainer = $('resultsContainer');
  const mapStatusText = $('mapStatusText');
  const candidateTabs = $('candidateTabs');
  const btnAnalyzeArea = $('btnAnalyzeArea');
  const areaReadout = $('areaReadout');

  // ── Data coverage footprint ─────────────────────────────────────────────
  async function loadCoverage() {
    try {
      const res = await fetch('/api/coverage');
      const d = await res.json();
      if (!d.success) return;
      coverageLayer.clearLayers();
      const latlngs = d.coverage_polygon.map(([lon, lat]) => [lat, lon]);
      L.polygon(latlngs, { color: '#FACC15', weight: 2, dashArray: '8 6', fill: false, interactive: false })
        .addTo(coverageLayer);
      map.fitBounds(latlngs, { padding: [20, 20] });
      mapStatusText.textContent = `Sample contour data loaded (${d.elevation_range_m[0]}–${d.elevation_range_m[1]} m). Draw your land area inside the dashed boundary.`;
    } catch (e) { /* map still usable */ }
  }
  loadCoverage();

  function showUploadedCoverage(data) {
    // For an uploaded map, show the bounding box of the analysed grid as coverage
    coverageLayer.clearLayers();
    const feats = (data.geojson_layers && data.geojson_layers.features) || [];
    const pts = [];
    feats.forEach(f => {
      if (f.geometry.type === 'Point') pts.push([f.geometry.coordinates[1], f.geometry.coordinates[0]]);
      else f.geometry.coordinates[0].forEach(c => pts.push([c[1], c[0]]));
    });
    if (pts.length) map.fitBounds(pts, { padding: [40, 40] });
  }

  // ── Selection helpers ───────────────────────────────────────────────────
  function geodesicAreaM2(latlngs) {
    return (L.GeometryUtil && L.GeometryUtil.geodesicArea) ? L.GeometryUtil.geodesicArea(latlngs) : 0;
  }

  function setSelection(layer) {
    drawnItems.clearLayers();
    drawnItems.addLayer(layer);
    const latlngs = layer.getLatLngs()[0];
    selectedPolygon = latlngs.map(p => [+p.lng.toFixed(7), +p.lat.toFixed(7)]);
    selectedPolygon.push(selectedPolygon[0]);
    wholeMapMode = false;
    const a = geodesicAreaM2(latlngs);
    areaReadout.innerHTML = `Selected: <b>${(a / 10000).toFixed(2)} ha</b> (${Math.round(a).toLocaleString()} m², ${latlngs.length} vertices)`;
    btnAnalyzeArea.disabled = false;
  }

  function clearSelection() {
    drawnItems.clearLayers(); layerGroup.clearLayers(); labelLayer.clearLayers();
    selectedPolygon = null; wholeMapMode = false;
    areaReadout.innerHTML = 'No area selected — draw inside the dashed <b>data coverage</b> boundary.';
    btnAnalyzeArea.disabled = true;
    resultsContainer.style.display = 'none';
  }

  map.on(L.Draw.Event.CREATED, (e) => {
    setSelection(e.layer);
    runAreaAnalysis();                       // auto-run as soon as the area is drawn
  });

  $('btnDrawRect').addEventListener('click', () => { polyDrawer.disable(); rectDrawer.enable(); mapStatusText.textContent = 'Click and drag on the map to draw a rectangle.'; });
  $('btnDrawPoly').addEventListener('click', () => { rectDrawer.disable(); polyDrawer.enable(); mapStatusText.textContent = 'Click to add vertices; click the first point to close the polygon.'; });
  $('btnClearArea').addEventListener('click', clearSelection);
  $('btnWholeMap').addEventListener('click', () => {
    drawnItems.clearLayers(); selectedPolygon = null; wholeMapMode = true;
    areaReadout.innerHTML = 'Whole contour map selected.';
    btnAnalyzeArea.disabled = false;
    runAreaAnalysis();
  });
  btnAnalyzeArea.addEventListener('click', runAreaAnalysis);

  // ── Upload (optional dataset) ───────────────────────────────────────────
  const dropZone = $('dropZone'), fileInput = $('fileInput'), fileNameDisplay = $('fileNameDisplay'), btnAnalyze = $('btnAnalyze');
  $('toggleUpload').addEventListener('click', () => {
    const b = $('uploadBody'); b.style.display = b.style.display === 'none' ? 'block' : 'none';
  });
  dropZone.addEventListener('click', () => fileInput.click());
  dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  ['dragleave', 'dragend'].forEach(evt => dropZone.addEventListener(evt, () => dropZone.classList.remove('drag-over')));
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault(); dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; handleFileSelected(); }
  });
  fileInput.addEventListener('change', handleFileSelected);
  function handleFileSelected() {
    if (fileInput.files.length > 0) {
      const f = fileInput.files[0];
      fileNameDisplay.textContent = `Selected: ${f.name} (${(f.size / 1024).toFixed(1)} KB)`;
      btnAnalyze.disabled = false;
    }
  }
  $('uploadForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return;
    uploadedFile = fileInput.files[0];
    $('datasetName').textContent = uploadedFile.name;
    drawnItems.clearLayers(); selectedPolygon = null; wholeMapMode = true;
    areaReadout.innerHTML = `Using <b>${uploadedFile.name}</b> — whole map analysed. Now draw a land area on it.`;
    btnAnalyzeArea.disabled = false;
    const ok = await runAreaAnalysis();
    if (ok) showUploadedCoverage(globalAnalysisData);
  });
  $('btnUseSample').addEventListener('click', () => {
    uploadedFile = null; fileInput.value = ''; fileNameDisplay.textContent = ''; btnAnalyze.disabled = true;
    $('datasetName').textContent = 'contours_1m.kml (sample)';
    clearSelection(); loadCoverage();
  });

  // ── Request building (stateless: dataset + polygon + params every time) ─
  function readParams() {
    return { rainfall_mm: parseFloat($('inRain').value), runoff_coeff: parseFloat($('inCoeff').value), pond_depth_m: parseFloat($('inDepth').value) };
  }
  function buildRequest(payload) {
    if (payload.file) {
      const fd = new FormData();
      fd.append('file', payload.file);
      if (payload.polygon) fd.append('polygon', JSON.stringify(payload.polygon));
      Object.entries(payload.params).forEach(([k, v]) => fd.append(k, v));
      return { method: 'POST', body: fd };
    }
    return { method: 'POST', headers: { 'Content-Type': 'application/json' },
             body: JSON.stringify({ polygon: payload.polygon, ...payload.params }) };
  }

  async function runAreaAnalysis() {
    if (!selectedPolygon && !wholeMapMode) { mapStatusText.textContent = 'Draw a land area first.'; return false; }
    const payload = { polygon: selectedPolygon, params: readParams(), file: uploadedFile };
    loaderOverlay.style.display = 'flex';
    mapStatusText.textContent = 'Analysing selected land area...';
    const t0 = performance.now();
    try {
      const response = await fetch('/api/analyzeArea', buildRequest(payload));
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || `Request failed (${response.status})`);
      const rtt = Math.round(performance.now() - t0);
      globalAnalysisData = result.data;
      lastPayload = payload;
      renderAnalysisResults(result.data);
      $('valServed').textContent = `${result.served_by} · ${rtt} ms${result.cache_hit ? ' (cached)' : ''}`;
      const n = result.data.total_catchments_detected || 1;
      mapStatusText.textContent = `${n} pond site${n > 1 ? 's' : ''} found · expected ${Math.round(result.data.total_expected_water_volume_all_sites_m3).toLocaleString()} m³/yr · ${rtt} ms`;
      return true;
    } catch (err) {
      mapStatusText.textContent = `⚠ ${err.message}`;
      layerGroup.clearLayers(); labelLayer.clearLayers();
      resultsContainer.style.display = 'none';
      return false;
    } finally {
      loaderOverlay.style.display = 'none';
    }
  }

  // ── Rendering ───────────────────────────────────────────────────────────
  const fmt = (v, d = 0) => Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

  function renderAnalysisResults(data) {
    resultsContainer.style.display = 'block';
    layerGroup.clearLayers(); labelLayer.clearLayers();
    const candidates = data.all_candidate_sites || [];
    const feats = (data.geojson_layers && data.geojson_layers.features) || [];

    candidateTabs.innerHTML = '';
    candidates.forEach((cand) => {
      const btn = document.createElement('button');
      btn.className = `tab-btn ${cand.rank === 1 ? 'active' : ''}`;
      btn.style.borderColor = cand.color;
      btn.innerHTML = `<span class="tab-badge" style="background:${cand.color}">#${cand.rank}</span> Site #${cand.rank} · ${cand.catchment_summary.area_hectares} ha · ${fmt(cand.water_harvesting_estimates.expected_water_volume_m3)} m³`;
      btn.addEventListener('click', () => switchCandidate(cand.rank));
      candidateTabs.appendChild(btn);
    });
    const note = $('siteNote');
    if (data.site_selection_note) { note.style.display = 'block'; note.textContent = data.site_selection_note; }
    else note.style.display = 'none';

    const bounds = [];
    const order = { selected_area: 0, catchment: 1, pond_footprint: 2, pond_site: 3 };
    feats.slice().sort((a, b) => order[a.properties.kind] - order[b.properties.kind]).forEach((f) => {
      const p = f.properties;
      if (f.geometry.type === 'Point') {
        const [lon, lat] = f.geometry.coordinates;
        bounds.push([lat, lon]);
        const m = L.circleMarker([lat, lon], { radius: 9, fillColor: p.color, color: '#FFFFFF', weight: 3, fillOpacity: 1 })
          .bindPopup(`
            <div style="font-family:Inter,sans-serif;min-width:210px">
              <h4 style="margin:0 0 6px;color:${p.color};font-size:14px">📍 Pond Site #${p.rank}</h4>
              <table style="width:100%;font-size:12px;border-collapse:collapse">
                <tr><td><b>Location</b></td><td>${lat.toFixed(5)}, ${lon.toFixed(5)}</td></tr>
                <tr><td><b>Elevation</b></td><td>${p.elevation_m} m</td></tr>
                <tr><td><b>Catchment</b></td><td>${p.area_ha} ha</td></tr>
                <tr><td><b>Water volume</b></td><td>${fmt(p.water_volume_m3)} m³/yr</td></tr>
                <tr><td><b>Pond capacity</b></td><td>${fmt(p.pond_capacity_m3)} m³</td></tr>
                <tr><td><b>Suitability</b></td><td>${p.suitability_score}%</td></tr>
                <tr><td><b>River dist.</b></td><td>${p.river_distance_m} m</td></tr>
              </table>
            </div>`)
          .addTo(layerGroup);
        m.on('click', () => switchCandidate(p.rank, false));
        L.marker([lat, lon], {
          interactive: false,
          icon: L.divIcon({ className: 'vol-label', iconSize: null, iconAnchor: [-12, 18],
            html: `<div style="border-color:${p.color}"><b>#${p.rank}</b> 💧 ${fmt(p.water_volume_m3)} m³/yr<br><small>catchment ${p.area_ha} ha · pond ${fmt(p.pond_capacity_m3)} m³</small></div>` })
        }).addTo(labelLayer);
        return;
      }
      const latlngs = f.geometry.coordinates[0].map(([lon, lat]) => [lat, lon]);
      latlngs.forEach(ll => bounds.push(ll));
      if (p.kind === 'selected_area') {
        L.polygon(latlngs, { color: '#FFFFFF', weight: 2.5, fill: false, interactive: false }).addTo(layerGroup);
      } else if (p.kind === 'catchment') {
        L.polygon(latlngs, { color: p.color, weight: 2, fillColor: p.color, fillOpacity: 0.28 })
          .bindTooltip(`<b>Catchment #${p.rank}</b><br>${p.area_ha} ha → ${fmt(p.water_volume_m3)} m³/yr`, { sticky: true })
          .addTo(layerGroup);
      } else if (p.kind === 'pond_footprint') {
        L.polygon(latlngs, { color: '#93C5FD', weight: 2, fillColor: '#2563EB', fillOpacity: 0.85 })
          .bindTooltip(`<b>Pond #${p.rank}</b> ${p.dimensions} × ${p.depth_m} m<br>capacity ${fmt(p.pond_capacity_m3)} m³`, { sticky: true })
          .addTo(layerGroup);
      }
    });

    if (!selectedPolygon && bounds.length) map.fitBounds(bounds, { padding: [30, 30] });
    else if (selectedPolygon) map.fitBounds(drawnItems.getBounds().extend(L.latLngBounds(bounds)), { padding: [30, 30] });

    displayCandidateMetrics(candidates[0]);

    const stats = data.terrain_statistics || {};
    $('valElevRange').textContent = `${stats.min_elevation_m}m - ${stats.max_elevation_m}m`;
    $('valSlope').textContent = `${stats.avg_slope_deg}° avg | TWI ${stats.avg_twi}`;
    $('valCoverage').textContent = `${fmt(stats.map_width_meters)}m x ${fmt(stats.map_height_meters)}m | cell ${stats.cell_size_m}m | buffer ${stats.river_buffer_used_m}m`;
    $('valContours').textContent = `${data.input_file_info ? fmt(data.input_file_info.contour_count) : '-'} lines | ${stats.utm_projection}`;
    const sa = data.selected_area;
    $('valSelArea').textContent = sa ? `${sa.area_hectares} ha` : 'Whole map';
    $('valSelAreaSub').textContent = sa ? `${sa.data_coverage_pct}% covered by contour data` : `${fmt(stats.map_width_meters)} × ${fmt(stats.map_height_meters)} m`;
    $('jsonPre').textContent = JSON.stringify(data, null, 2);
  }

  function switchCandidate(rank, pan = true) {
    activeRank = rank;
    const candidates = globalAnalysisData.all_candidate_sites || [];
    const selected = candidates.find(c => c.rank === rank) || candidates[0];
    document.querySelectorAll('.tab-btn').forEach((btn, idx) => btn.classList.toggle('active', idx + 1 === rank));
    displayCandidateMetrics(selected);
    if (pan && selected.pond_location) map.panTo([selected.pond_location.latitude, selected.pond_location.longitude]);
  }

  function displayCandidateMetrics(cand) {
    $('selectedSiteTitle').innerHTML = `<i class="fa-solid fa-chart-pie"></i> Pond Site #${cand.rank} Results`;
    $('valAreaHa').textContent = `${cand.catchment_summary.area_hectares} ha`;
    $('valAreaM2').textContent = `${fmt(cand.catchment_summary.area_m2)} m² / ${cand.catchment_summary.area_acres} acres`;
    const loc = cand.pond_location;
    $('valPondCoords').textContent = `${loc.latitude}, ${loc.longitude}`;
    $('valPondElev').textContent = `Elev: ${loc.elevation_m}m | slope ${loc.terrain_slope_deg}° | river ${loc.river_buffer_distance_m}m`;
    const w = cand.water_harvesting_estimates;
    $('valVolume').textContent = `${fmt(w.expected_water_volume_m3)} m³`;
    $('valVolumeSub').textContent = `${(w.estimated_annual_runoff_liters / 1e6).toFixed(2)} ML = ${w.runoff_coefficient_C} × ${w.assumed_annual_rainfall_mm} mm × ${cand.catchment_summary.area_hectares} ha`;
    $('valPondCap').textContent = `${fmt(w.recommended_pond_capacity_m3)} m³`;
    $('valPondDims').textContent = `${w.recommended_dimensions_m} × ${w.recommended_pond_depth_m}m deep`;
  }

  // Payload for plots / 3D uses exactly the request that produced the results
  function currentRequest() {
    return lastPayload ? buildRequest(lastPayload) : { method: 'GET' };
  }

  // ── Terrain Plots Modal ─────────────────────────────────────────────────
  const plotsModal = document.getElementById('plotsModal');
  const plotsLoading = document.getElementById('plotsLoading');
  const plotsGrid = document.getElementById('plotsGrid');
  const btnTerrain = document.getElementById('btnTerrainPlots');
  const closePlots = document.getElementById('closePlots');
  const plotsLoadingHTML = plotsLoading.innerHTML;

  const PLOT_LABELS = {
    '3d_elevation': { title: '3D Terrain Elevation Surface', icon: 'fa-mountain' },
    'dem_heatmap': { title: 'DEM Heatmap + Candidate Sites', icon: 'fa-map' },
    'slope_map': { title: 'Slope Map (Horn\'s 8-Neighbour)', icon: 'fa-angles-up' },
    'flow_accumulation': { title: 'D8 Flow Accumulation (log scale)', icon: 'fa-water' },
    'twi_map': { title: 'Topographic Wetness Index (TWI)', icon: 'fa-droplet' },
    'depression_map': { title: 'Terrain Depression Depth (Sinks)', icon: 'fa-arrow-trend-down' },
  };

  if (btnTerrain) {
    btnTerrain.addEventListener('click', async () => {
      plotsModal.style.display = 'block';
      plotsLoading.innerHTML = plotsLoadingHTML;
      plotsLoading.style.display = 'block';
      plotsGrid.style.display = 'none';
      plotsGrid.innerHTML = '';

      try {
        const res = await fetch('/api/plots', currentRequest());
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Plot generation failed');

        Object.entries(data.plots).forEach(([key, b64]) => {
          const meta = PLOT_LABELS[key] || { title: key, icon: 'fa-image' };
          const card = document.createElement('div');
          card.style.cssText = 'background:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #334155;';
          card.innerHTML = `
            <div style="padding:10px 14px;background:#0f172a;border-bottom:1px solid #334155;">
              <h4 style="margin:0;color:#10B981;font-size:13px;font-family:Inter,sans-serif;">
                <i class="fa-solid ${meta.icon}" style="margin-right:6px;"></i>${meta.title}
              </h4>
            </div>
            <img src="data:image/png;base64,${b64}" style="width:100%;display:block;" alt="${meta.title}">
          `;
          plotsGrid.appendChild(card);
        });

        plotsGrid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:14px;';
        plotsLoading.style.display = 'none';
        plotsGrid.style.display = 'grid';
      } catch (err) {
        plotsLoading.innerHTML = `<p style="color:#ef4444;"><i class="fa-solid fa-circle-exclamation"></i> ${err.message}</p>`;
      }
    });
  }

  if (closePlots) {
    closePlots.addEventListener('click', () => { plotsModal.style.display = 'none'; });
  }
  plotsModal && plotsModal.addEventListener('click', (e) => {
    if (e.target === plotsModal) plotsModal.style.display = 'none';
  });

  // Collapsible JSON Toggle
  const toggleJson = document.getElementById('toggleJson');
  if (toggleJson) {
    toggleJson.addEventListener('click', () => {
      const jsonBody = document.getElementById('jsonBody');
      if (jsonBody) {
        const isHidden = jsonBody.style.display === 'none';
        jsonBody.style.display = isHidden ? 'block' : 'none';
      }
    });
  }

  // ── Interactive 3D WebGL Terrain Renderer (Plotly.js) ───────────────────
  const modal3D = document.getElementById('modal3D');
  const btn3DTerrain = document.getElementById('btn3DTerrain');
  const close3D = document.getElementById('close3D');
  const btnReset3D = document.getElementById('btnReset3D');
  const plotly3DLoading = document.getElementById('plotly3DLoading');
  let plotly3DData = null;
  const plotly3DLoadingHTML = plotly3DLoading.innerHTML;

  if (btn3DTerrain) {
    btn3DTerrain.addEventListener('click', async () => {
      modal3D.style.display = 'block';
      plotly3DLoading.innerHTML = plotly3DLoadingHTML;
      plotly3DLoading.style.display = 'flex';

      try {
        const res = await fetch('/api/terrain_3d_mesh', currentRequest());
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Failed to fetch 3D mesh');

        plotly3DData = data;
        renderPlotly3DTerrain(data);
        plotly3DLoading.style.display = 'none';
      } catch (err) {
        plotly3DLoading.innerHTML = `<p style="color:#ef4444;"><i class="fa-solid fa-circle-exclamation"></i> ${err.message}</p>`;
      }
    });
  }

  function renderPlotly3DTerrain(data) {
    if (typeof Plotly === 'undefined') {
      plotly3DLoading.innerHTML = `<p style="color:#ef4444;">Plotly library failed to load. Please check your internet connection.</p>`;
      return;
    }

    const minElev = data.min_elev;
    const maxElev = data.max_elev;
    const zRange  = data.z_range;

    // Vibrant topographical colormap:
    // River channel (deep blue) -> Water edge (cyan) -> Farmland basin (emerald) -> Slopes (gold) -> Peaks (mountain brown)
    const customTerrainColorscale = [
      [0.00, '#0f172a'],
      [0.15, '#1e3a8a'],
      [0.30, '#0284c7'],
      [0.48, '#10b981'],
      [0.68, '#eab308'],
      [0.85, '#d97706'],
      [1.00, '#78350f']
    ];

    const surfaceTrace = {
      type: 'surface',
      x: data.x,
      y: data.y,
      z: data.z,
      cmin: minElev,
      cmax: maxElev,
      colorscale: customTerrainColorscale,
      contours: {
        z: { show: true, usecolormap: true, highlightcolor: '#38bdf8', project: { z: true } }
      },
      colorbar: {
        title: { text: `Elevation (m)<br><span style="font-size:11px;color:#94a3b8;">${minElev}m – ${maxElev}m</span>`, side: 'right' },
        thickness: 18,
        len: 0.85,
        tickfont: { color: '#cbd5e1', size: 11 },
        titlefont: { color: '#10B981', size: 13 }
      },
      lighting: {
        ambient: 0.65,
        diffuse: 0.8,
        fresnel: 0.2,
        specular: 0.5,
        roughness: 0.4
      }
    };

    const candX = data.candidates.map(c => c.longitude);
    const candY = data.candidates.map(c => c.latitude);
    const candZ = data.candidates.map(c => c.elevation_m + 2.0);
    const candText = data.candidates.map(c => `${c.label}<br>Elev: ${c.elevation_m}m`);
    const candColors = data.candidates.map(c => c.color);

    const scatterTrace = {
      type: 'scatter3d',
      mode: 'markers+text',
      x: candX,
      y: candY,
      z: candZ,
      text: data.candidates.map(c => `Site #${c.rank}`),
      textposition: 'top center',
      textfont: { color: '#ffffff', size: 13, family: 'Inter', weight: 'bold' },
      hoverinfo: 'text',
      hovertext: candText,
      marker: {
        size: 10,
        color: candColors,
        symbol: 'diamond',
        line: { color: '#ffffff', width: 2 }
      }
    };

    const layout = {
      margin: { l: 0, r: 0, b: 0, t: 0 },
      paper_bgcolor: '#090d16',
      plot_bgcolor: '#090d16',
      scene: {
        xaxis: { title: 'Longitude', titlefont: { color: '#94a3b8' }, tickfont: { color: '#64748b' }, gridcolor: '#1e293b' },
        yaxis: { title: 'Latitude', titlefont: { color: '#94a3b8' }, tickfont: { color: '#64748b' }, gridcolor: '#1e293b' },
        zaxis: {
          title: 'Elevation (m)',
          titlefont: { color: '#10B981' },
          tickfont: { color: '#64748b' },
          gridcolor: '#1e293b',
          range: zRange
        },
        camera: {
          eye: { x: 1.55, y: -1.55, z: 0.95 }
        }
      }
    };

    const config = {
      responsive: true,
      displayModeBar: true,
      modeBarButtonsToRemove: ['toImage'],
      displaylogo: false
    };

    Plotly.newPlot('plotly3DContainer', [surfaceTrace, scatterTrace], layout, config);
  }

  if (btnReset3D) {
    btnReset3D.addEventListener('click', () => {
      if (plotly3DData) renderPlotly3DTerrain(plotly3DData);
    });
  }

  if (close3D) {
    close3D.addEventListener('click', () => { modal3D.style.display = 'none'; });
  }
  modal3D && modal3D.addEventListener('click', (e) => {
    if (e.target === modal3D) modal3D.style.display = 'none';
  });

});
