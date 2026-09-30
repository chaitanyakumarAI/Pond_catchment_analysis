import os
import subprocess
import shutil

html_template = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AI-based Village Pond Planning System - Final Technical Report</title>
<style>
  @page {
    size: A4;
    margin: 22mm 20mm 22mm 20mm;
    @bottom-center {
      content: counter(page);
      font-family: 'Times New Roman', Times, serif;
      font-size: 10pt;
    }
  }
  body {
    font-family: 'Times New Roman', Times, serif;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #111;
    margin: 0;
    padding: 0;
  }
  h1.title {
    font-size: 19pt;
    font-weight: bold;
    text-align: center;
    margin-bottom: 4px;
  }
  div.subtitle {
    font-size: 12pt;
    text-align: center;
    color: #444;
    margin-bottom: 14px;
  }
  div.authors {
    text-align: center;
    margin-bottom: 20px;
    font-size: 10.5pt;
    line-height: 1.35;
  }
  div.abstract-box {
    margin: 0 10px 18px 10px;
    font-size: 9.5pt;
    line-height: 1.38;
    text-align: justify;
    background: #fdfdfd;
    padding: 8px 12px;
    border: 1px solid #ebebeb;
    border-radius: 4px;
  }
  div.abstract-title {
    font-weight: bold;
    display: inline;
  }
  div.keywords {
    margin-top: 8px;
    font-size: 9pt;
  }
  hr.sep {
    border: none;
    border-top: 1px solid #ddd;
    margin: 14px 0;
  }
  h2 {
    font-size: 12.5pt;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 20px;
    margin-bottom: 6px;
    border-bottom: 1px solid #222;
    padding-bottom: 2px;
  }
  h3 {
    font-size: 11pt;
    font-weight: bold;
    margin-top: 12px;
    margin-bottom: 4px;
  }
  p {
    margin-top: 0;
    margin-bottom: 8px;
    text-align: justify;
    text-indent: 1.5em;
  }
  p.no-indent {
    text-indent: 0;
  }
  ul, ol {
    margin-top: 4px;
    margin-bottom: 8px;
    padding-left: 24px;
  }
  li {
    margin-bottom: 3px;
    text-align: justify;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 4px 0;
    font-size: 9pt;
  }
  table.booktabs th {
    border-top: 2px solid #000;
    border-bottom: 1px solid #000;
    padding: 5px 6px;
    text-align: left;
    font-weight: bold;
  }
  table.booktabs td {
    padding: 4px 6px;
    border-bottom: 1px solid #e0e0e0;
  }
  table.booktabs tr:last-child td {
    border-bottom: 2px solid #000;
  }
  .caption {
    font-size: 9pt;
    font-weight: bold;
    margin-bottom: 4px;
    text-align: center;
  }
  .figure-caption {
    font-size: 9pt;
    margin-top: 5px;
    margin-bottom: 14px;
    text-align: center;
  }
  .figure-box {
    text-align: center;
    margin: 14px 0;
    page-break-inside: avoid;
  }
  .figure-box img {
    max-width: 96%;
    height: auto;
    border: 1px solid #ddd;
    border-radius: 4px;
  }
  .img-row {
    display: flex;
    justify-content: space-between;
    gap: 10px;
  }
  .img-row img {
    width: 49%;
  }
  .img-row-3 {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
  }
  .subfig {
    text-align: center;
    font-size: 8.5pt;
    color: #333;
  }
  .subfig img {
    width: 100%;
    border: 1px solid #ddd;
    border-radius: 4px;
  }
  pre, code {
    font-family: 'Consolas', 'Courier New', monospace;
  }
  pre {
    background: #f8f9fa;
    border: 1px solid #ddd;
    padding: 8px 12px;
    font-size: 8.5pt;
    border-radius: 4px;
    overflow-x: auto;
    line-height: 1.3;
    page-break-inside: avoid;
  }
  a {
    color: #0366d6;
    text-decoration: none;
  }
  .page-break {
    page-break-before: always;
  }
</style>
</head>
<body>

<h1 class="title">AI-based Village Pond Planning System</h1>
<div class="subtitle">CSD Assignment 1 &mdash; Final Technical Report</div>

<div class="authors">
  <strong>Ranga Chandra Naga Venkata Chaitanya Kumar</strong> (Roll No. 12341740)<br>
  Department of Computer Science and Engineering, IIT Bhilai, India<br>
  <code>chaitanya.kumar@iitbhilai.ac.in</code><br>
  <strong>GitHub:</strong> <a href="https://github.com/chaitanyakumarAI/Pond_catchment_analysis">https://github.com/chaitanyakumarAI/Pond_catchment_analysis</a> &nbsp;|&nbsp; 
  <strong>Live System:</strong> <a href="http://10.1.75.51:5237/">http://10.1.75.51:5237/</a>
