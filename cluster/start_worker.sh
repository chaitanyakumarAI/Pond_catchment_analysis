#!/bin/bash
# Start one analysis worker node (run on Sys1..Sys4).  Usage: bash start_worker.sh <node-name> [workers]
NODE=${1:-$(hostname)}
PORT=${WORKER_PORT:-5002}
WORKERS=${2:-$(nproc)}
APP_DIR="$HOME/pond"
cd "$APP_DIR" || { echo "missing $APP_DIR"; exit 1; }

echo "[$NODE] cores=$(nproc) mem=$(free -m | awk '/Mem/{print $2}')MB python=$(python3 -V 2>&1)"
python3 -m pip install --user -q -r requirements.txt 2>/dev/null \
  || python3 -m pip install --user -q --break-system-packages -r requirements.txt 2>/dev/null \
  || echo "[$NODE] WARNING: pip install failed — using already-installed packages"
python3 -c "import flask, flask_cors, numpy, scipy, pyproj, shapely, matplotlib" \
  || { echo "[$NODE] ERROR: Python dependencies missing"; exit 2; }

# stop any previous instance (Phase-1 app.py or an older worker)
pkill -f "gunicorn.*app:app" 2>/dev/null
pkill -f "Pond_catchment/app.py" 2>/dev/null
pkill -f "pond/app.py" 2>/dev/null
pkill -f "python3.*app.py" 2>/dev/null
ss -tlnp "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | xargs -r kill -9 2>/dev/null || true
sleep 1
export PATH="$HOME/.local/bin:$PATH"
if python3 -c "import gunicorn" 2>/dev/null; then
  NODE_NAME=$NODE WORKER_PORT=$PORT WORKERS=$WORKERS ACCESS_LOG=/dev/null \
    setsid python3 -m gunicorn -c cluster/gunicorn.conf.py app:app </dev/null > "$APP_DIR/worker.log" 2>&1 &
  MODE="gunicorn x$WORKERS"
else
  NODE_NAME=$NODE PORT=$PORT setsid python3 "$APP_DIR/app.py" </dev/null > "$APP_DIR/worker.log" 2>&1 &
  MODE="flask threaded (gunicorn unavailable)"
fi

for i in $(seq 1 30); do
  if curl -s -m 2 "http://127.0.0.1:$PORT/health" | grep -q healthy; then
    echo "[$NODE] UP on :$PORT ($MODE)"; exit 0
  fi
  sleep 1
done
echo "[$NODE] FAILED to start — last log lines:"; tail -20 "$APP_DIR/worker.log"; exit 3
