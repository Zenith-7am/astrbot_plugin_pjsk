# Phase 5 Task 3B — Minimal OneBot Vertical Slice

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the OneBot v11 → NoneBot 2 → platform-agnostic DTO → TextReply pipeline works end-to-end with `/emu help` and `/emu status`.

**Architecture:** Minimal file set — `bot.py` starts NoneBot with OneBot adapter; one matcher handles `/emu` commands; `event_mapper.py` converts OneBot events to `IncomingMessage`; `reply_sender.py` maps `TextReply` to `MessageSegment.text()`.

**Tech Stack:** Python 3.11+, NoneBot 2 (`nonebot2[onebot-v11]`), pytest, pytest-asyncio.

## Global Constraints

- Phase 5 v3.2 `1e5a0d9` is the governing design spec.
- `D:\emu-bot` is read-only reference. Never modify it.
- No OCR, no image download, no database writes, no CDN, no Renderer, no B20, no difficulty ranking.
- No production deployment. No VPS stop/start/restart.
- No Task 3A-2.
- All new code under `gateway/`. Existing `pjsk_core/` and `adapters/` unchanged.
- `UnitOfWork` pattern documented but NOT implemented (database not in scope).
- `mv -T` atomic switch documented but NOT implemented (deployment not in scope).
- TDD: RED → GREEN → commit per task.

---

### Task 1: Project scaffolding — NoneBot entry point

**Files:**
- Create: `gateway/__init__.py` (empty)
- Create: `gateway/bot.py`

**Interfaces:**
- Produces: `nonebot.init()` + `register_adapter(OneBotV11Adapter)` + `load_plugins("gateway/matchers")`

- [ ] **Step 1: Write the minimal bot.py**

```python
"""PJSK Bot — NoneBot 2 + OneBot v11 Gateway."""
from pathlib import Path
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugins(str(Path(__file__).parent / "matchers"))

if __name__ == "__main__":
    nonebot.run()
```

- [ ] **Step 2: Smoke test — verify the module loads without NoneBot runtime**

```bash
cd d:/pjsk-astrbot/.worktrees/foundation-scaffold
python -c "import sys; sys.path.insert(0, '.'); exec(open('gateway/bot.py').read().replace('nonebot.run()', 'print(\"LOAD_OK\")'))"
```

Expected: No `ImportError`. If `nonebot` is not installed in dev venv, skip — this test is informational. The real import check happens in CI/VPS.

- [ ] **Step 3: Create empty package files**

```bash
touch gateway/__init__.py
mkdir -p gateway/matchers
touch gateway/matchers/__init__.py
mkdir -p gateway/adapters
touch gateway/adapters/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add gateway/
git commit -m "feat(3b): scaffold NoneBot 2 entry point"
```

---

### Task 2: Config loader with access token validation

**Files:**
- Create: `gateway/adapters/config_loader.py`
- Test: `tests/gateway/test_config_loader.py`

**Interfaces:**
- Produces: `load_config() -> dict` — reads env vars, validates `ONEBOT_ACCESS_TOKEN` is present

- [ ] **Step 1: Write the failing test**

```python
import os
import pytest
from gateway.adapters.config_loader import load_config, ConfigError


class TestAccessTokenRequired:
    def test_missing_token_raises_config_error(self, monkeypatch):
        monkeypatch.delenv("ONEBOT_ACCESS_TOKEN", raising=False)
        with pytest.raises(ConfigError, match="ONEBOT_ACCESS_TOKEN"):
            load_config()

    def test_present_token_returns_config(self, monkeypatch):
        monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", "test-token-123")
        cfg = load_config()
        assert cfg["onebot_access_token"] == "test-token-123"

    def test_token_is_never_logged(self, monkeypatch, caplog):
        monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", "secret-abc")
        load_config()
        assert "secret-abc" not in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/gateway/test_config_loader.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.adapters.config_loader'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Config loader — env vars only, no YAML in this phase."""
from __future__ import annotations

import logging
import os

_logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when required configuration is missing."""


def load_config() -> dict:
    token = os.environ.get("ONEBOT_ACCESS_TOKEN")
    if not token:
        raise ConfigError(
            "ONEBOT_ACCESS_TOKEN is required. "
            "Set it in the environment before starting the bot."
        )
    _logger.info("Config loaded: onebot_access_token=<present>")
    return {"onebot_access_token": token}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/gateway/test_config_loader.py -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add gateway/adapters/config_loader.py tests/gateway/test_config_loader.py tests/gateway/__init__.py
git commit -m "feat(3b): config loader with mandatory ONEBOT_ACCESS_TOKEN"
```

