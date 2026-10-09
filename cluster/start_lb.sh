#!/bin/bash
# Start the load balancer on Sys1.  Usage: bash start_lb.sh <lb-port> <backends-csv> <max-inflight>
LB_PORT=${1:-5000}
BACKENDS=${2:-http://127.0.0.1:5002,http://172.17.0.39:5002,http://172.17.0.40:5002,http://172.17.0.41:5002}
MAXIN=${3:-4}
cd "$HOME/pond/cluster" || exit 1
chmod +x pond_lb
pkill -f "pond_lb" 2>/dev/null
# free the port if the Phase-1 app is still holding it
(command -v fuser >/dev/null && fuser -k ${LB_PORT}/tcp) >/dev/null 2>&1
ss -tlnp "sport = :$LB_PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | xargs -r kill -9 2>/dev/null || true
sleep 1
setsid ./pond_lb -port "$LB_PORT" -backends "$BACKENDS" -max-inflight "$MAXIN" \
      -queue-timeout 15s -health-interval 2s </dev/null > "$HOME/pond/lb.log" 2>&1 &
sleep 3
curl -s -m 3 "http://127.0.0.1:$LB_PORT/lb/stats" && echo && echo "[LB] running on :$LB_PORT" \
  || { echo "[LB] FAILED"; tail -20 "$HOME/pond/lb.log"; exit 1; }
