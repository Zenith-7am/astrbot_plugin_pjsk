> **Status: Approved** (core layer — still valid under Phase 5 standalone direction).
> The domain, application, ports, and adapter designs in this document remain authoritative for `pjsk_core` and `adapters/`.
> Current governance: `CLAUDE.md`. Phase-5 gateway design: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`.

# Phase 3b — CandidateStore + OCR Run Persistence + Candidate Confirmation

> 设计规格。Phase 3a 冻结后编写。经审查修订（R1）。

**目标：** 持久化每次 OCR 调用记录，存储分歧候选供用户确认，实现候选选择→入库闭环。

**架构：** 新增 `OcrRunRecorder`（记账）和 `ConfirmCandidate`（确认）两个用例；修订 `CandidateStore` port（原子消费、所有者校验）；修订 `RecognizeScore`（接入 recorder + store，贯通 ocr_run_id）。三个 adapter：`MemoryCandidateStore`、`SqliteOcrRunRepository`、migration 004。

---

## 1. 数据模型

### 1.1 新表（Migration 004）

```sql
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

- `result_status`: **每个 configured engine 都记一条**，包括被 breaker 拒绝和因共识取消的。审计价值要求完整记录。
- `final_state`: `consensus` | `degraded_single` | `disagreement` | `all_failed` | `no_available_engines` | `global_timeout`
- `selected_engine`: NULL unless consensus/degraded-single picked a winner
- `validation_status`: `strong` | `candidate` | `rejected` | NULL（engine error 或未返回识别结果时）
- `error_type`: NULL on success / cancelled / rejected
- `UNIQUE(ocr_run_id, engine_id)`: 每个引擎在一个 OCR run 内唯一

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
    result_status: str     # success | failed | timed_out | cancelled_by_consensus | cancelled_by_caller | circuit_rejected
    elapsed_ms: int
    song_title: str | None
    difficulty: Difficulty | None
    displayed_level: int | None
    judgements: Judgements | None
    matched_chart_id: int | None
    validation_status: str | None
    error_type: str | None
```

---

## 2. CandidateStore — 修订 port

现有 port（`pjsk_core/ports/cache.py`）存 `list[OcrObservation]`，替换为以下版本。

核心改动：`consume` 改为 `consume_selection` — 在存储层锁内完成**所有者校验 + 过期检查 + 索引验证 + 删除**，原子操作，杜绝"用户输错一次就永久丢失候选"和"跨用户删除"。

### 2.1 类型定义

```python
from dataclasses import dataclass
from enum import Enum


class CandidateConsumeStatus(Enum):
    """Result of a consume_selection attempt."""
    OK = "ok"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    FORBIDDEN = "forbidden"          # wrong user
    INVALID_SELECTION = "invalid_selection"  # index out of range


@dataclass(frozen=True)
class CandidateConsumeResult:
    status: CandidateConsumeStatus
    candidate: Candidate | None      # present only on OK
    candidate_set: CandidateSet | None  # present only on OK — full context for recording


@dataclass(frozen=True)
class CandidateSet:
    """A ranked set of disagreeing OCR candidates with enough context
    to construct a ScoreAttempt on user confirmation."""
    candidates: tuple[Candidate, ...]
    image_sha256: str
    source_gateway: str
    ocr_run_id: int                     # links back to the OCR run that produced these candidates
    chart_data_version: str             # snapshot at recognition time — for re-validation on confirm
```

### 2.2 Protocol

```python
class CandidateStore(Protocol):
    """Short-lived storage for ambiguous OCR results awaiting user selection.

    Single-consumption: ``consume_selection`` atomically validates and
    deletes in one locked operation. Expired entries auto-clean on put.
    """

    async def put(
        self, user_id: UserId, candidate_set: CandidateSet, ttl_seconds: int,
    ) -> str: ...
    """Store a candidate set and return a string ID for user reference.
    As a side effect, sweeps expired entries and evicts oldest if at capacity."""

    async def consume_selection(
        self, candidate_set_id: str, user_id: UserId, selection: int,
    ) -> CandidateConsumeResult: ...
    """Atomically validate ownership, expiry, and index; delete and return
    on success. Returns structured status on any failure."""
