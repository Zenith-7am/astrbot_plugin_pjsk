#!/bin/bash
set -e
TEST_DIR=/opt/pjsk-astrbot/test-gateway

echo "=== Clean and extract ==="
cd $TEST_DIR
rm -rf gateway pjsk_core pjsk_emubot pjsk_runtime adapters tests tools ops chart_data render_service pyproject.toml 2>/dev/null
tar xzf /tmp/pjsk-test-gw.tar.gz

echo "=== Check gateway ==="
ls gateway/matchers/

echo "=== Kill old test gateway ==="
pkill -f 'gateway/bot.py' 2>/dev/null || true
sleep 1

echo "=== Read env secrets ==="
source /opt/pjsk-astrbot/shared/bot.env 2>/dev/null || true

echo "=== Start gateway ==="
export ONEBOT_ACCESS_TOKEN="${ONEBOT_ACCESS_TOKEN:-pjsk-test-20260716}"
export TEST_QQ_ALLOWLIST=3366463190
export PATH="/root/.local/bin:$PATH"

cd $TEST_DIR
nohup python gateway/bot.py > /tmp/pjsk-gateway-test.log 2>&1 &
PID=$!
echo "Gateway PID: $PID"
sleep 3
echo "=== Log tail ==="
tail -30 /tmp/pjsk-gateway-test.log