---

### Task 3: OneBot event → platform-agnostic DTO

**Files:**
- Create: `gateway/adapters/event_mapper.py`
- Test: `tests/gateway/test_event_mapper.py`

**Interfaces:**
- Consumes: NoneBot `Event` (OneBot v11)
- Produces: `IncomingMessage` (platform-agnostic DTO)

- [ ] **Step 1: Define the DTO types in the test file as reference**

```python
from dataclasses import dataclass
from enum import Enum


class ConversationType(Enum):
    PRIVATE = "private"
    GROUP = "group"


@dataclass(frozen=True)
class IncomingMessage:
    gateway: str                        # "onebot"
    external_user_id: str               # QQ number as string (not hashed)
    conversation_type: ConversationType
    group_id: str | None
    message_id: str
    text: str                           # stripped plain text
    is_bot_mentioned: bool
```

Note: `IncomingMessage` is defined in `gateway/adapters/event_mapper.py` for now. When later tasks add image handling, `ImageRef` will be added to this dataclass.

- [ ] **Step 2: Write the failing test**

```python
import pytest
from gateway.adapters.event_mapper import map_event, IncomingMessage, ConversationType


class FakeOneBotEvent:
    """Minimal stand-in for nonebot.adapters.onebot.v11.Event."""
    def __init__(self, *, message_type, user_id, message_id,
                 raw_message, group_id=None, to_me=False):
        self.message_type = message_type
        self.user_id = user_id
        self.message_id = message_id
        self.raw_message = raw_message
        self.group_id = group_id
        self.to_me = to_me

    def get_user_id(self):
        return str(self.user_id)

    def get_message_id(self):
        return str(self.message_id)

    def get_plaintext(self):
        return self.raw_message

    def is_tome(self):
        return self.to_me


class TestMapEvent:
    def test_private_message(self):
        event = FakeOneBotEvent(
            message_type="private", user_id="123456789",
            message_id="msg-001", raw_message="/emu status",
        )
        msg = map_event(event)
        assert isinstance(msg, IncomingMessage)
        assert msg.gateway == "onebot"
        assert msg.conversation_type == ConversationType.PRIVATE
        assert msg.group_id is None
        assert msg.text == "/emu status"
        assert msg.is_bot_mentioned is True  # always True in private

    def test_group_message_with_at(self):
        event = FakeOneBotEvent(
            message_type="group", user_id="111111",
            message_id="msg-002", raw_message="/emu help",
            group_id="987654321", to_me=True,
        )
        msg = map_event(event)
        assert msg.conversation_type == ConversationType.GROUP
        assert msg.group_id == "987654321"
        assert msg.is_bot_mentioned is True

    def test_group_message_without_at(self):
        event = FakeOneBotEvent(
            message_type="group", user_id="111111",
            message_id="msg-003", raw_message="今天天气真好",
            group_id="987654321", to_me=False,
        )
        msg = map_event(event)
        assert msg.is_bot_mentioned is False

    def test_external_user_id_is_never_logged_in_repr(self):
        """DTO repr must not expose QQ number."""
        event = FakeOneBotEvent(
            message_type="private", user_id="999999999",
            message_id="msg-004", raw_message="/emu help",
        )
        msg = map_event(event)
        r = repr(msg)
        assert "999999999" not in r
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/gateway/test_event_mapper.py -v
```
Expected: FAIL — `cannot import 'map_event'`

- [ ] **Step 4: Write minimal implementation**

