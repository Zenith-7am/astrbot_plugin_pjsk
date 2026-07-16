> **Status: Approved** (core layer — still valid under Phase 5 standalone direction).
> The domain, application, ports, and adapter designs in this document remain authoritative for `pjsk_core` and `adapters/`.
> Current governance: `CLAUDE.md`. Phase-5 gateway design: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`.

# Phase 3b — CandidateStore + OCR Run Persistence + Candidate Confirmation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every OCR call for audit, store disagreeing candidates for user confirmation, and implement the confirm-then-record flow.

**Architecture:** 8 tasks. Bottom-up: migration → domain types + ports → adapters → application use cases → wire into RecognizeScore → update existing tests. Each task is independently testable and ends with a focused commit.

**Tech Stack:** Python 3.11+, aiosqlite, dataclasses, typing.Protocol, pytest, pytest-asyncio, ruff, mypy strict.

**Estimated total:** ~12 new/modified source files, ~10 test files.

## Global Constraints

- `domain` must be synchronous, pure computation, no I/O. No imports from application/ports/adapters/plugin/AstrBot/SQLite/Redis/httpx/any vision SDK.
- `application` depends only on `domain` and `ports`. Must not know AstrBot/OneBot/Official QQ event objects.
- `ports` define narrow interfaces; no business logic. Repository methods return domain objects, never dicts or SQLite rows.
- `adapters` implement ports. SQLite access only through repository adapters; application never executes raw SQL.
- Platform event objects must not enter the business core. Core domain interfaces must not return untyped generic `dict`.
- TDD: RED → GREEN → REFACTOR → commit per task. No implementation before tests.
- TTL default: 300 seconds. OCR audit is fail-safe: recording failure logs a rate-limited warning, main flow continues with `ocr_run_id=None`.
- Candidate confirmation validates: matched_chart_id exists, note_validated is True, difficulty matches chart, note_count ±1, chart exists.
- SqliteOcrRunRepository obtains independent connections via `get_connection()`, never shares with ScoreRepository/ChartRepository.
- Each migration file is auto-detected by the migrator's `sorted(migrations_dir.glob("*.sql"))` loop; version is parsed from the numeric prefix.

---

### Task 1: Migration 004 — ocr_runs + ocr_observations tables

**Files:**
- Create: `adapters/database/migrations/004_ocr_runs.sql`
- Modify: `tests/adapters/database/test_migrator.py` — all version assertions 3→4
- Modify: `tests/adapters/database/test_chart_repository.py` — no changes needed (migrator auto-detects 004)

**Interfaces:**
- Consumes: migrator auto-discovery (no code changes to migrator.py needed)
- Produces: `ocr_runs` and `ocr_observations` tables available for Task 4 (SqliteOcrRunRepository)

- [ ] **Step 1: Write migration SQL file**

```sql
-- 004: OCR run audit tables — one row per recognition attempt + per-engine observations

CREATE TABLE ocr_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    image_sha256    TEXT NOT NULL CHECK (length(image_sha256) = 64),
    source_gateway  TEXT NOT NULL CHECK (length(source_gateway) > 0),
    final_state     TEXT NOT NULL CHECK (
        final_state IN (
            'consensus', 'degraded_single', 'disagreement',
            'all_failed', 'no_available_engines', 'global_timeout'
        )
    ),
    selected_engine TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_ocr_runs_user_created ON ocr_runs(user_id, created_at);

CREATE TABLE ocr_observations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ocr_run_id        INTEGER NOT NULL REFERENCES ocr_runs(id) ON DELETE CASCADE,
    engine_id         TEXT NOT NULL,
    provider          TEXT NOT NULL CHECK (length(provider) > 0),
    result_status     TEXT NOT NULL CHECK (
        result_status IN (
            'success', 'failed', 'timed_out',
            'cancelled_by_consensus', 'cancelled_by_caller', 'circuit_rejected'
        )
    ),
    elapsed_ms        INTEGER NOT NULL CHECK (elapsed_ms >= 0),
    song_title        TEXT,
    difficulty        TEXT CHECK (difficulty IS NULL OR difficulty IN (
        'easy', 'normal', 'hard', 'expert', 'master', 'append'
    )),
    displayed_level   INTEGER,
    perfect           INTEGER CHECK (perfect IS NULL OR perfect >= 0),
    great             INTEGER CHECK (great IS NULL OR great >= 0),
    good              INTEGER CHECK (good IS NULL OR good >= 0),
    bad               INTEGER CHECK (bad IS NULL OR bad >= 0),
    miss              INTEGER CHECK (miss IS NULL OR miss >= 0),
    matched_chart_id  INTEGER REFERENCES charts(id),
    validation_status TEXT CHECK (validation_status IS NULL OR validation_status IN (
        'strong', 'candidate', 'rejected'
    )),
    error_type        TEXT CHECK (error_type IS NULL OR error_type IN (
        'timeout', 'connection', 'rate_limited',
        'server_error', 'invalid_response'
    )),
    UNIQUE(ocr_run_id, engine_id)
);

CREATE INDEX idx_ocr_obs_run ON ocr_observations(ocr_run_id);
```

- [ ] **Step 2: Run migrator test — it fails because assertions still expect version 3**

Run: `pytest tests/adapters/database/test_migrator.py -v`
Expected: FAIL — assertions like `assert version == 3` now fail because migrator applies 004, returning version 4.

- [ ] **Step 3: Update migrator test assertions from 3 → 4**

In `tests/adapters/database/test_migrator.py`, change all `assert version == 3` to `assert version == 4`:

Lines to change (grep for `version == 3`):
- `test_records_migration_version`: `assert version == 4`
- `test_idempotent_second_run`: `assert version == 4`
- `test_empty_db_returns_zero`: `assert version == 4`
- `test_sha_verification_rejects_modified_migration`: `assert v1 == 4`
- `test_sha_verification_rejects_missing_file`: `assert v1 == 4`

- [ ] **Step 4: Run migrator tests — all pass**

Run: `pytest tests/adapters/database/test_migrator.py -v`
Expected: 7 passed

- [ ] **Step 5: Verify the new tables exist in a full migration run**

Run: `pytest tests/adapters/database/test_migrator.py::TestRunMigrations::test_applies_initial_migration -v`
Expected: PASS (the test checks `tables <= expected` — add `"ocr_runs"` and `"ocr_observations"` to the `expected` set)

- [ ] **Step 6: Commit**

```bash
git add adapters/database/migrations/004_ocr_runs.sql tests/adapters/database/test_migrator.py
git commit -m "feat(db): migration 004 — ocr_runs + ocr_observations audit tables"
```

---

### Task 2: Domain types + ports — OcrRunRecord, OcrEngineRecord, OcrRunRepository, revised CandidateStore

**Files:**
- Create: `pjsk_core/domain/ocr_runs.py` — OcrRunRecord, OcrEngineRecord
- Create: `pjsk_core/ports/ocr_runs.py` — OcrRunRepository Protocol
- Modify: `pjsk_core/ports/cache.py` — replace CandidateStore with new CandidateSet, CandidateConsumeStatus, CandidateConsumeResult, consume_selection API
- Create: `tests/domain/test_ocr_runs.py`
- Modify: `tests/test_port_contracts.py` — update CandidateStore contract, add OcrRunRepository contract

**Interfaces:**
- Consumes: `pjsk_core.domain.users.UserId`, `pjsk_core.domain.charts.Difficulty`, `pjsk_core.domain.scores.Judgements`, `pjsk_core.domain.ocr.Candidate`
- Produces:
  - `OcrRunRecord(id, user_id, image_sha256, source_gateway, final_state, selected_engine, observations, created_at)` frozen dataclass
  - `OcrEngineRecord(engine_id, provider, result_status, elapsed_ms, song_title, difficulty, displayed_level, judgements, matched_chart_id, validation_status, error_type)` frozen dataclass
  - `OcrRunRepository.save(record: OcrRunRecord) -> OcrRunRecord` and `get_by_id(run_id: int) -> OcrRunRecord | None`
  - `CandidateSet(candidates: tuple[Candidate, ...], image_sha256: str, source_gateway: str, ocr_run_id: int, chart_data_version: str)` frozen
  - `CandidateConsumeStatus(Enum): OK, NOT_FOUND, EXPIRED, FORBIDDEN, INVALID_SELECTION`
  - `CandidateConsumeResult(status, candidate, candidate_set)` frozen
  - `CandidateStore.put(user_id, candidate_set, ttl_seconds) -> str` and `consume_selection(candidate_set_id, user_id, selection) -> CandidateConsumeResult`

- [ ] **Step 1: Write domain test for OcrRunRecord and OcrEngineRecord**

Create `tests/domain/test_ocr_runs.py`:

```python
"""Tests for OCR run domain types."""
from datetime import datetime, timezone

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId


class TestOcrEngineRecord:
    def test_success_record(self) -> None:
        rec = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Test Song", difficulty=Difficulty.MASTER,
            displayed_level=30,
            judgements=Judgements(perfect=1000, great=100, good=0, bad=0, miss=0),
            matched_chart_id=1, validation_status="strong", error_type=None,
        )
        assert rec.engine_id == "g"
        assert rec.result_status == "success"
        assert rec.judgements is not None

    def test_error_record(self) -> None:
        rec = OcrEngineRecord(
            engine_id="g", provider="google", result_status="failed",
            elapsed_ms=5000, song_title=None, difficulty=None,
            displayed_level=None, judgements=None,
            matched_chart_id=None, validation_status=None,
            error_type="timeout",
        )
        assert rec.result_status == "failed"
        assert rec.error_type == "timeout"
        assert rec.song_title is None

    def test_circuit_rejected_record(self) -> None:
        rec = OcrEngineRecord(
            engine_id="z", provider="zhipu", result_status="circuit_rejected",
            elapsed_ms=0, song_title=None, difficulty=None,
            displayed_level=None, judgements=None,
            matched_chart_id=None, validation_status=None, error_type=None,
        )
        assert rec.result_status == "circuit_rejected"

    def test_frozen(self) -> None:
        rec = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="T", difficulty=Difficulty.EXPERT,
            displayed_level=25,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            matched_chart_id=1, validation_status="strong", error_type=None,
        )
        try:
            rec.engine_id = "x"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except Exception:
            pass


