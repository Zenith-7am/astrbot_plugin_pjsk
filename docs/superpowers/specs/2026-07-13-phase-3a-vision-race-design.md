# Phase 3a: Vision Model Adapters and Race Consensus — Design Spec

Date: 2026-07-13

## Goal

Implement the core OCR pipeline: multi-model vision recognition (Gemini, Zhipu, StepFun),
concurrent racing with early consensus detection, circuit breaker, and local validation
(song matching, chart lookup, note/difficulty/level verification). Candidate storage and
OCR run persistence are deferred to Phase 3b.

## Architecture

```text
plugin / gateways
       ↓
   application                          ← RecognizeScore, VisionRace, ValidationPipeline
       ↓
 domain + ports                         ← SongMatcher, VisionEngine, CircuitBreaker, ChartRepository
       ↑
  adapters                              ← Gemini, Zhipu, StepFun, MemoryCircuitBreaker, SQLite repos
```

Dependency direction (enforced mechanically): domain imports nothing from application/ports/adapters.
Application depends only on domain + ports. Adapters implement ports.

## File Layout

| Layer | File | Responsibility |
|-------|------|----------------|
| domain | `pjsk_core/domain/ocr.py` (extend) | `EngineIdentity`, `VisionEngineError` hierarchy |
| domain | `pjsk_core/domain/song_matcher.py` | Four-step song matching, OCR corrections, scoring |
| ports | `pjsk_core/ports/vision.py` (revise) | `VisionEngine` with `EngineIdentity` |
| ports | `pjsk_core/ports/circuit_breaker.py` | `CircuitBreaker` Protocol, `CircuitFailure` enum |
| ports | `pjsk_core/ports/repositories.py` (extend) | `list_song_candidates()`, `get_by_song_and_difficulty()` |
| application | `pjsk_core/application/vision_policy.py` | `EnginePolicy`, `VisionRacePolicy` |
| application | `pjsk_core/application/vision_race.py` | `VisionRace`, `EngineRuntime`, result/outcome types |
| application | `pjsk_core/application/validate_ocr.py` | `ValidationPipeline`, `ValidatedObservation` |
| application | `pjsk_core/application/recognize_score.py` | `RecognizeScore` top-level use case |
| adapters | `adapters/vision/_http.py` | Shared httpx error mapping |
| adapters | `adapters/vision/gemini.py` | Gemini adapter |
| adapters | `adapters/vision/zhipu.py` | Zhipu adapter |
| adapters | `adapters/vision/stepfun.py` | StepFun adapter |
| adapters | `adapters/resilience/memory_circuit_breaker.py` | In-process circuit breaker |
| adapters | `adapters/config/vision.py` | YAML/dict → `VisionRacePolicy` parser |
| adapters | `adapters/database/repository.py` (extend) | New repository methods |

## 1. Domain: EngineIdentity and Error Hierarchy

### 1.1 EngineIdentity (extends `pjsk_core/domain/ocr.py`)

```python
@dataclass(frozen=True)
class EngineIdentity:
    engine_id: str    # globally unique, e.g. "gemini-2.5-flash"
    provider: str     # vendor, e.g. "google"
    model: str        # model name, e.g. "gemini-2.5-flash"
```

Consensus de-duplicates by `engine_id`. Two instances of the same model cannot count as two
independent sources. Provider-level dedup (future): change key from `engine_id` to `provider`.

### 1.2 Vision Engine Error Hierarchy (extends `pjsk_core/domain/ocr.py`)

```python
class VisionEngineError(Exception): ...
class VisionTimeoutError(VisionEngineError): ...
class VisionConnectionError(VisionEngineError): ...
class VisionRateLimitError(VisionEngineError): ...
class VisionServerError(VisionEngineError): ...
class VisionResponseError(VisionEngineError): ...
```

Vendor adapters map HTTP/SDK errors to these types. Application never catches
`httpx.TimeoutException` or vendor SDK exceptions directly.

### 1.3 Existing types (unchanged, used as-is)