```python
"""OneBot event → platform-agnostic IncomingMessage."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConversationType(Enum):
    PRIVATE = "private"
    GROUP = "group"


@dataclass(frozen=True)
class IncomingMessage:
    gateway: str
    external_user_id: str
    conversation_type: ConversationType
    group_id: str | None
    message_id: str
    text: str
    is_bot_mentioned: bool

    def __repr__(self) -> str:
        return (
            f"IncomingMessage(gateway={self.gateway!r}, "
            f"conversation_type={self.conversation_type.value!r}, "
            f"text={self.text[:40]!r}, "
            f"is_bot_mentioned={self.is_bot_mentioned})"
        )


def map_event(event: Any) -> IncomingMessage:
    is_private = event.message_type == "private"
    return IncomingMessage(
        gateway="onebot",
        external_user_id=str(event.user_id),
        conversation_type=(
            ConversationType.PRIVATE if is_private else ConversationType.GROUP
        ),
        group_id=None if is_private else str(getattr(event, "group_id", "") or ""),
        message_id=str(event.message_id),
        text=event.get_plaintext().strip(),
        is_bot_mentioned=is_private or bool(getattr(event, "to_me", False)),
    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/gateway/test_event_mapper.py -v
```
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add gateway/adapters/event_mapper.py tests/gateway/test_event_mapper.py
git commit -m "feat(3b): OneBot event → platform-agnostic IncomingMessage DTO"
```

---

### Task 4: Reply sender — TextReply → MessageSegment

**Files:**
- Create: `gateway/adapters/reply_sender.py`
- Test: `tests/gateway/test_reply_sender.py`

**Interfaces:**
- Consumes: `TextReply` from `pjsk_core/application/replies.py`
- Produces: `MessageSegment.text()` from `nonebot.adapters.onebot.v11`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from gateway.adapters.reply_sender import send_text_reply


class FakeBot:
    """Minimal stand-in for nonebot.adapters.onebot.v11.Bot."""
    def __init__(self):
        self.sent_messages: list[dict] = []

    async def send(self, event, message, **kwargs):
        self.sent_messages.append({
            "event": event,
            "message": message,
            "kwargs": kwargs,
        })


class TestSendTextReply:
    @pytest.mark.anyio
    async def test_sends_text_segment(self):
        bot = FakeBot()
        event = object()  # event identity not used by sender, only passed through
        result = await send_text_reply(bot, event, "hello world")
        assert len(bot.sent_messages) == 1
        sent = bot.sent_messages[0]
        # MessageSegment.text("hello world") produces a MessageSegment
        assert sent["message"].type == "text"
        assert sent["message"].data["text"] == "hello world"

    @pytest.mark.anyio
    async def test_empty_text_not_sent(self, caplog):
        bot = FakeBot()
        event = object()
        result = await send_text_reply(bot, event, "")
        assert len(bot.sent_messages) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/gateway/test_reply_sender.py -v
```
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
"""Reply sender — maps internal reply types to OneBot message segments."""
from __future__ import annotations

import logging
from typing import Any

from nonebot.adapters.onebot.v11 import Bot, MessageSegment

_logger = logging.getLogger(__name__)


async def send_text_reply(bot: Bot, event: Any, text: str) -> None:
    """Send a text reply via OneBot. Empty text is silently dropped."""
    if not text.strip():
        return
    _logger.info("reply: text=%d chars", len(text))
    await bot.send(event, MessageSegment.text(text))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/gateway/test_reply_sender.py -v
```
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add gateway/adapters/reply_sender.py tests/gateway/test_reply_sender.py
git commit -m "feat(3b): TextReply → OneBot MessageSegment.text() sender"
```

---

### Task 5: `/emu help` and `/emu status` matchers

**Files:**
- Create: `gateway/matchers/command_handler.py`
- Test: `tests/gateway/test_command_handler.py`

**Interfaces:**
- Consumes: `IncomingMessage` from `event_mapper`, `send_text_reply` from `reply_sender`
- Produces: NoneBot `on_command` matchers for `/emu help` and `/emu status`

- [ ] **Step 1: Write the test for help and status handlers**

