#!/bin/bash
cd /opt/pjsk-astrbot/test-gateway
export ONEBOT_ACCESS_TOKEN=pjsk-test-20260716
export TEST_QQ_ALLOWLIST=3366463190
export PATH=/root/.local/bin:/usr/bin:/bin
python gateway/bot.py
