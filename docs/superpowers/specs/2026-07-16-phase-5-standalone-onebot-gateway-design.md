# Phase 5 — Standalone OneBot Gateway (NoneBot-Based)

> **Status: Under Review** — not yet approved for implementation.
> **Supersedes:** v2 (commit `da2c00f`, subsequently `15e982d`).
> **Implementation allowed: No** — pending governance approval.
>
> 设计规格 v3。修订于 2026-07-16。
> v2→v3: shadow-composition fail-closed, CDN lifecycle independence, rollback gated on freeze-baseline, atomic-publish reference to production runbook.

**目标：** 将项目从"AstrBot 插件为生产入口"切换为"NoneBot 2 + OneBot v11 独立 Gateway"，AstrBot 退出生产消息链但代码保留。

## 1. 整体架构

```
NapCat (国内 VPS)
    │  OneBot v11 反向 WebSocket（NapCat 主动连接）
    │  经反向隧道 → 香港 VPS
    ▼
NoneBot 2 Gateway (香港 VPS，独立 systemd 服务)
    │  监听 127.0.0.1:<port>，接收 NapCat 连接
    │  事件转换 → 平台无关 DTO
    ▼
pjsk_core.application
    │  RecognizeScore / ConfirmCandidate / QueryB20 / QueryDifficultyRanking
    ▼
SQLite / Vision Engines / Renderer (同现有 adapters/)
```

### 1.1 连接方向（明确）

```
NapCat (国内 VPS)                     NoneBot (香港 VPS)
─────────────────                     ─────────────────
ws_reverse 配置:                      监听 host:port
  url: ws://<tunnel-host>:<port>/      register_adapter(OneBotV11Adapter)
       onebot/v11/ws/
NapCat 是 WebSocket 客户端             NoneBot 是 WebSocket 服务端
断线重连由 NapCat 负责                 NoneBot adapter 接受入站连接，
                                      连接断开时由 NapCat 重新发起
```

**关键配置项**：

- **NoneBot 侧**：`HOST=127.0.0.1`、`PORT=<port>`、`ONEBOT_ACCESS_TOKEN=<secret>`。NoneBot 不主动连接外部地址——它只监听。
- **NapCat 侧**：`ws_reverse` 配置中填写 `ws://<反向隧道地址>:<port>/onebot/v11/ws/`，携带 `access_token`。
- **隧道方向**：国内 VPS → 香港 VPS（反向隧道）。NapCat 通过隧道连接到 NoneBot。
- **鉴权要求**：跨 VPS WebSocket 必须携带 `access_token`——不得仅依赖隧道 IP 限制。`ONEBOT_ACCESS_TOKEN` 缺失时**启动失败**，不降级为无鉴权模式。

### 1.2 依赖方向（单向）

```
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

---

## 2. 新目录结构

```
gateway/
  __init__.py
  bot.py                    NoneBot 初始化 + OneBot adapter 注册 (=25 行)
  matchers/
    __init__.py
    image_handler.py        私聊/群聊图片识别 matcher
    command_handler.py      /emu command matcher
    candidate_handler.py    候选数字确认 matcher
  adapters/
    __init__.py
    event_mapper.py          OneBot Event -> ImageContext + IncomingMessage DTO
    reply_sender.py          TextReply/ImageReply/CandidateReply -> OneBot message segments
    config_loader.py         独立配置加载（环境变量 + YAML，含 ${VAR} 展开规则）
  health.py                 健康检查 HTTP endpoint
  connection_monitor.py     NapCat 心跳/生命周期监控 + 管理员通知（含 OneBot 不可用时的降级）

pjsk_emubot/                (现有，微调)
  bootstrap.py              提取独立 composition root -> pjsk_runtime/bootstrap.py
  runtime.py                 PlatformRuntime -> Runtime 重命名
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
  pjsk-onebot.service        新增 - 独立 OneBot Bot 的 systemd unit
```

---

## 3. bot.py — 最小入口

```python
"""PJSK Bot - NoneBot 2 + OneBot v11 Gateway."""
from pathlib import Path
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# Load gateway matchers only - no business logic lives here
nonebot.load_plugins(str(Path(__file__).parent / "matchers"))

if __name__ == "__main__":
    nonebot.run()
```

**约束**：
- 不在此文件配置 API Key、数据库路径或模型参数。
- 不在此文件注册业务 handler。
- 不从此文件 import `pjsk_core` 或 `adapters/`。

---

## 4. 事件与回复 DTO

### 4.1 输入 DTO（OneBot 事件 -> 平台无关类型）

```python
from dataclasses import dataclass
from enum import Enum
from pjsk_core.domain.users import QqNumber


class ConversationType(Enum):
    PRIVATE = "private"
    GROUP = "group"


@dataclass(frozen=True)
class ImageRef:
    """Reference to an image in a OneBot message."""
    file_id: str                        # OneBot file ID (for get_image API)
    url: str | None                     # Direct URL if available


@dataclass(frozen=True)
class IncomingMessage:
    """Platform-agnostic incoming message after OneBot event extraction."""
    gateway: str                        # "onebot"
    external_user_id: str               # QQ number as string
    qq_number: QqNumber
    conversation_type: ConversationType
    group_id: str | None                # None for private chat
    message_id: str
    text: str                           # stripped plain text
    image_refs: tuple[ImageRef, ...]    # immutable — images in message
    is_bot_mentioned: bool              # @Bot in group, always True in private
    reply_target_message_id: str | None
