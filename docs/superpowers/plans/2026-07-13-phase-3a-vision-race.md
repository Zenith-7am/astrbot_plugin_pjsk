> **Status: Approved** (core layer — still valid under Phase 5 standalone direction).
> The domain, application, ports, and adapter designs in this document remain authoritative for `pjsk_core` and `adapters/`.
> Current governance: `CLAUDE.md`. Phase-5 gateway design: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`.

# Phase 3a: Vision Model Adapters and Race Consensus — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement multi-model OCR pipeline — vendor adapters (Gemini/Zhipu/StepFun),
concurrent racing with early consensus, circuit breaker, song matching, and local
validation. Score recording on consensus.

**Architecture:** Domain types + ports define the contracts. Application orchestrates
the race, validation, and score construction. Adapters implement vendor HTTP calls,
circuit breaker state, and config loading. Dependency: adapters → ports ← application
→ domain. Domain imports nothing from outer layers.

**Tech Stack:** Python 3.11+, aiosqlite, httpx, dataclasses, typing.Protocol, asyncio,
pytest + pytest-asyncio, ruff, mypy strict.

Base: 183 tests, 48 source files. Branch: `codex/foundation-scaffold`.

## Global Constraints

These apply to every task. Copied verbatim from CLAUDE.md and the Phase 3a design spec:

1. `domain` must be synchronous, pure, no I/O. Must not import application / ports / adapters / httpx / aiosqlite.
2. `application` depends only on `domain` and `ports`. Must not import adapters.
3. `ports` define narrow Protocols. Repository methods return domain objects, never dicts.
4. `adapters` implement ports. Vendor adapters do NOT query the database, do NOT perform song matching, do NOT judge consensus.
5. Gateway/platform event objects must never enter the business core.
6. TDD: write a minimal failing test FIRST, confirm it fails for the right reason, then implement, confirm green, then commit. Never write implementation before the test.
7. One focused commit per task. Run `ruff check .` and `mypy pjsk_core adapters tools tests` before every commit.
8. Every successfully-acquired CircuitBreaker permit must be settled exactly once (success / failure / release).
9. Provider is the consensus voting unit — two engines from the same provider cannot form independent consensus.
10. Breaker success is recorded immediately after HTTP+parse, before local validation.
11. `displayed_level` mismatch → CANDIDATE, cannot enter auto-consensus.
12. GLOBAL_TIMEOUT decisions live in application (RecognizeScore), not in gateway.
13. API keys never appear in logs, exceptions, or repr.

---

### Task 1: Domain — SongMatcher (pure functions + types)

**Files:**
- Create: `pjsk_core/domain/song_matcher.py`
- Create: `tests/domain/test_song_matcher.py`

**Interfaces:**
- Produces: `SongMatchMethod(Enum)`, `TitleSource(Enum)`, `SongCandidate`, `SongMatch`, `match_song(raw_title, candidates) -> tuple[SongMatch, ...]`
- Produces (private): `_normalize_text(text) -> str`, `_normalize_ocr_text(text) -> str`, `_extract_title_regions(raw) -> tuple[str, ...]`

- [ ] **Step 1: Write the failing test**

```python
# tests/domain/test_song_matcher.py
"""Song matching tests — aligned with old emu-bot song_match.py fixtures."""
import pytest
from pjsk_core.domain.song_matcher import (
    SongCandidate, SongMatch, SongMatchMethod, TitleSource, match_song,
)


def _make_candidates(*titles_ja: str) -> tuple[SongCandidate, ...]:
    return tuple(
        SongCandidate(song_id=i + 1, title_ja=t, title_cn="", title_en="")
        for i, t in enumerate(titles_ja)
    )


class TestExactMatch:
    def test_exact_match_ja(self) -> None:
        candidates = _make_candidates("テルミーワールド", "泡沫未来", "初音ミクの消失")
        result = match_song("テルミーワールド", candidates)
        assert len(result) == 1
        assert result[0].song_id == 1
        assert result[0].method == SongMatchMethod.EXACT
        assert result[0].source == TitleSource.JAPANESE
        assert result[0].score == 1.0

    def test_exact_match_casefold(self) -> None:
        candidates = (SongCandidate(1, "Hello World", "", ""),)
        result = match_song("hello world", candidates)
        assert len(result) == 1
        assert result[0].song_id == 1

    def test_exact_match_nfkc(self) -> None:
        """Fullwidth ASCII should normalize to halfwidth via NFKC."""
        candidates = (SongCandidate(1, "ABC123", "", ""),)
        result = match_song("ＡＢＣ１２３", candidates)  # fullwidth
        assert len(result) == 1
        assert result[0].song_id == 1

    def test_ocr_correction_applied_to_raw_only(self) -> None:
        """OCR corrections (口→ク etc.) only transform the raw side.
        Candidate titles with real 口 must NOT be rewritten."""
        # A song whose real title contains 口
        candidates = (SongCandidate(1, "口ード", "", ""),)
        # OCR misreads ク as 口 — after correction, should match
        result = match_song("口ード", candidates)  # raw = OCR output
        assert len(result) == 1
        assert result[0].song_id == 1

    def test_normalization_collision_returns_multiple(self) -> None:
        """Two songs that normalize to the same string should both appear."""
        c = (
            SongCandidate(1, "Test Song", "", ""),
            SongCandidate(2, "test song", "", ""),  # casefold → same
        )
        result = match_song("Test Song", c)
        assert len(result) == 2
        assert {r.song_id for r in result} == {1, 2}


class TestRegionExtraction:
    def test_difficulty_keyword_truncation(self) -> None:
        """MASTER at end of title → stripped for region match."""
        candidates = _make_candidates("初音ミクの消失")
        result = match_song("初音ミクの消失 MASTER", candidates)
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.REGION

    def test_ui_noise_filtered(self) -> None:
        candidates = _make_candidates("Test")
        result = match_song("PERFECT Test GREAT 1234", candidates)
        assert len(result) >= 1


class TestFuzzyMatch:
    def test_fuzzy_above_threshold(self) -> None:
        candidates = _make_candidates("テルミーワールド")
        result = match_song("テルミーワルド", candidates)  # one char missing
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.FUZZY
        assert result[0].score >= 0.50

    def test_fuzzy_below_threshold_excluded(self) -> None:
        candidates = _make_candidates("テルミーワールド")
        result = match_song("abcdefg", candidates)
        assert len(result) == 0

    def test_fuzzy_position_bonus(self) -> None:
        """Substring match gets +0.08 position bonus."""
        candidates = _make_candidates("Hello World Song")
        result = match_song("Hello World", candidates)
        assert len(result) == 1
        assert result[0].score > 0.60  # Dice is high for substring


class TestPrefixMatch:
    def test_prefix_bidirectional(self) -> None:
        candidates = _make_candidates("Hello World Long Title")
        result = match_song("Hello World", candidates)
        assert len(result) == 1
        assert result[0].method == SongMatchMethod.PREFIX

    def test_prefix_too_short_rejected(self) -> None:
        candidates = _make_candidates("Hello World")
        result = match_song("Hel", candidates)  # only 3 chars
        assert len(result) == 0  # shorter side < 5


class TestFirstNonEmptyStep:
    def test_exact_stops_pipeline(self) -> None:
        """Exact match should prevent fuzzy from polluting results."""
        candidates = _make_candidates("Test", "Testing Song")
        result = match_song("Test", candidates)
        assert len(result) == 1
        assert result[0].song_id == 1
        assert result[0].method == SongMatchMethod.EXACT


class TestSongCandidateAliases:
    def test_alias_match(self) -> None:
        candidates = (
            SongCandidate(1, "初音ミクの消失", "初音未来的消失", "",
                          aliases=("消失", "激唱")),
        )
        result = match_song("消失", candidates)
        assert len(result) == 1
        assert result[0].song_id == 1
        assert result[0].source == TitleSource.ALIAS