class TestOcrRunRecord:
    def test_record_creation(self) -> None:
        obs = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Test", difficulty=Difficulty.MASTER,
            displayed_level=30,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            matched_chart_id=1, validation_status="strong", error_type=None,
        )
        now = datetime.now(timezone.utc)
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="a" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine="g",
            observations=(obs,), created_at=now,
        )
        assert record.id is None
        assert record.final_state == "consensus"
        assert len(record.observations) == 1

    def test_frozen(self) -> None:
        now = datetime.now(timezone.utc)
        record = OcrRunRecord(
            id=1, user_id=UserId(1),
            image_sha256="a" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine=None,
            observations=(), created_at=now,
        )
        try:
            record.final_state = "x"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except Exception:
            pass
```

- [ ] **Step 2: Run domain test — fails with import error**

Run: `pytest tests/domain/test_ocr_runs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pjsk_core.domain.ocr_runs'`

- [ ] **Step 3: Implement domain types**

Create `pjsk_core/domain/ocr_runs.py`:

```python
"""OCR run audit records — domain types for persistence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId


@dataclass(frozen=True)
class OcrEngineRecord:
    """Single engine's recognition outcome for audit persistence.

    Every configured engine produces one row, including those that were
    cancelled by consensus or rejected by the circuit breaker.
    """
    engine_id: str
    provider: str
    result_status: str
    elapsed_ms: int
    song_title: str | None
    difficulty: Difficulty | None
    displayed_level: int | None
    judgements: Judgements | None
    matched_chart_id: int | None
    validation_status: str | None
    error_type: str | None


@dataclass(frozen=True)
class OcrRunRecord:
    """Complete record of one OCR attempt — run + all engine observations."""
    id: int | None
    user_id: UserId
    image_sha256: str
    source_gateway: str
    final_state: str
    selected_engine: str | None
    observations: tuple[OcrEngineRecord, ...]
    created_at: datetime
```

- [ ] **Step 4: Run domain test — pass**

Run: `pytest tests/domain/test_ocr_runs.py -v`
Expected: 5 passed

- [ ] **Step 5: Write port contract test for OcrRunRepository**

Append to `tests/test_port_contracts.py` (after the existing CandidateStore test at line ~270):

```python
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.ports.ocr_runs import OcrRunRepository


class FakeOcrRunRepository:
    def __init__(self) -> None:
        self._store: dict[int, OcrRunRecord] = {}
        self._next_id = 1

    async def save(self, record: OcrRunRecord) -> OcrRunRecord:
        stored = OcrRunRecord(
            id=self._next_id, user_id=record.user_id,
            image_sha256=record.image_sha256,
            source_gateway=record.source_gateway,
            final_state=record.final_state,
            selected_engine=record.selected_engine,
            observations=record.observations,
            created_at=record.created_at,
        )
        self._next_id += 1
        self._store[stored.id] = stored
        return stored

    async def get_by_id(self, run_id: int) -> OcrRunRecord | None:
        return self._store.get(run_id)


async def test_ocr_run_repository_contract() -> None:
    repo: OcrRunRepository = FakeOcrRunRepository()
    obs = OcrEngineRecord(
        engine_id="g", provider="google", result_status="success",
        elapsed_ms=500, song_title="Test", difficulty=Difficulty.MASTER,
        displayed_level=30,
        judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
        matched_chart_id=1, validation_status="strong", error_type=None,
    )
    record = OcrRunRecord(
        id=None, user_id=UserId(1),
        image_sha256="a" * 64, source_gateway="astrbot",
        final_state="consensus", selected_engine="g",
        observations=(obs,), created_at=datetime.now(timezone.utc),
    )
    saved = await repo.save(record)
    assert saved.id is not None
    assert saved.id == 1

    fetched = await repo.get_by_id(1)
    assert fetched is not None
    assert fetched.final_state == "consensus"

    not_found = await repo.get_by_id(999)
    assert not_found is None
```

Add needed imports at the top of `tests/test_port_contracts.py`:
```python
from datetime import datetime, timezone
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.ports.ocr_runs import OcrRunRepository
```

- [ ] **Step 6: Run port contract test — fails (ports not created yet)**

Run: `pytest tests/test_port_contracts.py::test_ocr_run_repository_contract -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pjsk_core.ports.ocr_runs'`

- [ ] **Step 7: Implement OcrRunRepository port**

Create `pjsk_core/ports/ocr_runs.py`:

```python
"""OCR run repository port."""
from typing import Protocol

from pjsk_core.domain.ocr_runs import OcrRunRecord


class OcrRunRepository(Protocol):
    """Persistence for OCR run audit records."""

    async def save(self, record: OcrRunRecord) -> OcrRunRecord: ...
    async def get_by_id(self, run_id: int) -> OcrRunRecord | None: ...
```

- [ ] **Step 8: Run port contract test — pass**

Run: `pytest tests/test_port_contracts.py::test_ocr_run_repository_contract -v`
Expected: PASS

- [ ] **Step 9: Rewrite CandidateStore port**

Rewrite `pjsk_core/ports/cache.py` completely:

```python
"""Candidate store port — temporary OCR result storage for user confirmation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pjsk_core.domain.ocr import Candidate
    from pjsk_core.domain.users import UserId


class CandidateConsumeStatus(Enum):
    """Result of a consume_selection attempt."""
    OK = "ok"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    FORBIDDEN = "forbidden"
    INVALID_SELECTION = "invalid_selection"


@dataclass(frozen=True)
class CandidateConsumeResult:
    """Structured result from consume_selection.

    On OK, both ``candidate`` and ``candidate_set`` are present.
    On any other status, both are None.
    """
    status: CandidateConsumeStatus
    candidate: Candidate | None
    candidate_set: CandidateSet | None


@dataclass(frozen=True)
class CandidateSet:
    """A ranked set of disagreeing OCR candidates with enough context
    to construct a ScoreAttempt on user confirmation."""
    candidates: tuple[Candidate, ...]
    image_sha256: str
    source_gateway: str
    ocr_run_id: int
    chart_data_version: str


class CandidateStore(Protocol):
    """Short-lived storage for ambiguous OCR results awaiting user selection.

    Single-consumption: ``consume_selection`` atomically validates
    ownership, expiry, and selection index in one locked operation.
    Expired entries are swept on ``put``.
    """

    async def put(
        self,
        user_id: UserId,
        candidate_set: CandidateSet,
        ttl_seconds: int,
    ) -> str: ...
    """Store a candidate set and return a string ID for user reference."""

    async def consume_selection(
        self,
        candidate_set_id: str,
        user_id: UserId,
        selection: int,
    ) -> CandidateConsumeResult: ...
    """Atomically validate ownership, expiry, and index; delete and return
    on success. Returns structured status on any failure."""
```

- [ ] **Step 10: Update port contract test for new CandidateStore**

In `tests/test_port_contracts.py`, rewrite `FakeCandidateStore` (line ~160) and `test_candidate_store_contract` (line ~258):

```python
from pjsk_core.ports.cache import (
    CandidateConsumeResult,
    CandidateConsumeStatus,
    CandidateSet,
    CandidateStore,
)


class FakeCandidateStore:
    def __init__(self) -> None:
        self._store: dict[str, tuple[UserId, CandidateSet]] = {}
        self._lock = asyncio.Lock()

    async def put(
        self, user_id: UserId, candidate_set: CandidateSet, ttl_seconds: int,
    ) -> str:
        key = f"cs-{len(self._store)}"
        async with self._lock:
            self._store[key] = (user_id, candidate_set)
        return key

    async def consume_selection(
        self, candidate_set_id: str, user_id: UserId, selection: int,
    ) -> CandidateConsumeResult:
        async with self._lock:
            entry = self._store.pop(candidate_set_id, None)
        if entry is None:
            return CandidateConsumeResult(
                status=CandidateConsumeStatus.NOT_FOUND,
                candidate=None, candidate_set=None,
            )
        owner, cs = entry
        if owner != user_id:
            return CandidateConsumeResult(
                status=CandidateConsumeStatus.FORBIDDEN,
                candidate=None, candidate_set=None,
            )
        if selection < 1 or selection > len(cs.candidates):
            return CandidateConsumeResult(
                status=CandidateConsumeStatus.INVALID_SELECTION,
                candidate=None, candidate_set=None,
            )
        return CandidateConsumeResult(
            status=CandidateConsumeStatus.OK,
            candidate=cs.candidates[selection - 1],
            candidate_set=cs,
        )
```