```

**约束**：
- `ImageContext`（现有 `pjsk_emubot/event_mapper.py`）保留，但**不在其中添加 `from_onebot_event()`**。
- 从 OneBot 事件构造 `ImageContext` 的工厂逻辑放在 `gateway/adapters/event_mapper.py`——平台无关类型不得反向认识 OneBot。
- `image_refs` 使用不可变 `tuple`，禁止运行期修改。
- `conversation_type` 使用 `ConversationType` enum，不传魔术字符串 `"private"`/`"group"`。

### 4.2 输出 DTO（内部 reply -> OneBot 消息段）

**全部复用现有 `pjsk_core/application/replies.py`**：

```python
TextReply          -> OneBot MessageSegment.text()       -> send_msg API
ImageReply         -> OneBot MessageSegment.image(url)   -> send_msg API (CDN URL 模式)
CandidateReply     -> TextReply (formatted candidate list)
ProgressReply      -> TextReply (progress update)
ErrorReply         -> TextReply (error message)
```

`reply_sender.py` 负责这个映射——**不在 matcher 里直接拼消息段**。

**禁止**生成 `[CQ:image,...]` 字符串——必须使用 NoneBot OneBot v11 的 `MessageSegment.image(url)`。

---

## 5. Matcher 列表

| Matcher | 触发条件 | 优先级 | block | 说明 |
|---------|---------|--------|-------|------|
| `candidate_matcher` | 私聊/群聊文本，候选集存在 | 1 | True | 数字确认/取消 |
| `image_matcher` | 私聊单图，或 群聊 @Bot+单图 | 10 | False | OCR 识别 |
| `command_matcher` | `/emu` 开头 | 20 | False | 命令分发 |
| `emu_help_fallback` | `/emu` 开头但不匹配已知子命令 | 99 | False | 返回帮助文本 |

**`emu_help_fallback` 作用域**：只匹配 `/emu` 前缀的不明命令。不以 `/emu` 开头的普通消息**不触发此 matcher**——passthrough 给 NoneBot 的其他 handler（或直接无响应）。

### 5.1 命令路由

采用 NoneBot `on_command` matcher：

```
/emu help                         -> 帮助文本
/emu status                       -> 安全的聚合运行状态（无密钥、无用户标识）
/emu b20                          -> 个人 B20（渲染图片或文本降级）
/emu append include               -> APPEND 包含
/emu append exclude               -> APPEND 排除
/emu append status                -> APPEND 当前状态
/emu <diff><level>                -> 个人难度排行（如 /emu ma31）
/emu <diff><level> global         -> 全局难度排行
```

### 5.2 截图入口

| 场景 | 行为 | 复杂度 |
|------|------|--------|
| 私聊单图 | 直接 OCR -> 共识入库/候选 | 低 |
| 群聊 @Bot + 单图（同消息） | 直接 OCR | 低 |
| 候选数字确认 | 消费候选 -> 入库/错误 | 低 |
| 先发图后 @Bot（15s 窗口） | 消耗 EphemeralImageBuffer | 中 — 首版实现 |
| 先 @Bot 后发图（15s 窗口） | arm -> consume_arm | 中 — 首版实现 |

### 5.3 约束

- matcher 不得直接调用 `send_private_msg` 或 `send_group_msg`——必须通过 `reply_sender.py`。
- matcher 不计算 accuracy、rating、B20、难度排行。
- matcher 不直接访问数据库、Redis 或视觉引擎。
- `command_matcher` 只做路由分发，具体逻辑委托给 `pjsk_core.application` use cases。

---

## 6. 生命周期

```
systemd start pjsk-onebot.service
    │
    ▼
bot.py: nonebot.init() -> register_adapter(OneBotV11Adapter)
    │
    ▼
@driver.on_startup
    ├── config_loader.load()            # 读环境变量 + YAML，展开 ${VAR}，校验必需项
    ├── pjsk_runtime.bootstrap()        # Composition Root（同现有装配逻辑）
    ├── reply_sender.init(runtime)      # 注入 runtime -> reply sender
    ├── connection_monitor.init()       # 注册心跳/lifecycle handler
    └── health.start()                  # HTTP health endpoint
    │
    ▼
NoneBot 开始监听 -> NapCat 发起反向 WebSocket 连接 -> OneBot events flowing
    │
    ▼
@driver.on_shutdown
    ├── runtime.close()                 # 关闭 HTTP client, DB connections
    ├── reply_sender.shutdown()
    └── health.stop()
```

---

## 7. `pjsk_runtime/bootstrap.py` — 平台无关 Composition Root

从现有 `pjsk_emubot/bootstrap.py` 提取。返回类型从 `PluginRuntime` 重命名为 `Runtime`（平台无关）。

核心函数签名：

```python
from pjsk_emubot.runtime import Runtime  # renamed from PluginRuntime

async def bootstrap(config: dict[str, object]) -> Runtime:
    """Assemble all long-lived resources. Platform-agnostic.
    
    Accepts a plain dict (from env vars + YAML), NOT an AstrBot config dict.
    Returns Runtime with all dependencies wired.
    """