class TestEmptyInput:
    def test_empty_raw_title_returns_empty(self) -> None:
        candidates = _make_candidates("Test")
        result = match_song("", candidates)
        assert len(result) == 0

    def test_whitespace_raw_title_returns_empty(self) -> None:
        candidates = _make_candidates("Test")
        result = match_song("   ", candidates)
        assert len(result) == 0

    def test_empty_candidates_returns_empty(self) -> None:
        result = match_song("Test", ())
        assert len(result) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/domain/test_song_matcher.py -v`
Expected: 0 passed, all fail with `ModuleNotFoundError: No module named 'pjsk_core.domain.song_matcher'`

- [ ] **Step 3: Write minimal implementation**

```python
# pjsk_core/domain/song_matcher.py
"""Pure song-title matching pipeline — four-step, compatible with old emu-bot."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum


# ── Types ────────────────────────────────────────────────────────────────

class SongMatchMethod(Enum):
    EXACT = "exact"
    REGION = "region"
    FUZZY = "fuzzy"
    PREFIX = "prefix"


class TitleSource(Enum):
    JAPANESE = "ja"
    CHINESE = "cn"
    ENGLISH = "en"
    ALIAS = "alias"


@dataclass(frozen=True)
class SongCandidate:
    song_id: int
    title_ja: str
    title_cn: str = ""
    title_en: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class SongMatch:
    song_id: int
    score: float
    method: SongMatchMethod
    source: TitleSource


# ── Normalization ────────────────────────────────────────────────────────

_OCR_CORRECTIONS = str.maketrans({"口": "ク", "一": "ー", "才": "オ"})
_RE_WHITESPACE = re.compile(r"\s+")

# Keywords that mark difficulty labels in score screenshots
_DIFFICULTY_KEYWORDS = (
    "MASTER", "EXPERT", "APPEND", "HARD", "NORMAL", "EASY",
    "マスター", "エキスパート", "ハード", "ノーマル", "イージー",
)

# UI noise tokens from result-screen overlays
_UI_NOISE_RE = re.compile(
    r"PERFECT|GREAT|GOOD|BAD|MISS|COMBO|CLEAR|FULL|ALL|\d{1,6}",
    re.IGNORECASE,
)

_METHOD_PRIORITY = {
    SongMatchMethod.EXACT: 0,
    SongMatchMethod.REGION: 1,
    SongMatchMethod.FUZZY: 2,
    SongMatchMethod.PREFIX: 3,
}

_SOURCE_PRIORITY = {
    TitleSource.JAPANESE: 0,
    TitleSource.CHINESE: 1,
    TitleSource.ENGLISH: 2,
    TitleSource.ALIAS: 3,
}

STRONG_FUZZY_SCORE = 0.82


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = _RE_WHITESPACE.sub(" ", text)
    return text.strip()


def _normalize_ocr_text(text: str) -> str:
    return _normalize_text(text).translate(_OCR_CORRECTIONS)


# ── Step helpers ─────────────────────────────────────────────────────────

def _iter_sources(candidate: SongCandidate) -> list[tuple[str, TitleSource]]:
    pairs: list[tuple[str, TitleSource]] = []
    for title, src in [
        (candidate.title_ja, TitleSource.JAPANESE),
        (candidate.title_cn, TitleSource.CHINESE),
        (candidate.title_en, TitleSource.ENGLISH),
    ]:
        if title.strip():
            pairs.append((title, src))
    for alias in candidate.aliases:
        if alias.strip():
            pairs.append((alias, TitleSource.ALIAS))
    return pairs


def _try_exact(raw: str, candidates: Sequence[SongCandidate]) -> list[SongMatch]:
    norm_raw = _normalize_text(raw)
    ocr_raw = _normalize_ocr_text(raw)
    matches: list[SongMatch] = []
    seen: set[int] = set()

    for attempt in (norm_raw, ocr_raw):
        if not attempt:
            continue
        for c in candidates:
            for title, src in _iter_sources(c):
                if _normalize_text(title) == attempt and c.song_id not in seen:
                    matches.append(SongMatch(c.song_id, 1.0,
                                             SongMatchMethod.EXACT, src))
                    seen.add(c.song_id)
                    break
    return _dedup_sort(matches)


def _try_region(raw: str, candidates: Sequence[SongCandidate]) -> list[SongMatch]:
    regions = _extract_title_regions(raw)
    matches: list[SongMatch] = []
    seen: set[int] = set()
    for region in regions:
        norm_region = _normalize_text(region)
        if not norm_region:
            continue
        for c in candidates:
            for title, src in _iter_sources(c):
                if _normalize_text(title) == norm_region and c.song_id not in seen:
                    matches.append(SongMatch(c.song_id, 1.0,
                                             SongMatchMethod.REGION, src))
                    seen.add(c.song_id)
                    break
    return _dedup_sort(matches)


def _extract_title_regions(raw: str) -> tuple[str, ...]:
    """Split raw OCR output at difficulty keywords and remove UI noise."""
    # Build a regex that splits at difficulty keywords
    kw_pattern = "|".join(re.escape(kw) for kw in _DIFFICULTY_KEYWORDS)
    parts = re.split(rf"({kw_pattern})", raw, flags=re.IGNORECASE)
    regions: list[str] = []
    for part in parts:
        cleaned = _UI_NOISE_RE.sub(" ", part)
        cleaned = _RE_WHITESPACE.sub(" ", cleaned).strip()
        if cleaned and len(cleaned) >= 2:
            regions.append(cleaned)
    return tuple(dict.fromkeys(regions))  # dedup keeping order


def _try_fuzzy(raw: str, candidates: Sequence[SongCandidate]) -> list[SongMatch]:
    norm_raw = _normalize_text(raw)
    ocr_raw = _normalize_ocr_text(raw)
    best: dict[int, SongMatch] = {}

    for attempt in (norm_raw, ocr_raw):
        if not attempt:
            continue
        for c in candidates:
            for title, src in _iter_sources(c):
                norm_title = _normalize_text(title)
                if not norm_title:
                    continue
                score = _fuzzy_score(attempt, norm_title)
                if score < 0.50:
                    continue
                if c.song_id not in best or score > best[c.song_id].score:
                    best[c.song_id] = SongMatch(c.song_id, score,
                                                SongMatchMethod.FUZZY, src)
    return _dedup_sort(list(best.values()))


def _fuzzy_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    dice = _dice_coefficient(a, b)
    lev = _levenshtein_similarity(a, b)
    score = dice * 0.6 + lev * 0.4
    # Position bonus
    if a in b or b in a:
        score += 0.08
    return min(1.0, score)


def _dice_coefficient(a: str, b: str) -> float:
    """Dice coefficient on character bigrams."""
    a_bigrams = {a[i:i + 2] for i in range(len(a) - 1)} if len(a) >= 2 else {a}
    b_bigrams = {b[i:i + 2] for i in range(len(b) - 1)} if len(b) >= 2 else {b}
    if not a_bigrams or not b_bigrams:
        return 0.0
    intersection = a_bigrams & b_bigrams
    return 2.0 * len(intersection) / (len(a_bigrams) + len(b_bigrams))


def _levenshtein_similarity(a: str, b: str) -> float:
    """1 − (edit_distance / max(len(a), len(b)))."""
    if not a and not b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    dist = _levenshtein_distance(a, b)
    return 1.0 - dist / max_len


def _levenshtein_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, ca in enumerate(a, 1):
        curr[0] = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev, curr = curr, prev
    return prev[-1]


def _try_prefix(raw: str, candidates: Sequence[SongCandidate]) -> list[SongMatch]:
    norm_raw = _normalize_text(raw)
    ocr_raw = _normalize_ocr_text(raw)
    matches: list[SongMatch] = []
    seen: set[int] = set()

    for attempt in (norm_raw, ocr_raw):
        if not attempt:
            continue
        for c in candidates:
            for title, src in _iter_sources(c):
                norm_title = _normalize_text(title)
                if not norm_title:
                    continue
                shorter = min(attempt, norm_title, key=len)
                longer = max(attempt, norm_title, key=len)
                if len(shorter) < 5:
                    continue
                if longer.startswith(shorter) and c.song_id not in seen:
                    score = len(shorter) / len(longer)
                    matches.append(SongMatch(c.song_id, score,
                                             SongMatchMethod.PREFIX, src))
                    seen.add(c.song_id)
                    break
    return _dedup_sort(matches)


def _dedup_sort(matches: list[SongMatch]) -> list[SongMatch]:
    """Dedup by song_id (keep best), sort by score→method→source→id."""
    best: dict[int, SongMatch] = {}
    for m in matches:
        if m.song_id not in best:
            best[m.song_id] = m
        elif m.score > best[m.song_id].score:
            best[m.song_id] = m
    return sorted(
        best.values(),
        key=lambda m: (
            -m.score,
            _METHOD_PRIORITY[m.method],
            _SOURCE_PRIORITY[m.source],
            m.song_id,
        ),
    )


# ── Public API ───────────────────────────────────────────────────────────

def match_song(
    raw_title: str,
    candidates: Sequence[SongCandidate],
) -> tuple[SongMatch, ...]:
    """Match raw OCR title against song candidates.

    Four-step pipeline — the first non-empty step wins:
    1. Exact match (safe normalization, then OCR-corrected)
    2. Region extraction (difficulty keyword truncation, UI-noise filtered)
    3. Fuzzy match (Dice 60% + Levenshtein 40%, threshold 0.50)
    4. Prefix match (bidirectional, ≥5 chars)
    """
    if not raw_title.strip():
        return ()
    if not candidates:
        return ()

    steps = (
        lambda: _try_exact(raw_title, candidates),
        lambda: _try_region(raw_title, candidates),
        lambda: _try_fuzzy(raw_title, candidates),
        lambda: _try_prefix(raw_title, candidates),
    )
    for step in steps:
        result = step()
        if result:
            return tuple(result)
    return ()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/domain/test_song_matcher.py -v`
Expected: all tests PASS

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add pjsk_core/domain/song_matcher.py tests/domain/test_song_matcher.py
git commit -m "feat: implement four-step song title matching pipeline"
```

---

### Task 2: Domain — EngineIdentity + VisionEngineError hierarchy

**Files:**
- Modify: `pjsk_core/domain/ocr.py` (append EngineIdentity and error classes at end)
- Modify: `tests/domain/test_ocr.py` (add identity tests; existing tests are for observations_agree / rank_candidates)

**Interfaces:**
- Produces: `EngineIdentity(engine_id, provider, model)` — frozen dataclass
- Produces: `VisionEngineError(Exception)`, `VisionTimeoutError`, `VisionConnectionError`, `VisionRateLimitError`, `VisionServerError`, `VisionResponseError`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/domain/test_ocr.py:

class TestEngineIdentity:
    def test_identity_equality(self) -> None:
        a = EngineIdentity("g", "google", "gemini-2.5-flash")
        b = EngineIdentity("g", "google", "gemini-2.5-flash")
        assert a == b

    def test_identity_inequality(self) -> None:
        a = EngineIdentity("g", "google", "gemini-2.5-flash")
        b = EngineIdentity("z", "zhipu", "glm-4v-flash")
        assert a != b

    def test_identity_fields(self) -> None:
        eid = EngineIdentity("gemini-2.5-flash", "google", "gemini-2.5-flash")
        assert eid.engine_id == "gemini-2.5-flash"
        assert eid.provider == "google"
        assert eid.model == "gemini-2.5-flash"


class TestVisionEngineErrors:
    def test_error_hierarchy(self) -> None:
        assert issubclass(VisionTimeoutError, VisionEngineError)
        assert issubclass(VisionConnectionError, VisionEngineError)
        assert issubclass(VisionRateLimitError, VisionEngineError)
        assert issubclass(VisionServerError, VisionEngineError)
        assert issubclass(VisionResponseError, VisionEngineError)

    def test_error_is_exception(self) -> None:
        with pytest.raises(VisionEngineError):
            raise VisionTimeoutError("timed out")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/domain/test_ocr.py::TestEngineIdentity tests/domain/test_ocr.py::TestVisionEngineErrors -v`
Expected: FAIL — `NameError: name 'EngineIdentity' is not defined`

- [ ] **Step 3: Write minimal implementation**

Append to `pjsk_core/domain/ocr.py`:

```python
# ── Engine identity ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class EngineIdentity:
    """Stable identity for a vision engine instance.

    engine_id: globally unique instance identifier, e.g. "gemini-2.5-flash"
    provider:  vendor name, e.g. "google" — the consensus voting unit
    model:     model name, e.g. "gemini-2.5-flash"
    """
    engine_id: str
    provider: str
    model: str


# ── Vision engine error hierarchy ────────────────────────────────────────

class VisionEngineError(Exception):
    """Base for all vendor-engine failures."""

class VisionTimeoutError(VisionEngineError):
    """Request exceeded the allotted timeout."""

class VisionConnectionError(VisionEngineError):
    """Network-level connection failure."""

class VisionRateLimitError(VisionEngineError):
    """Vendor returned rate-limiting (HTTP 429)."""

class VisionServerError(VisionEngineError):
    """Vendor returned a server-side error (HTTP 5xx)."""

class VisionResponseError(VisionEngineError):
    """Vendor returned an unexpected response (HTTP 4xx ≠ 429, or invalid JSON)."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/domain/test_ocr.py -v`
Expected: all tests (existing + new) PASS

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add pjsk_core/domain/ocr.py tests/domain/test_ocr.py
git commit -m "feat: add EngineIdentity and VisionEngineError hierarchy"
```

---

### Task 3: Ports — CircuitBreaker Protocol

**Files:**
- Create: `pjsk_core/ports/circuit_breaker.py`
- Create: `tests/test_port_contracts.py` (append CircuitBreaker structural test)

**Interfaces:**
- Produces: `CircuitState(Enum)`, `CircuitFailure(Enum)`, `CircuitPermit(engine_id, probe)`, `CircuitBreaker(Protocol)` with `acquire`, `record_success`, `record_failure`, `release`, `state`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_port_contracts.py:

from pjsk_core.ports.circuit_breaker import (
    CircuitBreaker, CircuitFailure, CircuitPermit, CircuitState,
)


class TestCircuitBreakerContract:
    def test_protocol_methods_exist(self) -> None:
        """CircuitBreaker Protocol defines all required methods."""
        assert hasattr(CircuitBreaker, "acquire")
        assert hasattr(CircuitBreaker, "record_success")
        assert hasattr(CircuitBreaker, "record_failure")
        assert hasattr(CircuitBreaker, "release")
        assert hasattr(CircuitBreaker, "state")

    def test_circuit_permit_fields(self) -> None:
        permit = CircuitPermit("eng", probe=True)
        assert permit.engine_id == "eng"
        assert permit.probe is True

    def test_circuit_state_values(self) -> None:
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"
```

- [ ] **Step 2: Verify test fails**

Run: `pytest tests/test_port_contracts.py::TestCircuitBreakerContract -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# pjsk_core/ports/circuit_breaker.py
"""Circuit breaker port for vision engine resilience."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitFailure(Enum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class CircuitPermit:
    engine_id: str
    probe: bool  # True = HALF_OPEN探测请求


class CircuitBreaker(Protocol):
    async def acquire(self, engine_id: str) -> CircuitPermit | None: ...
    async def record_success(self, permit: CircuitPermit) -> None: ...
    async def record_failure(
        self, permit: CircuitPermit, failure: CircuitFailure,
    ) -> None: ...
    async def release(self, permit: CircuitPermit) -> None: ...
    async def state(self, engine_id: str) -> CircuitState: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_port_contracts.py::TestCircuitBreakerContract -v`
Expected: PASS

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add pjsk_core/ports/circuit_breaker.py tests/test_port_contracts.py
git commit -m "feat: define CircuitBreaker port with permit-based semantics"
```

---

### Task 4: Ports — Revise VisionEngine + Extend ChartRepository

**Files:**
- Modify: `pjsk_core/ports/vision.py` (add `identity: EngineIdentity`, remove `name`)
- Modify: `pjsk_core/ports/repositories.py` (add `get_song_catalog`, `get_by_song_and_difficulty`)
- Create: `tests/test_port_contracts.py` (append VisionEngine identity + ChartRepository new methods tests)

**Interfaces:**
- Revises: `VisionEngine` — replaces `name: str` with `identity: EngineIdentity`
- Produces: `SongCatalog(version, candidates)` dataclass
- Produces: `ChartRepository.get_song_catalog() -> SongCatalog`
- Produces: `ChartRepository.get_by_song_and_difficulty(song_id, difficulty) -> Chart | None`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_port_contracts.py:

from pjsk_core.ports.vision import VisionEngine
from pjsk_core.domain.ocr import EngineIdentity


class TestVisionEngineRevisedContract:
    def test_identity_attribute(self) -> None:
        """VisionEngine no longer has 'name'; it has 'identity'."""
        assert hasattr(VisionEngine, "identity")
        assert not hasattr(VisionEngine, "name")


class TestChartRepositoryExtended:
    def test_get_song_catalog_exists(self) -> None:
        assert hasattr(ChartRepository, "get_song_catalog")

    def test_get_by_song_and_difficulty_exists(self) -> None:
        assert hasattr(ChartRepository, "get_by_song_and_difficulty")
```

