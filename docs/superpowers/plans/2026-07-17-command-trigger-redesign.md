# Command Trigger Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 私聊静默直达（发图即识别，命令无前缀），群聊 `.emu` 统一入口（先发图再命令，30s 回溯窗口）。

**Architecture:** 新增 `PendingImageStore`（进程内 TTL dict），扩展 `CommandParser` 统一解析，重写 `image_handler` 和 `command_handler` 的触发规则。OCR 编排/候选确认/渲染不变。

**Tech Stack:** Python 3.11+、pytest、pytest-asyncio、NoneBot 2

## Global Constraints

- 不改变 OCR 引擎、候选确认、渲染服务、数据库任何逻辑
- 不引入持久化依赖（PendingImageStore 进程内，重启丢失可接受）
- 私聊 OCR 只返图不返文字
- 群聊 `.emu` / `。emu` 双前缀兼容
- 候选确认纯数字 1-9 始终生效，不加前缀
- 遵循 TDD：先测试，后实现
- Ruff / Mypy strict 零新增告警

---

## 风险分析

### R1: 群聊 OCR 延迟由「发图时等待」变为「发命令时等待」

**当前**: 用户发图时 OCR 立即启动，结果在 ~6s 内返回。
**新方案**: 用户发图后 30s 内发 `.emu`，此时才启动 OCR，用户需要等 ~6s。

**影响**: 用户感知延迟增加（发 `.emu` 后要等 OCR 完成）。
**缓解**: 可以后续优化——群聊图片暂存时预启动 OCR（不返结果），`.emu` 触发时取缓存结果。首版不做。

### R2: PendingImageStore 内存占用

群聊每张图 ~200KB，100 个活跃用户 = ~20MB。30s TTL 自动回收。
**缓解**: 设置硬上限（如 500 条），超出时淘汰最旧条目。首版做。

### R3: 候选状态与图片回溯的时序竞争

用户发图 → OCR 分歧 → 返候选 → 用户选数字。此时如果用户又发 `.emu`，会触发新的 OCR，候选状态被覆盖。
**缓解**: `.emu` 触发 OCR 时，先检查是否有该用户的待处理候选。如有，忽略 `.emu`，提示「请先完成当前候选选择」。

### R4: 命令解析歧义

`b20` 和「我的ma31」和其他文本消息无前缀就触发私聊 OCR，可能误触发。
**缓解**: 命令匹配用正则严格匹配，不匹配则走旧逻辑（仅私聊发图触发 OCR）。`b20` 精确匹配（不匹配 `b200`），「我的maXX」严格 `我的ma\d+`。

### R5: 同一群内多用户并发发图

用户 A 和 B 同时发图，然后各自发 `.emu`。各自的 `.emu` 认领各自的图（key 绑定了 (group_id, qq)）。无冲突。

---

### Task 1: `PendingImageStore` — 进程内图片暂存

**Files:**
- Create: `gateway/matchers/pending_image_store.py`
- Create: `tests/gateway/test_pending_image_store.py`

**Interfaces:**
- Produces: `PendingImageStore` class with `put(group_id, qq, image_bytes)`, `pop(group_id, qq, max_age_s=30) -> bytes | None`

- [ ] **Step 1: 写测试**

```python
"""Tests for PendingImageStore."""
import time
from gateway.matchers.pending_image_store import PendingImageStore


class TestPendingImageStore:
    def test_put_and_pop(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"img1")
        assert store.pop("g1", "u1") == b"img1"

    def test_pop_removes_entry(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"img1")
        store.pop("g1", "u1")
        assert store.pop("g1", "u1") is None

    def test_pop_expired_returns_none(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"img1")
        # Fast-forward past TTL by reaching into internals
        key = ("g1", "u1")
        store._entries[key] = (store._entries[key][0], time.monotonic() - 31)
        assert store.pop("g1", "u1") is None

    def test_different_users_independent(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"img1")
        store.put("g1", "u2", b"img2")
        assert store.pop("g1", "u1") == b"img1"
        assert store.pop("g1", "u2") == b"img2"

    def test_new_image_overwrites_old(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"old")
        store.put("g1", "u1", b"new")
        assert store.pop("g1", "u1") == b"new"

    def test_hard_limit_evicts_oldest(self):
        store = PendingImageStore(max_entries=3)
        store.put("g1", "u1", b"a")
        store.put("g1", "u2", b"b")
        store.put("g1", "u3", b"c")
        store.put("g1", "u4", b"d")  # evicts oldest
        assert store.pop("g1", "u1") is None  # evicted
        assert store.pop("g1", "u4") == b"d"
```