- `OcrObservation` — raw model output
- `ValidatedObservation` — will be revised (see §4)
- `Candidate` — used in Phase 3b
- `observations_agree()` / `validated_observations_agree()` — may be superseded by
  consensus logic in VisionRace
- `rank_candidates()` — used in RecognizeScore when DISAGREEMENT

## 2. Domain: SongMatcher

### 2.1 Types

```python
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
    title_cn: str
    title_en: str
    aliases: tuple[str, ...] = ()

@dataclass(frozen=True)
class SongMatch:
    song_id: int
    score: float              # 0.0–1.0, clamped
    method: SongMatchMethod
    source: TitleSource
```

### 2.2 Normalization

Two-tier: safe normalization for both OCR raw and candidate titles, OCR-specific
character corrections only for raw input.

```python
OCR_CORRECTIONS = str.maketrans({"口": "ク", "一": "ー", "才": "オ"})

def _normalize_text(text: str) -> str:
    # NFKC, casefold, normalize whitespace, strip
    ...

def _normalize_ocr_text(text: str) -> str:
    # _normalize_text + translate(OCR_CORRECTIONS)
    ...
```

Candidate titles only go through `_normalize_text` — OCR corrections are NOT applied
to the song database, so a real "一" in a song title is never rewritten.

### 2.3 Public Entry Point

```python
def match_song(
    raw_title: str,
    candidates: Sequence[SongCandidate],
) -> tuple[SongMatch, ...]:
```

Four-step pipeline. Each step iterates all title sources (ja → cn → en → aliases).
The first non-empty step produces results; later steps are skipped.

**Step 1 — Exact match** (score = 1.0, method = EXACT):
- Try `_normalize_text(raw)` against all `_normalize_text(candidate_title)`
- Then try `_normalize_ocr_text(raw)` against all `_normalize_text(candidate_title)`
- Both passes eligible

**Step 2 — Region extraction** (score = 1.0, method = REGION):
- `_extract_title_regions(raw) → tuple[str, ...]` — difficulty keyword truncation,
  UI-noise filtering
- Exact match each region against candidate titles

**Step 3 — Fuzzy match** (method = FUZZY):
- Dice × 60% + Levenshtein similarity × 40% + position bonus
- Clamp to `min(1.0, raw_score)`
- Threshold: ≥ 0.50
- When a song has multiple titles, take the max score across them

**Step 4 — Prefix match** (method = PREFIX):
- Bidirectional: `candidate.startswith(raw)` OR `raw.startswith(candidate)`
- Shorter side must be ≥ 5 Unicode characters
- score = len(shorter) / len(longer)

**Within-step dedup**: remove empty titles, dedup by song_id, sort by:
score DESC → method priority → source priority → song_id ASC.

### 2.4 STRONG Match Threshold

| Method | Auto-STRONG eligible |
|--------|---------------------|
| EXACT | Yes |
| REGION | Yes |
| FUZZY score ≥ 0.82 | Yes |
| FUZZY score < 0.82 | No (max CANDIDATE) |
| PREFIX | No (max CANDIDATE) |

`STRONG_FUZZY_SCORE = 0.82` is a config constant; exact value to be tuned with
real screenshot datasets.

## 3. Ports: VisionEngine and CircuitBreaker

### 3.1 VisionEngine (revised)

```python
class VisionEngine(Protocol):
    identity: EngineIdentity

    async def recognize(
        self, image: bytes, *, timeout: float,
    ) -> OcrObservation: ...
```

Replaces the old `name: str` field. `identity` provides `engine_id`, `provider`, and `model`
for dedup and consensus counting.

### 3.2 CircuitBreaker

```python
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
    probe: bool          # True = HALF_OPEN探测请求

class CircuitBreaker(Protocol):
    async def acquire(self, engine_id: str) -> CircuitPermit | None: ...
    async def record_success(self, permit: CircuitPermit) -> None: ...
    async def record_failure(
        self, permit: CircuitPermit, failure: CircuitFailure,
    ) -> None: ...
    async def state(self, engine_id: str) -> CircuitState: ...
```

