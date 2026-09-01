import os
import json
import traceback
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

from kml_parser import parse_kml_or_kmz
from terrain_analyzer import analyze_terrain_and_catchment, generate_plots

_last_result = None   # cache last analysis for /api/plots

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

SAMPLE_KML_PATH = os.path.join(os.path.dirname(__file__), 'contours_1m.kml')

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'Pond Catchment Analysis API',
        'version': '1.0.0'
    }), 200

def process_file_upload(file_obj):
    """Processes uploaded KML/KMZ file stream and returns analysis results."""
    filename = getattr(file_obj, 'filename', 'uploaded_map.kml')
    if not filename:
        filename = 'uploaded_map.kml'

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ['.kml', '.kmz']:
        raise ValueError("Unsupported file format. Please upload a .kml or .kmz file.")

    # Parse KML / KMZ
    parsed_data = parse_kml_or_kmz(file_obj)

    global _last_result
    results = analyze_terrain_and_catchment(parsed_data)
    results['input_file_info'] = {
        'filename': filename,
        'format': ext[1:].upper(),
        'contour_count': parsed_data['elevation_stats']['contour_count'],
        'total_parsed_points': parsed_data['elevation_stats']['total_points']
    }
    _last_result = results   # cache (includes numpy arrays for /api/plots)
    # Return a clean copy without numpy arrays
    return {k: v for k, v in results.items() if not k.startswith('_')}

@app.route('/analyzeContour', methods=['POST'])
@app.route('/findCatchment', methods=['POST'])
def analyze_contour_route():
    """
    Primary API Endpoint for Pond Catchment Analysis.
    Accepts KML or KMZ file upload.
    Returns structured JSON with Pond Location, Catchment Area, Runoff Estimates, and GeoJSON layers.
    """
    try:
        if 'file' not in request.files and 'contour_file' not in request.files:
            return jsonify({
                'error': 'No file uploaded. Please send a KML or KMZ file in form-data field "file" or "contour_file".'
            }), 400

        file_obj = request.files.get('file') or request.files.get('contour_file')
        if not file_obj or file_obj.filename == '':
            return jsonify({'error': 'Selected file is empty or missing filename.'}), 400

        results = process_file_upload(file_obj)
        return jsonify({
            'success': True,
            'message': 'Contour terrain analysis and catchment estimation completed successfully.',
            'data': results
        }), 200

    except Exception as e:
        app.logger.error(f"Error in analyze_contour_route: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': str(e),
            'details': traceback.format_exc()
        }), 500

@app.route('/api/sample', methods=['GET', 'POST'])
def analyze_sample_route():
    """
    Demonstration API route running analysis on the included sample contour map (contours_1m.kml).
    """
    try:
        if not os.path.exists(SAMPLE_KML_PATH):
            return jsonify({'error': 'Sample KML file contours_1m.kml not found on server.'}), 404

        global _last_result
        parsed_data = parse_kml_or_kmz(SAMPLE_KML_PATH)
        results = analyze_terrain_and_catchment(parsed_data)
        results['input_file_info'] = {
            'filename': 'contours_1m.kml',
            'format': 'KML',
            'contour_count': parsed_data['elevation_stats']['contour_count'],
            'total_parsed_points': parsed_data['elevation_stats']['total_points']
        }
        _last_result = results
        clean = {k: v for k, v in results.items() if not k.startswith('_')}
        return jsonify({
            'success': True,
            'message': 'Sample contour map (contours_1m.kml) analyzed successfully.',
            'data': clean
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/plots', methods=['GET'])
def get_plots():
    """Generate and return base64 terrain analysis plots from cached last analysis."""
    global _last_result
    try:
        if _last_result is None:
            # Auto-run sample if not yet analyzed
            parsed_data = parse_kml_or_kmz(SAMPLE_KML_PATH)
            _last_result = analyze_terrain_and_catchment(parsed_data)

        r = _last_result
        from pyproj import Transformer
        epsg = r['terrain_statistics']['utm_projection']
        t2w  = Transformer.from_crs(epsg, 'EPSG:4326', always_xy=True)

        plots = generate_plots(
            dem_raw    = r['_dem_raw'],
            dem_filled = r['_dem_filled'],
            slope      = r['_slope'],
            flow_acc   = r['_flow_acc'],
            twi        = r['_twi'],
            grid_x     = r['_gx_wgs'],
            grid_y     = r['_gy_wgs'],
            candidates = r['all_candidate_sites'],
            to_wgs84   = t2w
        )
        return jsonify({'success': True, 'plots': plots}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e),
                        'details': traceback.format_exc()}), 500

@app.route('/api/terrain_3d_mesh', methods=['GET'])
def get_terrain_3d_mesh():
    """Return 3D grid data for interactive WebGL rendering using Plotly.js."""
    global _last_result
    try:
        if _last_result is None:
            parsed_data = parse_kml_or_kmz(SAMPLE_KML_PATH)
            _last_result = analyze_terrain_and_catchment(parsed_data)

        r = _last_result
        dem_raw = r['_dem_raw']
        gx = r['_gx_wgs']
        gy = r['_gy_wgs']

        nr, nc = dem_raw.shape
        step = max(1, min(nr, nc) // 80)

        x_vals = gx[::step].tolist()
        y_vals = gy[::step].tolist()
        z_vals = dem_raw[::step, ::step].tolist()

        cands = []
        for c in r['all_candidate_sites']:
            cands.append({
                'rank': c['rank'],
                'longitude': c['pond_location']['longitude'],
                'latitude': c['pond_location']['latitude'],
                'elevation_m': c['pond_location']['elevation_m'],
                'color': c['color'],
                'area_ha': c['catchment_summary']['area_hectares'],
                'label': f"Site #{c['rank']} ({c['catchment_summary']['area_hectares']} ha)"
            })

        return jsonify({
            'success': True,
            'x': x_vals,
            'y': y_vals,
            'z': z_vals,
            'candidates': cands,
            'min_elev': 260.0,
            'max_elev': 300.0,
            'z_range': [250.0, 300.0]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/')
def index():
    """Serves the interactive web dashboard."""
    return render_template('index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print(f"==================================================")
    print(f"  Pond Catchment Analysis API & Web Dashboard")
    print(f"  Listening on : http://localhost:{port}")
    print(f"  API Endpoint : POST http://localhost:{port}/analyzeContour")
    print(f"  Sample API   : GET  http://localhost:{port}/api/sample")
    print(f"==================================================")
    app.run(host='0.0.0.0', port=port, debug=True)