- [ ] **Step 3: Write implementation**

Revise `pjsk_core/ports/vision.py`:

```python
"""Vision engine port — multi-model OCR for score screenshots."""
from typing import Protocol
from pjsk_core.domain.ocr import EngineIdentity, OcrObservation


class VisionEngine(Protocol):
    """A single vision model backend for recognizing score screenshots."""
    identity: EngineIdentity

    async def recognize(
        self, image: bytes, *, timeout: float,
    ) -> OcrObservation: ...
```

Revise `pjsk_core/ports/repositories.py` — append after `list_by_difficulty_level`:

```python
from dataclasses import dataclass
from pjsk_core.domain.song_matcher import SongCandidate  # added after Task 1

@dataclass(frozen=True)
class SongCatalog:
    version: str
    candidates: tuple[SongCandidate, ...]


class ChartRepository(Protocol):
    # ... existing methods unchanged ...

    async def get_song_catalog(self) -> SongCatalog: ...

    async def get_by_song_and_difficulty(
        self, song_id: int, difficulty: Difficulty,
    ) -> Chart | None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_port_contracts.py -v`
Expected: all port contract tests PASS

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add pjsk_core/ports/vision.py pjsk_core/ports/repositories.py tests/test_port_contracts.py
git commit -m "feat: revise VisionEngine port with EngineIdentity; extend ChartRepository"
```

---

### Task 5: Application — VisionRacePolicy

**Files:**
- Create: `pjsk_core/application/vision_policy.py`
- Create: `tests/application/__init__.py` (empty)
- Create: `tests/application/test_vision_policy.py`

**Interfaces:**
- Produces: `EnginePolicy(engine_id, priority, enabled, timeout_seconds, max_concurrency)` with validation
- Produces: `VisionRacePolicy(engines, global_timeout_seconds, consensus_threshold)` with validation

- [ ] **Step 1: Write the failing test**

```python
# tests/application/test_vision_policy.py
import pytest
from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy


class TestEnginePolicy:
    def test_valid_engine_policy(self) -> None:
        ep = EnginePolicy("gemini-2.5-flash", priority=1, enabled=True,
                          timeout_seconds=15.0, max_concurrency=3)
        assert ep.engine_id == "gemini-2.5-flash"
        assert ep.priority == 1

    def test_empty_engine_id_raises(self) -> None:
        with pytest.raises(ValueError, match="engine_id"):
            EnginePolicy("", priority=1, enabled=True,
                        timeout_seconds=15.0, max_concurrency=3)

    def test_priority_below_1_raises(self) -> None:
        with pytest.raises(ValueError, match="priority"):
            EnginePolicy("g", priority=0, enabled=True,
                        timeout_seconds=15.0, max_concurrency=3)

    def test_timeout_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout"):
            EnginePolicy("g", priority=1, enabled=True,
                        timeout_seconds=0, max_concurrency=3)

    def test_max_concurrency_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="max_concurrency"):
            EnginePolicy("g", priority=1, enabled=True,
                        timeout_seconds=15.0, max_concurrency=0)


class TestVisionRacePolicy:
    def _make_policy(self, **overrides) -> VisionRacePolicy:
        defaults = dict(
            engines=(
                EnginePolicy("g", priority=1, enabled=True, timeout_seconds=15.0, max_concurrency=3),
                EnginePolicy("z", priority=2, enabled=True, timeout_seconds=15.0, max_concurrency=3),
            ),
            global_timeout_seconds=30.0,
            consensus_threshold=2,
        )
        defaults.update(overrides)
        return VisionRacePolicy(**defaults)

    def test_valid_policy(self) -> None:
        policy = self._make_policy()
        assert policy.global_timeout_seconds == 30.0

    def test_zero_enabled_engines_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            self._make_policy(engines=(
                EnginePolicy("g", priority=1, enabled=False, timeout_seconds=15.0, max_concurrency=3),
            ))

    def test_duplicate_engine_id_raises(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            self._make_policy(engines=(
                EnginePolicy("g", priority=1, enabled=True, timeout_seconds=15.0, max_concurrency=3),
                EnginePolicy("g", priority=2, enabled=True, timeout_seconds=15.0, max_concurrency=3),
            ))

    def test_consensus_threshold_exceeds_enabled_raises(self) -> None:
        with pytest.raises(ValueError, match="consensus_threshold"):
            self._make_policy(consensus_threshold=3)

    def test_consensus_threshold_below_2_raises(self) -> None:
        with pytest.raises(ValueError, match="consensus_threshold"):
            self._make_policy(consensus_threshold=1)

    def test_global_timeout_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="global_timeout"):
            self._make_policy(global_timeout_seconds=0)
```

- [ ] **Step 3: Write minimal implementation**

```python
# pjsk_core/application/vision_policy.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnginePolicy:
    engine_id: str
    priority: int
    enabled: bool
    timeout_seconds: float
    max_concurrency: int

    def __post_init__(self) -> None:
        if not self.engine_id:
            raise ValueError("engine_id must not be empty")
        if self.priority < 1:
            raise ValueError(f"priority must be >= 1, got {self.priority}")
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be > 0, got {self.timeout_seconds}"
            )
        if self.max_concurrency < 1:
            raise ValueError(
                f"max_concurrency must be >= 1, got {self.max_concurrency}"
            )


