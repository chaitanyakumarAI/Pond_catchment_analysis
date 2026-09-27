"""
Pond Catchment Analysis — Phase 3 web service (API + front-end).

Endpoints
  GET  /                      interactive map front-end
  GET  /health                liveness / readiness (used by the load balancer)
  GET  /api/coverage          data-coverage footprint of the contour map (for the map)
  POST /api/analyzeArea       analyse a land area selected on the map  (Phase 3)
  POST /analyzeContour        Phase-1 route: analyse a whole uploaded KML/KMZ
  POST /findCatchment         alias of /analyzeContour
  GET  /api/sample            whole-map analysis of the bundled sample map
  GET|POST /api/plots         six terrain plots (base64 PNG) for the same request
  GET|POST /api/terrain_3d_mesh  3D DEM mesh for WebGL rendering
  GET  /metrics               per-worker counters (requests, cache hits, latency)

Design for scaling (see report §System design):
  * Stateless workers — every request carries the dataset (sample id or uploaded
    file) and the selected polygon, so ANY worker on ANY of the 4 systems can serve
    it and the load balancer needs no sticky sessions.
  * Stage-A terrain model is cached per dataset (sha1 of file bytes); Stage-B area
    queries on a cached model take only milliseconds.
  * Results are cached by sha1(dataset, polygon, parameters) in a bounded LRU.
"""
import os
import io
import json
import time
import socket
import hashlib
import threading
import traceback
from collections import OrderedDict

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

from kml_parser import parse_kml_or_kmz
from terrain_analyzer import (build_terrain_model, select_sites, generate_plots,
                              AreaSelectionError)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_UPLOAD_MB', 25)) * 1024 * 1024
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_KML_PATH = os.path.join(BASE_DIR, 'contours_1m.kml')
NODE_NAME = os.environ.get('NODE_NAME', socket.gethostname())

MODEL_CACHE_SIZE = int(os.environ.get('MODEL_CACHE_SIZE', 4))      # terrain models (~5 MB each)
RESULT_CACHE_SIZE = int(os.environ.get('RESULT_CACHE_SIZE', 256))  # JSON results (~30 KB each)
PARAM_LIMITS = {'rainfall_mm': (100.0, 5000.0), 'runoff_coeff': (0.05, 0.95), 'pond_depth_m': (1.0, 10.0)}


class LRU:
    """Small thread-safe LRU cache."""
    def __init__(self, size):
        self.size, self.d, self.lock = size, OrderedDict(), threading.Lock()
        self.hits = self.misses = 0

    def get(self, k):
        with self.lock:
            if k in self.d:
                self.d.move_to_end(k); self.hits += 1
                return self.d[k]
            self.misses += 1
            return None

    def put(self, k, v):
        with self.lock:
            self.d[k] = v; self.d.move_to_end(k)
            while len(self.d) > self.size:
                self.d.popitem(last=False)


MODELS = LRU(MODEL_CACHE_SIZE)
RESULTS = LRU(RESULT_CACHE_SIZE)
_model_locks = {}
_model_locks_guard = threading.Lock()
STATS = {'requests': 0, 'errors': 0, 'analyses': 0, 'total_ms': 0.0, 'started': time.time()}
_stats_lock = threading.Lock()


def _count(key, inc=1):
    with _stats_lock:
        STATS[key] += inc


def get_model(dataset_id, loader):
    """Return (model, parsed_meta) for a dataset, building it at most once per process."""
    m = MODELS.get(dataset_id)
    if m is not None:
        return m
    with _model_locks_guard:
        lock = _model_locks.setdefault(dataset_id, threading.Lock())
    with lock:                                   # avoid duplicate builds under concurrency
        m = MODELS.get(dataset_id)
        if m is None:
            parsed = loader()
            model = build_terrain_model(parsed)
            m = (model, {'contour_count': parsed['elevation_stats']['contour_count'],
                         'total_parsed_points': parsed['elevation_stats']['total_points'],
                         'bbox': parsed['bbox']})
            MODELS.put(dataset_id, m)
    return m