```

- TTL 默认 **300 秒**，通过 `RecognizeScore` 构造函数注入
- `put` 返回 12 字符 hex ID（uuid4 前 12 位）

---

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
    Returns the persisted OcrRunRecord with database-assigned id.
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
1. 遍历**所有** `outcome.results`，包括 CANCELLED 和 breaker-rejected：
   - SUCCESS: `result_status="success"`, 填 song_title/difficulty/displayed_level/judgements/matched_chart_id/validation_status
   - FAILED: `result_status="failed"`, 填 error_type
   - TIMED_OUT: `result_status="timed_out"`, error_type="timeout"
   - CANCELLED_BY_CONSENSUS: `result_status="cancelled_by_consensus"`, error_type=NULL, song_title 等 NULL
   - CANCELLED_BY_CALLER: `result_status="cancelled_by_caller"`, error_type=NULL
   - 被 breaker 拒绝的引擎（`ctx.rejects`）: `result_status="circuit_rejected"`, error_type=NULL
2. `final_state` = `outcome.decision.name.lower()`
3. `selected_engine` = consensus winner 的 engine_id，或 degraded-single 的 engine_id，其余 NULL
4. 组装 `OcrRunRecord` → `repo.save(record)`
5. 返回 `OcrRunRecord`（含 repo 填充的 id）

### 3.3 SqliteOcrRunRepository — 独立连接

新增文件 `adapters/database/ocr_run_repository.py`：

**关键约束：不使用共享连接。** 每次 `save()` 从 connection factory 获取独立连接，在独立连接上执行事务。不与 `ScoreRepository` / `ChartRepository` 共享连接，避免嵌套 BEGIN 和事务冲突。

```python
class SqliteOcrRunRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def save(self, record: OcrRunRecord) -> OcrRunRecord:
        conn = await get_connection(self._db_path)
        try:
            await conn.execute("BEGIN")
            # INSERT ocr_runs ...
            # INSERT ocr_observations (one per engine) ...
            await conn.commit()
            # return record with populated id
        except Exception:
            await conn.rollback()
            raise
        finally:
            await conn.close()

    async def get_by_id(self, run_id: int) -> OcrRunRecord | None:
        # read-only, single connection fine
        ...