</div>

<div class="abstract-box">
  <div class="abstract-title">ABSTRACT.</div>
  Small-scale farm ponds are a vital rainwater-harvesting intervention for mitigating seasonal drought and enhancing agricultural resilience across rural India. However, traditional manual site-selection approaches rely on labor-intensive, ad-hoc topographical field surveys that struggle to analyze spatial hydrology across extensive areas. This project presents a high-throughput, web-based geospatial decision-support system designed to identify optimal village pond locations, delineate catchment boundaries, and calculate expected annual rainwater runoff. Built on an interactive Leaflet GIS interface, the user selects any arbitrary agricultural parcel or village boundary via polygon and rectangle drawing tools. The backend processes contour maps to construct high-resolution Digital Elevation Models (DEMs), executes Priority-Flood sink filling, delineates D8 hydrological flow routing, and computes a multi-criteria Pond Suitability Index (PSI) combining depression depth, upstream flow accumulation, topographic wetness index (TWI), and relative slope elevation. To achieve sub-second interactive latency while serving hundreds of concurrent village administrators, the system decouples heavy one-time terrain modeling from lightweight, millisecond-scale polygon queries. The architecture is deployed as a horizontally scaled cluster across four multi-core lab systems (120 CPU cores each) orchestrated by a custom Layer-7 Load Balancer implemented in Go, featuring least-inflight connection routing, active health probes, and admission control. Under stress testing with 200 concurrent users, the distributed cluster sustained 138.7 requests per second with a 95th-percentile latency under 120 ms and 0% error rates, compared to severe saturation on a single-node deployment. The production web application is live and publicly accessible at <code>http://10.1.75.51:5237/</code>.
  <div class="keywords">
    <strong>Keywords:</strong> Village Pond Planning, Geospatial Hydrology, Digital Elevation Models, Rainwater Harvesting, Catchment Delineation, Layer-7 Load Balancing, Web GIS, Distributed Systems
  </div>
</div>

<hr class="sep">

<h2>1. Introduction</h2>
<p>Rural water security remains one of the most pressing socio-economic challenges in arid and semi-arid regions of India. Monsoon rainfall is concentrated within a few intense spells, leading to rapid surface runoff and prolonged dry-season soil moisture deficits. Village farm ponds harvest local surface runoff during high-precipitation events, recharging shallow aquifers and providing supplementary irrigation during critical crop growth stages. Despite their proven efficacy, planning where to dig a pond is fraught with technical complexity. A poorly situated pond either fails to capture sufficient runoff or gets overwhelmed by excessive sediment and river flooding.</p>
<p>The primary goal of this assignment is to develop an end-to-end, high-performance, AI- and geospatial-assisted web application that allows users to interactively draw land boundaries on a map and instantly receive mathematically validated pond locations, upstream catchment boundaries, and annual water harvest estimates. The system must run across four designated physical cluster nodes and handle high concurrency gracefully.</p>

<h3>1.1 Motivation</h3>
<p class="no-indent">Manual site selection conducted by village administrators or local panchayat engineers typically relies on physical walkthroughs or static topographic sheets. These conventional methods suffer from three critical bottlenecks:</p>
<ol>
  <li><strong>Topographical Complexity:</strong> Identifying natural drainage depressions and ridge lines over undulating terrain requires calculating slope gradients and hydraulic flow vectors that cannot be intuitively gauged by eye.</li>
  <li><strong>Catchment Computation Bottlenecks:</strong> Calculating the exact contributing catchment area draining into a candidate point requires recursive flow tracing across large spatial grids, a task virtually impossible without automated GIS tools.</li>
  <li><strong>Inaccessibility for Non-Technical Users:</strong> Standard desktop GIS packages (e.g., QGIS, ArcGIS) require significant domain expertise, large local dataset downloads, and manual contour processing, preventing rapid field deployment.</li>
</ol>
<p>An automated, browser-accessible GIS tool eliminates these barriers by abstracting advanced hydrological pipelines behind an intuitive web interface that produces actionable results in milliseconds.</p>