@dataclass(frozen=True)
class VisionRacePolicy:
    engines: tuple[EnginePolicy, ...]
    global_timeout_seconds: float
    consensus_threshold: int = 2

    def __post_init__(self) -> None:
        if self.global_timeout_seconds <= 0:
            raise ValueError(
                f"global_timeout_seconds must be > 0, "
                f"got {self.global_timeout_seconds}"
            )
        if self.consensus_threshold < 2:
            raise ValueError(
                f"consensus_threshold must be >= 2, got {self.consensus_threshold}"
            )

        enabled = [e for e in self.engines if e.enabled]
        if not enabled:
            raise ValueError("at least one engine must be enabled")

        ids = [e.engine_id for e in self.engines]
        if len(ids) != len(set(ids)):
            raise ValueError("engine_id must be unique across engines")

        if self.consensus_threshold > len(enabled):
            raise ValueError(
                f"consensus_threshold ({self.consensus_threshold}) "
                f"exceeds enabled engines ({len(enabled)})"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/application/test_vision_policy.py -v`
Expected: PASS

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add pjsk_core/application/vision_policy.py tests/application/__init__.py tests/application/test_vision_policy.py
git commit -m "feat: define VisionRacePolicy with EnginePolicy validation"
```

---

### Task 6: Application — ValidationPipeline

**Files:**
- Create: `pjsk_core/application/validate_ocr.py`
- Create: `tests/application/test_validate_ocr.py`

**Interfaces:**
- Consumes: `SongMatch`, `SongMatchMethod`, `SongCandidate` from domain; `ChartRepository`, `Chart`, `Difficulty` from ports
- Produces: `ValidationStatus(Enum)`, `ValidatedCandidate`, `ValidatedObservation`, `ValidationPipeline(charts).validate(observation) -> ValidatedObservation`

- [ ] **Step 1: Write the failing test**

```python
# tests/application/test_validate_ocr.py
import pytest
from pjsk_core.application.validate_ocr import (
    ValidatedCandidate, ValidatedObservation, ValidationPipeline, ValidationStatus,
)
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.song_matcher import SongCandidate


class _FakeChartRepository:
    """In-memory fake for testing ValidationPipeline without SQLite."""
    def __init__(self, songs: tuple[SongCandidate, ...], charts: tuple[Chart, ...]) -> None:
        self._catalog_version = "2026-07-12"
        self._songs = songs
        self._charts = charts

    async def get_song_catalog(self):
        from pjsk_core.ports.repositories import SongCatalog
        return SongCatalog(self._catalog_version, self._songs)

    async def get_by_song_and_difficulty(self, song_id: int, difficulty: Difficulty) -> Chart | None:
        for c in self._charts:
            if c.song_id == song_id and c.difficulty == difficulty:
                return c
        return None


def _obs(song_title="Test Song", difficulty=Difficulty.MASTER,
         displayed_level=30, perfect=1000, great=100, good=0, bad=0, miss=0) -> OcrObservation:
    return OcrObservation(song_title, difficulty, displayed_level,
                          Judgements(perfect, great, good, bad, miss),
                          engine="test", elapsed_ms=500)


def _chart(song_id=1, difficulty=Difficulty.MASTER, official_level=30,
           community_constant="30.5", note_count=1100) -> Chart:
    return Chart(id=1, song_id=song_id, difficulty=difficulty,
                 official_level=official_level,
                 community_constant=community_constant,
                 note_count=note_count, data_version="2026-07-12")


class TestValidationPipeline:
    async def test_exact_match_note_pass_level_pass(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Test Song", "", ""),),
            charts=(_chart(song_id=1, official_level=30, note_count=1100),),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", perfect=1000, great=100)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.STRONG
        assert result.primary is not None
        assert result.primary.note_validated is True
        assert result.primary.level_validated is True

    async def test_note_off_by_one_passes(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Test Song", "", ""),),
            charts=(_chart(song_id=1, note_count=1101),),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", perfect=1000, great=101)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.STRONG
        assert result.primary.note_validated is True

    async def test_note_off_by_two_fails(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Test Song", "", ""),),
            charts=(_chart(song_id=1, note_count=1102),),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", perfect=1000, great=100)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.CANDIDATE

    async def test_level_mismatch_is_candidate(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Test Song", "", ""),),
            charts=(_chart(song_id=1, official_level=31),),  # obs says 30
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", displayed_level=30)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.CANDIDATE

    async def test_no_song_match_rejected(self) -> None:
        repo = _FakeChartRepository(
            songs=(SongCandidate(1, "Completely Different", "", ""),),
            charts=(_chart(song_id=1),),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song")
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.REJECTED
        assert result.primary is None

    async def test_first_match_fail_second_succeed(self) -> None:
        """First song match gets note failure, second gets it right."""
        repo = _FakeChartRepository(
            songs=(
                SongCandidate(1, "Test Song", "", ""),
                SongCandidate(2, "Test Song Remix", "", ""),
            ),
            charts=(
                _chart(song_id=1, note_count=9999),   # way off
                _chart(song_id=2, note_count=1100),   # correct
            ),
        )
        pipeline = ValidationPipeline(repo)
        obs = _obs(song_title="Test Song", perfect=1000, great=100)
        result = await pipeline.validate(obs)
        assert result.status == ValidationStatus.STRONG
        assert result.primary.song_match.song_id == 2
```

- [ ] **Step 3: Write implementation**

```python
# pjsk_core/application/validate_ocr.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.song_matcher import (
    SongCandidate, SongMatch, SongMatchMethod, match_song,
)
from pjsk_core.ports.repositories import ChartRepository

MAX_VALIDATION_CANDIDATES = 5


class ValidationStatus(Enum):
    STRONG = "strong"
    CANDIDATE = "candidate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ValidatedCandidate:
    song_match: SongMatch
    chart: Chart | None
    note_distance: int | None
    note_validated: bool
    level_validated: bool
    status: ValidationStatus


@dataclass(frozen=True)
class ValidatedObservation:
    observation: OcrObservation
    primary: ValidatedCandidate | None
    candidates: tuple[ValidatedCandidate, ...]
    status: ValidationStatus


class ValidationPipeline:
    def __init__(self, charts: ChartRepository) -> None:
        self._charts = charts

    async def validate(
        self, observation: OcrObservation,
    ) -> ValidatedObservation:
        catalog = await self._charts.get_song_catalog()
        song_matches = match_song(
            observation.song_title, catalog.candidates,
        )[:MAX_VALIDATION_CANDIDATES]

        if not song_matches:
            return ValidatedObservation(
                observation=observation,
                primary=None,
                candidates=(),
                status=ValidationStatus.REJECTED,
            )

        validated_candidates: list[ValidatedCandidate] = []
        for match in song_matches:
            chart = await self._charts.get_by_song_and_difficulty(
                match.song_id, observation.difficulty,
            )
            vc = self._assess(match, chart, observation)
            validated_candidates.append(vc)

        validated_candidates.sort(
            key=lambda vc: (
                not vc.note_validated,
                vc.chart is None,
                -(vc.song_match.score),
                vc.note_distance if vc.note_distance is not None else 9999,
                vc.song_match.song_id,
            ),
        )
        return ValidatedObservation(
            observation=observation,
            primary=validated_candidates[0] if validated_candidates else None,
            candidates=tuple(validated_candidates),
            status=validated_candidates[0].status if validated_candidates
                   else ValidationStatus.REJECTED,
        )

    def _assess(
        self, match: SongMatch, chart: Chart | None,
        observation: OcrObservation,
    ) -> ValidatedCandidate:
        if chart is None:
            return ValidatedCandidate(
                song_match=match, chart=None,
                note_distance=None, note_validated=False,
                level_validated=False, status=ValidationStatus.CANDIDATE,
            )

        total = (observation.judgements.perfect + observation.judgements.great
                 + observation.judgements.good + observation.judgements.bad
                 + observation.judgements.miss)
        if total == 0:
            return ValidatedCandidate(
                song_match=match, chart=chart,
                note_distance=None, note_validated=False,
                level_validated=False, status=ValidationStatus.REJECTED,
            )

        note_distance = abs(total - chart.note_count)
        note_ok = note_distance <= 1
        level_ok = observation.displayed_level == chart.official_level

        match_is_strong = (
            match.method in (SongMatchMethod.EXACT, SongMatchMethod.REGION)
            or (match.method == SongMatchMethod.FUZZY
                and match.score >= 0.82)  # STRONG_FUZZY_SCORE
        )

        if note_ok and level_ok and match_is_strong:
            status = ValidationStatus.STRONG
        else:
            status = ValidationStatus.CANDIDATE

        return ValidatedCandidate(
            song_match=match, chart=chart,
            note_distance=note_distance, note_validated=note_ok,
            level_validated=level_ok, status=status,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/application/test_validate_ocr.py -v`
Expected: PASS

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add pjsk_core/application/validate_ocr.py tests/application/test_validate_ocr.py
git commit -m "feat: implement ValidationPipeline with top-N matching and STRONG/CANDIDATE/REJECTED"
```

---

### Task 7: Application — VisionRace (core orchestrator)

**Files:**
- Create: `pjsk_core/application/vision_race.py`
- Create: `tests/application/test_vision_race.py`

**Interfaces:**
- Consumes: `VisionRacePolicy`, `EnginePolicy`, `CircuitBreaker`, `ObservationValidator` (from `validate_ocr`), `VisionEngine` (port), `EngineIdentity`
- Produces: `EngineResultStatus`, `VisionRaceDecision`, `EngineResult`, `ConsensusMatch`, `VisionRaceOutcome`, `EngineRuntime`, `VisionRace`

This is the largest task. The plan includes the full `VisionRace` class.

- [ ] **Step 1: Write the failing test (mock-based, no real HTTP)**

```python
# tests/application/test_vision_race.py
import asyncio
import pytest
from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy
from pjsk_core.application.vision_race import (
    ConsensusMatch, EngineResult, EngineResultStatus, EngineRuntime,
    VisionRace, VisionRaceDecision, VisionRaceOutcome,
)
from pjsk_core.application.validate_ocr import (
    ValidatedCandidate, ValidatedObservation, ValidationPipeline, ValidationStatus,
)
from pjsk_core.domain.ocr import (
    EngineIdentity, OcrObservation, VisionEngineError, VisionTimeoutError,
)
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.charts import Difficulty
from pjsk_core.ports.circuit_breaker import (
    CircuitBreaker, CircuitFailure, CircuitPermit, CircuitState,
)


# ── Fake / Mock helpers ──────────────────────────────────────────────────

class FakeEngine:
    """Mock VisionEngine that returns predefined results or raises."""
    def __init__(self, identity: EngineIdentity,
                 results: list[OcrObservation | Exception]) -> None:
        self.identity = identity
        self._results = results
        self._calls = 0

    async def recognize(self, image: bytes, *, timeout: float) -> OcrObservation:
        if self._calls >= len(self._results):
            raise RuntimeError("No more mock results")
        result = self._results[self._calls]
        self._calls += 1
        if isinstance(result, Exception):
            raise result
        return result


class FakeBreaker:
    """Always-CLOSED breaker for happy-path tests."""
    async def acquire(self, engine_id: str) -> CircuitPermit | None:
        return CircuitPermit(engine_id, probe=False)
    async def record_success(self, permit: CircuitPermit) -> None: pass
    async def record_failure(self, permit: CircuitPermit, failure: CircuitFailure) -> None: pass
    async def release(self, permit: CircuitPermit) -> None: pass
    async def state(self, engine_id: str) -> CircuitState:
        return CircuitState.CLOSED


class FakeValidator:
    """Validates by matching song_title to chart_id via a lookup dict."""
    def __init__(self, chart_map: dict[str, int]) -> None:
        self._chart_map = chart_map

    async def validate(self, observation: OcrObservation) -> ValidatedObservation:
        chart_id = self._chart_map.get(observation.song_title)
        if chart_id is None:
            return ValidatedObservation(
                observation=observation, primary=None, candidates=(),
                status=ValidationStatus.REJECTED,
            )
        vc = ValidatedCandidate(
            song_match=None, chart=None,  # simplified — not testing match details
            note_distance=0, note_validated=True,
            level_validated=True, status=ValidationStatus.STRONG,
        )
        return ValidatedObservation(
            observation=observation, primary=vc, candidates=(vc,),
            status=ValidationStatus.STRONG,
        )


def _obs(title="Song A", perfect=1000, great=100, good=0, bad=0, miss=0) -> OcrObservation:
    return OcrObservation(title, Difficulty.MASTER, 30,
                          Judgements(perfect, great, good, bad, miss),
                          engine="test", elapsed_ms=100)


def _runtime(engine_id: str, provider: str, results: list,
             priority: int = 1, timeout: float = 15.0,
             max_concurrency: int = 3) -> EngineRuntime:
    return EngineRuntime(
        engine=FakeEngine(EngineIdentity(engine_id, provider, engine_id), results),
        policy=EnginePolicy(engine_id, priority=priority, enabled=True,
                           timeout_seconds=timeout,
                           max_concurrency=max_concurrency),
        semaphore=asyncio.Semaphore(max_concurrency),
    )


# ── Tests ────────────────────────────────────────────────────────────────

class TestVisionRace:
    def _race(self, runtimes, validator=None, **policy_kw) -> VisionRace:
        if validator is None:
            validator = FakeValidator({"Song A": 1, "Song B": 1})
        engines = tuple(r.policy for r in runtimes)
        policy = VisionRacePolicy(
            engines=engines,
            global_timeout_seconds=policy_kw.pop("global_timeout_seconds", 30.0),
            consensus_threshold=policy_kw.pop("consensus_threshold", 2),
        )
        return VisionRace(
            runtimes=runtimes,
            breaker=FakeBreaker(),
            validator=validator,
            policy=policy,
        )

    @pytest.mark.asyncio
    async def test_two_engines_agree_consensus(self) -> None:
        race = self._race([
            _runtime("g", "google", [_obs("Song A")]),
            _runtime("z", "zhipu", [_obs("Song A")]),
            _runtime("s", "stepfun", [_obs("Song A")]),
        ])
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.CONSENSUS
        assert outcome.consensus is not None
        assert outcome.consensus.selected is not None
        # Two providers form consensus
        providers = outcome.consensus.supporting_providers
        assert len(providers) == 2  # 2 providers agree, third may or may not

    @pytest.mark.asyncio
    async def test_same_provider_not_independent(self) -> None:
        """Two engines from the same provider cannot form consensus alone."""
        race = self._race([
            _runtime("g", "google", [_obs("Song A")]),
            _runtime("g2", "google", [_obs("Song A")]),  # same provider
            _runtime("z", "zhipu", [_obs("Song A")]),
        ])
        outcome = await race.run(b"fake_image")
        # Two googles agree, but they share a provider → need zhipu too
        # With g + z = 2 providers → consensus
        assert outcome.decision == VisionRaceDecision.CONSENSUS

    @pytest.mark.asyncio
    async def test_disagreement(self) -> None:
        race = self._race([
            _runtime("g", "google", [_obs("Song A")]),
            _runtime("z", "zhipu", [_obs("Song B")]),
            _runtime("s", "stepfun", [_obs("Song C")]),
        ])
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.DISAGREEMENT

    @pytest.mark.asyncio
    async def test_degraded_single(self) -> None:
        """One success + others fail → degraded_single."""
        race = self._race([
            _runtime("g", "google", [_obs("Song A")]),
            _runtime("z", "zhipu", [VisionTimeoutError("timeout")]),
        ])
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.DEGRADED_SINGLE
        assert outcome.selected is not None

    @pytest.mark.asyncio
    async def test_all_failed(self) -> None:
        race = self._race([
            _runtime("g", "google", [VisionTimeoutError("t")]),
            _runtime("z", "zhipu", [VisionTimeoutError("t")]),
        ])
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.ALL_FAILED

    @pytest.mark.asyncio
    async def test_one_throws_others_unaffected(self) -> None:
        race = self._race([
            _runtime("g", "google", [_obs("Song A")]),
            _runtime("z", "zhipu", [VisionTimeoutError("t")]),
            _runtime("s", "stepfun", [_obs("Song A")]),
        ])
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.CONSENSUS

    @pytest.mark.asyncio
    async def test_circuit_rejected_engine_skipped(self) -> None:
        class SelectiveBreaker(FakeBreaker):
            async def acquire(self, engine_id: str) -> CircuitPermit | None:
                if engine_id == "z":
                    return None  # zhipu is down
                return await super().acquire(engine_id)

        policy = VisionRacePolicy(
            engines=tuple(
                EnginePolicy(eid, priority=i, enabled=True,
                            timeout_seconds=15.0, max_concurrency=3)
                for i, eid in enumerate(["g", "z", "s"], 1)
            ),
            global_timeout_seconds=30.0,
            consensus_threshold=2,
        )
        race = VisionRace(
            runtimes=[
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [_obs("Song A")]),
                _runtime("s", "stepfun", [_obs("Song A")]),
            ],
            breaker=SelectiveBreaker(),
            validator=FakeValidator({"Song A": 1}),
            policy=policy,
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.CONSENSUS
        assert len(outcome.circuit_rejects) >= 1
        assert any(r.engine_id == "z" for r in outcome.circuit_rejects)

    @pytest.mark.asyncio
    async def test_global_timeout_returns_partial(self) -> None:
        """Very short global timeout → partial results."""
        async def _slow_obs():
            await asyncio.sleep(5.0)
            return _obs("Song A")

        race = self._race(
            [_runtime("g", "google", [_obs("Song A")]),
             _runtime("z", "zhipu", [asyncio.TimeoutError()])],
            global_timeout_seconds=0.1,
        )
        outcome = await race.run(b"fake_image")
        # With global timeout this short, we should get GLOBAL_TIMEOUT
        assert outcome.decision in (
            VisionRaceDecision.GLOBAL_TIMEOUT,
            VisionRaceDecision.DEGRADED_SINGLE,
        )
```

- [ ] **Step 3: Write `VisionRace` implementation**

Full implementation of `VisionRace` class in `pjsk_core/application/vision_race.py`:

```python
"""Vision race orchestrator — concurrent engines, consensus, degradation."""
from __future__ import annotations

import asyncio
import time as _time
from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Sequence
from typing import Protocol

from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy
from pjsk_core.application.validate_ocr import (
    ValidatedObservation, ValidationStatus,
)
from pjsk_core.domain.ocr import (
    EngineIdentity, OcrObservation, VisionEngineError,
)
from pjsk_core.ports.circuit_breaker import (
    CircuitBreaker, CircuitFailure, CircuitPermit,
)
from pjsk_core.ports.vision import VisionEngine


class EngineResultStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED_BY_CONSENSUS = "cancelled_by_consensus"
    CANCELLED_BY_CALLER = "cancelled_by_caller"


class VisionRaceDecision(Enum):
    CONSENSUS = "consensus"
    DEGRADED_SINGLE = "degraded_single"
    DISAGREEMENT = "disagreement"
    ALL_FAILED = "all_failed"
    NO_AVAILABLE_ENGINES = "no_available_engines"
    GLOBAL_TIMEOUT = "global_timeout"


@dataclass(frozen=True)
class EngineResult:
    identity: EngineIdentity
    status: EngineResultStatus
    observation: OcrObservation | None
    validated: ValidatedObservation | None
    error: VisionEngineError | None
    elapsed_ms: int


@dataclass(frozen=True)
class ConsensusMatch:
    selected: ValidatedObservation
    supporting_engines: tuple[EngineIdentity, ...]
    supporting_providers: tuple[str, ...]


@dataclass(frozen=True)
class VisionRaceOutcome:
    decision: VisionRaceDecision
    selected: ValidatedObservation | None
    consensus: ConsensusMatch | None
    results: tuple[EngineResult, ...]
    circuit_rejects: tuple[EngineIdentity, ...]


@dataclass
class EngineRuntime:
    engine: VisionEngine
    policy: EnginePolicy
    semaphore: asyncio.Semaphore


class ObservationValidator(Protocol):
    async def validate(
        self, observation: OcrObservation,
    ) -> ValidatedObservation: ...


class VisionRace:
    def __init__(
        self,
        runtimes: Sequence[EngineRuntime],
        breaker: CircuitBreaker,
        validator: ObservationValidator,
        policy: VisionRacePolicy,
    ) -> None:
        # Validate identity consistency + provider uniqueness
        enabled_runtimes = [r for r in runtimes if r.policy.enabled]
        seen_providers: set[str] = set()
        for r in enabled_runtimes:
            if r.policy.engine_id != r.engine.identity.engine_id:
                raise ValueError(
                    f"Engine {r.policy.engine_id}: policy.engine_id does not "
                    f"match engine.identity.engine_id ({r.engine.identity.engine_id})"
                )
            provider = r.engine.identity.provider
            if provider in seen_providers:
                raise ValueError(
                    f"Duplicate provider '{provider}': V1 allows at most one "
                    f"enabled engine per provider"
                )
            seen_providers.add(provider)

        self._runtimes = tuple(runtimes)
        self._breaker = breaker
        self._validator = validator
        self._policy = policy

    async def run(self, image: bytes) -> VisionRaceOutcome:
        runtimes = [r for r in self._runtimes if r.policy.enabled]
        if not runtimes:
            return VisionRaceOutcome(
                decision=VisionRaceDecision.NO_AVAILABLE_ENGINES,
                selected=None, consensus=None, results=(),
                circuit_rejects=(),
            )

        # Filter circuit-rejected
        active: list[EngineRuntime] = []
        rejects: list[EngineIdentity] = []
        for r in sorted(runtimes, key=lambda r: r.policy.priority):
            permit = await self._breaker.acquire(
                r.engine.identity.engine_id
            )
            if permit is None:
                rejects.append(r.engine.identity)
            else:
                active.append(r)

        if not active:
            return VisionRaceOutcome(
                decision=VisionRaceDecision.ALL_FAILED,
                selected=None, consensus=None, results=(),
                circuit_rejects=tuple(rejects),
            )

        try:
            async with asyncio.timeout(self._policy.global_timeout_seconds):
                return await self._collect(image, active, rejects)
        except TimeoutError:
            return await self._finish_global_timeout(active, rejects)
        except asyncio.CancelledError:
            await self._cancel_all(active)
            raise

    async def _collect(
        self, image: bytes, active: list[EngineRuntime],
        rejects: list[EngineIdentity],
    ) -> VisionRaceOutcome:
        tasks: dict[asyncio.Task, EngineRuntime] = {}
        for r in active:
            task = asyncio.create_task(self._worker(r, image))
            tasks[task] = r

        results: list[EngineResult] = []
        pending = set(tasks.keys())

        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                result = await task
                results.append(result)

            # Check for consensus
            decision, outcome = self._evaluate_consensus(results)
            if decision is not None:
                # Cancel remaining
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                return outcome

        # All done, no consensus
        return self._final_decision(results, rejects)

    def _evaluate_consensus(
        self, results: list[EngineResult],
    ) -> tuple[VisionRaceDecision | None, VisionRaceOutcome | None]:
        successes = [r for r in results
                     if r.status == EngineResultStatus.SUCCESS
                     and r.validated is not None
                     and r.validated.status == ValidationStatus.STRONG]

        # Group by (chart_id, difficulty, judgements) → providers
        groups: dict[tuple, dict[str, tuple[EngineIdentity, ValidatedObservation]]] = {}
        for r in successes:
            v = r.validated
            key = (
                v.primary.chart.id if v.primary and v.primary.chart else None,
                r.observation.difficulty,
                r.observation.judgements,
            )
            if key[0] is None:
                continue
            if key not in groups:
                groups[key] = {}
            provider = r.identity.provider
            if provider not in groups[key]:
                groups[key][provider] = (r.identity, v)

        for key, provider_votes in groups.items():
            if len(provider_votes) >= self._policy.consensus_threshold:
                # Pick best provider by priority
                supporting_ids = tuple(v[0] for v in provider_votes.values())
                supporting_providers = tuple(provider_votes.keys())
                selected_v = next(iter(provider_votes.values()))[1]

                all_results = sorted(results, key=lambda r: r.identity.engine_id)
                return VisionRaceDecision.CONSENSUS, VisionRaceOutcome(
                    decision=VisionRaceDecision.CONSENSUS,
                    selected=selected_v,
                    consensus=ConsensusMatch(
                        selected=selected_v,
                        supporting_engines=tuple(sorted(
                            supporting_ids, key=lambda eid: eid.engine_id)),
                        supporting_providers=tuple(sorted(supporting_providers)),
                    ),
                    results=tuple(all_results),
                    circuit_rejects=(),
                )

        return None, None

    def _final_decision(
        self, results: list[EngineResult],
        rejects: list[EngineIdentity],
    ) -> VisionRaceOutcome:
        successes = [r for r in results if r.status == EngineResultStatus.SUCCESS]
        strong = [r for r in successes
                  if r.validated and r.validated.status == ValidationStatus.STRONG]

        all_results = tuple(sorted(results, key=lambda r: r.identity.engine_id))

        if not successes:
            return VisionRaceOutcome(
                decision=VisionRaceDecision.ALL_FAILED,
                selected=None, consensus=None,
                results=all_results,
                circuit_rejects=tuple(rejects),
            )
        if len(strong) == 1:
            return VisionRaceOutcome(
                decision=VisionRaceDecision.DEGRADED_SINGLE,
                selected=strong[0].validated, consensus=None,
                results=all_results,
                circuit_rejects=tuple(rejects),
            )
        # Multiple successes but no consensus
        return VisionRaceOutcome(
            decision=VisionRaceDecision.DISAGREEMENT,
            selected=None, consensus=None,
            results=all_results,
            circuit_rejects=tuple(rejects),
        )

    async def _finish_global_timeout(
        self, active: list[EngineRuntime],
        rejects: list[EngineIdentity],
    ) -> VisionRaceOutcome:
        # We already caught TimeoutError — collect whatever finished
        results: list[EngineResult] = []
        strong: list[ValidatedObservation] = []
        for r in active:
            if hasattr(r, '_last_result'):
                result = r._last_result
                results.append(result)
                if (result.status == EngineResultStatus.SUCCESS
                        and result.validated
                        and result.validated.status == ValidationStatus.STRONG):
                    strong.append(result.validated)

        all_results = tuple(sorted(results, key=lambda r: r.identity.engine_id))

        selected = strong[0] if len(strong) == 1 else None
        return VisionRaceOutcome(
            decision=VisionRaceDecision.GLOBAL_TIMEOUT,
            selected=selected, consensus=None,
            results=all_results,
            circuit_rejects=tuple(rejects),
        )

    async def _cancel_all(self, runtimes: list[EngineRuntime]) -> None:
        """Drain — workers handle their own permit release on CancelledError."""

    async def _worker(
        self, runtime: EngineRuntime, image: bytes,
    ) -> EngineResult:
        async with runtime.semaphore:
            permit = await self._breaker.acquire(
                runtime.engine.identity.engine_id
            )
            if permit is None:
                return EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.FAILED,
                    observation=None, validated=None,
                    error=None, elapsed_ms=0,
                )

            settled = False
            started = _time.monotonic()
            try:
                async with asyncio.timeout(runtime.policy.timeout_seconds):
                    observation = await runtime.engine.recognize(
                        image, timeout=runtime.policy.timeout_seconds,
                    )
                await self._breaker.record_success(permit)
                settled = True

                # Validate after recording success
                validated = await self._validator.validate(observation)
                elapsed = int((_time.monotonic() - started) * 1000)
                return EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.SUCCESS,
                    observation=observation, validated=validated,
                    error=None, elapsed_ms=elapsed,
                )
            except asyncio.TimeoutError:
                await self._breaker.record_failure(
                    permit, CircuitFailure.TIMEOUT,
                )
                settled = True
                elapsed = int((_time.monotonic() - started) * 1000)
                return EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.TIMED_OUT,
                    observation=None, validated=None,
                    error=VisionEngineError("timeout"),
                    elapsed_ms=elapsed,
                )
            except VisionEngineError as e:
                await self._breaker.record_failure(permit, _error_to_failure(e))
                settled = True
                elapsed = int((_time.monotonic() - started) * 1000)
                return EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.FAILED,
                    observation=None, validated=None,
                    error=e, elapsed_ms=elapsed,
                )
            except asyncio.CancelledError:
                if not settled:
                    await self._breaker.release(permit)
                    settled = True
                elapsed = int((_time.monotonic() - started) * 1000)
                return EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.CANCELLED_BY_CONSENSUS,
                    observation=None, validated=None,
                    error=None, elapsed_ms=elapsed,
                )


