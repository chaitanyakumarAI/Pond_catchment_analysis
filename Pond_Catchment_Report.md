# Pond Catchment Analysis & Terrain Engine Report

**Course:** Computer System Design (CSD)  
**Assignment:** Automated Pond Catchment Analysis API & Web Interface  
**Student Name:** Ranga Chandra Naga Venkata Chaitanya Kumar  
**Roll Number:** 12341740  
**GitHub Repository Link:** https://github.com/chaitanyakumar-CSD/Pond_catchment_analysis  
**Working API Route URL:** `http://localhost:5050/analyzeContour` (and `http://localhost:5050/findCatchment`)  
**Interactive Dashboard Web URL:** `http://localhost:5050/`  

---

## 1. Executive Summary & Problem Overview

This project implements an automated, generalized backend API and web application that accepts contour elevation maps in **KML** or **KMZ** format, performs 2D/3D terrain analysis (Digital Elevation Model grid generation, slope computation, D8 flow direction, flow accumulation), identifies the optimal location for farm pond construction, and delineates the corresponding upstream catchment area (watershed).

The implementation strictly avoids hardcoding coordinates, elevation ranges, or map-specific values. It dynamically parses XML geometries and elevation metadata, making it fully extensible to generalized contour maps across any geographical location.

---

## 2. Catchment Estimation & Terrain Analysis Approach

The terrain analysis engine executes the following scientific pipeline:

```
+-------------------+      +--------------------+      +--------------------+
|  KML / KMZ Upload | ---> | Dynamic XML Parser | ---> | DEM Grid Gen (scipy)|
+-------------------+      +--------------------+      +--------------------+
                                                                 |
                                                                 v
+-------------------+      +--------------------+      +--------------------+
| Catchment Polygon | <--- | Upstream Tracing   | <--- | D8 Flow Dir & Acc  |
| & Runoff Volume   |      | & PSI Pond Sizing  |      | Matrix Calculation |
+-------------------+      +--------------------+      +--------------------+
```

### Key Technical Steps:
1. **Dynamic KML/KMZ Parsing (`kml_parser.py`)**:
   - Unzips `.kmz` archives automatically if provided.
   - Extracts coordinates `(longitude, latitude, elevation)` from Placemark `<LineString>`, `<Polygon>`, `<ExtendedData>`, and `<name>` tags.
   - Converts lat/lon bounding box into physical ground distances in meters using the Haversine formula.

2. **Digital Elevation Model (DEM) Interpolation (`terrain_analyzer.py`)**:
   - Constructs a regular $150 \times 122$ grid across the bounding box.
   - Uses `scipy.interpolate.griddata(method='linear')` with nearest-neighbor border fallback.
   - Applies Gaussian smoothing ($\sigma = 1.0$) to eliminate micro-interpolation noise.

3. **Slope & D8 Flow Direction Algorithm**:
   - Calculates terrain gradient $\nabla Z = (\frac{\partial Z}{\partial x}, \frac{\partial Z}{\partial y})$ and slope angle in degrees.
   - Computes D8 flow direction vector for each cell pointing along the steepest downward gradient to one of 8 neighbors.

4. **Flow Accumulation & Pond Suitability Index (PSI)**:
   - Sorts cells by elevation descending and calculates cumulative upstream contributing cells.
   - Evaluates a multi-factor Pond Suitability Index:
     $$\text{PSI} = 0.50 \times \text{NormFA} + 0.35 \times (1 - \text{NormZ}) + 0.15 \times (1 - \text{NormSlope})$$
   - Selects the optimal cell $(i_{\text{pond}}, j_{\text{pond}})$ maximizing PSI.

5. **Upstream Catchment Delineation**:
   - Traces all upstream cells flowing into the pond site via reverse D8 adjacency graph.
   - Computes catchment area in square meters ($m^2$), hectares (ha), and acres.
   - Generates a Convex Hull boundary polygon for GeoJSON export.

