# Phase 5 — Standalone OneBot Gateway (NoneBot-Based)

> 设计规格。Phase 4b 冻结后编写，基于 Task 1 审计结论和旧 bot 复用评估。

**目标：** 将项目从"AstrBot 插件为生产入口"切换为"NoneBot 2 + OneBot v11 独立 Gateway"，AstrBot 退出生产消息链但代码保留。

**架构决策：** 复用 NoneBot 2 框架的 OneBot adapter（连接管理、事件模型、消息段类型），不自研 WebSocket 层。Gateway 只做事件转换、命令路由和回复呈现，业务规则继续放在 `pjsk_core`。

---

## 1. 整体架构

```text
NapCat (国内 VPS，反向隧道)
    │  OneBot v11 WebSocket
    ▼
NoneBot 2 Gateway (香港 VPS，独立 systemd 服务)
    │  事件转换 → 平台无关 DTO
    ▼
pjsk_core.application
    │  RecognizeScore / ConfirmCandidate / QueryB20 / QueryDifficultyRanking
    ▼
SQLite / Vision Engines / Renderer (同现有 adapters/)
```

依赖方向（单向）：

```text
gateway/          (NoneBot matchers, reply sender, command router)
    │
    ▼
pjsk_emubot/      (runtime, ephemeral buffer, rate limiter, candidate presenter)
    │
    ▼
pjsk_core/        (application, domain, ports — 零变更)
    │
    ▲
adapters/         (database, vision, rendering, cache, resilience — 零变更)
```

## 2. 新目录结构

```text
gateway/
  __init__.py
  bot.py                    NoneBot 初始化 + OneBot adapter 注册 (≈25 行)
  matchers/
    __init__.py
    image_handler.py        私聊/群聊图片识别 matcher
    command_handler.py      /emu command matcher (b20, append, difficulty, help, status)
    candidate_handler.py    候选数字确认 matcher
  adapters/
    __init__.py
    event_mapper.py          OneBot Event → ImageContext + IncomingMessage DTO
    reply_sender.py          TextReply/ImageReply/CandidateReply → OneBot API calls
    config_loader.py         独立配置加载（环境变量 + YAML）
  health.py                 健康检查 HTTP endpoint
  connection_monitor.py     NapCat 心跳/生命周期监控 + 管理员通知

pjsk_emubot/                (现有，微调)
  bootstrap.py              提取独立 composition root → pjsk_runtime/bootstrap.py
  runtime.py                 (不变)
  ephemeral.py               (不变)
  rate_limiter.py            (不变)
  candidate_presenter.py     (不变)
  result_dto.py              (不变)
  _handlers.py               逐步废弃，逻辑迁移至 gateway/matchers/
  event_mapper.py            逐步废弃，逻辑迁移至 gateway/adapters/event_mapper.py
  reply_builder.py           PluginErrorCode 保留，_AstroPlain 移除

pjsk_runtime/
  __init__.py
  bootstrap.py               平台无关的 Composition Root（从 pjsk_emubot/bootstrap.py 提取）

main.py                     保留（AstrBot 兼容），但不再主动维护
metadata.yaml               保留，不删除
_conf_schema.json            保留，不删除

ops/
  pjsk-renderer.service      (现有)
  pjsk-onebot.service        新增 — 独立 OneBot Bot 的 systemd unit
```

## 3. bot.py — 最小入口

```python
"""PJSK Bot — NoneBot 2 + OneBot v11 Gateway."""
from pathlib import Path
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# Load gateway matchers only — no business logic lives here
nonebot.load_plugins(str(Path(__file__).parent / "matchers"))

if __name__ == "__main__":
    nonebot.run()
```

**约束**：
- 不在此文件配置 API Key、数据库路径或模型参数。
- 不在此文件注册业务 handler。
- 不从此文件 import `pjsk_core` 或 `adapters/`。

## 4. 事件与回复 DTO

### 4.1 输入 DTO（OneBot 事件 → 平台无关类型）

