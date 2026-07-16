> **Status: Superseded** by Phase 5 standalone OneBot gateway direction.
> **Historical reference only.** Do not use as current implementation authority.
> Current spec: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`
> Current governance: `CLAUDE.md` §18.

# Phase 4a — AstrBot 首个可用纵向链路

> 设计规格。Phase 3b 冻结后编写。

**目标：** 将已有的 OCR pipeline 接入 AstrBot，实现"发图→识别→共识自动入库 / 分歧候选确认"闭环。

**架构：** 手写 Composition Root（`bootstrap.py`）+ `PluginRuntime` 持有长生命周期资源。`plugin/` 层做事件转换+回复呈现，`pjsk_core/application` 不感知 AstrBot。不引入 DI 容器、不自建平台 adapter、不使用全局 service locator。

---

## 1. 插件目录结构

```text
plugin/
  __init__.py
  main.py                 AstrBot 装饰器、事件分流、回复发送
  bootstrap.py            唯一装配入口 — 手写 Composition Root
  runtime.py              PluginRuntime — 持有并关闭长生命周期资源
  event_mapper.py         提取 QQ/OpenID、图片 bytes、会话 ID
  reply_builder.py        TextReply/ImageReply/CandidateReply → AstrBot 消息链
  candidate_presenter.py  候选格式化与用户回复解析
  ephemeral.py            EphemeralImageBuffer — 群聊 15s 图片窗口
```

---

## 2. 生命周期

```text
AstrBot 启动完成
    ↓
on_astrbot_loaded()
    ↓
assemble_plugin_runtime(config_path)
    ├── 数据库迁移
    ├── 连接工厂
    ├── Repository（User / Chart / Score / OCR run）
    ├── Vision Engines（Gemini / 智谱 / StepFun）
    ├── MemoryCircuitBreaker
    ├── VisionRace
    ├── CandidateStore（内存版）
    ├── Application Use Cases
    │     ├── RecognizeScore
    │     └── ConfirmCandidate
    └── EphemeralImageBuffer
    ↓
PluginRuntime
    ↓
terminate()
    └── runtime.close()
         ├── HTTP client 关闭
         └── ImageBuffer 清空
```

### 2.1 PluginRuntime

```python
@dataclass
class PluginRuntime:
    user_repo: UserRepository
    chart_repo: ChartRepository
    score_repo: ScoreRepository
    ocr_run_repo: OcrRunRepository
    recognize_score: RecognizeScore
    confirm_candidate: ConfirmCandidate
    candidate_store: CandidateStore
    image_buffer: EphemeralImageBuffer

    async def close(self) -> None:
        # Close HTTP clients, clear buffers
        ...
```

### 2.2 PjskPlugin

```python
class PjskPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.runtime: PluginRuntime | None = None

    @filter.on_astrbot_loaded()
    async def startup(self):
        self.runtime = await assemble_plugin_runtime(...)

    async def terminate(self):
        if self.runtime is not None:
            await self.runtime.close()
```

---

## 3. 消息分流

### 3.1 入口

两个 handler：

```python
# Handler 1: /pjsk 命令
@filter.command_group("pjsk")
def pjsk():
    pass
# Phase 4a: /pjsk bind
# Phase 4b: /pjsk b20, /pjsk rank, /pjsk my

# Handler 2: 图片 + 候选确认
@filter.event_message_type(filter.EventMessageType.ALL)
async def on_message(self, event: AstrMessageEvent):
    ...
```

### 3.2 分流顺序

```text
收到 AstrMessageEvent
    │
    ├─ 消息以 "/" 开头（可能被框架路由到 command_group）
    │    → 放行，不在此 handler 处理
    │
    ├─ 纯数字/候选选择指令 + 当前会话有有效候选
    │    → candidate_presenter.parse_selection()
    │    → ConfirmCandidate
    │    → 回复 "已记录" 或错误提示
    │    → stop_event()
    │
    ├─ 消息链包含 Image
    │    → event_mapper 提取 image_bytes + 会话信息
    │    → auto_register（首次自动创建用户）
    │    → RecognizeScore
    │    → 返回共识/分歧/错误回复
    │    → stop_event()
    │
    └─ 其他消息
         → return（放行给 AstrBot 聊天人格）
