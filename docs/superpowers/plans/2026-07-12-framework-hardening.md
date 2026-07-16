> **Status: Approved** (core layer — still valid under Phase 5 standalone direction).
> The domain, application, ports, and adapter designs in this document remain authoritative for `pjsk_core` and `adapters/`.
> Current governance: `CLAUDE.md`. Phase-5 gateway design: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`.

# Framework Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the "container" — plugin shell, domain data types, port contracts, reply types, and gateway adapter structure — before extracting any business logic from the old `emu-bot`.

**Architecture:** Inside-out: domain data classes → reply types → ports → gateway signatures. The AstrBot plugin entry point (`main.py` + `metadata.yaml`) goes first because it's purely mechanical with zero dependencies. Every task follows TDD: write the failing test, run it red, implement the minimum, run it green, commit.

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio, ruff, mypy strict, dataclasses, typing.Protocol, datetime.

## Global Constraints

- Domain code is synchronous, pure, no I/O — enforced by existing boundary tests.
- No business logic (accuracy, rating, B20, song matching) in this phase.
- No placeholder functions or fake implementations — only real types and contracts.
- Every task ends in a focused commit.
- `plugin/` in the architecture diagram refers to AstrBot-facing code at repo root (`main.py`, `metadata.yaml`) plus the `plugin/` subdirectory for handler modules.
- AstrBot plugins load from `AstrBot/data/plugins/<name>/`; `main.py` and `metadata.yaml` must be at repo root.
- Ruff and mypy strict must pass at the end of every task.

---

## File Structure Map

```
repo_root/                          ← AstrBot plugin root
  metadata.yaml                     ← Task 1: AstrBot plugin metadata
  main.py                           ← Task 1: Star subclass entry point
  pyproject.toml                    ← existing, may need minor updates
  pjsk_core/
    __init__.py                     ← existing
    domain/
      __init__.py                   ← existing
      users.py                      ← Task 2: UserId, QqNumber, User
      charts.py                     ← Task 3: Difficulty, Chart
      scores.py                     ← Task 4: ScoreStatus, Judgements, ScoreAttempt
      ocr.py                        ← Task 5: OcrObservation
    application/
      __init__.py                   ← existing
      replies.py                    ← Task 6: TextReply, ImageReply, CandidateReply, ProgressReply, ErrorReply
    ports/
      __init__.py                   ← existing
      repositories.py               ← Task 7: UserRepository, ChartRepository, ScoreRepository
      vision.py                     ← Task 7: VisionEngine
      renderer.py                   ← Task 7: Renderer, RenderRequest, RenderResult
      identity.py                   ← Task 7: IdentityResolver
      cache.py                      ← Task 7: CandidateStore
  adapters/
    __init__.py                     ← Task 8
    gateways/
      __init__.py                   ← Task 8
      astrbot/
        __init__.py                 ← Task 8
        event_converter.py          ← Task 8: docstring only, no implementations
        reply_mapper.py             ← Task 8: docstring only, no implementations
  tests/
    __init__.py                     ← existing
    test_package_boundaries.py      ← existing, must keep passing
    domain/
      __init__.py                   ← Task 2
      test_users.py                 ← Task 2
      test_charts.py                ← Task 3
      test_scores.py                ← Task 4
      test_ocr.py                   ← Task 5
    test_reply_types.py             ← Task 6
    test_port_contracts.py          ← Task 7
```

### Dependency Order

```
Task 1 (plugin shell)
  ↓
Task 2 (users)
  ↓
Task 3 (charts)
  ↓
Task 4 (scores) ── depends on Task 2 (UserId)
  ↓
Task 5 (ocr) ── depends on Task 3 (Difficulty) + Task 4 (Judgements)
  ↓
Task 6 (replies) ── depends on Task 5 (OcrObservation)
  ↓
Task 7 (ports) ── depends on Tasks 2-6 (all domain + reply types)
  ↓
Task 8 (gateway adapter) ── directory structure only
  ↓
Task 9 (final verification)
```

---

### Task 1: AstrBot Plugin Shell

**Files:**
- Create: `metadata.yaml`
- Create: `main.py`

**Interfaces:**
- Produces: AstrBot-loadable plugin with zero registered commands. `MyPlugin` class extends `Star`, has empty `initialize()` and `terminate()`.

- [ ] **Step 1: Create metadata.yaml**

```yaml
name: pjsk-astrbot
desc: PJSK score tracking, B20, and chart rankings via multi-model vision OCR.
version: 0.0.0
author: leoviria
astrbot_version: ">=4.16"
```

- [ ] **Step 2: Create main.py with empty Star subclass**

```python
"""PJSK AstrBot plugin entry point.

This plugin provides score screenshot OCR, personal best tracking,
B20 ranking, and chart difficulty rankings for Project SEKAI.
"""

from astrbot.api.star import Context, Star, register
from astrbot.api import logger


@register(
    "pjsk-astrbot",
    "leoviria",
    "PJSK score tracking, B20, and chart rankings via multi-model vision OCR",
    "0.0.0",
)
class PjskPlugin(Star):
    """PJSK AstrBot plugin — score tracking and rankings."""

    def __init__(self, context: Context) -> None:
        super().__init__(context)

    async def initialize(self) -> None:
        """Called after plugin class is instantiated."""
        logger.info("pjsk-astrbot plugin initialized")

    async def terminate(self) -> None:
        """Called when plugin is unloaded or disabled."""
        logger.info("pjsk-astrbot plugin terminated")
