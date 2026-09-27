# Handoff — CSD Assignment 1, Phase 3 (Pond Catchment) deployment

## Goal
Deploy the finished Phase 3 app on the 4 lab systems, verify the public front-end URL,
run the stress test on the lab, push to GitHub, and finish the report TODOs.
Submission needs: Final Report, GitHub URL, working front-end URL, ≤5-min YouTube demo.

## Where things are
- Local project: `E:\CSD\Pond_catchment` (git repo, remote
  `https://github.com/chaitanyakumarAI/Pond_catchment_analysis.git`, branch `main`).
- Phase 3 changes are written to disk but **not committed or pushed**. GitHub still has the
  Phase 1 version (last commit 543b361, Sep 3).
- Lab 6 files in `E:\CSD\Lab6_DynamicLoadBalancer` and `E:\CSD\deploy_cluster_auto.py` hold
  the earlier cluster settings (ports and IPs reused below).

## What was built (tested locally, not yet on the lab)
- `terrain_analyzer.py`: split into two stages.
  - `build_terrain_model()` (Stage A): DEM, Priority-Flood, D8, TWI and PSI. Runs once per
    dataset, about 0.5 s, and is cached.
  - `select_sites(model, polygon)` (Stage B): pond sites inside the user's polygon, their
    catchments and Q = C·P·A. Takes 7–35 ms.
  - `analyze_terrain_and_catchment()` keeps the Phase 1 signature.
  - The whole-map output is identical to Phase 1: top site 21.245616, 81.29504, 0.98 ha,
    2902.62 m³/yr.
- `app.py`: new `POST /api/analyzeArea`, which accepts JSON `{polygon, rainfall_mm,
  runoff_coeff, pond_depth_m}` or multipart with a file.
  - Other new routes: `GET /api/coverage`, `/metrics`.
  - `/api/plots` and `/api/terrain_3d_mesh` now accept POST with the same payload, so
    workers are stateless.
  - LRU caches for terrain models and results.
  - Validation returns 422 for areas under 0.5 ha, over 50 km², or with less than 60 %
    data coverage.
  - Phase 1 routes (`/analyzeContour`, `/findCatchment`, `/api/sample`) unchanged.
- Front-end (`templates/index.html`, `static/app.js`, `static/style.css`):
  - Leaflet.draw rectangle and polygon tools, a dashed outline of where contour data
    exists, and inputs for the three parameters.
  - Overlays: pond site, catchment polygon, pond footprint to scale, volume labels, legend.
  - Leaflet, Leaflet.draw and Plotly are copied into `static/vendor`. Font Awesome and the
    map tiles still load from the internet.
- `cluster/`:
  - `pond_lb.go` plus a prebuilt linux/amd64 `pond_lb` binary. Go load balancer:
    least-inflight routing, round-robin on ties, per-node concurrency cap, bounded queue
    then 503 shedding, health checks, retry on another node, `/lb/stats`.
  - `gunicorn.conf.py`, `start_worker.sh`, `start_lb.sh`.
  - `deploy_cluster.py` (paramiko; prompts for the password or reads `POND_SSH_PASS`).
  - `locustfile.py` and `run_stress.py`.
- `test_api.py <base_url>`: full API test. Passes against a local 4-worker + LB setup.
- `report/Final_Report.tex` and `.pdf` (7 pages): generic LaTeX, because the Overleaf
  template link couldn't be read. Its sections must be copied into the official template.
  Red `\todo{}` marks need lab data.
- `results/local_dryrun_*`: stress results from a 2-core VM. Label them as a local run;
  they are not lab numbers.

## Cluster settings (in `cluster/deploy_cluster.py` CONFIG)
| Item | Value |
|---|---|
| Host / user | 10.1.75.51 / student |
| SSH ports | sys1 2237, sys2 2238, sys3 2239, sys4 2240 |
| Worker IPs (as seen from Sys1) | sys1 127.0.0.1, sys2 172.17.0.39, sys3 172.17.0.40, sys4 172.17.0.41 |
| Worker port | 5002 on every system (5001 is used by the Lab 6 chat backend) |
| LB port on Sys1 | **5000 — unverified.** Assumes public :5237 → Sys1 :5000, by analogy with Lab 6 (4237 → 4000). Phase 1 was reached at :5237, but its app default was 5050. Check which internal port serves :5237 and set `lb_port`. |
| Public URL | http://10.1.75.51:5237/ |

The user gives the passwords directly to whoever deploys. **None are stored in this file.**
The Sys1 password was pasted in chat, so recommend changing it after the viva.

## Next steps
1. From a machine on the campus network or VPN:
   `pip install paramiko` then `python cluster/deploy_cluster.py`.
   - It uploads a tarball to `~/pond` on each system and pip-installs the requirements
     (`--user`). It starts gunicorn on :5002 (flask threaded mode if gunicorn is missing),
     then starts `pond_lb` on Sys1.
   - `start_worker.sh` stops old `Pond_catchment/app.py` processes. It does not touch the
     Lab 6 chat processes.
2. `python cluster/deploy_cluster.py --status`, then `python test_api.py http://10.1.75.51:5237`,
   then open the URL in a browser.
3. If pip fails (no internet on the lab systems), dependencies must be installed another
   way. Python needs flask, flask-cors, numpy, scipy, pyproj, shapely, matplotlib and
   gunicorn.
4. Stress test on the lab: `python cluster/run_stress.py --target cluster=http://10.1.75.51:5237`
   (optionally add `--target single=http://172.17.0.39:5002` from inside the lab network).
   Put the resulting csv and png in report Table 2 and Figure 4, and fill in the total
   core count.
5. `git add -A && git commit -m "Phase 3: map area selection, 4-system LB, report" && git push`.
6. Report: copy it into the official Overleaf template and replace the UI screenshot with
   one from the lab deployment. Add the front-end URL and the YouTube link.

## Known gaps and risks
- Nothing has run on the lab systems yet, and the LB port mapping is unconfirmed.
- The shell on the user's PC failed to start this session, so all file transfers used
  copy tools.
- The Python and pip versions on the lab systems are unknown. `requirements.txt` uses
  minimum versions (`>=`).
