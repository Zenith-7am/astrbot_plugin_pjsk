# Phase 4b — Query & Render Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** B20 query, difficulty rankings, APPEND toggle, and independent FastAPI+Playwright render service — from domain types through AstrBot commands.

**Architecture:** 12 tasks in 3 sub-phases. 4b-1 (queries) → 4b-2 (render service) → 4b-3 (AstrBot commands). Each sub-phase independently testable. pjsk_core/application never touches AstrBot types. Render service is a separate process with its own lifecycle.

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio, dataclasses, aiosqlite, httpx. Render service: FastAPI + Playwright (Node.js not required — JS runs in Chromium).

**Estimated:** ~12 new source files + ~10 test files.

## Global Constraints

- domain: synchronous, pure, no I/O. Must not import application/ports/adapters/plugin/AstrBot/httpx.
- application: async, only depends on domain + ports. Must not import AstrBot/OneBot event types.
- ports: narrow interfaces. Repository methods return domain objects, never dicts/rows.
- adapters: implement ports. Database access only through repository adapters.
- TDD: RED → GREEN → REFACTOR → commit per task.
- pytest, ruff, mypy strict must pass on all code.
- Migration changes are explicit versioned .sql files — no implicit ALTER TABLE at startup.
- Render service: independent process, `127.0.0.1:3000`. Two fixed endpoints only. No Rating calculation in JS.
- All values pre-computed in Python domain layer; JS only renders.
- `calc_player_class()` recovered from old emu-bot git `a3070e7` — commit to old repo first, then transplant.

---

## Phase 4b-1: Queries & Preferences

### Task 1: Song domain type + PlayerClass domain type

**Files:**
- Create: `pjsk_core/domain/song.py`
- Create: `pjsk_core/domain/player_class.py`
- Create: `tests/domain/test_song.py`
- Create: `tests/domain/test_player_class.py`

**Interfaces:**
- Produces: `Song(id, title_ja, title_cn, title_en, aliases)` frozen dataclass
- Produces: `PlayerClass(name, icon, stars, fallback_color)` frozen dataclass
- Produces: `calc_player_class(sp: float) -> PlayerClass` pure function

- [ ] **Step 1: Write RED tests for Song**

```python
# tests/domain/test_song.py
def test_song_is_frozen():
    from pjsk_core.domain.song import Song
    s = Song(id=1, title_ja="幾望の月", title_cn="", title_en="", aliases="[]")
    assert s.id == 1
    with pytest.raises(Exception):
        s.id = 2
```

- [ ] **Step 2: Write RED tests for PlayerClass**

```python
# tests/domain/test_player_class.py
def test_sekai_master_threshold():
    from pjsk_core.domain.player_class import calc_player_class
    pc = calc_player_class(3939)
    assert pc.name == "SEKAI MASTER"
    assert pc.stars == 10

def test_grand_master_boundary():
    pc = calc_player_class(3400)
    assert pc.name == "Grand Master"
    pc2 = calc_player_class(3399)
    assert pc2.name == "Master"
```

Cover all 9 threshold boundaries: 3939, 3400, 3250, 3150, 3050, 2950, 2800, 2500, and <2500. Also test star calculations for each tier.

- [ ] **Step 3: Implement Song dataclass** — `pjsk_core/domain/song.py`
- [ ] **Step 4: Implement PlayerClass + calc_player_class()** — from old emu-bot `a3070e7` source, return `PlayerClass` dataclass not dict
- [ ] **Step 5: GREEN — pytest pass**
- [ ] **Step 6: Commit**

---

### Task 2: SongRepository port + SqliteSongRepository adapter + songs table migration

**Files:**
- Create: `adapters/database/migrations/005_songs_table.sql` (renumbered to 006 later if 005 reserved for append_excluded)
- Create: `adapters/database/song_repository.py`
- Create: `tests/adapters/database/test_song_repository.py`
- Modify: `pjsk_core/ports/repositories.py` (add SongRepository)

**Interfaces:**
- Produces: `SongRepository` Protocol — `get_by_id(song_id) -> Song | None`, `get_all() -> list[Song]`
- Produces: `SqliteSongRepository` — implements SongRepository, reads from `songs` table

**Note on migration ordering:** songs table schema already exists in the old project (`CREATE TABLE songs`). The new project's chart_data importer populates songs. This task adds the migration to ensure the table is created by the migration system, plus the `SqliteSongRepository` adapter. If `chart_data/` import already creates the songs table at bootstrap, the migration is a no-op safety net.