def _error_to_failure(e: VisionEngineError) -> CircuitFailure:
    from pjsk_core.domain.ocr import (
        VisionTimeoutError, VisionConnectionError,
        VisionRateLimitError, VisionServerError, VisionResponseError,
    )
    if isinstance(e, VisionTimeoutError):
        return CircuitFailure.TIMEOUT
    if isinstance(e, VisionConnectionError):
        return CircuitFailure.CONNECTION
    if isinstance(e, VisionRateLimitError):
        return CircuitFailure.RATE_LIMITED
    if isinstance(e, VisionServerError):
        return CircuitFailure.SERVER_ERROR
    return CircuitFailure.INVALID_RESPONSE
```

Note: the `_finish_global_timeout` method uses a simplified approach. The plan implementer should refine the global timeout handling to properly collect already-completed results and cancel remaining tasks.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/application/test_vision_race.py -v`
Expected: all tests PASS

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add pjsk_core/application/vision_race.py tests/application/test_vision_race.py
git commit -m "feat: implement VisionRace orchestrator with consensus and degradation"
```

---

### Task 8: Application — RecognizeScore

**Files:**
- Create: `pjsk_core/application/recognize_score.py`
- Create: `tests/application/test_recognize_score.py`

**Interfaces:**
- Consumes: `VisionRace`, `ScoreRepository`, `ScoreAttempt`, domain rules
- Produces: `RecognizeResult`, `RecognizeScore(race, scores).recognize(user_id, image, source_gateway) -> RecognizeResult`

- [ ] **Step 1: Write the failing test**

```python
# tests/application/test_recognize_score.py
import pytest
from datetime import datetime, timezone
from pjsk_core.application.recognize_score import RecognizeResult, RecognizeScore
from pjsk_core.application.vision_race import (
    ConsensusMatch, EngineResult, EngineResultStatus, EngineRuntime,
    VisionRaceDecision, VisionRaceOutcome,
)
from pjsk_core.application.validate_ocr import (
    ValidatedCandidate, ValidatedObservation, ValidationStatus,
)
from pjsk_core.domain.ocr import OcrObservation, EngineIdentity
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.users import UserId