6. **Hydrological Water Harvesting & Storage Estimates**:
   - Estimates annual surface runoff using the Rational Method:
     $$Q = C \times P \times A$$
     where $C = 0.35$ (runoff coefficient), $P = 850\text{ mm}$ (annual rainfall), $A = \text{Catchment Area}$.
   - Calculates recommended pond dimensions ($48.1\text{m} \times 48.1\text{m} \times 3.5\text{m}$) and storage capacity ($8,110.18\text{ m}^3$).

---

## 3. API Documentation & Specifications

### Endpoint 1: `POST /analyzeContour` (and `POST /findCatchment`)
- **Description:** Uploads a `.kml` or `.kmz` contour map and performs terrain analysis & catchment estimation.
- **Content-Type:** `multipart/form-data`
- **Body Parameter:** `file` or `contour_file` (File stream)

#### Sample cURL Request:
```bash
curl -X POST http://localhost:5050/analyzeContour \
  -F "file=@contours_1m.kml"
```

#### Structured JSON Response Schema:
```json
{
  "success": true,
  "message": "Contour terrain analysis and catchment estimation completed successfully.",
  "data": {
    "pond_location": {
      "latitude": 21.250033,
      "longitude": 81.290211,
      "elevation_m": 268.01,
      "suitability_score_pct": 68.6,
      "terrain_slope_deg": 0.94
    },
    "catchment_summary": {
      "area_m2": 151450.61,
      "area_hectares": 15.15,
      "area_acres": 37.42,
      "contributing_cells": 324,
      "catchment_percentage_of_map": 1.77
    },
    "water_harvesting_estimates": {
      "assumed_annual_rainfall_mm": 850,
      "estimated_annual_runoff_m3": 45056.56,
      "estimated_annual_runoff_liters": 45056556.0,
      "recommended_pond_capacity_m3": 8110.18,
      "recommended_pond_depth_m": 3.5,
      "recommended_dimensions_m": "48.1m x 48.1m"
    },
    "terrain_statistics": {
      "min_elevation_m": 34.15,
      "max_elevation_m": 296.32,
      "avg_slope_deg": 2.44,
      "map_width_meters": 3238.0,
      "map_height_meters": 2641.8
    },
    "geojson_layers": {
      "pond_point": {
        "type": "Feature",
        "geometry": { "type": "Point", "coordinates": [81.290211, 21.250033] }
      },
      "catchment_boundary": {
        "type": "Feature",
        "geometry": { "type": "Polygon", "coordinates": [...] }
      }
    }
  }
}
```

### Endpoint 2: `GET /health`
- **Description:** Health check endpoint returning HTTP 200 OK.

---

## 4. Experimental Demonstration on Sample Map (`contours_1m.kml`)

| Parameter / Metric | Derived Value | Hydrological Significance |
|---|---|---|
| **Parsed Contour Count** | 2,711 lines (160,473 coordinates) | High-density 1.0m elevation contours |
| **Elevation Range** | 267.0m — 298.0m ($\Delta 31.0\text{m}$) | Natural rolling valley topography |
| **Optimal Pond Location** | **21.250033 N, 81.290211 E** | Centroid of natural low micro-basin |
| **Pond Site Elevation & Slope** | **268.01 m (Slope: 0.94°)** | Flat valley depression ideal for excavation |
| **Delineated Catchment Area** | **15.15 Hectares (151,450.6 m²)** | Upstream drainage watershed area |
| **Est. Annual Water Runoff** | **45,056.56 m³ (45.05 Million Liters)** | Abundant runoff for pond filling |
| **Recommended Storage Sizing** | **8,110.18 m³ ($48.1\text{m} \times 48.1\text{m} \times 3.5\text{m}$)** | Recommended farm pond dimensions |

---

## 5. Verification & Test Execution

Automated test script (`test_api.py`) executed 3 test suites:
1. `test_health()`: Verified HTTP 200 OK.
2. `test_sample_route()`: Verified `/api/sample` execution on `contours_1m.kml`.
3. `test_upload_route()`: Verified multipart file upload on `POST /analyzeContour`.

**Result:** All 3 test suites passed 100% successfully.
