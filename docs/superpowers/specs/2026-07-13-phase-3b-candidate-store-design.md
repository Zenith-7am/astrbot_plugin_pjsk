# Phase 3b — CandidateStore + OCR Run Persistence + Candidate Confirmation

> 设计规格。Phase 3a 冻结后编写。

**目标：** 持久化每次 OCR 调用记录，存储分歧候选供用户确认，实现候选选择→入库闭环。

**架构：** 新增 `OcrRunRecorder`（记账）和 `ConfirmCandidate`（确认）两个用例；修订 `CandidateStore` port（存 `CandidateSet` 而非 `OcrObservation`）；修订 `RecognizeScore`（接入 recorder + store）。三个 adapter：`MemoryCandidateStore`、`SqliteOcrRunRepository`、migration 004。

## 1. 数据模型

### 1.1 新表（Migration 004）

```sql
CREATE TABLE ocr_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    image_sha256    TEXT NOT NULL,
    source_gateway  TEXT NOT NULL,
    final_state     TEXT NOT NULL,
    selected_engine TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE ocr_observations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ocr_run_id        INTEGER NOT NULL REFERENCES ocr_runs(id),
    engine_id         TEXT NOT NULL,
    provider          TEXT NOT NULL,
    elapsed_ms        INTEGER NOT NULL,
    song_title        TEXT,
    difficulty        TEXT,
    displayed_level   INTEGER,
    perfect           INTEGER,
    great             INTEGER,
    good              INTEGER,
    bad               INTEGER,
    miss              INTEGER,
    matched_chart_id  INTEGER REFERENCES charts(id),
    validation_status TEXT,
    error_type        TEXT
);
```

- `final_state`: `consensus` | `degraded_single` | `disagreement` | `all_failed` | `no_available_engines` | `global_timeout`
- `selected_engine`: NULL unless consensus/degraded-single picked a winner
- `validation_status`: `strong` | `candidate` | `rejected` | NULL（engine error 时）
- `error_type`: `timeout` | `connection` | `rate_limited` | `server_error` | `invalid_response` | NULL（success 时）

### 1.2 域类型

```python
@dataclass(frozen=True)
class OcrRunRecord:
    id: int | None
    user_id: UserId
    image_sha256: str
    source_gateway: str
    final_state: str
    selected_engine: str | None
    observations: tuple[OcrEngineRecord, ...]
    created_at: datetime

@dataclass(frozen=True)
class OcrEngineRecord:
    engine_id: str
    provider: str
    elapsed_ms: int
    song_title: str | None
    difficulty: Difficulty | None
    displayed_level: int | None
    judgements: Judgements | None
    matched_chart_id: int | None
    validation_status: str | None
    error_type: str | None
```

## 2. CandidateStore — 修订 port

现有 port（`pjsk_core/ports/cache.py`）存 `list[OcrObservation]`，替换为以下版本。

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class CandidateSet:
    """A ranked set of disagreeing OCR candidates with enough context
    to construct a ScoreAttempt on user confirmation."""
    candidates: tuple[Candidate, ...]   # domain Candidate, already ranked
    image_sha256: str
    source_gateway: str

class CandidateStore(Protocol):
    """Short-lived storage for ambiguous OCR results awaiting user selection.

    Single-consumption: ``consume`` atomically retrieves and deletes.
    Expired entries return None from ``consume``, same as not-found.
    """

    async def put(
        self, user_id: UserId, candidate_set: CandidateSet, ttl_seconds: int,
    ) -> str: ...
    """Store a candidate set and return a string ID for user reference."""

    async def consume(
        self, candidate_set_id: str, user_id: UserId,
    ) -> CandidateSet | None: ...
    """Retrieve and delete. Returns None if expired, consumed, or nonexistent."""
```

- TTL 默认 60 秒，通过 `RecognizeScore` 构造函数注入
- `put` 返回的 ID 是字符串（Redis UUID / 内存递增编号）

## 3. OCR Run 持久化

### 3.1 OcrRunRepository port

新增文件 `pjsk_core/ports/ocr_runs.py`：

```python
class OcrRunRepository(Protocol):
    """Persistence for OCR run audit records."""

    async def save(self, record: OcrRunRecord) -> OcrRunRecord: ...
    async def get_by_id(self, run_id: int) -> OcrRunRecord | None: ...
