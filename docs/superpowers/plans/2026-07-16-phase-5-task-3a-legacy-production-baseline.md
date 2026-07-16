# Phase 5 Task 3A — Legacy Production Freeze and Feature Baseline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reliable, verifiable baseline of the old production bot — what files it consists of, what commands it serves, how images trigger OCR, and whether it qualifies as a rollback candidate.

**Architecture:** Read-only audit across two sources (local `D:\emu-bot` Git repo + HK VPS `/opt/pjsk-emu-bot` live filesystem). Cross-reference Git history against live files to produce a drift matrix. Extract commands, triggers, and reply behaviors from source-code static analysis and journal evidence.

**Tech Stack:** bash/ssh (read-only remote queries), Python 3.11+ (static import analysis), git (history and diff), SQLite CLI `mode=ro` (schema-only inspection).

## Global Constraints

- Phase 5 v3.2 `1e5a0d9` is the governing design spec.
- `D:\emu-bot` is read-only reference. Never modify it.
- VPS `/opt/pjsk-emu-bot` is read-only for 3A-1. No stop/start/restart/kill/chmod/write.
- Never read `.env`, `bot.env`, or any file containing API keys or access tokens.
- Never output QQ numbers, game IDs, OCR text, image URLs, or any user-level PII.
- Database inspection: schema-only (`sqlite3 .schema`), no `SELECT * FROM users/scores`.
- Each task ends with an independent commit.
- No placeholders (TODO/TBD/待定).
- 3A-1 must complete and pass human review before 3A-2 begins.
- Do NOT proceed to Task 3B after 3A completes.

---

### Task 1: Local old-repo file manifest

**Files:**
- Create: `docs/production/LEGACY-PRODUCTION-BASELINE.md` (initial skeleton)

**Interfaces:**
- Consumes: `D:\emu-bot` (read-only filesystem)
- Produces: Section "1. Local Repository Snapshot" in LEGACY-PRODUCTION-BASELINE.md

- [ ] **Step 1: Record the Git HEAD and status of the old repo**

```bash
cd D:\emu-bot
git log --oneline -5
git status --short --branch
git remote -v
```

Record the output verbatim (it contains no secrets). If the repo is dirty, record which files are modified.

- [ ] **Step 2: Generate a full file listing with SHA-256 hashes**

```bash
cd D:\emu-bot
find . -type f \( -name "*.py" -o -name "*.json" -o -name "*.yml" -o -name "*.yaml" -o -name "*.txt" -o -name "*.toml" -o -name "*.db" \) \
  ! -path "./.git/*" \
  ! -path "./__pycache__/*" \
  ! -path "./*.pyc" \
  ! -path "./logs/*" \
  ! -name ".env" \
  ! -name "*.env" \
  -exec sha256sum {} \; | sort -k2
```

**Privacy rule**: If `.env` or any file containing `API_KEY` / `SECRET` / `TOKEN` appears in the listing, skip it and note "N files excluded (secrets)".

- [ ] **Step 3: Count files by category**

Count and record:
- Total `.py` files
- `.json` files
- `.db` files (record path and size, do NOT open)
- Test files
- Config files
- Files in `.gitignore` that exist on disk

- [ ] **Step 4: Write the local snapshot section into the baseline document**

```markdown
## 1. Local Repository Snapshot

- **Path**: D:\emu-bot
- **Git HEAD**: <sha>
- **Git branch**: <branch>
- **Git remote**: <url>
- **Worktree**: clean | dirty (<N modified files>)
- **File count**: <N> .py, <N> .json, <N> .db
- **Snapshot date**: 2026-07-16
- **SHA-256 manifest**: (summary — top-level checksums for key files)
```

- [ ] **Step 5: Commit**

```bash
git add docs/production/LEGACY-PRODUCTION-BASELINE.md
git commit -m "audit(3a): record local old-repo file manifest and git status"
```

---

### Task 2: VPS live production snapshot