```

提取规则：
- 移除 `from astrbot.core.utils.astrbot_path import get_astrbot_data_path`
- 数据库路径改为显式传入 `config["database_path"]`
- `_read_config()` 改为纯 YAML + env 合并（见 §8.1），不再 merge AstrBot WebUI dict
- `PLUGIN_NAME` 改为 `"pjsk-bot"`
- `PluginRuntime` 重命名为 `Runtime`（`pjsk_emubot/runtime.py` 同步改动）
- 其他装配逻辑不变（connections, repos, vision engines, use cases）

**兼容过渡**：旧 `pjsk_emubot/bootstrap.py` 改为 thin wrapper：

```python
from pjsk_runtime.bootstrap import bootstrap as _bootstrap
from pjsk_emubot.runtime import Runtime  # re-export for AstrBot consumers
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

async def assemble_plugin_runtime(config=None):
    cfg = _read_config(config)          # AstrBot-specific config merge
    cfg["database_path"] = str(_resolve_db_path())
    return await _bootstrap(cfg)
```

---

## 8. 配置模型

### 8.1 加载优先级（高优先覆盖低）

1. 环境变量（secrets：API Keys, Access Token）
2. YAML 配置文件（结构配置：超时、并发、URLs）
3. 代码默认值

### 8.2 `${VAR}` 展开规则

YAML 值中的 `${VAR}` 语法在加载时展开：

```python
import os, re

_EXPAND_RE = re.compile(r"\$\{(\w+)\}")

def _expand_env(value: str) -> str:
    def _replace(m: re.Match) -> str:
        var = m.group(1)
        env_val = os.environ.get(var)
        if env_val is None:
            raise ConfigError(f"Unresolved env var: ${var}")
        return env_val
    return _EXPAND_RE.sub(_replace, value)
```

- `${VAR}` 未在环境变量中定义 -> **启动失败**，报告未解析的变量名。
- 不静默替换为空字符串。

### 8.3 配置项

```yaml
# pjsk-bot.yml (结构配置，可提交模板 — 不含任何 secret)

onebot:
  # NoneBot 监听地址（NapCat 反向 WebSocket 连接到此地址）
  host: "127.0.0.1"
  port: 8080
  access_token: "${ONEBOT_ACCESS_TOKEN}"  # 必填；跨 VPS 连接必须鉴权

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
  url: "http://127.0.0.1:3000"            # 同 VPS 本地 renderer
  timeout_seconds: 30

rate_limit:
  user_cooldown_seconds: 5
  candidate_ttl_seconds: 300
  image_window_seconds: 15

admin:
  qq: "${ADMIN_QQ}"                       # 故障通知目标（必填）

cdn:
  enabled: true
  # CDN base URL — NapCat 用于下载图片的地址。
  # NapCat 在国内 VPS，必须通过反向隧道或公网 HTTPS 可达。
  # 暂定：先评估 NapCat 的其他图片发送方式，CDN 设计待 T3 细化。
  base_url: "${CDN_BASE_URL}"             # 必填，无默认值
  image_dir: "/opt/pjsk-astrbot/shared/cache/images"  # shared 目录，非 /tmp
  cleanup_ttl_seconds: 600
  max_file_size_bytes: 5242880            # 5 MiB
  url_token_ttl_seconds: 3600             # URL 有效期
```

### 8.4 启动验证

- `ONEBOT_ACCESS_TOKEN` 未定义 -> **启动失败**（跨 VPS 连接必须鉴权）。
- 所有视觉引擎 API Key 均缺失 -> **启动失败**，明确错误。
- `ADMIN_QQ` 未定义 -> **启动失败**（管理员通知是安全关键路径）。
- `cdn.enabled=true` 且 `CDN_BASE_URL` 未定义 -> **启动失败**。不得自动把用户配置的 `enabled=true` 静默改成 `false`。
- `cdn.enabled=false` -> 允许启动，图片回复始终降级为文本。
- Renderer URL 不可达 -> 降级（文本回复），不阻塞。
- 数据库路径不可写 -> 启动失败。

### 8.5 约束

- API Key 和 Access Token 不得写入日志、YAML 模板或 systemd unit。
- systemd unit 通过 `EnvironmentFile` 引用受保护的 env 文件（权限 600）。
- Redis 不可用不阻塞启动；进入 degraded 模式。

---

## 9. 旧代码复用审计

### 9.1 逐项评估

| 旧文件 | 可提取内容 | 风险 | 处置 |
|--------|-----------|------|------|
| `src/core/api.py` | `send_group_msg()`, `send_private_msg()`, `get_image_url()` 的 OneBot API 调用模式 | 低 — NoneBot 2 API 稳定 | 提取模式，重写实现：英文命名、类型标注、移除旧 throttle 依赖 |
| `src/core/connection_monitor.py` | 心跳/lifecycle 事件监听、离线检测、恢复通知模式 | 中 — 通知通道必须降级 | 提取模式，重写：英文代码、结构化日志、OneBot 不可用时回退到 journal |
| `src/features/_common.py` | `reply()`, `reply_at()`, `reply_image()` | 中 — `reply_image()` CDN 需安全审计 | `reply`/`reply_at` 模式提取到 `reply_sender.py`；`reply_image()` 见 §10 |
| `bot.py` | NoneBot 初始化模式 | 极低 | 直接参考 — 模式简单 |
| `src/core/config.py` | CDN 图片路径和清理 TTL | 低 — 纯配置 | 提取配置值，改入新 config 模型 |
| `src/core/throttle.py` | 图片/文本限流逻辑 | 中 — 耦合 Redis | 不复用 — 新 bot 用现有 `UserRateLimiter` |
| `src/features/handler_ocr.py` 及所有 `handler_*.py` | — | — | **不复用** — 全部已在 `pjsk_core` 重写 |

### 9.2 提取原则

- 读旧代码理解行为 -> 写新代码在新位置 -> 不复制旧文件。
- 新代码：英文注释/标识符、类型标注、无硬编码密钥、日志脱敏。
- 每个提取的模块编写独立测试。
- 旧仓库 `D:\\emu-bot` 保持只读。

---

## 10. CDN 图片发送安全设计

### 10.1 旧实现风险分析

旧 `reply_image()`（`_common.py:53-67`）：
- 文件名 `uuid.uuid4().hex` = 不可预测 ✅
- 路径拼接无穿越校验 ❌
- 无文件大小校验 ❌
- 无文件类型校验 ❌
- 输出 `[CQ:image,file=url]` 裸字符串 ❌（应使用 `MessageSegment.image()`）

旧 `_serve_image()`（`__init__.py:54-63`）：
- 路径穿越防护 `filename.replace(".","").isalnum()` 不充分 ❌
- 无符号链接防护 ❌
- 无 Content-Disposition 限制 ❌

### 10.2 新设计 — 回复侧

```python
import secrets
from pathlib import Path
from nonebot.adapters.onebot.v11 import MessageSegment