- [ ] **Step 2: 运行确认 RED**

- [ ] **Step 3: 实现**

```python
"""Process-in-memory store for pending group images (TTL + hard cap)."""
from __future__ import annotations

import time
from typing import NamedTuple


class _Entry(NamedTuple):
    data: bytes
    timestamp: float


class PendingImageStore:
    """Stores the latest image per (group_id, qq) with a 30s TTL.

    Not persisted — data is lost on restart (acceptable).
    """

    def __init__(self, max_entries: int = 500) -> None:
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._max_entries = max_entries

    def put(self, group_id: str, qq: str, image_bytes: bytes) -> None:
        """Store (or overwrite) the latest image for this user in this group."""
        key = (group_id, qq)
        if len(self._entries) >= self._max_entries and key not in self._entries:
            # Evict the oldest entry
            oldest = min(self._entries, key=lambda k: self._entries[k].timestamp)
            del self._entries[oldest]
        self._entries[key] = _Entry(data=image_bytes, timestamp=time.monotonic())

    def pop(self, group_id: str, qq: str, max_age_s: float = 30) -> bytes | None:
        """Return and remove the latest image for this user if ≤ max_age_s.

        Returns None if no image or the image has expired.
        """
        key = (group_id, qq)
        entry = self._entries.get(key)
        if entry is None:
            return None
        del self._entries[key]
        if time.monotonic() - entry.timestamp > max_age_s:
            return None
        return entry.data
```

- [ ] **Step 4: 运行确认 GREEN**

- [ ] **Step 5: Commit**

---

### Task 2: `CommandParser` — 统一命令解析

**Files:**
- Modify: `gateway/commands.py` — 扩展 `EmuCommand` enum，新增 `parse_trigger(text, is_group) -> EmuCommand | None`
- Modify: `tests/gateway/test_commands.py` — 新增解析测试

**Interfaces:**
- Produces: `EmuCommand` enum 扩展: `B20`, `MY_DIFFICULTY(level)`, `GLOBAL_DIFFICULTY(level)`, `OCR_TRIGGER`
- Produces: `parse_trigger(text, is_group) -> EmuCommand | None`

- [ ] **Step 1: 扩写 `EmuCommand` enum**

```python
class EmuCommand(Enum):
    HELP = "help"
    STATUS = "status"
    REGISTER = "register"
    B20 = "b20"
    MY_DIFFICULTY = "my_difficulty"       # "我的ma31"
    GLOBAL_DIFFICULTY = "global_difficulty"  # "难度排行ma31"
    OCR_TRIGGER = "ocr_trigger"           # ".emu" 无参数（群聊）
```

- [ ] **Step 2: 写 `parse_trigger`**

```python
import re

_STRIP_EMU = re.compile(r"^[.。]emu\s*", re.IGNORECASE)
_B20 = re.compile(r"^(?:b20|查b20)$", re.IGNORECASE)
_MY_DIFF = re.compile(r"^我的ma(\d+)$")
_GLOBAL_DIFF = re.compile(r"^难度排行ma(\d+)$")

def parse_trigger(text: str, *, is_group: bool) -> EmuCommand | None:
    """Parse a non-image text message into a command.

    Private chat: no prefix needed for B20/difficulty commands.
    Group chat: ".emu" or "。emu" prefix required (except candidate 1-9).

    Returns None if the message does not match any command.
    """
    text = text.strip()
    if not text:
        return None

    # Group: strip ".emu"/"。emu" prefix first
    if is_group:
        text = _STRIP_EMU.sub("", text).strip()
        # ".emu" with no arguments → OCR trigger
        # But we can't distinguish here — caller passes pre-stripped text

    # B20
    if _B20.match(text):
        return EmuCommand.B20

    # 我的maXX
    m = _MY_DIFF.match(text)
    if m:
        level = int(m.group(1))
        return EmuCommand.MY_DIFFICULTY  # level stored separately

    # 难度排行maXX
    m = _GLOBAL_DIFF.match(text)
    if m:
        level = int(m.group(1))
        return EmuCommand.GLOBAL_DIFFICULTY

    # Legacy /emu commands
    if text in ("/emu register", "/emu help", "/emu status"):
        inner = text.split("/emu ")[1]
        return EmuCommand(inner)

    return None
```