**Failure counting rules:**
- COUNTED: TIMEOUT, CONNECTION, RATE_LIMITED, SERVER_ERROR, INVALID_RESPONSE
- NOT COUNTED: image validation errors (too large, unsupported format), local validation
  failures, song not matched, note mismatch, caller cancellation, consensus-driven cancel

**Permit semantics (atomic):**
- CLOSED: `acquire()` always returns a permit (`probe=False`)
- OPEN: `acquire()` returns `None` (rejected)
- HALF_OPEN: `acquire()` atomically occupies the single probe slot inside a lock.
  Two concurrent `acquire()` calls → only one gets a `probe=True` permit.
- On `record_success(probe=True)` → transition to CLOSED, reset failure count.
- On `record_failure(probe=True)` → transition back to OPEN, extend cooldown.

**Thresholds** (configurable defaults):
- Consecutive failures to OPEN: `3`
- OPEN → HALF_OPEN cooldown: `30` seconds

### 3.3 ChartRepository (extended)

Add two methods to the existing `ChartRepository` Protocol:

```python
async def list_song_candidates(self) -> tuple[SongCandidate, ...]: ...
async def get_by_song_and_difficulty(
    self, song_id: int, difficulty: Difficulty,
) -> Chart | None: ...
```

## 4. Application: VisionRacePolicy

Location: `pjsk_core/application/vision_policy.py` (NOT in adapters — application depends
on it, and application must not depend on adapters).

```python
@dataclass(frozen=True)
class EnginePolicy:
    engine_id: str
    priority: int             # 1=highest; task creation order, degrade preference
    enabled: bool
    timeout_seconds: float
    max_concurrency: int      # in-process per-engine cap

@dataclass(frozen=True)
class VisionRacePolicy:
    engines: tuple[EnginePolicy, ...]
    global_timeout_seconds: float
    consensus_threshold: int = 2
```

**Validation** (`__post_init__`):
- `engine_id` non-empty, unique across engines
- `priority ≥ 1`, `timeout_seconds > 0`, `max_concurrency ≥ 1`
- `global_timeout_seconds > 0`
- At least one engine enabled
- `consensus_threshold ≥ 2`, must not exceed enabled engine count

**V1 determinism constraint**: at most 3 distinct providers enabled, consensus_threshold = 2.
With ≤3 providers and threshold 2, a 2-vote majority is unique — no race between two
different 2-vote groups.

**API keys are NOT in these dataclasses.** They are injected into vendor adapters at
construction time. Secrets use a `Secret` wrapper that suppresses repr/logging.

## 5. Application: VisionRace

### 5.1 Result Types

```python
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
    results: tuple[EngineResult, ...]               # sorted by engine_id
    circuit_rejects: tuple[EngineIdentity, ...]
```

### 5.2 EngineRuntime

```python
@dataclass
class EngineRuntime:
    engine: VisionEngine
    policy: EnginePolicy
    semaphore: asyncio.Semaphore  # long-lived, shared across races
```

### 5.3 VisionRace Class

```python
class ObservationValidator(Protocol):
    """Validates a raw observation — defined in application, not ports."""
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
    ) -> None: ...

    async def run(self, image: bytes) -> VisionRaceOutcome: ...
```

### 5.4 run() Flow

1. Filter: skip disabled engines and circuit-rejected engines
2. Start: create one `asyncio.Task` per engine, sorted by priority
3. Collect: use `asyncio.wait(FIRST_COMPLETED)` loop
4. Per arriving result:
   a. SUCCESS → validate the observation → check if consensus formed
   b. Consensus formed (≥2 providers agree on matched_chart_id + difficulty + judgements)
      → cancel all remaining tasks, `asyncio.gather(*pending, return_exceptions=True)`
      to drain them, mark them CANCELLED_BY_CONSENSUS (NOT counted as breaker failures)
   c. FAILED/TIMED_OUT → record to breaker
5. All done, no consensus:
   a. Single SUCCESS with STRONG validation → DEGRADED_SINGLE
   b. Multiple SUCCESSES but no agreement → DISAGREEMENT
   c. All failed → ALL_FAILED
