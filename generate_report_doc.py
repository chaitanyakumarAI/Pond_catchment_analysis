import os
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

def create_report():
    doc = docx.Document()
    
    # Page Margins
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # Styles & Colors
    PRIMARY = RGBColor(16, 185, 129)     # Emerald Green #10B981
    SECONDARY = RGBColor(6, 182, 212)   # Cyan #06B6D4
    TEXT_DARK = RGBColor(30, 30, 30)     # Charcoal Dark
    
    def set_cell_background(cell, color_hex):
        shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
        cell._tc.get_or_add_tcPr().append(shading_elm)

    def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
        tcPr = cell._tc.get_or_add_tcPr()
        tcMar = OxmlElement('w:tcMar')
        for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
            node = OxmlElement(f'w:{m}')
            node.set(qn('w:w'), str(val))
            node.set(qn('w:type'), 'dxa')
            tcMar.append(node)
        tcPr.append(tcMar)

    def add_heading_1(text):
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(16)
        h.paragraph_format.space_after = Pt(6)
        h.paragraph_format.keep_with_next = True
        r = h.add_run(text)
        r.font.size = Pt(15)
        r.font.bold = True
        r.font.color.rgb = PRIMARY
        return h

    def add_heading_2(text):
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(4)
        h.paragraph_format.keep_with_next = True
        r = h.add_run(text)
        r.font.size = Pt(12.5)
        r.font.bold = True
        r.font.color.rgb = SECONDARY
        return h

    def add_body(text, bold_prefix=""):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.15
        if bold_prefix:
            rb = p.add_run(bold_prefix)
            rb.font.bold = True
            rb.font.color.rgb = TEXT_DARK
        r = p.add_run(text)
        r.font.color.rgb = TEXT_DARK
        return p

    def add_code_block(code_text):
        tbl = doc.add_table(rows=1, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = tbl.rows[0].cells[0]
        set_cell_background(cell, "F4F5F7")
        set_cell_margins(cell, top=100, bottom=100, left=150, right=150)
        p = cell.paragraphs[0]
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(code_text)
        r.font.name = "Consolas"
        r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor(40, 40, 40)
        doc.add_paragraph().paragraph_format.space_after = Pt(6)

    def add_screenshot_placeholder(title, description):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(f"📷 {title}")
        r.font.bold = True
        r.font.size = Pt(11)
        r.font.color.rgb = SECONDARY

        tbl = doc.add_table(rows=1, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = tbl.rows[0].cells[0]
        set_cell_background(cell, "FAFAFA")
        set_cell_margins(cell, top=200, bottom=200, left=200, right=200)
        cp = cell.paragraphs[0]
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cr = cp.add_run(f"[ INSERT SCREENSHOT HERE: {description} ]")
        cr.font.italic = True
        cr.font.bold = True
        cr.font.color.rgb = RGBColor(120, 120, 120)
        cr.font.size = Pt(10)
        doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # Title Banner
    p_course = doc.add_paragraph()
    p_course.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_course = p_course.add_run("COURSE: COMPUTER SYSTEM DESIGN (CSD)")
    r_course.font.size = Pt(12)
    r_course.font.bold = True
    r_course.font.color.rgb = SECONDARY

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_title = p_title.add_run("POND CATCHMENT ANALYSIS & TERRAIN ENGINE API REPORT")
    r_title.font.size = Pt(20)
    r_title.font.bold = True
    r_title.font.color.rgb = PRIMARY

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # 1. Student & Project Details
    add_heading_1("1. Student & Project Overview")
    add_body("Ranga Chandra Naga Venkata Chaitanya Kumar", "Student Name: ")
    add_body("12341740", "Roll Number: ")
    add_body("https://github.com/chaitanyakumarAI/Pond_catchment_analysis.git", "GitHub Repository Link: ")
    add_body("http://localhost:5050/analyzeContour (and /findCatchment)", "Working API Route URL: ")
    add_body("http://localhost:5050/", "Interactive Dashboard Web URL: ")

    # 2. Catchment Estimation Approach
    add_heading_1("2. Terrain Analysis & Catchment Estimation Approach")
    add_body("The core engine processes arbitrary elevation contour maps (.KML and .KMZ formats) through a multi-stage scientific pipeline without hardcoding geographical parameters:")

    add_body("Parses Placemark LineStrings, Polygons, and ExtendedData elements. Coordinates (longitude, latitude, elevation) are extracted dynamically and converted to physical meter extents using the Haversine formula.", "A. Generalized KML/KMZ Parsing: ")
    add_body("Constructs a 2D regular grid across the bounding box and interpolates elevations using scipy.interpolate.griddata (linear interpolation with nearest fallback). A 2D Gaussian filter (sigma=1.0) is applied to remove micro-interpolation artifacts.", "B. Digital Elevation Model (DEM) Generation: ")
    add_body("Computes terrain slope angle in degrees and assigns 8-direction (D8) flow vectors pointing along the steepest downward gradient for each cell.", "C. Slope & D8 Flow Direction Analysis: ")
    add_body("Traverses D8 flow paths in descending elevation order to calculate cumulative upstream cell counts for every grid cell, revealing natural drainage channels.", "D. Flow Accumulation Matrix: ")
    add_body("Evaluates a multi-factor Pond Suitability Index (PSI = 0.50 * NormFA + 0.35 * (1 - NormZ) + 0.15 * (1 - NormSlope)) to select the optimal pond location site.", "E. Optimal Pond Site Selection: ")
    add_body("Performs reverse flow-path tracing from the selected pond site to identify all contributing upstream cells, forming the watershed polygon and computing area (m², hectares, acres).", "F. Upstream Catchment Delineation: ")
    add_body("Estimates annual runoff volume Q = C * P * A (Rational Method) and calculates recommended pond dimensions and storage capacity.", "G. Hydrological Storage Sizing: ")

    # 3. API Documentation
    add_heading_1("3. API Documentation & Specifications")
    
    add_heading_2("Endpoint 1: POST /analyzeContour (and POST /findCatchment)")
    add_body("Accepts KML or KMZ contour map file upload and returns full catchment analysis in JSON format.")
    add_body("multipart/form-data with key 'file' or 'contour_file' containing .kml/.kmz file.", "Request Format: ")

    add_body("Sample JSON Response Output:")
    code_json_sample = """{
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
      "contributing_cells": 324
    },
    "water_harvesting_estimates": {
      "assumed_annual_rainfall_mm": 850,
      "estimated_annual_runoff_m3": 45056.56,
      "estimated_annual_runoff_liters": 45056556.0,
      "recommended_pond_capacity_m3": 8110.18,
      "recommended_pond_depth_m": 3.5,
      "recommended_dimensions_m": "48.1m x 48.1m"
    },
    "geojson_layers": {
      "pond_point": { "type": "Feature", "geometry": { "type": "Point", "coordinates": [81.290211, 21.250033] } },
      "catchment_boundary": { "type": "Feature", "geometry": { "type": "Polygon", "coordinates": [...] } }
    }
  }
}"""
    add_code_block(code_json_sample)

    add_heading_2("Endpoint 2: GET /health")
    add_body("Returns 200 OK health status for load balancers and system monitoring.")

    # 4. Demonstration on Sample Map
    add_heading_1("4. Demonstration & Results on Provided Sample Map (contours_1m.kml)")
    add_body("The API was executed and verified against the provided contours_1m.kml dataset. The quantitative findings are summarized below:")

    table_results = doc.add_table(rows=8, cols=3)
    table_results.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["Parameter / Metric", "Derived Value", "Hydrological Significance"]
    for i, h in enumerate(headers):
        cell = table_results.rows[0].cells[i]
        cell.text = h
        set_cell_background(cell, "10B981")
        p = cell.paragraphs[0]
        p.runs[0].font.bold = True
        p.runs[0].font.color.rgb = RGBColor(255, 255, 255)

    results_data = [
        ["Parsed Contour Count", "2,711 lines (160,473 pts)", "Dense 1.0m interval elevation contours"],
        ["Elevation Range", "267.0m — 298.0m (Δ 31.0m)", "Low rolling hills with natural drainage valley"],
        ["Optimal Pond Coordinates", "21.250033 N, 81.290211 E", "Centroid of natural micro-basin / sink"],
        ["Pond Elevation & Slope", "268.01 m (Slope: 0.94°)", "Flat depression ideal for excavation"],
        ["Catchment Area", "15.15 Hectares (151,450.6 m²)", "Upstream drainage area feeding the site"],
        ["Est. Annual Water Runoff", "45,056.56 m³ (45.05 Million L)", "Abundant surface runoff for pond filling"],
        ["Recommended Pond Capacity", "8,110.18 m³ (48.1m x 48.1m x 3.5m)", "Optimal farm pond storage sizing"],
    ]

    for row_idx, data in enumerate(results_data, start=1):
        row_cells = table_results.rows[row_idx].cells
        bg_color = "F4FBF7" if row_idx % 2 == 0 else "FFFFFF"
        for col_idx, text in enumerate(data):
            row_cells[col_idx].text = text
            set_cell_background(row_cells[col_idx], bg_color)
            p = row_cells[col_idx].paragraphs[0]

    # 5. Screenshots
    add_heading_1("5. Relevant Screenshots & Visual Demonstration")

    add_screenshot_placeholder(
        "Screenshot 1: Interactive Web Dashboard & Upload Interface",
        "Browser UI showing AquaTerrain AI dashboard, file upload drop-zone, and sample run button."
    )

    add_screenshot_placeholder(
        "Screenshot 2: Interactive Leaflet Map with Pond Location & Catchment Polygon",
        "Map showing optimal pond site marker (emerald circle) and catchment boundary polygon (cyan overlay) on contours_1m.kml."
    )

    add_screenshot_placeholder(
        "Screenshot 3: API JSON Response Output",
        "Postman or cURL terminal window showing POST /analyzeContour returning HTTP 200 OK with full JSON payload."
    )

    add_screenshot_placeholder(
        "Screenshot 4: Automated Test Suite Execution (test_api.py)",
        "Terminal output showing all automated test cases passing for /health, /api/sample, and /analyzeContour."
    )

    out_file = "Pond_Catchment_Analysis_Report.docx"
    doc.save(out_file)
    print(f"Report generated successfully as {out_file}")

if __name__ == "__main__":
    create_report()
