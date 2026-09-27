# AquaTerrain AI — Pond Site & Catchment Planner (CSD Assignment 1)

Web app that lets a user **select a land area on a map** and returns, for that area:

- the **suggested pond location(s)**,
- the **catchment area** that drains into each pond,
- the **expected water volume** that can be collected per year (Q = C · P · A),

all drawn on the map (pond footprint to scale, catchment polygon, volume labels).

## Run locally

```bash
pip install -r requirements.txt
python app.py                  # http://localhost:5050
```

## API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/analyzeArea` | **Phase 3.** Body `{"polygon": [[lon,lat],...], "rainfall_mm": 850, "runoff_coeff": 0.35, "pond_depth_m": 3.5}`. Also accepts multipart with `file` (KML/KMZ) + `polygon`. |
| `GET` | `/api/coverage` | Footprint of the contour data (dashed boundary on the map) and limits |
| `POST` | `/analyzeContour`, `/findCatchment` | Phase-1 routes: whole uploaded map |
| `GET` | `/api/sample` | Whole-map analysis of `contours_1m.kml` |
| `GET/POST` | `/api/plots`, `/api/terrain_3d_mesh` | Terrain plots / 3D mesh for the same request |
| `GET` | `/health`, `/metrics` | Health check and per-worker counters |
| `GET` | `/lb/stats` | Load-balancer statistics (only through the LB) |

```bash
curl -X POST http://10.1.75.51:5237/api/analyzeArea -H "Content-Type: application/json" \
  -d '{"polygon":[[81.29,21.245],[81.30,21.245],[81.30,21.254],[81.29,21.254],[81.29,21.245]]}'
```

## Four-system deployment

```
 browser ──► Sys1 :5000  pond_lb (Go)  ──┬──► Sys1 :5002 gunicorn (cores-1 procs)
                                         ├──► Sys2 :5002 gunicorn (cores procs)
                                         ├──► Sys3 :5002 gunicorn
                                         └──► Sys4 :5002 gunicorn
```

```bash
cd cluster && GOOS=linux GOARCH=amd64 go build -o pond_lb . && cd ..   # once
pip install paramiko
python cluster/deploy_cluster.py          # uploads + starts all 4 systems
python cluster/deploy_cluster.py --status
```

Check `CONFIG` at the top of `cluster/deploy_cluster.py` (SSH ports, private IPs,
LB port that maps to the public URL).

## Stress test

```bash
pip install locust
python cluster/run_stress.py --target cluster=http://10.1.75.51:5237 \
       --target single=http://172.17.0.39:5002 --users 10 50 100 200 --duration 60
```

Writes `results/stress_summary.csv` and `results/stress_plot.png`. Run the
`single` target from a lab system, because the private IP is only reachable there.

## Repository layout

```
app.py               Flask API + front-end, caching, validation
terrain_analyzer.py  Stage A terrain model (DEM, sink fill, D8, TWI, PSI) + Stage B area query
kml_parser.py        KML/KMZ contour parser
templates/, static/  Leaflet + Leaflet.draw front-end (libraries vendored in static/vendor)
cluster/             pond_lb.go, gunicorn.conf.py, start_*.sh, deploy_cluster.py, locustfile.py, run_stress.py
test_api.py          API verification suite  (python test_api.py http://host:port)
```