```

### 3.4 OCR audit 失败策略

OCR audit 是重要但 **fail-safe** 的观测子系统：

- `recorder.record()` 失败 → 记录 **rate-limited warning**（不重复刷日志），触发 admin 通知（未来实现，当前预留接口）
- **主识别流程继续**：即使 audit 记录失败，共识/降级成绩仍入库，但 `ocr_run_id=None`
- 此策略适用于磁盘满、DB 锁定等临时故障
- `ocr_run_id=None` 本身是一种信号：该成绩的 OCR 审计轨迹丢失

### 3.5 OCR run 保留期限

- 默认保留 **90 天**
- 清理策略在 ops 层面实现（cron 或 systemd timer），不在插件启动时执行
- Phase 3b 只定义 `created_at` 列以支持后续清理，不实现清理脚本

---

## 4. 候选确认流程

### 4.1 ConfirmCandidate 用例

新增文件 `pjsk_core/application/confirm_candidate.py`：

```python
from enum import Enum

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

    Injects ChartRepository (Plan B) for live chart validation at
    confirmation time rather than caching chart fields in Candidate.
    """

    def __init__(
        self,
        store: CandidateStore,
        scores: ScoreRepository,
        charts: ChartRepository,          # Plan B — live lookup, not cached
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None: ...

    async def confirm(
        self,
        user_id: UserId,
        candidate_set_id: str,
        selection: int,                    # 1-based
    ) -> ConfirmResult: ...
```

**流程（Plan B — ChartRepository 注入）：**

1. `store.consume_selection(candidate_set_id, user_id, selection)` → 根据 `CandidateConsumeResult.status`：
   - `NOT_FOUND` → `ConfirmResult(None, NOT_FOUND)`
   - `EXPIRED` → `ConfirmResult(None, EXPIRED)`
   - `FORBIDDEN` → `ConfirmResult(None, FORBIDDEN)`
   - `INVALID_SELECTION` → `ConfirmResult(None, INVALID_SELECTION)`
   - `OK` → 拿到 `candidate` + `candidate_set`，继续

2. **可确认性验证**（全部通过才允许入库）：
   - `candidate.matched_chart_id is not None`
   - `candidate.note_validated is True`
   - `charts.get_by_id(candidate.matched_chart_id)` → chart 存在
   - `candidate.observation.difficulty == chart.difficulty`
   - `|total_judges - chart.note_count| <= 1`
   - 以上任何一条不满足 → `ConfirmResult(None, NOT_CONFIRMABLE)`

3. 如果 `candidate_set.chart_data_version != chart.data_version`：
   - 定数版本已变化，重新校验（可选：打 warning，但仍允许入库——定数更新不应阻塞用户确认）

4. `classify_status(judgements)` → `calculate_accuracy(judgements)` → `calculate_rating(chart.official_level, chart.community_constant, status, accuracy, chart.difficulty)`

5. `ScoreAttempt(ocr_run_id=candidate_set.ocr_run_id, ...)` → `scores.record_attempt(attempt)` → `ConfirmResult(attempt, None)`

### 4.2 Candidate 不扩展

**选方案 B。** Candidate 保持原样，不添加 `official_level` / `community_constant`。确认时通过 `ChartRepository` 查 chart 获取定数，保证使用最新值。Candidate 只描述"模型说了什么"，不复制 chart 属性。

---

## 5. RecognizeScore — 修订

### 5.1 构造函数

```python
class RecognizeScore:
    def __init__(
        self,
        race: VisionRace,
        scores: ScoreRepository,
        recorder: OcrRunRecorder,               # NEW
        store: CandidateStore,                  # NEW
        charts: ChartRepository,                # NEW — for chart_data_version in CandidateSet
        *,
        candidate_ttl_seconds: int = 300,       # NEW — 5 minutes
        clock: Callable[[], datetime] | None = None,
    ) -> None: ...
```

### 5.2 recognize() 流程

```python
async def recognize(self, user_id, image, *, source_gateway) -> RecognizeResult:
    image_sha256 = hashlib.sha256(image).hexdigest()
    outcome = await self._race.run(image)

    # Record OCR run. On failure: log rate-limited warning, continue with ocr_run_id=None.
    ocr_run_id: int | None = None
    try:
        ocr_run = await self._recorder.record(
            user_id, image_sha256, source_gateway, outcome,
        )
        ocr_run_id = ocr_run.id
    except Exception:
        self._log_audit_failure(user_id, image_sha256)  # rate-limited warning

    if outcome.decision in (CONSENSUS, DEGRADED_SINGLE):
        attempt = await self._record(selected, user_id, image_sha256,
                                     source_gateway, ocr_run_id)
        return RecognizeResult(...)

    if outcome.decision == DISAGREEMENT:
        candidates = self._collect_candidates(outcome)
        catalog = await self._charts.get_song_catalog()
        cs = CandidateSet(
            candidates=candidates,
            image_sha256=image_sha256,
            source_gateway=source_gateway,
            ocr_run_id=ocr_run_id,
            chart_data_version=catalog.version,
        )
        cid = await self._store.put(user_id, cs, ttl_seconds=self._candidate_ttl_seconds)
        return RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=candidates,
            candidate_set_id=cid,
            score_attempt=None,
        )

    # GLOBAL_TIMEOUT, ALL_FAILED, NO_AVAILABLE_ENGINES — similar pattern
```

### 5.3 _record() 签名更新

```python
async def _record(
    self,
    selected: ValidatedObservation,
    user_id: UserId,
    image_sha256: str,
    source_gateway: str,
    ocr_run_id: int | None,              # NEW — from recorder
) -> ScoreAttempt: ...
```

### 5.4 RecognizeResult

```python
@dataclass(frozen=True)
class RecognizeResult:
    outcome: VisionRaceOutcome
    validated: ValidatedObservation | None
    candidates_for_user: tuple[Candidate, ...]
    candidate_set_id: str | None
    score_attempt: ScoreAttempt | None
```

---

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
    MAX_ENTRIES = 1000

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def put(self, user_id, candidate_set, ttl_seconds) -> str:
        import uuid
        cid = uuid.uuid4().hex[:12]
        async with self._lock:
            # Sweep expired entries
            now = time.monotonic()
            expired = [k for k, v in self._entries.items() if now > v.expires_at]
            for k in expired:
                del self._entries[k]
            # Evict oldest if at capacity
            if len(self._entries) >= self.MAX_ENTRIES:
                oldest = min(self._entries.keys(), key=lambda k: self._entries[k].expires_at)
                del self._entries[oldest]
            self._entries[cid] = _Entry(
                candidate_set=candidate_set,
                user_id=user_id,
                expires_at=now + ttl_seconds,
            )
        return cid

    async def consume_selection(
        self, candidate_set_id, user_id, selection,
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

**设计要点：**
- 锁内完成全部校验 → 删除，无 TOCTOU 窗口
- 所有者校验在 `del` 之前，杜绝跨用户删除
- 过期项即时清理（`put` 时 sweep）
- `max_entries=1000`，超限时淘汰最旧项
- 重启丢失（可接受——内存存储是 cache，不是持久化）

### 6.2 RedisCandidateStore

Phase 3b 只定义接口，不实现。首版部署无 Redis 依赖，`MemoryCandidateStore` 即可工作。

---

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

- `application` 只依赖 `domain` + `ports`
- 不引入 AstrBot / 平台事件对象进入核心
- `ConfirmCandidate` 注入 `ChartRepository`（Plan B），不把 chart 字段塞进 `Candidate`

---

## 8. 非目标（本阶段不做）

- RedisCandidateStore（adapter 接口保留，实现延后）
- 候选重新发送（用户说"重发候选人"需要联系 gateway 层，延后到功能层）
- 批量确认（一次选多个候选，首版只支持单选）
- OCR runs 查询/统计 UI（get_by_id 仅用于测试验证）
- OCR run 自动清理脚本（`created_at` 已定义，脚本延后到 ops 层）
- CandidateStore peek / renew / list（只有 put + consume_selection）
