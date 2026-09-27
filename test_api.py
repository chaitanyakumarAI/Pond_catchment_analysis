"""API verification suite.  Usage: python test_api.py [base_url]"""
import sys
import time
import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://10.1.75.51:5237"
PARCEL = [[81.29, 21.245], [81.30, 21.245], [81.30, 21.254], [81.29, 21.254], [81.29, 21.245]]


def test_health():
    r = requests.get(f"{BASE_URL}/health", timeout=10)
    print("health:", r.status_code, r.json())
    assert r.status_code == 200


def test_coverage():
    r = requests.get(f"{BASE_URL}/api/coverage", timeout=30)
    d = r.json()
    assert r.status_code == 200 and d['success'] and len(d['coverage_polygon']) > 3
    print("coverage polygon vertices:", len(d['coverage_polygon']))


def test_analyze_area():
    t0 = time.time()
    r = requests.post(f"{BASE_URL}/api/analyzeArea", json={"polygon": PARCEL, "rainfall_mm": 850}, timeout=60)
    d = r.json()
    assert r.status_code == 200 and d['success']
    data = d['data']
    for key in ('pond_location', 'catchment_summary', 'expected_water_volume_m3', 'geojson_layers', 'selected_area'):
        assert key in data, key
    kinds = {f['properties']['kind'] for f in data['geojson_layers']['features']}
    assert {'pond_site', 'catchment', 'pond_footprint', 'selected_area'} <= kinds, kinds
    print(f"analyzeArea ({time.time()-t0:.2f}s, node {d['served_by']}): "
          f"{data['total_catchments_detected']} site(s), volume {data['expected_water_volume_m3']} m3/yr")


def test_area_validation():
    outside = [[81.40, 21.30], [81.42, 21.30], [81.42, 21.32], [81.40, 21.32]]
    r = requests.post(f"{BASE_URL}/api/analyzeArea", json={"polygon": outside}, timeout=30)
    assert r.status_code == 422, r.status_code
    print("outside-coverage rejected:", r.json()['error'][:60], "...")


def test_sample_route():
    r = requests.get(f"{BASE_URL}/api/sample", timeout=60)
    d = r.json()
    assert d['success']
    print("sample pond:", d['data']['pond_location'])


def test_upload_route():
    t0 = time.time()
    with open("contours_1m.kml", "rb") as f:
        r = requests.post(f"{BASE_URL}/analyzeContour",
                          files={"file": ("contours_1m.kml", f, "application/vnd.google-earth.kml+xml")}, timeout=120)
    assert r.json()['success']
    print(f"upload analyse OK ({time.time()-t0:.2f}s)")


def test_3d_mesh_route():
    r = requests.post(f"{BASE_URL}/api/terrain_3d_mesh", json={"polygon": PARCEL}, timeout=60)
    d = r.json()
    assert r.status_code == 200 and d['success']
    print(f"3D mesh: {len(d['x'])}x{len(d['y'])} grid, {len(d['candidates'])} candidates")


if __name__ == '__main__':
    for t in (test_health, test_coverage, test_analyze_area, test_area_validation,
              test_sample_route, test_upload_route, test_3d_mesh_route):
        t()
    print("\nAll API tests passed.")
