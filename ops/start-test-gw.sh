#!/bin/bash
# Test gateway start script — source API keys from current environment
cd /opt/pjsk-astrbot/test-gateway

# Pull API keys from the running AstrBot process
ASTRO_PID=$(pgrep -f 'bot.py' | head -1)
if [ -n "$ASTRO_PID" ] && [ -f "/proc/$ASTRO_PID/environ" ]; then
    eval "$(cat /proc/$ASTRO_PID/environ | tr '\0' '\n' | grep -E '^(GEMINI|ZHIPU|STEPFUN|DASHSCOPE)_API_KEY=' | sed 's/^/export /')"
fi

# Override with manually set env vars if any
export ONEBOT_ACCESS_TOKEN="${ONEBOT_ACCESS_TOKEN:-pjsk-test-20260716}"
export TEST_QQ_ALLOWLIST="${TEST_QQ_ALLOWLIST:-3366463190}"

echo "Starting gateway with engines:"
env | grep -i 'api_key' | awk -F= '{print "  " $1 ": SET"}'

/usr/bin/python3 gateway/bot.py