```python
from dataclasses import dataclass
from pjsk_core.domain.users import QqNumber

@dataclass(frozen=True)
class IncomingMessage:
    """Platform-agnostic incoming message after OneBot event extraction."""
    gateway: str                        # "onebot"
    external_user_id: str               # QQ number as string
    qq_number: QqNumber
    conversation_type: str              # "private" | "group"
    group_id: str | None                # None for private chat
    message_id: str
    text: str                           # stripped plain text
    image_refs: list[ImageRef]          # images in message
    is_bot_mentioned: bool              # @Bot in group, always True in private
    reply_target_message_id: str | None


@dataclass(frozen=True)
class ImageRef:
    """Reference to an image in a OneBot message."""
    file_id: str                        # OneBot file ID (for get_image API)
    url: str | None                     # Direct URL if available
```

`ImageContext`（现有 `pjsk_emubot/event_mapper.py`）保留，增加 `from_onebot_event()` 工厂方法。

### 4.2 输出 DTO（内部 reply → OneBot 消息段）

**全部复用现有 `pjsk_core/application/replies.py`**：

```python
TextReply          → OneBot text segment → send_msg API
ImageReply         → CDN URL → [CQ:image,file=url] → send_msg API
CandidateReply     → TextReply (formatted candidate list)
ProgressReply      → TextReply (progress update)
ErrorReply         → TextReply (error message)
```

`reply_sender.py` 负责这个映射——**不在 matcher 里直接拼 CQ 码**。

## 5. Matcher 列表

| Matcher | 触发条件 | 优先级 | block | 说明 |
|---------|---------|--------|-------|------|
| `candidate_matcher` | 私聊/群聊文本，候选集存在 | 1 | True | 数字确认/取消 |
| `image_matcher` | 私聊单图，或 群聊 @Bot+单图 | 10 | False | OCR 识别 |
| `command_matcher` | `/emu` 开头 | 20 | False | 命令分发 |
| `help_fallback` | 未匹配的命令 / 未知输入 | 99 | False | 返回帮助文本 |

### 5.1 命令路由

采用 NoneBot `on_command` matcher：

```text
/emu help                         → 帮助文本
/emu status                       → 安全的聚合运行状态（无密钥、无用户标识）
/emu b20                          → 个人 B20（渲染图片或文本降级）
/emu append include               → APPEND 包含
/emu append exclude               → APPEND 排除
/emu append status                → APPEND 当前状态
/emu <diff><level>                → 个人难度排行（如 /emu ma31）
/emu <diff><level> global         → 全局难度排行
```

### 5.2 截图入口

| 场景 | 行为 | 复杂度 |
|------|------|--------|
| 私聊单图 | 直接 OCR → 共识入库/候选 | 低 |
| 群聊 @Bot + 单图（同消息） | 直接 OCR | 低 |
| 候选数字确认 | 消费候选 → 入库/错误 | 低 |
| 先发图后 @Bot（15s 窗口） | 消耗 EphemeralImageBuffer | 中 — 首版实现 |
| 先 @Bot 后发图（15s 窗口） | arm → consume_arm | 中 — 首版实现 |

### 5.3 约束

- matcher 不得直接调用 `send_private_msg` 或 `send_group_msg`——必须通过 `reply_sender.py`。
- matcher 不计算 accuracy、rating、B20、难度排行。
- matcher 不直接访问数据库、Redis 或视觉引擎。
- `command_matcher` 只做路由分发，具体逻辑委托给 `pjsk_core.application` use cases。

## 6. 生命周期

```text
systemd start pjsk-onebot.service
    │
    ▼
bot.py: nonebot.init() → register_adapter(OneBotV11Adapter)
    │
    ▼
@driver.on_startup
    ├── config_loader.load()            # 读环境变量 + YAML
    ├── pjsk_runtime.bootstrap()        # Composition Root（同现有装配逻辑）
    ├── reply_sender.init(runtime)      # 注入 runtime → reply sender
    ├── connection_monitor.init()       # 注册心跳/lifecycle handler
    └── health.start()                  # HTTP health endpoint
    │
    ▼
NapCat WebSocket connected → OneBot events flowing
    │
    ▼
@driver.on_shutdown
    ├── runtime.close()                 # 关闭 HTTP client, DB connections
    ├── reply_sender.shutdown()
    └── health.stop()
```

