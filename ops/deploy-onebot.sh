#!/bin/bash
# Atomic deploy for PJSK OneBot Gateway (production only).
#
# Usage: ops/deploy-onebot.sh
#
# Reads the project root from the caller's cwd (must be the repo root).
# Uploads a clean tarball to HK VPS, builds a new immutable release in
# /opt/pjsk-astrbot/releases/<release_id>/, preflights it on a temporary
# port, atomically switches /opt/pjsk-astrbot/current, restarts
# pjsk-onebot.service, and runs health checks.
#
# On failure the script auto-rolls-back current to the previous release
# (service restart + health check).  Database is NEVER rolled back.
#
# This script NEVER uses rm -rf on production directories.
# It does NOT reuse test-gateway scripts.
set -euo pipefail

VPS="${VPS_HOST:-root@154.37.219.8}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE_BASE="/opt/pjsk-astrbot/releases"
CURRENT_LINK="/opt/pjsk-astrbot/current"
SHARED_DIR="/opt/pjsk-astrbot/shared"
SERVICE_NAME="pjsk-onebot.service"
PREFLIGHT_PORT=19999
RELEASE_ID="$(date -u +%Y%m%d-%H%M%S)-$(git -C "$REPO_ROOT" rev-parse --short=7 HEAD)"

# ── Step 0: Check clean git ──────────────────────────────────────────────
if ! git -C "$REPO_ROOT" diff-index --quiet HEAD --; then
    echo "ERROR: git worktree is dirty. Commit or stash changes before deploying." >&2
    exit 1
fi
GIT_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "=== Deploying $RELEASE_ID (git $GIT_SHA) ==="

# ── Step 1: Build and upload release tarball ────────────────────────────
TARBALL="/tmp/pjsk-release-${RELEASE_ID}.tar.gz"
cd "$REPO_ROOT"
# Use git archive to guarantee only tracked files are included.
# Untracked files (artifacts, temp scripts, .venv, etc.) are never packaged.
git archive --format=tar.gz --output="$TARBALL" HEAD
echo "=== Tarball: $(du -h "$TARBALL" | cut -f1) ==="

echo "=== Uploading to VPS ==="
scp "$TARBALL" "$VPS:/tmp/"

# ── Step 2: Build new release on VPS ────────────────────────────────────
ssh "$VPS" bash -lc "
    set -euo pipefail
    RELEASE_DIR='${RELEASE_BASE}/${RELEASE_ID}'
    echo '=== Creating release directory ==='
    mkdir -p \"\$RELEASE_DIR\"

    echo '=== Extracting tarball ==='
    tar xzf '/tmp/pjsk-release-${RELEASE_ID}.tar.gz' -C \"\$RELEASE_DIR\"
    rm '/tmp/pjsk-release-${RELEASE_ID}.tar.gz'

    cd \"\$RELEASE_DIR\"

    # ── Venv (non-editable — no .pth pointer to another release) ───────
    echo '=== Creating venv ==='
    python3 -m venv .venv
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q '.[dev,render]'

    # ── Release manifest ────────────────────────────────────────────
    echo \"git_sha=${GIT_SHA}\" > .release-manifest.txt
    echo \"release_id=${RELEASE_ID}\" >> .release-manifest.txt
    echo \"created_at=\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" >> .release-manifest.txt

    # ── Import check ────────────────────────────────────────────────────
    echo '=== Import check ==='
    .venv/bin/python -c '