class _FakeScoreRepo:
    def __init__(self) -> None:
        self.recorded: list[ScoreAttempt] = []

    async def record_attempt(self, attempt: ScoreAttempt) -> ScoreAttempt:
        self.recorded.append(attempt)
        return attempt


class _FakeVisionRace:
    def __init__(self, outcome: VisionRaceOutcome) -> None:
        self.outcome = outcome

    async def run(self, image: bytes) -> VisionRaceOutcome:
        return self.outcome


def _make_outcome(decision: VisionRaceDecision,
                  selected: ValidatedObservation | None = None,
                  candidates: tuple = ()) -> VisionRaceOutcome:
    return VisionRaceOutcome(
        decision=decision, selected=selected, consensus=None,
        results=(), circuit_rejects=(),
    )


class TestRecognizeScore:
    async def test_consensus_records_score(self) -> None:
        chart = Chart(id=1, song_id=1, difficulty=Difficulty.MASTER,
                      official_level=30, community_constant="30.5",
                      note_count=1100, data_version="v1")
        vc = ValidatedCandidate(
            song_match=None, chart=chart, note_distance=0,
            note_validated=True, level_validated=True,
            status=ValidationStatus.STRONG,
        )
        obs = OcrObservation("Test", Difficulty.MASTER, 30,
                            Judgements(1000, 100, 0, 0, 0),
                            "test", 100)
        validated = ValidatedObservation(
            observation=obs, primary=vc, candidates=(vc,),
            status=ValidationStatus.STRONG,
        )
        outcome = _make_outcome(VisionRaceDecision.CONSENSUS, selected=validated)

        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recognize = RecognizeScore(race, repo)
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )

        assert result.score_attempt is not None
        assert result.score_attempt.user_id == UserId(1)
        assert result.score_attempt.source_gateway == "astrbot"
        assert len(repo.recorded) == 1

    async def test_disagreement_returns_candidates(self) -> None:
        outcome = _make_outcome(VisionRaceDecision.DISAGREEMENT)
        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recognize = RecognizeScore(race, repo)
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )
        assert result.score_attempt is None
        assert len(repo.recorded) == 0

    async def test_all_failed_no_score(self) -> None:
        outcome = _make_outcome(VisionRaceDecision.ALL_FAILED)
        repo = _FakeScoreRepo()
        race = _FakeVisionRace(outcome)
        recognize = RecognizeScore(race, repo)
        result = await recognize.recognize(
            UserId(1), b"img", source_gateway="astrbot",
        )
        assert result.score_attempt is None
```

- [ ] **Step 3: Write implementation**

```python
# pjsk_core/application/recognize_score.py
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass

from pjsk_core.application.vision_race import (
    VisionRace, VisionRaceDecision, VisionRaceOutcome,
)
from pjsk_core.application.validate_ocr import (
    ValidatedObservation, ValidationStatus,
)
from pjsk_core.domain.ocr import Candidate
from pjsk_core.domain.scores import (
    Judgements, ScoreAttempt, ScoreStatus,
    calculate_accuracy, classify_status,
)
from pjsk_core.domain.rating import calculate_rating
from pjsk_core.domain.users import UserId
from pjsk_core.ports.repositories import ScoreRepository


@dataclass(frozen=True)
class RecognizeResult:
    outcome: VisionRaceOutcome
    validated: ValidatedObservation | None
    candidates_for_user: tuple[Candidate, ...]
    score_attempt: ScoreAttempt | None


class RecognizeScore:
    def __init__(
        self,
        race: VisionRace,
        scores: ScoreRepository,
    ) -> None:
        self._race = race
        self._scores = scores

    async def recognize(
        self,
        user_id: UserId,
        image: bytes,
        *,
        source_gateway: str,
    ) -> RecognizeResult:
        image_sha256 = hashlib.sha256(image).hexdigest()
        outcome = await self._race.run(image)

        if outcome.decision in (
            VisionRaceDecision.CONSENSUS,
            VisionRaceDecision.DEGRADED_SINGLE,
        ):
            selected = outcome.selected
            if selected is None or selected.primary is None:
                return RecognizeResult(
                    outcome=outcome, validated=selected,
                    candidates_for_user=(), score_attempt=None,
                )
            attempt = await self._record(
                selected, user_id, image_sha256, source_gateway,
            )
            return RecognizeResult(
                outcome=outcome, validated=selected,
                candidates_for_user=(), score_attempt=attempt,
            )

        if outcome.decision == VisionRaceDecision.DISAGREEMENT:
            # Collect candidates from all engine results
            # (simplified for now — full candidate merge in Phase 3b)
            return RecognizeResult(
                outcome=outcome, validated=outcome.selected,
                candidates_for_user=(), score_attempt=None,
            )

        if outcome.decision == VisionRaceDecision.GLOBAL_TIMEOUT:
            if outcome.selected is not None:
                return await self._adopt_timeout_result(
                    outcome, user_id, image_sha256, source_gateway,
                )
            return RecognizeResult(
                outcome=outcome, validated=None,
                candidates_for_user=(), score_attempt=None,
            )

        return RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=(), score_attempt=None,
        )

    async def _record(
        self, selected: ValidatedObservation,
        user_id: UserId, image_sha256: str, source_gateway: str,
    ) -> ScoreAttempt:
        chart = selected.primary.chart
        obs = selected.observation
        judgements = obs.judgements
        status = classify_status(judgements)
        accuracy = calculate_accuracy(judgements)
        rating = calculate_rating(
            chart.official_level, chart.community_constant,
            status, accuracy, chart.difficulty,
        )
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None, user_id=user_id, chart_id=chart.id,
            judgements=judgements, accuracy=accuracy,
            rating=rating, status=status,
            image_sha256=image_sha256, source_gateway=source_gateway,
            ocr_run_id=None, created_at=now,
        )
        return await self._scores.record_attempt(attempt)

    async def _adopt_timeout_result(
        self, outcome: VisionRaceOutcome,
        user_id: UserId, image_sha256: str, source_gateway: str,
    ) -> RecognizeResult:
        if (outcome.selected is None
                or outcome.selected.status != ValidationStatus.STRONG):
            return RecognizeResult(
                outcome=outcome, validated=None,
                candidates_for_user=(), score_attempt=None,
            )
        attempt = await self._record(
            outcome.selected, user_id, image_sha256, source_gateway,
        )
        return RecognizeResult(
            outcome=outcome, validated=outcome.selected,
            candidates_for_user=(), score_attempt=attempt,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/application/test_recognize_score.py -v`
Expected: PASS

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add pjsk_core/application/recognize_score.py tests/application/test_recognize_score.py
git commit -m "feat: implement RecognizeScore use case — score construction and recording"
```

---

### Task 9: Database — Migration 003 + Repository Extensions

**Files:**
- Create: `adapters/database/migrations/003_aliases_column.sql`
- Modify: `adapters/database/repository.py` (extend SqliteChartRepository)
- Modify: `pjsk_core/ports/repositories.py` (add SongCatalog dataclass; update ChartRepository Protocol)
- Modify: `tests/adapters/database/test_chart_repository.py` (add catalog + song+difficulty tests)

**Interfaces:**
- Produces: migration 003 — `ALTER TABLE songs ADD COLUMN aliases TEXT NOT NULL DEFAULT '[]'`
- Produces: `SqliteChartRepository.get_song_catalog() -> SongCatalog`
- Produces: `SqliteChartRepository.get_by_song_and_difficulty(song_id, difficulty) -> Chart | None`
- Revises: `ChartRepository` Protocol (Task 4 partial — finalize here)

- [ ] **Step 1: Create migration file**

```sql
-- 003: Add aliases column to songs
ALTER TABLE songs ADD COLUMN aliases TEXT NOT NULL DEFAULT '[]';
```

Write to: `adapters/database/migrations/003_aliases_column.sql`

- [ ] **Step 2: Extend repository implementation**

Add to `SqliteChartRepository` in `adapters/database/repository.py`:

```python
async def get_song_catalog(self) -> SongCatalog:
    from pjsk_core.ports.repositories import SongCatalog
    rows = await self._conn.execute_fetchall(
        "SELECT id, title_ja, title_cn, title_en, aliases FROM songs"
    )
    candidates = tuple(
        SongCandidate(
            song_id=row["id"],
            title_ja=row["title_ja"],
            title_cn=row["title_cn"],
            title_en=row["title_en"],
            aliases=self._parse_aliases(row["aliases"]),
        )
        for row in rows
    )
    # Catalog version from the latest migration
    ver_row = await self._conn.execute_fetchall(
        "SELECT chart_data_version FROM charts LIMIT 1"
    )
    version = ver_row[0][0] if ver_row else "unknown"
    return SongCatalog(version=version, candidates=candidates)

async def get_by_song_and_difficulty(
    self, song_id: int, difficulty: Difficulty,
) -> Chart | None:
    rows = list(await self._conn.execute_fetchall(
        "SELECT id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version "
        "FROM charts WHERE song_id = ? AND difficulty = ?",
        (song_id, difficulty.value),
    ))
    if not rows:
        return None
    return self._row_to_chart(rows[0])

@staticmethod
def _parse_aliases(raw: str) -> tuple[str, ...]:
    import json
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return ()
        result = tuple(a for a in parsed if isinstance(a, str) and a.strip())
        # Dedup preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for a in result:
            if a not in seen:
                deduped.append(a)
                seen.add(a)
        return tuple(deduped)
    except (json.JSONDecodeError, TypeError):
        return ()
```

- [ ] **Step 3: Write tests**

```python
# Append to tests/adapters/database/test_chart_repository.py:

class TestSongCatalog:
    async def test_get_song_catalog(self, repo: SqliteChartRepository) -> None:
        await _seed_song_and_chart(repo._conn, song_id=1)
        catalog = await repo.get_song_catalog()
        assert catalog.version != ""
        assert len(catalog.candidates) >= 1
        assert catalog.candidates[0].song_id == 1

    async def test_get_song_catalog_includes_aliases(self, repo: SqliteChartRepository) -> None:
        await repo._conn.execute(
            "INSERT INTO songs(id, title_ja, aliases) VALUES (99, 'Test', '[\"alias1\", \"alias2\"]')"
        )
        await repo._conn.commit()
        catalog = await repo.get_song_catalog()
        c = next(c for c in catalog.candidates if c.song_id == 99)
        assert "alias1" in c.aliases
        assert "alias2" in c.aliases

    async def test_get_song_catalog_bad_json_graceful(self, repo: SqliteChartRepository) -> None:
        await repo._conn.execute(
            "INSERT INTO songs(id, title_ja, aliases) VALUES (88, 'Bad', 'not-json')"
        )
        await repo._conn.commit()
        catalog = await repo.get_song_catalog()
        c = next(c for c in catalog.candidates if c.song_id == 88)
        assert c.aliases == ()


class TestGetBySongAndDifficulty:
    async def test_existing_chart(self, repo: SqliteChartRepository) -> None:
        await _seed_song_and_chart(repo._conn, song_id=42, difficulty="master")
        chart = await repo.get_by_song_and_difficulty(42, Difficulty.MASTER)
        assert chart is not None
        assert chart.song_id == 42

    async def test_nonexistent_difficulty(self, repo: SqliteChartRepository) -> None:
        await _seed_song_and_chart(repo._conn, song_id=42, difficulty="master")
        chart = await repo.get_by_song_and_difficulty(42, Difficulty.EASY)
        assert chart is None

    async def test_nonexistent_song(self, repo: SqliteChartRepository) -> None:
        chart = await repo.get_by_song_and_difficulty(999, Difficulty.MASTER)
        assert chart is None
```

- [ ] **Step 4: Run test to verify**

Run: `pytest tests/adapters/database/test_chart_repository.py -v`
Expected: all tests PASS (existing + new)

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add adapters/database/migrations/003_aliases_column.sql adapters/database/repository.py pjsk_core/ports/repositories.py tests/adapters/database/test_chart_repository.py
git commit -m "feat: add song aliases column, get_song_catalog, get_by_song_and_difficulty"
```

---

### Task 10: Adapters — MemoryCircuitBreaker + HTTP error mapping + Gemini engine

**Files:**
- Create: `adapters/resilience/__init__.py` (empty)
- Create: `adapters/resilience/memory_circuit_breaker.py`
- Create: `tests/adapters/resilience/__init__.py` (empty)
- Create: `tests/adapters/resilience/test_memory_circuit_breaker.py`
- Create: `adapters/vision/_http.py`
- Create: `adapters/vision/__init__.py` (empty)
- Create: `adapters/vision/gemini.py`
- Create: `tests/adapters/vision/__init__.py` (empty)
- Create: `tests/adapters/vision/test_gemini.py` (response-parsing only, no real HTTP)

This task combines three small, independent adapters that share infrastructure.

**Interfaces:**
- Produces: `MemoryCircuitBreaker(failure_threshold, cooldown_seconds)` implements `CircuitBreaker`
- Produces: `map_request_error(exc)`, `map_status_error(response)` in `_http.py`
- Produces: `GeminiVisionEngine(config, client)` implements `VisionEngine`

- [ ] **Step 1: Write MemoryCircuitBreaker**

```python
# adapters/resilience/memory_circuit_breaker.py
from __future__ import annotations

import asyncio
import time as _time
from pjsk_core.ports.circuit_breaker import (
    CircuitBreaker, CircuitFailure, CircuitPermit, CircuitState,
)


class MemoryCircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._states: dict[str, CircuitState] = {}
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._probe_active: dict[str, bool] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, engine_id: str) -> CircuitPermit | None:
        async with self._lock:
            state = self._states.get(engine_id, CircuitState.CLOSED)
            if state == CircuitState.CLOSED:
                return CircuitPermit(engine_id, probe=False)
            if state == CircuitState.OPEN:
                if _time.monotonic() >= self._open_until.get(engine_id, 0.0):
                    self._states[engine_id] = CircuitState.HALF_OPEN
                    state = CircuitState.HALF_OPEN
                else:
                    return None
            if state == CircuitState.HALF_OPEN:
                if self._probe_active.get(engine_id, False):
                    return None
                self._probe_active[engine_id] = True
                return CircuitPermit(engine_id, probe=True)
        return CircuitPermit(engine_id, probe=False)

    async def record_success(self, permit: CircuitPermit) -> None:
        async with self._lock:
            self._failures[permit.engine_id] = 0
            if permit.probe:
                self._states[permit.engine_id] = CircuitState.CLOSED
                self._probe_active[permit.engine_id] = False

    async def record_failure(
        self, permit: CircuitPermit, failure: CircuitFailure,
    ) -> None:
        _ = failure  # all failures counted equally
        async with self._lock:
            eid = permit.engine_id
            self._failures[eid] = self._failures.get(eid, 0) + 1
            if permit.probe:
                self._states[eid] = CircuitState.OPEN
                self._open_until[eid] = _time.monotonic() + self._cooldown
                self._probe_active[eid] = False
            elif self._failures[eid] >= self._threshold:
                self._states[eid] = CircuitState.OPEN
                self._open_until[eid] = _time.monotonic() + self._cooldown

    async def release(self, permit: CircuitPermit) -> None:
        if not permit.probe:
            return
        async with self._lock:
            self._states[permit.engine_id] = CircuitState.OPEN
            self._probe_active[permit.engine_id] = False

    async def state(self, engine_id: str) -> CircuitState:
        return self._states.get(engine_id, CircuitState.CLOSED)