```

### 3.2 OcrRunRecorder 用例

新增文件 `pjsk_core/application/ocr_run_recorder.py`：

```python
class OcrRunRecorder:
    """Record every OCR attempt for audit/debugging.

    Call after VisionRace.run() completes, regardless of outcome.
    """

    def __init__(self, repo: OcrRunRepository) -> None: ...

    async def record(
        self,
        user_id: UserId,
        image_sha256: str,
        source_gateway: str,
        outcome: VisionRaceOutcome,
    ) -> OcrRunRecord: ...
```

**内部逻辑：**
1. 遍历 `outcome.results`，每个 `EngineResult` → `OcrEngineRecord`：
   - SUCCESS：填 song_title/difficulty/displayed_level/judgements, matched_chart_id, validation_status
   - FAILED/TIMED_OUT：填 error_type，song_title 等为 None
   - CANCELLED_BY_CONSENSUS/CANCELLED_BY_CALLER：不记入 observations（没有实际调用结果）
2. `final_state` = `outcome.decision.name.lower()`
3. `selected_engine` = consensus winner 的 engine_id，或 degraded-single 的 engine_id，其余 NULL
4. 组装 `OcrRunRecord` → `repo.save(record)`
5. 返回 `OcrRunRecord`（含 repo 填充的 id）

### 3.3 SqliteOcrRunRepository

新增文件 `adapters/database/ocr_run_repository.py`：

- 接收 `aiosqlite.Connection`
- `save()`: 在一个事务内 INSERT ocr_runs + 多条 ocr_observations
- `get_by_id()`: JOIN 查询，还原 `OcrRunRecord`

## 4. 候选确认流程

### 4.1 ConfirmCandidate 用例

新增文件 `pjsk_core/application/confirm_candidate.py`：

```python
@dataclass(frozen=True)
class ConfirmResult:
    score_attempt: ScoreAttempt | None
    error: str | None              # "not_found", "expired", "invalid_index"

class ConfirmCandidate:
    """Resolve a disagreeing OCR run by user candidate selection."""

    def __init__(
        self,
        store: CandidateStore,
        scores: ScoreRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None: ...

    async def confirm(
        self,
        user_id: UserId,
        candidate_set_id: str,
        selection: int,             # 1-based
    ) -> ConfirmResult: ...
```

**流程：**
1. `store.consume(candidate_set_id, user_id)` → None → `ConfirmResult(None, "not_found")`
2. `selection < 1 or selection > len(candidates)` → `ConfirmResult(None, "invalid_index")`
3. 取 `candidate = candidates[selection - 1]`
4. 从 candidate.observation.judgements 构造判定 → `classify_status()` → `calculate_accuracy()`
5. chart_id = candidate.matched_chart_id；若为 None → `ConfirmResult(None, "invalid_index")`
6. `calculate_rating(level, constant, status, accuracy, difficulty)` ← 需要 chart 信息
7. 构造 `ScoreAttempt(image_sha256=cs.image_sha256, source_gateway=cs.source_gateway, ocr_run_id=None, ...)`
8. `scores.record_attempt(attempt)` → `ConfirmResult(attempt, None)`

**注意：** ConfirmCandidate 需要 chart 的 `official_level` 和 `community_constant` 才能算 rating。Candidate 的 `matched_chart_id` 只能拿到 chart ID，拿不到 level/constant。两个选择：
- **方案 A（省事）：** Candidate 扩展，加 `official_level` 和 `community_constant` 字段。Phase 3a 的 `_collect_candidates` 已经有 chart 引用，直接塞进去。
- **方案 B（纯正）：** ConfirmCandidate 注入 `ChartRepository`，根据 chart_id 查。

**选方案 A。** Candidate 已是富类型，加两个字段比多一次数据库查询简单。

### 4.2 Candidate 扩展

```python
@dataclass(frozen=True)
class Candidate:
    observation: OcrObservation
    model_support: int
    note_validated: bool
    title_similarity: float
    note_distance: int
    matched_chart_id: int | None
    official_level: int | None       # NEW — for rating calc on confirm
    community_constant: str | None   # NEW
```

## 5. RecognizeScore — 修订

现有用例需要三处改动：注入新依赖、记录 OCR run、存储候选。

### 5.1 构造函数

```python
class RecognizeScore:
    def __init__(
        self,
        race: VisionRace,
        scores: ScoreRepository,
        recorder: OcrRunRecorder,           # NEW
        store: CandidateStore,              # NEW
        *,
        candidate_ttl_seconds: int = 60,    # NEW
        clock: Callable[[], datetime] | None = None,
    ) -> None: ...
```

### 5.2 recognize() 流程

```python
async def recognize(self, user_id, image, *, source_gateway) -> RecognizeResult:
    image_sha256 = hashlib.sha256(image).hexdigest()
    outcome = await self._race.run(image)

    # NEW — always record the OCR run
    await self._recorder.record(user_id, image_sha256, source_gateway, outcome)

    if outcome.decision in (CONSENSUS, DEGRADED_SINGLE):
        # Existing flow — construct + record ScoreAttempt
        ...

    if outcome.decision == DISAGREEMENT:
        candidates = self._collect_candidates(outcome)
        # NEW — store for user confirmation
        cs = CandidateSet(
            candidates=candidates,
            image_sha256=image_sha256,
            source_gateway=source_gateway,
        )
        cid = await self._store.put(user_id, cs, ttl_seconds=self._candidate_ttl_seconds)
        return RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=candidates,
            candidate_set_id=cid,            # NEW field
            score_attempt=None,
        )

    # ... other branches