```

- [ ] **Step 3: Confirm ruff passes on new files**

Run: `.venv\Scripts\python -m ruff check metadata.yaml main.py`

- [ ] **Step 4: Commit**

Run: `git add metadata.yaml main.py && git commit -m "feat: add AstrBot plugin entry point shell"`

---

### Task 2: Domain — User Identity Types

**Files:**
- Create: `tests/domain/__init__.py`
- Create: `tests/domain/test_users.py`
- Create: `pjsk_core/domain/users.py`

**Interfaces:**
- Produces: `UserId(value: int)`, `QqNumber(value: str)`, `User(id, qq_number, game_id)`. All frozen dataclasses.

- [ ] **Step 1: Write failing tests**

Create `tests/domain/__init__.py` (empty).

Create `tests/domain/test_users.py`:

```python
"""Tests for pjsk_core.domain.users — identity value objects."""

import pytest
from pjsk_core.domain.users import QqNumber, User, UserId


class TestQqNumber:
    def test_valid_qq_number(self) -> None:
        qq = QqNumber("123456789")
        assert qq.value == "123456789"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            QqNumber("")

    def test_non_digit_characters_raise(self) -> None:
        with pytest.raises(ValueError):
            QqNumber("abc123")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError):
            QqNumber("   ")

    def test_strips_and_validates(self) -> None:
        qq = QqNumber("  123456789  ")
        assert qq.value == "123456789"

    def test_equality(self) -> None:
        assert QqNumber("123") == QqNumber("123")
        assert QqNumber("123") != QqNumber("456")


class TestUserId:
    def test_valid_user_id(self) -> None:
        uid = UserId(1)
        assert uid.value == 1

    def test_zero_is_valid(self) -> None:
        uid = UserId(0)
        assert uid.value == 0

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError):
            UserId(-1)

    def test_equality(self) -> None:
        assert UserId(1) == UserId(1)
        assert UserId(1) != UserId(2)


class TestUser:
    def test_user_with_game_id(self) -> None:
        user = User(
            id=UserId(1),
            qq_number=QqNumber("123456789"),
            game_id="player123",
        )
        assert user.id == UserId(1)
        assert user.qq_number == QqNumber("123456789")
        assert user.game_id == "player123"

    def test_user_without_game_id(self) -> None:
        user = User(
            id=UserId(1),
            qq_number=QqNumber("123456789"),
            game_id=None,
        )
        assert user.game_id is None

    def test_empty_game_id_raises(self) -> None:
        with pytest.raises(ValueError):
            User(
                id=UserId(1),
                qq_number=QqNumber("123456789"),
                game_id="",
            )

    def test_frozen(self) -> None:
        user = User(id=UserId(1), qq_number=QqNumber("123"), game_id=None)
        with pytest.raises(Exception):
            user.game_id = "new"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests — expect collection/import errors**

Run: `.venv\Scripts\python -m pytest tests/domain/test_users.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pjsk_core.domain.users'`

- [ ] **Step 3: Implement users.py**

```python
"""User identity value objects — QQ number, user ID, and user entity."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QqNumber:
    """A validated QQ number as a digit-only string."""

    value: str

    def __post_init__(self) -> None:
        stripped = self.value.strip()
        if not stripped:
            raise ValueError("QQ number must not be empty")
        if not stripped.isdigit():
            raise ValueError(
                f"QQ number must contain only digits, got: {self.value!r}"
            )
        if stripped != self.value:
            object.__setattr__(self, "value", stripped)


@dataclass(frozen=True)
class UserId:
    """Internal user primary key."""

    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError(f"User ID must be non-negative, got: {self.value}")


@dataclass(frozen=True)
class User:
    """A registered user with QQ identity and optional game binding."""

    id: UserId
    qq_number: QqNumber
    game_id: str | None

    def __post_init__(self) -> None:
        if self.game_id is not None and self.game_id == "":
            raise ValueError("game_id must be None or a non-empty string")
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `.venv\Scripts\python -m pytest tests/domain/test_users.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core tests`

- [ ] **Step 6: Commit**

Run: `git add tests/domain/__init__.py tests/domain/test_users.py pjsk_core/domain/users.py && git commit -m "feat: define user identity domain types"`

---

### Task 3: Domain — Chart and Difficulty Types

**Files:**
- Create: `tests/domain/test_charts.py`
- Create: `pjsk_core/domain/charts.py`

**Interfaces:**
- Produces: `Difficulty` enum (EASY/NORMAL/HARD/EXPERT/MASTER/APPEND), `Chart` frozen dataclass.

- [ ] **Step 1: Write failing tests**

Create `tests/domain/test_charts.py`:

```python
"""Tests for pjsk_core.domain.charts — difficulty and chart types."""

import pytest
from pjsk_core.domain.charts import Chart, Difficulty


class TestDifficulty:
    def test_six_members(self) -> None:
        members = list(Difficulty)
        assert len(members) == 6
        names = {m.name for m in members}
        assert names == {"EASY", "NORMAL", "HARD", "EXPERT", "MASTER", "APPEND"}

    def test_values_are_lowercase(self) -> None:
        for member in Difficulty:
            assert member.value == member.name.lower()

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("easy", Difficulty.EASY),
            ("normal", Difficulty.NORMAL),
            ("hard", Difficulty.HARD),
            ("expert", Difficulty.EXPERT),
            ("master", Difficulty.MASTER),
            ("append", Difficulty.APPEND),
        ],
    )
    def test_from_string(self, value: str, expected: Difficulty) -> None:
        assert Difficulty(value) is expected