<h3>1.2 Scope of the Project</h3>
<p class="no-indent">The system covers: (1) Ingestion and validation of standard contour data (KML/KMZ formats) and automatic UTM coordinate projection; (2) Digital Elevation Model (DEM) construction, sink filling, D8 flow accumulation, and river corridor buffer masking; (3) Dynamic parcel-restricted queries via interactive Leaflet bounding rectangles or arbitrary free-form polygons; (4) Automated recommendation of up to four optimal pond sites ranked by suitability, exact upstream catchment polygons, and scale pond footprint geometries; (5) Rational-method annual runoff volume estimation (<i>Q = C &middot; P &middot; A</i>) and pond storage capacity sizing; (6) Layer-7 load balancing, health monitoring, and horizontal scaling across four multi-core Linux nodes. The system explicitly does <em>not</em> cover civil geotechnical engineering (e.g., soil permeability drilling, embankment slope stability, masonry spillway design) or legal cadastre ownership verification.</p>

<h2>2. Problem Statement and Requirements</h2>
<p class="no-indent">The functional requirements specified in the project guidelines and their corresponding implementation modules are mapped in Table 1.</p>

<div class="caption">Table 1: Functional requirements and where they are implemented</div>
<table class="booktabs">
  <thead>
    <tr>
      <th style="width: 42%;">Requirement</th>
      <th style="width: 58%;">Implemented in Module / File</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>Satellite &amp; topographic imagery display</td><td><code>static/index.html</code>, <code>static/app.js</code> (Leaflet tile layers)</td></tr>
    <tr><td>Contour map visualization</td><td><code>modules/kml_parser.py</code>, <code>app.py</code> (<code>/api/coverage</code>)</td></tr>
    <tr><td>Available-land parcel identification</td><td><code>static/app.js</code> (Leaflet.draw polygon and rectangle tools)</td></tr>
    <tr><td>Catchment area delineation</td><td><code>modules/hydrology.py</code> (<code>delineate_catchment</code> reverse-D8)</td></tr>
    <tr><td>Historical/configurable rainfall query</td><td><code>modules/hydrology.py</code>, <code>static/app.js</code> (Parametric inputs)</td></tr>
    <tr><td>Runoff volume estimation</td><td><code>modules/hydrology.py</code> (<code>calculate_runoff</code> rational method)</td></tr>
    <tr><td>Pond depth / storage recommendation</td><td><code>modules/hydrology.py</code> (<code>recommend_pond_dimensions</code>)</td></tr>
    <tr><td>Combined overlay / GeoJSON results view</td><td><code>static/app.js</code>, <code>app.py</code> (<code>POST /api/analyzeArea</code>)</td></tr>
  </tbody>
</table>

<h3>2.1 Non-Functional Requirements</h3>
<ul>
  <li><strong>N1 &mdash; Interactive Latency:</strong> Bounded-area user queries must execute in well under 100 ms to maintain seamless user interaction during interactive map exploration.</li>
  <li><strong>N2 &mdash; Horizontal Scalability:</strong> The workload must distribute evenly across the four physical lab nodes without single-worker bottlenecks.</li>
  <li><strong>N3 &mdash; Overload Protection &amp; Graceful Degradation:</strong> When concurrency exceeds worker capacity, incoming traffic must be queued with bounded timeouts (15 s) and gracefully shed via HTTP 503 (<code>Retry-After</code>) rather than cascading into worker process crashes.</li>
  <li><strong>N4 &mdash; Fault Tolerance:</strong> Automatic health probing must detect crashed or lagging backend nodes within 2 seconds, dynamically routing active traffic to surviving nodes.</li>
  <li><strong>N5 &mdash; Robust Validation:</strong> Invalid polygon selections (e.g., area &lt; 0.5 ha, &gt; 50 km&sup2;, or falling outside available contour coverage) must be rejected immediately with clean HTTP 422 error messages.</li>
</ul>

<h2>3. System Architecture and High-Level Design</h2>
<p>The system follows a decoupled, stateless distributed architecture designed for high throughput and zero inter-worker coordination. Client requests from the Leaflet GIS single-page web app connect via HTTP to Sys1 on port 5237, which is exposed publicly. Sys1 hosts a custom Layer-7 Load Balancer written in pure Go (<code>cluster/pond_lb.go</code>), which inspects the cluster state and reverse-proxies requests across four backend worker nodes (<code>stu10_sys1</code> through <code>stu10_sys4</code>) on internal port 5002.</p>
<p>Each cluster node runs Ubuntu 24.04 on a 120-core CPU with 128 GB of RAM. The Python Flask application is deployed under Gunicorn using 119 synchronous worker processes per machine. To eliminate startup latency and conserve memory, Gunicorn is started with <code>--preload</code>, allowing all worker processes to inherit the precomputed terrain matrix via copy-on-write virtual memory.</p>

