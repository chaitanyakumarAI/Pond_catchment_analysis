"""
Pond Catchment Terrain Analysis Engine  (v3 - corrected)
=========================================================
Pipeline:
  1. Parse & downsample KML points
  2. Nearest-neighbour DEM (200-col grid, ~16m/cell)
  3. Gaussian smooth (sigma=1 cell)
  4. Vectorised D8 flow accumulation
  5. River identification — top 3% FA cells
  6. Adaptive river buffer = min(60% of map width, 200m)
  7. Depression detection (morphological diff vs 3-cell sigma blur)
  8. PSI = 55% depression + 30% low elevation + 15% flat slope
  9. Local maxima → spatially spread candidate sites
 10. Upstream watershed flood-fill
 11. Polar-sorted perimeter boundary polygon
"""

import math
import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import (gaussian_filter, distance_transform_edt,
                            maximum_filter)

# ---------------------------------------------------------------------------
# Haversine helper
# ---------------------------------------------------------------------------
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# D8 flow accumulation  (pure NumPy, no Python loops per cell)
# ---------------------------------------------------------------------------
def _d8_flow_accumulation(dem):
    """
    Vectorised D8 flow accumulation.
    For each cell, the steepest-descent neighbour receives its accumulated count.
    Returns float array same shape as dem.
    """
    n_rows, n_cols = dem.shape
    # Pad with +inf so border cells always drain inward
    padded = np.pad(dem.astype(np.float64), 1, constant_values=np.inf)

    # For each of 8 directions, compute the drop gradient
    shifts = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    distances = [math.sqrt(2), 1, math.sqrt(2), 1, 1, math.sqrt(2), 1, math.sqrt(2)]

    best_drop  = np.full((n_rows, n_cols), -np.inf)
    flow_dr    = np.zeros((n_rows, n_cols), dtype=np.int32)
    flow_dc    = np.zeros((n_rows, n_cols), dtype=np.int32)
    has_target = np.zeros((n_rows, n_cols), dtype=bool)

    for (dr, dc), dist in zip(shifts, distances):
        neighbour = padded[1+dr: 1+dr+n_rows, 1+dc: 1+dc+n_cols]
        drop = (dem - neighbour) / dist
        better = drop > best_drop
        best_drop[better]  = drop[better]
        flow_dr[better]    = dr
        flow_dc[better]    = dc
        has_target[better] = True

    # Accumulate high → low
    flat_order = np.argsort(dem.ravel())[::-1]   # high-to-low flat indices
    flat_acc   = np.ones(n_rows * n_cols, dtype=np.float32)
    flat_dr    = flow_dr.ravel()
    flat_dc    = flow_dc.ravel()
    flat_ht    = has_target.ravel()

    for fi in flat_order:
        if not flat_ht[fi]:
            continue
        r, c = divmod(int(fi), n_cols)
        nr = r + int(flat_dr[fi])
        nc = c + int(flat_dc[fi])
        if 0 <= nr < n_rows and 0 <= nc < n_cols:
            flat_acc[nr * n_cols + nc] += flat_acc[fi]

    return flat_acc.reshape(n_rows, n_cols), flow_dr, flow_dc, has_target