class TestChart:
    def test_valid_chart(self) -> None:
        chart = Chart(
            id=1,
            song_id=42,
            difficulty=Difficulty.MASTER,
            official_level=31,
            community_constant="31.2",
            note_count=1200,
            data_version="2026-07-01",
        )
        assert chart.id == 1
        assert chart.song_id == 42
        assert chart.difficulty == Difficulty.MASTER
        assert chart.official_level == 31
        assert chart.community_constant == "31.2"
        assert chart.note_count == 1200
        assert chart.data_version == "2026-07-01"

    def test_community_constant_with_plus(self) -> None:
        chart = Chart(
            id=2, song_id=1, difficulty=Difficulty.MASTER,
            official_level=32, community_constant="32.5+", note_count=1000,
            data_version="v1",
        )
        assert chart.community_constant == "32.5+"

    def test_community_constant_with_minus(self) -> None:
        chart = Chart(
            id=3, song_id=1, difficulty=Difficulty.MASTER,
            official_level=30, community_constant="30.1-", note_count=900,
            data_version="v1",
        )
        assert chart.community_constant == "30.1-"

    def test_invalid_official_level_raises(self) -> None:
        with pytest.raises(ValueError):
            Chart(
                id=1, song_id=1, difficulty=Difficulty.EASY,
                official_level=0, community_constant="1.0", note_count=100,
                data_version="v1",
            )

    def test_invalid_note_count_raises(self) -> None:
        with pytest.raises(ValueError):
            Chart(
                id=1, song_id=1, difficulty=Difficulty.EASY,
                official_level=5, community_constant="5.0", note_count=0,
                data_version="v1",
            )

    def test_frozen(self) -> None:
        chart = Chart(
            id=1, song_id=1, difficulty=Difficulty.EXPERT,
            official_level=25, community_constant="25.5", note_count=800,
            data_version="v1",
        )
        with pytest.raises(Exception):
            chart.official_level = 26  # type: ignore[misc]
```

- [ ] **Step 2: Run tests — expect import error**

Run: `.venv\Scripts\python -m pytest tests/domain/test_charts.py -v`
Expected: FAIL

- [ ] **Step 3: Implement charts.py**

```python
"""Chart and difficulty domain types for Project SEKAI."""

from dataclasses import dataclass
from enum import Enum


class Difficulty(Enum):
    """PJSK difficulty levels."""

    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"
    EXPERT = "expert"
    MASTER = "master"
    APPEND = "append"


@dataclass(frozen=True)
class Chart:
    """A playable chart (song + difficulty combination).

    community_constant is the community-researched precise difficulty
    rating (e.g. "31.2", "32.5+", "30.1-"). Parsing of suffixes is
    deferred to the rating domain (Task 3).
    """

    id: int
    song_id: int
    difficulty: Difficulty
    official_level: int
    community_constant: str
    note_count: int
    data_version: str

    def __post_init__(self) -> None:
        if self.official_level <= 0:
            raise ValueError(
                f"official_level must be positive, got: {self.official_level}"
            )
        if self.note_count <= 0:
            raise ValueError(
                f"note_count must be positive, got: {self.note_count}"
            )
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `.venv\Scripts\python -m pytest tests/domain/test_charts.py -v`

- [ ] **Step 5: Run full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core tests`

- [ ] **Step 6: Commit**

Run: `git add tests/domain/test_charts.py pjsk_core/domain/charts.py && git commit -m "feat: define chart and difficulty domain types"`

---

### Task 4: Domain — Score Status and Judgement Types

**Files:**
- Create: `tests/domain/test_scores.py`
- Create: `pjsk_core/domain/scores.py`

**Interfaces:**
- Produces: `ScoreStatus` enum (AP/FC/CLEAR), `Judgements` frozen dataclass (non-negative validation), `ScoreAttempt` frozen dataclass (requires timezone-aware datetime).
- Consumes: `UserId` from Task 2 (`pjsk_core.domain.users`).

- [ ] **Step 1: Write failing tests**

Create `tests/domain/test_scores.py`:

```python
"""Tests for pjsk_core.domain.scores — status, judgements, and attempts."""

from datetime import datetime, timezone

import pytest
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import UserId


class TestScoreStatus:
    def test_three_members(self) -> None:
        members = list(ScoreStatus)
        assert len(members) == 3
        names = {m.name for m in members}
        assert names == {"AP", "FC", "CLEAR"}

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("ap", ScoreStatus.AP),
            ("fc", ScoreStatus.FC),
            ("clear", ScoreStatus.CLEAR),
        ],
    )
    def test_from_string(self, value: str, expected: ScoreStatus) -> None:
        assert ScoreStatus(value) is expected


class TestJudgements:
    def test_all_perfect(self) -> None:
        j = Judgements(perfect=1000, great=0, good=0, bad=0, miss=0)
        assert j.perfect == 1000
        assert j.great == 0

    def test_mixed_judgements(self) -> None:
        j = Judgements(perfect=900, great=80, good=15, bad=3, miss=2)
        assert j.perfect == 900
        assert j.great == 80
        assert j.good == 15
        assert j.bad == 3
        assert j.miss == 2

    def test_all_zeros_is_valid(self) -> None:
        j = Judgements(perfect=0, great=0, good=0, bad=0, miss=0)
        assert j.perfect == 0

    def test_negative_perfect_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=-1, great=0, good=0, bad=0, miss=0)

    def test_negative_great_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=0, great=-1, good=0, bad=0, miss=0)

    def test_negative_good_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=0, great=0, good=-1, bad=0, miss=0)

    def test_negative_bad_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=0, great=0, good=0, bad=-1, miss=0)

    def test_negative_miss_raises(self) -> None:
        with pytest.raises(ValueError):
            Judgements(perfect=0, great=0, good=0, bad=0, miss=-1)

    def test_frozen(self) -> None:
        j = Judgements(perfect=1, great=0, good=0, bad=0, miss=0)
        with pytest.raises(Exception):
            j.perfect = 2  # type: ignore[misc]