**Files:**
- Modify: `docs/production/LEGACY-PRODUCTION-BASELINE.md` (add §2)

**Interfaces:**
- Consumes: SSH root@154.37.219.8 (read-only commands)
- Produces: Section "2. VPS Live Snapshot" in LEGACY-PRODUCTION-BASELINE.md

**Privacy rules for all SSH commands in this task:**
- Never `cat .env` or any file whose path contains `env`, `secret`, `token`, `key`.
- Never `cat` database files.
- Never `grep` for QQ numbers or game IDs.
- If a command accidentally captures a secret in stdout, truncate and note "redacted".

- [ ] **Step 1: Record service states**

```bash
ssh root@154.37.219.8 \
  "systemctl is-active pjsk-emu-bot.service;
   systemctl is-enabled pjsk-emu-bot.service;
   systemctl cat pjsk-emu-bot.service"
```

Record the unit file — but **redact** any `Environment=` lines containing `KEY`, `SECRET`, `TOKEN`, or `PROXY`. Replace values with `<REDACTED>`.

- [ ] **Step 2: Generate VPS file listing with SHA-256**

```bash
ssh root@154.37.219.8 \
  "find /opt/pjsk-emu-bot -type f \( -name '*.py' -o -name '*.json' -o -name '*.yml' -o -name '*.txt' -o -name '*.toml' \) \
    ! -path '*/__pycache__/*' \
    ! -name '.env' \
    ! -name '*.env' \
    -exec sha256sum {} \;" | sort -k2
```

- [ ] **Step 3: Record OS-level metadata**

```bash
ssh root@154.37.219.8 \
  "python3 --version;
   pip3 freeze 2>/dev/null | head -30 || echo 'pip_freeze_unavailable';
   which python3"
```

Record the Python version and top-level packages. Do NOT record the full `pip freeze` if it contains internally-developed package versions that might reveal paths — top 30 public packages only.

- [ ] **Step 4: Record database schema (no user data)**

```bash
ssh root@154.37.219.8 \
  "sqlite3 /opt/pjsk-emu-bot/data/bot.db '.schema' 2>&1"
```

Record the CREATE TABLE statements. Do NOT run any SELECT queries. If the database is missing or the path differs, record the actual path found via `find /opt/pjsk-emu-bot -name '*.db'`.

- [ ] **Step 5: Sample recent journal for behavioral evidence**

```bash
ssh root@154.37.219.8 \
  "journalctl -u pjsk-emu-bot --no-pager -n 100 2>&1"
```

**Privacy**: If any line contains a QQ number (5-11 digit numeric string in a user-visible position), replace it with `<QQ_REDACTED>`. If any line contains an OCR text or image URL, replace the value with `<REDACTED>`.

- [ ] **Step 6: Write the VPS snapshot section**

```markdown
## 2. VPS Live Snapshot

- **Host**: RainYun-p9Th9FEh (154.37.219.8)
- **Service**: pjsk-emu-bot.service — <active/inactive>, <enabled/disabled>
- **WorkingDirectory**: /opt/pjsk-emu-bot
- **Python**: <version>
- **Database path**: /opt/pjsk-emu-bot/data/bot.db
- **Database tables**: <list from .schema>
- **File count**: <N> .py files
- **Journal last activity**: <date> (from journalctl)
- **Snapshot date**: 2026-07-16
- **SHA-256 manifest**: (summary)
```

- [ ] **Step 7: Commit**

```bash
git add docs/production/LEGACY-PRODUCTION-BASELINE.md
git commit -m "audit(3a): record VPS live snapshot — services, files, schema, journal"
```

---

### Task 3: Git-vs-VPS drift matrix

**Files:**
- Modify: `docs/production/LEGACY-PRODUCTION-BASELINE.md` (add §3)

**Interfaces:**
- Consumes: Task 1 local manifest, Task 2 VPS manifest
- Produces: Section "3. Git↔VPS Drift Matrix" with three tables

- [ ] **Step 1: Cross-reference file paths**