## 7. `pjsk_runtime/bootstrap.py` — 平台无关 Composition Root

从现有 `pjsk_emubot/bootstrap.py` 提取。核心函数签名：

```python
async def bootstrap(config: dict[str, object]) -> PluginRuntime:
    """Assemble all long-lived resources. Platform-agnostic.
    
    Accepts a plain dict (from env vars + YAML), NOT an AstrBot config dict.
    Returns PluginRuntime with all dependencies wired.
    """
```

提取规则：
- 移除 `from astrbot.core.utils.astrbot_path import get_astrbot_data_path`
- 数据库路径改为显式传入 `config["database_path"]`
- `_read_config()` 改为纯 YAML + env 合并，不再 merge AstrBot WebUI dict
- `PLUGIN_NAME` 改为 `"pjsk-bot"`
- 其他装配逻辑不变（connections, repos, vision engines, use cases）

**兼容过渡**：旧 `pjsk_emubot/bootstrap.py` 改为 thin wrapper：

```python
from pjsk_runtime.bootstrap import bootstrap as _bootstrap
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

async def assemble_plugin_runtime(config=None):
    cfg = _read_config(config)          # AstrBot-specific config merge
    cfg["database_path"] = str(_resolve_db_path())
    return await _bootstrap(cfg)
```

## 8. 配置模型

### 8.1 加载优先级（高优先覆盖低）

1. 环境变量（secrets：API Keys, Access Token）
2. YAML 配置文件（结构配置：超时、并发、URLs）
3. 代码默认值

### 8.2 配置项

```yaml
# pjsk-bot.yml (结构配置，可提交模板)
onebot:
  ws_url: "ws://127.0.0.1:3001"        # NapCat 反向 WS 地址
  access_token: "${ONEBOT_ACCESS_TOKEN}" # 环境变量引用

database:
  path: "/opt/pjsk-astrbot/shared/data/pjsk.db"

vision:
  engines:
    gemini:
      api_key: "${GEMINI_API_KEY}"
      model: "2.5-flash"
      enabled: true
    zhipu:
      api_key: "${ZHIPU_API_KEY}"
      model: "glm-4.6v-flash"
      enabled: true
    stepfun:
      api_key: "${STEPFUN_API_KEY}"
      model: "step-1v-32k"
      enabled: false
    dashscope:
      api_key: "${DASHSCOPE_API_KEY}"
      model: "qwen3-vl-flash"
      enabled: true
  timeout_seconds: 15
  concurrency: 3

renderer:
  url: "http://127.0.0.1:3000"
  timeout_seconds: 30

rate_limit:
  user_cooldown_seconds: 5
  candidate_ttl_seconds: 300
  image_window_seconds: 15

admin:
  qq: "${ADMIN_QQ}"                     # 故障通知目标

cdn:
  enabled: true
  base_url: "http://127.0.0.1:8082"
  image_dir: "/tmp/pjsk_images"
  cleanup_ttl_seconds: 600
  max_file_size_bytes: 5242880          # 5 MiB
```

### 8.3 启动验证

- 缺少 `ONEBOT_ACCESS_TOKEN` → 警告（部分部署不需要）
- 缺少**所有**视觉引擎 API Key → 启动失败，明确错误
- 数据库路径不可写 → 启动失败
- Renderer URL 不可达 → 降级（文本回复），不阻塞

### 8.4 约束

- API Key 和 Access Token 不得写入日志或 systemd unit。
- systemd unit 通过 `EnvironmentFile` 引用受保护的 env 文件。
- Redis 不可用不阻塞启动；进入 degraded 模式。

## 9. 旧代码复用审计

### 9.1 逐项评估