6. Global timeout: preserve completed results, cancel remaining, return GLOBAL_TIMEOUT.
   If a strong single result arrived before timeout, it is available for the caller to
   decide — VisionRace does not auto-adopt on global timeout.
7. Caller cancellation: cancel + drain all tasks, re-raise `CancelledError` (never swallow).

### 5.5 Consensus Rules

Two validated observations agree when:
1. Both `validation_status == STRONG`
2. `matched_chart_id` identical
3. `difficulty` identical
4. `judgements` (all 5 fields) identical
5. From different `provider` values

`displayed_level` is NOT a consensus condition — the local chart database has
official level; a misread level digit should not block an otherwise-strong
agreement.

### 5.6 Worker Lifecycle

```
async with runtime.semaphore:           # 1. Wait for concurrency slot
    permit = await breaker.acquire()    # 2. Get breaker permit
    if permit is None: → circuit reject

    started = monotonic()
    try:
        async with asyncio.timeout(policy.timeout_seconds):
            observation = await engine.recognize(image, timeout=...)
        # Success — breaker.record_success called by orchestrator after validation
    except asyncio.CancelledError:
        raise  # Let caller handle — do NOT record breaker failure
    except TimeoutError:
        await breaker.record_failure(permit, CircuitFailure.TIMEOUT)
    except VisionEngineError as e:
        await breaker.record_failure(permit, ...)
```

Semaphore before permit: prevents HALF_OPEN probe from being blocked waiting for a slot.

### 5.7 Results Ordering

`results` tuple is sorted by `engine_id` (stable for tests/logs/audit).
`selected` is NOT read from sorted position — it is chosen by:
1. Match to consensus group
2. Provider priority (from EnginePolicy)
3. Engine ID deterministic tie-break

## 6. Application: ValidationPipeline

### 6.1 Types

```python
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
```

### 6.2 ValidationPipeline

```python
class ValidationPipeline:
    def __init__(self, charts: ChartRepository) -> None: ...

    async def validate(
        self, observation: OcrObservation,
    ) -> ValidatedObservation: ...
```

### 6.3 Flow

1. Load `SongCandidate` list from `ChartRepository.list_song_candidates()`
2. `domain.match_song(raw_title, candidates)` → top N SongMatch (max 5)
3. For each match (in order):
   a. `ChartRepository.get_by_song_and_difficulty(song_id, difficulty)` → Chart | None
   b. If chart: validate note (±1 tolerance), validate displayed_level vs official_level
   c. Determine ValidationStatus per §6.4
4. Sort candidates: note_validated → chart exists → match score → note distance → song_id
5. `primary = candidates[0]`, keep all candidates

### 6.4 ValidationStatus Rules

**STRONG**: primary chart exists + difficulty matches + note ≤ ±1 + match meets strong
threshold (§2.4) + judgement total > 0 + displayed_level matches official_level

**CANDIDATE**: any song match exists but STRONG conditions not all met (weak match score,
missing difficulty, note out of range, level conflict, multiple indistinguishable
candidates)

**REJECTED**: no song match exceeds minimum threshold, title empty/whitespace-only,
judgement total = 0, or structurally invalid

### 6.5 Catalog Cache

ValidationPipeline holds an in-memory snapshot of `SongCandidate` list, keyed by
`chart_data_version`. On first call, load from repository. On subsequent calls,
re-load only if `chart_data_version` changed. No Redis needed.

## 7. Application: RecognizeScore

```python
@dataclass(frozen=True)
class RecognizeResult:
    outcome: VisionRaceOutcome
    validated: ValidatedObservation | None
    candidates_for_user: tuple[Candidate, ...]  # non-empty only on DISAGREEMENT

class RecognizeScore:
    def __init__(
        self,
        race: VisionRace,
        charts: ChartRepository,
        scores: ScoreRepository,
    ) -> None: ...

    async def recognize(
        self, user_id: UserId, image: bytes,
    ) -> RecognizeResult: ...
```