- [ ] **Step 3: 写测试覆盖所有命令变体**

- [ ] **Step 4: GREEN → Commit**

---

### Task 3: 重写 `image_handler` — 私聊直接 OCR + 群聊暂存

**Files:**
- Modify: `gateway/matchers/image_handler.py`

**变更:**
- 私聊：OCR 后只返渲染图（`ImageReply`），不返文字
- 群聊：**不 OCR**，只存入 `PendingImageStore`
- 提取 `PendingImageStore` 单例供 `command_handler` 读取

- [ ] **Step 1: 修改 `_image_trigger`**

保持现有一致：私聊有图就触发，群聊 `to_me` + 图触发。

- [ ] **Step 2: 修改主处理逻辑**

```
if private:
    ocr → render → ImageReply only (no TextReply)
elif group:
    store image in PendingImageStore
    reply "截图已记录，30秒内发送 .emu 开始识别"
```

- [ ] **Step 3: 测试**

- [ ] **Step 4: Commit**

---

### Task 4: 重写 `command_handler` — `.emu` 前缀 + 私聊直发

**Files:**
- Modify: `gateway/matchers/command_handler.py`

**变更:**
- 群聊：用 `on_message`（不再 `on_command`），匹配 `.emu` / `。emu` 前缀
- 私聊：用 `on_message`，直接匹配 B20/我的maXX 等无前缀命令
- `.emu` 无参数群聊 → 读取 `PendingImageStore` → OCR → 返图
- 其他命令 → 调用对应 use case → 返图

- [ ] **Step 1: 写群聊触发规则**

```python
_EMU_PREFIX = re.compile(r"^[.。]emu(?:\s|$)")

async def _group_emu_trigger(event: MessageEvent) -> bool:
    if event.message_type != "group":
        return False
    return bool(_EMU_PREFIX.match(event.get_plaintext().strip()))
```

- [ ] **Step 2: 写私聊触发规则**

```python
async def _private_cmd_trigger(event: MessageEvent) -> bool:
    if event.message_type != "private":
        return False
    text = event.get_plaintext().strip()
    # Don't capture pure numbers (candidate selection)
    if re.match(r"^\d{1,2}$", text):
        return False
    # Don't capture plain images
    if any(seg.type == "image" for seg in event.message):
        return False  # image_handler handles this
    return parse_trigger(text, is_group=False) is not None
```

- [ ] **Step 3: 写 `.emu` OCR 触发逻辑**

```python
async def _handle_ocr_trigger(bot, event, msg):
    image = pending_store.pop(msg.group_id, msg.external_user_id)
    if image is None:
        await send_text_reply(bot, event, TextReply("未找到30秒内的截图，请先发图再 .emu"))
        return
    # Run OCR with same flow as image_handler
    ...
```

- [ ] **Step 4: 集成其他命令路由（B20/排行/register/help）**

- [ ] **Step 5: 测试全覆盖**

- [ ] **Step 6: Commit**

---

### Task 5: 集成验证 + 全量测试

- [ ] **Step 1: `pytest tests/gateway/ -v`** — 新测试全绿
- [ ] **Step 2: `pytest tests/ -k "not visual" -q`** — 全量回归零失败
- [ ] **Step 3: `ruff check gateway/ tests/`** — 零告警
- [ ] **Step 4: `mypy gateway --strict`** — 零错误

---

## 验证清单

1. 私聊发图 → OCR → 只返图
2. 私聊 `b20` → B20 图
3. 私聊 `我的ma31` → 个人难度排行图
4. 群聊发图 → "截图已记录"
5. 群聊 `.emu`（30s 内） → OCR 返图
6. 群聊 `.emu`（超时） → "未找到"
7. 群聊 `.emu b20` → B20 图
8. 群聊 `。emu b20` → B20 图
9. 候选确认 1-9 → 不变
10. `/emu register` → 不变