| 旧文件 | 行数 | 可提取内容 | 风险 | 处置 |
|--------|------|-----------|------|------|
| `src/core/api.py` | 105 | `send_group_msg()`, `send_private_msg()`, `get_image_url()` 的 OneBot API 调用模式 | 低 — NoneBot 2 API 稳定 | 提取模式，重写实现：英文命名、类型标注、移除旧 throttle 依赖 |
| `src/core/connection_monitor.py` | 163 | 心跳/lifecycle 事件监听、离线检测、恢复通知模式 | 低 — NoneBot 2 事件类型不变 | 提取模式，重写：英文代码、结构化日志、可注入通知目标 |
| `src/features/_common.py` | 88 | `is_dm()`, `get_user_id()`, `reply()`, `reply_at()`, `reply_image()` | 中 — `reply_image()` CDN 模式需安全审计 | `is_dm`/`get_user_id` 直接引用 NoneBot 类型，无需提取；`reply`/`reply_at` 模式提取到 `reply_sender.py`；`reply_image()` 见 §10 |
| `bot.py` | 20 | NoneBot 初始化模式 | 极低 | 直接参考 — 模式简单，三行代码 |
| `src/core/config.py` | 47 | CDN 图片路径和清理 TTL | 低 — 纯配置 | 提取配置值，改入新 config 模型 |
| `src/core/throttle.py` | — | 图片/文本限流逻辑 | 中 — 耦合 Redis | 不提取 — 新 bot 用现有 `UserRateLimiter`；图片频率控制在 `reply_sender.py` 用简单计数器 |
| `src/features/handler_ocr.py` | — | OCR 处理流程 | — | **不复用** — 已被 `pjsk_core/application/recognize_score.py` 完全替代 |
| 所有 `src/features/handler_*.py` | — | B20、难度排行、alias、注册等 | — | **不复用** — 全部已在 `pjsk_core` 重写 |

### 9.2 提取原则

- 读旧代码理解行为 → 写新代码在新位置 → 不复制旧文件。
- 新代码：英文注释/标识符、类型标注、无硬编码密钥、日志脱敏。
- 每个提取的模块编写独立测试（不需要旧 bot 环境）。
- 旧仓库 `D:\emu-bot` 保持只读，不做任何修改。

## 10. CDN 图片发送安全审计

### 10.1 旧实现风险分析

旧 `reply_image()`（`_common.py:53-67`）：

```python
filename = f"{uuid.uuid4().hex}.jpg"      # ✅ 不可预测
filepath = os.path.join(IMAGE_DIR, filename) # ⚠️ 无路径穿越校验
with open(filepath, "wb") as f:            # ⚠️ 无文件大小校验
    f.write(image_bytes)
url = f"{IMAGE_BASE_URL}/images/{filename}" # ⚠️ 无文件类型校验
await reply(event, f"[CQ:image,file={url}]") # ✅ CDN URL 模式
```

旧 `_serve_image()`（`__init__.py:54-63`）：

```python
@app.get("/images/{filename}")
async def _serve_image(filename: str):
    # ⚠️ 路径穿越防护不足 — filename.replace(".","") 只能阻止 ".."
    if not filename.replace(".", "").replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=404, detail="Invalid filename")
    filepath = os.path.join(IMAGE_DIR, filename)
    # ⚠️ 无 os.path.realpath() 校验，符号链接攻击可能绕过
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(filepath, media_type="image/jpeg")
    # ⚠️ 无 Content-Disposition 限制，无文件大小限制
```

### 10.2 新设计加固