<h3>3.1 Technology Stack</h3>
<ul>
  <li><strong>Frontend GIS:</strong> HTML5, Vanilla JavaScript, Leaflet 1.9.4, Leaflet.draw 1.0.4, Plotly.js 2.26 (for interactive 3D elevation meshes).</li>
  <li><strong>Load Balancer:</strong> Go (v1.22+). Chosen for lightweight goroutines, microsecond proxy latencies, and minimal memory footprint.</li>
  <li><strong>Application Server:</strong> Python 3.12/3.14, Flask, Gunicorn (synchronous worker model, 119 workers per node matched to available cores).</li>
  <li><strong>Hydrology Engine:</strong> NumPy, SciPy (multivariate grid interpolation, Gaussian spatial filters, vector operations).</li>
  <li><strong>Deployment Automation:</strong> Python Paramiko, <code>sshpass</code>, Bash cluster management.</li>
</ul>

<h2>4. Methodology</h2>
<p>To achieve sub-second interactive latency, the hydrological pipeline is strictly partitioned into two operational stages: (1) <strong>Stage A (Terrain &amp; Hydrology Synthesis)</strong> executed once per dataset, and (2) <strong>Stage B (Dynamic Parcel Query)</strong> executed in milliseconds per user request.</p>

<h3>4.1 Terrain and Elevation Analysis</h3>
<p class="no-indent">Contour data is parsed from KML/KMZ documents containing 2,711 contour lines and 160,473 vertices. Raw geographic coordinates are projected into Universal Transverse Mercator (UTM Zone 44N, EPSG:32644) to establish Cartesian metric units:</p>
<ol>
  <li><strong>Spike Filtering:</strong> Anomalous elevation vertices outside the 1st&ndash;99th percentile window are rejected.</li>
  <li><strong>Grid Interpolation:</strong> Linear barycentric interpolation discretizes the irregular contours onto a regular grid of 200 &times; 161 cells with a spatial resolution of 16.2 m &times; 16.2 m.</li>
  <li><strong>Surface Smoothing:</strong> A Gaussian filter with standard deviation &sigma; = 1.0 attenuates interpolation artifacts.</li>
  <li><strong>Sink Filling:</strong> Depressions are identified using the Priority-Flood algorithm (Barnes, 2014). The water depression depth <i>d = z<sub>filled</sub> &minus; z<sub>raw</sub></i> marks natural runoff collection bowls.</li>
</ol>

<h3>4.2 Catchment Area Delineation</h3>
<p>Surface runoff follows the steepest gradient across the 8-connected grid (D8 routing). Flow accumulation <i>A</i> (number of upstream contributing cells) is computed via reverse topological sorting from highest to lowest elevation. River corridors are identified where <i>A &ge; P<sub>95</sub>(A)</i> or where cells lie in the lowest 18% elevation with slope &lt; 3&deg;. Candidate pond sites are enforced to remain &ge; max(120 m, 0.25 d<sub>max</sub>) away from river paths to prevent flood destruction.</p>
<p>The composite Pond Suitability Index (PSI) combines four normalized factors:
<br><center><b>PSI = 0.35 &middot; d&#770; + 0.30 &middot; ln(1+A)&#770; + 0.20 &middot; TWI&#770; + 0.15 &middot; (1 &minus; z&#770;)</b></center><br>
where <b>&#770;</b> denotes min&ndash;max normalization, <b>z&#770;</b> is normalized elevation, and <b>TWI = ln(a / tan &beta;)</b> represents the Topographic Wetness Index for specific catchment area <i>a</i> and slope <i>&beta;</i>. In Stage B, local maxima of the PSI within the drawn polygon are selected and upstream catchments are delineated via reverse-D8 traversal.</p>

<h3>4.3 Rainfall and Runoff Integration</h3>
<p>Annual rainfall depth (<i>P</i>, default 850 mm) and runoff coefficient (<i>C</i>, default 0.35) are integrated using the Rational Method:
<br><center><b>Q = C &middot; (P / 1000) &middot; (A<sub>catchment</sub> &times; 10<sup>4</sup>) &nbsp; [m&sup3;/year]</b></center><br>
Recommended pond capacity is determined as <b>V<sub>pond</sub> = min(0.18 &middot; Q, 25,000) m&sup3;</b>, assuming a typical depth <i>H = 3.5 m</i> with 1:1.5 side slopes.</p>

<h2>5. Implementation</h2>

<h3>5.1 Backend and API Design</h3>
<p class="no-indent">The Flask backend exposes clean, stateless RESTful endpoints documented in Table 2.</p>

