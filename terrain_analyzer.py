"""
Pond Catchment Analysis Engine  v4
====================================
Integrates best-in-class techniques from peer implementations:
  1. UTM metric projection (pyproj) — accurate metre-based grid
  2. Priority-Flood depression filling (Barnes et al. 2014)
  3. Horn's 8-neighbour slope algorithm (GIS standard)
  4. Topographic Wetness Index  TWI = ln(A / tan(β))
  5. Gaussian slope suitability score  (peak at 2.5°)
  6. PSI = 0.40·ln(FA) + 0.25·GaussSlope + 0.20·TWI + 0.15·LowElev
  7. Shapely unary_union catchment boundary polygon
  8. Stage-storage rating curve output
"""

import math, heapq
import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter, distance_transform_edt, maximum_filter
from pyproj import Transformer
from shapely.geometry import box as shapely_box
from shapely.ops import unary_union

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_utm_epsg(center_lon, center_lat):
    """Return UTM EPSG code for a given lon/lat center."""
    zone = int((center_lon + 180) / 6) + 1
    if center_lat >= 0:
        return f"EPSG:326{zone:02d}"
    return f"EPSG:327{zone:02d}"


def _priority_flood_fill(dem):
    """
    Priority-Flood Depression Filling (Barnes et al. 2014).
    Eliminates all artificial pits so D8 routing is hydrologically correct.
    """
    filled = dem.copy().astype(np.float64)
    n_rows, n_cols = filled.shape
    EPS = 1e-4
    visited = np.zeros((n_rows, n_cols), dtype=bool)
    heap = []

    # Seed heap with all border cells
    for r in range(n_rows):
        for c in [0, n_cols - 1]:
            heapq.heappush(heap, (filled[r, c], r, c))
            visited[r, c] = True
    for c in range(n_cols):
        for r in [0, n_rows - 1]:
            if not visited[r, c]:
                heapq.heappush(heap, (filled[r, c], r, c))
                visited[r, c] = True

    neighbors = [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]
    while heap:
        elev, r, c = heapq.heappop(heap)
        for dr, dc in neighbors:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n_rows and 0 <= nc < n_cols and not visited[nr, nc]:
                visited[nr, nc] = True
                filled[nr, nc] = max(filled[nr, nc], elev + EPS)
                heapq.heappush(heap, (filled[nr, nc], nr, nc))
    return filled


def _horn_slope(dem, cell_x, cell_y):
    """Horn's 8-neighbour weighted slope (GIS standard used by GDAL/ArcGIS)."""
    padded = np.pad(dem, 1, mode='edge')
    dzdx = ((padded[:-2, 2:] + 2*padded[1:-1, 2:] + padded[2:, 2:]) -
            (padded[:-2, :-2] + 2*padded[1:-1, :-2] + padded[2:, :-2])) / (8 * cell_x)
    dzdy = ((padded[2:, :-2] + 2*padded[2:, 1:-1] + padded[2:, 2:]) -
            (padded[:-2, :-2] + 2*padded[:-2, 1:-1] + padded[:-2, 2:])) / (8 * cell_y)
    return np.degrees(np.arctan(np.sqrt(dzdx**2 + dzdy**2)))


def _d8_flow(dem):
    """Vectorised D8 flow direction and accumulation. Returns flow_acc, flow_dr, flow_dc, has_target."""
    n_rows, n_cols = dem.shape
    padded = np.pad(dem.astype(np.float64), 1, constant_values=np.inf)
    shifts = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    dists  = [math.sqrt(2),1,math.sqrt(2),1,1,math.sqrt(2),1,math.sqrt(2)]

    best_drop  = np.full((n_rows, n_cols), -np.inf)
    flow_dr    = np.zeros((n_rows, n_cols), dtype=np.int32)
    flow_dc    = np.zeros((n_rows, n_cols), dtype=np.int32)
    has_target = np.zeros((n_rows, n_cols), dtype=bool)

    for (dr, dc), d in zip(shifts, dists):
        nb   = padded[1+dr: 1+dr+n_rows, 1+dc: 1+dc+n_cols]
        drop = (dem - nb) / d
        upd  = drop > best_drop
        best_drop[upd] = drop[upd]
        flow_dr[upd] = dr; flow_dc[upd] = dc; has_target[upd] = True

    # Accumulate high→low
    flat_acc = np.ones(n_rows * n_cols, dtype=np.float32)
    for fi in np.argsort(dem.ravel())[::-1]:
        r, c = divmod(int(fi), n_cols)
        if has_target[r, c]:
            nr, nc = r + int(flow_dr[r, c]), c + int(flow_dc[r, c])
            if 0 <= nr < n_rows and 0 <= nc < n_cols:
                flat_acc[nr*n_cols + nc] += flat_acc[fi]

    return flat_acc.reshape(n_rows, n_cols), flow_dr, flow_dc, has_target