```python
import secrets
import os
from pathlib import Path

def _safe_image_path(filename: str, image_dir: Path) -> Path | None:
    """Resolve and validate an image path. Returns None if unsafe."""
    candidate = (image_dir / filename).resolve()
    if not str(candidate).startswith(str(image_dir.resolve())):
        return None                        # path traversal attempt
    return candidate

# New reply_image:
async def reply_image(event, image_bytes: bytes, max_bytes: int = 5 * 1024 * 1024):
    # 1. Size gate
    if len(image_bytes) > max_bytes:
        logger.warning("Image too large: %d bytes", len(image_bytes))
        await reply(event, "[图片过大，请压缩后重试]")
        return

    # 2. Magic-byte validation (JPEG / PNG / GIF / WebP only)
    if not _is_valid_image_magic(image_bytes):
        logger.warning("Invalid image magic bytes")
        await reply(event, "[图片格式不支持]")
        return

    # 3. Unpredictable filename
    filename = f"{secrets.token_hex(16)}.jpg"
    filepath = IMAGE_DIR / filename

    # 4. Write with size limit (defense-in-depth)
    filepath.write_bytes(image_bytes)

    url = f"{IMAGE_BASE_URL}/images/{filename}"
    await reply(event, f"[CQ:image,file={url}]")

# New serve:
@app.get("/images/{filename}")
async def _serve_image(filename: str):
    path = _safe_image_path(filename, IMAGE_DIR)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404)
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=404)
    return FileResponse(
        str(path),
        media_type="image/jpeg",
        headers={"Content-Disposition": "inline"},
    )
```

### 10.3 CDN 降级

CDN 不可用时（`IMAGE_BASE_URL` 未配置或 FastAPI 路由未加载），退化为 **文本回复**：显示识别结果摘要（song/difficulty/status/accuracy/rating），不发送图片。

## 11. 数据库：旧数据迁移

### 11.1 当前状态

| 数据库 | 路径 | Schema | 记录数 |
|--------|------|--------|--------|
| 新库 | `/root/data/plugin_data/astrbot_plugin_pjsk/pjsk.db` | v6 | 7 users, 4 score_attempts |
| 旧库 | `/opt/pjsk-emu-bot/data/bot.db` | 旧 schema（6 tables） | 旧生产数据 |

### 11.2 迁移策略

**目标**：新库成为唯一生产库。旧数据迁入后，旧库保留为只读备份。

**流程**（不在此 Phase 执行，仅设计）：

```text
1. 制旧库只读快照
2. 审计器输出聚合统计（不输出用户级 PII）
3. 导入 users → 旧 QqNumber 冲突时优先保留新库记录
4. 导入 songs/charts/aliases → 与 chart_data 交叉校验
5. 旧 scores → score_attempts（逐条转换，保留原始 OCR 来源标记）
6. 按新规则重算 personal_bests
7. 对账：用户数、成绩数、抽样 B20、难度排行
8. 影子查询（新 old 两路对比，统计差异）
9. 备份新库
10. 最终增量迁移
11. 新库设为唯一写入源
```

**约束**：
- 迁移脚本只连接只读旧库快照 + 读写新库。
- 不直接修改旧生产库。
- 迁移后旧库保留至少 30 天作为回滚参考。
- `source_gateway` 标记区分新旧来源：`"onebot"` (新) vs `"legacy_emu"` (旧导入)。

## 12. 并发模型

```text
NapCat WS Event
    │
    ▼
NoneBot driver (asyncio event loop, 单线程)
    │
    ├── image_matcher    ──→ RecognizeScore.recognize()
    │                             ├── VisionRace (asyncio.gather, 2-3 engines)
    │                             └── ScoreRepository (aiosqlite, WAL mode)
    │
    ├── command_matcher  ──→ QueryB20 / QueryDifficultyRanking
    │                             └── Renderer (httpx, semaphore-gated)
    │
    └── candidate_matcher ──→ ConfirmCandidate
                                  └── ScoreRepository (same connection, WAL)
```

- 所有 I/O 为 async（aiosqlite、httpx、NoneBot API）。
- VisionRace 内部用 `asyncio.Semaphore` 限并发。
- Renderer 调用用 `asyncio.Semaphore` 限并发。
- SQLite WAL mode 支持并发读/单写（已在现有代码中启用）。
- `EphemeralImageBuffer` 在单进程内线程安全（asyncio 单线程）。

## 13. 错误处理