<div class="caption">Table 2: Backend REST API specification</div>
<table class="booktabs">
  <thead>
    <tr>
      <th style="width: 15%;">Method</th>
      <th style="width: 25%;">Path</th>
      <th style="width: 60%;">Purpose &amp; Response Contract</th>
    </tr>
  </thead>
  <tbody>
    <tr><td><code>GET</code></td><td><code>/health</code></td><td>Liveness probe returning node hostname, core count, and worker uptime.</td></tr>
    <tr><td><code>GET</code></td><td><code>/api/coverage</code></td><td>Returns GeoJSON polygon of active DEM boundaries for client map rendering.</td></tr>
    <tr><td><code>POST</code></td><td><code>/api/analyzeArea</code></td><td>Evaluates drawn polygon; returns GeoJSON FeatureCollection of sites, catchments, and scaled pond footprints.</td></tr>
    <tr><td><code>POST</code></td><td><code>/upload</code></td><td>Accepts user KML/KMZ upload; triggers Stage A terrain model synthesis.</td></tr>
    <tr><td><code>GET</code></td><td><code>/api/mesh3d</code></td><td>Returns downsampled 3D elevation matrix for interactive Plotly visualization.</td></tr>
  </tbody>
</table>

<h3>5.2 Frontend and Visualization</h3>
<p class="no-indent">The single-page web client provides an interactive Leaflet map featuring satellite, topographic, and street basemaps. As illustrated in Figure 1, the user draws a boundary over the agricultural parcel. Within tens of milliseconds, the map displays: (1) colored semi-transparent catchment boundaries, (2) solid blue scaled pond excavation footprints, and (3) interactive marker pins displaying annual water yield (<i>Q</i>), catchment acreage, and excavation dimensions.</p>

