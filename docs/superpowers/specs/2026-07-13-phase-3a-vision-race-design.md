# Phase 3a: Vision Model Adapters and Race Consensus — Design Spec

Date: 2026-07-13 · Revised 2026-07-13 (spec review)

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
| ports | `pjsk_core/ports/repositories.py` (extend) | `get_song_catalog()`, `get_by_song_and_difficulty()` |
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
    engine_id: str    # globally unique instance id, e.g. "gemini-2.5-flash"
    provider: str     # vendor, e.g. "google"
    model: str        # model name, e.g. "gemini-2.5-flash"
```

**Dedup rules:**
- `engine_id` is used for instance identity, configuration, logging, and result ordering.
- **Provider** is the consensus voting unit — two engines from the same provider cannot
  form an independent two-vote consensus.
- V1: at most one enabled engine per provider.  Provider-internal multi-model aggregation
  is deferred.

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
- `Candidate` — used in Phase 3b
- `observations_agree()` / `validated_observations_agree()` — superseded by
  consensus logic in VisionRace; may be removed or kept for tests
- `rank_candidates()` — used in RecognizeScore when DISAGREEMENT

## 2. Domain: SongMatcher

### 2.1 Algorithm Compatibility Baseline

Song matching reproduces the behaviour of `D:\emu-bot\src\features\song_match.py`.
First copy the old fixtures, then extract the matching pipeline into structured pure
functions. Any intentional deviation from old scores is documented in the test file.

### 2.2 Types

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

### 2.3 Normalization

Two-tier: safe normalization for both OCR raw and candidate titles, OCR-specific
character corrections only for raw input.

```python
OCR_CORRECTIONS = str.maketrans({"口": "ク", "一": "ー", "才": "オ"})

def _normalize_text(text: str) -> str:
    """NFKC, casefold, collapse whitespace, strip.  Applied to both
    OCR raw and candidate titles."""
    ...

def _normalize_ocr_text(text: str) -> str:
    """_normalize_text + translate(OCR_CORRECTIONS).  Applied to OCR
    raw only — never to candidate titles."""
    ...
```

Candidate titles only go through `_normalize_text` — OCR corrections are NOT applied
to the song database, so a real "一" in a song title is never rewritten.

### 2.4 Public Entry Point

```python
def match_song(
    raw_title: str,
    candidates: Sequence[SongCandidate],
) -> tuple[SongMatch, ...]:
```

Four-step pipeline. Each step iterates all title sources (ja → cn → en → aliases).
The first non-empty step produces results; later steps are skipped.

**Step 1 — Exact match** (score = 1.0, method = EXACT):
- Try `_normalize_text(raw)` against `_normalize_text(candidate_title)` for every source
- Then try `_normalize_ocr_text(raw)` against `_normalize_text(candidate_title)` for every source
- Both passes eligible; dedup by song_id after the step

**Step 2 — Region extraction** (score = 1.0, method = REGION):
- `_extract_title_regions(raw) → tuple[str, ...]` — difficulty keyword truncation,
  UI-noise filtering
- Difficulty keywords: `MASTER`, `EXPERT`, `APPEND`, `HARD`, `NORMAL`, `EASY` and
  their JP localisations
- UI noise: `PERFECT`, `GREAT`, `GOOD`, `BAD`, `MISS`, `COMBO`, `CLEAR`, `FULL`,
  `ALL`, plus score digits and separator characters from result-screen UI
- Each region is exact-matched against candidate titles

**Step 3 — Fuzzy match** (method = FUZZY):
- Dice coefficient on character bigrams × 0.6 + normalised Levenshtein similarity × 0.4
- Levenshtein similarity = `1 − (edit_distance / max(len(a), len(b)))`
- Position bonus: +0.08 when raw appears as substring of candidate or vice versa
- Clamp to `min(1.0, raw_score)`
- Threshold: ≥ 0.50
- When a song has multiple titles, take the max score across them
- Empty-string input → score 0.0 for all candidates

**Step 4 — Prefix match** (method = PREFIX):
- Bidirectional: `normalized_candidate.startswith(normalized_raw)` OR
  `normalized_raw.startswith(normalized_candidate)`
- Shorter side must be ≥ 5 Unicode characters (after normalization)
- score = len(shorter_normalized) / len(longer_normalized)

**Within-step dedup**: remove entries with empty/whitespace-only titles, dedup by
song_id (keep highest score per song, then best method, then best source per the
ordering below), sort by: score DESC → method priority (EXACT > REGION > FUZZY >
PREFIX) → source priority (JA > CN > EN > ALIAS) → song_id ASC.

### 2.5 STRONG Match Threshold

| Method | Auto-STRONG eligible |
|--------|---------------------|
| EXACT | Yes |
| REGION | Yes |
| FUZZY score ≥ 0.82 | Yes |
| FUZZY score < 0.82 | No (max CANDIDATE) |
| PREFIX | No (max CANDIDATE) |

`STRONG_FUZZY_SCORE = 0.82` is a config constant; exact value to be tuned with
real screenshot datasets against old emu-bot matcher behaviour.

## 3. Ports: VisionEngine, CircuitBreaker, and ChartRepository

### 3.1 VisionEngine (revised)

```python
class VisionEngine(Protocol):
    identity: EngineIdentity

    async def recognize(
        self, image: bytes, *, timeout: float,
    ) -> OcrObservation: ...