| 层 | 错误 | 处理 |
|----|------|------|
| OneBot 连接断开 | WebSocket closed | NoneBot 自动重连；connection_monitor 记录离线时长 |
| 图片下载失败 | HTTP error / timeout | 文本回复"图片下载失败，请重试" |
| OCR 全引擎故障 | 所有 VisionEngine 超时/熔断 | 文本回复"识别服务暂不可用" |
| OCR 无共识 | candidates available | 发送候选列表，等用户确认 |
| 候选超时 | TTL expired | 文本回复"确认已过期，请重新发送截图" |
| Renderer 故障 | HTTP error / timeout | 文本降级（纯文本排行榜/B20 列表） |
| 数据库故障 | SQLite error | 启动失败 + 明确错误日志 |
| 未知命令 | 不匹配任何 matcher | `/emu help` 文本 |
| NapCat 断线 > 5min | heartbeat timeout | 管理员通知 + degraded 模式 |

## 14. 日志与健康检查

### 14.1 日志

```text
[PJSK] gateway started, onebot connected
[PJSK] image received: type=private size=<bytes>
[PJSK] OCR started: engines=[gemini-2.5-flash, qwen3-vl-flash]
[PJSK] OCR result: consensus=STRONG engine=gemini-2.5-flash elapsed=2.3s
[PJSK] OCR disagreement: 2 candidates for user_id=<hash>
[PJSK] candidate confirmed: selection=2
[PJSK] renderer: b20 rendered 180KB in 1.2s
[PJSK] renderer: fallback to text (HTTP 503)
[PJSK] onebot disconnected: reason="WebSocket closed" downtime=0s
[PJSK] onebot reconnected: downtime=45s
[PJSK] gateway shutting down...
```

**禁止记录**：QQ 号、游戏 ID、OCR 原文、图片 URL、图片内容、API Key、Access Token。

### 14.2 健康检查

HTTP endpoint `GET /health`：

```json
{
  "status": "ok" | "degraded" | "down",
  "onebot": "connected" | "disconnected",
  "database": "ok" | "error",
  "vision": {
    "gemini-2.5-flash": "ok" | "degraded" | "down",
    "zhipu-glm-4.6v-flash": "ok" | "degraded" | "down"
  },
  "renderer": "ok" | "degraded",
  "uptime_seconds": 3600
}
```

不含：API Key、数据库路径、用户数、成绩数、QQ 号。

## 15. systemd 与部署

### 15.1 `pjsk-onebot.service`

```ini
[Unit]
Description=PJSK OneBot Gateway (NoneBot 2)
After=network.target pjsk-renderer.service
Wants=pjsk-renderer.service

[Service]
Type=simple
User=pjsk
WorkingDirectory=/opt/pjsk-astrbot/current
EnvironmentFile=/opt/pjsk-astrbot/shared/bot.env
ExecStart=/opt/pjsk-astrbot/current/.venv/bin/python gateway/bot.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/pjsk-astrbot/shared/data /tmp/pjsk_images

[Install]
WantedBy=multi-user.target
```

**`/opt/pjsk-astrbot/shared/bot.env`**（权限 600，非 root 可读）：

```text
ONEBOT_ACCESS_TOKEN=<secret>
GEMINI_API_KEY=<secret>
ZHIPU_API_KEY=<secret>
STEPFUN_API_KEY=<secret>
DASHSCOPE_API_KEY=<secret>
ADMIN_QQ=<secret>
```

### 15.2 依赖关系

```text
pjsk-renderer.service ──→ (独立 FastAPI 渲染)
pjsk-onebot.service    ──→ Wants=pjsk-renderer.service
                            (renderer 不可用不阻塞启动)
                            After=network.target
```

## 16. 影子验证

### 16.1 设计

不采用"同一 QQ 号双 Bot 同时回复"模式（会导致用户收到重复消息）。

**方案 A（首选）**：测试 QQ 号 + 测试 NapCat 实例
- 独立 QQ 号 + 独立 NapCat → 新 gateway → 写测试数据库
- 零影响生产，完整功能验证