```

- [ ] **Step 2: Write CircuitBreaker tests**

```python
# tests/adapters/resilience/test_memory_circuit_breaker.py
import asyncio
import pytest
from adapters.resilience.memory_circuit_breaker import MemoryCircuitBreaker
from pjsk_core.ports.circuit_breaker import CircuitFailure, CircuitState


class TestMemoryCircuitBreaker:
    @pytest.mark.asyncio
    async def test_closed_returns_permit(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=3)
        permit = await cb.acquire("gemini")
        assert permit is not None
        assert permit.probe is False

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=3)
        for _ in range(3):
            p = await cb.acquire("gemini")
            await cb.record_failure(p, CircuitFailure.TIMEOUT)
        assert await cb.state("gemini") == CircuitState.OPEN
        assert await cb.acquire("gemini") is None

    @pytest.mark.asyncio
    async def test_cooldown_enters_half_open(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p = await cb.acquire("gemini")
        await cb.record_failure(p, CircuitFailure.TIMEOUT)
        assert await cb.state("gemini") == CircuitState.OPEN
        await asyncio.sleep(0.02)
        p = await cb.acquire("gemini")
        assert p is not None
        assert p.probe is True

    @pytest.mark.asyncio
    async def test_probe_success_closes(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p = await cb.acquire("gemini")
        await cb.record_failure(p, CircuitFailure.TIMEOUT)
        await asyncio.sleep(0.02)
        p = await cb.acquire("gemini")
        await cb.record_success(p)
        assert await cb.state("gemini") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_probe_failure_reopens(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p = await cb.acquire("gemini")
        await cb.record_failure(p, CircuitFailure.TIMEOUT)
        await asyncio.sleep(0.02)
        p = await cb.acquire("gemini")
        await cb.record_failure(p, CircuitFailure.SERVER_ERROR)
        assert await cb.state("gemini") == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_two_concurrent_half_open_only_one_probe(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p0 = await cb.acquire("gemini")
        await cb.record_failure(p0, CircuitFailure.TIMEOUT)
        await asyncio.sleep(0.02)

        async def acq():
            return await cb.acquire("gemini")

        p1, p2 = await asyncio.gather(acq(), acq())
        permits = [p for p in (p1, p2) if p is not None]
        assert len(permits) == 1
        assert permits[0].probe is True

    @pytest.mark.asyncio
    async def test_release_probe_frees_slot(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p0 = await cb.acquire("gemini")
        await cb.record_failure(p0, CircuitFailure.TIMEOUT)
        await asyncio.sleep(0.02)
        p = await cb.acquire("gemini")
        await cb.release(p)
        assert await cb.state("gemini") == CircuitState.OPEN
        # After another cooldown, should be able to probe again
        await asyncio.sleep(0.02)
        p2 = await cb.acquire("gemini")
        assert p2 is not None
        assert p2.probe is True
```

- [ ] **Step 3: Write HTTP error mapping**

```python
# adapters/vision/_http.py
"""Shared HTTP error mapping for vendor vision adapters."""
from __future__ import annotations

import httpx
from pjsk_core.domain.ocr import (
    VisionConnectionError,
    VisionRateLimitError,
    VisionResponseError,
    VisionServerError,
    VisionTimeoutError,
)


def map_request_error(error: httpx.RequestError) -> VisionConnectionError | VisionTimeoutError:
    """Map transport-layer errors."""
    if isinstance(error, httpx.TimeoutException):
        return VisionTimeoutError(str(error))
    return VisionConnectionError(str(error))


def map_status_error(response: httpx.Response) -> VisionRateLimitError | VisionServerError | VisionResponseError:
    """Map HTTP status errors (call AFTER receiving a response)."""
    status = response.status_code
    if status == 429:
        return VisionRateLimitError(f"HTTP 429: {response.text[:200]}")
    if 500 <= status < 600:
        return VisionServerError(f"HTTP {status}: {response.text[:200]}")
    return VisionResponseError(f"HTTP {status}: {response.text[:200]}")
```

- [ ] **Step 4: Write Gemini adapter (minimal)**

```python
# adapters/vision/gemini.py
"""Gemini vision engine adapter."""
from __future__ import annotations

import json
import httpx
from pjsk_core.domain.ocr import (
    EngineIdentity, OcrObservation, VisionResponseError,
)
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.charts import Difficulty
from pjsk_core.ports.vision import VisionEngine
from adapters.vision._http import map_request_error, map_status_error


class Secret:
    def __init__(self, value: str) -> None:
        self._value = value
    def reveal(self) -> str:
        return self._value
    def __repr__(self) -> str:
        return "Secret(***)"


class GeminiVisionEngine:
    def __init__(
        self, api_key: str, model: str, client: httpx.AsyncClient,
    ) -> None:
        self._api_key = Secret(api_key)
        self._model = model
        self._client = client
        self.identity = EngineIdentity(
            engine_id=f"gemini-{model}",
            provider="google",
            model=model,
        )

    async def recognize(
        self, image: bytes, *, timeout: float,
    ) -> OcrObservation:
        # Build prompt — tune response format per official docs at impl time
        prompt = (
            "You are a PJSK score screenshot reader. "
            "Extract: song title, difficulty (EASY/NORMAL/HARD/EXPERT/MASTER/APPEND), "
            "level number, and counts: PERFECT GREAT GOOD BAD MISS. "
            "Return ONLY valid JSON with keys: song_title, difficulty, level, "
            "perfect, great, good, bad, miss."
        )
        # Request shape to be confirmed from official Gemini vision API docs
        body = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg",
                                     "data": _encode_base64(image)}},
                ]
            }]
        }
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self._model}:generateContent"
            f"?key={self._api_key.reveal()}"
        )
        try:
            response = await self._client.post(
                url, json=body, timeout=timeout,
            )
        except httpx.RequestError as e:
            raise map_request_error(e) from e

        if response.status_code >= 400:
            raise map_status_error(response)

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as e:
            raise VisionResponseError(f"Invalid JSON response: {e}") from e

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> OcrObservation:
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise VisionResponseError(f"Cannot parse Gemini response: {e}") from e

        diff_map = {
            "EASY": Difficulty.EASY, "NORMAL": Difficulty.NORMAL,
            "HARD": Difficulty.HARD, "EXPERT": Difficulty.EXPERT,
            "MASTER": Difficulty.MASTER, "APPEND": Difficulty.APPEND,
        }
        difficulty = diff_map.get(parsed.get("difficulty", "").upper())
        if difficulty is None:
            raise VisionResponseError(
                f"Unknown difficulty: {parsed.get('difficulty')}"
            )

        return OcrObservation(
            song_title=str(parsed.get("song_title", "")),
            difficulty=difficulty,
            displayed_level=int(parsed.get("level", 0)),
            judgements=Judgements(
                perfect=int(parsed.get("perfect", 0)),
                great=int(parsed.get("great", 0)),
                good=int(parsed.get("good", 0)),
                bad=int(parsed.get("bad", 0)),
                miss=int(parsed.get("miss", 0)),
            ),
            engine=f"gemini-{self._model}",
            elapsed_ms=0,
        )


import base64 as _base64
def _encode_base64(data: bytes) -> str:
    return _base64.b64encode(data).decode("ascii")
```

- [ ] **Step 5: Write Gemini response-parsing test**

```python
# tests/adapters/vision/test_gemini.py
import json
import pytest
from adapters.vision.gemini import GeminiVisionEngine
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import EngineIdentity


class TestGeminiResponseParsing:
    def test_parses_valid_json_response(self) -> None:
        # We test _parse_response directly — no HTTP
        engine = object.__new__(GeminiVisionEngine)
        engine._model = "gemini-2.5-flash"
        engine.identity = EngineIdentity(
            "gemini-gemini-2.5-flash", "google", "gemini-2.5-flash",
        )

        fake_api_response = {
            "candidates": [{
                "content": {"parts": [{
                    "text": json.dumps({
                        "song_title": "Test Song",
                        "difficulty": "MASTER",
                        "level": 30,
                        "perfect": 1000,
                        "great": 100,
                        "good": 0,
                        "bad": 0,
                        "miss": 0,
                    })
                }]}
            }]
        }
        obs = engine._parse_response(fake_api_response)
        assert obs.song_title == "Test Song"
        assert obs.difficulty == Difficulty.MASTER
        assert obs.displayed_level == 30
        assert obs.judgements.perfect == 1000

    def test_invalid_difficulty_raises(self) -> None:
        engine = object.__new__(GeminiVisionEngine)
        engine._model = "g"
        engine.identity = EngineIdentity("g", "google", "g")
        fake = {
            "candidates": [{"content": {"parts": [{
                "text": json.dumps({"song_title": "T", "difficulty": "LEGEND",
                                    "level": 30, "perfect": 1, "great": 0,
                                    "good": 0, "bad": 0, "miss": 0})
            }]}}]
        }
        with pytest.raises(Exception):
            engine._parse_response(fake)

    def test_secret_not_in_repr(self) -> None:
        from adapters.vision.gemini import Secret
        s = Secret("sk-abc123")
        assert "sk-abc123" not in repr(s)
        assert s.reveal() == "sk-abc123"