```python
async def test_candidate_store_contract() -> None:
    store: CandidateStore = FakeCandidateStore()
    from pjsk_core.domain.ocr import Candidate
    obs = OcrObservation(
        song_title="Test", difficulty=Difficulty.HARD,
        displayed_level=15,
        judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
        engine="test", elapsed_ms=0,
    )
    candidate = Candidate(
        observation=obs, model_support=1, note_validated=True,
        title_similarity=1.0, note_distance=0, matched_chart_id=1,
    )
    cs = CandidateSet(
        candidates=(candidate,), image_sha256="a" * 64,
        source_gateway="astrbot", ocr_run_id=1, chart_data_version="v1",
    )
    cid = await store.put(UserId(1), cs, ttl_seconds=300)
    assert cid is not None

    result = await store.consume_selection(cid, UserId(1), 1)
    assert result.status == CandidateConsumeStatus.OK
    assert result.candidate is not None
    assert result.candidate_set is not None

    # Second consume returns NOT_FOUND
    result2 = await store.consume_selection(cid, UserId(1), 1)
    assert result2.status == CandidateConsumeStatus.NOT_FOUND

    # Wrong user
    cid2 = await store.put(UserId(1), cs, ttl_seconds=300)
    result3 = await store.consume_selection(cid2, UserId(2), 1)
    assert result3.status == CandidateConsumeStatus.FORBIDDEN

    # Invalid selection
    cid3 = await store.put(UserId(1), cs, ttl_seconds=300)
    result4 = await store.consume_selection(cid3, UserId(1), 5)
    assert result4.status == CandidateConsumeStatus.INVALID_SELECTION
```

Note: add `import asyncio` to the imports in `test_port_contracts.py`.

- [ ] **Step 11: Run all port contract tests**

Run: `pytest tests/test_port_contracts.py -v`
Expected: all contract tests pass (candidate_store_contract + ocr_run_repository_contract + existing)

- [ ] **Step 12: Run domain tests to confirm no regression**

Run: `pytest tests/domain/test_ocr_runs.py tests/domain/ -v`
Expected: all domain tests pass

- [ ] **Step 13: Commit**

```bash
git add pjsk_core/domain/ocr_runs.py pjsk_core/ports/ocr_runs.py pjsk_core/ports/cache.py tests/domain/test_ocr_runs.py tests/test_port_contracts.py
git commit -m "feat: domain types + ports — OcrRunRecord, OcrRunRepository, revised CandidateStore"
```

---

### Task 3: OcrRunRecorder use case

**Files:**
- Create: `pjsk_core/application/ocr_run_recorder.py`
- Create: `tests/application/test_ocr_run_recorder.py`

**Interfaces:**
- Consumes: `OcrRunRecord`, `OcrEngineRecord` (Task 2), `OcrRunRepository` (Task 2), `VisionRaceOutcome`, `EngineResult`, `EngineResultStatus` (existing Phase 3a)
- Produces: `OcrRunRecorder(ocr_run_repo).record(user_id, image_sha256, source_gateway, outcome) -> OcrRunRecord`

- [ ] **Step 1: Write recorder test**

Create `tests/application/test_ocr_run_recorder.py`:

```python
"""Tests for OcrRunRecorder — audit trail construction from VisionRaceOutcome."""
from datetime import datetime, timezone

from pjsk_core.application.ocr_run_recorder import OcrRunRecorder
from pjsk_core.application.vision_race import (
    EngineResult,
    EngineResultStatus,
    VisionRaceDecision,
    VisionRaceOutcome,
)
from pjsk_core.application.validate_ocr import (
    ValidatedCandidate,
    ValidatedObservation,
    ValidationStatus,
)
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionTimeoutError,
)
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.song_matcher import SongMatch, SongMatchMethod, TitleSource
from pjsk_core.domain.users import UserId
from pjsk_core.ports.ocr_runs import OcrRunRepository


def _obs(title: str = "Test Song") -> OcrObservation:
    return OcrObservation(
        title, Difficulty.MASTER, 30,
        Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
        engine="g", elapsed_ms=100,
    )


def _chart() -> Chart:
    return Chart(
        id=1, song_id=1, difficulty=Difficulty.MASTER,
        official_level=30, community_constant="30.5",
        note_count=1100, data_version="v1",
    )


def _make_validated_strong() -> ValidatedObservation:
    sm = SongMatch(song_id=1, score=1.0, method=SongMatchMethod.EXACT, source=TitleSource.JAPANESE)
    vc = ValidatedCandidate(
        song_match=sm, chart=_chart(), note_distance=0,
        note_validated=True, level_validated=True,
        status=ValidationStatus.STRONG,
    )
    return ValidatedObservation(
        observation=_obs(), primary=vc, candidates=(vc,),
        status=ValidationStatus.STRONG,
    )


class FakeOcrRunRepo:
    def __init__(self) -> None:
        self.saved: list[OcrRunRecord] = []
        self._next_id = 1

    async def save(self, record: OcrRunRecord) -> OcrRunRecord:
        stored = OcrRunRecord(
            id=self._next_id, user_id=record.user_id,
            image_sha256=record.image_sha256,
            source_gateway=record.source_gateway,
            final_state=record.final_state,
            selected_engine=record.selected_engine,
            observations=record.observations,
            created_at=record.created_at,
        )
        self._next_id += 1
        self.saved.append(stored)
        return stored

    async def get_by_id(self, run_id: int) -> OcrRunRecord | None:
        for r in self.saved:
            if r.id == run_id:
                return r
        return None


class TestOcrRunRecorder:
    async def test_records_consensus_outcome(self) -> None:
        repo = FakeOcrRunRepo()
        recorder = OcrRunRecorder(repo)
        validated = _make_validated_strong()
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.CONSENSUS,
            selected=validated, consensus=None,
            results=(
                EngineResult(
                    identity=EngineIdentity("g", "google", "gemini-flash"),
                    status=EngineResultStatus.SUCCESS,
                    observation=_obs(), validated=validated,
                    error=None, elapsed_ms=100,
                ),
                EngineResult(
                    identity=EngineIdentity("s", "stepfun", "stepfun-vision"),
                    status=EngineResultStatus.CANCELLED_BY_CONSENSUS,
                    observation=None, validated=None,
                    error=None, elapsed_ms=50,
                ),
            ),
            circuit_rejects=(),
        )
        record = await recorder.record(
            UserId(1), "a" * 64, "astrbot", outcome,
        )
        assert record.id == 1
        assert record.final_state == "consensus"
        assert record.selected_engine == "g"
        assert len(record.observations) == 2
        success_obs = [o for o in record.observations if o.result_status == "success"]
        cancelled_obs = [o for o in record.observations if o.result_status == "cancelled_by_consensus"]
        assert len(success_obs) == 1
        assert len(cancelled_obs) == 1
        assert success_obs[0].song_title == "Test Song"

    async def test_records_all_failed(self) -> None:
        repo = FakeOcrRunRepo()
        recorder = OcrRunRecorder(repo)
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.ALL_FAILED,
            selected=None, consensus=None,
            results=(
                EngineResult(
                    identity=EngineIdentity("g", "google", "g"),
                    status=EngineResultStatus.FAILED,
                    observation=None, validated=None,
                    error=VisionTimeoutError("timeout"), elapsed_ms=5000,
                ),
            ),
            circuit_rejects=(),
        )
        record = await recorder.record(
            UserId(1), "a" * 64, "astrbot", outcome,
        )
        assert record.final_state == "all_failed"
        assert record.selected_engine is None
        obs = record.observations[0]
        assert obs.result_status == "failed"
        assert obs.error_type == "timeout"
        assert obs.song_title is None

    async def test_records_circuit_rejected(self) -> None:
        repo = FakeOcrRunRepo()
        recorder = OcrRunRecorder(repo)
        rejected_id = EngineIdentity("z", "zhipu", "z")
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.DEGRADED_SINGLE,
            selected=_make_validated_strong(), consensus=None,
            results=(
                EngineResult(
                    identity=EngineIdentity("g", "google", "g"),
                    status=EngineResultStatus.SUCCESS,
                    observation=_obs(), validated=_make_validated_strong(),
                    error=None, elapsed_ms=100,
                ),
            ),
            circuit_rejects=(rejected_id,),
        )
        record = await recorder.record(
            UserId(1), "a" * 64, "astrbot", outcome,
        )
        assert len(record.observations) == 2
        rejected = [o for o in record.observations if o.result_status == "circuit_rejected"]
        assert len(rejected) == 1
        assert rejected[0].engine_id == "z"
        assert rejected[0].provider == "zhipu"
```

- [ ] **Step 2: Run test — fails (module not found)**

Run: `pytest tests/application/test_ocr_run_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement OcrRunRecorder**

Create `pjsk_core/application/ocr_run_recorder.py`:

```python
"""OcrRunRecorder — persist every OCR attempt for audit/debugging."""
from __future__ import annotations

from datetime import datetime, timezone

from pjsk_core.application.vision_race import (
    EngineResultStatus,
    VisionRaceOutcome,
)
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.domain.users import UserId
from pjsk_core.ports.ocr_runs import OcrRunRepository