```

### 3.3 stop_event() 规则

- 仅在插件确认接管消息后调用
- 普通消息绝不调用
- 候选数字：有候选且合法 → 消费并 stop；无候选或超范围 → 放行

### 3.4 群聊图片触发

```text
私聊：
  单张图 → 立即 OCR

群聊：
  @Bot + Image（同消息）→ 立即 OCR
  Image → 15s 内单独 @Bot → OCR
  单独 @Bot → 15s 内发 Image → OCR
  @Bot + 普通文字 → 放行给 AstrBot 人格
  无 @ 普通图片 → 不回复，只存 EphemeralImageBuffer
```

### 3.5 艾特检测

以下触发 OCR：
- 消息链同时含 `At(Bot)` 和 `Image`
- 消息只有 `At(Bot)` 且无其他有效文字

以下放行给聊天人格：
- `@Bot 你好`、`@Bot 这张图好看吗` 等含语义文字的艾特

---

## 4. 用户注册

**首次发图自动注册。** `/pjsk bind` 只用于补充游戏 ID。

```text
收到图片
    ↓
event_mapper.extract_qq(event) → qq_number
    ↓
user_repo.get_by_qq(qq_number)
    ├─ 存在 → user
    └─ None → user_repo.create(qq_number, game_id=None)
              → user
    ↓
后续流程使用 user.id
```

`/pjsk bind <game_id>` 更新已有用户的 `game_id` 字段。无需额外注册步骤。

---

## 5. 候选确认交互

### 5.1 候选归属

使用 `(platform_id, conversation_id, user_id)` 三元组隔离：

- 同一用户同一会话只保留一组候选
- 再次上传覆盖旧候选
- 不同群/私聊/用户互不影响

### 5.2 回复格式

```text
识别结果存在分歧，请选择：

1. Tell Your World / MASTER 26
2. テルユアワールド / MASTER 26
3. Tell Your World / EXPERT 22

请在 5 分钟内回复 1、2 或 3。
候选编号：3b7f
```

### 5.3 用户输入优先级

1. **引用候选消息 + 数字** — 精确匹配
2. **`选 3b7f 2`** — 跨平台显式兜底
3. **纯数字 `2`** — 默认方式，仅当当前会话有唯一有效候选

### 5.4 TTL

- 首版 5 分钟（与 CandidateStore 300s 默认 TTL 一致）
- 过期后回复 "候选已过期，请重新发图"

### 5.5 状态提示

| 状态 | 回复 |
|------|------|
| 确认成功 | "已记录，Master 26 FC 1100/1200" |
| 过期 | "候选已过期，请重新发图" |
| 已被覆盖 | "已有新的识别结果，请重新选择" |
| 无效编号 | "请输入 1-3 之间的数字" |
| 无可确认 | "该候选无法确认（数据异常），请重新发图" |
| 无候选 | 放行给 AstrBot 聊天人格 |

---

## 6. 图片处理器

### 6.1 event_mapper

```python
@dataclass(frozen=True)
class ImageContext:
    image_bytes: bytes
    qq_number: QqNumber              # 必需
    openid: str | None               # QQ 官方 Bot
    platform_id: str                 # "qq_official" / "onebot_v11"
    conversation_id: str             # 群号或私聊 ID
    source_gateway: str              # 持久化用

class EventMapper:
    """Extract image bytes and identity from AstrBot event."""
    def extract(self, event: AstrMessageEvent) -> ImageContext | None: ...
    def extract_qq(self, event: AstrMessageEvent) -> QqNumber: ...
    def extract_conversation_id(self, event: AstrMessageEvent) -> str: ...
```

**关键约束：**
- 在 handler 返回前读取图片为 `bytes`
- 不把临时文件路径传给后台任务
- 不检查 HTTP Content-Type，只检查 AstrBot 统一消息组件 `Image`

### 6.2 图片数量

- 1 张：正常识别
- >1 张：回复 "目前一次只能识别一张"
- AstrBot 临时文件在 handler 返回前读取完毕

### 6.3 图片大小限制

- 单图上限 10 MiB
- 超过：回复 "图片过大，请压缩后重试"

---

## 7. EphemeralImageBuffer

群聊窗口需要短暂保存图片以待 @Bot 触发。

```python
class EphemeralImageBuffer:
    MAX_SIZE_BYTES = 10 * 1024 * 1024   # 10 MiB per image
    MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 50 MiB global cap
    TTL_SECONDS = 15

    def put(
        self,
        platform_id: str,
        group_id: str,
        sender_qq: QqNumber,
        image_bytes: bytes,
    ) -> None: ...

    def consume(
        self,
        platform_id: str,
        group_id: str,
        sender_qq: QqNumber,
        *,
        within_seconds: float = 15.0,
    ) -> bytes | None:
        """Return the most recent image from this user within the window,
        and remove it from the buffer."""
        ...

    async def close(self) -> None:
        """Clear all buffered images."""
        ...
