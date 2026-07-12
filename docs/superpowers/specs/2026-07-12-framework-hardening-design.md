# Framework Hardening — Pre-Extraction Scaffold Design

日期：2026-07-12

## 目标

在从旧 `emu-bot` 提取业务逻辑（Task 2+）之前，搭好承载代码的"容器"：插件外壳、领域数据类型、端口合约、回复类型、gateway 转换签名。核心原则：**由内向外，先定型，后填逻辑**。

## 设计哲学

- **核心**（domain）— 纯数据类型，不写计算逻辑
- **数据**（ports）— 五个窄 Protocol，定义"核心需要什么能力"
- **功能**（application）— 统一回复类型，用例编排依赖 ports
- AstrBot 插件可加载性是最终检验标准

## 范围（本次必须产出）

1. `plugin/metadata.yaml` + `plugin/main.py` — AstrBot Star 子类壳
2. `pjsk_core/domain/users.py` — UserId, QqNumber, User
3. `pjsk_core/domain/charts.py` — Difficulty enum, Chart
4. `pjsk_core/domain/scores.py` — ScoreStatus enum, Judgements, ScoreAttempt
5. `pjsk_core/domain/ocr.py` — OcrObservation
6. `pjsk_core/application/replies.py` — TextReply, ImageReply, CandidateReply, ProgressReply, ErrorReply
7. `pjsk_core/ports/repositories.py` — UserRepository, ChartRepository, ScoreRepository
8. `pjsk_core/ports/vision.py` — VisionEngine
9. `pjsk_core/ports/renderer.py` — Renderer, RenderRequest, RenderResult
10. `pjsk_core/ports/identity.py` — IdentityResolver
11. `pjsk_core/ports/cache.py` — CandidateStore
12. `adapters/gateways/astrbot/` — 事件转换与回复映射（函数签名层）
13. 配套测试：port contracts, reply types, domain 不变式

## 明确排除

- accuracy / rating / B20 公式实现
- 曲名匹配算法
- 任何 I/O 实现（数据库、HTTP、Redis）
- 数据库 schema 或迁移脚本
- 视觉模型 SDK 集成
- 渲染服务实现
- placeholder 函数或假实现

以上留给 Phase 1 Task 2–7。

## Domain 数据类

所有数据类均为 frozen dataclass，`__post_init__` 仅做输入校验，不做业务计算。

### users.py

```python
@dataclass(frozen=True)
class QqNumber:
    value: str  # 纯数字字符串，"123456789"

@dataclass(frozen=True)
class UserId:
    value: int

@dataclass(frozen=True)
class User:
    id: UserId
    qq_number: QqNumber
    game_id: str | None
```

不变式：QQ 号只含数字字符；game_id 可为 None 但不可为空字符串。

### charts.py

```python
class Difficulty(Enum):
    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"
    EXPERT = "expert"
    MASTER = "master"
    APPEND = "append"

@dataclass(frozen=True)
class Chart:
    id: int
    song_id: int
    difficulty: Difficulty
    official_level: int
    community_constant: str       # "31.2", "32.5+" — 显示值，解析逻辑在 Task 3
    note_count: int
    data_version: str
```

### scores.py

```python
class ScoreStatus(Enum):
    AP = "ap"
    FC = "fc"
    CLEAR = "clear"

@dataclass(frozen=True)
class Judgements:
    perfect: int
    great: int
    good: int
    bad: int
    miss: int

@dataclass(frozen=True)
class ScoreAttempt:
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
```

不变式：id 为 None 表示未入库；created_at 必须带时区。

### ocr.py

```python
@dataclass(frozen=True)
class OcrObservation:
    song_title: str
    difficulty: Difficulty
    displayed_level: int
    judgements: Judgements
    engine: str
    elapsed_ms: int
```

## Ports

所有端口均为 `typing.Protocol`，方法签名引用 domain 类型。返回领域对象，不返回 dict 或数据库行。

### repositories.py

- `UserRepository` — `get_by_id`, `get_by_qq`, `create`
- `ChartRepository` — `get_by_id`, `find_by_song_and_difficulty`, `list_by_difficulty_level`
- `ScoreRepository` — `record_attempt`（同一事务内 attempt 入库 + 更新 personal_best）, `get_personal_best`, `list_personal_bests`

### vision.py

```python
class VisionEngine(Protocol):
    name: str
    async def recognize(self, image: bytes, *, timeout: float) -> OcrObservation: ...
```

### renderer.py

- `RenderRequest` / `RenderResult` dataclass
- `Renderer` Protocol — `async def render(self, request: RenderRequest) -> RenderResult`

### identity.py

```python
class IdentityResolver(Protocol):
    async def resolve(self, platform: str, external_id: str) -> QqNumber | None: ...
```

### cache.py

```python
class CandidateStore(Protocol):
    async def put(self, user_id: UserId, candidates: list[OcrObservation], ttl_seconds: int) -> str: ...
    async def consume(self, candidate_set_id: str) -> list[OcrObservation] | None: ...
```

## 回复类型

```python
@dataclass(frozen=True)
class TextReply: text: str

@dataclass(frozen=True)
class ImageReply: image_bytes: bytes; mime_type: str

@dataclass(frozen=True)
class CandidateReply: candidate_set_id: str; candidates: list[OcrObservation]

@dataclass(frozen=True)
class ProgressReply: message: str; current: int; total: int

@dataclass(frozen=True)
class ErrorReply: message: str; recoverable: bool
```

## Plugin 外壳

- `plugin/metadata.yaml` — name, desc, version, author, astrbot_version
- `plugin/main.py` — `@register` 装饰的 Star 子类，空的 initialize/terminate，无命令注册
- 目标：AstrBot 能成功加载插件，不报错即可

## Gateway Adapter

```
adapters/gateways/astrbot/
  __init__.py
  event_converter.py   # AstrMessageEvent → 内部事件（函数签名）
  reply_mapper.py      # 内部 Reply → AstrBot 消息（函数签名）
```

只定义函数签名和 docstring，不写转换逻辑。AstrBot 类型（`AstrMessageEvent`, `Context` 等）不进入 `pjsk_core`。

## 测试

- 现有包边界测试 4 个 — 保持通过
- `tests/test_port_contracts.py` — 每个 Protocol 写 fake 实现，赋值给类型变量，做 async smoke call
- `tests/domain/test_users.py` — QqNumber 校验（空字符串、非数字字符拒绝；纯数字通过）
- `tests/domain/test_charts.py` — Difficulty enum 成员完整性
- `tests/domain/test_scores.py` — ScoreStatus enum, Judgements 非负校验
- `tests/domain/test_ocr.py` — OcrObservation 构造
- `tests/test_reply_types.py` — 五种 Reply 构造 + 字段校验

## 执行顺序

1. `plugin/metadata.yaml` + `plugin/main.py` — Star 壳
2. `pjsk_core/domain/` — users, charts, scores, ocr 数据类
3. `pjsk_core/application/replies.py` — 五种回复类型
4. `pjsk_core/ports/` — 五个 Protocol
5. `adapters/gateways/astrbot/` — 事件转换签名
6. 配套测试
7. pytest + ruff + mypy 全绿
8. 逐个 task commit

## 完成标准

- AstrBot 可加载插件（`plugin/main.py` 不报错）
- 所有 domain 数据类可通过不变式校验
- 所有 ports 有 fake 实现并通过 contract 测试
- 边界测试保持通过
- Ruff / mypy strict 零错误