def sample_model():
    return get_model('sample', lambda: parse_kml_or_kmz(SAMPLE_KML_PATH))


def uploaded_model(file_storage):
    filename = file_storage.filename or 'uploaded_map.kml'
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.kml', '.kmz'):
        raise ValueError("Unsupported file format. Please upload a .kml or .kmz file.")
    data = file_storage.read()
    if not data:
        raise ValueError("Uploaded file is empty.")
    ds_id = 'up:' + hashlib.sha1(data).hexdigest()
    model, meta = get_model(ds_id, lambda: parse_kml_or_kmz(io.BytesIO(data)))
    return ds_id, model, meta, filename, ext[1:].upper()


def _clean(result):
    return {k: v for k, v in result.items() if not k.startswith('_')}


def _read_request():
    """Parse a request that may be JSON or multipart (file + fields)."""
    if request.files:
        form = request.form
        poly = form.get('polygon')
        body = {'polygon': json.loads(poly) if poly else None}
        for k in PARAM_LIMITS:
            if form.get(k) not in (None, ''):
                body[k] = form.get(k)
        f = request.files.get('file') or request.files.get('contour_map')
        return body, f
    body = request.get_json(silent=True) or {}
    return body, None


def _params(body):
    out = {}
    defaults = {'rainfall_mm': 850.0, 'runoff_coeff': 0.35, 'pond_depth_m': 3.5}
    for k, (lo, hi) in PARAM_LIMITS.items():
        try:
            v = float(body.get(k, defaults[k]))
        except (TypeError, ValueError):
            raise AreaSelectionError(f"'{k}' must be a number.")
        if not lo <= v <= hi:
            raise AreaSelectionError(f"'{k}' must be between {lo} and {hi}.")
        out[k] = v
    return out


def _polygon(body):
    poly = body.get('polygon')
    if poly is None:
        return None
    # accept GeoJSON geometry / feature too
    if isinstance(poly, dict):
        geom = poly.get('geometry', poly)
        if geom.get('type') != 'Polygon':
            raise AreaSelectionError("Only Polygon geometries are supported.")
        poly = geom['coordinates'][0]
    if not isinstance(poly, list):
        raise AreaSelectionError("polygon must be a list of [lon, lat] pairs.")
    return [[round(float(p[0]), 7), round(float(p[1]), 7)] for p in poly]


def run_analysis(body, file_storage, want_arrays=False):
    """Shared analysis path for /api/analyzeArea, /api/plots and /api/terrain_3d_mesh."""
    if file_storage is not None and file_storage.filename:
        ds_id, model, meta, fname, fmt = uploaded_model(file_storage)
    else:
        ds_id = 'sample'
        model, meta = sample_model()
        fname, fmt = 'contours_1m.kml', 'KML'
    polygon = _polygon(body)
    params = _params(body)
    key = hashlib.sha1(json.dumps([ds_id, polygon, params], sort_keys=True).encode()).hexdigest()

    if not want_arrays:
        cached = RESULTS.get(key)
        if cached is not None:
            return cached, True, model
    res = select_sites(model, area_polygon=polygon, **params)
    res['input_file_info'] = {'filename': fname, 'format': fmt,
                              'contour_count': meta['contour_count'],
                              'total_parsed_points': meta['total_parsed_points']}
    res['request_key'] = key
    clean = _clean(res)
    RESULTS.put(key, clean)
    _count('analyses')
    return (res if want_arrays else clean), False, model


def ok(data, message, cache_hit=False, t0=None):
    resp = jsonify({'success': True, 'message': message, 'served_by': NODE_NAME,
                    'cache_hit': cache_hit,
                    'server_time_ms': round((time.perf_counter() - t0) * 1000, 1) if t0 else None,
                    'data': data})
    resp.headers['X-Served-By'] = NODE_NAME
    return resp, 200