Flow:
```
1. sha256 = hashlib.sha256(image).hexdigest()
2. outcome = await race.run(image)
3. Dispatch on outcome.decision:
   CONSENSUS / DEGRADED_SINGLE:
     → ScoreRepository.record_attempt() (atomic INSERT + UPSERT personal_best)
     → Return success
   DISAGREEMENT:
     → Merge validated.candidates from all engine results
     → domain.rank_candidates()
     → Return candidates_for_user (deferred to Phase 3b CandidateStore)
   ALL_FAILED / NO_AVAILABLE_ENGINES:
     → Return error info for gateway to map to ErrorReply
   GLOBAL_TIMEOUT:
     → Keep completed results. If a single STRONG result exists, leave adoption
       decision to the caller (gateway). Return partial results.
```

## 8. Adapters: Vendor Vision Engines

### 8.1 Shared HTTP (`adapters/vision/_http.py`)

```python
def map_http_error(error: Exception) -> VisionEngineError:
    # httpx.TimeoutException → VisionTimeoutError
    # httpx.ConnectError → VisionConnectionError
    # HTTP 429 → VisionRateLimitError
    # HTTP 5xx → VisionServerError
    # HTTP 4xx (non-429) → VisionResponseError
```

Single `httpx.AsyncClient` injected into each adapter (shared connection pool).

### 8.2 Gemini, Zhipu, StepFun

Each adapter:
- Receives config (api_key, model) + `httpx.AsyncClient` at construction
- Exposes `identity: EngineIdentity` (engine_id = `{provider}-{model}`)
- `recognize(image, timeout)`:
  1. Build request (Gemini: multipart, Zhipu/StepFun: JSON with base64)
  2. POST with timeout passed to httpx
  3. Parse response → extract song title, difficulty, level, 5 judgements
  4. Map HTTP errors via `_http.map_http_error`
  5. Return `OcrObservation`

**Contracts (all adapters):**
- API key never appears in exception messages, logs, or repr
- No database access, no candidate storage, no consensus logic
- All external errors mapped to `VisionEngineError` subtypes
- Timeout passed to HTTP client (double-layer with `asyncio.timeout`)
- Image bytes never sent to secondary services

### 8.3 Prompt Strategy

Each adapter uses the same semantic prompt adapted to the vendor's API format.
Required fields: song title, difficulty, displayed level, PERFECT/GREAT/GOOD/BAD/MISS counts.
Not required: chart ID, note count, community constant.
Prompt template and response parsing live in each adapter file — vendors differ in output
format tendencies, making a shared template undesirable.

## 9. Adapters: CircuitBreaker Implementation

```python
# adapters/resilience/memory_circuit_breaker.py

class MemoryCircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None: ...

    # Implements CircuitBreaker Protocol
    # Uses asyncio.Lock for permit atomicity
    # State machine: CLOSED → OPEN → HALF_OPEN → CLOSED (or back to OPEN)
```

## 10. Adapters: Config Loading

```python
# adapters/config/vision.py

def load_vision_race_policy(raw: dict) -> VisionRacePolicy:
    """Parse dict (from AstrBot config or YAML) into VisionRacePolicy."""
```

Input shape:
```json
{
    "engines": {
        "gemini-2.5-flash": {
            "provider": "google", "enabled": true,
            "priority": 1, "timeout": 15.0, "max_concurrency": 3
        }
    },
    "global_timeout_seconds": 30.0,
    "consensus_threshold": 2
}
```

Validates and raises clear errors on: missing fields, invalid values, duplicate IDs,
unachievable consensus threshold, zero enabled engines.

API keys are NOT in this config — they are injected separately when constructing
vendor adapters.

## 11. Adapters: Repository Extensions

Add to `SqliteChartRepository`:

```python
async def list_song_candidates(self) -> tuple[SongCandidate, ...]:
    """Return all songs with titles and aliases for matching."""

async def get_by_song_and_difficulty(
    self, song_id: int, difficulty: Difficulty,
) -> Chart | None:
    """Find a specific chart by song + difficulty."""
```

The `songs` table needs an `aliases` column. Add via migration 003 if not present.

## 12. Test Plan

### 12.1 Domain Tests (`tests/domain/`)

