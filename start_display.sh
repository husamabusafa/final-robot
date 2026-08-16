#!/bin/bash
# Launches a dedicated Chrome window in app mode with web security
# disabled, so ALL sites (even those with X-Frame-Options) load inside
# the iframe.  Switching between videos/sites is instant.
#
# Close Chrome first (this uses a separate profile so your normal
# browsing is unaffected).

cd "$(dirname "$0")"

# Kill any existing display Chrome instance
pkill -f "display-chrome-profile" 2>/dev/null
sleep 0.5

# Launch Chrome in app mode pointing at display.html
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir=/tmp/display-chrome-profile \
  --disable-web-security \
  --disable-features=IsolateOrigins,site-per-process \
  --autoplay-policy=no-user-gesture-required \
  --app="http://localhost:3000/display.html" \
  --window-size=1920,1080 &

# Start the local HTTP server in the background
python3 -m http.server 3000 &
HTTP_PID=$!

echo "Display running on http://localhost:3000/display.html"
echo "Press Ctrl+C to stop"
wait $HTTP_PID