def fail(e, status):
    _count('errors')
    body = {'success': False, 'error': str(e), 'served_by': NODE_NAME}
    if isinstance(e, AreaSelectionError):
        body.update(e.extra)
    elif status >= 500:
        app.logger.error(traceback.format_exc())
    return jsonify(body), status


@app.before_request
def _before():
    _count('requests')


@app.after_request
def _after(resp):
    resp.headers.setdefault('X-Served-By', NODE_NAME)
    return resp


@app.errorhandler(413)
def too_large(_e):
    return jsonify({'success': False, 'error': f"File too large (limit {app.config['MAX_CONTENT_LENGTH']//1048576} MB)."}), 413


# ── routes ───────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'service': 'Pond Catchment Analysis API',
                    'version': '3.0.0', 'node': NODE_NAME, 'pid': os.getpid(),
                    'sample_model_cached': MODELS.get('sample') is not None}), 200


@app.route('/metrics', methods=['GET'])
def metrics():
    with _stats_lock:
        s = dict(STATS)
    s['uptime_s'] = round(time.time() - s.pop('started'), 1)
    s['avg_analysis_ms'] = round(s['total_ms'] / s['analyses'], 1) if s['analyses'] else 0
    s.update({'node': NODE_NAME, 'pid': os.getpid(),
              'result_cache': {'entries': len(RESULTS.d), 'hits': RESULTS.hits, 'misses': RESULTS.misses},
              'model_cache': {'entries': len(MODELS.d), 'hits': MODELS.hits, 'misses': MODELS.misses}})
    return jsonify(s), 200