**方案 B（次选）**：只读观测模式
- 新 gateway 连接生产 NapCat，注册消息监听
- `RecognizeScore` 传入 `readonly=True` → OCR 执行 + 校验，但不写 `score_attempts`
- 对比新/旧 OCR 结果和评分，记录差异
- 不对用户回复

**方案 C（最后选择）**：受控时间窗口
- 暂停旧 bot（`systemctl stop pjsk-emu-bot`）
- 启动新 gateway 5 分钟
- 执行预定义测试序列
- 恢复旧 bot
- 此方案会短暂中断服务

### 16.2 验证项

| # | 测试 | 验收标准 |
|---|------|---------|
| 1 | OneBot 连接 | WebSocket connected, heartbeat 正常 |
| 2 | 私聊文本 | 无 PJSK 内容 → 不回复，passthrough |
| 3 | 私聊图片 | 成绩截图 → OCR 成功 → 富文本 Echo 回复 |
| 4 | 群聊 @Bot + 图片 | 同消息 @ → OCR 触发 |
| 5 | 先图后 @（15s 内） | buffer consume → OCR 触发 |
| 6 | 先 @ 后图（15s 内） | arm → consume_arm → OCR 触发 |
| 7 | 候选确认 | 发数字 → 确认入库 → 确认 Echo |
| 8 | `/emu help` | 返回帮助文本 |
| 9 | `/emu status` | 返回安全运行状态 |
| 10 | `/emu b20` | 渲染图片或文本降级 |
| 11 | `/emu ma31` | 个人难度排行 |
| 12 | `/emu ma31 global` | 全局难度排行 |
| 13 | `/emu append exclude` | 切换 APPEND 设置 |
| 14 | OCR 超时 | 单引擎超时不阻塞，多引擎全超时返回错误 |
| 15 | 单引擎故障 | 其他引擎继续，共识阈值自适应 |
| 16 | Renderer 故障 | 文本降级，不报错 |
| 17 | NapCat 断线重连 | 15s 内自动重连，日志记录 |
| 18 | 服务重启 | 数据库一致，in-flight 成绩不丢失 |
| 19 | 并发多图 | 用户级 rate limit + 全局 semaphore 生效 |

## 17. 切换与回滚

### 17.1 切换步骤（待批准后执行）

```text
1. 备份生产数据库 (cp pjsk.db pjsk.db.bak-$(date -I))
2. 记录基线：Git SHA, schema_version, chart_data_version, user_count, score_count
3. 部署新代码到 /opt/pjsk-astrbot/releases/<id>/
4. 预检：全模块 import、配置校验、数据库连接测试
5. systemctl stop pjsk-emu-bot.service      # 暂停旧 bot
6. systemctl start pjsk-onebot.service       # 启动新 gateway
7. health check: curl /health → status=ok
8. 执行 1 条受控测试（私聊发图 → 确认回复和入库）
9. 核对数据库写入（新 score_attempts 行，personal_bests 更新）
10. 观察 15 分钟错误率和延迟
11. 如果正常 → systemctl disable pjsk-emu-bot.service
12. 如果异常 → 见回滚
```

### 17.2 回滚步骤

```text
1. systemctl stop pjsk-onebot.service
2. systemctl start pjsk-emu-bot.service
3. 验证旧 bot 恢复（/health/napcat → online: true）
4. 恢复旧数据库 (cp pjsk.db.bak-* pjsk.db)
5. 观察 5 分钟确认正常
6. 记录故障原因和时间线
```

**回滚不丢失数据**：新 gateway 写入的成绩在 `score_attempts` 中标记 `source_gateway="onebot"`。回滚时旧 bot 继续使用旧逻辑（读旧数据库），新成绩保留在新库中，恢复后再迁移。

## 18. 测试矩阵