class TestScoreAttempt:
    def test_valid_attempt(self) -> None:
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None,
            user_id=UserId(1),
            chart_id=42,
            judgements=Judgements(perfect=1000, great=10, good=0, bad=0, miss=0),
            accuracy=100.5,
            rating=3200.0,
            status=ScoreStatus.FC,
            image_sha256="abc123",
            source_gateway="astrbot",
            ocr_run_id=None,
            created_at=now,
        )
        assert attempt.id is None
        assert attempt.user_id == UserId(1)
        assert attempt.chart_id == 42
        assert attempt.status == ScoreStatus.FC

    def test_with_id(self) -> None:
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=1,
            user_id=UserId(1),
            chart_id=1,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            accuracy=101.0,
            rating=3500.0,
            status=ScoreStatus.AP,
            image_sha256="def456",
            source_gateway="astrbot",
            ocr_run_id=5,
            created_at=now,
        )
        assert attempt.id == 1

    def test_naive_datetime_raises(self) -> None:
        naive = datetime(2026, 7, 12, 12, 0, 0)  # no tzinfo
        with pytest.raises(ValueError):
            ScoreAttempt(
                id=None,
                user_id=UserId(1),
                chart_id=1,
                judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
                accuracy=50.0,
                rating=100.0,
                status=ScoreStatus.CLEAR,
                image_sha256="ghi789",
                source_gateway="astrbot",
                ocr_run_id=None,
                created_at=naive,
            )

    def test_frozen(self) -> None:
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None,
            user_id=UserId(1),
            chart_id=1,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            accuracy=100.0,
            rating=3000.0,
            status=ScoreStatus.FC,
            image_sha256="abc",
            source_gateway="astrbot",
            ocr_run_id=None,
            created_at=now,
        )
        with pytest.raises(Exception):
            attempt.accuracy = 99.0  # type: ignore[misc]
```

- [ ] **Step 2: Run tests — expect import error**

Run: `.venv\Scripts\python -m pytest tests/domain/test_scores.py -v`
Expected: FAIL

- [ ] **Step 3: Implement scores.py**

```python
"""Score status, judgement counts, and score attempt domain types."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pjsk_core.domain.users import UserId


class ScoreStatus(Enum):
    """Play result classification."""

    AP = "ap"
    FC = "fc"
    CLEAR = "clear"


@dataclass(frozen=True)
class Judgements:
    """Counts for each judgement tier in a single play."""

    perfect: int
    great: int
    good: int
    bad: int
    miss: int

    def __post_init__(self) -> None:
        for field_name in ("perfect", "great", "good", "bad", "miss"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(
                    f"{field_name} must be non-negative, got: {value}"
                )


@dataclass(frozen=True)
class ScoreAttempt:
    """A single confirmed score submission.

    id is None before database insert; assigned by the repository.
    """

    id: int | None
    user_id: UserId
    chart_id: int
    judgements: Judgements
    accuracy: float
    rating: float
    status: ScoreStatus
    image_sha256: str
    source_gateway: str
    ocr_run_id: int | None
    created_at: datetime

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.accuracy < 0:
            raise ValueError(f"accuracy must be non-negative, got: {self.accuracy}")
        if self.rating < 0:
            raise ValueError(f"rating must be non-negative, got: {self.rating}")
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `.venv\Scripts\python -m pytest tests/domain/test_scores.py -v`

- [ ] **Step 5: Run full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core tests`

- [ ] **Step 6: Commit**

Run: `git add tests/domain/test_scores.py pjsk_core/domain/scores.py && git commit -m "feat: define score status, judgements, and attempt domain types"`

---

### Task 5: Domain — OCR Observation Type

**Files:**
- Create: `tests/domain/test_ocr.py`
- Create: `pjsk_core/domain/ocr.py`

**Interfaces:**
- Produces: `OcrObservation` frozen dataclass.
- Consumes: `Difficulty` from Task 3, `Judgements` from Task 4.

- [ ] **Step 1: Write failing tests**

Create `tests/domain/test_ocr.py`:

```python
"""Tests for pjsk_core.domain.ocr — vision engine observation type."""

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.scores import Judgements


def test_valid_observation() -> None:
    obs = OcrObservation(
        song_title="Tell Your World",
        difficulty=Difficulty.MASTER,
        displayed_level=31,
        judgements=Judgements(perfect=1000, great=10, good=0, bad=0, miss=0),
        engine="gemini",
        elapsed_ms=1234,
    )
    assert obs.song_title == "Tell Your World"
    assert obs.difficulty == Difficulty.MASTER
    assert obs.displayed_level == 31
    assert obs.judgements.perfect == 1000
    assert obs.engine == "gemini"
    assert obs.elapsed_ms == 1234


def test_frozen() -> None:
    obs = OcrObservation(
        song_title="Test",
        difficulty=Difficulty.EASY,
        displayed_level=1,
        judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
        engine="test",
        elapsed_ms=0,
    )
    with pytest.raises(Exception):
        obs.song_title = "Changed"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests — expect import error**

Run: `.venv\Scripts\python -m pytest tests/domain/test_ocr.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ocr.py**

```python
"""Vision engine observation — raw OCR result before validation."""

from dataclasses import dataclass

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import Judgements


@dataclass(frozen=True)
class OcrObservation:
    """A single vision model's recognition result."""

    song_title: str
    difficulty: Difficulty
    displayed_level: int
    judgements: Judgements
    engine: str
    elapsed_ms: int
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `.venv\Scripts\python -m pytest tests/domain/test_ocr.py -v`

