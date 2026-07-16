"""PJSK AstrBot plugin — score screenshot OCR, B20, chart rankings.

Handler methods decorated with ``@filter`` MUST be defined in this
module because AstrBot v4 discovers handlers by scanning the plugin's
root module (``data.plugins.astrbot_plugin_pjsk.main``).  Helper
functions are imported from ``pjsk_emubot._handlers``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure the plugin directory is on sys.path so that the bundled
# ``pjsk_emubot`` and ``pjsk_core`` packages can be imported regardless
# of how AstrBot launches the plugin loader.
_plugin_root = str(Path(__file__).resolve().parent)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

# ── AstrBot imports with dev/testing fallback ──────────────────────────
try:
    from astrbot.api import logger
    from astrbot.api.event import filter, AstrMessageEvent
    from astrbot.api.star import Context, Star
except ImportError:
    # Dev/testing — AstrBot package not available.
    import logging

    class _FakeFilter:
        """Mock filter with no-op decorators for dev/testing."""

        class EventMessageType:
            ALL = "all"

        @staticmethod
        def command(name: str) -> Any:  # noqa: ARG004
            return lambda fn: fn

        @staticmethod
        def command_group(name: str) -> Any:  # noqa: ARG004
            class _FakeGroup:
                def command(self, name: str) -> Any:  # noqa: ARG004
                    return lambda fn: fn
            def _decorator(fn: Any) -> _FakeGroup:
                return _FakeGroup()
            return _decorator

        @staticmethod
        def event_message_type(etype: str) -> Any:  # noqa: ARG004
            return lambda fn: fn

    filter = _FakeFilter()
    AstrMessageEvent = object

    class _FakeEvent:
        @staticmethod
        def plain_result(text: str) -> str:
            return text

        @staticmethod
        def image_result(image_bytes: bytes) -> bytes:
            return image_bytes

        @staticmethod
        def stop_event() -> None:
            pass

    class _FakeStar:
        def __init__(self, context: Any, config: Any = None) -> None:
            self.context = context
            self.config = config

    Context = object
    Star = _FakeStar
    logger = logging.getLogger("astrbot")

from pjsk_emubot._handlers import (  # noqa: E402
    _get_image_result_text,
    _get_self_id,
    _handle_buffered_image,
    _handle_image,
    _handle_selection,
    _image_count,
    _is_at_bot,
    _is_group_chat,
    _pjsk_append,
    _pjsk_b20,
    _pjsk_difficulty,
    _read_single_image_bytes_async,
    _text_beyond_components,
)
from pjsk_emubot.event_mapper import EventMapper  # noqa: E402
from pjsk_emubot.reply_builder import PluginErrorCode  # noqa: E402
from pjsk_emubot.runtime import PluginRuntime  # noqa: E402


class PjskPlugin(Star):  # type: ignore[misc]
    """PJSK score recognition plugin for AstrBot."""

    def __init__(
        self,
        context: Context,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(context, config)
        self.config = config or {}
        self._runtime: PluginRuntime | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Called by AstrBot after plugin instantiation."""
        from pjsk_emubot.bootstrap import assemble_plugin_runtime

        logger.info("[PJSK] initialize begin")
        try:
            self._runtime = await assemble_plugin_runtime(self.config)
            logger.info(
                "[PJSK] runtime ready: recognize_score=%s",
                self._runtime.recognize_score is not None,
            )
        except Exception:
            logger.exception("[PJSK] initialize failed")
            raise

    # ── Main message handler ──────────────────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.ALL)  # type: ignore[untyped-decorator]
    async def on_message(self, event: AstrMessageEvent) -> None:  # type: ignore[misc]
        """Handle incoming messages — candidate selection, image recognition."""
        if self._runtime is None:
            return

        rt = self._runtime
        mapper = EventMapper()

        # ── 0. QQ Official early bypass ───────────────────────────────
        if mapper.is_qq_official(event):
            if _image_count(event) > 0:
                yield event.plain_result(
                    "QQ 官方入口暂未开放，请暂时使用 OneBot/NapCat"
                )
                event.stop_event()
            return

        # ── Collect event context ─────────────────────────────────────
        img_count = _image_count(event)
        group_chat = _is_group_chat(event)
        bot_id = _get_self_id(event) if group_chat else ""
        has_at = _is_at_bot(event, bot_id) if group_chat else False
        platform_id = event.get_platform_id()
        group_id = event.get_group_id() or "" if group_chat else ""
        sender_qq = mapper.extract_qq(event) if group_chat else None

        # ── Diagnostic: log component classes (remove after debug) ────
        try:
            comp_names = [c.__class__.__name__ for c in event.message_obj.message]
            logger.info(
                "[PJSK] on_message: img_count=%d group_chat=%s has_at=%s "
                "platform=%s components=%s",
                img_count, group_chat, has_at, platform_id, comp_names,
            )
        except Exception:
            logger.info("[PJSK] on_message: (unable to enumerate components)")

        # ── 2. Group chat: @Bot without image → consume buffer / arm ─
        if group_chat and has_at and img_count == 0:
            buffered = rt.image_buffer.consume(
                platform_id, group_id, sender_qq, within_seconds=15.0,
            )
            if buffered is not None:
                code, result = await _handle_buffered_image(event, rt, buffered)
                if code != PluginErrorCode.NOT_PJSK_SCREENSHOT:
                    reply_text = await _get_image_result_text(
                        event, code, rt, mapper, result,
                    )
                    yield event.plain_result(reply_text)
                    event.stop_event()
                return
            if not _text_beyond_components(event):
                rt.image_buffer.arm(platform_id, group_id, sender_qq)
                event.stop_event()
                return
            return

        # ── 3. Candidate selection (non-image messages) ───────────────
        if img_count == 0:
            try:
                text = event.message_str or ""
            except (AttributeError, TypeError):
                text = ""
            if text.strip():
                qq = mapper.extract_qq(event)
                user = await rt.user_repo.get_by_qq(qq)
                if user is not None:
                    conv_id = mapper.extract_conversation_id(event)
                    cid = rt.get_pending_candidate_set_id(
                        user.id.value, platform_id, conv_id,
                    )
                    if cid is not None:
                        is_selection, err_msg, attempt = await _handle_selection(
                            text, user.id, platform_id, conv_id, rt,
                        )
                        if is_selection:
                            if err_msg is not None:
                                yield event.plain_result(err_msg)
                            else:
                                from pjsk_emubot.result_dto import format_confirm_echo
                                yield event.plain_result(
                                    format_confirm_echo(attempt)
                                )
                            event.stop_event()
                            return
            return

        # ── 4. Private chat image handling ────────────────────────────
        if not group_chat:
            if img_count > 1:
                yield event.plain_result("目前一次只能识别一张")
                event.stop_event()
                return
            code, result = await _handle_image(event, rt)
            if code == PluginErrorCode.NOT_PJSK_SCREENSHOT:
                return
            reply_text = await _get_image_result_text(event, code, rt, mapper, result)
            yield event.plain_result(reply_text)
            event.stop_event()
            return

        # ── 5. Group chat image state machine ─────────────────────────

        # 5a. @Bot + Image same message → OCR immediately
        if has_at and img_count == 1:
            code, result = await _handle_image(event, rt)
            if code != PluginErrorCode.NOT_PJSK_SCREENSHOT:
                reply_text = await _get_image_result_text(event, code, rt, mapper, result)
                yield event.plain_result(reply_text)
                event.stop_event()
            return

        # 5b. @Bot + multiple images → reject
        if has_at and img_count > 1:
            yield event.plain_result("目前一次只能识别一张")
            event.stop_event()
            return

        # 5c. No @Bot — check arm or cache
        if not has_at and img_count >= 1:
            if img_count == 1:
                armed = rt.image_buffer.consume_arm(
                    platform_id, group_id, sender_qq, within_seconds=15.0,
                )
                if armed:
                    code, result = await _handle_image(event, rt)
                    if code != PluginErrorCode.NOT_PJSK_SCREENSHOT:
                        reply_text = await _get_image_result_text(
                            event, code, rt, mapper, result,
                        )
                        yield event.plain_result(reply_text)
                        event.stop_event()
                    return
                try:
                    image_bytes = await _read_single_image_bytes_async(
                        event, rt.http_client,
                    )
                    if image_bytes is not None:
                        rt.image_buffer.put(
                            platform_id, group_id, sender_qq, image_bytes,
                        )
                except Exception:
                    pass
            return

        return

    # ── /pjsk commands ─────────────────────────────────────────────────

    @filter.command("pjsk")  # type: ignore[untyped-decorator]
    async def pjsk_command(self, event: AstrMessageEvent) -> None:  # type: ignore[misc]
        """Handle /pjsk subcommands: b20, difficulty, append."""
        if self._runtime is None:
            return

        rt = self._runtime
        mapper = EventMapper()

        try:
            raw = event.message_str or ""
        except (AttributeError, TypeError):
            return

        text = raw.strip()
        if not text.startswith("/pjsk"):
            return

        # Extract the subcommand part: "/pjsk b20" → "b20"
        parts = text[len("/pjsk"):].strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if subcommand == "b20":
            text, image_bytes = await _pjsk_b20(rt, mapper, event)
            if image_bytes is not None:
                yield event.image_result(image_bytes)
            else:
                yield event.plain_result(text)
            event.stop_event()
            return

        if subcommand == "append":
            sub = rest.strip().lower()
            yield event.plain_result(await _pjsk_append(rt, mapper, event, sub))
            event.stop_event()
            return

        # Difficulty ranking: e.g. /pjsk ma31, /pjsk exp28 global
        import re
        m = re.match(r"^(ma|ex|apd|exp|hd|nm|ez)(\d{1,2})$", subcommand)
        if m:
            global_mode = rest.strip().lower() == "global"
            text, image_bytes = await _pjsk_difficulty(
                rt, mapper, event, m.group(1), int(m.group(2)), global_mode,
            )
            if image_bytes is not None:
                yield event.image_result(image_bytes)
            else:
                yield event.plain_result(text)
            event.stop_event()
            return

        # Unknown subcommand — passthrough to LLM
        return

    async def terminate(self) -> None:
        """Clean up plugin resources."""
        if self._runtime:
            await self._runtime.close()
            self._runtime = None