class OcrRunRecorder:
    """Record every OCR attempt for audit/debugging.

    Call after VisionRace.run() completes, regardless of outcome.
    Returns the persisted OcrRunRecord with database-assigned id.
    """

    def __init__(self, repo: OcrRunRepository) -> None:
        self._repo = repo

    async def record(
        self,
        user_id: UserId,
        image_sha256: str,
        source_gateway: str,
        outcome: VisionRaceOutcome,
    ) -> OcrRunRecord:
        """Build and persist OcrRunRecord from a completed vision race."""
        engine_records: list[OcrEngineRecord] = []

        for result in outcome.results:
            obs = result.observation
            validated = result.validated
            primary = validated.primary if validated else None

            engine_records.append(OcrEngineRecord(
                engine_id=result.identity.engine_id,
                provider=result.identity.provider,
                result_status=result.status.value,
                elapsed_ms=result.elapsed_ms,
                song_title=obs.song_title if obs else None,
                difficulty=obs.difficulty if obs else None,
                displayed_level=obs.displayed_level if obs else None,
                judgements=obs.judgements if obs else None,
                matched_chart_id=(
                    primary.chart.id
                    if primary and primary.chart
                    else None
                ),
                validation_status=(
                    validated.status.value if validated else None
                ),
                error_type=_error_type_from_result(result),
            ))

        # Circuit-rejected engines — never produced an EngineResult
        for identity in outcome.circuit_rejects:
            engine_records.append(OcrEngineRecord(
                engine_id=identity.engine_id,
                provider=identity.provider,
                result_status="circuit_rejected",
                elapsed_ms=0,
                song_title=None, difficulty=None, displayed_level=None,
                judgements=None, matched_chart_id=None,
                validation_status=None, error_type=None,
            ))

        selected_engine: str | None = None
        if outcome.consensus and outcome.consensus.supporting_engines:
            selected_engine = outcome.consensus.supporting_engines[0].engine_id
        elif outcome.selected and outcome.selected.primary:
            # Degraded single — extract from first successful result
            for result in outcome.results:
                if result.status == EngineResultStatus.SUCCESS:
                    selected_engine = result.identity.engine_id
                    break

        record = OcrRunRecord(
            id=None,
            user_id=user_id,
            image_sha256=image_sha256,
            source_gateway=source_gateway,
            final_state=outcome.decision.value,
            selected_engine=selected_engine,
            observations=tuple(engine_records),
            created_at=datetime.now(timezone.utc),
        )
        return await self._repo.save(record)


def _error_type_from_result(result) -> str | None:
    """Extract error_type string from an EngineResult's error."""
    if result.error is None:
        return None
    from pjsk_core.domain.ocr import (
        VisionConnectionError,
        VisionRateLimitError,
        VisionServerError,
        VisionTimeoutError,
    )
    if isinstance(result.error, VisionTimeoutError):
        return "timeout"
    if isinstance(result.error, VisionConnectionError):
        return "connection"
    if isinstance(result.error, VisionRateLimitError):
        return "rate_limited"
    if isinstance(result.error, VisionServerError):
        return "server_error"
    return "invalid_response"
```

- [ ] **Step 4: Run recorder tests — pass**

Run: `pytest tests/application/test_ocr_run_recorder.py -v`
Expected: 3 passed

- [ ] **Step 5: Run full test suite to catch regressions**

Run: `pytest tests/ -q`
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add pjsk_core/application/ocr_run_recorder.py tests/application/test_ocr_run_recorder.py
git commit -m "feat: OcrRunRecorder — audit trail from VisionRaceOutcome"
```

---

### Task 4: SqliteOcrRunRepository adapter

**Files:**
- Create: `adapters/database/ocr_run_repository.py`
- Create: `tests/adapters/database/test_ocr_run_repository.py`

**Interfaces:**
- Consumes: `OcrRunRecord`, `OcrEngineRecord` (Task 2), `OcrRunRepository` (Task 2), `get_connection()` (existing), migration 004 (Task 1)
- Produces: `SqliteOcrRunRepository(db_path: Path)` implementing `OcrRunRepository`

- [ ] **Step 1: Write repository test**

Create `tests/adapters/database/test_ocr_run_repository.py`:

```python
"""Tests for SqliteOcrRunRepository."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from adapters.database.migrator import run_migrations
from adapters.database.ocr_run_repository import SqliteOcrRunRepository
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteOcrRunRepository:
    db = tmp_path / "test.db"
    await run_migrations(db)
    return SqliteOcrRunRepository(db)


class TestSqliteOcrRunRepository:
    async def test_save_and_retrieve(self, repo: SqliteOcrRunRepository) -> None:
        obs = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Test", difficulty=Difficulty.MASTER,
            displayed_level=30,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            matched_chart_id=None, validation_status="strong", error_type=None,
        )
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="a" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine="g",
            observations=(obs,), created_at=datetime.now(timezone.utc),
        )
        saved = await repo.save(record)
        assert saved.id is not None

        fetched = await repo.get_by_id(saved.id)
        assert fetched is not None
        assert fetched.final_state == "consensus"
        assert len(fetched.observations) == 1
        assert fetched.observations[0].result_status == "success"
        assert fetched.observations[0].song_title == "Test"

    async def test_save_multiple_observations(self, repo: SqliteOcrRunRepository) -> None:
        obs_g = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Song A", difficulty=Difficulty.MASTER,
            displayed_level=30,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            matched_chart_id=None, validation_status="strong", error_type=None,
        )
        obs_z = OcrEngineRecord(
            engine_id="z", provider="zhipu", result_status="failed",
            elapsed_ms=5000, song_title=None, difficulty=None,
            displayed_level=None, judgements=None,
            matched_chart_id=None, validation_status=None,
            error_type="timeout",
        )
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="b" * 64, source_gateway="astrbot",
            final_state="disagreement", selected_engine=None,
            observations=(obs_g, obs_z), created_at=datetime.now(timezone.utc),
        )
        saved = await repo.save(record)
        fetched = await repo.get_by_id(saved.id)
        assert fetched is not None
        assert len(fetched.observations) == 2

    async def test_get_by_id_not_found(self, repo: SqliteOcrRunRepository) -> None:
        assert await repo.get_by_id(999) is None

    async def test_rollback_on_error(self, tmp_path: Path) -> None:
        """If observations INSERT fails, ocr_runs row must be rolled back."""
        db = tmp_path / "test.db"
        await run_migrations(db)
        repo = SqliteOcrRunRepository(db)
        # An observation with invalid difficulty should fail the CHECK constraint
        bad_obs = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="Test", difficulty="INVALID",  # type: ignore[arg-type]
            displayed_level=30,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            matched_chart_id=None, validation_status="strong", error_type=None,
        )
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="c" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine="g",
            observations=(bad_obs,), created_at=datetime.now(timezone.utc),
        )
        try:
            await repo.save(record)
        except Exception:
            pass
        # The ocr_runs row should not exist
        assert await repo.get_by_id(1) is None

    async def test_uses_independent_connection(self, tmp_path: Path) -> None:
        """Each save() call creates its own connection — no shared state."""
        db = tmp_path / "test.db"
        await run_migrations(db)
        repo = SqliteOcrRunRepository(db)
        obs = OcrEngineRecord(
            engine_id="g", provider="google", result_status="success",
            elapsed_ms=500, song_title="T", difficulty=Difficulty.EASY,
            displayed_level=1,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            matched_chart_id=None, validation_status="strong", error_type=None,
        )
        record = OcrRunRecord(
            id=None, user_id=UserId(1),
            image_sha256="d" * 64, source_gateway="astrbot",
            final_state="consensus", selected_engine="g",
            observations=(obs,), created_at=datetime.now(timezone.utc),
        )
        # Two concurrent saves should both succeed (independent connections)
        import asyncio
        results = await asyncio.gather(
            repo.save(record),
            repo.save(record),
        )
        assert results[0].id is not None
        assert results[1].id is not None
        assert results[0].id != results[1].id
```

- [ ] **Step 2: Run test — fails (module not found)**

Run: `pytest tests/adapters/database/test_ocr_run_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adapters.database.ocr_run_repository'`

- [ ] **Step 3: Implement SqliteOcrRunRepository**

Create `adapters/database/ocr_run_repository.py`:

```python
"""SQLite-backed OcrRunRepository — independent connections per operation."""
from __future__ import annotations

from pathlib import Path

from adapters.database.connection import get_connection
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId


class SqliteOcrRunRepository:
    """OcrRunRepository backed by independent aiosqlite connections.

    Each ``save()`` opens its own connection so concurrent saves and
    saves interleaved with ScoreRepository operations never conflict.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def save(self, record: OcrRunRecord) -> OcrRunRecord:
        conn = await get_connection(self._db_path)
        try:
            await conn.execute("BEGIN")
            cursor = await conn.execute(
                """INSERT INTO ocr_runs
                   (user_id, image_sha256, source_gateway, final_state,
                    selected_engine, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    record.user_id.value, record.image_sha256,
                    record.source_gateway, record.final_state,
                    record.selected_engine, record.created_at.isoformat(),
                ),
            )
            run_id = cursor.lastrowid
            if run_id is None:
                raise RuntimeError("INSERT did not return a row id")

            for obs in record.observations:
                await conn.execute(
                    """INSERT INTO ocr_observations
                       (ocr_run_id, engine_id, provider, result_status,
                        elapsed_ms, song_title, difficulty, displayed_level,
                        perfect, great, good, bad, miss,
                        matched_chart_id, validation_status, error_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, obs.engine_id, obs.provider,
                        obs.result_status, obs.elapsed_ms,
                        obs.song_title,
                        obs.difficulty.value if obs.difficulty else None,
                        obs.displayed_level,
                        obs.judgements.perfect if obs.judgements else None,
                        obs.judgements.great if obs.judgements else None,
                        obs.judgements.good if obs.judgements else None,
                        obs.judgements.bad if obs.judgements else None,
                        obs.judgements.miss if obs.judgements else None,
                        obs.matched_chart_id, obs.validation_status,
                        obs.error_type,
                    ),
                )

            await conn.commit()
            return OcrRunRecord(
                id=run_id, user_id=record.user_id,
                image_sha256=record.image_sha256,
                source_gateway=record.source_gateway,
                final_state=record.final_state,
                selected_engine=record.selected_engine,
                observations=record.observations,
                created_at=record.created_at,
            )
        except Exception:
            await conn.rollback()
            raise
        finally:
            await conn.close()

    async def get_by_id(self, run_id: int) -> OcrRunRecord | None:
        conn = await get_connection(self._db_path)
        try:
            rows = list(await conn.execute_fetchall(
                "SELECT * FROM ocr_runs WHERE id = ?", (run_id,)
            ))
            if not rows:
                return None
            run_row = rows[0]

            obs_rows = list(await conn.execute_fetchall(
                "SELECT * FROM ocr_observations WHERE ocr_run_id = ? "
                "ORDER BY id", (run_id,)
            ))

            observations = tuple(
                OcrEngineRecord(
                    engine_id=r["engine_id"], provider=r["provider"],
                    result_status=r["result_status"],
                    elapsed_ms=r["elapsed_ms"],
                    song_title=r["song_title"],
                    difficulty=Difficulty(r["difficulty"]) if r["difficulty"] else None,
                    displayed_level=r["displayed_level"],
                    judgements=(
                        Judgements(
                            perfect=r["perfect"], great=r["great"],
                            good=r["good"], bad=r["bad"], miss=r["miss"],
                        )
                        if r["perfect"] is not None
                        else None
                    ),
                    matched_chart_id=r["matched_chart_id"],
                    validation_status=r["validation_status"],
                    error_type=r["error_type"],
                )
                for r in obs_rows
            )

            from datetime import datetime
            return OcrRunRecord(
                id=run_row["id"], user_id=UserId(run_row["user_id"]),
                image_sha256=run_row["image_sha256"],
                source_gateway=run_row["source_gateway"],
                final_state=run_row["final_state"],
                selected_engine=run_row["selected_engine"],
                observations=observations,
                created_at=datetime.fromisoformat(run_row["created_at"]),
            )
        finally:
            await conn.close()
```