- [ ] **Step 5: Run full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core tests`

- [ ] **Step 6: Commit**

Run: `git add tests/domain/test_ocr.py pjsk_core/domain/ocr.py && git commit -m "feat: define OCR observation domain type"`

---

### Task 6: Application — Reply Types

**Files:**
- Create: `tests/test_reply_types.py`
- Create: `pjsk_core/application/replies.py`

**Interfaces:**
- Produces: `TextReply`, `ImageReply`, `CandidateReply`, `ProgressReply`, `ErrorReply` frozen dataclasses.
- Consumes: `OcrObservation` from Task 5.

- [ ] **Step 1: Write failing tests**

Create `tests/test_reply_types.py`:

```python
"""Tests for pjsk_core.application.replies — unified reply types."""

from pjsk_core.application.replies import (
    CandidateReply,
    ErrorReply,
    ImageReply,
    ProgressReply,
    TextReply,
)
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.scores import Judgements


class TestTextReply:
    def test_creation(self) -> None:
        reply = TextReply(text="Hello, world!")
        assert reply.text == "Hello, world!"

    def test_frozen(self) -> None:
        reply = TextReply(text="test")
        with pytest.raises(Exception):
            reply.text = "changed"  # type: ignore[misc]


class TestImageReply:
    def test_creation(self) -> None:
        reply = ImageReply(image_bytes=b"\x89PNG", mime_type="image/png")
        assert reply.image_bytes == b"\x89PNG"
        assert reply.mime_type == "image/png"

    def test_frozen(self) -> None:
        reply = ImageReply(image_bytes=b"", mime_type="image/jpeg")
        with pytest.raises(Exception):
            reply.mime_type = "image/png"  # type: ignore[misc]


class TestCandidateReply:
    def test_creation(self) -> None:
        obs = OcrObservation(
            song_title="Test", difficulty=Difficulty.EXPERT,
            displayed_level=25,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            engine="gemini", elapsed_ms=500,
        )
        reply = CandidateReply(
            candidate_set_id="abc-123",
            candidates=[obs],
        )
        assert reply.candidate_set_id == "abc-123"
        assert len(reply.candidates) == 1

    def test_frozen(self) -> None:
        reply = CandidateReply(candidate_set_id="x", candidates=[])
        with pytest.raises(Exception):
            reply.candidate_set_id = "y"  # type: ignore[misc]


class TestProgressReply:
    def test_creation(self) -> None:
        reply = ProgressReply(message="Processing...", current=2, total=5)
        assert reply.message == "Processing..."
        assert reply.current == 2
        assert reply.total == 5

    def test_frozen(self) -> None:
        reply = ProgressReply(message="test", current=0, total=1)
        with pytest.raises(Exception):
            reply.current = 1  # type: ignore[misc]


class TestErrorReply:
    def test_recoverable_error(self) -> None:
        reply = ErrorReply(message="Timeout, retrying...", recoverable=True)
        assert reply.message == "Timeout, retrying..."
        assert reply.recoverable is True

    def test_non_recoverable_error(self) -> None:
        reply = ErrorReply(message="Chart not found", recoverable=False)
        assert reply.recoverable is False

    def test_frozen(self) -> None:
        reply = ErrorReply(message="test", recoverable=False)
        with pytest.raises(Exception):
            reply.message = "changed"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests — expect import error**

Run: `.venv\Scripts\python -m pytest tests/test_reply_types.py -v`
Expected: FAIL

- [ ] **Step 3: Implement replies.py**

```python
"""Unified reply types for gateway-agnostic responses.

Gateways convert these into platform-specific messages
(AstrBot MessageEventResult, OneBot CQ codes, etc.).
"""

from dataclasses import dataclass

from pjsk_core.domain.ocr import OcrObservation


@dataclass(frozen=True)
class TextReply:
    """Plain text response."""

    text: str


@dataclass(frozen=True)
class ImageReply:
    """Rendered image response."""

    image_bytes: bytes
    mime_type: str


@dataclass(frozen=True)
class CandidateReply:
    """Ambiguous OCR result — presents numbered candidates for user selection."""

    candidate_set_id: str
    candidates: list[OcrObservation]


@dataclass(frozen=True)
class ProgressReply:
    """Processing status update for long-running operations."""

    message: str
    current: int
    total: int


@dataclass(frozen=True)
class ErrorReply:
    """Error response with recoverability hint."""

    message: str
    recoverable: bool
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `.venv\Scripts\python -m pytest tests/test_reply_types.py -v`

- [ ] **Step 5: Run full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core tests`

- [ ] **Step 6: Commit**

Run: `git add tests/test_reply_types.py pjsk_core/application/replies.py && git commit -m "feat: define unified gateway-agnostic reply types"`

---

### Task 7: Ports — All Five Protocol Contracts

**Files:**
- Create: `tests/test_port_contracts.py`
- Create: `pjsk_core/ports/repositories.py`
- Create: `pjsk_core/ports/vision.py`
- Create: `pjsk_core/ports/renderer.py`
- Create: `pjsk_core/ports/identity.py`
- Create: `pjsk_core/ports/cache.py`

