# Legacy Production Baseline

> **Status: 3A-1 Complete.** 3A-2 (freeze archive) requires separate approval.
>
> Generated from read-only audit of `D:\emu-bot` (local Git) and `/opt/pjsk-emu-bot` (VPS live).
> Audit date: 2026-07-16. No production writes performed.

---

## 1. Local Repository Snapshot

- **Path**: `D:\emu-bot`
- **Git HEAD**: `a0821a1` — "docs: plan Phoebe pet production"
- **Git branch**: `feat/astrobot-chat-opt`
- **Worktree**: **DIRTY** — ~150+ staged deletions under `_archive/ocr_train/` (not relevant to runtime)
- **File count**: 83 `.py` files, 7 `.json` files, 3 `.db` files (codegraph, backup, data)
- **Test files**: 25
- **Snapshot date**: 2026-07-16

### Local-only (Git has, VPS does not)

- `src/core/throttle.py` — referenced by `_common.py`/`api.py` but conditionally imported; fail-safe handles missing module

### Local-missing (VPS has, Git does not)

| File | Classification |
|------|---------------|
| `src/core/player_class.py` | LIVE_ORPHAN — imported by `handler_b20.py` |
| `src/core/qq_gateway.py` | NO_STATIC_REFERENCE |
| `src/data/identity.py` | LIVE_ORPHAN — imported by `handler_register.py` |

---

## 2. VPS Live Snapshot

- **Host**: RainYun-p9Th9FEh (154.37.219.8)
- **Service**: `pjsk-emu-bot.service` — **active** (running), **enabled**
- **ExecStart**: `/usr/bin/python3 bot.py`
- **WorkingDirectory**: `/opt/pjsk-emu-bot`
- **User**: root
- **Restart**: on-failure (RestartSec=5)
- **Python**: 3.11.2 (system python3)
- **File count**: 60 `.py` files (vs 83 in local Git)
- **Snapshot date**: 2026-07-16

### Database Schema (7 tables)

```sql
users(qq_id TEXT PK, game_id TEXT, created_at INTEGER, updated_at INTEGER,
      b20_cache_path TEXT, a39_cache_path TEXT, append_excluded INTEGER DEFAULT 1)
scores(id INTEGER PK AUTOINCREMENT, game_id TEXT, song_id INTEGER, difficulty TEXT,
       perfect INTEGER, great INTEGER, good INTEGER, bad INTEGER, miss INTEGER,
       accuracy REAL, power REAL, uploaded_at INTEGER)
score_history(id INTEGER PK AUTOINCREMENT, game_id TEXT, song_id INTEGER,
              difficulty TEXT, perfect INTEGER, great INTEGER, good INTEGER,
              bad INTEGER, miss INTEGER, accuracy REAL, power REAL, uploaded_at INTEGER)
songs(id INTEGER PK, title_ja TEXT, title_cn TEXT, title_en TEXT, aliases TEXT DEFAULT '[]')
song_difficulties(song_id INTEGER, difficulty TEXT, note_count INTEGER, constant REAL,
                  const_tag TEXT, PK(song_id, difficulty))
ocr_records(id INTEGER PK AUTOINCREMENT, qq_id TEXT, ocr_lines TEXT, created_at INTEGER)
openid_map(openid TEXT PK, qq_id TEXT NOT NULL UNIQUE, group_openid TEXT,
           bound_at INTEGER, last_seen_at INTEGER)
```

**Known issue**: `scores.game_id` stores QQ number, not game ID (misnamed field).

### Journal Activity

- **Date range**: `2026-07-16T19:13:07` (narrow — limited retention)
- **Module distribution**: `src/core/connection_monitor` — 4,981 hits (essentially all entries)
- **Last substantive activity**: Jul 14 `OneBot V11 WebSocket closed by peer`
- **OneBot connection**: `GET /health/napcat` returned `online:false, last_heartbeat_ago:~180217s` (unverified against NapCat logs — marked **unknown**)