- [ ] **Step 4: Run repository tests — pass**

Run: `pytest tests/adapters/database/test_ocr_run_repository.py -v`
Expected: 5 passed

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q && ruff check pjsk_core adapters tools tests && mypy pjsk_core adapters tools tests --strict`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add adapters/database/ocr_run_repository.py tests/adapters/database/test_ocr_run_repository.py
git commit -m "feat: SqliteOcrRunRepository — independent connections, atomic save"
```

---

### Task 5: MemoryCandidateStore adapter

**Files:**
- Create: `adapters/cache/__init__.py` (empty)
- Create: `adapters/cache/memory_candidate_store.py`
- Create: `tests/adapters/cache/__init__.py` (empty)
- Create: `tests/adapters/cache/test_memory_candidate_store.py`

**Interfaces:**
- Consumes: `CandidateStore`, `CandidateSet`, `CandidateConsumeStatus`, `CandidateConsumeResult` (Task 2), `Candidate` (existing), `UserId` (existing)
- Produces: `MemoryCandidateStore()` implementing `CandidateStore`

- [ ] **Step 1: Write adapter test**

Create `tests/adapters/cache/test_memory_candidate_store.py`:

```python
"""Tests for MemoryCandidateStore."""
import asyncio
import time

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import Candidate, OcrObservation
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import (
    CandidateConsumeStatus,
    CandidateSet,
)
from adapters.cache.memory_candidate_store import MemoryCandidateStore


def _candidate(title: str = "Test Song", chart_id: int = 1) -> Candidate:
    return Candidate(
        observation=OcrObservation(
            title, Difficulty.MASTER, 30,
            Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            engine="g", elapsed_ms=100,
        ),
        model_support=2, note_validated=True,
        title_similarity=1.0, note_distance=0,
        matched_chart_id=chart_id,
    )


def _candidate_set() -> CandidateSet:
    return CandidateSet(
        candidates=(_candidate("Song A", 1), _candidate("Song B", 2)),
        image_sha256="a" * 64, source_gateway="astrbot",
        ocr_run_id=1, chart_data_version="v1",
    )


class TestMemoryCandidateStore:
    async def test_put_and_consume_selection_ok(self) -> None:
        store = MemoryCandidateStore()
        cs = _candidate_set()
        cid = await store.put(UserId(1), cs, 300)
        assert cid is not None
        assert len(cid) == 12  # uuid4 hex[:12]

        result = await store.consume_selection(cid, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.OK
        assert result.candidate is not None
        assert result.candidate.matched_chart_id == 1
        assert result.candidate_set is not None

    async def test_consume_twice_returns_not_found(self) -> None:
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), 300)
        await store.consume_selection(cid, UserId(1), 1)
        result = await store.consume_selection(cid, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.NOT_FOUND

    async def test_wrong_user_returns_forbidden(self) -> None:
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), 300)
        result = await store.consume_selection(cid, UserId(2), 1)
        assert result.status == CandidateConsumeStatus.FORBIDDEN
        # Original owner can still consume
        result2 = await store.consume_selection(cid, UserId(1), 1)
        assert result2.status == CandidateConsumeStatus.OK

    async def test_invalid_selection_does_not_delete(self) -> None:
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), 300)
        result = await store.consume_selection(cid, UserId(1), 99)
        assert result.status == CandidateConsumeStatus.INVALID_SELECTION
        # Entry still exists — user can retry
        result2 = await store.consume_selection(cid, UserId(1), 1)
        assert result2.status == CandidateConsumeStatus.OK

    async def test_expired_returns_expired_and_deletes(self) -> None:
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), ttl_seconds=0)
        # Force expiry by waiting slightly — TTL 0 means already expired
        await asyncio.sleep(0.01)
        result = await store.consume_selection(cid, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.EXPIRED
        # Second call returns NOT_FOUND (deleted on expiry check)
        result2 = await store.consume_selection(cid, UserId(1), 1)
        assert result2.status == CandidateConsumeStatus.NOT_FOUND

    async def test_put_sweeps_expired_entries(self) -> None:
        store = MemoryCandidateStore()
        # Put with 0 TTL — expires immediately
        cid = await store.put(UserId(1), _candidate_set(), ttl_seconds=0)
        await asyncio.sleep(0.01)
        # Put another — should sweep the expired one
        cid2 = await store.put(UserId(2), _candidate_set(), 300)
        # Expired entry should be gone
        result = await store.consume_selection(cid, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.NOT_FOUND
        # New entry should still be there
        result2 = await store.consume_selection(cid2, UserId(2), 1)
        assert result2.status == CandidateConsumeStatus.OK

    async def test_evicts_oldest_when_full(self) -> None:
        store = MemoryCandidateStore(max_entries=2)
        cid1 = await store.put(UserId(1), _candidate_set(), 300)
        await asyncio.sleep(0.01)  # ensure different expiry times
        cid2 = await store.put(UserId(1), _candidate_set(), 300)
        # Third put should evict cid1 (oldest)
        cid3 = await store.put(UserId(1), _candidate_set(), 300)
        assert await store.consume_selection(cid1, UserId(1), 1) is not None
        # Actually cid1 should be NOT_FOUND since it was evicted
        result = await store.consume_selection(cid1, UserId(1), 1)
        assert result.status == CandidateConsumeStatus.NOT_FOUND
        # cid2 and cid3 should still be accessible
        r2 = await store.consume_selection(cid2, UserId(1), 1)
        assert r2.status == CandidateConsumeStatus.OK

    async def test_nonexistent_id_returns_not_found(self) -> None:
        store = MemoryCandidateStore()
        result = await store.consume_selection("nonexistent", UserId(1), 1)
        assert result.status == CandidateConsumeStatus.NOT_FOUND

    async def test_concurrent_consume_atomic(self) -> None:
        """Two concurrent consumes — only one succeeds."""
        store = MemoryCandidateStore()
        cid = await store.put(UserId(1), _candidate_set(), 300)

        async def consume() -> CandidateConsumeStatus:
            result = await store.consume_selection(cid, UserId(1), 1)
            return result.status

        results = await asyncio.gather(consume(), consume())
        oks = [r for r in results if r == CandidateConsumeStatus.OK]
        not_founds = [r for r in results if r == CandidateConsumeStatus.NOT_FOUND]
        assert len(oks) == 1
        assert len(not_founds) == 1
```

- [ ] **Step 2: Run test — fails (module not found)**