- [ ] **Step 1: Write RED test** — SqliteSongRepository CRUD against temp DB
- [ ] **Step 2: Add SongRepository Protocol to ports/repositories.py**
- [ ] **Step 3: Add songs table migration .sql**
- [ ] **Step 4: Implement SqliteSongRepository**
- [ ] **Step 5: GREEN**
- [ ] **Step 6: Commit**

---

### Task 3: Migration 005 — users.append_excluded + UserRepository extension

**Files:**
- Create: `adapters/database/migrations/006_append_excluded.sql`
- Modify: `pjsk_core/ports/repositories.py` (add `get_append_excluded`, `set_append_excluded` to UserRepository)
- Modify: `adapters/database/repository.py` (implement new methods)
- Modify: `pjsk_core/domain/users.py` (add `append_excluded: bool` to User)
- Create: `tests/adapters/database/test_append_excluded.py`

- [ ] **Step 1: Write RED test** — `get_append_excluded` returns True (default), `set_append_excluded` toggles
- [ ] **Step 2: Write migration SQL with backfill logic**

```sql
ALTER TABLE users ADD COLUMN append_excluded INTEGER NOT NULL DEFAULT 1;

UPDATE users SET append_excluded = 0
WHERE id IN (
    SELECT DISTINCT pb.user_id FROM personal_bests pb
    JOIN charts c ON c.id = pb.chart_id
    WHERE c.difficulty = 'append' AND pb.status IN ('ap', 'fc')
);
```

- [ ] **Step 3: Add `append_excluded: bool` to User dataclass (default=True)**
- [ ] **Step 4: Implement get/set in SqliteUserRepository**
- [ ] **Step 5: GREEN**
- [ ] **Step 6: Commit**

---

### Task 4: ScoreRepository extensions

**Files:**
- Modify: `pjsk_core/ports/repositories.py` (add `get_b20`, `list_personal_bests_for_difficulty`)
- Modify: `adapters/database/repository.py` (implement both methods)
- Create: `tests/adapters/database/test_b20_query.py`

- [ ] **Step 1: Write RED tests**

```python
# get_b20: returns FC/AP personal_bests, sorted rating DESC, chart_id ASC
async def test_get_b20_returns_fc_ap_only(db_with_scores):
    rows = await repo.get_b20(user_id, include_append=True)
    assert all(r.status in (ScoreStatus.AP, ScoreStatus.FC) for r in rows)
    # Sorted by rating DESC
    assert rows[0].rating >= rows[1].rating

# list_personal_bests_for_difficulty: returns dict[chart_id, ScoreAttempt]
async def test_bests_for_difficulty_returns_dict(db_with_scores):
    result = await repo.list_personal_bests_for_difficulty(user_id, [chart1.id, chart2.id])
    assert isinstance(result, dict)
    assert result[chart1.id].chart_id == chart1.id
```

- [ ] **Step 2: Add methods to ScoreRepository Protocol**
- [ ] **Step 3: Implement SQL queries in SqliteScoreRepository**
- [ ] **Step 4: GREEN**
- [ ] **Step 5: Commit**

---

### Task 5: B20 query types + QueryB20 use case

**Files:**
- Create: `pjsk_core/domain/b20.py`
- Create: `pjsk_core/application/query_b20.py`
- Create: `tests/domain/test_b20_types.py`
- Create: `tests/application/test_query_b20.py`

- [ ] **Step 1: Write RED tests for B20Entry, B20Result types**
- [ ] **Step 2: Write RED test for QueryB20**

```python
async def test_query_b20_returns_top_20():
    use_case = QueryB20(scores=mock_scores, songs=mock_songs,
                        charts=mock_charts, users=mock_users)
    result = await use_case.query(user_id)
    assert len(result.entries) <= 20
    assert result.sp == result.b20_avg + result.fc_bonus + result.ap_bonus
    assert result.fc_bonus == 0.0  # reserved
```

- [ ] **Step 3: Implement domain types**
- [ ] **Step 4: Implement QueryB20** — filter FC/AP, exclude APPEND per preference, sort, top 20, resolve song titles, compute SP
- [ ] **Step 5: GREEN**
- [ ] **Step 6: Commit**

---

### Task 6: Difficulty ranking types + QueryDifficultyRanking use case