# Allowed image magic bytes
_ALLOWED_MAGICS: dict[bytes, str] = {
    b"\xff\xd8\xff": ".jpg",       # JPEG
    b"\x89PNG\r\n\x1a\n": ".png",  # PNG
    b"GIF87a": ".gif",             # GIF
    b"GIF89a": ".gif",             # GIF
    b"RIFF": ".webp",              # WebP (further check needed)
}


def _detect_extension(image_bytes: bytes) -> str | None:
    """Detect file extension from magic bytes. Returns None if unknown."""
    for magic, ext in _ALLOWED_MAGICS.items():
        if image_bytes.startswith(magic):
            # WebP needs extra check: "RIFF....WEBP"
            if ext == ".webp" and image_bytes[8:12] != b"WEBP":
                continue
            return ext
    return None


async def reply_image(event, image_bytes: bytes, max_bytes: int = 5 * 1024 * 1024):
    # 1. Size gate
    if len(image_bytes) > max_bytes:
        logger.warning("Image too large for CDN: %d bytes", len(image_bytes))
        await reply(event, "[图片过大，请压缩后重试]")
        return

    # 2. Magic-byte validation
    ext = _detect_extension(image_bytes)
    if ext is None:
        logger.warning("Unrecognized image format, first 16 bytes: %s",
                       image_bytes[:16].hex())
        await reply(event, "[图片格式不支持]")
        return

    # 3. Cryptographically unpredictable filename
    filename = f"{secrets.token_hex(16)}{ext}"
    filepath = IMAGE_DIR / filename

    # 4. Write with size limit (defense-in-depth)
    filepath.write_bytes(image_bytes)

    # 5. Send via MessageSegment (not raw CQ string)
    url = f"{CDN_BASE_URL}/images/{filename}"
    await reply(event, MessageSegment.image(url))
```

### 10.3 新设计 — CDN 服务侧

```python
from pathlib import Path


def _safe_image_path(filename: str, image_dir: Path) -> Path | None:
    """Resolve and validate an image path. Returns None if unsafe."""
    # Reject filenames that don't match the generated format
    if not _FILENAME_RE.match(filename):
        return None

    candidate = (image_dir / filename).resolve(strict=False)

    # Python 3.11+: is_relative_to — no prefix-collision risk
    if not candidate.is_relative_to(image_dir.resolve()):
        return None

    # Reject symlinks
    try:
        if candidate.is_symlink():
            return None
    except OSError:
        return None

    # Must be a regular file
    if not candidate.is_file():
        return None

    return candidate


@app.get("/images/{filename}")
async def _serve_image(filename: str):
    path = _safe_image_path(filename, IMAGE_DIR)
    if path is None:
        raise HTTPException(status_code=404)
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=404)
    return FileResponse(
        str(path),
        media_type="image/jpeg",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "private, max-age=3600",
        },
    )
```

**文件名格式校验**：`_FILENAME_RE = re.compile(r"[a-f0-9]{32}\\.(jpg|png|gif|webp)")`——只接受 `secrets.token_hex(16)` + 白名单扩展名。

### 10.4 CDN 可达性

NapCat 在国内 VPS，香港 VPS 的 `127.0.0.1` 不可达。`CDN_BASE_URL` 必须为：

- 反向隧道暴露的地址（例：`http://<tunnel-host>:<tunnel-port>`）— NapCat 通过此地址下载图片
- 或受保护的 HTTPS 地址（cloudflared / nginx proxy）

**实施前必须验证**：NapCat 能否从国内 VPS 通过上述地址成功 GET 图片。

### 10.5 CDN 降级