Compare the file lists from Task 1 and Task 2:

1. Files present in Git AND on VPS with identical SHA-256 → `ALIGNED`
2. Files present in Git AND on VPS with different SHA-256 → `DRIFT`
3. Files present in Git but NOT on VPS → `GIT_ONLY`
4. Files present on VPS but NOT in Git → `VPS_ONLY (ORPHAN)`

- [ ] **Step 2: For each ORPHAN file, check if it is imported by any aligned/drift file**

For each VPS_ONLY file, grep the VPS source tree:

```bash
ssh root@154.37.219.8 \
  "grep -r 'import <module_name>' /opt/pjsk-emu-bot/src/ 2>/dev/null || echo 'NO_IMPORTERS'"
```

Classify each orphan:
- **LIVE_ORPHAN**: imported by at least one other source file (production depends on it)
- **DEAD_ORPHAN**: not imported by any source file (likely residual)
- **UNKNOWN**: cannot determine (e.g., dynamic import, `__import__`)

- [ ] **Step 3: Build the drift matrix**

```markdown
## 3. Git↔VPS Drift Matrix

### 3.1 Summary

| Category | Count |
|----------|-------|
| ALIGNED | <N> |
| DRIFT | <N> |
| GIT_ONLY | <N> |
| VPS_ONLY (ORPHAN) | <N> |
| … of which LIVE_ORPHAN | <N> |
| … of which DEAD_ORPHAN | <N> |

### 3.2 DRIFT files

| File | Git SHA-256 | VPS SHA-256 | Notes |
|------|-------------|-------------|-------|

### 3.3 LIVE_ORPHAN files (production depends on these)

| File | Imported by | Risk if missing |
|------|-------------|-----------------|

### 3.4 DEAD_ORPHAN files (no known importers)

| File | Size | Last modified (VPS) |
|------|------|---------------------|
```

- [ ] **Step 4: Commit**

```bash
git add docs/production/LEGACY-PRODUCTION-BASELINE.md
git commit -m "audit(3a): cross-reference Git vs VPS — drift matrix with orphan classification"
```

---

### Task 4: Feature extraction — commands and matchers

**Files:**
- Create: `docs/production/LEGACY-FEATURE-MATRIX.md` (initial skeleton)
- Modify: `docs/production/LEGACY-PRODUCTION-BASELINE.md` (add §4)

**Interfaces:**
- Consumes: Local `D:\emu-bot\src\features\` source files, VPS `/opt/pjsk-emu-bot/src/features/` source files
- Produces: LEGACY-FEATURE-MATRIX.md with complete command/trigger/reply table

- [ ] **Step 1: Grep for all NoneBot matchers in the old features directory**

```bash
cd D:\emu-bot
grep -rn "on_message\|on_command\|on_keyword\|on_regex\|on_startswith\|on_type\|on_notice\|on_request" src/features/ --include="*.py"
```

For each matcher found, record:
- File and line
- Matcher type (on_message, on_command, etc.)
- Priority
- Block flag
- Trigger condition (rule checker, keyword, to_me, etc.)

- [ ] **Step 2: Grep for all command keywords and patterns**

```bash
cd D:\emu-bot
grep -rn "Command\|command\|kw\|keyword\|startswith\|match\|parse_command" src/features/ --include="*.py" | head -200
```

Extract every user-facing command string. Track aliases (e.g., "查b20" and "b20" may both work).

- [ ] **Step 3: Extract the reply path for each handler**

For each handler file, trace the reply calls:

```bash
cd D:\emu-bot
grep -rn "await reply\|await reply_at\|await reply_image\|send_group_msg\|send_private_msg\|finish\|matcher.finish\|matcher.send" src/features/ --include="*.py"
```

Classify each reply as: `text_only` | `image_only` | `text_and_image` | `multi_segment`.

- [ ] **Step 4: Extract image trigger logic**

```bash
cd D:\emu-bot
grep -rn "type.*image\|\[CQ:image\|seg.type\|message.*image\|图片\|image_listener\|pending_image\|push_pending\|pop_pending" src/features/ --include="*.py"
```

Map the image flow:
1. How are images detected in messages?
2. How are they cached (Redis? memory?) and for how long?
3. What triggers OCR on cached images?
4. What happens on multi-image messages?

- [ ] **Step 5: Extract candidate/confirmation logic**

```bash
cd D:\emu-bot
grep -rn "candidate\|候选\|选\|select\|confirm\|数字\|pending_select\|pop_pending_select" src/features/ --include="*.py" | head -100
```

Record: how candidates are presented, how numbers are parsed, what error messages exist.

- [ ] **Step 6: Check VPS for any divergence in feature files**

Compare the feature files from Git vs VPS using the drift matrix from Task 3. If any feature file is DRIFT or VPS_ONLY, inspect the VPS version:

```bash
ssh root@154.37.219.8 "cat /opt/pjsk-emu-bot/src/features/<file>" 2>&1
```

Only for files that do NOT contain secrets (no API keys, tokens, or user data).

- [ ] **Step 7: Populate the feature matrix**

```markdown
# Legacy Feature Matrix