# ---------------------------------------------------------------------------
# Polar-sorted boundary polygon
# ---------------------------------------------------------------------------
def _polar_boundary(catchment_cells, grid_x, grid_y, n_rows, n_cols):
    if not catchment_cells:
        return []
    mask = np.zeros((n_rows, n_cols), dtype=bool)
    for cr, cc in catchment_cells:
        mask[cr, cc] = True
    # Erode to find edge cells
    padded = np.pad(mask, 1, constant_values=False)
    edge = np.zeros_like(mask)
    for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
        edge |= mask & ~padded[1+dr:1+dr+n_rows, 1+dc:1+dc+n_cols]
    rs, cs = np.where(edge)
    if len(rs) < 3:
        rs, cs = np.where(mask)
    cx, cy = cs.mean(), rs.mean()
    angles = np.arctan2(rs - cy, cs - cx)
    idx    = np.argsort(angles)
    coords = [[float(grid_x[cs[i]]), float(grid_y[rs[i]])] for i in idx]
    coords.append(coords[0])
    return coords


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------
def analyze_terrain_and_catchment(parsed_kml_data, max_candidate_ponds=4):
    """
    Correct, lightweight pond-site analysis from KML contour data.
    Uses adaptive river-buffer distance (data-aware, not hardcoded).
    """
    pts  = parsed_kml_data['points']
    bbox = parsed_kml_data['bbox']

    lons  = pts[:, 0].copy()
    lats  = pts[:, 1].copy()
    elevs = pts[:, 2].copy()

    # 1. Validity filter
    valid = (elevs > 0) & (elevs < 9_000)
    lons, lats, elevs = lons[valid], lats[valid], elevs[valid]

    # 2. Downsample to ≤ 12,000 points (keeps Delaunay fast & memory-safe)
    if len(lons) > 12_000:
        step = len(lons) // 12_000
        lons, lats, elevs = lons[::step], lats[::step], elevs[::step]

    # 3. Grid dimensions (target ~16 m/cell)
    width_m  = haversine_distance(bbox['min_lat'], bbox['min_lon'],
                                  bbox['min_lat'], bbox['max_lon'])
    height_m = haversine_distance(bbox['min_lat'], bbox['min_lon'],
                                  bbox['max_lat'], bbox['min_lon'])

    n_cols = 200
    n_rows = max(50, int(n_cols * height_m / max(width_m, 1.0)))
    cell_x = width_m  / n_cols
    cell_y = height_m / n_rows
    cell_avg  = (cell_x + cell_y) / 2.0
    cell_area = cell_x * cell_y

    grid_x = np.linspace(bbox['min_lon'], bbox['max_lon'], n_cols)
    grid_y = np.linspace(bbox['min_lat'], bbox['max_lat'], n_rows)
    gx, gy = np.meshgrid(grid_x, grid_y)
    query  = np.column_stack((gx.ravel(), gy.ravel()))
    src    = np.column_stack((lons, lats))

    # 4. DEM interpolation
    dem_lin = griddata(src, elevs, query, method='linear').reshape(n_rows, n_cols)
    dem_nn  = griddata(src, elevs, query, method='nearest').reshape(n_rows, n_cols)
    dem     = np.where(np.isnan(dem_lin), dem_nn, dem_lin)
    dem     = gaussian_filter(dem, sigma=1.0)

    # 5. Slope
    dy_g, dx_g = np.gradient(dem, cell_y, cell_x)
    slope_deg   = np.degrees(np.arctan(np.sqrt(dx_g**2 + dy_g**2)))

    # 6. D8 flow accumulation
    flow_acc, flow_dr, flow_dc, has_target = _d8_flow_accumulation(dem)

    # 7. Build upstream map for watershed delineation
    upstream_map = {}
    r_idx, c_idx = np.where(has_target)
    for r, c in zip(r_idx.tolist(), c_idx.tolist()):
        nr = r + int(flow_dr[r, c])
        nc = c + int(flow_dc[r, c])
        if 0 <= nr < n_rows and 0 <= nc < n_cols:
            upstream_map.setdefault((nr, nc), []).append((r, c))

    # 8. River mask & ADAPTIVE buffer distance
    #    River = cells in top 2% of flow accumulation (main channel trunks)
    river_threshold = np.percentile(flow_acc, 98)
    is_river = flow_acc >= river_threshold
    dist_to_river = distance_transform_edt(~is_river) * cell_avg   # metres

    # Adaptive buffer:
    #   Use 55% of the maximum available distance to the river within the map.
    #   This guarantees we always have a valid farmland zone regardless of map size.
    max_dist_available = float(dist_to_river.max())
    buffer_m = max(30.0, max_dist_available * 0.55)

    # 9. Depression depth (morphological) — sigma=1.5 cells (~25m neighbourhood)
    #    This matches real farm pond micro-basin scale without conflating hills.
    nbr_mean         = gaussian_filter(dem, sigma=1.5)
    depression_depth = nbr_mean - dem        # positive = concave sink / basin
    # Threshold = 15% of the 75th percentile of positive depressions
    pos_dep = depression_depth[depression_depth > 0]
    dep_q75 = float(np.percentile(pos_dep, 75)) if len(pos_dep) > 0 else 0.1
    dep_threshold = max(0.02, dep_q75 * 0.15)

    # 10. PSI
    min_z, max_z = dem.min(), dem.max()
    z_range = max(max_z - min_z, 1.0)
    norm_z         = (dem - min_z) / z_range
    norm_dep       = np.clip(depression_depth / max(dep_q75, 0.1), 0.0, 1.0)
    norm_slope     = np.clip(slope_deg / 15.0, 0.0, 1.0)

    valid_zone = (dist_to_river >= buffer_m) & (slope_deg < 12.0) & (depression_depth > dep_threshold)

    psi = np.where(
        valid_zone,
        0.55 * norm_dep + 0.30 * (1.0 - norm_z) + 0.15 * (1.0 - norm_slope),
        0.0
    )

    # Border mask
    b = 5
    psi[:b, :] = psi[-b:, :] = psi[:, :b] = psi[:, -b:] = 0.0

    # 11. Candidate sites: local maxima with spatial separation
    lmax  = maximum_filter(psi, size=16)
    peaks = np.argwhere((psi == lmax) & (psi > 0.01))
    peaks = sorted(peaks, key=lambda rc: psi[rc[0], rc[1]], reverse=True)

    sep_cells = max(10, int(350 / cell_avg))   # ~350m apart
    selected  = []
    for r, c in peaks:
        if all((r-pr)**2 + (c-pc)**2 >= sep_cells**2 for pr, pc in selected):
            selected.append((r, c))
        if len(selected) >= max_candidate_ponds:
            break

    # Fallback: lowest valid-zone point
    if not selected:
        masked = np.where(valid_zone, dem, np.inf)
        masked[:b, :] = masked[-b:, :] = masked[:, :b] = masked[:, -b:] = np.inf
        if np.isfinite(masked).any():
            br, bc = np.unravel_index(np.argmin(masked), dem.shape)
        else:
            # Final fallback ignoring zone constraints
            br, bc = np.unravel_index(np.argmin(dem), dem.shape)
        selected = [(int(br), int(bc))]

    # 12. Per-candidate output
    colors = ['#10B981', '#06B6D4', '#8B5CF6', '#F59E0B', '#EC4899']
    candidates      = []
    geojson_features = []

    for rank, (pr, pc) in enumerate(selected, start=1):
        # Upstream flood-fill catchment
        catchment = set()
        stack = [(int(pr), int(pc))]
        while stack:
            cell = stack.pop()
            if cell not in catchment:
                catchment.add(cell)
                stack.extend(upstream_map.get(cell, []))

        area_m2    = len(catchment) * cell_area
        area_ha    = area_m2 / 10_000
        area_acres = area_m2 / 4_046.86

        boundary = _polar_boundary(catchment, grid_x, grid_y, n_rows, n_cols)

        # Hydrology
        rainfall_m  = 0.85
        runoff_c    = 0.35
        runoff_m3   = area_m2 * rainfall_m * runoff_c
        capacity_m3 = min(runoff_m3 * 0.18, 25_000.0)
        surface_m2  = capacity_m3 / 3.5
        side_m      = math.sqrt(max(surface_m2, 1.0))

        color     = colors[(rank-1) % len(colors)]
        pond_lat  = float(grid_y[pr])
        pond_lon  = float(grid_x[pc])
        pond_elev = float(dem[pr, pc])
        river_d   = round(float(dist_to_river[pr, pc]), 1)
        score     = round(float(psi[pr, pc]) * 100, 1)
        slope_v   = round(float(slope_deg[pr, pc]), 2)
        dep_v     = round(float(depression_depth[pr, pc]), 3)

        cand = {
            'rank': rank,
            'is_primary': rank == 1,
            'pond_location': {
                'latitude':               round(pond_lat, 6),
                'longitude':              round(pond_lon, 6),
                'elevation_m':            round(pond_elev, 2),
                'river_buffer_distance_m': river_d,
                'depression_depth_m':     dep_v,
                'suitability_score_pct':  score,
                'terrain_slope_deg':      slope_v,
            },
            'catchment_summary': {
                'area_m2':          round(area_m2, 2),
                'area_hectares':    round(area_ha, 2),
                'area_acres':       round(area_acres, 2),
                'contributing_cells': len(catchment),
            },
            'water_harvesting_estimates': {
                'assumed_annual_rainfall_mm':    850,
                'runoff_coefficient_C':          runoff_c,
                'estimated_annual_runoff_m3':    round(runoff_m3, 2),
                'estimated_annual_runoff_liters': round(runoff_m3 * 1000, 0),
                'recommended_pond_capacity_m3':  round(capacity_m3, 2),
                'recommended_pond_depth_m':      3.5,
                'recommended_pond_surface_area_m2': round(surface_m2, 2),
                'recommended_dimensions_m':      f"{round(side_m,1)}m x {round(side_m,1)}m",
            },
            'color': color,
        }
        candidates.append(cand)

        geojson_features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [round(pond_lon,6), round(pond_lat,6)]},
            'properties': {
                'rank': rank, 'name': f"Farm Pond Site #{rank}",
                'elevation_m': round(pond_elev,2), 'river_distance_m': river_d,
                'depression_depth_m': dep_v, 'suitability_score': score,
                'area_ha': round(area_ha,2), 'color': color,
            }
        })
        geojson_features.append({
            'type': 'Feature',
            'geometry': {'type': 'Polygon', 'coordinates': [boundary]},
            'properties': {
                'rank': rank, 'name': f"Catchment Basin #{rank}",
                'area_ha': round(area_ha,2), 'area_m2': round(area_m2,2), 'color': color,
            }
        })

    primary = candidates[0]
    return {
        'pond_location':              primary['pond_location'],
        'catchment_summary':          primary['catchment_summary'],
        'water_harvesting_estimates': primary['water_harvesting_estimates'],
        'total_catchments_detected':  len(candidates),
        'all_candidate_sites':        candidates,
        'terrain_statistics': {
            'min_elevation_m':   round(float(min_z), 2),
            'max_elevation_m':   round(float(max_z), 2),
            'elevation_range_m': round(float(z_range), 2),
            'avg_slope_deg':     round(float(slope_deg.mean()), 2),
            'river_buffer_used_m': round(buffer_m, 1),
            'map_width_meters':  round(width_m, 1),
            'map_height_meters': round(height_m, 1),
            'grid_resolution':   f"{n_cols} x {n_rows}",
            'cell_size_m':       round(cell_avg, 1),
        },
        'geojson_layers': {
            'type': 'FeatureCollection',
            'features': geojson_features,
        },
    }


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import time
    from kml_parser import parse_kml_or_kmz

    t0 = time.time()
    data = parse_kml_or_kmz('contours_1m.kml')
    t1 = time.time()
    print(f"[Parse]   {t1-t0:.2f}s  |  {data['elevation_stats']['total_points']:,} pts  |  {data['elevation_stats']['contour_count']} contours")

    result = analyze_terrain_and_catchment(data)
    t2 = time.time()
    print(f"[Analyse] {t2-t1:.2f}s  |  {result['total_catchments_detected']} candidate sites")
    print(f"[Total]   {t2-t0:.2f}s")
    stats = result['terrain_statistics']
    print(f"[Info]    River buffer used: {stats['river_buffer_used_m']}m | Grid: {stats['grid_resolution']} | Cell: {stats['cell_size_m']}m")
    print()
    for c in result['all_candidate_sites']:
        loc = c['pond_location']
        cs  = c['catchment_summary']
        print(f"  Site #{c['rank']} | {loc['latitude']:.5f},{loc['longitude']:.5f} "
              f"| Elev {loc['elevation_m']}m | Depression {loc['depression_depth_m']}m "
              f"| River {loc['river_buffer_distance_m']}m away "
              f"| {cs['area_hectares']} ha | Score {loc['suitability_score_pct']}%")