---

## 3. Git↔VPS Drift Matrix

### 3.1 Summary

| Category | Count |
|----------|-------|
| ALIGNED (identical SHA-256) | 27 |
| DRIFT (different SHA-256) | 8 |
| GIT_ONLY (in Git, not on VPS) | 1 |
| VPS_ONLY (on VPS, not in Git) | 3 (in src/) + N (root scripts, data/astrobot/) |

### 3.2 DRIFT Files

| File | Git SHA-256 | VPS SHA-256 | Notes |
|------|-------------|-------------|-------|
| `src/core/api.py` | `686e8b0c` | `1740fce9` | Throttle wiring or API key handling differs |
| `src/core/config.py` | `26c95c40` | `434c763a` | Paths/env vars differ (expected — dev vs prod) |
| `src/features/_common.py` | `5165cfa9` | `0b70d14f` | Reply/image path differs |
| `src/features/zhipu_ocr.py` | `baae59de` | `c9b8b10a` | API endpoint or model differs |
| `src/features/gemini_ocr.py` | `c43d9103` | `559784d1` | API endpoint or model differs |
| `src/data/redis_store.py` | `9679519d` | `a9c825a5` | Redis config or key prefix differs |
| `bot.py` | `28a59aa5` | `00265e32` | Entry point differs |
| `requirements.txt` | `bd0f7fd1` | `94b493ac` | Dependency list differs |

### 3.3 LIVE_ORPHAN Files (Production Depends on These)

| File | VPS SHA-256 | Imported by | Risk if Missing |
|------|-------------|-------------|-----------------|
| `src/core/player_class.py` | `153d5506` | `handler_b20.py` | B20 command crashes |
| `src/data/identity.py` | `12057a24` | `handler_register.py` | Registration crashes |

### 3.4 NO_STATIC_REFERENCE Files (No Known Static Importers)

| File | VPS SHA-256 | Notes |
|------|-------------|-------|
| `src/core/qq_gateway.py` | `b926dae2` | May be dynamically imported or dead code |
| `src/features/stepfun_ocr.py` | `abf4b3ff` | Present on VPS, missing from local Git (DRIFT+VPS_ONLY hybrid) |

### 3.5 Root-Level VPS-Only Scripts

`add_song.py`, `fetch_songs.py`, `fix_vps_constants.py`, `migrate_new_songs.py`, `verify_fix.py`, `__init__.py` (root), `data/ocr_engine.py`, `data/astrobot/*.py` — present on VPS, not in local Git `src/` tree.

---

## 4. Command and Feature Summary

> Detailed inventory in [LEGACY-FEATURE-MATRIX.md](LEGACY-FEATURE-MATRIX.md).

### 4.1 User-Facing Commands (from `parse_command` keyword list)

| Keyword | Handler | Priority |
|---------|---------|----------|
| `帮助` / `help` | `handler_help.py` | 1 |
| `批量` | `handler_batch.py` | 4 |
| `别名` | `handler_alias.py` | 5 |
| `注册` | `handler_register.py` | 6 |
| `查b20` / `b20` | `handler_b20.py` | 8 |
| `查分` | `handler_ocr.py` (score query) | 9 |
| `难度排行` | `handler_difficulty.py` | 8 |
| `我的` | `handler_difficulty.py` (personal) | 8 |
| `append` | `handler_append.py` | 8 |
| (chat) | `handler_chat.py` | — |

### 4.2 Image Trigger Flow

1. `image_listener` (priority 7): Catches ALL images, pushes URL to Redis `pending_images` with 15s TTL
2. `ocr_cmd` (priority 9): On `查分` command, pops pending images from Redis by QQ ID
3. If image found → download → OCR race → song match → judge parse → score card render
4. Candidate disagreement → push to Redis `pending_select`, wait for numeric confirmation

### 4.3 Reply Types