import gateway.health
import pjsk_core
import pjsk_runtime
import adapters.database
import render_service.main
print(\"All imports OK\")
'

    # ── Systemd units ─────────────────────────────────────────────────
    echo '=== Installing systemd units ==='
    cp \"\$RELEASE_DIR/ops/pjsk-render.service\" /etc/systemd/system/pjsk-render.service
    cp \"\$RELEASE_DIR/ops/pjsk-onebot.service\" /etc/systemd/system/pjsk-onebot.service
    systemctl daemon-reload

    # ── Chart data import (first-install safe) ─────────────────────────
    echo '=== Chart data import ==='
    .venv/bin/python -c '
from adapters.database.migrator import run_migrations
from tools.import_chart_data import import_chart_data
from pathlib import Path
import asyncio, os

db_path = Path(os.environ.get(\"PJSK_DB_PATH\", \"${SHARED_DIR}/data/pjsk.db\"))
asyncio.run(run_migrations(db_path))
print(f\"Migrations applied to {db_path}\")
'

    # ── Preflight on temp port ─────────────────────────────────────────
    echo '=== Preflight (port ${PREFLIGHT_PORT}) ==='
    .venv/bin/python -m uvicorn render_service.main:app \
        --host 127.0.0.1 --port ${PREFLIGHT_PORT} &
    RENDER_PID=\$!
    sleep 3

    # Verify render service health
    curl -sf http://127.0.0.1:${PREFLIGHT_PORT}/health || {
        echo 'ERROR: render preflight health failed'
        kill \$RENDER_PID 2>/dev/null || true
        exit 1
    }
    kill \$RENDER_PID 2>/dev/null || true
    sleep 1
    echo 'Preflight OK'

    # ── Switch current atomically ──────────────────────────────────────
    echo '=== Atomic switch ==='
    OLD_CURRENT=\$(readlink -f '${CURRENT_LINK}' 2>/dev/null || echo '')

    exec 9>'${SHARED_DIR}/.deploy.lock'
    flock -x 9 || { echo 'ABORT: another deploy in progress'; exit 1; }

    TEMP_LINK='${CURRENT_LINK}.deploying.\$\$'
    ln -s \"\$RELEASE_DIR\" \"\$TEMP_LINK\"
    mv -T \"\$TEMP_LINK\" '${CURRENT_LINK}'

    FINAL=\$(readlink -f '${CURRENT_LINK}')
    if [ \"\$FINAL\" != \"\$RELEASE_DIR\" ]; then
        echo 'ERROR: atomic switch verification failed'
        exec 9>&-
        exit 1
    fi
    echo \"current -> \$FINAL\"
    exec 9>&-

    # Persist OLD_CURRENT into a shared file so the rollback SSH block
    # (which runs in a separate session) can read it.
    echo \"\$OLD_CURRENT\" > '${SHARED_DIR}/.prev-release'
"

# ── Step 3: Restart renderer first, then gateway ────────────────────────
RENDER_SERVICE="pjsk-render.service"
echo "=== Restarting $RENDER_SERVICE ==="
ssh "$VPS" bash -lc "
    set -euo pipefail
    systemctl restart '${RENDER_SERVICE}'
    sleep 3
    # Verify renderer health before restarting gateway
    if ! curl -sf --max-time 5 http://127.0.0.1:3000/health > /dev/null; then
        echo 'ERROR: renderer health check failed — aborting deploy'
        exit 1
    fi
    echo 'Renderer OK'
"

echo "=== Restarting $SERVICE_NAME ==="
ssh "$VPS" bash -lc "
    set -euo pipefail
    systemctl restart '${SERVICE_NAME}'
    sleep 3

    # Health check: up to 3 retries, validate json fields (not just HTTP 200)
    for i in 1 2 3; do
        echo \"Health attempt \$i/3 …\"
        RESP=\$(curl -sf --max-time 5 http://127.0.0.1:8080/health 2>/dev/null || echo '')
        if [ -n \"\$RESP\" ]; then
            echo \"\$RESP\" | python3 -m json.tool 2>/dev/null || echo \"\$RESP\"
            # Verify critical fields are healthy
            STATUS_OK=\$(echo \"\$RESP\" | python3 -c \"import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('status')=='ok' and d.get('database')=='ok' and d.get('runtime')=='ready' else 1)\" 2>/dev/null && echo 1 || echo 0)
            if [ \"\$STATUS_OK\" = \"1\" ]; then
                echo '=== Deploy SUCCESS ==='
                echo \"Release: ${RELEASE_ID}\"
                echo \"Git SHA: ${GIT_SHA}\"
                exit 0
            fi
        fi
        sleep 2
    done

    # ── ROLLBACK ────────────────────────────────────────────────────────
    echo '=== Health check FAILED — rolling back ==='

    # Read the previous release path saved during atomic switch
    OLD_CURRENT=\$(cat '${SHARED_DIR}/.prev-release' 2>/dev/null || echo '')
    if [ -n \"\$OLD_CURRENT\" ] && [ -d \"\$OLD_CURRENT\" ]; then
        ln -snf \"\$OLD_CURRENT\" '${CURRENT_LINK}'
        echo \"Rolled back current -> \$OLD_CURRENT\"
    else
        # Fallback: find latest release that isn't the failed one
        PREV=\$(ls -1d '${RELEASE_BASE}'/*/ 2>/dev/null | grep -v '${RELEASE_ID}' | sort -r | head -1 || echo '')
        if [ -n \"\$PREV\" ]; then
            ln -snf \"\$PREV\" '${CURRENT_LINK}'
            echo \"Rolled back current (fallback) -> \$PREV\"
        else
            echo 'FATAL: no previous release found for rollback'
            exit 1
        fi
    fi

    # Restart BOTH renderer and gateway on rollback
    systemctl restart '${RENDER_SERVICE}' || true
    sleep 2
    systemctl restart '${SERVICE_NAME}'
    sleep 2

    echo '=== Post-rollback health ==='
    curl -s http://127.0.0.1:3000/health || echo 'renderer health failed'
    curl -s http://127.0.0.1:8080/health | python3 -m json.tool || echo 'gateway health failed'
    echo '=== Deploy FAILED — rolled back ==='
    exit 1
"

# Clean up local tarball
rm -f "$TARBALL"