@app.route('/api/coverage', methods=['GET'])
def coverage():
    """Footprint of the sample contour data so the user knows where to draw."""
    try:
        model, meta = sample_model()
        return jsonify({'success': True, 'dataset': 'contours_1m.kml',
                        'coverage_polygon': model['hull_wgs'], 'bbox': meta['bbox'],
                        'elevation_range_m': [round(model['mz'], 1), round(model['Mz'], 1)],
                        'cell_size_m': round((model['cx'] + model['cy']) / 2, 1),
                        'limits': {'min_area_ha': 0.5, 'max_area_km2': 50, 'min_coverage_pct': 60,
                                   'max_upload_mb': app.config['MAX_CONTENT_LENGTH'] // 1048576}}), 200
    except Exception as e:
        return fail(e, 500)


@app.route('/api/analyzeArea', methods=['POST'])
def analyze_area():
    """
    Phase-3 route. Body (JSON):
      {"polygon": [[lon,lat],...], "rainfall_mm": 850, "runoff_coeff": 0.35, "pond_depth_m": 3.5}
    or multipart/form-data with 'file' (KML/KMZ) + 'polygon' (JSON string) + params.
    Omitting polygon analyses the whole map.
    """
    t0 = time.perf_counter()
    try:
        body, f = _read_request()
        data, hit, _ = run_analysis(body, f)
        dt = (time.perf_counter() - t0) * 1000
        _count('total_ms', dt)
        return ok(data, 'Selected land area analysed successfully.', hit, t0)
    except AreaSelectionError as e:
        return fail(e, 422)
    except ValueError as e:
        return fail(e, 400)
    except Exception as e:
        return fail(e, 500)


def process_file_upload(file_obj):
    """Phase-1 behaviour: whole-map analysis of an uploaded file."""
    ds_id, model, meta, fname, fmt = uploaded_model(file_obj)
    res = select_sites(model)
    res['input_file_info'] = {'filename': fname, 'format': fmt,
                              'contour_count': meta['contour_count'],
                              'total_parsed_points': meta['total_parsed_points']}
    return _clean(res)


@app.route('/analyzeContour', methods=['POST'])
@app.route('/findCatchment', methods=['POST'])
def analyze_contour_route():
    t0 = time.perf_counter()
    try:
        file_obj = request.files.get('file') or request.files.get('contour_map')
        if not file_obj or not file_obj.filename:
            return jsonify({'success': False, 'error': 'No file uploaded. Send a KML or KMZ file in form-data field "file" or "contour_map".'}), 400
        return ok(process_file_upload(file_obj),
                  'Contour terrain analysis and catchment estimation completed successfully.', False, t0)
    except ValueError as e:
        return fail(e, 400)
    except Exception as e:
        return fail(e, 500)


@app.route('/api/sample', methods=['GET', 'POST'])
def analyze_sample_route():
    t0 = time.perf_counter()
    try:
        data, hit, _ = run_analysis({}, None)
        return ok(data, 'Sample contour map (contours_1m.kml) analyzed successfully.', hit, t0)
    except Exception as e:
        return fail(e, 500)


@app.route('/api/plots', methods=['GET', 'POST'])
def get_plots():
    """Terrain plots for the same (dataset, polygon) request — stateless."""
    try:
        body, f = _read_request() if request.method == 'POST' else ({}, None)
        r, _, model = run_analysis(body, f, want_arrays=True)
        plots = generate_plots(dem_raw=r['_dem_raw'], dem_filled=r['_dem_filled'], slope=r['_slope'],
                               flow_acc=r['_flow_acc'], twi=r['_twi'], grid_x=r['_gx_wgs'],
                               grid_y=r['_gy_wgs'], candidates=r['all_candidate_sites'],
                               to_wgs84=model['t2w'])
        return jsonify({'success': True, 'served_by': NODE_NAME, 'plots': plots}), 200
    except AreaSelectionError as e:
        return fail(e, 422)
    except Exception as e:
        return fail(e, 500)


@app.route('/api/terrain_3d_mesh', methods=['GET', 'POST'])
def get_terrain_3d_mesh():
    try:
        body, f = _read_request() if request.method == 'POST' else ({}, None)
        r, _, model = run_analysis(body, f, want_arrays=True)
        dem_raw, gx, gy = r['_dem_raw'], r['_gx_wgs'], r['_gy_wgs']
        nr, nc = dem_raw.shape
        step = max(1, min(nr, nc) // 80)
        cands = [{'rank': c['rank'], 'longitude': c['pond_location']['longitude'],
                  'latitude': c['pond_location']['latitude'], 'elevation_m': c['pond_location']['elevation_m'],
                  'color': c['color'], 'area_ha': c['catchment_summary']['area_hectares'],
                  'label': f"Site #{c['rank']} ({c['catchment_summary']['area_hectares']} ha)"}
                 for c in r['all_candidate_sites']]
        zmin, zmax = float(dem_raw.min()), float(dem_raw.max())
        return jsonify({'success': True, 'served_by': NODE_NAME,
                        'x': gx[::step].tolist(), 'y': gy[::step].tolist(),
                        'z': dem_raw[::step, ::step].round(2).tolist(), 'candidates': cands,
                        'selected_area': (r.get('selected_area') or {}).get('polygon'),
                        'min_elev': round(zmin, 1), 'max_elev': round(zmax, 1),
                        'z_range': [round(zmin - max(2.0, 0.25 * (zmax - zmin)), 1), round(zmax + 2, 1)]}), 200
    except AreaSelectionError as e:
        return fail(e, 422)
    except Exception as e:
        return fail(e, 500)


@app.route('/')
def index():
    return render_template('index.html')


# Warm the sample terrain model at import time. With `gunicorn --preload` this
# happens once in the master and is shared copy-on-write by all worker processes.
if os.environ.get('POND_WARMUP', '1') == '1' and os.path.exists(SAMPLE_KML_PATH):
    try:
        sample_model()
    except Exception:  # never block start-up
        traceback.print_exc()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print("==================================================")
    print("  Pond Catchment Analysis — API & Web Front-end")
    print(f"  Listening on : http://0.0.0.0:{port}  (node {NODE_NAME})")
    print(f"  Area API     : POST /api/analyzeArea")
    print("==================================================")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