**仅当 `cdn.enabled=false` 时**图片回复降级为文本回复。`cdn.enabled=true` 但 CDN 运行时不可用（HTTP 503 等）时，单次渲染失败降级为文本，同时记录 warning——不下调全局配置。

### 10.6 CDN 生命周期独立

当前 8082 图片服务由旧 Bot（`pjsk-emu-bot.service`，端口 8082 + `/images/{filename}` 路由）提供。新设计推荐将 CDN 拆为独立服务：

```text
pjsk-cdn.service  (独立于旧 Bot 和新 Gateway)
  - FastAPI 单路由: GET /images/{filename}
  - 只服务受控图片目录
  - URL token 有效期（可选）
  - 文件名白名单 + magic-byte 校验
  - 拒绝符号链接
  - 限制文件大小
  - 定时清理
  - NapCat 跨 VPS 可达（通过反向隧道暴露或 HTTPS）
```

**优势**：Gateway 停止不必导致已生成图片立即不可访问。旧 Bot 停用时 CDN 不受影响。

如果不采用独立服务，必须在实施计划中给出同等可靠的生命周期设计和切换顺序：确保 CDN 在新旧 Bot 切换期间持续可用，不依赖任何单一 Bot 进程。

---

## 11. 数据库与旧数据迁移

### 11.1 当前状态

| 数据库 | 路径 | Schema | 记录数 |
|--------|------|--------|--------|
| 新库 | `/root/data/plugin_data/astrbot_plugin_pjsk/pjsk.db` | v6 | 7 users, 4 score_attempts |
| 旧库 | `/opt/pjsk-emu-bot/data/bot.db` | 旧 schema（6 tables） | 旧生产数据 |

### 11.2 迁移策略

**目标**：新库成为唯一生产库。旧数据迁入后，旧库保留为只读备份。

**流程**（不在此 Phase 执行，仅设计）：

```
1. 制旧库只读快照（cp --reflink 或 cp + chmod 444）
2. 审计器输出聚合统计（不输出用户级 PII）
3. 导入 users：
   - 旧 QqNumber 与新库冲突时：合并关联记录（旧 scores 归属到新 user_id），不静默丢弃
   - 无冲突时直接创建
4. 导入 songs/charts/aliases -> 与 chart_data 交叉校验
5. 旧 scores -> score_attempts（逐条转换，source_gateway="legacy_emu"）
6. 按新规则重算 personal_bests
7. 对账：用户数、成绩数、抽样 B20、难度排行
8. 影子查询（新旧两路对比，统计差异）
9. 备份新库（迁移前）
10. 最终增量迁移
11. 新库设为唯一写入源
```

**用户合并规则**：如旧库 QQ 123456 有 50 条成绩，新库 QQ 123456 已有 4 条成绩——合并：旧 50 条 `score_attempts` 归属到新 `user_id`，保留全部数据。

**约束**：
- 迁移脚本只连接只读旧库快照 + 读写新库。
- 不直接修改旧生产库。
- 迁移后旧库保留至少 30 天。
- `source_gateway` 标记：`"onebot"` (新 gateway) vs `"legacy_emu"` (旧导入)。

---

## 12. 并发模型

```
NapCat WS Event
    │
    ▼
NoneBot driver (asyncio event loop, 单线程)
    │
    ├── image_matcher    --> RecognizeScore.recognize()
    │                             ├── VisionRace (asyncio.gather, 2-3 engines)
    │                             └── ScoreRepository (aiosqlite, WAL mode)
    │
    ├── command_matcher  --> QueryB20 / QueryDifficultyRanking
    │                             └── Renderer (httpx, semaphore-gated)
    │
    └── candidate_matcher --> ConfirmCandidate
                                  └── ScoreRepository (same connection, WAL)
```

- 所有 I/O 为 async（aiosqlite、httpx、NoneBot API）。
- VisionRace 内部用 `asyncio.Semaphore` 限并发。
- Renderer 调用用 `asyncio.Semaphore` 限并发。
- SQLite WAL mode 支持并发读/单写。
- `EphemeralImageBuffer` 在单进程 asyncio 内线程安全。

---

## 13. 错误处理

| 层 | 错误 | 处理 |
|----|------|------|
| OneBot 连接断开 | WebSocket closed | NapCat 自动重连（客户端侧）；connection_monitor 记录离线时长 |
| OneBot 长时间断开 > 5min | heartbeat timeout | 写 journal + 尝试独立告警渠道（见 §14.3） |
| 图片下载失败 | HTTP error / timeout | 文本回复"图片下载失败，请重试" |
| OCR 全引擎故障 | 所有 VisionEngine 超时/熔断 | 文本回复"识别服务暂不可用" |
| OCR 无共识 | candidates available | 发送候选列表，等用户确认 |
| 候选超时 | TTL expired | 文本回复"确认已过期，请重新发送截图" |
| Renderer 故障 | HTTP error / timeout | 文本降级（纯文本排行榜/B20 列表） |
| 数据库故障 | SQLite error | 启动失败 + 明确错误日志 |
| 未知 `/emu` 命令 | 不匹配任何已知子命令 | `emu_help_fallback` -> 帮助文本 |
| 非 `/emu` 文本 | 普通聊天消息 | 无响应（passthrough）；不触发 help |

---

