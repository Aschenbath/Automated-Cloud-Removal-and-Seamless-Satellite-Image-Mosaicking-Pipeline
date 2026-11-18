#!/bin/bash
# Double-click to run CloudPeel on this Mac. Close the window to stop it.
cd "$(dirname "$0")" || exit 1
PORT=8765
while lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; do PORT=$((PORT + 1)); done
echo "CloudPeel is running at http://localhost:$PORT"
echo "Close this window (or press Ctrl+C) to stop it."
(sleep 1; open "http://localhost:$PORT") &
exec python3 -m http.server "$PORT" --bind 127.0.0.1 -d site
