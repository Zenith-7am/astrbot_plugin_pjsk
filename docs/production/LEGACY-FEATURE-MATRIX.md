# Legacy Feature Matrix

> Generated from static analysis of `D:\emu-bot\src\features\` and cross-referenced
> with VPS `/opt/pjsk-emu-bot/src/features/` (SHA-256 comparison).
> Audit date: 2026-07-16. Sources: Git HEAD `a0821a1`, VPS live files.

---

## Commands

| feature_id | user_command | aliases | conversation | trigger | arguments | current_handler | dependencies | reply_type | database_read | database_write | production_evidence | compatibility | reason | new_command |
|------------|-------------|---------|-------------|---------|-----------|-----------------|-------------|------------|--------------|---------------|--------------------|-------------|--------|------------|
| F-001 | `帮助` | `help` | both | command (rule_checker) | (none) | `handler_help.py` | `_common`, `emu` (astrobot_service) | text or image (base64) | none | none | Git+VPS aligned | **keep** | Core help command | `/emu help` |
| F-002 | `注册` | — | both | command (rule_checker) | `<game_id>` | `handler_register.py` | `_common`, `db`, `emu`, `identity` | text | users (read) | users (create/update) | Git+VPS aligned; VPS has LIVE_ORPHAN `identity.py` | **keep** | User registration required for all write ops | `/emu bind <game_id>` |
| F-003 | `b20` | `查b20` | both | command (rule_checker) | (none) | `handler_b20.py` | `_common`, `db`, `emu`, `player_class`, `render_client`, `b20_renderer` | image (base64) or text | scores, songs, charts | none | Git+VPS aligned; VPS has LIVE_ORPHAN `player_class.py` | **keep** | Core B20 feature | `/emu b20` |
| F-004 | `查分` | — | both | command (rule_checker) | (none, uses cached image) | `handler_ocr.py` | `_common`, `db`, `ocr_pipeline`, `ocr_card`, `song_match`, `emu` | image (base64) | songs, charts, aliases | scores (insert), score_history (insert), personal_best (upsert) | Git+VPS aligned | **keep** | OCR entry point | (image trigger, not command) |
| F-005 | `难度排行` | — | both | command (rule_checker) | `<diff><level>` e.g. `ma31` | `handler_difficulty.py` | `_common`, `db`, `emu`, `difficulty_renderer`, `render_client` | image (base64) | songs, charts, scores | none | Git+VPS aligned | **keep** | Difficulty ranking | `/emu ma31` |
| F-006 | `我的` | — | both | command (rule_checker) | `<diff><level>` e.g. `我的ex28` | `handler_difficulty.py` | same as F-005 | image (base64) | songs, charts, scores | none | Git+VPS aligned | **keep** | Personal difficulty ranking | `/emu ma31` (default personal) |
| F-007 | `append开启` / `append关闭` | — | both | command (rule_checker) | `开启` or `关闭` | `handler_append.py` | `_common`, `db` | text | users (read) | users (update append_excluded) | Git+VPS aligned | **rename** | `开启/关闭` confusing. `on/off` also confusing. | `/emu append include` `/emu append exclude` |
| F-008 | `别名列表` / `别名添加` / `别名删除` | — | both | command (rule_checker) | `<song>`, `<song> <alias>` | `handler_alias.py` | `_common`, `db`, `emu` | text | songs | songs (update aliases) | Git+VPS aligned | **defer** | Alias management not in Phase 5 scope; defer to post-MVP | (deferred) |
| F-009 | `批量` | `批量上传` | both | command (rule_checker) | (none, then forward msg + images) | `handler_batch.py` | `_common`, `db`, `emu`, `api` | text + image | users, songs | scores (insert per image) | Git+VPS aligned | **defer** | Batch upload explicitly out of scope for Phase 5 | (deferred) |
| F-010 | (chat) | — | group | command (rule_checker, any unknown) | `<any text>` | `handler_chat.py` | `_common`, `emu`, `astrobot_config` | text | none | none | Git+VPS aligned | **remove** | Chat personality delegated to NoneBot/AstrBot; new gateway returns help for unknown /emu, passthrough otherwise | (removed) |
| F-011 | (batch session) | `开始批量` / `结束批量上传` / `结束批量` | private | command | — | `handler_batch_session.py` | `_common`, `db`, `emu`, `ocr_pipeline`, `ocr_card`, `api` | text + image | users, songs, scores | scores (insert), score_history (insert) | Git+VPS aligned | **remove** | Batch session state machine explicitly out of scope; single-image per message | (removed) |

---

## Image Triggers

| feature_id | scenario | conversation | caching | window_s | multi-image | triggers_ocr | handler | production_evidence |
|------------|----------|-------------|---------|----------|-------------|-------------|---------|--------------------|
| I-001 | Single image in private chat | private | Redis `pending_images` (keyed by QQ) | 15s | N/A (single) | Yes — via `ocr_cmd` on `查分` or via `image_listener` → `ocr_cmd` pop | `handler_ocr.py` | Git+VPS aligned |
| I-002 | Single image in group chat | group | Redis `pending_images` (keyed by QQ + group_id) | 15s | N/A (single) | Yes — via `ocr_cmd` or @Bot with image | `handler_ocr.py` | Git+VPS aligned |
| I-003 | @Bot + Image (same message) | group | N/A (direct) | — | Rejected if >1 | Yes — rule_checker returns True for @Bot | whichever matcher matches first | Git+VPS aligned |
| I-004 | Image then @Bot (within 15s) | group | Redis `pending_images` | 15s | Only first image used | Yes — @Bot triggers `ocr_cmd` which pops pending | `handler_ocr.py` | Git+VPS aligned |
| I-005 | Forwarded message with images | group | N/A | — | Multiple (extracted from forward) | Yes — batch handler extracts images from forward msg | `handler_batch.py` | Git+VPS aligned |
| I-006 | Multi-image in single message | both | N/A | — | Multiple | Rejected ("一次只能识别一张") for non-batch path; Accepted for batch path | `handler_ocr.py` / `handler_batch.py` | Git+VPS aligned |

**Key finding**: The old bot uses **Redis** for image caching (15s window). The new gateway uses in-process `EphemeralImageBuffer` — functionally equivalent but eliminates Redis dependency for this path.

---

## Candidate Confirmation

| feature_id | presentation | parse_rule | error_messages | ttl_s | handler | production_evidence |
|------------|-------------|-----------|---------------|-------|---------|--------------------|
| C-001 | Formatted text: numbered candidate list with song/difficulty/level/judges | Numeric input `1`-`N` (single digit or number) | "选择已超时，请重新上传截图" / "无效选择，请回复 1-N" / "无效选择，请重新上传截图" | 300s (Redis TTL) | `handler_ocr.py` — `pop_pending_select()` | Git+VPS aligned |
| C-002 | Batch mode: per-image candidate confirmation | Same numeric rules + "跳过" skip option | "选择已超时" / "无效选择，该图已跳过" | 300s (Redis TTL) | `handler_batch_session.py` | Git+VPS aligned |

**Key finding**: Redis used for candidate state. New gateway uses in-process `NoopCandidateStore` (shadow) or `MemoryCandidateStore` (production) — already implemented in `adapters/cache/`.

---

## Unconfirmed / Unknown Behaviors

| item | reason unknown | risk if mischaracterized |
|------|---------------|--------------------------|
| `data/astrobot/*` modules on VPS | Not present in local Git; purpose unclear (appears to be a separate chat personality layer) | May be running in-process; removal could break unknown functionality |
| `qq_gateway.py` usage | NO_STATIC_REFERENCE; may be dynamically imported via string-based import | If actually live, QQ gateway logic may not be captured in feature matrix |
| `stepfun_ocr.py` on VPS but not in Git | DRIFT+VPS_ONLY hybrid; likely added directly on VPS | If imported by `ocr_engine.py` via dynamic dispatch, one OCR engine path is unversioned |
| Exact NapCat connection status | Health endpoint reports `online:false` with ~50h since last heartbeat; NapCat logs on China VPS not checked | If connection is actually alive (health endpoint bug), old bot might still be receiving messages |
| Batch session state machine TTL behavior | Code uses Redis TTL + manual expiry; edge cases around concurrent sessions unclear | If two sessions race on same user, one silently wins; candidate mix-up possible |
| `handler_chat.py` LLM integration | Uses `astrobot_service` / `astrobot_config` — appears to be an Astrobot chat bridge | If chat is actively used by users, removing it changes the bot's persona |

---

> **Next**: Update LEGACY-PRODUCTION-BASELINE.md with link to this matrix.
> **After 3A approval**: Use this matrix as source of truth for Task 3B command contract.
