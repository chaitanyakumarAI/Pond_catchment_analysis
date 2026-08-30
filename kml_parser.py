import os
import re
import zipfile
import xml.etree.ElementTree as ET
import numpy as np

def parse_kml_or_kmz(file_source):
    """
    Parses a KML file, KMZ file, or file-like object/bytes.
    Dynamically extracts contour lines, elevations, coordinates, and bounding box.
    Returns a dictionary with extracted spatial data.
    """
    kml_content = None

    # Handle file path string or bytes/stream
    if isinstance(file_source, str):
        if file_source.lower().endswith('.kmz'):
            with zipfile.ZipFile(file_source, 'r') as z:
                kml_files = [f for f in z.namelist() if f.lower().endswith('.kml')]
                if not kml_files:
                    raise ValueError("No .kml file found inside the KMZ archive.")
                # Read primary kml file (doc.kml or first kml)
                main_kml = 'doc.kml' if 'doc.kml' in kml_files else kml_files[0]
                kml_content = z.read(main_kml)
        else:
            with open(file_source, 'rb') as f:
                kml_content = f.read()
    elif hasattr(file_source, 'read'):
        content = file_source.read()
        # Check if zip (KMZ signature starts with PK)
        if content.startswith(b'PK\x03\x04'):
            import io
            with zipfile.ZipFile(io.BytesIO(content), 'r') as z:
                kml_files = [f for f in z.namelist() if f.lower().endswith('.kml')]
                if not kml_files:
                    raise ValueError("No .kml file found inside the uploaded KMZ archive.")
                main_kml = 'doc.kml' if 'doc.kml' in kml_files else kml_files[0]
                kml_content = z.read(main_kml)
        else:
            kml_content = content

    if not kml_content:
        raise ValueError("Empty or invalid KML/KMZ input.")

    # Parse XML Tree
    root = ET.fromstring(kml_content)
    
    # KML Namespaces
    ns_map = {
        'kml': 'http://www.opengis.net/kml/2.2',
        'gx': 'http://www.google.com/kml/ext/2.2'
    }

    def find_all_tags(element, tag_name):
        results = []
        for elem in element.iter():
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag.lower() == tag_name.lower():
                results.append(elem)
        return results

    placemarks = find_all_tags(root, 'Placemark')
    
    contours = []
    all_points = []
    elevations = []

    for pm in placemarks:
        # Extract Elevation from Placemark metadata or name
        elev = None
        
        # 1. Try ExtendedData SimpleData
        for sd in find_all_tags(pm, 'SimpleData'):
            name_attr = sd.attrib.get('name', '').lower()
            if name_attr in ['elevation', 'elev', 'height', 'z', 'contour']:
                try:
                    elev = float(sd.text.strip())
                    break
                except (ValueError, AttributeError):
                    pass

        # 2. Try Name tag (e.g. <name>277.0</name>)
        if elev is None:
            name_elems = find_all_tags(pm, 'name')
            if name_elems and name_elems[0].text:
                text = name_elems[0].text.strip()
                # Regex search for floating point elevation number
                match = re.search(r'[-+]?\d*\.\d+|\d+', text)
                if match:
                    try:
                        elev = float(match.group())
                    except ValueError:
                        pass

        # Extract Coordinate Geometries (LineString, Polygon, MultiGeometry)
        coords_elements = find_all_tags(pm, 'coordinates')
        line_coords_list = []

        for ce in coords_elements:
            if not ce.text:
                continue
            raw_pts = ce.text.strip().split()
            pts = []
            for pt in raw_pts:
                parts = pt.split(',')
                if len(parts) >= 2:
                    try:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        z_val = float(parts[2]) if len(parts) >= 3 else (elev if elev is not None else 0.0)
                        pts.append((lon, lat, z_val))
                        all_points.append((lon, lat, z_val))
                    except ValueError:
                        continue
            if pts:
                line_coords_list.append(pts)

        if line_coords_list:
            if elev is not None:
                elevations.append(elev)
            contours.append({
                'elevation': elev if elev is not None else 0.0,
                'lines': line_coords_list
            })

    if not all_points:
        raise ValueError("Could not extract valid coordinates from input KML/KMZ file.")

    pts_arr = np.array(all_points)
    lons = pts_arr[:, 0]
    lats = pts_arr[:, 1]
    zs = pts_arr[:, 2]

    # If elevations were missing in name/ExtendedData, use 3D Z coordinates
    if not elevations and len(zs) > 0:
        elevations = zs.tolist()

    bbox = {
        'min_lon': float(np.min(lons)),
        'max_lon': float(np.max(lons)),
        'min_lat': float(np.min(lats)),
        'max_lat': float(np.max(lats)),
    }

    elevation_stats = {
        'min_elevation_m': float(np.min(zs)) if len(zs) > 0 else (float(np.min(elevations)) if elevations else 0.0),
        'max_elevation_m': float(np.max(zs)) if len(zs) > 0 else (float(np.max(elevations)) if elevations else 0.0),
        'contour_count': len(contours),
        'total_points': len(all_points)
    }

    return {
        'contours': contours,
        'points': pts_arr,  # numpy array of (lon, lat, z)
        'bbox': bbox,
        'elevation_stats': elevation_stats
    }

if __name__ == '__main__':
    res = parse_kml_or_kmz('contours_1m.kml')
    print("Parsing successful!")
    print("Stats:", res['elevation_stats'])
    print("BBox:", res['bbox'])