## 14. 日志、健康检查与告警

### 14.1 日志

```
[PJSK] gateway started, listening on 127.0.0.1:8080
[PJSK] onebot connected (NapCat reverse WS)
[PJSK] image received: type=private size=<bytes>
[PJSK] OCR started: engines=[gemini-2.5-flash, qwen3-vl-flash]
[PJSK] OCR result: consensus=STRONG engine=gemini-2.5-flash elapsed=2.3s
[PJSK] OCR disagreement: 2 candidates
[PJSK] candidate confirmed: selection=2
[PJSK] renderer: b20 rendered 180KB in 1.2s
[PJSK] renderer: fallback to text (HTTP 503)
[PJSK] onebot disconnected: reason="WebSocket closed" downtime=0s
[PJSK] onebot reconnected: downtime=45s
[PJSK] gateway shutting down...
```

**禁止记录**：QQ 号、游戏 ID、OCR 原文、图片 URL、图片内容、API Key、Access Token。**不记录 `user_hash` 或任何稳定可关联的用户标识。**

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

### 14.3 管理员告警

连接监控的故障通知有两条通道：

1. **主通道**：通过 OneBot `send_private_msg` 发送给 `ADMIN_QQ`。仅在 OneBot 连接健康时可用。
2. **降级通道**：当 OneBot 本身不可用时（连接断开 > 5min），通知**只能写入 journal**（`logger.error` 级别），并标记 `[ADMIN_ALERT]` 前缀供外部日志采集。

不尝试在 OneBot 断开时通过 OneBot 发送告警（逻辑悖论）。

---

## 15. systemd 与部署

**原子发布流程、release manifest、预检门禁、共享数据边界和回滚定义**参见 `docs/production/PRODUCTION-OPERATIONS.md` §§D–H。本节约定的 systemd unit 和 env 文件必须与 runbook 中的发布布局一致。

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
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/pjsk-astrbot/shared/data
ReadWritePaths=/opt/pjsk-astrbot/shared/cache/images
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

**`/opt/pjsk-astrbot/shared/bot.env`**（权限 600，owner `pjsk`）：

```text
ONEBOT_ACCESS_TOKEN=<secret>
GEMINI_API_KEY=<secret>
ZHIPU_API_KEY=<secret>
STEPFUN_API_KEY=<secret>
DASHSCOPE_API_KEY=<secret>
ADMIN_QQ=<secret>
CDN_BASE_URL=<secret>
```

**`PrivateTmp=yes` 与图片目录**：图片目录使用 `ReadWritePaths=/opt/pjsk-astrbot/shared/cache/images`（shared 目录下），不依赖 `/tmp`。`PrivateTmp=yes` 不影响此路径。所有图片文件在该目录下管理，权限 700，owner `pjsk`。

### 15.2 依赖关系

```
pjsk-renderer.service --> (独立 FastAPI 渲染)
pjsk-onebot.service    --> Wants=pjsk-renderer.service
                          (renderer 不可用不阻塞启动)
                          After=network.target
```

---

## 16. 影子验证

### 16.1 方案设计

不采用"同一 QQ 号双 Bot 同时回复"模式（会导致用户收到重复消息）。

**方案 A（首选）**：测试 QQ 号 + 独立 NapCat 实例
- 注册独立测试 QQ 号，配置独立的 NapCat 实例
- 新 gateway 连接此测试 NapCat -> 读写独立的测试数据库
- 零影响生产，完整功能验证（OCR、B20、排行、候选确认）

**方案 B（次选）**：真正只读的影子观测模式

影子模式通过**独立的 shadow composition root** 实现，从初始化阶段物理禁止写入：

```python
# gateway/shadow_bootstrap.py — shadow-mode assembly（仅用于验证阶段）

class ShadowWriteViolation(Exception):
    """Raised when shadow-mode code attempts a write operation."""


class FailClosedScoreRepository:
    """Score repository that refuses all writes — fail-closed, not silent."""
    async def save(self, *args, **kwargs):
        raise ShadowWriteViolation("score_attempts write in shadow mode")
    async def update_personal_best(self, *args, **kwargs):
        raise ShadowWriteViolation("personal_bests write in shadow mode")
    # read methods delegate to real repository (read-only safe)


class FailClosedOcrRunRepository:
    async def save(self, *args, **kwargs):
        raise ShadowWriteViolation("ocr_runs write in shadow mode")


class FailClosedUserRepository:
    async def create(self, *args, **kwargs):
        raise ShadowWriteViolation("user create in shadow mode")
    async def get_or_create(self, qq_number):
        # Return ephemeral User WITHOUT persisting — reads only
        return User(id=UserId(-1), qq_number=qq_number, game_id=None)
    # get_by_qq / get_by_id delegate to real repository (read-only)


class NoopCandidateStore:
    async def put(self, *args, **kwargs) -> str:
        return "shadow-cid-0000"  # ephemeral, never persisted
    async def consume_selection(self, *args, **kwargs):
        return CandidateConsumeResult(CandidateConsumeStatus.NOT_FOUND, None, None)


async def shadow_bootstrap(config: dict) -> Runtime:
    """Assemble a read-only Runtime. Real write-adapters are NEVER instantiated."""
    shadow_adapters = {
        "score_repo": FailClosedScoreRepository(real_score_repo),
        "ocr_run_repo": FailClosedOcrRunRepository(),
        "user_repo": FailClosedUserRepository(real_user_repo),
        "candidate_store": NoopCandidateStore(),
    }
    return await bootstrap(config, adapters=shadow_adapters)
```