```

Replaces the old `name: str` field. `identity` provides `engine_id`, `provider`, and `model`
for configuration, logging, and consensus counting.

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
    async def release(self, permit: CircuitPermit) -> None: ...
    async def state(self, engine_id: str) -> CircuitState: ...
```

**Settlement rule:** every successfully-acquired permit MUST be settled exactly once
across all exit paths — via `record_success`, `record_failure`, or `release`.

**Failure counting rules:**
- COUNTED: TIMEOUT, CONNECTION, RATE_LIMITED, SERVER_ERROR, INVALID_RESPONSE
- NOT COUNTED (use `release`): consensus-driven cancel, caller cancellation,
  shutdown, image validation errors (too large, unsupported format), local
  validation failures, song not matched, note mismatch

**Permit semantics (atomic):**
- CLOSED: `acquire()` always returns a permit (`probe=False`)
- OPEN: `acquire()` returns `None` (rejected)
- HALF_OPEN: `acquire()` atomically occupies the single probe slot inside a lock.
  Two concurrent `acquire()` calls → only one gets a `probe=True` permit.
- On `record_success(probe=True)` → transition to CLOSED, reset failure count.
- On `record_failure(probe=True)` → transition back to OPEN, extend cooldown.
- On `release(probe=True)` → probe slot freed, state back to OPEN, preserve original
  cooldown (no penalty and no success).