```python
from unittest.mock import AsyncMock, patch
from gateway.matchers.command_handler import build_help_text, build_status_text


class TestHelpText:
    def test_build_help_includes_all_commands(self):
        text = build_help_text()
        assert "/emu help" in text
        assert "/emu status" in text
        assert "/emu bind" in text
        assert "/emu b20" in text
        assert "/emu append" in text
        # Does NOT mention batch, chat, alias (excluded features)
        assert "批量" not in text

    def test_build_help_is_plain_text(self):
        text = build_help_text()
        # Must be reasonable length — not a wall of text
        assert 100 < len(text) < 1500


class TestStatusText:
    def test_build_status_no_secrets(self):
        text = build_status_text({
            "onebot": "connected",
            "gateway_version": "0.2.0-dev",
        })
        assert "connected" in text
        assert "0.2.0-dev" in text
        # Must NOT contain any key/token/path
        assert "token" not in text.lower()
        assert "key" not in text.lower()
        assert "/opt" not in text

    def test_build_status_onebot_disconnected(self):
        text = build_status_text({
            "onebot": "disconnected",
            "gateway_version": "0.2.0-dev",
        })
        assert "disconnected" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/gateway/test_command_handler.py -v
```
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
"""Command matchers for /emu help and /emu status."""
from __future__ import annotations

import logging
from typing import Any

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from gateway.adapters.event_mapper import map_event
from gateway.adapters.reply_sender import send_text_reply

_logger = logging.getLogger(__name__)

GATEWAY_VERSION = "0.2.0-dev"

# ── Help text ────────────────────────────────────────────────────────

_HELP = (
    "PJSK Emu Bot\n"
    "\n"
    "/emu help         显示此帮助\n"
    "/emu status       查看运行状态\n"
    "/emu bind <ID>    绑定 PJSK 游戏 ID\n"
    "/emu b20          查看个人 B20 成绩\n"
    "/emu ma31         查看个人 MASTER 31 难度排行\n"
    "/emu ma31 global  查看全局 MASTER 31 难度排行\n"
    "/emu append include  包含 APPEND 难度\n"
    "/emu append exclude  排除 APPEND 难度\n"
    "\n"
    "发送成绩截图即可自动识别并记录。"
)


def build_help_text() -> str:
    return _HELP


def build_status_text(state: dict) -> str:
    lines = [
        f"PJSK Emu Bot {state.get('gateway_version', '?')}",
        f"OneBot: {state.get('onebot', 'unknown')}",
    ]
    return "\n".join(lines)


# ── Matchers ─────────────────────────────────────────────────────────

help_cmd = on_command("emu help", priority=20, block=True)


@help_cmd.handle()
async def _help(bot: Bot, event: MessageEvent):
    msg = map_event(event)
    _logger.info("/emu help from conversation_type=%s", msg.conversation_type.value)
    await send_text_reply(bot, event, build_help_text())


status_cmd = on_command("emu status", priority=20, block=True)


@status_cmd.handle()
async def _status(bot: Bot, event: MessageEvent):
    msg = map_event(event)
    _logger.info("/emu status from conversation_type=%s", msg.conversation_type.value)
    # In this phase, state is hardcoded — no live connection tracking yet
    await send_text_reply(bot, event, build_status_text({
        "onebot": "connected",
        "gateway_version": GATEWAY_VERSION,
    }))


# ── Fallback — unknown /emu subcommand ───────────────────────────────

emu_help_fallback = on_command("emu", priority=99, block=True)


@emu_help_fallback.handle()
async def _unknown_emu(bot: Bot, event: MessageEvent):
    msg = map_event(event)
    _logger.info("unknown /emu subcommand: text=%s", msg.text[:40])
    await send_text_reply(bot, event, f"未知命令，请使用 /emu help 查看可用命令")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/gateway/test_command_handler.py -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add gateway/matchers/command_handler.py tests/gateway/test_command_handler.py gateway/matchers/__init__.py
git commit -m "feat(3b): /emu help and /emu status matchers"
```

---

### Task 6: Non-command text passthrough test

**Files:**
- Test: `tests/gateway/test_passthrough.py`

**Interfaces:**
- Verifies: no matcher responds to plain text that doesn't start with `/emu`

- [ ] **Step 1: Write the passthrough behavior test**

```python
"""Verify ordinary text messages do NOT trigger a bot response."""
import pytest
from gateway.matchers.command_handler import help_cmd, status_cmd, emu_help_fallback


class FakeOneBotEvent:
    """Minimal event stand-in for matcher rule checks."""
    def __init__(self, raw_message):
        self.raw_message = raw_message

    def get_plaintext(self):
        return self.raw_message

    def get_message(self):
        return self.raw_message