**Files:**
- Create: `pjsk_core/domain/difficulty_ranking.py`
- Create: `pjsk_core/application/query_difficulty_ranking.py`
- Create: `tests/domain/test_difficulty_ranking_types.py`
- Create: `tests/application/test_query_difficulty_ranking.py`

- [ ] **Step 1: Write RED tests**

```python
async def test_global_ranking_sorts_by_constant():
    result = await use_case.query_global(Difficulty.MASTER, 31)
    # Sorted: constant DESC, same value: + > none > -, song_id ASC
    constants = [e.community_constant for e in result.entries]
    assert _is_sorted(constants)

async def test_personal_ranking_shows_unplayed():
    result = await use_case.query_personal(user_id, Difficulty.MASTER, 31)
    unplayed = [e for e in result.entries if not e.is_played]
    assert len(unplayed) > 0
    assert unplayed[0].personal_best is None
```

- [ ] **Step 2: Implement DifficultyRankEntry, DifficultyRanking dataclasses**
- [ ] **Step 3: Implement Chart constant sorting logic** (`+ > none > -` ordering)
- [ ] **Step 4: Implement QueryDifficultyRanking** — list charts → sort → LEFT JOIN personal bests → resolve songs
- [ ] **Step 5: GREEN**
- [ ] **Step 6: Commit**

---

### Task 7: ToggleAppend use case + Renderer port

**Files:**
- Create: `pjsk_core/ports/renderer.py`
- Create: `pjsk_core/application/toggle_append.py`
- Create: `tests/application/test_toggle_append.py`

- [ ] **Step 1: Write RED tests**
- [ ] **Step 2: Implement Renderer Protocol + RenderPayload dataclass**
- [ ] **Step 3: Implement ToggleAppend**
- [ ] **Step 4: GREEN**
- [ ] **Step 5: Commit**

---

## Phase 4b-2: Render Service

### Task 8: jacket_cache adapter

**Files:**
- Create: `adapters/rendering/__init__.py`
- Create: `adapters/rendering/jacket_cache.py`
- Create: `tests/adapters/rendering/test_jacket_cache.py`

**Interfaces:**
- Produces: `async def get_jacket(song_id: int) -> str | None` — returns `data:image/webp;base64,...` or None
- Produces: `async def prefetch_jackets(song_ids: list[int]) -> dict[int, str]`

**CDN URL:** `https://api.pjsk-rate-api.com/music/jacket/thumbnail_{song_id}/thumbnail_{song_id}.webp?v=2`

**Cache strategy:** Local disk → CDN download (max 5 concurrent). Cache directory configurable, default `/var/cache/pjsk/jackets/` (or `tempfile.gettempdir()` for tests).

- [ ] **Step 1: Write RED test** — mock CDN response → cached to disk → second call hits cache
- [ ] **Step 2: Implement `_load_from_cache`, `_fetch_from_cdn`, `get_jacket`, `prefetch_jackets`**
- [ ] **Step 3: GREEN**
- [ ] **Step 4: Commit**

---

### Task 9: Render service FastAPI app + JS functions migration

**Files:**
- Create: `render_service/` directory with:
  - `render_service/main.py`
  - `render_service/functions/_loader.js`
  - `render_service/functions/b20.js`
  - `render_service/functions/difficulty.js`
- Create: `render_service/config.py` (HOST, PORT, CACHE_DIR)
- Create: `tests/render_service/__init__.py` (empty)
- Create: `tests/render_service/test_render_service.py`

**Architecture:** Reuse old `render_service/main.py` pattern — FastAPI lifespan with Playwright, two pages (HTML content page for one-off use, canvas page for function rendering). Browser shared, Page/Context per-request with finally cleanup.

**JS migration rules:**
- `b20.js`: Remove `parseLevel()` (~13 lines) and `calcKn()` (~30 lines). All field values read directly from Python pre-computed payload entries (`entry.display_level`, `entry.rating`, `entry.accuracy`, `entry.status`). Canvas drawing code unchanged.
- `difficulty.js`: Remove `parseLevel()`. Read `entry.community_constant` as-is for tier labels. Canvas drawing code unchanged.
- `_loader.js`: Copy verbatim from old project.