- On `release(probe=False)` → no-op (CLOSED permits don't need release tracking).

**Thresholds** (configurable defaults):
- Consecutive failures to OPEN: `3`
- OPEN → HALF_OPEN cooldown: `30` seconds

### 3.3 ChartRepository (extended)

```python
@dataclass(frozen=True)
class SongCatalog:
    version: str                          # chart_data_version
    candidates: tuple[SongCandidate, ...]

# In ChartRepository Protocol:
async def get_song_catalog(self) -> SongCatalog: ...
async def get_by_song_and_difficulty(
    self, song_id: int, difficulty: Difficulty,
) -> Chart | None: ...
```

Atomic snapshot: version and candidates are returned together, so ValidationPipeline
never sees a version/candidate mismatch. The old `list_song_candidates()` is
removed in favour of `get_song_catalog()`.

## 4. Application: VisionRacePolicy

Location: `pjsk_core/application/vision_policy.py` (NOT in adapters — application depends
on it, and application must not depend on adapters).

```python
@dataclass(frozen=True)
class EnginePolicy:
    engine_id: str
    provider: str
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
- `engine_id` non-empty, unique across all engines
- `provider` non-empty
- Among enabled engines: all `provider` values must be unique (V1: one model per provider)
- `priority ≥ 1`, `timeout_seconds > 0`, `max_concurrency ≥ 1`
- `global_timeout_seconds > 0`
- At least one engine enabled
- `consensus_threshold ≥ 2`, must not exceed enabled provider count
- V1 determinism: at most 3 distinct enabled providers, threshold fixed at 2.
  With ≤3 providers and threshold 2, a 2-vote majority is unique — no race between
  two different 2-vote groups.

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
    validated: ValidatedObservation | None    # set when SUCCESS + validation done
    error: VisionEngineError | None
    elapsed_ms: int

    # Invariants:
    #   SUCCESS → observation is not None
    #   SUCCESS + validated → validated is not None
    #   FAILED / TIMED_OUT / CANCELLED_* → observation is None, validated is None
    #   error is not None only for FAILED / TIMED_OUT

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
   a. SUCCESS → `breaker.record_success(permit)` immediately (breaker is about
      vendor health, not local validation). Then validate observation.
      Check if consensus formed.
   b. Consensus formed (≥2 *providers* agree on matched_chart_id + difficulty +
      judgements) → cancel all remaining tasks, `asyncio.gather(*pending,
      return_exceptions=True)` to drain them. For each cancelled task, call
      `breaker.release(permit)` — NOT `record_failure`. Mark results as
      CANCELLED_BY_CONSENSUS.
   c. FAILED/TIMED_OUT → `breaker.record_failure(permit, ...)`
5. All done, no consensus:
   a. Single SUCCESS with STRONG validation → DEGRADED_SINGLE
   b. Multiple SUCCESSES but no agreement → DISAGREEMENT
   c. All failed → ALL_FAILED
6. Global timeout: preserve completed results, cancel remaining, call
   `breaker.release()` for each cancelled permit. Return GLOBAL_TIMEOUT.
7. Caller cancellation: cancel + drain all tasks, `breaker.release()` for each
   pending permit, re-raise `CancelledError` (never swallow).

### 5.5 Consensus Rules

Two validated observations agree when:
1. Both `validation_status == STRONG`
2. `matched_chart_id` identical
3. `difficulty` identical
4. `judgements` (all 5 fields) identical
5. From different `provider` values

`displayed_level` is NOT a consensus condition in its own right. However,
`validation_status == STRONG` already requires `displayed_level == official_level`
(see §6.4), so a level mismatch prevents the observation from ever reaching STRONG
and thus from ever entering consensus. The practical effect is: level-conflict
observations are CANDIDATE and cannot form auto-consensus.

### 5.6 Worker Lifecycle

```
async with runtime.semaphore:           # 1. Wait for concurrency slot
    permit = await breaker.acquire()    # 2. Get breaker permit
    if permit is None: → circuit reject

    started = monotonic()
    try:
        async with asyncio.timeout(policy.timeout_seconds):
            observation = await engine.recognize(image, timeout=...)
        # 3. HTTP + parse succeeded → breaker success NOW (before validation)
        await breaker.record_success(permit)
    except asyncio.CancelledError:
        await breaker.release(permit)   # 4a. Consensus/caller cancel → release
        raise
    except TimeoutError:
        await breaker.record_failure(permit, CircuitFailure.TIMEOUT)
    except VisionEngineError as e:
        await breaker.record_failure(permit, ...)
```

Breaker success is recorded immediately after the vendor returns a well-formed
response — local validation (song matching, note check, level check) happens
afterward and does not affect breaker state.  A HALF_OPEN probe that returns
a valid observation but whose local validation fails is still a vendor success.

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

1. Load `SongCatalog` via `ChartRepository.get_song_catalog()`
2. `domain.match_song(raw_title, catalog.candidates)` → top N SongMatch (max 5)
3. For each match (in order):
   a. `ChartRepository.get_by_song_and_difficulty(song_id, difficulty)` → Chart | None
   b. If chart: validate note (±1 tolerance), validate displayed_level vs official_level
   c. Determine ValidationStatus per §6.4
4. Sort candidates: note_validated → chart exists → match score → note distance → song_id
5. `primary = candidates[0]`, keep all candidates

### 6.4 ValidationStatus Rules

**STRONG**: primary chart exists + difficulty matches + note ≤ ±1 + match meets strong
threshold (§2.5) + judgement total > 0 + displayed_level matches official_level

**CANDIDATE**: any song match exists but STRONG conditions not all met (weak match score,
missing difficulty, note out of range, displayed_level conflict, multiple
indistinguishable candidates)

**REJECTED**: no song match exceeds minimum threshold, title empty/whitespace-only,
judgement total = 0, or structurally invalid

Note: `displayed_level` mismatch → CANDIDATE.  Since STRONG is required for consensus,
a level-misread observation cannot be auto-adopted.  This is conservative by design — a
screenshot whose displayed level doesn't match local data is flagged for human review.

### 6.5 Catalog Cache

ValidationPipeline holds an in-memory `SongCatalog` snapshot. On first call, load
via `get_song_catalog()`. On subsequent calls, re-load only if `catalog.version`
differs from the last seen version. No Redis needed.

## 7. Application: RecognizeScore

### 7.1 Types

```python
@dataclass(frozen=True)
class RecognizeResult:
    outcome: VisionRaceOutcome
    validated: ValidatedObservation | None
    candidates_for_user: tuple[Candidate, ...]  # non-empty only on DISAGREEMENT
    score_attempt: ScoreAttempt | None          # set when score was recorded
```

### 7.2 RecognizeScore

```python
class RecognizeScore:
    def __init__(
        self,
        race: VisionRace,
        charts: ChartRepository,
        scores: ScoreRepository,
    ) -> None: ...

    async def recognize(
        self,
        user_id: UserId,
        image: bytes,
        *,
        source_gateway: str,
    ) -> RecognizeResult:
```

### 7.3 Flow

```
1. image_sha256 = hashlib.sha256(image).hexdigest()
2. outcome = await race.run(image)
3. Dispatch on outcome.decision:

   CONSENSUS / DEGRADED_SINGLE:
     a. Take outcome.selected (ValidatedObservation)
     b. chart = selected.primary.chart
     c. judgements = selected.observation.judgements
     d. status = classify_status(judgements)
     e. accuracy = calculate_accuracy(judgements)
     f. rating = calculate_rating(
            chart.official_level, chart.community_constant,
            status, accuracy, chart.difficulty,
        )
     g. Construct ScoreAttempt:
            user_id=user_id
            chart_id=chart.id
            judgements=judgements
            accuracy=accuracy
            rating=rating
            status=status
            image_sha256=image_sha256
            source_gateway=source_gateway
            ocr_run_id=None (Phase 3b)
            created_at=current_time
     h. await scores.record_attempt(attempt)  (atomic INSERT + UPSERT personal_best)
     i. Return RecognizeResult with score_attempt set

   DISAGREEMENT:
     a. Collect validated.candidates from every EngineResult that has validated set
     b. Build Candidate list → domain.rank_candidates()
     c. Return candidates_for_user (deferred to Phase 3b CandidateStore)
     d. Do NOT auto-record any score

   ALL_FAILED / NO_AVAILABLE_ENGINES:
     → Return error info; no candidates, no score

   GLOBAL_TIMEOUT:
     → Application decides (not gateway):
        - If outcome.selected exists and is STRONG: treat as DEGRADED_SINGLE
          (adopt the single strong result)
        - If candidates exist from partial results: return candidates
        - Otherwise: return recoverable error (user can retry)
     → This policy lives in RecognizeScore, not in VisionRace and not in gateway.
```

### 7.4 Time Injection

`RecognizeScore` accepts an optional `clock: Callable[[], datetime]` (default:
`datetime.now(timezone.utc)`) so tests can freeze time without patching.

## 8. Adapters: Vendor Vision Engines

### 8.1 Shared HTTP (`adapters/vision/_http.py`)

```python
def map_request_error(error: httpx.RequestError) -> VisionEngineError:
    """Map transport-layer errors to domain exceptions.
    - httpx.TimeoutException → VisionTimeoutError
    - httpx.ConnectError / httpx.InvalidURL → VisionConnectionError
    - Other RequestError → VisionConnectionError"""

def map_status_error(response: httpx.Response) -> VisionEngineError:
    """Map HTTP status to domain exceptions (call AFTER receiving response).
    - HTTP 429 → VisionRateLimitError
    - HTTP 5xx → VisionServerError
    - HTTP 4xx (non-429) → VisionResponseError"""
```

Single `httpx.AsyncClient` injected into each adapter (shared connection pool).

### 8.2 Gemini, Zhipu, StepFun

Each adapter:
- Receives config (api_key, model) + `httpx.AsyncClient` at construction
- Exposes `identity: EngineIdentity` (engine_id = `{provider}-{model}`)
- `recognize(image, timeout)`:
  1. Build request according to the vendor's current official HTTP API.  Request
     format (JSON inline, multipart, etc.) is confirmed from official documentation
     at implementation time and locked in with request-shape tests.
  2. POST with timeout passed to httpx
  3. Parse response → extract song title, difficulty, level, 5 judgements
  4. Map HTTP errors via `_http.map_request_error` / `_http.map_status_error`
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
    # HALF_OPEN: single probe slot inside lock
    # release(probe=True): free probe slot, back to OPEN, preserve cooldown
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

Validates and raises clear errors on: missing fields, invalid values, duplicate engine IDs,
duplicate providers among enabled engines, unachievable consensus threshold, zero enabled
engines, more than 3 enabled providers.

API keys are NOT in this config — they are injected separately when constructing
vendor adapters.

## 11. Adapters: Repository Extensions

Add to `SqliteChartRepository`:

```python
@dataclass(frozen=True)
class SongCatalog:
    version: str
    candidates: tuple[SongCandidate, ...]

async def get_song_catalog(self) -> SongCatalog: ...

async def get_by_song_and_difficulty(
    self, song_id: int, difficulty: Difficulty,
) -> Chart | None: ...
```

### 11.1 Alias Schema

Add `aliases` column to the `songs` table via the next available, consecutive migration
version (the exact version number is determined at plan time by inspecting the current
migration directory — write the plan to use `N+1` where N is the latest version on disk).

```sql
ALTER TABLE songs ADD COLUMN aliases TEXT NOT NULL DEFAULT '';
```

Phase 3a repository reads aliases (split on a delimiter, e.g. newline, into
`tuple[str, ...]`).  Population of aliases from old emu-bot DB is deferred —
for now only ja/cn/en titles participate in matching.

## 12. Test Plan

### 12.1 Domain Tests (`tests/domain/`)

| Test file | Coverage |
|-----------|----------|
| `test_song_matcher.py` | Exact match (ja/cn/en/alias), NFKC, casefold, OCR corrections on raw only, real title characters not corrupted on candidate side, normalization collision returns multiple candidates, region extraction (difficulty keywords at boundaries, UI noise filtering), four-step first-non-empty, Dice coefficient on bigrams, Levenshtein normalised similarity, position bonus, clamp to 1.0, fuzzy threshold ≥ 0.50, bidirectional prefix, prefix < 5 chars rejected, empty/whitespace title, empty candidates, same score sorted by song_id, compatibility alignment with old emu-bot fixtures |

### 12.2 Application Tests (`tests/application/`)

| Test file | Coverage |
|-----------|----------|
| `test_vision_policy.py` | Validation rejects invalid values, unique engine_id, unique provider among enabled, consensus_threshold vs enabled provider count, ≤3 provider rule, threshold must be 2 |
| `test_vision_race.py` | Two providers agree → consensus; slow third cancelled + awaited + permit released; single success + others fail → degraded_single; two providers disagree → disagreement; one engine throws → others unaffected; consensus cancel calls breaker.release NOT record_failure; circuit-rejected engines skipped; all fail → all_failed; global timeout → partial results; caller cancel → all permits released + re-raised; completion order randomized → result deterministic; same provider ×2 models → cannot form independent consensus; semaphore before permit ordering; breaker.record_success called before validation |
| `test_validate_ocr.py` | First match fail → second match succeed; EXACT + note + level → STRONG; weak fuzzy + note match → CANDIDATE; PREFIX → max CANDIDATE; song exists + difficulty missing → CANDIDATE; note ±1 pass / ±2 fail; level match / conflict → CANDIDATE; all candidates rejected → REJECTED; catalog loads once and invalidates on version change; returns domain objects not dicts |
| `test_recognize_score.py` | Consensus → score recorded (verify accuracy/rating/status via calculate_*); degraded_single → score recorded; disagreement → candidates returned + no score recorded; all_failed → error info + no score; global_timeout + strong single → adopted as degraded_single; global_timeout + no strong → recoverable error; transaction rollback on score write failure; source_gateway propagated to ScoreAttempt |

### 12.3 Adapter Tests (`tests/adapters/`)

| Test file | Coverage |
|-----------|----------|
| `tests/adapters/vision/test_gemini.py` | Response parsing (valid JSON → OcrObservation), request shape matches official API, error response → VisionEngineError subtype, timeout propagation to httpx, Secret not in repr |
| `tests/adapters/vision/test_zhipu.py` | Same as Gemini |
| `tests/adapters/vision/test_stepfun.py` | Same as Gemini |
| `tests/adapters/resilience/test_memory_circuit_breaker.py` | CLOSED→OPEN after N failures, OPEN rejects, cooldown → HALF_OPEN, probe success → CLOSED, probe failure → OPEN, two concurrent acquire in HALF_OPEN only one gets permit, release(probe=True) frees slot + no success/failure recorded, release(probe=False) is no-op, state() is async-safe, every permit settled exactly once |

### 12.4 Integration Notes

- Vision race tests use mock `VisionEngine` that returns pre-configured responses
  and can simulate delays/timeouts/errors — no real API calls
- Vendor adapter tests use recorded HTTP responses (or mock httpx transport)
  so request shape is validated against actual vendor API
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
- Old emu-bot alias data migration (schema column added, population deferred)

## 14. Design Decisions Summary

| Decision | Rationale |
|----------|-----------|
| ≤3 providers, threshold=2 | Deterministic consensus — 2-vote majority unique |
| Provider as consensus unit | Prevents same-vendor false-consensus |
| Permit-based breaker with release() | HALF_OPEN single-probe atomicity + cancel-safe |
| Breaker success before validation | Breaker measures vendor health, not match quality |
| EngineResult carries validated | DISAGREEMENT can merge candidates without re-validation |
| `displayed_level` mismatch → CANDIDATE | Conservative: level conflicts flagged for human review |
| OCR corrections on raw only | Prevents corrupting real song titles |
| Validate top 5 SongMatch | First match + note fail ≠ song is wrong |
| SongCatalog atomic snapshot | Version + candidates never out of sync |
| `EnginePolicy` in application | Application must not import adapters |
| Config parsing in adapter | Application never touches YAML/env vars |
| GLOBAL_TIMEOUT decided in application | Gateway only presents results — no business decisions |
| RecognizeScore builds full ScoreAttempt | All domain rules (accuracy/rating/status) in one path |
| `source_gateway` as parameter | Gateway identity is caller's concern, not global state |
| Shared `httpx.AsyncClient` | Connection pooling, uniform timeout |
| In-memory catalog cache | No Redis dependency for matching |
| Algorithm baseline = old emu-bot | Fixture compatibility over clean-room rewrite |