**Interfaces:**
- Produces: `UserRepository`, `ChartRepository`, `ScoreRepository`, `VisionEngine`, `Renderer` (+ `RenderRequest`, `RenderResult`), `IdentityResolver`, `CandidateStore`.
- Consumes: All domain types from Tasks 2–5, reply types from Task 6.

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_port_contracts.py`:

```python
"""Contract tests: every Protocol has a fake implementation that type-checks
and passes a basic async smoke call."""

from datetime import datetime, timezone

from pjsk_core.application.replies import ErrorReply, TextReply
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import QqNumber, User, UserId
from pjsk_core.ports.cache import CandidateStore
from pjsk_core.ports.identity import IdentityResolver
from pjsk_core.ports.renderer import RenderRequest, RenderResult, Renderer
from pjsk_core.ports.repositories import (
    ChartRepository,
    ScoreRepository,
    UserRepository,
)
from pjsk_core.ports.vision import VisionEngine


# ── Fake implementations ────────────────────────────────────────────

class FakeUserRepository:
    def __init__(self) -> None:
        self._users: dict[int, User] = {}
        self._next_id = 1

    async def get_by_id(self, user_id: UserId) -> User | None:
        return self._users.get(user_id.value)

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        for u in self._users.values():
            if u.qq_number == qq:
                return u
        return None

    async def create(self, qq: QqNumber, game_id: str | None) -> User:
        uid = UserId(self._next_id)
        self._next_id += 1
        user = User(id=uid, qq_number=qq, game_id=game_id)
        self._users[uid.value] = user
        return user


class FakeChartRepository:
    def __init__(self) -> None:
        self._charts: dict[int, Chart] = {}

    async def get_by_id(self, chart_id: int) -> Chart | None:
        return self._charts.get(chart_id)

    async def find_by_song_and_difficulty(
        self, song_title: str, difficulty: Difficulty
    ) -> Chart | None:
        for c in self._charts.values():
            if c.difficulty == difficulty:
                return c
        return None

    async def list_by_difficulty_level(
        self, difficulty: Difficulty, official_level: int
    ) -> list[Chart]:
        return [
            c
            for c in self._charts.values()
            if c.difficulty == difficulty and c.official_level == official_level
        ]


class FakeScoreRepository:
    def __init__(self) -> None:
        self._attempts: dict[int, ScoreAttempt] = {}
        self._bests: dict[tuple[int, int], ScoreAttempt] = {}
        self._next_id = 1

    async def record_attempt(self, attempt: ScoreAttempt) -> ScoreAttempt:
        saved = ScoreAttempt(
            id=self._next_id,
            user_id=attempt.user_id,
            chart_id=attempt.chart_id,
            judgements=attempt.judgements,
            accuracy=attempt.accuracy,
            rating=attempt.rating,
            status=attempt.status,
            image_sha256=attempt.image_sha256,
            source_gateway=attempt.source_gateway,
            ocr_run_id=attempt.ocr_run_id,
            created_at=attempt.created_at,
        )
        self._next_id += 1
        self._attempts[saved.id] = saved  # type: ignore[index]
        key = (saved.user_id.value, saved.chart_id)
        current = self._bests.get(key)
        if current is None or saved.rating >= current.rating:
            self._bests[key] = saved
        return saved

    async def get_personal_best(
        self, user_id: UserId, chart_id: int
    ) -> ScoreAttempt | None:
        return self._bests.get((user_id.value, chart_id))

    async def list_personal_bests(
        self, user_id: UserId, status_filter: set[ScoreStatus] | None = None,
    ) -> list[ScoreAttempt]:
        results = [
            v for k, v in self._bests.items() if k[0] == user_id.value
        ]
        if status_filter is not None:
            results = [r for r in results if r.status in status_filter]
        return results


class FakeVisionEngine:
    name = "fake-vision"

    async def recognize(self, image: bytes, *, timeout: float) -> OcrObservation:
        return OcrObservation(
            song_title="Test Song",
            difficulty=Difficulty.EXPERT,
            displayed_level=25,
            judgements=Judgements(perfect=800, great=0, good=0, bad=0, miss=0),
            engine=self.name,
            elapsed_ms=100,
        )


class FakeRenderer:
    async def render(self, request: RenderRequest) -> RenderResult:
        return RenderResult(
            image_bytes=b"fake-png-data",
            renderer_version="fake-1.0",
            template_version=request.template + "-v1",
        )


class FakeIdentityResolver:
    async def resolve(self, platform: str, external_id: str) -> QqNumber | None:
        return QqNumber("123456789") if external_id == "known" else None


class FakeCandidateStore:
    def __init__(self) -> None:
        self._store: dict[str, list[OcrObservation]] = {}
        self._consumed: set[str] = set()

    async def put(
        self, user_id: UserId, candidates: list[OcrObservation], ttl_seconds: int
    ) -> str:
        key = f"candidate-{len(self._store)}"
        self._store[key] = candidates
        return key

    async def consume(self, candidate_set_id: str) -> list[OcrObservation] | None:
        if candidate_set_id in self._consumed:
            return None
        self._consumed.add(candidate_set_id)
        return self._store.get(candidate_set_id)


# ── Contract tests ──────────────────────────────────────────────────