Run: `pytest tests/adapters/cache/test_memory_candidate_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement MemoryCandidateStore**

Create `adapters/cache/__init__.py` (empty) and `adapters/cache/memory_candidate_store.py`:

```python
"""In-memory CandidateStore — dict-backed with asyncio.Lock, expiry sweep on put."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from pjsk_core.domain.ocr import Candidate
from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import (
    CandidateConsumeResult,
    CandidateConsumeStatus,
    CandidateSet,
)


@dataclass
class _Entry:
    candidate_set: CandidateSet
    user_id: UserId
    expires_at: float  # monotonic timestamp


class MemoryCandidateStore:
    """In-memory single-consumption candidate storage.

    No external dependencies. Restart loses all pending candidates
    (acceptable — this is a cache, not persistence).

    Expired entries are swept on ``put()``. When the entry count
    reaches ``max_entries``, the entry with the earliest expiry is
    evicted before inserting the new one.
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max_entries

    async def put(
        self,
        user_id: UserId,
        candidate_set: CandidateSet,
        ttl_seconds: int,
    ) -> str:
        cid = uuid.uuid4().hex[:12]
        now = time.monotonic()
        async with self._lock:
            # Sweep expired entries
            expired = [
                k for k, v in self._entries.items()
                if now > v.expires_at
            ]
            for k in expired:
                del self._entries[k]
            # Evict oldest if at capacity
            if len(self._entries) >= self._max_entries:
                oldest = min(
                    self._entries.keys(),
                    key=lambda k: self._entries[k].expires_at,
                )
                del self._entries[oldest]
            self._entries[cid] = _Entry(
                candidate_set=candidate_set,
                user_id=user_id,
                expires_at=now + ttl_seconds,
            )
        return cid

    async def consume_selection(
        self,
        candidate_set_id: str,
        user_id: UserId,
        selection: int,
    ) -> CandidateConsumeResult:
        async with self._lock:
            # 1. Check existence — BEFORE any mutation
            entry = self._entries.get(candidate_set_id)
            if entry is None:
                return CandidateConsumeResult(
                    status=CandidateConsumeStatus.NOT_FOUND,
                    candidate=None, candidate_set=None,
                )
            # 2. Check ownership — BEFORE delete
            if entry.user_id != user_id:
                return CandidateConsumeResult(
                    status=CandidateConsumeStatus.FORBIDDEN,
                    candidate=None, candidate_set=None,
                )
            # 3. Check expiry
            if time.monotonic() > entry.expires_at:
                del self._entries[candidate_set_id]
                return CandidateConsumeResult(
                    status=CandidateConsumeStatus.EXPIRED,
                    candidate=None, candidate_set=None,
                )
            # 4. Check selection bounds
            cs = entry.candidate_set
            if selection < 1 or selection > len(cs.candidates):
                return CandidateConsumeResult(
                    status=CandidateConsumeStatus.INVALID_SELECTION,
                    candidate=None, candidate_set=None,
                )
            # 5. All checks passed — atomically delete and return
            del self._entries[candidate_set_id]
            return CandidateConsumeResult(
                status=CandidateConsumeStatus.OK,
                candidate=cs.candidates[selection - 1],
                candidate_set=cs,
            )
```

- [ ] **Step 4: Run adapter tests — pass**

Run: `pytest tests/adapters/cache/test_memory_candidate_store.py -v`
Expected: all 8 pass

- [ ] **Step 5: Commit**

```bash
git add adapters/cache/__init__.py adapters/cache/memory_candidate_store.py tests/adapters/cache/
git commit -m "feat: MemoryCandidateStore — atomic consume_selection, expiry sweep, eviction"
```

---

### Task 6: ConfirmCandidate use case

**Files:**
- Create: `pjsk_core/application/confirm_candidate.py`
- Create: `tests/application/test_confirm_candidate.py`

**Interfaces:**
- Consumes: `CandidateStore`, `CandidateConsumeStatus`, `CandidateSet` (Task 2), `ScoreRepository`, `ChartRepository` (existing), `Candidate` (existing domain), `calculate_accuracy`, `classify_status` (existing domain), `calculate_rating` (existing domain)
- Produces:
  - `ConfirmError(Enum): NOT_FOUND, EXPIRED, FORBIDDEN, INVALID_SELECTION, NOT_CONFIRMABLE`
  - `ConfirmResult(score_attempt: ScoreAttempt | None, error: ConfirmError | None)`
  - `ConfirmCandidate(store, scores, charts, clock?).confirm(user_id, candidate_set_id, selection) -> ConfirmResult`

- [ ] **Step 1: Write ConfirmCandidate test**

Create `tests/application/test_confirm_candidate.py`:

```python
"""Tests for ConfirmCandidate — user selection → score recording."""
import asyncio
from datetime import datetime, timezone

from pjsk_core.application.confirm_candidate import (
    ConfirmCandidate,
    ConfirmError,
)
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import Candidate, OcrObservation
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import (
    CandidateConsumeResult,
    CandidateConsumeStatus,
    CandidateSet,
    CandidateStore,
)
from pjsk_core.ports.repositories import ChartRepository, ScoreRepository


# ── Fakes ──────────────────────────────────────────────────────────────

class _FakeCandidateStore:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[UserId, CandidateSet]] = {}
        self._lock = asyncio.Lock()

    async def put(self, user_id: UserId, cs: CandidateSet, ttl: int) -> str:
        key = f"cs-{len(self._entries)}"
        async with self._lock:
            self._entries[key] = (user_id, cs)
        return key

    async def consume_selection(
        self, cid: str, user_id: UserId, selection: int,
    ) -> CandidateConsumeResult:
        async with self._lock:
            entry = self._entries.pop(cid, None)
        if entry is None:
            return CandidateConsumeResult(
                CandidateConsumeStatus.NOT_FOUND, None, None)
        owner, cs = entry
        if owner != user_id:
            return CandidateConsumeResult(
                CandidateConsumeStatus.FORBIDDEN, None, None)
        if selection < 1 or selection > len(cs.candidates):
            return CandidateConsumeResult(
                CandidateConsumeStatus.INVALID_SELECTION, None, None)
        return CandidateConsumeResult(
            CandidateConsumeStatus.OK,
            cs.candidates[selection - 1], cs)


class _FakeScoreRepo:
    def __init__(self) -> None:
        self.recorded: list[ScoreAttempt] = []

    async def record_attempt(self, a: ScoreAttempt) -> ScoreAttempt:
        self.recorded.append(a)
        return a

    async def get_personal_best(self, uid: UserId, cid: int) -> ScoreAttempt | None:
        return None

    async def list_personal_bests(
        self, uid: UserId, sf: set[ScoreStatus] | None = None,
    ) -> list[ScoreAttempt]:
        return []


class _FakeChartRepo:
    def __init__(self, chart: Chart | None = None) -> None:
        self._chart = chart or Chart(
            id=1, song_id=1, difficulty=Difficulty.MASTER,
            official_level=30, community_constant="30.5",
            note_count=1100, data_version="v1",
        )

    async def get_by_id(self, chart_id: int) -> Chart | None:
        if chart_id == self._chart.id:
            return self._chart
        return None

    async def find_by_song_and_difficulty(
        self, title: str, diff: Difficulty,
    ) -> Chart | None:
        return None

    async def list_by_difficulty_level(
        self, diff: Difficulty, level: int,
    ) -> list[Chart]:
        return []

    async def get_song_catalog(self):
        from pjsk_core.domain.song_matcher import SongCandidate
        from pjsk_core.ports.repositories import SongCatalog
        return SongCatalog(version="v1", candidates=())

    async def get_by_song_and_difficulty(
        self, song_id: int, diff: Difficulty,
    ) -> Chart | None:
        return None


# ── Helpers ────────────────────────────────────────────────────────────

def _candidate(chart_id: int = 1, note_validated: bool = True) -> Candidate:
    return Candidate(
        observation=OcrObservation(
            "Test Song", Difficulty.MASTER, 30,
            Judgements(perfect=1000, great=100, good=0, bad=0, miss=0),
            engine="g", elapsed_ms=100,
        ),
        model_support=2, note_validated=note_validated,
        title_similarity=1.0, note_distance=0, matched_chart_id=chart_id,
    )


def _cs(candidates: tuple[Candidate, ...] | None = None) -> CandidateSet:
    if candidates is None:
        candidates = (_candidate(),)
    return CandidateSet(
        candidates=candidates, image_sha256="a" * 64,
        source_gateway="astrbot", ocr_run_id=1, chart_data_version="v1",
    )


# ── Tests ──────────────────────────────────────────────────────────────

class TestConfirmCandidate:
    async def test_confirm_records_score(self) -> None:
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()
        cc = ConfirmCandidate(store, scores, charts)  # type: ignore[arg-type]
        cs_ = _cs()
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error is None
        assert result.score_attempt is not None
        assert result.score_attempt.chart_id == 1
        assert result.score_attempt.ocr_run_id == 1
        assert result.score_attempt.source_gateway == "astrbot"
        assert len(scores.recorded) == 1

    async def test_not_found(self) -> None:
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()
        cc = ConfirmCandidate(store, scores, charts)  # type: ignore[arg-type]
        result = await cc.confirm(UserId(1), "nonexistent", 1)
        assert result.error == ConfirmError.NOT_FOUND
        assert result.score_attempt is None

    async def test_fails_not_confirmable_no_chart(self) -> None:
        """Candidate with chart_id=None is not confirmable."""
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()
        cc = ConfirmCandidate(store, scores, charts)  # type: ignore[arg-type]
        bad = Candidate(
            observation=OcrObservation(
                "X", Difficulty.MASTER, 30,
                Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
                engine="g", elapsed_ms=100,
            ),
            model_support=1, note_validated=True,
            title_similarity=0.5, note_distance=0, matched_chart_id=None,
        )
        cs_ = _cs((bad,))
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error == ConfirmError.NOT_CONFIRMABLE

    async def test_fails_not_confirmable_note_mismatch(self) -> None:
        """Candidate with |notes - expected| > 1 is not confirmable."""
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()  # chart has note_count=1100
        cc = ConfirmCandidate(store, scores, charts)  # type: ignore[arg-type]
        # judgements sum = 10, chart note_count = 1100 → diff = 1090 > 1
        bad = _candidate(note_validated=False)
        cs_ = _cs((bad,))
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error == ConfirmError.NOT_CONFIRMABLE

    async def test_fails_not_confirmable_wrong_difficulty(self) -> None:
        """Candidate difficulty != chart difficulty → not confirmable."""
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        # Chart is MASTER, but candidate says EXPERT
        chart = Chart(
            id=1, song_id=1, difficulty=Difficulty.MASTER,
            official_level=30, community_constant="30.5",
            note_count=1100, data_version="v1",
        )
        charts = _FakeChartRepo(chart)
        cc = ConfirmCandidate(store, scores, charts)  # type: ignore[arg-type]
        bad = Candidate(
            observation=OcrObservation(
                "X", Difficulty.EXPERT, 25,
                Judgements(perfect=1100, great=0, good=0, bad=0, miss=0),
                engine="g", elapsed_ms=100,
            ),
            model_support=1, note_validated=True,
            title_similarity=0.5, note_distance=0, matched_chart_id=1,
        )
        cs_ = _cs((bad,))
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error == ConfirmError.NOT_CONFIRMABLE

    async def test_confirm_with_chart_not_found(self) -> None:
        """chart_id doesn't exist in database → not confirmable."""
        store = _FakeCandidateStore()
        scores = _FakeScoreRepo()
        charts = _FakeChartRepo()  # only chart_id=1 exists
        cc = ConfirmCandidate(store, scores, charts)  # type: ignore[arg-type]
        bad = _candidate(chart_id=999)
        cs_ = _cs((bad,))
        cid = await store.put(UserId(1), cs_, 300)
        result = await cc.confirm(UserId(1), cid, 1)
        assert result.error == ConfirmError.NOT_CONFIRMABLE