- **Text only**: help, register, append
- **Image (base64)**: B20, difficulty ranking, OCR score card
- **Image (CDN URL)**: `reply_image()` path (not the primary OCR reply path)
- **Multi-segment**: batch results, candidate lists

---

## 5. Rollback Eligibility Assessment

### 5.1 Git Reproducibility

**Can the VPS state be reproduced from current Git HEAD?** — **NO**

Evidence:
- **2 LIVE_ORPHAN files** (player_class.py, identity.py) — production depends on unversioned files
- **8 DRIFT files** — Git has the files but content differs from VPS
- **1 GIT_ONLY file** (throttle.py) — not present on VPS
- Worktree is dirty (staged deletions in `_archive/`)

### 5.2 Import Soundness

Not tested at runtime (static AST only — no `importlib.import_module()` per safety rules). Static import resolution of critical-path files showed all imports from `src/` resolve to existing `.py` files on VPS (including LIVE_ORPHAN files).

### 5.3 Eligibility Verdict

- **Eligible as formal rollback candidate?** — **NO**
- **Conditions to meet before eligibility**:
  1. Complete 3A-2 freeze archive (tarball + manifest + baseline ID)
  2. Resolve the 8 DRIFT files — reconcile VPS version vs Git version
  3. Commit LIVE_ORPHAN files to Git or document their origin
  4. Isolated smoke test proving old bot starts without NapCat and serves health endpoint
  5. Dependency version lock (current pip freeze shows 100+ packages, no lock file)
- **Current status**: **NOT_ELIGIBLE** — freeze baseline incomplete.
  Do NOT reference this bot as a rollback target in deployment scripts.

---

## 6. Completeness Self-Assessment

### Covered
- [x] Local Git state
- [x] VPS live filesystem
- [x] Git↔VPS drift matrix
- [x] Orphan classification (LIVE_ORPHAN / NO_STATIC_REFERENCE)
- [x] Command inventory
- [x] Image trigger flow
- [x] Candidate confirmation flow
- [x] Reply type classification
- [x] Rollback eligibility
- [x] Database schema (read-only, no user data)
- [x] Journal aggregates (no raw log output)

### Not Covered (Out of Scope for 3A-1)
- Database row counts and user statistics (requires SELECT — PII risk)
- Runtime performance profiling
- NapCat configuration (on China VPS, not accessible)
- Redis data inspection
- Old OCR model weights or training data
- Non-Python files (system scripts, cron jobs outside `/opt/pjsk-emu-bot`)

### Unknowns (Require Further Investigation)
- `qq_gateway.py` — NO_STATIC_REFERENCE; may be dynamic import or dead code
- `stepfun_ocr.py` — VPS_ONLY, not in local Git; may be dynamically imported
- Exact OneBot connection status — health endpoint reports offline, NapCat logs not checked
- `data/astrobot/*` — appears to be an Astrobot chat integration layer; relationship to main bot unknown
- Exact diff content of 8 DRIFT files — only SHA-256 compared, not content

---

## 7. Phase 3A-2 Approval Gate

**3A-1 is now complete.** The following data has been collected without any production writes:

- File manifests (local + VPS)
- Drift matrix (8 DRIFT, 2 LIVE_ORPHAN)
- Command and feature inventory
- Orphan classification
- Rollback eligibility assessment (NOT_ELIGIBLE)
- Database schema (7 tables)
- Journal aggregates (connection_monitor-dominated)

**3A-2 (Freeze Archive) requires separate human authorization.**

3A-2 will:
- Create a tarball of `/opt/pjsk-emu-bot` on the VPS (excluding .env, *.db, __pycache__, logs/)
- Generate `source-manifest.sha256` and `dependency-manifest.txt`
- Copy the archive to a secure audit location
- Assign a legacy baseline ID

3A-2 will NOT:
- Stop, restart, or modify any service
- Modify any file under `/opt/pjsk-emu-bot`
- Read or copy `.env`, `bot.env`, or database files
- Install or remove packages

**Do NOT proceed to 3A-2 without explicit user approval.**