- [ ] **Step 1: Write RED test** — `curl POST /render/b20` with fixture payload → PNG bytes, valid Content-Type
- [ ] **Step 2: Copy + modify `_loader.js`**
- [ ] **Step 3: Copy + modify `b20.js`** (strip calcKn/parseLevel)
- [ ] **Step 4: Copy + modify `difficulty.js`** (strip parseLevel)
- [ ] **Step 5: Implement `render_service/main.py`** — FastAPI lifespan, Playwright setup, `/health`, `/render/b20`, `/render/difficulty`
- [ ] **Step 6: GREEN** — Start service, run HTTP tests against it
- [ ] **Step 7: Commit**

---

### Task 10: HttpRenderer adapter

**Files:**
- Create: `adapters/rendering/renderer_adapter.py`
- Create: `tests/adapters/rendering/test_renderer_adapter.py`

**Interfaces:**
- Produces: `HttpRenderer` implementing `Renderer` port — `async def render(payload: RenderPayload) -> bytes | None`

- [ ] **Step 1: Write RED test** — mock aiohttp server → adapter returns bytes; server error → returns None
- [ ] **Step 2: Implement `HttpRenderer`** — POST to `http://127.0.0.1:3000/render/{template_name}` with JSON body, timeout, error handling
- [ ] **Step 3: GREEN**
- [ ] **Step 4: Commit**

---

## Phase 4b-3: AstrBot Integration

### Task 11: Bootstrap extension + PluginRuntime extension

**Files:**
- Modify: `pjsk_emubot/bootstrap.py`
- Modify: `pjsk_emubot/runtime.py`
- Modify: `tests/plugin/test_runtime.py` (if exists) or create new

- [ ] **Step 1: Write RED test** — PluginRuntime holds `query_b20`, `query_difficulty`, `toggle_append`, `renderer`, `song_repo`; `close()` releases all
- [ ] **Step 2: Add new fields to PluginRuntime**
- [ ] **Step 3: Extend `assemble_plugin_runtime()`** — wire SongRepository, QueryB20, QueryDifficultyRanking, ToggleAppend, HttpRenderer
- [ ] **Step 4: GREEN**
- [ ] **Step 5: Commit**

---

### Task 12: AstrBot commands — /pjsk b20, /pjsk difficulty, /pjsk append

**Files:**
- Modify: `main.py` (add `@pjsk_command_group.command(...)` handlers)
- Modify: `pjsk_emubot/_handlers.py` (add command helpers)
- Modify: `tests/plugin/test_main.py` (add command tests)

**Commands:**

| Command | Handler | Flow |
|---------|---------|------|
| `/pjsk b20` | `pjsk_b20` | QueryB20 → Renderer → image reply, or text fallback |
| `/pjsk ma31` | `pjsk_difficulty` | Parse `(diff_abbr)(level)` → QueryDifficultyRanking.query_personal |
| `/pjsk ma31 global` | same | `global` keyword → query_global |
| `/pjsk append on` | `pjsk_append` | ToggleAppend.set(excluded=False) |
| `/pjsk append off` | same | ToggleAppend.set(excluded=True) |
| `/pjsk append status` | same | ToggleAppend.get() |

**Difficulty command parsing** (in plugin layer):
- Regex: `^(ma\|ex\|apd\|exp\|hd\|nm\|ez)(\d{1,2})$` — case insensitive
- Map: `ma→MASTER, ex→EXPERT, apd→APPEND, exp→EXPERT, hd→HARD, nm→NORMAL, ez→EASY`
- Optional `global` suffix switches to global ranking

**Render fallback:** When `Renderer.render()` returns None, format B20Result or DifficultyRanking as text summary.

- [ ] **Step 1: Write RED tests** — mock QueryB20 with FakeRenderer → command returns image/text; invalid format → error message
- [ ] **Step 2: Add `pjsk_b20` handler**
- [ ] **Step 3: Add `pjsk_difficulty` handler with regex parsing**
- [ ] **Step 4: Add `pjsk_append` handler**
- [ ] **Step 5: Add text fallback formatting for render failures**
- [ ] **Step 6: GREEN — full pytest + ruff + mypy**
- [ ] **Step 7: Commit**

---

## Verification (per task and final)

Each task ends with:
```bash
pytest tests/<task_module>/ -v    # focused tests GREEN
pytest tests/ -q                   # full regression — all must pass
ruff check .                       # clean
mypy pjsk_core adapters pjsk_emubot tools tests main.py render_service --strict
```

Final gate after Task 12:
- All tests pass, Ruff clean, Mypy baseline maintained
- `python -c "from render_service.main import app"` → FastAPI app imports cleanly
- `curl http://127.0.0.1:3000/health` → `{"status":"ok"}`