```

- [ ] **Step 2: Run test — fails (module not found)**

Run: `pytest tests/application/test_confirm_candidate.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ConfirmCandidate**

Create `pjsk_core/application/confirm_candidate.py`:

```python
"""ConfirmCandidate — resolve a disagreeing OCR run by user selection."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pjsk_core.domain.scores import (
    Judgements,
    ScoreAttempt,
    calculate_accuracy,
    classify_status,
)
from pjsk_core.domain.rating import calculate_rating
from pjsk_core.domain.users import UserId
from pjsk_core.ports.cache import CandidateConsumeStatus, CandidateStore
from pjsk_core.ports.repositories import ChartRepository, ScoreRepository


class ConfirmError(Enum):
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    FORBIDDEN = "forbidden"
    INVALID_SELECTION = "invalid_selection"
    NOT_CONFIRMABLE = "not_confirmable"


@dataclass(frozen=True)
class ConfirmResult:
    score_attempt: ScoreAttempt | None
    error: ConfirmError | None


class ConfirmCandidate:
    """Resolve a disagreeing OCR run by user candidate selection.

    Validates the selected candidate against live chart data before
    recording — the user can decide which song this is, but cannot
    override note-count or difficulty mismatches.
    """

    def __init__(
        self,
        store: CandidateStore,
        scores: ScoreRepository,
        charts: ChartRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._scores = scores
        self._charts = charts
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def confirm(
        self,
        user_id: UserId,
        candidate_set_id: str,
        selection: int,
    ) -> ConfirmResult:
        consume_result = await self._store.consume_selection(
            candidate_set_id, user_id, selection,
        )

        # Map store status to ConfirmError
        status_map = {
            CandidateConsumeStatus.NOT_FOUND: ConfirmError.NOT_FOUND,
            CandidateConsumeStatus.EXPIRED: ConfirmError.EXPIRED,
            CandidateConsumeStatus.FORBIDDEN: ConfirmError.FORBIDDEN,
            CandidateConsumeStatus.INVALID_SELECTION: ConfirmError.INVALID_SELECTION,
        }
        if consume_result.status in status_map:
            return ConfirmResult(None, status_map[consume_result.status])

        # OK — validate confirmability
        candidate = consume_result.candidate
        cs = consume_result.candidate_set
        if candidate is None or cs is None:
            return ConfirmResult(None, ConfirmError.NOT_FOUND)

        # 1. Must have a matched chart
        if candidate.matched_chart_id is None:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # 2. Note validation must have passed
        if not candidate.note_validated:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # 3. Chart must still exist
        chart = await self._charts.get_by_id(candidate.matched_chart_id)
        if chart is None:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # 4. Difficulty must match
        if candidate.observation.difficulty != chart.difficulty:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # 5. Note count ±1
        total_judges = sum([
            candidate.observation.judgements.perfect,
            candidate.observation.judgements.great,
            candidate.observation.judgements.good,
            candidate.observation.judgements.bad,
            candidate.observation.judgements.miss,
        ])
        if abs(total_judges - chart.note_count) > 1:
            return ConfirmResult(None, ConfirmError.NOT_CONFIRMABLE)

        # Construct and record ScoreAttempt
        judgements = candidate.observation.judgements
        status = classify_status(judgements)
        accuracy = calculate_accuracy(judgements)
        rating = calculate_rating(
            chart.official_level, chart.community_constant,
            status, accuracy, chart.difficulty,
        )
        now = self._clock()
        attempt = ScoreAttempt(
            id=None, user_id=user_id, chart_id=chart.id,
            judgements=judgements, accuracy=accuracy,
            rating=rating, status=status,
            image_sha256=cs.image_sha256,
            source_gateway=cs.source_gateway,
            ocr_run_id=cs.ocr_run_id,
            created_at=now,
        )
        recorded = await self._scores.record_attempt(attempt)
        return ConfirmResult(recorded, None)
```

- [ ] **Step 4: Run ConfirmCandidate tests — pass**

Run: `pytest tests/application/test_confirm_candidate.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add pjsk_core/application/confirm_candidate.py tests/application/test_confirm_candidate.py
git commit -m "feat: ConfirmCandidate — user selection with chart validation"
```

---

### Task 7: RecognizeScore revision — wire in recorder and store

**Files:**
- Modify: `pjsk_core/application/recognize_score.py` — add recorder + store + charts dependencies, ocr_run_id flow, candidate_set_id in result
- Modify: `tests/application/test_recognize_score.py` — update constructor calls and assertions

**Interfaces:**
- Consumes: `OcrRunRecorder` (Task 3), `CandidateStore`, `CandidateSet` (Task 2), `ChartRepository` (existing), `VisionRace`, `ScoreRepository` (existing)
- Produces: `RecognizeScore(race, scores, recorder, store, charts, *, candidate_ttl_seconds=300, clock=None)`, `RecognizeResult` with `candidate_set_id: str | None`

- [ ] **Step 1: Update test file — add new fakes and update constructor calls**

In `tests/application/test_recognize_score.py`:

Add new fake classes after `_FakeScoreRepo`:

```python
class _FakeOcrRunRecorder:
    """Fake OcrRunRecorder — returns a record with id=42."""
    def __init__(self) -> None:
        self.recorded: list = []

    async def record(self, user_id, image_sha256, source_gateway, outcome):
        from pjsk_core.domain.ocr_runs import OcrRunRecord
        from datetime import datetime, timezone
        record = OcrRunRecord(
            id=42, user_id=user_id, image_sha256=image_sha256,
            source_gateway=source_gateway,
            final_state=outcome.decision.value if hasattr(outcome.decision, 'value') else str(outcome.decision),
            selected_engine=None, observations=(),
            created_at=datetime.now(timezone.utc),
        )
        self.recorded.append(record)
        return record


class _FakeCandidateStore:
    def __init__(self) -> None:
        self.put_calls: list = []

    async def put(self, user_id, candidate_set, ttl_seconds) -> str:
        self.put_calls.append((user_id, candidate_set, ttl_seconds))
        return "cs-test-123"

    async def consume_selection(self, candidate_set_id, user_id, selection):
        raise NotImplementedError("Not needed for RecognizeScore tests")


class _FakeChartRepo:
    async def get_song_catalog(self):
        from pjsk_core.domain.song_matcher import SongCandidate
        from pjsk_core.ports.repositories import SongCatalog
        return SongCatalog(version="v1", candidates=())

    async def get_by_id(self, chart_id):
        return None  # not needed for consensus tests
```

Update every `RecognizeScore(race, repo)` call to include new dependencies:

```python
recorder = _FakeOcrRunRecorder()
store = _FakeCandidateStore()
charts = _FakeChartRepo()
recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
```

This pattern applies to all existing tests in the class. The `_FakeVisionRace` and `_FakeScoreRepo` remain unchanged.