**关键设计规则**：

- **真实写 adapter 从未被实例化**——`FailClosedScoreRepository` 在构造时接收只读 repo 用于 reads，但 write 方法无条件抛 `ShadowWriteViolation`。
- 不创建或迁移数据库（使用现有数据库的只读连接）。
- 不生成持久文件（允许明确批准的临时缓存除外）。
- **所有 shadow write 方法 fail-closed**：`raise ShadowWriteViolation`——不得"返回 success 但静默不写"，否则会掩盖错误路径。

**验证规则**（必须有测试确认）：

| # | 禁止写入项 | 测试方法 |
|---|-----------|---------|
| 1 | 不写 `ocr_runs` | 调用 `FailClosedOcrRunRepository.save()` → assert raises `ShadowWriteViolation` |
| 2 | 不写 `ocr_observations` | 同上（是 `save()` 的传入参数） |
| 3 | 不写 `score_attempts` | 调用 `FailClosedScoreRepository.save()` → assert raises `ShadowWriteViolation` |
| 4 | 不写 `personal_bests` | 调用 `update_personal_best()` → assert raises `ShadowWriteViolation` |
| 5 | 不创建 `users` | 调用 `FailClosedUserRepository.create()` → assert raises `ShadowWriteViolation` |
| 6 | 不修改候选状态 | `NoopCandidateStore.put()` 不写磁盘，`consume_selection()` 返回 NOT_FOUND |

### 16.2 影子验证与测试账号验证拆分

**Shadow E2E**（只读观测——不发送用户回复，零持久化写入）：

- 接收 OneBot 事件；
- 下载图片；
- OCR 竞速 + 校验；
- 生成候选；
- 渲染或文本摘要（发送到管理员测试通道或仅 log）；
- 零持久化写入（由 fail-closed adapters 保证）。

**Test-Account E2E**（独立测试环境——完整写入验证）：

- 独立测试 QQ 号；
- 独立 NapCat 实例；
- 独立测试数据库（全新创建或测试专用副本）；
- 完整确认入库；
- PB 更新；
- B20；
- 难度排行；
- 图片发送；
- 重启一致性。

**不得在 `NoopCandidateStore` 下要求验证"候选确认入库"**——shadow 模式物理上不支持写入。

### 16.3 验证项

| # | 测试 | 验收标准 |
|---|------|---------|
| 1 | OneBot 连接 | WebSocket connected, heartbeat 正常 |
| 2 | 私聊文本 | 无 PJSK 内容 -> 不回复，passthrough |
| 3 | 私聊图片 | 成绩截图 -> OCR 成功 -> 富文本 Echo 回复 |
| 4 | 群聊 @Bot + 图片 | 同消息 @ -> OCR 触发 |
| 5 | 先图后 @（15s 内） | buffer consume -> OCR 触发 |
| 6 | 先 @ 后图（15s 内） | arm -> consume_arm -> OCR 触发 |
| 7 | 候选确认 | 发数字 -> 确认入库 -> 确认 Echo |
| 8 | `/emu help` | 返回帮助文本 |
| 9 | `/emu status` | 返回安全运行状态 |
| 10 | `/emu b20` | 渲染图片或文本降级 |
| 11 | `/emu ma31` | 个人难度排行 |
| 12 | `/emu ma31 global` | 全局难度排行 |
| 13 | `/emu append exclude` | 切换 APPEND 设置 |
| 14 | OCR 超时 | 单引擎超时不阻塞 |
| 15 | 单引擎故障 | 其他引擎继续 |
| 16 | Renderer 故障 | 文本降级 |
| 17 | NapCat 断线重连 | NapCat 自动重连 |
| 18 | 服务重启 | 数据库一致 |
| 19 | 并发多图 | rate limit + semaphore 生效 |

---

## 17. 切换与回滚

### 17.1 切换步骤（待批准后执行）

```
1. 备份生产数据库（cp pjsk.db pjsk.db.pre-switch-$(date -I)）
2. 记录基线：Git SHA, schema_version, chart_data_version, user_count, score_count
3. 部署新代码到 /opt/pjsk-astrbot/releases/<id>/
4. 预检：全模块 import、配置校验、数据库连接测试、health endpoint
5. systemctl stop pjsk-emu-bot.service          # 暂停旧 bot
6. systemctl start pjsk-onebot.service           # 启动新 gateway
7. health check: curl /health -> status=ok
8. 执行 1 条受控测试（私聊发图 -> 确认回复和入库）
9. 核对数据库写入（新 score_attempts 行，personal_bests 更新）
10. 观察 15 分钟错误率和延迟
11. 如果正常 -> systemctl disable pjsk-emu-bot.service
12. 如果异常 -> 见回滚
```

### 17.2 回滚前提

**旧 Bot 只有完成冻结基线（`PRODUCTION-OPERATIONS.md` §I）后，才能成为服务入口回滚候选。** 在此之前，旧 Bot 仅是未经验证的应急候选，不得在回滚流程中引用。

