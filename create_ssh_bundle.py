import os
import base64

project_dir = os.path.dirname(__file__)

files_to_bundle = [
    'kml_parser.py',
    'terrain_analyzer.py',
    'app.py',
    'templates/index.html',
    'static/style.css',
    'static/app.js'
]

kml_file = 'contours_1m.kml'

out_sh = os.path.join(project_dir, 'setup_pond_catchment.sh')

with open(out_sh, 'w', encoding='utf-8') as out:
    out.write("#!/bin/bash\n")
    out.write("# Setup script for Pond Catchment Analysis API on Sys1 SSH Server\n\n")
    out.write("echo '=================================================='\n")
    out.write("echo '  Deploying Pond Catchment API on SSH Server...'\n")
    out.write("echo '=================================================='\n\n")
    out.write("mkdir -p ~/Pond_catchment/templates ~/Pond_catchment/static\n")
    out.write("cd ~/Pond_catchment\n\n")

    out.write("echo 'Installing Python dependencies (flask, flask-cors, numpy, scipy)...'\n")
    out.write("pip install flask flask-cors numpy scipy shapely pykml --quiet 2>/dev/null || python3 -m pip install flask flask-cors numpy scipy --quiet\n\n")

    for rel_path in files_to_bundle:
        full_path = os.path.join(project_dir, rel_path)
        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            out.write(f"cat << 'EOF' > ~/Pond_catchment/{rel_path}\n")
            out.write(content)
            if not content.endswith('\n'):
                out.write('\n')
            out.write("EOF\n\n")

    # Encode KML file as base64 to handle large size and special chars cleanly
    kml_full_path = os.path.join(project_dir, kml_file)
    if os.path.exists(kml_full_path):
        with open(kml_full_path, 'rb') as kf:
            b64_kml = base64.b64encode(kf.read()).decode('ascii')
        out.write("echo 'Extracting contours_1m.kml sample file...'\n")
        out.write("cat << 'EOF_KML_B64' | base64 -d > ~/Pond_catchment/contours_1m.kml\n")
        out.write(b64_kml)
        out.write("\nEOF_KML_B64\n\n")

    out.write("echo '=================================================='\n")
    out.write("echo '  Setup Complete! Starting Pond Catchment API...'\n")
    out.write("echo '  Listening on: http://0.0.0.0:5050'\n")
    out.write("echo '=================================================='\n\n")
    out.write("python3 ~/Pond_catchment/app.py\n")

print(f"Generated bundle script: {out_sh}")
