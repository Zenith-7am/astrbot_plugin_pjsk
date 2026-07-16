#!/bin/bash
# Deploy test gateway code to HK VPS and start it
set -euo pipefail

VPS="root@154.37.219.8"
TEST_DIR="/opt/pjsk-astrbot/test-gateway"
LOCAL_SRC="d:/pjsk-astrbot/.worktrees/foundation-scaffold"

# Step 1: Package local source
echo "=== Packaging source ==="
cd "$LOCAL_SRC"
tar czf /tmp/pjsk-test-gateway.tar.gz \
    --exclude='.venv' --exclude='.git' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='.pytest_cache' --exclude='.worktrees' \
    --exclude='node_modules' --exclude='data' \
    .

# Step 2: Upload to VPS
echo "=== Uploading to VPS ==="
scp /tmp/pjsk-test-gateway.tar.gz "$VPS:/tmp/"

# Step 3: Extract on VPS and start gateway
echo "=== Extracting and starting ==="
ssh "$VPS" bash -lc "
    set -euo pipefail
    cd $TEST_DIR
    rm -rf gateway pjsk_core pjsk_emubot pjsk_runtime adapters tests tools ops chart_data render_service pyproject.toml
    tar xzf /tmp/pjsk-test-gateway.tar.gz

    # Kill old test gateway if running
    pkill -f 'gateway/bot.py' 2>/dev/null || true
    sleep 1

    # Set env
    export ONEBOT_ACCESS_TOKEN='pjsk-test-20260716'
    export TEST_QQ_ALLOWLIST='3366463190'
    export GEMINI_API_KEY='\$(grep GEMINI_API_KEY /opt/pjsk-astrbot/shared/bot.env 2>/dev/null | cut -d= -f2 || echo '')'
    export ZHIPU_API_KEY='\$(grep ZHIPU_API_KEY /opt/pjsk-astrbot/shared/bot.env 2>/dev/null | cut -d= -f2 || echo '')'
    export DASHSCOPE_API_KEY='\$(grep DASHSCOPE_API_KEY /opt/pjsk-astrbot/shared/bot.env 2>/dev/null | cut -d= -f2 || echo '')'

    # Use uv's Python
    export PATH=\"/root/.local/bin:\$PATH\"

    nohup python gateway/bot.py > /tmp/pjsk-gateway-test.log 2>&1 &
    echo \"Gateway PID: \$!\"
    sleep 2
    tail -20 /tmp/pjsk-gateway-test.log
"
