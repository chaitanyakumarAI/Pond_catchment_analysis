import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter, maximum_filter
from scipy.spatial import ConvexHull
import math

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates distance in meters between two lat/lon coordinates using Haversine formula."""
    R = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def analyze_terrain_and_catchment(parsed_kml_data, grid_resolution=150, max_candidate_ponds=4):
    """
    Generalized Terrain & Hydrological Analysis Engine.
    Detects MULTIPLE suitable pond sites & sub-catchments across the contour map.
    Returns primary optimal catchment + list of all sub-catchment candidates.
    """
    pts = parsed_kml_data['points']
    bbox = parsed_kml_data['bbox']
    
    lons = pts[:, 0]
    lats = pts[:, 1]
    elevs = pts[:, 2]

    # Filter invalid/outlier elevations
    valid_mask = (elevs > 0) & (elevs < 9000)
    if np.sum(valid_mask) > 10:
        lons = lons[valid_mask]
        lats = lats[valid_mask]
        elevs = elevs[valid_mask]

    # Calculate physical extent in meters
    width_m = haversine_distance(bbox['min_lat'], bbox['min_lon'], bbox['min_lat'], bbox['max_lon'])
    height_m = haversine_distance(bbox['min_lat'], bbox['min_lon'], bbox['max_lat'], bbox['min_lon'])

    n_cols = grid_resolution
    aspect_ratio = height_m / (width_m if width_m > 0 else 1.0)
    n_rows = max(30, int(n_cols * aspect_ratio))

    cell_size_x = width_m / n_cols
    cell_size_y = height_m / n_rows
    cell_area_m2 = cell_size_x * cell_size_y

    # Create 2D coordinate grid
    grid_x = np.linspace(bbox['min_lon'], bbox['max_lon'], n_cols)
    grid_y = np.linspace(bbox['min_lat'], bbox['max_lat'], n_rows)
    gx, gy = np.meshgrid(grid_x, grid_y)

    # DEM Grid Interpolation
    grid_pts = np.column_stack((gx.ravel(), gy.ravel()))
    input_pts = np.column_stack((lons, lats))

    dem_linear = griddata(input_pts, elevs, grid_pts, method='linear').reshape((n_rows, n_cols))
    dem_nearest = griddata(input_pts, elevs, grid_pts, method='nearest').reshape((n_rows, n_cols))
    dem = np.where(np.isnan(dem_linear), dem_nearest, dem_linear)
    dem = gaussian_filter(dem, sigma=1.0)

    # Compute Slope (in degrees)
    dy, dx = np.gradient(dem, cell_size_y, cell_size_x)
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    slope_deg = np.degrees(slope_rad)

    # Compute D8 Flow Direction
    neighbors = [
        (-1, 0, cell_size_y),        # North (1)
        (-1, 1, np.sqrt(cell_size_x**2 + cell_size_y**2)), # NE (2)
        (0, 1, cell_size_x),         # East (4)
        (1, 1, np.sqrt(cell_size_x**2 + cell_size_y**2)),  # SE (8)
        (1, 0, cell_size_y),         # South (16)
        (1, -1, np.sqrt(cell_size_x**2 + cell_size_y**2)), # SW (32)
        (0, -1, cell_size_x),        # West (64)
        (-1, -1, np.sqrt(cell_size_x**2 + cell_size_y**2)) # NW (128)
    ]

    flow_dir = np.zeros((n_rows, n_cols), dtype=int)
    downstream_target = {}

    for r in range(n_rows):
        for c in range(n_cols):
            max_drop_grad = -1.0
            best_target = None
            code = 0
            for idx, (dr, dc, dist) in enumerate(neighbors):
                nr, nc = r + dr, c + dc
                if 0 <= nr < n_rows and 0 <= nc < n_cols:
                    drop = dem[r, c] - dem[nr, nc]
                    grad = drop / dist
                    if grad > max_drop_grad:
                        max_drop_grad = grad
                        best_target = (nr, nc)
                        code = 1 << idx
            if best_target and max_drop_grad > 0:
                flow_dir[r, c] = code
                downstream_target[(r, c)] = best_target

    # Compute Flow Accumulation
    flow_acc = np.ones((n_rows, n_cols), dtype=float)
    cell_coords = [(r, c) for r in range(n_rows) for c in range(n_cols)]
    cell_coords.sort(key=lambda item: dem[item[0], item[1]], reverse=True)

    for r, c in cell_coords:
        if (r, c) in downstream_target:
            nr, nc = downstream_target[(r, c)]
            flow_acc[nr, nc] += flow_acc[r, c]

    # Normalize metrics for Pond Suitability Index (PSI)
    min_z, max_z = np.min(dem), np.max(dem)
    z_range = max_z - min_z if max_z > min_z else 1.0
    norm_z = (dem - min_z) / z_range

    max_fa = np.max(flow_acc)
    norm_fa = flow_acc / (max_fa if max_fa > 0 else 1.0)
    max_slope = np.max(slope_deg)
    norm_slope = slope_deg / (max_slope if max_slope > 0 else 1.0)

    # Pond Suitability Index Grid
    # Favor high flow accumulation, low elevation, and gentle slope
    psi = 0.50 * norm_fa + 0.35 * (1.0 - norm_z) + 0.15 * (1.0 - norm_slope)

    # River Channel Exclusion Filter:
    # Major river trunks (top 3% highest flow accumulation) are active river beds.
    # Farm ponds should be built on farm field tributaries/depressions, not inside the active river.
    river_threshold = np.percentile(flow_acc, 97)
    is_river = flow_acc >= river_threshold
    psi[is_river] *= 0.3  # Penalize active river trunk channels

    # Zero out outer borders
    border = 4
    psi[0:border, :] = 0
    psi[-border:, :] = 0
    psi[:, 0:border] = 0
    psi[:, -border:] = 0

    # Build inverse flow adjacency graph for upstream catchment tracing
    upstream_map = {}
    for src, dst in downstream_target.items():
        upstream_map.setdefault(dst, []).append(src)

    # Detect Local Maxima in PSI (Spatially separated candidate pond sites)
    local_max = maximum_filter(psi, size=15)
    is_local_max = (psi == local_max) & (psi > 0.20)

    peak_coords = np.argwhere(is_local_max)
    # Sort peaks by PSI score descending
    peak_coords = sorted(peak_coords, key=lambda rc: psi[rc[0], rc[1]], reverse=True)

    # Enforce minimum distance separation (at least 20 grid cells / ~400 meters)
    selected_peaks = []
    min_dist_cells = 18

    for r, c in peak_coords:
        is_far = True
        for pr, pc in selected_peaks:
            dist_sq = (r - pr)**2 + (c - pc)**2
            if dist_sq < min_dist_cells**2:
                is_far = False
                break
        if is_far:
            selected_peaks.append((r, c))
        if len(selected_peaks) >= max_candidate_ponds:
            break

    if not selected_peaks:
        best_idx = np.unravel_index(np.argmax(psi), psi.shape)
        selected_peaks = [(best_idx[0], best_idx[1])]

    # Color palette for candidate catchments
    colors = ['#10B981', '#06B6D4', '#8B5CF6', '#F59E0B', '#EC4899']

    candidate_results = []
    geojson_features = []

    for rank, (pond_r, pond_c) in enumerate(selected_peaks, start=1):
        pond_lon = float(grid_x[pond_c])
        pond_lat = float(grid_y[pond_r])
        pond_elev = float(dem[pond_r, pond_c])
        suitability_pct = round(float(psi[pond_r, pond_c]) * 100, 1)
        slope_val = round(float(slope_deg[pond_r, pond_c]), 2)

        # Delineate Upstream Catchment for this candidate pond
        catchment_cells = set()
        stack = [(pond_r, pond_c)]
        while stack:
            curr = stack.pop()
            if curr not in catchment_cells:
                catchment_cells.add(curr)
                if curr in upstream_map:
                    stack.extend(upstream_map[curr])

        catchment_area_m2 = len(catchment_cells) * cell_area_m2
        catchment_area_ha = catchment_area_m2 / 10000.0
        catchment_area_acres = catchment_area_m2 / 4046.86

        # Catchment Boundary Polygon
        catchment_pts = np.array([[grid_x[c], grid_y[r]] for r, c in catchment_cells])
        boundary_coordinates = []
        if len(catchment_pts) >= 4:
            try:
                hull = ConvexHull(catchment_pts)
                boundary_pts = catchment_pts[hull.vertices]
                boundary_coordinates = [[float(pt[0]), float(pt[1])] for pt in boundary_pts]
                boundary_coordinates.append(boundary_coordinates[0])  # Close ring
            except Exception:
                boundary_coordinates = [[float(pt[0]), float(pt[1])] for pt in catchment_pts[:20]]
        else:
            boundary_coordinates = [[float(pt[0]), float(pt[1])] for pt in catchment_pts]

        # Hydrological Runoff & Sizing
        rainfall_m = 0.85
        runoff_coef = 0.35
        annual_runoff_m3 = catchment_area_m2 * rainfall_m * runoff_coef
        annual_runoff_liters = annual_runoff_m3 * 1000.0
        recommended_pond_depth_m = 3.5
        target_capacity_m3 = min(annual_runoff_m3 * 0.18, 25000.0)
        pond_surface_area_m2 = target_capacity_m3 / recommended_pond_depth_m
        side_len_m = math.sqrt(pond_surface_area_m2)

        color_hex = colors[(rank - 1) % len(colors)]

        candidate_obj = {
            'rank': rank,
            'is_primary': (rank == 1),
            'pond_location': {
                'latitude': round(pond_lat, 6),
                'longitude': round(pond_lon, 6),
                'elevation_m': round(pond_elev, 2),
                'suitability_score_pct': suitability_pct,
                'terrain_slope_deg': slope_val,
                'grid_row': int(pond_r),
                'grid_col': int(pond_c)
            },
            'catchment_summary': {
                'area_m2': round(catchment_area_m2, 2),
                'area_hectares': round(catchment_area_ha, 2),
                'area_acres': round(catchment_area_acres, 2),
                'contributing_cells': len(catchment_cells)
            },
            'water_harvesting_estimates': {
                'assumed_annual_rainfall_mm': 850,
                'runoff_coefficient_C': runoff_coef,
                'estimated_annual_runoff_m3': round(annual_runoff_m3, 2),
                'estimated_annual_runoff_liters': round(annual_runoff_liters, 0),
                'recommended_pond_capacity_m3': round(target_capacity_m3, 2),
                'recommended_pond_depth_m': recommended_pond_depth_m,
                'recommended_pond_surface_area_m2': round(pond_surface_area_m2, 2),
                'recommended_dimensions_m': f"{round(side_len_m, 1)}m x {round(side_len_m, 1)}m"
            },
            'color': color_hex
        }

        candidate_results.append(candidate_obj)

        # GeoJSON Features
        geojson_features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [round(pond_lon, 6), round(pond_lat, 6)]
            },
            'properties': {
                'rank': rank,
                'name': f"Pond Site Candidate #{rank}",
                'elevation_m': round(pond_elev, 2),
                'suitability_score': suitability_pct,
                'area_ha': round(catchment_area_ha, 2),
                'color': color_hex
            }
        })

        geojson_features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [boundary_coordinates]
            },
            'properties': {
                'rank': rank,
                'name': f"Catchment Basin #{rank}",
                'area_ha': round(catchment_area_ha, 2),
                'area_m2': round(catchment_area_m2, 2),
                'color': color_hex
            }
        })

    # Primary Top 1 Pond Site
    primary = candidate_results[0]

    return {
        'pond_location': primary['pond_location'],
        'catchment_summary': primary['catchment_summary'],
        'water_harvesting_estimates': primary['water_harvesting_estimates'],
        'total_catchments_detected': len(candidate_results),
        'all_candidate_sites': candidate_results,
        'terrain_statistics': {
            'min_elevation_m': round(float(min_z), 2),
            'max_elevation_m': round(float(max_z), 2),
            'elevation_range_m': round(float(z_range), 2),
            'avg_slope_deg': round(float(np.mean(slope_deg)), 2),
            'map_width_meters': round(width_m, 1),
            'map_height_meters': round(height_m, 1),
            'grid_resolution': f"{n_cols} x {n_rows}"
        },
        'geojson_layers': {
            'type': 'FeatureCollection',
            'features': geojson_features
        }
    }

if __name__ == '__main__':
    from kml_parser import parse_kml_or_kmz
    data = parse_kml_or_kmz('contours_1m.kml')
    analysis = analyze_terrain_and_catchment(data)
    print("Detected catchments count:", analysis['total_catchments_detected'])
    for c in analysis['all_candidate_sites']:
        print(f"Rank {c['rank']}: Area {c['catchment_summary']['area_hectares']} ha, Coords: {c['pond_location']['latitude']}, {c['pond_location']['longitude']}, Score: {c['pond_location']['suitability_score_pct']}%")