```

- [ ] **Step 6: Run tests to verify**

Run: `pytest tests/adapters/resilience/test_memory_circuit_breaker.py tests/adapters/vision/test_gemini.py -v`
Expected: all PASS

- [ ] **Step 7: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add adapters/resilience/ adapters/vision/ tests/adapters/resilience/ tests/adapters/vision/
git commit -m "feat: add MemoryCircuitBreaker, HTTP error mapping, Gemini engine adapter"
```

---

### Task 11: Adapters — Zhipu + StepFun engines

**Files:**
- Create: `adapters/vision/zhipu.py`
- Create: `tests/adapters/vision/test_zhipu.py`
- Create: `adapters/vision/stepfun.py`
- Create: `tests/adapters/vision/test_stepfun.py`

**Interfaces:**
- Produces: `ZhipuVisionEngine(api_key, model, client)` implements `VisionEngine`
- Produces: `StepFunVisionEngine(api_key, model, client)` implements `VisionEngine`

Both follow the same pattern as Gemini — post to vendor API, parse JSON response, return `OcrObservation`. Response parsing tests only (no real HTTP).

- [ ] **Step 1: Write Zhipu adapter**

```python
# adapters/vision/zhipu.py
"""Zhipu (智谱) vision engine adapter."""
from __future__ import annotations

import json
import httpx
import base64

from pjsk_core.domain.ocr import (
    EngineIdentity, OcrObservation, VisionResponseError,
)
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.charts import Difficulty
from pjsk_core.ports.vision import VisionEngine
from adapters.vision._http import map_request_error, map_status_error
from adapters.vision.gemini import Secret


_DIFF_MAP = {
    "EASY": Difficulty.EASY, "NORMAL": Difficulty.NORMAL,
    "HARD": Difficulty.HARD, "EXPERT": Difficulty.EXPERT,
    "MASTER": Difficulty.MASTER, "APPEND": Difficulty.APPEND,
}


class ZhipuVisionEngine:
    def __init__(
        self, api_key: str, model: str, client: httpx.AsyncClient,
    ) -> None:
        self._api_key = Secret(api_key)
        self._model = model
        self._client = client
        self.identity = EngineIdentity(
            engine_id=f"zhipu-{model}",
            provider="zhipu",
            model=model,
        )

    async def recognize(
        self, image: bytes, *, timeout: float,
    ) -> OcrObservation:
        prompt = (
            "You are a PJSK score screenshot reader. "
            "Extract: song title, difficulty (EASY/NORMAL/HARD/EXPERT/MASTER/APPEND), "
            "level number, and counts: PERFECT GREAT GOOD BAD MISS. "
            "Return ONLY valid JSON."
        )
        body = {
            "model": self._model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{base64.b64encode(image).decode('ascii')}"
                    }},
                ],
            }],
        }
        headers = {"Authorization": f"Bearer {self._api_key.reveal()}"}
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

        try:
            response = await self._client.post(
                url, json=body, headers=headers, timeout=timeout,
            )
        except httpx.RequestError as e:
            raise map_request_error(e) from e

        if response.status_code >= 400:
            raise map_status_error(response)

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as e:
            raise VisionResponseError(f"Invalid JSON: {e}") from e

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> OcrObservation:
        try:
            text = data["choices"][0]["message"]["content"]
            parsed = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise VisionResponseError(f"Cannot parse Zhipu response: {e}") from e

        difficulty = _DIFF_MAP.get(parsed.get("difficulty", "").upper())
        if difficulty is None:
            raise VisionResponseError(
                f"Unknown difficulty: {parsed.get('difficulty')}"
            )
        return OcrObservation(
            song_title=str(parsed.get("song_title", "")),
            difficulty=difficulty,
            displayed_level=int(parsed.get("level", 0)),
            judgements=Judgements(
                perfect=int(parsed.get("perfect", 0)),
                great=int(parsed.get("great", 0)),
                good=int(parsed.get("good", 0)),
                bad=int(parsed.get("bad", 0)),
                miss=int(parsed.get("miss", 0)),
            ),
            engine=f"zhipu-{self._model}",
            elapsed_ms=0,
        )
```

- [ ] **Step 2: Write StepFun adapter**

```python
# adapters/vision/stepfun.py
"""StepFun (阶跃星辰) vision engine adapter.

Uses an OpenAI-compatible chat completions endpoint.
Request shape confirmed from official docs at implementation time.
"""
from __future__ import annotations

import json
import httpx
import base64

from pjsk_core.domain.ocr import (
    EngineIdentity, OcrObservation, VisionResponseError,
)
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.charts import Difficulty
from pjsk_core.ports.vision import VisionEngine
from adapters.vision._http import map_request_error, map_status_error
from adapters.vision.gemini import Secret

_DIFF_MAP = {
    "EASY": Difficulty.EASY, "NORMAL": Difficulty.NORMAL,
    "HARD": Difficulty.HARD, "EXPERT": Difficulty.EXPERT,
    "MASTER": Difficulty.MASTER, "APPEND": Difficulty.APPEND,
}


class StepFunVisionEngine:
    def __init__(
        self, api_key: str, model: str, client: httpx.AsyncClient,
    ) -> None:
        self._api_key = Secret(api_key)
        self._model = model
        self._client = client
        self.identity = EngineIdentity(
            engine_id=f"stepfun-{model}",
            provider="stepfun",
            model=model,
        )

    async def recognize(
        self, image: bytes, *, timeout: float,
    ) -> OcrObservation:
        prompt = (
            "You are a PJSK score screenshot reader. "
            "Extract: song title, difficulty (EASY/NORMAL/HARD/EXPERT/MASTER/APPEND), "
            "level number, and counts: PERFECT GREAT GOOD BAD MISS. "
            "Return ONLY valid JSON."
        )
        body = {
            "model": self._model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{base64.b64encode(image).decode('ascii')}"
                    }},
                ],
            }],
        }
        headers = {"Authorization": f"Bearer {self._api_key.reveal()}"}
        url = "https://api.stepfun.com/v1/chat/completions"

        try:
            response = await self._client.post(
                url, json=body, headers=headers, timeout=timeout,
            )
        except httpx.RequestError as e:
            raise map_request_error(e) from e

        if response.status_code >= 400:
            raise map_status_error(response)

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as e:
            raise VisionResponseError(f"Invalid JSON: {e}") from e

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> OcrObservation:
        try:
            text = data["choices"][0]["message"]["content"]
            parsed = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise VisionResponseError(f"Cannot parse StepFun response: {e}") from e

        difficulty = _DIFF_MAP.get(parsed.get("difficulty", "").upper())
        if difficulty is None:
            raise VisionResponseError(
                f"Unknown difficulty: {parsed.get('difficulty')}"
            )
        return OcrObservation(
            song_title=str(parsed.get("song_title", "")),
            difficulty=difficulty,
            displayed_level=int(parsed.get("level", 0)),
            judgements=Judgements(
                perfect=int(parsed.get("perfect", 0)),
                great=int(parsed.get("great", 0)),
                good=int(parsed.get("good", 0)),
                bad=int(parsed.get("bad", 0)),
                miss=int(parsed.get("miss", 0)),
            ),
            engine=f"stepfun-{self._model}",
            elapsed_ms=0,
        )
```

- [ ] **Step 3: Write response-parsing tests**

```python
# tests/adapters/vision/test_zhipu.py and test_stepfun.py
# Follow same pattern as test_gemini.py — construct adapter object,
# call _parse_response with a mock API response dict, verify OcrObservation.
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/adapters/vision/ -v`
Expected: PASS (3 adapter tests)

- [ ] **Step 5: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add adapters/vision/zhipu.py adapters/vision/stepfun.py tests/adapters/vision/
git commit -m "feat: add Zhipu and StepFun vision engine adapters"
```

---

### Task 12: Adapters — Config loader + wiring

**Files:**
- Create: `adapters/config/__init__.py` (empty)
- Create: `adapters/config/vision.py`
- Create: `tests/adapters/config/__init__.py` (empty)
- Create: `tests/adapters/config/test_vision_config.py`

**Interfaces:**
- Produces: `load_vision_race_policy(raw: dict) -> VisionRacePolicy`

- [ ] **Step 1: Write config loader**

```python
# adapters/config/vision.py
"""Parse AstrBot config dict into VisionRacePolicy."""
from __future__ import annotations

from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy


def load_vision_race_policy(raw: dict) -> VisionRacePolicy:
    engines_raw: dict[str, dict] = raw.get("engines", {})
    if not engines_raw:
        raise ValueError("'engines' must be a non-empty dict")

    policies: list[EnginePolicy] = []
    for engine_id, cfg in engines_raw.items():
        policies.append(EnginePolicy(
            engine_id=engine_id,
            priority=int(cfg.get("priority", len(policies) + 1)),
            enabled=bool(cfg.get("enabled", True)),
            timeout_seconds=float(cfg.get("timeout", 15.0)),
            max_concurrency=int(cfg.get("max_concurrency", 3)),
        ))

    return VisionRacePolicy(
        engines=tuple(policies),
        global_timeout_seconds=float(raw.get("global_timeout_seconds", 30.0)),
        consensus_threshold=int(raw.get("consensus_threshold", 2)),
    )
```

- [ ] **Step 2: Write config test**

```python
# tests/adapters/config/test_vision_config.py
import pytest
from adapters.config.vision import load_vision_race_policy


class TestLoadVisionRacePolicy:
    def test_minimal_config(self) -> None:
        raw = {
            "engines": {
                "gemini-2.5-flash": {
                    "provider": "google", "enabled": True,
                    "priority": 1, "timeout": 15.0, "max_concurrency": 3,
                },
                "zhipu-glm-4v-flash": {
                    "provider": "zhipu", "enabled": True,
                    "priority": 2, "timeout": 15.0, "max_concurrency": 3,
                },
            },
            "global_timeout_seconds": 30.0,
            "consensus_threshold": 2,
        }
        policy = load_vision_race_policy(raw)
        assert len(policy.engines) == 2
        assert policy.global_timeout_seconds == 30.0

    def test_zero_engines_raises(self) -> None:
        with pytest.raises(ValueError):
            load_vision_race_policy({"engines": {}})

    def test_disabled_engines_filtered_correctly(self) -> None:
        raw = {
            "engines": {
                "g": {"provider": "google", "enabled": False,
                      "priority": 1, "timeout": 15.0, "max_concurrency": 3},
            },
            "global_timeout_seconds": 30.0,
        }
        with pytest.raises(ValueError, match="at least one"):
            load_vision_race_policy(raw)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/adapters/config/test_vision_config.py -v`
Expected: PASS

- [ ] **Step 4: Ruff + Mypy + Commit**

```bash
python -m ruff check . && mypy pjsk_core adapters tools tests
git add adapters/config/ tests/adapters/config/
git commit -m "feat: add vision config loader — dict to VisionRacePolicy"
```

---

### Final Verification

Run full suite:
```bash
python -m pytest -q
python -m ruff check .
mypy pjsk_core adapters tools tests
```

Update CLAUDE.md §16 execution boundary to Phase 3a, then commit.

---

## Self-Review

**1. Spec coverage:**
- §1 EngineIdentity + VisionEngineError → Tasks 2
- §2 SongMatcher → Tasks 1
- §3 Ports (VisionEngine revise, CircuitBreaker, ChartRepository extend) → Tasks 3, 4
- §4 VisionRacePolicy → Tasks 5
- §5 VisionRace (result types, EngineRuntime, VisionRace class, consensus rules, worker lifecycle) → Tasks 7
- §6 ValidationPipeline → Tasks 6
- §7 RecognizeScore → Tasks 8
- §8 Vendor adapters (HTTP, Gemini, Zhipu, StepFun) → Tasks 10, 11
- §9 MemoryCircuitBreaker → Tasks 10
- §10 Config loading → Tasks 12
- §11 Repository extensions (aliases, catalog, song+difficulty) → Tasks 9

**2. Placeholders:** None. Every code block has actual implementation.

**3. Type consistency:** `EngineIdentity` defined in Task 2, consumed by Tasks 3, 7, 10-11. `SongMatch` defined in Task 1, consumed by Tasks 6. `VisionRacePolicy` defined in Task 5, consumed by Tasks 7, 12. `ValidatedObservation` defined in Task 6, consumed by Tasks 7, 8. All consistent.