```

**约束：**
- 纯内存，不入数据库
- 每个用户只保留最新一张
- 超时自动释放（lazy，put 或 consume 时清理）
- 插件关闭时统一清空
- 不记录图片内容到日志
- 属于 AstrBot 交互适配层，不放 domain / Repository / CandidateStore

---

## 8. 错误回复策略

### 8.1 用户端

所有错误返回简短中文文本，不暴露内部细节。

| 场景 | 回复 |
|------|------|
| 所有引擎不可用 | "识别服务暂不可用，请稍后再试" |
| 图片不是 PJSK 截图 | "未能识别到 PJSK 成绩，请确认截图正确" |
| 识别超时 | "识别超时，请稍后重试" |
| 图片过大 | "图片过大，请压缩后重试" |
| 同时多张图 | "目前一次只能识别一张" |
| 用户限流 | "当前使用人数较多，请稍后再试" |

### 8.2 内部 ErrorCode

```python
class PluginErrorCode(Enum):
    ALL_ENGINES_DOWN = "E001"
    NOT_PJSK_SCREENSHOT = "E002"
    OCR_TIMEOUT = "E003"
    IMAGE_TOO_LARGE = "E004"
    MULTIPLE_IMAGES = "E005"
    USER_RATE_LIMITED = "E006"
```

- 用户端不暴露 `ErrorCode`
- debug 日志记录完整上下文（ErrorCode + user_id + 摘要信息）
- 不做 PII 泄露（不记录 QQ 号全量到普通日志）

---

## 9. 命令注册

Phase 4a 只实现 `/pjsk bind`。其余命令延后到 Phase 4b。

```python
@pjsk.command("bind")
async def bind_handler(self, event, game_id: str):
    """绑定 PJSK 游戏 ID。"""
```

### 9.1 bind 校验

- game_id 必须为 6-16 位数字
- 同一 game_id 不能绑定到不同 QQ 号（先到先得）
- 已绑定也可以重新绑定更新

---

## 10. 限流

首版：**用户级简单限流**。

- 每次 OCR 识别后给 user_id 记一个"冷却"标记
- 冷却期内发送新图片回复限流提示
- 冷却时长可配置，默认 5 秒
- 仅限同一用户，不阻塞其他用户
- 当前共识自动入库的用户不受限流影响（已在冷却中）

限流器放在 plugin 层（非 application 层），因为它关联的是用户交互频率，不是业务规则。

```python
class UserRateLimiter:
    COOLDOWN_SECONDS = 5.0

    def check(self, user_id: UserId) -> bool:
        """Return True if allowed, False if rate-limited."""
        ...

    def mark(self, user_id: UserId) -> None:
        """Record a successful recognition for cooldown."""
        ...
```

用 `time.monotonic()`，进程内存即可。不需要 Redis。

---

## 11. 依赖方向

```text
plugin/            ← AstrBot 事件、回复呈现、Composition Root
    ↓
pjsk_core/
  application/     ← RecognizeScore, ConfirmCandidate, OcrRunRecorder
    ↓
  domain + ports   ← 不做任何修改
    ↑
  adapters/        ← 不做任何修改（已有所有 adapter）
```

- `plugin/` 认识 AstrBot + `pjsk_core`
- `pjsk_core` 不认识 AstrBot（不变）
- `plugin/` 不自己实现 Rating / B20 / 数据库规则
- `Context` 不入 application/domain

---

## 12. 非目标（Phase 4a 不做）

- `/pjsk b20`、`/pjsk rank`、`/pjsk my` 命令（Phase 4b）
- 渲染服务接入（Phase 4b）
- Redis adapter
- 批量上传
- 旧库数据迁移
- VPS 部署
- `/pjsk cancel` 命令（用户发新图覆盖即可替代）
- 群聊无 @ 图片的 OCR 回复（既不回复"这是什么"也不调用 LLM）
- EphemeralImageBuffer 的主动过期清理（TTL 过期时惰性清理）