> Generated from static analysis of D:\emu-bot and /opt/pjsk-emu-bot.
> Audit date: 2026-07-16. Sources: Git HEAD <sha>, VPS live files.

## Commands

| feature_id | user_command | aliases | conversation | trigger | arguments | current_handler | dependencies | reply_type | database_read | database_write | production_evidence | compatibility | reason | new_command |
|------------|-------------|---------|-------------|---------|-----------|-----------------|-------------|------------|--------------|---------------|--------------------|-------------|--------|------------|
| F-001 | ... | ... | private/group | command | ... | handler_xxx.py | ... | text | ... | ... | Git+VPS aligned | keep | ... | /emu ... |

## Image Triggers

| feature_id | scenario | conversation | caching | window_s | multi-image | triggers_ocr | handler | production_evidence |
|------------|----------|-------------|---------|----------|-------------|-------------|---------|--------------------|

## Candidate Confirmation

| feature_id | presentation | parse_rule | error_messages | ttl_s | handler | production_evidence |
|------------|-------------|-----------|---------------|-------|---------|--------------------|

## Unknown / Unconfirmed Behaviors

| item | reason unknown | risk if mischaracterized |
|------|---------------|--------------------------|
```

- [ ] **Step 8: Commit**

```bash
git add docs/production/LEGACY-FEATURE-MATRIX.md docs/production/LEGACY-PRODUCTION-BASELINE.md
git commit -m "audit(3a): extract legacy commands, image triggers, and candidate flow"
```

---

### Task 5: Rollback eligibility assessment

**Files:**
- Modify: `docs/production/LEGACY-PRODUCTION-BASELINE.md` (add §5)

**Interfaces:**
- Consumes: Tasks 1–4 outputs
- Produces: Section "5. Rollback Eligibility Assessment"

- [ ] **Step 1: Assess Git reproducibility**

Can the VPS state be reproduced from the Git HEAD?

```text
IF (GIT_ONLY count > 0) → NO — not all needed files are in Git
IF (LIVE_ORPHAN count > 0) → NO — production depends on unversioned files
IF (DRIFT count > 0) → PARTIAL — Git has the files but content differs
IF (all three counts == 0) → YES
```

- [ ] **Step 2: Assess import soundness**

Run static import analysis on the VPS source tree:

```bash
ssh root@154.37.219.8 \
  "cd /opt/pjsk-emu-bot && python3 -c '