async def test_user_repository_contract() -> None:
    repo: UserRepository = FakeUserRepository()
    assert await repo.get_by_id(UserId(1)) is None

    qq = QqNumber("123456789")
    user = await repo.create(qq, None)
    assert user.id == UserId(1)

    fetched = await repo.get_by_qq(qq)
    assert fetched == user


async def test_chart_repository_contract() -> None:
    repo: ChartRepository = FakeChartRepository()
    assert await repo.get_by_id(999) is None

    chart = Chart(
        id=1, song_id=10, difficulty=Difficulty.MASTER,
        official_level=31, community_constant="31.2", note_count=1200,
        data_version="v1",
    )
    repo._charts[1] = chart
    assert await repo.get_by_id(1) == chart


async def test_score_repository_contract() -> None:
    repo: ScoreRepository = FakeScoreRepository()
    now = datetime.now(timezone.utc)
    attempt = ScoreAttempt(
        id=None,
        user_id=UserId(1),
        chart_id=42,
        judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
        accuracy=101.0,
        rating=3500.0,
        status=ScoreStatus.AP,
        image_sha256="abc",
        source_gateway="astrbot",
        ocr_run_id=None,
        created_at=now,
    )
    saved = await repo.record_attempt(attempt)
    assert saved.id is not None

    best = await repo.get_personal_best(UserId(1), 42)
    assert best is not None


async def test_vision_engine_contract() -> None:
    engine: VisionEngine = FakeVisionEngine()
    obs = await engine.recognize(b"fake-image", timeout=10.0)
    assert obs.engine == "fake-vision"
    assert obs.song_title == "Test Song"


async def test_renderer_contract() -> None:
    renderer: Renderer = FakeRenderer()
    req = RenderRequest(template="b20", data={}, width=800, height=600)
    result = await renderer.render(req)
    assert result.image_bytes == b"fake-png-data"


async def test_identity_resolver_contract() -> None:
    resolver: IdentityResolver = FakeIdentityResolver()
    result = await resolver.resolve("qq_official", "known")
    assert result == QqNumber("123456789")

    result = await resolver.resolve("qq_official", "unknown")
    assert result is None


async def test_candidate_store_contract() -> None:
    store: CandidateStore = FakeCandidateStore()
    obs = OcrObservation(
        song_title="Test", difficulty=Difficulty.HARD,
        displayed_level=15,
        judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
        engine="test", elapsed_ms=0,
    )
    cid = await store.put(UserId(1), [obs], ttl_seconds=60)
    assert cid is not None

    result = await store.consume(cid)
    assert result == [obs]

    # Second consume returns None (already consumed)
    result2 = await store.consume(cid)
    assert result2 is None
```

- [ ] **Step 2: Run tests — expect import errors (no port modules yet)**

Run: `.venv\Scripts\python -m pytest tests/test_port_contracts.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement repositories.py**

Create `pjsk_core/ports/repositories.py`:

```python
"""Repository ports for persistent storage of users, charts, and scores.

All methods return domain objects, never dicts or database rows.
"""

from typing import Protocol

from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.scores import ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import QqNumber, User, UserId


class UserRepository(Protocol):
    """User identity persistence."""

    async def get_by_id(self, user_id: UserId) -> User | None: ...
    async def get_by_qq(self, qq: QqNumber) -> User | None: ...
    async def create(self, qq: QqNumber, game_id: str | None) -> User: ...


class ChartRepository(Protocol):
    """Chart and song metadata lookups."""

    async def get_by_id(self, chart_id: int) -> Chart | None: ...
    async def find_by_song_and_difficulty(
        self, song_title: str, difficulty: Difficulty
    ) -> Chart | None: ...
    async def list_by_difficulty_level(
        self, difficulty: Difficulty, official_level: int
    ) -> list[Chart]: ...


class ScoreRepository(Protocol):
    """Score persistence and personal best tracking.

    record_attempt inserts the attempt and updates the personal best
    within a single transaction.
    """

    async def record_attempt(self, attempt: ScoreAttempt) -> ScoreAttempt: ...
    async def get_personal_best(
        self, user_id: UserId, chart_id: int
    ) -> ScoreAttempt | None: ...
    async def list_personal_bests(
        self, user_id: UserId, status_filter: set[ScoreStatus] | None = None,
    ) -> list[ScoreAttempt]: ...
```

- [ ] **Step 4: Implement vision.py**

Create `pjsk_core/ports/vision.py`:

```python
"""Vision engine port — multi-model OCR for score screenshots."""

from typing import Protocol

from pjsk_core.domain.ocr import OcrObservation


class VisionEngine(Protocol):
    """A single vision model backend for recognizing score screenshots."""

    name: str

    async def recognize(
        self, image: bytes, *, timeout: float
    ) -> OcrObservation: ...
```

- [ ] **Step 5: Implement renderer.py**

Create `pjsk_core/ports/renderer.py`:

```python
"""Renderer port — image generation for rankings and charts."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RenderRequest:
    """Request to render a template with data."""

    template: str
    data: dict[str, object]
    width: int
    height: int


@dataclass(frozen=True)
class RenderResult:
    """Rendered image with version metadata for cache invalidation."""

    image_bytes: bytes
    renderer_version: str
    template_version: str


class Renderer(Protocol):
    """Rendering service adapter."""

    async def render(self, request: RenderRequest) -> RenderResult: ...
```

- [ ] **Step 6: Implement identity.py**

Create `pjsk_core/ports/identity.py`:

```python
"""Identity resolver port — maps platform identities to internal QQ numbers."""

from typing import Protocol

from pjsk_core.domain.users import QqNumber


class IdentityResolver(Protocol):
    """Resolve external platform identity (e.g. Official QQ OpenID)
    to an internal QQ number via binding table lookup."""

    async def resolve(
        self, platform: str, external_id: str
    ) -> QqNumber | None: ...
```