| Test file | Coverage |
|-----------|----------|
| `test_song_matcher.py` | Exact match (ja/cn/en/alias), NFKC, casefold, OCR corrections on raw only, real title characters not corrupted on candidate side, normalization collision returns multiple candidates, region extraction, four-step first-non-empty, fuzzy threshold boundaries, position bonus not exceeding 1.0, bidirectional prefix, prefix < 5 chars rejected, same score sorted by song_id, empty title, empty candidates |

### 12.2 Application Tests (`tests/application/`)

| Test file | Coverage |
|-----------|----------|
| `test_vision_policy.py` | Validation rejects invalid values, unique engine_id enforcement, consensus_threshold vs enabled count, ≤3 provider rule |
| `test_vision_race.py` | Two engines agree → consensus; slow third cancelled and awaited; single success + others fail → degraded_single; two engines disagree → disagreement; one engine throws → others unaffected; consensus cancel NOT counted as breaker failure; circuit-rejected engines skipped; all fail → all_failed; global timeout → partial results; caller cancel → re-raised; completion order randomized → result deterministic; same provider ×2 models → not independent consensus; semaphore before permit ordering |
| `test_validate_ocr.py` | First match fail → second match succeed; EXACT + note + level → STRONG; weak fuzzy + note match → CANDIDATE; PREFIX → max CANDIDATE; song exists + difficulty missing → CANDIDATE; note ±1 pass / ±2 fail; level match / conflict; all candidates rejected → REJECTED; catalog loads once and invalidates on data version change; returns domain objects not dicts |
| `test_recognize_score.py` | Consensus → score recorded; degraded_single → score recorded; disagreement → candidates returned; all_failed → error info; transaction rollback on score write failure |

### 12.3 Adapter Tests (`tests/adapters/`)

| Test file | Coverage |
|-----------|----------|
| `tests/adapters/vision/test_gemini.py` | Response parsing (valid JSON → OcrObservation), error response mapping, timeout propagation, prompt construction |
| `tests/adapters/vision/test_zhipu.py` | Same as Gemini |
| `tests/adapters/vision/test_stepfun.py` | Same as Gemini |
| `tests/adapters/resilience/test_memory_circuit_breaker.py` | CLOSED→OPEN after N failures, OPEN rejects, cooldown → HALF_OPEN, probe success → CLOSED, probe failure → OPEN, two concurrent acquire in HALF_OPEN only one gets permit, success/failure recording with permits, state() is async-safe |

### 12.4 Integration Notes

- Vision race tests use mock `VisionEngine` that returns pre-configured responses
  and can simulate delays/timeouts/errors — no real API calls
- Vendor adapter tests use recorded HTTP responses (or mock httpx transport)
- Circuit breaker tests are real unit tests — no mocks needed

## 13. Non-Goals (Deferred to Phase 3b or Later)

- Redis-backed CandidateStore (Phase 3b)
- OCR runs / observations table persistence (Phase 3b)
- Candidate user confirmation flow end-to-end (Phase 3b)
- AstrBot handler wiring (`/pjsk score` command) — later phase
- Staggered race start (start_delay_seconds)
- Provider-internal multi-model aggregation (one provider = one model for now)
- Certificate pinning / TLS fingerprint verification
- Vendor SDK usage (use httpx directly for all three)
- Song alias migration from old DB (migration to be designed when alias data is available)

## 14. Design Decisions Summary

| Decision | Rationale |
|----------|-----------|
| ≤3 providers, threshold=2 | Deterministic consensus — 2-vote majority unique |
| Permit-based breaker | HALF_OPEN single-probe atomicity |
| OCR corrections on raw only | Prevents corrupting real song titles |
| Validate top 5 SongMatch | First match + note fail ≠ song is wrong |
| `displayed_level` not in consensus | Local DB is authoritative for level |
| `EnginePolicy` in application | Application must not import adapters |
| Config parsing in adapter | Application never touches YAML/env vars |
| Shared `httpx.AsyncClient` | Connection pooling, uniform timeout |
| In-memory catalog cache | No Redis dependency for matching |
