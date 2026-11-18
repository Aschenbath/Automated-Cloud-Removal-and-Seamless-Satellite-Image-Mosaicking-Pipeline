#!/bin/bash
# Record the 30-second backup demo video: media/cloudpeel_demo.mp4
# Needs Google Chrome, Node 22+ and macOS (for the Swift encoder). Uses ports 8790 and 9333.
set -euo pipefail
cd "$(dirname "$0")/.."
WORK=$(mktemp -d)
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

python3 -m http.server 8790 --bind 127.0.0.1 -d site >/dev/null 2>&1 &
SERVER=$!
"$CHROME" --headless=new --remote-debugging-port=9333 --user-data-dir="$WORK/profile" \
  --hide-scrollbars --window-size=1280,720 about:blank >/dev/null 2>&1 &
BROWSER=$!
trap 'kill $SERVER $BROWSER 2>/dev/null || true; rm -rf "$WORK"' EXIT
sleep 3

node tools/record_demo.mjs "http://127.0.0.1:8790/" "$WORK/frames"
mkdir -p media
swift tools/encode_mp4.swift "$WORK/frames" media/cloudpeel_demo.mp4