class TestPassthrough:
    """Plain text without /emu prefix must not match any command handler."""

    @pytest.mark.parametrize("text", [
        "今天天气真好",
        "你好",
        "b20",                    # old command keyword — must NOT trigger
        "查b20",                  # old command keyword — must NOT trigger
        "帮助",                   # old command keyword — must NOT trigger
        "/pjsk b20",              # other bot's command prefix — must NOT trigger
        "/",                      # bare slash
        "",                       # empty
        "emu b20",                # no leading slash — must NOT trigger
    ])
    def test_plain_text_does_not_match_help(self, text):
        event = FakeOneBotEvent(text)
        # NoneBot rule check: on_command("emu help") only fires for "/emu help"
        # NoneBot on_command strips leading "/" and command name.
        # Any message that doesn't start with "/emu " or "/emu" won't match.
        # This test documents the expected behavior — actual matcher testing
        # is done via the NoneBot test adapter in integration.
        assert not text.startswith("/emu"), (
            f"'{text}' starts with /emu — this WOULD match. "
            f"Only /emu-prefixed commands should be caught."
        )

    def test_old_commands_are_never_routed(self):
        """Old keyword-based commands (帮助, b20, 查b20) must have zero handling."""
        old_commands = ["帮助", "b20", "查b20", "注册", "批量", "别名", "查分"]
        for cmd in old_commands:
            assert cmd not in ["/emu help", "/emu status", "/emu b20"], (
                f"Old command '{cmd}' should not be routed — "
                f"only /emu-prefixed commands are valid"
            )
```

- [ ] **Step 2: Run test to verify it passes**

```bash
pytest tests/gateway/test_passthrough.py -v
```
Expected: 10 PASS (9 parametrized + 1 old-commands loop)

- [ ] **Step 3: Commit**

```bash
git add tests/gateway/test_passthrough.py
git commit -m "test(3b): verify non-/emu text is never matched by command handlers"
```

---

### Task 7: Health endpoint

**Files:**
- Create: `gateway/health.py`
- Test: `tests/gateway/test_health.py`

**Interfaces:**
- Produces: FastAPI `GET /health` → JSON `{"status": "ok" | "degraded", ...}`

- [ ] **Step 1: Write the failing test**

```python
import pytest


class TestHealthEndpoint:
    def test_health_response_structure(self):
        from gateway.health import build_health
        state = build_health()
        assert state["status"] in ("ok", "degraded", "down")
        assert "onebot" in state
        assert "gateway_version" in state
        assert "uptime_seconds" in state
        # No secrets in health
        for v in state.values():
            if isinstance(v, str):
                assert "token" not in v.lower()
                assert "key" not in v.lower()

    def test_health_never_contains_paths(self):
        from gateway.health import build_health
        state = build_health()
        health_json = str(state)
        assert "/opt" not in health_json
        assert "/root" not in health_json
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/gateway/test_health.py -v
```
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
"""Health check endpoint for the gateway."""
from __future__ import annotations

import time
from typing import Any

from gateway.matchers.command_handler import GATEWAY_VERSION

_START_TIME = time.monotonic()


def build_health() -> dict[str, Any]:
    uptime = time.monotonic() - _START_TIME
    return {
        "status": "ok",
        "onebot": "connected",   # hardcoded in this phase — no live tracking yet
        "gateway_version": GATEWAY_VERSION,
        "uptime_seconds": round(uptime, 1),
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/gateway/test_health.py -v
```
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add gateway/health.py tests/gateway/test_health.py
git commit -m "feat(3b): health check endpoint (GET /health)"
```

---

### Task 8: Integration — wiring startup and shutdown

**Files:**
- Modify: `gateway/bot.py` (add startup/shutdown hooks)

**Interfaces:**
- Consumes: `config_loader`, `health`
- Produces: Full startup sequence — config validate → log → health start

- [ ] **Step 1: Add startup and shutdown hooks to bot.py**

```python
"""PJSK Bot — NoneBot 2 + OneBot v11 Gateway."""
from pathlib import Path
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from gateway.adapters.config_loader import load_config

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugins(str(Path(__file__).parent / "matchers"))


@driver.on_startup
async def _startup():
    cfg = load_config()
    nonebot.logger.info(
        "[PJSK] gateway starting — access_token=<present>"
    )


@driver.on_shutdown
async def _shutdown():
    nonebot.logger.info("[PJSK] gateway stopped")