- [ ] **Step 7: Implement cache.py**

Create `pjsk_core/ports/cache.py`:

```python
"""Candidate store port — temporary OCR result storage for user confirmation."""

from typing import Protocol

from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.users import UserId


class CandidateStore(Protocol):
    """Temporary storage for ambiguous OCR results awaiting user selection.

    Each candidate set is single-consumption with a TTL.
    """

    async def put(
        self,
        user_id: UserId,
        candidates: list[OcrObservation],
        ttl_seconds: int,
    ) -> str: ...

    async def consume(
        self, candidate_set_id: str
    ) -> list[OcrObservation] | None: ...
```

- [ ] **Step 8: Run contract tests — expect all pass**

Run: `.venv\Scripts\python -m pytest tests/test_port_contracts.py -v`

- [ ] **Step 9: Run full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core tests`

- [ ] **Step 10: Commit**

Run: `git add tests/test_port_contracts.py pjsk_core/ports/repositories.py pjsk_core/ports/vision.py pjsk_core/ports/renderer.py pjsk_core/ports/identity.py pjsk_core/ports/cache.py && git commit -m "feat: define all application port contracts"`

---

### Task 8: Gateway Adapter — Directory Structure

**Files:**
- Create: `adapters/__init__.py`
- Create: `adapters/gateways/__init__.py`
- Create: `adapters/gateways/astrbot/__init__.py`
- Create: `adapters/gateways/astrbot/event_converter.py`
- Create: `adapters/gateways/astrbot/reply_mapper.py`

**Interfaces:**
- Produces: Directory structure with module docstrings. No function bodies yet — these will be filled when AstrBot integration begins.
- Boundary test: the existing `test_domain_does_not_import_outer_layers` must still pass (domain must not import from adapters).

- [ ] **Step 1: Create directory structure and docstrings**

Create `adapters/__init__.py`:

```python
"""Adapters — concrete implementations of ports.

Subpackages:
  database   — SQLite schema, repository, versioned migrations
  vision     — Gemini / Zhipu / StepFun adapters and racer
  rendering  — HTTP adapter for the standalone render service
  cache      — Redis + in-process fallback
  gateways   — AstrBot / Official QQ / OneBot platform adapters
"""
```

Create `adapters/gateways/__init__.py`:

```python
"""Platform gateway adapters.

Each gateway converts platform-specific events into internal
representations and maps internal reply types back to the
platform's message format.
"""
```

Create `adapters/gateways/astrbot/__init__.py`:

```python
"""AstrBot gateway adapter.

Converts AstrMessageEvent objects into internal events and maps
TextReply / ImageReply / CandidateReply / ProgressReply / ErrorReply
back to AstrBot MessageEventResult objects.

All AstrBot-specific types (AstrMessageEvent, Context, etc.) stay
in this module and never enter pjsk_core.
"""
```

Create `adapters/gateways/astrbot/event_converter.py`:

```python
"""Convert AstrBot AstrMessageEvent into internal event representations.

AstrBot types never cross this boundary into pjsk_core.
"""
```

Create `adapters/gateways/astrbot/reply_mapper.py`:

```python
"""Map internal reply types to AstrBot MessageEventResult objects.

TextReply → plain_result / image_result
ImageReply → image_result
CandidateReply → plain_result with numbered options
ProgressReply → plain_result (status)
ErrorReply → plain_result (error message)
"""
```

- [ ] **Step 2: Verify existing boundary tests still pass**

Run: `.venv\Scripts\python -m pytest tests/test_package_boundaries.py -v`
Expected: 4 passed

- [ ] **Step 3: Run full suite + ruff + mypy**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core tests`

- [ ] **Step 4: Commit**

Run: `git add adapters/ && git commit -m "feat: scaffold gateway adapter directory structure"`

---

### Task 9: Final Verification

**Files:**
- Modify: `pyproject.toml` (if needed for ruff/mypy coverage)

**Interfaces:**
- Produces: Clean baseline — all tests pass, ruff zero, mypy strict zero.

- [ ] **Step 1: Ensure mypy covers all new packages**

Update `pyproject.toml` if `adapters` needs mypy coverage. Since adapters currently contain only docstrings (no typed code), mypy on `pjsk_core tests` should suffice.

- [ ] **Step 2: Run complete verification suite**

Run: `.venv\Scripts\python -m pytest -v`
Run: `.venv\Scripts\python -m ruff check .`
Run: `.venv\Scripts\python -m mypy pjsk_core tests`

All must pass with zero errors.

- [ ] **Step 3: Review git status — confirm all files committed**

Run: `git status --short --branch`
Expected: clean working tree, all changes committed.

- [ ] **Step 4: Report final status**

Run: `git log --oneline -10`
List all commit hashes, test counts, and confirm ruff/mypy green.

---

## Completion Gate

Phase "framework hardening" is complete when:
- AstrBot plugin shell exists (`main.py`, `metadata.yaml`)
- All 5 domain data class files exist with validation (`users`, `charts`, `scores`, `ocr`)
- All 5 reply types defined
- All 5 port Protocols defined with fake implementations passing contract tests
- Gateway adapter directory structure exists with docstrings
- All existing boundary tests pass
- Full test suite passes (expected: 15–20 tests)
- Ruff zero errors
- Mypy strict zero errors
- Working tree clean, all commits atomic