冻结基线包含：完整文件列表 + SHA-256、Python 版本和依赖记录、静态 import 检查（确认无缺失模块）、Git↔VPS 差异清单（孤儿文件标记）、归档 tarball、隔离环境 smoke test、Legacy baseline ID。

### 17.3 回滚步骤（旧 Bot 冻结后生效）

```
1. systemctl stop pjsk-onebot.service
2. systemctl start pjsk-emu-bot.service
3. 验证旧 bot 恢复（health check）
4. 观察 5 分钟确认正常
5. 记录故障原因和时间线
```

### 17.4 回滚时的数据库处理（红线）

- **回滚入口服务时，不自动回滚数据库。**
- 新 gateway 切换期间写入的成绩**保留在新数据库中**，不作删除或回退。
- 旧 bot 恢复后继续写入**旧数据库**（`/opt/pjsk-emu-bot/data/bot.db`）——旧 bot 不认识新库 schema。
- 切换期间的增量数据（新库中的成绩）在恢复后另行评估：
  - 是否迁移回旧库；
  - 是否保留在新库等待下次切换；
  - 是否标记为"切换期"并人工审核。
- **数据库回退必须另行设计并经明确批准**，不得在回滚操作中自动执行 `cp pjsk.db.bak-* pjsk.db`（与 CLAUDE.md §15 安全红线冲突）。

### 17.5 切换期间的增量追踪

新 gateway 写入的每条记录标记 `source_gateway="onebot"`。回滚后可通过以下查询定位切换期间的增量：

```sql
SELECT COUNT(*) FROM score_attempts WHERE source_gateway = 'onebot';
```

---

## 18. 测试矩阵

| 层 | 测试类型 | 数量估算 | 说明 |
|----|---------|---------|------|
| `gateway/adapters/event_mapper.py` | 单元 | ~12 | OneBot JSON fixtures -> ImageContext / IncomingMessage |
| `gateway/adapters/reply_sender.py` | 单元 | ~8 | TextReply / ImageReply -> MessageSegment |
| `gateway/adapters/config_loader.py` | 单元 | ~8 | `${VAR}` 展开、缺失项报错、脱敏 |
| `gateway/matchers/image_handler.py` | 集成 | ~10 | 私聊/群聊图片 -> _handle_image |
| `gateway/matchers/command_handler.py` | 集成 | ~12 | 6 种子命令 + help + 未知 `/emu` + 非 `/emu` 不触发 |
| `gateway/matchers/candidate_handler.py` | 集成 | ~5 | 数字确认/过期/无效输入 |
| `gateway/connection_monitor.py` | 单元 | ~5 | 心跳超时、状态转换、通知降级 |
| `gateway/health.py` | 单元 | ~4 | ok/degraded/down 状态 |
| `gateway/bot.py` | 冒烟 | ~2 | 模块加载、adapter 注册 |
| `pjsk_runtime/bootstrap.py` | 单元 | ~8 | 配置加载、资源创建、关闭 |
| 影子 non-writing adapters | 单元 | ~6 | 6 项禁止写入验证（§16.1） |
| CDN image serving | 安全 | ~8 | 路径穿越、magic bytes、符号链接、文件名、size gate |
| 影子验证 | E2E | ~19 | 见 §16.2 |

---

## 19. 依赖清单

```
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

---

## 20. 旧代码提取候选及风险

| # | 来源 | 提取内容 | 新位置 | 风险等级 | 风险说明 |
|---|------|---------|--------|---------|---------|
| 1 | `bot.py:1-19` | NoneBot 初始化模式 | `gateway/bot.py` | 极低 | 参考模式，不复制代码 |
| 2 | `api.py:26-49` | `send_group_msg` / `send_private_msg` 模式 | `gateway/adapters/reply_sender.py` | 低 | NoneBot API 稳定；移除旧 throttle |
| 3 | `api.py:52-79` | `get_image_url` — file_id -> URL 解析 | `gateway/adapters/reply_sender.py` | 低 | NapCat 响应格式可能变化 |
| 4 | `connection_monitor.py:50-61` | 心跳 watchdog 模式 | `gateway/connection_monitor.py` | 低 | 纯 NoneBot 事件 |
| 5 | `connection_monitor.py:66-107` | 状态转换逻辑 | `gateway/connection_monitor.py` | 中 | 状态机需完整测试 |
| 6 | `connection_monitor.py:29-36` | 管理员通知（含降级） | `gateway/connection_monitor.py` | 中 | OneBot 不可用时降级到 journal |
| 7 | `_common.py:53-67` | `reply_image` CDN 模式 | `gateway/adapters/reply_sender.py` | **高** | 路径穿越、文件类型伪造、CDN 可达性 |
| 8 | `_common.py:19-28` | `is_dm` / `get_user_id` / `get_group_id` | 直接用 NoneBot 2 event 属性 | 极低 | 无需封装 |
| 9 | `config.py:31-33` | CDN 图片路径和清理 TTL | `pjsk-bot.yml` 配置模板 | 低 | 纯配置迁移 |
| 10 | `__init__.py:54-63` | `_serve_image` FastAPI 路由 | `gateway/health.py` 的图片服务部分 | **高** | 路径穿越；需完整安全加固（§10.3） |

---

> **状态：设计 v2 完成，待审查。** 批准后进入 Task 3（命令设计细化）。