Also update `_make_strong_candidate` — remove `kind` parameter if present (shouldn't be — just verify).

- [ ] **Step 2: Run tests — fail (constructor signature mismatch)**

Run: `pytest tests/application/test_recognize_score.py -v`
Expected: FAIL — `TypeError: RecognizeScore.__init__() takes N positional arguments but M were given`

- [ ] **Step 3: Revise RecognizeScore**

Modify `pjsk_core/application/recognize_score.py`:

Update `RecognizeResult` — add `candidate_set_id`:

```python
@dataclass(frozen=True)
class RecognizeResult:
    outcome: VisionRaceOutcome
    validated: ValidatedObservation | None
    candidates_for_user: tuple[Candidate, ...]
    candidate_set_id: str | None       # NEW
    score_attempt: ScoreAttempt | None
```

Update constructor:

```python
class RecognizeScore:
    def __init__(
        self,
        race: VisionRace,
        scores: ScoreRepository,
        recorder: OcrRunRecorder,                     # NEW
        store: CandidateStore,                        # NEW
        charts: ChartRepository,                      # NEW
        *,
        candidate_ttl_seconds: int = 300,             # NEW
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._race = race
        self._scores = scores
        self._recorder = recorder
        self._store = store
        self._charts = charts
        self._candidate_ttl_seconds = candidate_ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
```

Update `recognize()` method — add OCR run recording at start, ocr_run_id flow, candidate storage:

```python
async def recognize(self, user_id, image, *, source_gateway) -> RecognizeResult:
    image_sha256 = hashlib.sha256(image).hexdigest()
    outcome = await self._race.run(image)

    # Record OCR run. On failure: warn and continue with ocr_run_id=None.
    ocr_run_id: int | None = None
    try:
        ocr_run = await self._recorder.record(
            user_id, image_sha256, source_gateway, outcome,
        )
        ocr_run_id = ocr_run.id
    except Exception:
        import logging
        _logger = logging.getLogger(__name__)
        _logger.warning(
            "Failed to persist OCR run for user=%s sha256=%s",
            user_id, image_sha256[:16],
        )

    if outcome.decision in (
        VisionRaceDecision.CONSENSUS,
        VisionRaceDecision.DEGRADED_SINGLE,
    ):
        selected = outcome.selected
        if selected is None or selected.primary is None:
            return RecognizeResult(
                outcome=outcome, validated=selected,
                candidates_for_user=(), candidate_set_id=None,
                score_attempt=None,
            )
        attempt = await self._record(
            selected, user_id, image_sha256, source_gateway, ocr_run_id,
        )
        return RecognizeResult(
            outcome=outcome, validated=selected,
            candidates_for_user=(), candidate_set_id=None,
            score_attempt=attempt,
        )

    if outcome.decision == VisionRaceDecision.DISAGREEMENT:
        candidates = self._collect_candidates(outcome)
        catalog = await self._charts.get_song_catalog()
        cs = CandidateSet(
            candidates=candidates,
            image_sha256=image_sha256,
            source_gateway=source_gateway,
            ocr_run_id=ocr_run_id if ocr_run_id is not None else 0,
            chart_data_version=catalog.version,
        )
        cid = await self._store.put(
            user_id, cs, ttl_seconds=self._candidate_ttl_seconds,
        )
        return RecognizeResult(
            outcome=outcome, validated=outcome.selected,
            candidates_for_user=candidates,
            candidate_set_id=cid,
            score_attempt=None,
        )

    if outcome.decision == VisionRaceDecision.GLOBAL_TIMEOUT:
        if outcome.selected is not None:
            return await self._adopt_timeout_result(
                outcome, user_id, image_sha256, source_gateway, ocr_run_id,
            )
        candidates = self._collect_candidates(outcome)
        return RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=candidates, candidate_set_id=None,
            score_attempt=None,
        )

    return RecognizeResult(
        outcome=outcome, validated=None,
        candidates_for_user=(), candidate_set_id=None,
        score_attempt=None,
    )
```

Update `_record()` — add `ocr_run_id` parameter:

```python
async def _record(
    self,
    selected: ValidatedObservation,
    user_id: UserId,
    image_sha256: str,
    source_gateway: str,
    ocr_run_id: int | None,
) -> ScoreAttempt:
    primary = selected.primary
    if primary is None:
        raise RuntimeError("Cannot record: selected has no primary candidate")
    chart = primary.chart
    if chart is None:
        raise RuntimeError("Cannot record: primary candidate has no chart")
    obs = selected.observation
    judgements = obs.judgements
    status = classify_status(judgements)
    accuracy = calculate_accuracy(judgements)
    rating = calculate_rating(
        chart.official_level, chart.community_constant,
        status, accuracy, chart.difficulty,
    )
    now = self._clock()
    attempt = ScoreAttempt(
        id=None, user_id=user_id, chart_id=chart.id,
        judgements=judgements, accuracy=accuracy,
        rating=rating, status=status,
        image_sha256=image_sha256, source_gateway=source_gateway,
        ocr_run_id=ocr_run_id,
        created_at=now,
    )
    return await self._scores.record_attempt(attempt)
```

Update `_adopt_timeout_result()` — add `ocr_run_id` parameter:

```python
async def _adopt_timeout_result(
    self, outcome, user_id, image_sha256, source_gateway, ocr_run_id,
) -> RecognizeResult:
    if (outcome.selected is None
            or outcome.selected.status != ValidationStatus.STRONG):
        return RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=(), candidate_set_id=None,
            score_attempt=None,
        )
    attempt = await self._record(
        outcome.selected, user_id, image_sha256, source_gateway, ocr_run_id,
    )
    return RecognizeResult(
        outcome=outcome, validated=outcome.selected,
        candidates_for_user=(), candidate_set_id=None,
        score_attempt=attempt,
    )
```

Add required imports at top:

```python
import logging

from pjsk_core.application.ocr_run_recorder import OcrRunRecorder
from pjsk_core.ports.cache import CandidateSet, CandidateStore
from pjsk_core.ports.repositories import ChartRepository
```

- [ ] **Step 4: Run RecognizeScore tests — pass**

Run: `pytest tests/application/test_recognize_score.py -v`
Expected: all 8 pass (updated constructor)

- [ ] **Step 5: Add new tests for ocr_run_id flow and candidate store integration**

Add to `tests/application/test_recognize_score.py`:

```python
    async def test_consensus_sets_ocr_run_id(self) -> None:
        """On CONSENSUS, ScoreAttempt.ocr_run_id comes from recorded OCR run."""
        validated = _make_validated_strong()
        outcome = _make_outcome(VisionRaceDecision.CONSENSUS, selected=validated)
        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(UserId(1), b"img", source_gateway="astrbot")
        assert result.score_attempt is not None
        assert result.score_attempt.ocr_run_id == 42

    async def test_disagreement_stores_candidates(self) -> None:
        """DISAGREEMENT stores candidates and returns candidate_set_id."""
        obs1 = OcrObservation(
            "Song A", Difficulty.MASTER, 30,
            Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            engine="g", elapsed_ms=100,
        )
        obs2 = OcrObservation(
            "Song B", Difficulty.MASTER, 30,
            Judgements(perfect=500, great=500, good=0, bad=0, miss=0),
            engine="z", elapsed_ms=100,
        )
        chart = _make_chart()
        sm = SongMatch(song_id=1, score=1.0, method=SongMatchMethod.EXACT, source=TitleSource.JAPANESE)
        vc = ValidatedCandidate(
            song_match=sm, chart=chart, note_distance=0,
            note_validated=True, level_validated=True,
            status=ValidationStatus.STRONG,
        )
        valid = ValidatedObservation(
            observation=obs1, primary=vc, candidates=(vc,),
            status=ValidationStatus.STRONG,
        )
        results = (
            EngineResult(
                EngineIdentity("g", "google", "g"),
                EngineResultStatus.SUCCESS, obs1, valid, None, 100,
            ),
            EngineResult(
                EngineIdentity("z", "zhipu", "z"),
                EngineResultStatus.SUCCESS, obs2, valid, None, 100,
            ),
        )
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.DISAGREEMENT,
            selected=None, consensus=None,
            results=results, circuit_rejects=(),
        )
        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recorder = _FakeOcrRunRecorder()
        store = _FakeCandidateStore()
        charts = _FakeChartRepo()
        recognize = RecognizeScore(race, repo, recorder, store, charts)  # type: ignore[arg-type]
        result = await recognize.recognize(UserId(1), b"img", source_gateway="astrbot")
        assert result.candidate_set_id == "cs-test-123"
        assert len(result.candidates_for_user) > 0
        assert result.score_attempt is None
        assert len(store.put_calls) == 1
```

- [ ] **Step 6: Run all RecognizeScore tests — all pass**

Run: `pytest tests/application/test_recognize_score.py -v`
Expected: 10 passed (8 original + 2 new)

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -q && ruff check pjsk_core adapters tools tests && mypy pjsk_core adapters tools tests --strict`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add pjsk_core/application/recognize_score.py tests/application/test_recognize_score.py
git commit -m "feat: wire OcrRunRecorder + CandidateStore into RecognizeScore"
```

---

### Task 8: Final integration — migrator test updates + port contract cleanup + full regression

**Files:**
- Modify: `tests/adapters/database/test_migrator.py` — `expected` set in `test_applies_initial_migration` (add `ocr_runs`, `ocr_observations`)
- Modify: `tests/test_port_contracts.py` — ensure all contracts pass with new types
- Verify: `pyproject.toml` — `adapters.cache*` in packages (if not already covered by `adapters*`)

**Interfaces:**
- Consumes: all tasks above
- Produces: clean test suite, updated assertions

- [ ] **Step 1: Update `test_applies_initial_migration`**

In `tests/adapters/database/test_migrator.py`, the `expected` set currently expects `schema_version`, `users`, `external_identities`, `songs`, `charts`, `score_attempts`, `personal_bests`. Add the two new tables:

```python
expected = {"schema_version", "users", "external_identities",
            "songs", "charts", "score_attempts", "personal_bests",
            "ocr_runs", "ocr_observations"}
```

- [ ] **Step 2: Verify pyproject.toml packages**

Run: `grep -n "adapters" pyproject.toml`
Expected: `"adapters*"` covers `adapters.cache` and `adapters.database` packages.

If `adapters*` is not present (it was added in Phase 3a R2 for wheel builds), add it:
```
packages = ["pjsk_core", "adapters", "adapters.database", "adapters.vision", "adapters.resilience", "adapters.config", "adapters.cache", "plugin", "tools"]
```

- [ ] **Step 3: Run full regression**

Run: `pytest tests/ -q`
Expected: all tests pass (baseline 296 + new tests)

Run: `ruff check pjsk_core adapters tools tests`
Expected: All checks passed!

Run: `mypy pjsk_core adapters tools tests --strict`
Expected: Success: no issues found

- [ ] **Step 4: Commit**

```bash
git add tests/adapters/database/test_migrator.py tests/test_port_contracts.py
git commit -m "test: finalize Phase 3b — migrator assertions, port contracts, full regression"
```
