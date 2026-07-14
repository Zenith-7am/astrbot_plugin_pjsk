#!/usr/bin/env bash
# Deploy PJSK Render Service to HK VPS (154.37.219.8)
# Run from the plugin project root on the VPS.
set -euo pipefail

RELEASE_DIR="/opt/pjsk-astrbot/current"
VENV="${RELEASE_DIR}/.venv"
RENDER_DIR="${RELEASE_DIR}/render_service"

echo "=== 1. Install render dependencies ==="
"${VENV}/bin/pip" install ".[render]"

echo "=== 2. Install Chromium for Playwright ==="
"${VENV}/bin/playwright" install chromium

echo "=== 3. Verify Chromium works ==="
"${VENV}/bin/python" -c "
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
b = p.chromium.launch(headless=True)
print('Chromium OK, version:', b.version)
b.close()
p.stop()
"

echo "=== 4. Test render service import ==="
"${VENV}/bin/python" -c "from render_service.main import app; print('FastAPI app OK:', app.title)"

echo "=== 5. Quick-start render service (manual test) ==="
echo "Starting on 127.0.0.1:3000 for 5 seconds..."
RENDER_HOST=127.0.0.1 RENDER_PORT=3000 \
  "${VENV}/bin/python" -m uvicorn render_service.main:app \
  --host 127.0.0.1 --port 3000 &
PID=$!
sleep 3

echo "=== 6. Health check ==="
curl -s http://127.0.0.1:3000/health | python -m json.tool

echo "=== 7. Stop test instance ==="
kill $PID 2>/dev/null || true

echo ""
echo "=== Manual steps remaining ==="
echo "1. Install systemd unit:"
echo "   sudo cp ops/pjsk-renderer.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable --now pjsk-renderer"
echo "   sudo systemctl status pjsk-renderer"
echo ""
echo "2. Configure plugin (set in config):"
echo "   render_service_url: http://127.0.0.1:3000"
echo "   jacket_cache_dir: /var/cache/pjsk/jackets"
echo ""
echo "3. Test: /pjsk b20 in QQ"
echo ""
echo "4. Rollback: set render_service_url to \"\" and restart plugin"