```

### 5.3 RecognizeResult

```python
@dataclass(frozen=True)
class RecognizeResult:
    outcome: VisionRaceOutcome
    validated: ValidatedObservation | None
    candidates_for_user: tuple[Candidate, ...]
    candidate_set_id: str | None       # NEW
    score_attempt: ScoreAttempt | None
```

## 6. Adapters

### 6.1 MemoryCandidateStore

新增文件 `adapters/cache/memory_candidate_store.py`：

```python
@dataclass
class _Entry:
    candidate_set: CandidateSet
    user_id: UserId
    expires_at: float  # monotonic timestamp

class MemoryCandidateStore:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def put(self, user_id, candidate_set, ttl_seconds) -> str:
        import uuid
        cid = uuid.uuid4().hex[:12]
        async with self._lock:
            self._entries[cid] = _Entry(
                candidate_set=candidate_set,
                user_id=user_id,
                expires_at=time.monotonic() + ttl_seconds,
            )
        return cid

    async def consume(self, candidate_set_id, user_id) -> CandidateSet | None:
        async with self._lock:
            entry = self._entries.pop(candidate_set_id, None)
        if entry is None:
            return None
        if entry.user_id != user_id:
            return None
        if time.monotonic() > entry.expires_at:
            return None
        return entry.candidate_set
```

- 无外部依赖，重启丢失
- 不做主动过期清理
- `user_id` 校验防止跨用户消费

### 6.2 RedisCandidateStore

Phase 3b 只定义接口，不实现。首版部署无 Redis 依赖，`MemoryCandidateStore` 即可工作。

## 7. 依赖方向

```text
plugin / gateways
       ↓
   application        ← OcrRunRecorder, ConfirmCandidate, RecognizeScore（修订）
       ↓
 domain + ports       ← OcrRunRecord, OcrEngineRecord, CandidateSet, CandidateStore, OcrRunRepository
       ↑
  adapters            ← SqliteOcrRunRepository, MemoryCandidateStore
```

- `application` 只依赖 `domain` + `ports`（OcrRunRecorder、ConfirmCandidate、修订后 RecognizeScore 均满足）
- 不引入 AstrBot / 平台事件对象进入核心
- ConfirmCandidate 不感知任何 platform 对象

## 8. 非目标（本阶段不做）

- RedisCandidateStore（adapter 接口保留，实现延后）
- 候选重新发送（用户说"重发候选人"需要联系 gateway 层，延后到功能层）
- 批量确认（一次选多个候选，首版只支持单选）
- OCR runs 查询/统计（get_by_id 仅用于测试验证，不做生产查询界面）
- CandidateStore peek / renew / list（只有 put + consume）