def _shapely_boundary(catchment_cells, x_coords, y_coords, res_x, res_y, wgs84_transformer):
    """Build accurate catchment polygon using Shapely unary_union, then project back to WGS84."""
    if not catchment_cells:
        return []
    boxes = [shapely_box(x_coords[c] - res_x/2, y_coords[r] - res_y/2,
                         x_coords[c] + res_x/2, y_coords[r] + res_y/2)
             for r, c in catchment_cells]
    union = unary_union(boxes).simplify(max(res_x, res_y) * 0.4)
    if union.is_empty:
        return []

    def transform_ring(ring_coords):
        coords = []
        for x, y in ring_coords:
            lon, lat = wgs84_transformer.transform(x, y)
            coords.append([round(lon, 6), round(lat, 6)])
        return coords

    if union.geom_type == 'Polygon':
        exterior = transform_ring(union.exterior.coords)
        return exterior
    else:
        # MultiPolygon — return largest polygon
        largest = max(union.geoms, key=lambda g: g.area)
        return transform_ring(largest.exterior.coords)


def _stage_storage_curve(dem_utm, catchment_cells, pond_r, pond_c, cell_area_m2):
    """Compute elevation-area-volume rating curve at the pond outlet."""
    base_elev = float(dem_utm[pond_r, pond_c])
    elev_cells = [float(dem_utm[r, c]) for r, c in catchment_cells]
    curve = []
    for depth in [0.5, 1.0, 1.5, 2.0, 3.0]:
        water_elev = base_elev + depth
        flooded    = sum(1 for e in elev_cells if e <= water_elev)
        area_m2    = flooded * cell_area_m2
        vol_m3     = sum((water_elev - e) * cell_area_m2
                         for e in elev_cells if e <= water_elev)
        curve.append({
            'water_depth_m':        depth,
            'water_surface_elev_m': round(water_elev, 2),
            'flooded_area_m2':      round(area_m2, 1),
            'storage_volume_m3':    round(vol_m3, 1),
        })
    return curve


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def analyze_terrain_and_catchment(parsed_kml_data, max_candidate_ponds=4):
    """
    v4: UTM-projected, Priority-Flood filled, TWI + Gaussian slope PSI engine.
    """
    pts  = parsed_kml_data['points']
    bbox = parsed_kml_data['bbox']

    lons  = pts[:, 0].copy(); lats = pts[:, 1].copy(); elevs = pts[:, 2].copy()
    valid = (elevs > 0) & (elevs < 9_000)
    lons, lats, elevs = lons[valid], lats[valid], elevs[valid]
    if len(lons) > 12_000:
        step = len(lons) // 12_000
        lons, lats, elevs = lons[::step], lats[::step], elevs[::step]

    # ── 1. UTM Projection ──────────────────────────────────────────────────
    center_lon = (bbox['min_lon'] + bbox['max_lon']) / 2
    center_lat = (bbox['min_lat'] + bbox['max_lat']) / 2
    utm_epsg   = _get_utm_epsg(center_lon, center_lat)

    to_utm   = Transformer.from_crs("EPSG:4326", utm_epsg, always_xy=True)
    to_wgs84 = Transformer.from_crs(utm_epsg, "EPSG:4326", always_xy=True)

    xs, ys = to_utm.transform(lons, lats)

    x_min, x_max = xs.min(), xs.max()
    y_min, y_max = ys.min(), ys.max()
    width_m  = x_max - x_min
    height_m = y_max - y_min

    # Grid: ~16m cell size
    n_cols   = 200
    n_rows   = max(50, int(n_cols * height_m / max(width_m, 1.0)))
    cell_x   = width_m  / n_cols
    cell_y   = height_m / n_rows
    cell_area = cell_x * cell_y

    grid_x_utm = np.linspace(x_min, x_max, n_cols)   # UTM metres
    grid_y_utm = np.linspace(y_min, y_max, n_rows)
    GX, GY     = np.meshgrid(grid_x_utm, grid_y_utm)
    query      = np.column_stack((GX.ravel(), GY.ravel()))
    src        = np.column_stack((xs, ys))

    # ── 2. DEM Interpolation ───────────────────────────────────────────────
    dem_lin = griddata(src, elevs, query, method='linear').reshape(n_rows, n_cols)
    dem_nn  = griddata(src, elevs, query, method='nearest').reshape(n_rows, n_cols)
    dem_raw = np.where(np.isnan(dem_lin), dem_nn, dem_lin)
    dem_raw = gaussian_filter(dem_raw, sigma=1.0)

    # ── 3. Priority-Flood Depression Fill ─────────────────────────────────
    dem = _priority_flood_fill(dem_raw)

    # ── 4. Horn's Slope ────────────────────────────────────────────────────
    slope_deg = _horn_slope(dem, cell_x, cell_y)

    # ── 5. D8 Flow ─────────────────────────────────────────────────────────
    flow_acc, flow_dr, flow_dc, has_target = _d8_flow(dem)

    # Upstream map for watershed delineation
    upstream_map = {}
    r_idx, c_idx = np.where(has_target)
    for r, c in zip(r_idx.tolist(), c_idx.tolist()):
        nr, nc = r + int(flow_dr[r, c]), c + int(flow_dc[r, c])
        if 0 <= nr < n_rows and 0 <= nc < n_cols:
            upstream_map.setdefault((nr, nc), []).append((r, c))

    # ── 6. River buffer (adaptive) ─────────────────────────────────────────
    river_threshold = np.percentile(flow_acc, 99)
    is_river        = flow_acc >= river_threshold
    dist_to_river   = distance_transform_edt(~is_river) * ((cell_x + cell_y) / 2)
    max_dist        = float(dist_to_river.max())
    buffer_m        = max(40.0, max_dist * 0.40)

    # ── 7. TWI — Topographic Wetness Index ─────────────────────────────────
    # TWI = ln(specific_catchment_area / tan(slope_rad))
    slope_rad     = np.radians(np.clip(slope_deg, 0.1, 89.9))
    spec_area     = np.maximum(flow_acc * cell_x, 1.0)   # m²/m width
    twi           = np.log(spec_area / (np.tan(slope_rad) + 1e-6))
    twi           = np.clip(twi, 0, None)
    twi_norm      = (twi - twi.min()) / max(twi.max() - twi.min(), 1e-6)

    # ── 8. PSI ─────────────────────────────────────────────────────────────
    # Flow score: log-scaled (prevents river dominance)
    flow_log      = np.log1p(flow_acc)
    flow_norm     = (flow_log - flow_log.min()) / max(flow_log.max() - flow_log.min(), 1e-6)

    # Gaussian slope score — peak at 2.5° (optimal pond gradient)
    slope_gauss   = np.exp(-((slope_deg - 2.5)**2) / (2 * 2.0**2))
    slope_gauss   = np.where(slope_deg > 8.0, 0.0, slope_gauss)

    # Elevation score
    min_z, max_z  = dem.min(), dem.max()
    norm_z        = (dem - min_z) / max(max_z - min_z, 1.0)

    # Depression depth (morphological)
    nbr_mean         = gaussian_filter(dem, sigma=1.5)
    depression_depth = nbr_mean - dem
    pos_dep          = depression_depth[depression_depth > 0]
    dep_p30          = float(np.percentile(pos_dep, 30)) if len(pos_dep) > 0 else 0.1
    dep_threshold    = max(0.05, dep_p30)

    valid_zone = (dist_to_river >= buffer_m) & (slope_deg >= 0.3) & (slope_deg < 8.0) & (depression_depth > dep_threshold)

    # PSI weights from Friend 1 (best validated formula):
    # 0.40·Flow  +  0.25·GaussSlope  +  0.20·TWI  +  0.15·LowElev
    psi = np.where(
        valid_zone,
        0.40 * flow_norm + 0.25 * slope_gauss + 0.20 * twi_norm + 0.15 * (1.0 - norm_z),
        0.0
    )

    b = 5
    psi[:b,:] = psi[-b:,:] = psi[:,:b] = psi[:,-b:] = 0.0

    # ── 9. Candidate selection ─────────────────────────────────────────────
    lmax  = maximum_filter(psi, size=16)
    peaks = np.argwhere((psi == lmax) & (psi > 0.01))
    peaks = sorted(peaks, key=lambda rc: psi[rc[0], rc[1]], reverse=True)

    sep_cells         = max(12, int(400 / ((cell_x + cell_y) / 2)))
    min_catch_cells   = max(5, int(15_000 / cell_area))   # ~1.5 ha minimum
    selected          = []

    for r, c in peaks:
        # Quick pre-check: does this site have enough upstream area?
        test = set(); stk = [(int(r), int(c))]
        while stk and len(test) < min_catch_cells * 2:
            cell = stk.pop()
            if cell not in test:
                test.add(cell)
                stk.extend(upstream_map.get(cell, []))
        if len(test) < min_catch_cells:
            continue
        if all((r-pr)**2 + (c-pc)**2 >= sep_cells**2 for pr, pc in selected):
            selected.append((r, c))
        if len(selected) >= max_candidate_ponds:
            break

    if not selected:
        masked = np.where(valid_zone, dem, np.inf)
        masked[:b,:] = masked[-b:,:] = masked[:,:b] = masked[:,-b:] = np.inf
        br, bc = np.unravel_index(np.argmin(masked if np.isfinite(masked).any() else dem), dem.shape)
        selected = [(int(br), int(bc))]

    # ── 10. Per-candidate output ───────────────────────────────────────────
    colors = ['#10B981','#06B6D4','#8B5CF6','#F59E0B','#EC4899']
    candidates = []; geojson_features = []

    for rank, (pr, pc) in enumerate(selected, start=1):
        # Watershed flood-fill
        catchment = set(); stk = [(int(pr), int(pc))]
        while stk:
            cell = stk.pop()
            if cell not in catchment:
                catchment.add(cell)
                stk.extend(upstream_map.get(cell, []))

        area_m2    = len(catchment) * cell_area
        area_ha    = area_m2 / 10_000
        area_acres = area_m2 / 4_046.86

        # Shapely boundary → back-projected to WGS84
        boundary = _shapely_boundary(catchment, grid_x_utm, grid_y_utm, cell_x, cell_y, to_wgs84)

        # Hydrology
        rainfall_m  = 0.85; runoff_c = 0.35
        runoff_m3   = area_m2 * rainfall_m * runoff_c
        capacity_m3 = min(runoff_m3 * 0.18, 25_000.0)
        surface_m2  = capacity_m3 / 3.5
        side_m      = math.sqrt(max(surface_m2, 1.0))

        # Stage-storage curve
        rating_curve = _stage_storage_curve(dem, catchment, pr, pc, cell_area)

        # Convert pond UTM back to WGS84
        pond_lon_f, pond_lat_f = to_wgs84.transform(float(grid_x_utm[pc]), float(grid_y_utm[pr]))
        pond_elev  = float(dem[pr, pc])
        river_d    = round(float(dist_to_river[pr, pc]), 1)
        score      = round(float(psi[pr, pc]) * 100, 1)
        slope_v    = round(float(slope_deg[pr, pc]), 2)
        twi_v      = round(float(twi[pr, pc]), 2)
        dep_v      = round(float(depression_depth[pr, pc]), 3)
        color      = colors[(rank-1) % len(colors)]

        cand = {
            'rank': rank, 'is_primary': rank == 1,
            'pond_location': {
                'latitude':                round(pond_lat_f, 6),
                'longitude':               round(pond_lon_f, 6),
                'elevation_m':             round(pond_elev, 2),
                'river_buffer_distance_m': river_d,
                'depression_depth_m':      dep_v,
                'topographic_wetness_index': twi_v,
                'suitability_score_pct':   score,
                'terrain_slope_deg':       slope_v,
            },
            'catchment_summary': {
                'area_m2': round(area_m2,2), 'area_hectares': round(area_ha,2),
                'area_acres': round(area_acres,2), 'contributing_cells': len(catchment),
            },
            'water_harvesting_estimates': {
                'assumed_annual_rainfall_mm':     850,
                'runoff_coefficient_C':           runoff_c,
                'estimated_annual_runoff_m3':     round(runoff_m3, 2),
                'estimated_annual_runoff_liters': round(runoff_m3*1000, 0),
                'recommended_pond_capacity_m3':   round(capacity_m3, 2),
                'recommended_pond_depth_m':       3.5,
                'recommended_pond_surface_area_m2': round(surface_m2, 2),
                'recommended_dimensions_m':       f"{round(side_m,1)}m x {round(side_m,1)}m",
            },
            'stage_storage_curve': rating_curve,
            'color': color,
        }
        candidates.append(cand)

        geojson_features.append({
            'type':'Feature',
            'geometry':{'type':'Point','coordinates':[round(pond_lon_f,6), round(pond_lat_f,6)]},
            'properties':{
                'rank':rank,'name':f"Farm Pond Site #{rank}",
                'elevation_m':round(pond_elev,2),'river_distance_m':river_d,
                'depression_depth_m':dep_v,'twi':twi_v,
                'suitability_score':score,'area_ha':round(area_ha,2),'color':color,
            }
        })
        if boundary:
            geojson_features.append({
                'type':'Feature',
                'geometry':{'type':'Polygon','coordinates':[boundary]},
                'properties':{
                    'rank':rank,'name':f"Catchment Basin #{rank}",
                    'area_ha':round(area_ha,2),'area_m2':round(area_m2,2),'color':color,
                }
            })

    primary = candidates[0]
    return {
        'pond_location':              primary['pond_location'],
        'catchment_summary':          primary['catchment_summary'],
        'water_harvesting_estimates': primary['water_harvesting_estimates'],
        'stage_storage_curve':        primary['stage_storage_curve'],
        'total_catchments_detected':  len(candidates),
        'all_candidate_sites':        candidates,
        'terrain_statistics': {
            'min_elevation_m':     round(float(min_z),2),
            'max_elevation_m':     round(float(max_z),2),
            'elevation_range_m':   round(float(max_z-min_z),2),
            'avg_slope_deg':       round(float(slope_deg.mean()),2),
            'avg_twi':             round(float(twi.mean()),2),
            'utm_projection':      utm_epsg,
            'river_buffer_used_m': round(buffer_m,1),
            'map_width_meters':    round(width_m,1),
            'map_height_meters':   round(height_m,1),
            'grid_resolution':     f"{n_cols} x {n_rows}",
            'cell_size_m':         round((cell_x+cell_y)/2,1),
        },
        'geojson_layers':{'type':'FeatureCollection','features':geojson_features},
    }


# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import time
    from kml_parser import parse_kml_or_kmz
    t0 = time.time()
    data   = parse_kml_or_kmz('contours_1m.kml')
    result = analyze_terrain_and_catchment(data)
    t1 = time.time()
    print(f"[Done] {t1-t0:.2f}s | {result['total_catchments_detected']} sites | UTM: {result['terrain_statistics']['utm_projection']} | Buffer: {result['terrain_statistics']['river_buffer_used_m']}m")
    for c in result['all_candidate_sites']:
        l = c['pond_location']; cs = c['catchment_summary']
        print(f"  #{c['rank']} {l['latitude']:.5f},{l['longitude']:.5f} | Elev {l['elevation_m']}m | Slope {l['terrain_slope_deg']}° | TWI {l['topographic_wetness_index']} | Dep {l['depression_depth_m']}m | {cs['area_hectares']} ha | Score {l['suitability_score_pct']}%")
        for s in c['stage_storage_curve'][:2]:
            print(f"     Storage @ {s['water_depth_m']}m depth: {s['storage_volume_m3']} m³  ({s['flooded_area_m2']} m² flooded)")
