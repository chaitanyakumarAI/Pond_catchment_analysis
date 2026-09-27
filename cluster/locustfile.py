"""
Stress test for the Pond Catchment cluster.

  locust -f cluster/locustfile.py --host http://10.1.75.51:5237 \
         --headless -u 100 -r 10 -t 3m --csv results/stress

Traffic mix (models a class demo / many farmers using the site at once):
  60 %  new land parcel drawn at a random place inside the data coverage (cache miss)
  20 %  a popular parcel re-queried (result-cache hit)
  10 %  whole-map analysis (/api/sample)
   5 %  coverage + health (page load)
   5 %  3D mesh for a parcel (heavier JSON)
"""
import random
from locust import HttpUser, task, between

# Data coverage of contours_1m.kml (lon/lat bbox, shrunk slightly inward)
LON0, LON1 = 81.2840, 81.3100
LAT0, LAT1 = 21.2420, 21.2615
POPULAR = [
    [[81.2815, 21.24], [81.297, 21.24], [81.297, 21.2635], [81.2815, 21.2635], [81.2815, 21.24]],
    [[81.29, 21.245], [81.30, 21.245], [81.30, 21.254], [81.29, 21.254], [81.29, 21.245]],
    [[81.285, 21.242], [81.305, 21.245], [81.295, 21.26], [81.285, 21.242]],
]


def random_parcel():
    w = random.uniform(0.002, 0.012)      # ≈ 200 m – 1.25 km
    h = random.uniform(0.002, 0.010)
    x = random.uniform(LON0, LON1 - w)
    y = random.uniform(LAT0, LAT1 - h)
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]


class Farmer(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.client.get("/api/coverage", name="/api/coverage")

    @task(60)
    def new_parcel(self):
        body = {"polygon": random_parcel(), "rainfall_mm": random.choice([700, 850, 1100])}
        with self.client.post("/api/analyzeArea", json=body, name="/api/analyzeArea [new]",
                              catch_response=True) as r:
            if r.status_code == 422:
                r.success()          # validation reject (e.g. area too small) is a correct answer
            elif r.status_code == 503:
                r.failure("shed 503")

    @task(20)
    def popular_parcel(self):
        self.client.post("/api/analyzeArea", json={"polygon": random.choice(POPULAR)},
                         name="/api/analyzeArea [cached]")

    @task(10)
    def whole_map(self):
        self.client.get("/api/sample", name="/api/sample")

    @task(5)
    def page_load(self):
        self.client.get("/health", name="/health")
        self.client.get("/api/coverage", name="/api/coverage")

    @task(5)
    def mesh(self):
        self.client.post("/api/terrain_3d_mesh", json={"polygon": random.choice(POPULAR)},
                         name="/api/terrain_3d_mesh")