| 层 | 测试类型 | 数量估算 | 说明 |
|----|---------|---------|------|
| `gateway/adapters/event_mapper.py` | 单元 | ~12 | OneBot JSON fixtures → ImageContext / IncomingMessage |
| `gateway/adapters/reply_sender.py` | 单元 | ~8 | TextReply / ImageReply → OneBot message segment |
| `gateway/adapters/config_loader.py` | 单元 | ~6 | 优先级、缺失项、脱敏 |
| `gateway/matchers/image_handler.py` | 集成 | ~10 | 私聊/群聊图片 → _handle_image |
| `gateway/matchers/command_handler.py` | 集成 | ~12 | 6 种子命令 + help + 未知命令 |
| `gateway/matchers/candidate_handler.py` | 集成 | ~5 | 数字确认/过期/无效输入 |
| `gateway/connection_monitor.py` | 单元 | ~5 | 心跳超时、状态转换、通知 |
| `gateway/health.py` | 单元 | ~4 | ok/degraded/down 状态 |
| `gateway/bot.py` | 冒烟 | ~2 | 模块加载、adapter 注册 |
| `pjsk_runtime/bootstrap.py` | 单元 | ~8 | 配置加载、资源创建、关闭 |
| CDN image serving | 安全 | ~6 | 路径穿越、magic bytes、size gate |
| 影子验证 | E2E | ~19 | 见 §16.2 |

**免责**：NoneBot 2 框架本身的 OneBot adapter（WebSocket、重连、心跳）已有 NoneBot 社区测试覆盖。我们不测试框架，只测试自己的 gateway 层。

## 19. 依赖清单

```text
# 新依赖
nonebot2[onebot-v11]       # OneBot v11 adapter
httpx                      # HTTP client (已有)
aiosqlite                  # SQLite async (已有)
pyyaml                     # YAML config (已有)

# 不再需要的依赖（AstrBot 专用）
astrbot                    # 不再安装为生产依赖

# 保持不变的依赖
fastapi, playwright        # render_service (已有)
Pillow                     # 图片处理 (已有)
```

## 20. 旧代码提取候选及风险

| # | 来源 | 提取内容 | 新位置 | 风险等级 | 风险说明 |
|---|------|---------|--------|---------|---------|
| 1 | `bot.py:1-19` | NoneBot 初始化模式 | `gateway/bot.py` | 极低 | 参考模式，不复制代码 |
| 2 | `api.py:26-49` | `send_group_msg` / `send_private_msg` 模式 | `gateway/adapters/reply_sender.py` | 低 | NoneBot API 稳定；移除旧 throttle |
| 3 | `api.py:52-79` | `get_image_url` — file_id → URL 解析 | `gateway/adapters/reply_sender.py` | 低 | NapCat 响应格式可能变化，需覆盖 3 种已知格式 |
| 4 | `connection_monitor.py:50-61` | 心跳 watchdog 模式 | `gateway/connection_monitor.py` | 低 | 纯 NoneBot 事件；重写更安全 |
| 5 | `connection_monitor.py:66-107` | 状态转换逻辑（在线↔离线↔恢复） | `gateway/connection_monitor.py` | 中 | 状态机需完整测试 |
| 6 | `connection_monitor.py:29-36` | 管理员通知发送 | `gateway/connection_monitor.py` | 中 | 故障时通知可能失败（NapCat 离线）；需降级 |
| 7 | `_common.py:53-67` | `reply_image` CDN 模式 | `gateway/adapters/reply_sender.py` | **高** | 路径穿越、文件类型伪造、DoS（§10） |
| 8 | `_common.py:19-28` | `is_dm` / `get_user_id` / `get_group_id` | 直接用 NoneBot 2 event 属性 | 极低 | 无需封装 |
| 9 | `config.py:31-33` | CDN 图片路径和清理 TTL | `pjsk-bot.yml` 配置模板 | 低 | 纯配置迁移 |
| 10 | `__init__.py:54-63` | `_serve_image` FastAPI 路由 | `gateway/health.py` 的图片服务部分 | **高** | 路径穿越（§10）；需完整安全加固 |

---

> **状态：设计完成，待审查。** 批准后进入 Task 3（命令设计细化）。
