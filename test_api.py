import requests
import json
import time

BASE_URL = "http://localhost:5050"

def test_health():
    print("Testing /health endpoint...")
    r = requests.get(f"{BASE_URL}/health")
    print("Health Response:", r.status_code, r.json())
    assert r.status_code == 200

def test_sample_route():
    print("\nTesting /api/sample endpoint...")
    t0 = time.time()
    r = requests.get(f"{BASE_URL}/api/sample")
    elapsed = time.time() - t0
    print(f"Sample Route Response ({elapsed:.2f}s):", r.status_code)
    data = r.json()
    assert data['success'] == True
    print("Pond Location:", data['data']['pond_location'])
    print("Catchment Summary:", data['data']['catchment_summary'])
    print("Water Harvesting Estimates:", data['data']['water_harvesting_estimates'])

def test_upload_route():
    print("\nTesting POST /analyzeContour endpoint (File Upload)...")
    kml_file_path = "contours_1m.kml"
    t0 = time.time()
    with open(kml_file_path, "rb") as f:
        files = {"file": (kml_file_path, f, "application/vnd.google-earth.kml+xml")}
        r = requests.post(f"{BASE_URL}/analyzeContour", files=files)
    elapsed = time.time() - t0
    print(f"Upload Route Response ({elapsed:.2f}s):", r.status_code)
    data = r.json()
    assert data['success'] == True
    print("File Upload Status: SUCCESS [OK]")
    print("Analyzed Contours:", data['data']['input_file_info']['contour_count'])

def test_3d_mesh_route():
    print("\nTesting /api/terrain_3d_mesh endpoint...")
    r = requests.get(f"{BASE_URL}/api/terrain_3d_mesh")
    assert r.status_code == 200
    data = r.json()
    assert data['success'] == True
    print(f"3D Mesh Data OK: {len(data['x'])}x{len(data['y'])} grid with {len(data['candidates'])} pond candidates.")

if __name__ == '__main__':
    print("Starting API Verification Test Suite...")
    test_health()
    test_sample_route()
    test_upload_route()
    test_3d_mesh_route()
    print("\nAll API Verification Tests Passed Successfully!")