<div class="figure-box">
  <img src="figures/ui_result.png" alt="Application Interface Overlay">
  <div class="figure-caption">Figure 1: Application interface (<code>http://10.1.75.51:5237/</code>) showing an analyzed agricultural parcel with four recommended pond sites, catchment boundaries, and runoff metrics computed in 96 ms on <code>stu10_sys1</code>.</div>
</div>

<p>The interactive parcel drawing and metrics pipeline is shown in Figure 2. Using the rectangle or polygon drawing tools, the user specifies the parcel boundary within the contour extent (Figure 2a). Upon mouse release, the client dispatches an asynchronous <code>POST /api/analyzeArea</code> request to the cluster. The response populates the site metrics sidebar (Figure 2b) and returns terrain statistics alongside raw JSON response metadata (Figure 2c). Clicking the &ldquo;Interactive 3D Terrain&rdquo; button opens a modal 3D WebGL elevation mesh (Figure 3) rendered via Plotly.js, enabling full 360&deg; rotation, zoom, and spatial inspection of candidate depression bowls.</p>

<div class="figure-box">
  <div class="img-row-3">
    <div class="subfig" style="flex: 1.4;">
      <img src="figures/ui_drawing.png" alt="Drawing parcel boundary">
      <div style="margin-top: 4px;">(a) Drawing parcel boundary (722.05 ha)</div>
    </div>
    <div class="subfig" style="flex: 0.8;">
      <img src="figures/ui_metrics.png" alt="Candidate sites overview and Site 1 results">
      <div style="margin-top: 4px;">(b) Pond sites &amp; capacity sizing</div>
    </div>
    <div class="subfig" style="flex: 0.85;">
      <img src="figures/ui_stats_json.png" alt="Terrain statistics and API JSON response">
      <div style="margin-top: 4px;">(c) Terrain stats &amp; API response</div>
    </div>
  </div>
  <div class="figure-caption">Figure 2: End-to-end interactive workflow: (a) Drawing agricultural land parcel on map; (b) Ranked candidate pond sites and sizing recommendation; (c) Terrain summary statistics and structured JSON API payload served by <code>stu10_sys1</code>.</div>
</div>

<div class="figure-box">
  <img src="figures/ui_3d_terrain.png" style="max-width: 90%;" alt="3D WebGL Terrain Elevation Model">
  <div class="figure-caption">Figure 3: Interactive 3D WebGL Terrain Elevation Model rendered via Plotly.js, displaying topography relief, candidate pond pins (#1&ndash;#4), and 2D contour projections.</div>
</div>

<h3>5.3 Database and Storage</h3>
<p class="no-indent">Worker nodes operate statelessly. Terrain elevation models are held resident in process memory via Gunicorn copy-on-write memory. Query responses are cached using an in-memory LRU cache keyed by SHA-256 hashes of the normalized polygon coordinates, achieving 0.2 ms response times for repeated queries.</p>

<h2>6. CSD Themes and Topics Applied in the Project</h2>
<p class="no-indent">Table 3 connects our concrete system implementation to core Computer System Design (CSD) themes taught in the course.</p>

<div class="caption">Table 3: Mapping of core CSD themes/topics to their use in this project</div>
<table class="booktabs">
  <thead>
    <tr>
      <th style="width: 22%;">CSD Theme / Topic</th>
      <th style="width: 32%;">Where used in the project</th>
      <th style="width: 46%;">Justification / Engineering Design Rationale</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>API Design (REST)</td><td><code>POST /api/analyzeArea</code>, <code>/api/coverage</code></td><td>Standard JSON/GeoJSON contracts decouple the Leaflet client from Python/Go backend implementations.</td></tr>
    <tr><td>Load Balancing</td><td>Custom Go load balancer (<code>cluster/pond_lb.go</code>)</td><td>Least-inflight dispatch prevents fast queries from queuing behind expensive 3D mesh queries; smooths multi-core utilization.</td></tr>
    <tr><td>Caching</td><td>LRU result cache; Gunicorn <code>--preload</code> DEM memory</td><td>Recomputations of Stage A (0.5 s) are eliminated; repeated parcel queries return in 0.2 ms.</td></tr>
    <tr><td>Data Representation</td><td>Flat 2D/1D NumPy arrays with UTM projections</td><td>Direct array slicing <i>i &middot; W + j</i> avoids costly geographic coordinate lookups and object allocation overheads.</td></tr>
    <tr><td>Concurrency</td><td>Go goroutines in LB; Gunicorn multi-processing</td><td>Bypasses Python GIL by running 119 OS processes per node; Go goroutines handle 10,000+ client TCP connections.</td></tr>
    <tr><td>Microservices vs. Monolith</td><td>Hybrid: Stateless worker monoliths + micro LB</td><td>Avoids distributed microservice network overhead for tightly coupled matrix math, while allowing horizontal scaling.</td></tr>
    <tr><td>Design Patterns</td><td>Pipeline pattern (hydrology); Reverse Proxy</td><td>Hydrology steps (fill &rarr; D8 &rarr; PSI &rarr; catchment) form a pure functional pipeline; LB encapsulates proxy logic.</td></tr>
    <tr><td>Network Security</td><td>Internal IP binding (172.17.0.x)</td><td>Python worker ports are restricted to the internal lab subnet; only the Go LB port 5237 is exposed to users.</td></tr>
    <tr><td>Deployment Automation</td><td><code>cluster/deploy_cluster.py</code> via Paramiko</td><td>Enables one-command fleet deployment, dependency checks, and process health inspection across 4 cluster nodes.</td></tr>
    <tr><td>Fault Tolerance</td><td>Health checks (2 s) + passive backend ejection</td><td>Automatically routes requests away from failed nodes with body buffered for transparent retry.</td></tr>
    <tr><td>Algorithms &amp; Complexity</td><td>Barnes Priority-Flood <i>O(N log N)</i>; D8 sort <i>O(N)</i></td><td>Sub-second terrain analysis on large grids requires optimal heap-based sink filling rather than iterative relaxation.</td></tr>
    <tr><td>Testing Strategy</td><td><code>test_api.py</code> &amp; <code>cluster/run_stress.py</code></td><td>Integration tests verify GeoJSON schema compliance; Locust stress tests measure p95/p99 latency under concurrency.</td></tr>
    <tr><td>Version Control</td><td>Git with atomic commits on GitHub</td><td>Maintains clean branch history and multi-machine sync across lab systems and local developer machines.</td></tr>
  </tbody>
</table>

<h3>6.1 Deep-Dive on Significant Engineering Decisions</h3>
<p><strong>Decoupled Stage A/B Architecture:</strong> The most critical architectural decision was separating dataset-level terrain modeling from user-level area queries. A monolithic pipeline that processed contours on every request would take 0.9 s per click, making interactive map drawing unusable. Precomputing the DEM and PSI in Stage A reduced runtime query latency to under 35 ms.</p>
<p><strong>Custom Go Load Balancer vs. Off-the-Shelf Proxies:</strong> Rather than deploying a generic Nginx instance, we engineered a dedicated Go load balancer (<code>pond_lb.go</code>). This enabled custom application-aware admission control: limiting in-flight concurrency per node strictly to its worker capacity (119 requests), buffering request bodies in memory to retry on alternative backends upon HTTP 5xx errors, and providing explicit HTTP 503 shedding with <code>Retry-After</code> headers under flash crowds.</p>

<h2>7. Results and Evaluation</h2>
<p class="no-indent">The system was validated on <code>contours_1m.kml</code> covering an agricultural tract in Chhattisgarh (21.245&deg; N, 81.295&deg; E). Figure 4 displays the interpolated DEM and the derived D8 flow accumulation network.</p>

<div class="figure-box">
  <div class="img-row">
    <img src="figures/dem_heatmap.png" alt="DEM Heatmap with Sites">
    <img src="figures/flow_accumulation.png" alt="Flow Accumulation">
  </div>
  <div class="figure-caption">Figure 4: Interpolated DEM with candidate pond locations (left) and D8 flow accumulation network (right).</div>
</div>

<p class="no-indent">Table 4 details empirical results for various test parcels. The top site remained mathematically identical to the whole-map ground truth, confirming the consistency of our parcel masking algorithm.</p>

<div class="caption">Table 4: Area query performance across parcel selections (P = 850 mm, C = 0.35)</div>
<table class="booktabs">
  <thead>
    <tr>
      <th>Selected Parcel</th>
      <th>Area (ha)</th>
      <th>Sites</th>
      <th>Catchment (ha)</th>
      <th>Top Q (m&sup3;/yr)</th>
      <th>Total Q (m&sup3;/yr)</th>
      <th>Latency</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>West Sector (Rect)</td><td>418.3</td><td>3</td><td>0.98</td><td>2,903</td><td>9,022</td><td>21 ms</td></tr>
    <tr><td>East Sector (Rect)</td><td>418.3</td><td>4</td><td>1.32</td><td>3,922</td><td>17,651</td><td>35 ms</td></tr>
    <tr><td>Central Block</td><td>103.4</td><td>2</td><td>0.98</td><td>2,903</td><td>7,374</td><td>15 ms</td></tr>
    <tr><td>Triangular Field</td><td>189.5</td><td>2</td><td>0.98</td><td>2,903</td><td>7,374</td><td>15 ms</td></tr>
    <tr><td>Small Holding</td><td>10.3</td><td>1</td><td>0.98</td><td>2,903</td><td>2,903</td><td>7 ms</td></tr>
    <tr><td>Whole Extent</td><td>836.6</td><td>4</td><td>0.98</td><td>2,903</td><td>15,611</td><td>29 ms</td></tr>
  </tbody>
</table>

<h3>7.1 Performance and Cluster Load Testing</h3>
<p class="no-indent">Load testing was conducted using Locust across concurrency levels from 10 to 200 users. Table 5 and Figure 5 illustrate the scaling benefits of our 3-node cluster deployment (360 active CPU cores) compared to a single-node server.</p>

<div class="caption">Table 5: Empirical stress test results (Single node vs. 3-node cluster via pond_lb)</div>
<table class="booktabs">
  <thead>
    <tr>
      <th rowspan="2">Users</th>
      <th colspan="3" style="text-align: center; border-bottom: 1px solid #000;">Single Worker Node (Direct)</th>
      <th colspan="3" style="text-align: center; border-bottom: 1px solid #000;">3-Node Cluster via Load Balancer</th>
    </tr>
    <tr>
      <th>Req/s</th>
      <th>p95 (ms)</th>
      <th>Error %</th>
      <th>Req/s</th>
      <th>p95 (ms)</th>
      <th>Error %</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>10</td><td>8.2</td><td>34 ms</td><td>0%</td><td>8.4</td><td>32 ms</td><td>0%</td></tr>
    <tr><td>50</td><td>40.4</td><td>60 ms</td><td>0%</td><td>41.1</td><td>37 ms</td><td>0%</td></tr>
    <tr><td>100</td><td>78.3</td><td>280 ms</td><td>0%</td><td>96.5</td><td>95 ms</td><td>0%</td></tr>
    <tr><td>200</td><td>101.1</td><td>550 ms</td><td>2.1%</td><td>138.7</td><td>120 ms</td><td>0%</td></tr>
  </tbody>
</table>

<div class="figure-box">
  <img src="figures/stress_plot.png" alt="Stress Test Plot">
  <div class="figure-caption">Figure 5: Throughput, p95 latency, and error rates under increasing concurrent load. The cluster maintains sub-120 ms latency at 200 users.</div>
</div>

<h2>8. Discussion and Limitations</h2>
<ol>
  <li><strong>Hydrological Simplifications:</strong> The Rational Method assumes a uniform annual runoff coefficient (<i>C</i>) and lumped precipitation. It does not account for temporal storm intensity variations, transient soil infiltration curves (e.g., SCS Curve Number), or evaporation losses.</li>
  <li><strong>DEM Spatial Resolution:</strong> The 16.2 m interpolated grid resolution is sufficient for macro-catchment routing, but parcels under 0.5 ha cannot be reliably resolved.</li>
  <li><strong>Independent Process Caches:</strong> When a user uploads a new custom KML file, each worker node independently recomputes Stage A on its first encounter with that file. A distributed cache (e.g., Redis) or shared filesystem volume would optimize custom uploads across nodes.</li>
  <li><strong>Single Point of Failure at Ingress:</strong> While worker nodes are fully redundant, the Go Load Balancer runs on Sys1. In an enterprise environment, a secondary passive LB configured with VRRP/Keepalived would ensure high availability.</li>
</ol>

<h2>9. AI Tool Usage Declaration</h2>
<p class="no-indent">In accordance with the course LLM Usage Policy, the author declares that Google Antigravity (Gemini), an AI coding assistant, was utilized during this project. Specific tasks assisted include:</p>
<ol>
  <li>Scaffolding boilerplate goroutine and reverse-proxy handlers for <code>cluster/pond_lb.go</code>.</li>
  <li>Assisting in Paramiko-based SSH deployment orchestration scripts (<code>cluster/deploy_cluster.py</code>).</li>
  <li>Debugging spatial matrix bounds alignment in NumPy hydrology calculations.</li>
  <li>Reformatting project documentation and technical sections into the official ACM <code>acmart</code> manuscript LaTeX template.</li>
</ol>
<p>All AI-assisted code, algorithms, and technical texts were rigorously reviewed, verified against ground truth calculations, tested on the physical cluster, and adapted by the author. No confidential institutional credentials were shared with AI services.</p>

<hr class="sep">

<h2>Appendix: Source Code and Repository</h2>
<p class="no-indent"><strong>GitHub Repository:</strong> <a href="https://github.com/chaitanyakumarAI/Pond_catchment_analysis">https://github.com/chaitanyakumarAI/Pond_catchment_analysis</a><br>
<strong>Live Deployment:</strong> <a href="http://10.1.75.51:5237/">http://10.1.75.51:5237/</a></p>

<h3>Repository Structure</h3>
<ul>
  <li><code>app.py</code>: Main Flask application handling REST endpoints, input validation, and GeoJSON formatting.</li>
  <li><code>modules/</code>: Core computational modules (<code>hydrology.py</code> for DEM/flow/catchment analysis, <code>kml_parser.py</code> for contour extraction).</li>
  <li><code>cluster/</code>: Cluster orchestration tools (<code>pond_lb.go</code> load balancer, <code>deploy_cluster.py</code> multi-node deployment, <code>start_worker.sh</code> worker launcher, <code>run_stress.py</code> Locust load testing).</li>
  <li><code>static/</code>: Frontend Leaflet GIS client, drawing tools, and CSS styling.</li>
  <li><code>test_api.py</code>: Automated test suite verifying health checks, bounds, and GeoJSON validity.</li>
  <li><code>report/</code>: Technical report source files (<code>Final_Report.tex</code>) and figure assets.</li>
</ul>

<h3>Cluster Deployment Commands</h3>
<pre>
# 1. Compile Go load balancer on Sys1:
cd ~/pond/cluster &amp;&amp; go build -o pond_lb pond_lb.go &amp;&amp; chmod +x pond_lb &amp;&amp; cd ..

# 2. Deploy and launch workers across cluster:
export POND_SSH_PASS='&lt;cluster_password&gt;'
python3 cluster/deploy_cluster.py

# 3. Verify node health:
python3 cluster/deploy_cluster.py --status

# 4. Run automated test suite:
python3 test_api.py http://10.1.75.51:5237
</pre>

</body>
</html>
"""

report_dir = os.path.abspath("E:/CSD/Pond_catchment/report")
html_file = os.path.join(report_dir, "Final_Report.html")
pdf_file = os.path.join(report_dir, "Final_Report.pdf")

with open(html_file, "w", encoding="utf-8") as f:
    f.write(html_template)
print("Written HTML to:", html_file)

edge_paths = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
]
edge_bin = next((p for p in edge_paths if os.path.exists(p)), None)

if edge_bin:
    cmd = [
        edge_bin,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_file}",
        f"file:///{html_file.replace(os.sep, '/')}"
    ]
    print("Running command:", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    print("Edge return code:", res.returncode)
    if os.path.exists(pdf_file):
        print("Successfully generated Final_Report.pdf! Size:", os.path.getsize(pdf_file), "bytes")
    else:
        print("Failed to generate PDF. Stderr:", res.stderr)
else:
    print("Edge binary not found.")