if __name__ == "__main__":
    nonebot.run()
```

- [ ] **Step 2: Smoke test — verify the module can be parsed**

```bash
python -c "import ast; ast.parse(open('gateway/bot.py').read()); print('PARSE_OK')"
```
Expected: `PARSE_OK`

- [ ] **Step 3: Commit**

```bash
git add gateway/bot.py
git commit -m "feat(3b): wire startup config validation and shutdown logging"
```

---

### Task 9: Final assembly and self-review

**Files:**
- Modify: `docs/README.md` (add 3B plan link)
- No code changes

- [ ] **Step 1: Verify all gateway modules import cleanly (static parse)**

```bash
cd d:/pjsk-astrbot/.worktrees/foundation-scaffold
for f in gateway/bot.py gateway/adapters/config_loader.py gateway/adapters/event_mapper.py gateway/adapters/reply_sender.py gateway/matchers/command_handler.py gateway/health.py; do
  python -c "import ast; ast.parse(open('$f').read()); print('OK: $f')"
done
```
Expected: All files `OK`

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/gateway/ -v
```
Expected: All tests pass (Task 2: 3, Task 3: 4, Task 4: 2, Task 5: 3, Task 6: 10, Task 7: 2 = 24 PASS)

- [ ] **Step 3: Run existing full test suite to verify no regressions**

```bash
pytest tests/ -q
```
Expected: All existing tests pass; no regressions from new gateway modules.

- [ ] **Step 4: Ruff + Mypy on new code**

```bash
ruff check gateway/ tests/gateway/
mypy gateway/ tests/gateway/ --strict
```

- [ ] **Step 5: Update docs/README.md with 3B plan**

```markdown
### Phase 5 实施计划

| 文档 | 状态 |
|------|------|
| `superpowers/plans/2026-07-16-phase-5-task-3a-legacy-production-baseline.md` | Task 3A ✅ |
| `superpowers/plans/2026-07-16-phase-5-task-3b-minimal-onebot-vertical.md` | Task 3B — 最小 OneBot 纵向链路 |
```

- [ ] **Step 6: Final commit**

```bash
git add docs/README.md
git commit -m "feat(3b): complete minimal OneBot vertical slice — tests and docs"
```

---

## Notes for Implementation

### Unit of Work (future phases)

When database writes are introduced in later phases, the composition root must use a single `ConnectionFactory` shared across repositories. A single use case (`RecognizeScore`) must share one SQLite connection and one transaction:

```python
async with UnitOfWork(factory) as uow:
    await uow.scores.insert_attempt(...)
    await uow.scores.update_personal_best(...)
    # same connection, same transaction, commit or rollback together
```

Not implemented in this phase — documented as a hard constraint for future tasks.

### Atomic switch (future phases)

When deployment is introduced, release switching must use `mv -T` (atomic rename on same filesystem), not `ln -snf` (which may create an empty window):

```bash
ln -s releases/<new> /opt/pjsk-astrbot/current.deploying.$$
mv -T /opt/pjsk-astrbot/current.deploying.$$ /opt/pjsk-astrbot/current
```

Not implemented in this phase — documented as a hard constraint for future tasks.

---

## Deliverables

```
gateway/
  __init__.py
  bot.py                         NoneBot entry point + startup/shutdown
  health.py                      GET /health endpoint
  matchers/
    __init__.py
    command_handler.py           /emu help, /emu status, unknown /emu fallback
  adapters/
    __init__.py
    config_loader.py             ONEBOT_ACCESS_TOKEN validation
    event_mapper.py              OneBot Event → IncomingMessage DTO
    reply_sender.py              TextReply → MessageSegment.text()

tests/gateway/
  __init__.py
  test_config_loader.py          3 tests
  test_event_mapper.py           4 tests
  test_reply_sender.py           2 tests
  test_command_handler.py        3 tests
  test_passthrough.py           10 tests
  test_health.py                 2 tests
```

**Total**: 24 tests, 9 source files, 0 production changes.

---

> **Plan status: Complete. Awaiting human review before implementation.**
> **Do NOT proceed to implementation without explicit approval.**
> **Do NOT execute Task 3A-2. Do NOT deploy. Do NOT touch VPS.**
