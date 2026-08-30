import os
import json
import traceback
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

from kml_parser import parse_kml_or_kmz
from terrain_analyzer import analyze_terrain_and_catchment

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

    # Perform Terrain & Catchment Analysis
    results = analyze_terrain_and_catchment(parsed_data)
    results['input_file_info'] = {
        'filename': filename,
        'format': ext[1:].upper(),
        'contour_count': parsed_data['elevation_stats']['contour_count'],
        'total_parsed_points': parsed_data['elevation_stats']['total_points']
    }
    return results

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

        parsed_data = parse_kml_or_kmz(SAMPLE_KML_PATH)
        results = analyze_terrain_and_catchment(parsed_data)
        results['input_file_info'] = {
            'filename': 'contours_1m.kml',
            'format': 'KML',
            'contour_count': parsed_data['elevation_stats']['contour_count'],
            'total_parsed_points': parsed_data['elevation_stats']['total_points']
        }
        return jsonify({
            'success': True,
            'message': 'Sample contour map (contours_1m.kml) analyzed successfully.',
            'data': results
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