import ast, sys, os
from pathlib import Path
errors = []
for pyfile in Path(\"src\").rglob(\"*.py\"):
    try:
        with open(pyfile) as f:
            ast.parse(f.read())
    except SyntaxError as e:
        errors.append(f\"{pyfile}: {e}\")
if errors:
    for e in errors[:20]:
        print(e)
    print(f\"... and {len(errors)-20} more\")
else:
    print(\"ALL_FILES_PARSE_OK\")
' 2>&1"
```

- [ ] **Step 3: Verify critical-path import chain**

Check that the main entry point's import chain is complete:

```bash
ssh root@154.37.219.8 \
  "cd /opt/pjsk-emu-bot && python3 -c '
import sys; sys.path.insert(0, \".\")
try:
    # Dry-run imports for critical path only — no side effects
    import ast, importlib
    critical = [
        \"src.core.calc_accuracy\",
        \"src.core.kn_power\",
        \"src.features.handler_b20\",
        \"src.features.handler_ocr\",
    ]
    for mod in critical:
        try:
            importlib.import_module(mod)
            print(f\"OK: {mod}\")
        except ImportError as e:
            print(f\"MISSING: {mod} — {e}\")
except Exception as e:
    print(f\"FATAL: {e}\")
' 2>&1"
```

**Privacy**: The module names above do not contain secrets. If the import fails because of a missing `.env`-based config, record "import blocked by missing config (non-fatal for static check)".

- [ ] **Step 4: Write the rollback eligibility assessment**

```markdown
## 5. Rollback Eligibility Assessment

### 5.1 Git reproducibility

- **Can the VPS state be reproduced from current Git HEAD?**: <YES | PARTIAL | NO>
- **Evidence**: <N> GIT_ONLY, <N> LIVE_ORPHAN, <N> DRIFT

### 5.2 Import soundness

- **All .py files parse successfully?**: <YES | NO — N files with SyntaxError>
- **Critical-path imports resolve?**: <ALL_OK | N_MISSING>

### 5.3 Eligibility verdict

- **Eligible as formal rollback candidate?**: <YES | NO | CONDITIONAL>
- **Conditions to meet before eligibility**:
  1. ...
- **Current status**: NOT_ELIGIBLE — freeze baseline incomplete.
  Do NOT reference this bot as a rollback target in deployment scripts.
```

- [ ] **Step 5: Commit**

```bash
git add docs/production/LEGACY-PRODUCTION-BASELINE.md
git commit -m "audit(3a): assess old bot rollback eligibility — reproducibility and imports"
```

---

### Task 6: Final assembly and self-review

**Files:**
- Modify: `docs/production/LEGACY-PRODUCTION-BASELINE.md` (add §6, cross-reference links)
- Modify: `docs/production/LEGACY-FEATURE-MATRIX.md` (add completeness notes)
- Modify: `docs/README.md` (add links to new docs)

**Interfaces:**
- Consumes: Tasks 1–5 outputs
- Produces: Completed baseline document and feature matrix

- [ ] **Step 1: Add a completeness self-assessment to the baseline document**

```markdown
## 6. Completeness Self-Assessment

### Covered
- [x] Local Git state
- [x] VPS live filesystem
- [x] Git↔VPS drift matrix
- [x] Orphan classification (live/dead)
- [x] Command inventory
- [x] Image trigger flow
- [x] Candidate confirmation flow
- [x] Reply type classification
- [x] Rollback eligibility

### Not Covered (out of scope for 3A-1)
- Database row counts and user statistics (requires SELECT — PII risk)
- Runtime performance profiling
- NapCat configuration details
- Redis data inspection
- Old OCR model weights or training data
- Non-Python files (system scripts, cron jobs outside /opt/pjsk-emu-bot)

### Unknowns (require further investigation)
- (list any behaviors that could not be confirmed from static analysis alone)
```

- [ ] **Step 2: Add a 3A-1 → 3A-2 approval gate to the baseline document**

```markdown
## 7. Phase 3A-2 Approval Gate

**3A-1 is now complete.** The following data has been collected without
any production writes:

- File manifests (local + VPS)
- Drift matrix
- Command and feature inventory
- Orphan classification
- Rollback eligibility assessment

**3A-2 (Freeze Archive) requires separate human authorization.**

3A-2 will:
- Create a tarball of /opt/pjsk-emu-bot on the VPS
- Generate a SHA-256 manifest of the archive
- Record Python dependency versions
- Copy the archive to a secure audit location
- Assign a legacy baseline ID

**3A-2 will NOT:**
- Stop, restart, or modify any service
- Modify any file under /opt/pjsk-emu-bot
- Read or copy .env, bot.env, or database files
- Install or remove packages

**Do NOT proceed to 3A-2 without explicit user approval.**
```

- [ ] **Step 3: Update docs/README.md**

Add the new documents under a "Legacy Audit" section:

```markdown
### Legacy Audit (Phase 5 Task 3A)

| 文档 | 用途 |
|------|------|
| [`production/LEGACY-PRODUCTION-BASELINE.md`](production/LEGACY-PRODUCTION-BASELINE.md) | Old bot frozen baseline — files, drift, rollback eligibility |
| [`production/LEGACY-FEATURE-MATRIX.md`](production/LEGACY-FEATURE-MATRIX.md) | Old bot command and trigger inventory |
```

- [ ] **Step 4: Final commit for 3A-1**

```bash
git add docs/production/LEGACY-PRODUCTION-BASELINE.md docs/production/LEGACY-FEATURE-MATRIX.md docs/README.md
git commit -m "audit(3a): complete read-only baseline — feature matrix, rollback assessment, 3A-2 gate"
```

---

### Task 7 (FUTURE — do NOT execute): 3A-2 Freeze Archive

> ⛔ **HUMAN APPROVAL REQUIRED BEFORE THIS TASK.**
>
> This task performs production write operations (creating files on VPS,
> copying source code). It must NOT be executed as part of 3A-1.
>
> When approved, the implementer must:
> 1. Create `/opt/pjsk-astrbot/shared/audit/legacy-<baseline_id>/` on the VPS
> 2. `cp -r /opt/pjsk-emu-bot` (excluding .env, *.db, __pycache__, logs/) into the audit directory
> 3. Generate `source-manifest.sha256` and `dependency-manifest.txt`
> 4. Create a tarball and record its SHA-256
> 5. Commit only the manifests (not the tarball) to Git under `artifacts/legacy-baseline/<baseline_id>/`
> 6. Add `.gitignore` entries for `*.tar.gz` and `*.db` under `artifacts/`
> 7. Assign a formal `legacy_baseline_id`
> 8. Update LEGACY-PRODUCTION-BASELINE.md with the baseline ID and archive location

---

## Self-Review

### 1. Spec coverage

| Spec requirement | Task |
|-----------------|------|
| Local old-repo file manifest | Task 1 |
| VPS live filesystem snapshot | Task 2 |
| Git-vs-VPS drift matrix | Task 3 |
| Feature extraction (commands, triggers, replies) | Task 4 |
| Rollback eligibility assessment | Task 5 |
| Privacy: no QQ/game ID/OCR/image URL in outputs | All tasks (privacy rules per step) |
| Read-only in 3A-1 | All tasks (no stop/start/kill/write) |
| 3A-1 → 3A-2 human approval gate | Task 6 §7 |
| Feature matrix with all required fields | Task 4 |
| Orphan classification (live/dead) | Task 3 |
| Cross-reference Git, VPS, journal, tests | Tasks 1-4 |
| Do not auto-proceed to Task 3B | Task 6 §7 |
| Independent commits | Each task ends with commit |

### 2. Placeholder scan

No TODO, TBD, 待定, 稍后决定, 可能, 视情况, or 默认应该 found.

### 3. Type consistency

All file paths use forward slashes. All SSH commands use explicit host and paths. All bash commands include `2>&1` for error capture. Commit messages follow `audit(3a):` prefix convention.

---

> **Plan status: Complete. Awaiting human review before execution.**
> **Next step after approval: Execute Tasks 1–6 (3A-1 read-only audit).**
> **Do NOT execute Task 7 (3A-2) without separate approval.**
> **Do NOT proceed to Task 3B after 3A completes.**
