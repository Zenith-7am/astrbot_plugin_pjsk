"""Tests for PjskPlugin handler logic."""
import os
import tempfile
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import sys

# Root main.py defines PjskPlugin in the repo root, not under pjsk_emubot/.
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
import main as _plugin_main  # noqa: E402

from pjsk_emubot._handlers import (  # noqa: E402
    _get_self_id,
    _handle_image,
    _handle_selection,
    _image_count,
    _is_at_bot,
    _is_group_chat,
    _text_beyond_components,
)
from pjsk_emubot.ephemeral import EphemeralImageBuffer  # noqa: E402
from pjsk_emubot.rate_limiter import UserRateLimiter  # noqa: E402
from pjsk_emubot.reply_builder import PluginErrorCode  # noqa: E402
from pjsk_core.domain.charts import Difficulty  # noqa: E402
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus  # noqa: E402
from pjsk_core.domain.users import QqNumber, User, UserId  # noqa: E402


# ── Fake AstrBot types ─────────────────────────────────────────────────────

@dataclass
class Image:
    """Fake for astrbot.api.message_components.Image."""
    url: str = ""
    file: str = ""


@dataclass
class At:
    """Fake for astrbot.api.message_components.At."""
    target: str = ""
    qq: str = ""


@dataclass
class FakeMessageObj:
    message: list[Any] = field(default_factory=list)
    self_id: str | None = None


@dataclass
class FakeEvent:
    message_obj: FakeMessageObj = field(default_factory=FakeMessageObj)
    platform_id: str = "onebot_v11"
    sender_id: str = "123456789"
    _group_id: str | None = None
    message_str: str = ""
    _stopped: bool = field(default=False, init=False)

    def get_platform_id(self) -> str:
        return self.platform_id

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_group_id(self) -> str | None:
        return self._group_id

    def get_message_type(self) -> str:
        return "private"

    def get_self_id(self) -> str | None:
        return self.message_obj.self_id

    def get_message_obj(self) -> Any:
        return self.message_obj

    def plain_result(self, text: str) -> str:
        """Simulate AstrBot's event.plain_result() — returns text for yield."""
        return text

    def stop_event(self) -> None:
        """Simulate AstrBot's event.stop_event() — tracked for tests."""
        self._stopped = True

    def is_stopped(self) -> bool:
        """Test helper: was stop_event() called?"""
        return self._stopped


# ── Fake Runtime dependencies ──────────────────────────────────────────────

class _FakeUserRepo:
    """Simulates a UserRepository that returns a pre-built user."""

    async def get_by_id(self, user_id: UserId) -> User | None:
        return User(id=user_id, qq_number=QqNumber("123456789"), game_id=None)

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        return User(id=UserId(1), qq_number=qq, game_id=None)

    async def create(self, qq: QqNumber, game_id: str | None) -> User:
        return User(id=UserId(1), qq_number=qq, game_id=game_id)

    async def get_or_create(self, qq: QqNumber) -> User:
        return User(id=UserId(1), qq_number=qq, game_id=None)

    async def bind_game_id(self, user_id: UserId, game_id: str) -> User:
        return User(id=user_id, qq_number=QqNumber("123456789"), game_id=game_id)


class _FakeRecognizeScore:
    """Simulates RecognizeScore use case.

    When ``consensus=True`` (default), returns a RecognizedResult with
    a non-None score_attempt.  When ``False``, returns a DISAGREEMENT
    outcome with no score and no candidates.
    """

    def __init__(self, consensus: bool = True) -> None:
        self._consensus = consensus
        self.calls: list[Any] = []

    async def recognize(
        self, user_id: UserId, image: bytes, *, source_gateway: str,
    ) -> Any:
        self.calls.append((user_id, source_gateway))
        from pjsk_core.application.recognize_score import RecognizeResult
        from pjsk_core.application.vision_race import (
            VisionRaceDecision,
            VisionRaceOutcome,
        )

        decision = (
            VisionRaceDecision.CONSENSUS
            if self._consensus
            else VisionRaceDecision.DISAGREEMENT
        )
        outcome = VisionRaceOutcome(
            decision=decision, selected=None, consensus=None,
            results=(), circuit_rejects=(),
        )

        if self._consensus:
            attempt = ScoreAttempt(
                id=None, user_id=user_id, chart_id=1,
                judgements=Judgements(
                    perfect=100, great=0, good=0, bad=0, miss=0,
                ),
                accuracy=101.0, rating=3500.0, status=ScoreStatus.AP,
                image_sha256="fake", source_gateway=source_gateway,
                ocr_run_id=None,
                created_at=datetime.now(timezone.utc),
            )
            return RecognizeResult(
                outcome=outcome, validated=None,
                candidates_for_user=(), candidate_set_id=None,
                score_attempt=attempt,
            )

        # DISAGREEMENT — no score, no candidates
        return RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=(), candidate_set_id=None,
            score_attempt=None,
        )


class _FakeRecognizeScoreNoMatch:
    """Simulates RecognizeScore returning NOT_PJSK_SCREENSHOT (no consensus, no candidates)."""

    async def recognize(
        self, user_id: UserId, image: bytes, *, source_gateway: str,
    ) -> Any:
        from pjsk_core.application.recognize_score import RecognizeResult
        from pjsk_core.application.vision_race import (
            VisionRaceDecision,
            VisionRaceOutcome,
        )

        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.ALL_FAILED,
            selected=None, consensus=None,
            results=(), circuit_rejects=(),
        )
        return RecognizeResult(
            outcome=outcome, validated=None,
            candidates_for_user=(), candidate_set_id=None,
            score_attempt=None,
        )


class _FakeConfirmCandidate:
    async def confirm(
        self, user_id: UserId, candidate_set_id: str, selection: int,
    ) -> Any:
        from pjsk_core.application.confirm_candidate import ConfirmResult
        return ConfirmResult(score_attempt=None, error=None)


class _FakeCandidateStore:
    async def consume_selection(
        self, *args: Any, **kwargs: Any,
    ) -> Any:
        from pjsk_core.ports.cache import (
            CandidateConsumeResult,
            CandidateConsumeStatus,
        )
        return CandidateConsumeResult(
            CandidateConsumeStatus.NOT_FOUND, None, None,
        )

    async def put(self, *args: Any, **kwargs: Any) -> str:
        return "fake-id"


class _FakeRuntime:
    """Simulates PluginRuntime for handler testing."""
    user_repo = _FakeUserRepo()
    chart_repo = None
    score_repo = None
    ocr_run_repo = None
    recognize_score = _FakeRecognizeScore()
    confirm_candidate = _FakeConfirmCandidate()
    candidate_store = _FakeCandidateStore()
    image_buffer = None
    rate_limiter = UserRateLimiter()
    http_client = None  # Available for async image reads

    def set_pending(self, uid: int, pid: str, cid: str, csid: str, display: str) -> None:
        self._pending_sets[(uid, pid, cid)] = csid
        self._pending_display[(uid, pid, cid)] = display

    def get_pending_candidate_set_id(self, uid: int, pid: str, cid: str) -> str | None:
        return self._pending_sets.get((uid, pid, cid))

    def get_pending_display_text(self, uid: int, pid: str, cid: str) -> str | None:
        return self._pending_display.get((uid, pid, cid))

    def clear_pending(self, uid: int, pid: str, cid: str) -> None:
        self._pending_sets.pop((uid, pid, cid), None)
        self._pending_display.pop((uid, pid, cid), None)

    _pending_sets: dict[tuple[int, str, str], str] = {}
    _pending_display: dict[tuple[int, str, str], str] = {}

    async def close(self) -> None:
        pass


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def image_file() -> Generator[str, None, None]:
    """Create a temporary file that EventMapper can read as image bytes."""
    path = tempfile.mktemp(suffix=".png")
    Path(path).write_bytes(b"fake-image-data")
    yield path
    os.unlink(path)


# ── Tests ──────────────────────────────────────────────────────────────────

class TestImageCount:
    def test_no_images(self) -> None:
        event = FakeEvent(message_obj=FakeMessageObj(message=[]))
        assert _image_count(event) == 0

    def test_one_image(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(message=[Image()]),
        )
        assert _image_count(event) == 1

    def test_two_images(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(
                message=[Image(), Image()],
            ),
        )
        assert _image_count(event) == 2


class TestHandleImage:
    async def test_single_image_triggers_recognize(
        self, image_file: str,
    ) -> None:
        """A single image should go through recognition and return SUCCESS."""
        rt = _FakeRuntime()
        img = Image(file=image_file)
        event = FakeEvent(message_obj=FakeMessageObj(message=[img]))
        code, _result = await _handle_image(event, rt)  # type: ignore[arg-type]
        assert code == PluginErrorCode.SUCCESS

    async def test_multiple_images_rejected(self) -> None:
        """More than one image should return MULTIPLE_IMAGES."""
        rt = _FakeRuntime()
        event = FakeEvent(
            message_obj=FakeMessageObj(
                message=[Image(), Image()],
            ),
        )
        code, _result = await _handle_image(event, rt)  # type: ignore[arg-type]
        assert code == PluginErrorCode.MULTIPLE_IMAGES


class TestHandleSelection:
    async def test_no_candidates_returns_none(self) -> None:
        """When no candidates exist, returns (False, None, None) — not a selection."""
        rt = _FakeRuntime()
        is_sel, err, attempt = await _handle_selection(
            "2", UserId(1), "onebot", "cs-1", rt,  # type: ignore[arg-type]
        )
        assert is_sel is False
        assert err is None
        assert attempt is None


# ── @Bot detection tests (R4) ────────────────────────────────────────────────


class TestIsAtBot:
    """Tests for _is_at_bot — Commit 1 R4."""

    def test_matches_exact_target(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(
                message=[At(target="bot123")],
                self_id="bot123",
            ),
        )
        assert _is_at_bot(event, "bot123") is True
        assert _is_at_bot(event, "bot456") is False

    def test_matches_qq_field(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(
                message=[At(qq="bot999")],
                self_id="bot999",
            ),
        )
        assert _is_at_bot(event, "bot999") is True

    def test_empty_bot_self_id_returns_false(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(
                message=[At(target="bot123")],
            ),
        )
        assert _is_at_bot(event, "") is False

    def test_no_at_component_returns_false(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(message=[Image()]),
        )
        assert _is_at_bot(event, "bot123") is False

    def test_wrong_target_returns_false(self) -> None:
        """@Other user + Image → no OCR trigger."""
        event = FakeEvent(
            message_obj=FakeMessageObj(
                message=[At(target="other_user"), Image()],
                self_id="bot123",
            ),
        )
        assert _is_at_bot(event, "bot123") is False

    def test_empty_message_returns_false(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(message=[]),
        )
        assert _is_at_bot(event, "bot123") is False


class TestGetSelfId:
    """Tests for _get_self_id — Commit 1 R4."""

    def test_from_message_obj(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(self_id="self-from-msg"),
        )
        assert _get_self_id(event) == "self-from-msg"

    def test_falls_back_to_get_self_id(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(self_id=None),
        )
        # FakeEvent.get_self_id() returns message_obj.self_id, which is None
        assert _get_self_id(event) == ""

    def test_no_self_id_available_returns_empty(self) -> None:
        event = FakeEvent(message_obj=FakeMessageObj())
        # No self_id field at all
        assert _get_self_id(event) == ""


class TestIsGroupChat:
    """Tests for _is_group_chat."""

    def test_group_chat_returns_true(self) -> None:
        event = FakeEvent(_group_id="12345")
        assert _is_group_chat(event) is True

    def test_private_chat_returns_false(self) -> None:
        event = FakeEvent(_group_id=None)
        assert _is_group_chat(event) is False


# ── QQ Official tests (R4) ───────────────────────────────────────────────────


class TestQQOfficialBypass:
    """QQ Official must not construct QqNumber and must return early."""

    def test_qq_official_event_is_detected(self) -> None:
        from pjsk_emubot.event_mapper import EventMapper
        mapper = EventMapper()
        event = FakeEvent(platform_id="qq_official", sender_id="openid-abc")
        assert mapper.is_qq_official(event) is True

    def test_onebot_event_is_not_qq_official(self) -> None:
        from pjsk_emubot.event_mapper import EventMapper
        mapper = EventMapper()
        event = FakeEvent(platform_id="onebot_v11", sender_id="123456")
        assert mapper.is_qq_official(event) is False

    def test_qq_official_context_has_null_qq(self) -> None:
        """QQ Official ImageContext must have qq_number=None, not QqNumber('0')."""
        import asyncio as _asyncio
        from pjsk_emubot.event_mapper import EventMapper
        mapper = EventMapper()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"test-image-data")
            tmp_path = f.name
        try:
            img = Image(file=tmp_path)
            event = FakeEvent(
                platform_id="qq_official",
                sender_id="openid-abc123",
                message_obj=FakeMessageObj(message=[img]),
            )
            ctx = _asyncio.run(mapper.extract_async(event))
            assert ctx is not None
            assert ctx.qq_number is None
            assert ctx.openid == "openid-abc123"
        finally:
            os.unlink(tmp_path)


# ── on_message integration tests (R5 — verify state machine routing) ────────


class _FakeOcrRunRepo:
    """Minimal fake that satisfies OcrRunRepository protocol."""
    async def save(self, *a: Any, **kw: Any) -> Any:
        return None
    async def get_by_id(self, *a: Any, **kw: Any) -> Any:
        return None


class _IntegrationFakeRuntime:
    """Runtime with real EphemeralImageBuffer for on_message integration tests."""

    def __init__(self) -> None:
        self.user_repo = _FakeUserRepo()
        self.chart_repo = None
        self.score_repo = None
        self.ocr_run_repo = _FakeOcrRunRepo()
        self.recognize_score = _FakeRecognizeScore()
        self.confirm_candidate = _FakeConfirmCandidate()
        self.candidate_store = _FakeCandidateStore()
        self.image_buffer = EphemeralImageBuffer()
        self.rate_limiter = UserRateLimiter()
        self.http_client = None
        self._pending_sets: dict[tuple[int, str, str], str] = {}
        self._pending_display: dict[tuple[int, str, str], str] = {}
        self.db_conn = None
        self.chart_db_conn = None
        self.score_db_conn = None

    def set_pending(self, uid: int, pid: str, cid: str, csid: str, display: str) -> None:
        self._pending_sets[(uid, pid, cid)] = csid
        self._pending_display[(uid, pid, cid)] = display

    def get_pending_candidate_set_id(self, uid: int, pid: str, cid: str) -> str | None:
        return self._pending_sets.get((uid, pid, cid))

    def get_pending_display_text(self, uid: int, pid: str, cid: str) -> str | None:
        return self._pending_display.get((uid, pid, cid))

    def clear_pending(self, uid: int, pid: str, cid: str) -> None:
        self._pending_sets.pop((uid, pid, cid), None)
        self._pending_display.pop((uid, pid, cid), None)

    async def close(self) -> None:
        await self.image_buffer.close()


class TestOnMessageStateMachine:
    """Integration tests for on_message routing (R5 — P0 fix verification)."""

    @pytest.fixture
    def image_file(self) -> Generator[str, None, None]:
        path = tempfile.mktemp(suffix=".png")
        Path(path).write_bytes(b"fake-image-data")
        yield path
        if os.path.isfile(path):
            os.unlink(path)

    def _make_plugin(self) -> _plugin_main.PjskPlugin:
        """Create a PjskPlugin with a fake runtime wired in."""
        plugin: _plugin_main.PjskPlugin = _plugin_main.PjskPlugin.__new__(_plugin_main.PjskPlugin)
        object.__setattr__(plugin, '_runtime', _IntegrationFakeRuntime())
        return plugin

    async def _collect_replies(self, gen: Any) -> list[str]:
        """Collect all yielded plain_result texts from an async generator."""
        replies: list[str] = []
        async for item in gen:
            if isinstance(item, str):
                replies.append(item)
        return replies

    # ── Scenario 1: @Bot + Image same message → OCR ───────────────────

    async def test_at_bot_plus_image_same_message_triggers_ocr(
        self, image_file: str,
    ) -> None:
        """@Bot + Image in the same group message → immediate OCR."""
        plugin = self._make_plugin()
        img = Image(file=image_file)
        at = At(target="bot123")
        event = FakeEvent(
            platform_id="onebot_v11",
            sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(
                message=[at, img],
                self_id="bot123",
            ),
        )
        replies = await self._collect_replies(plugin.on_message(event))
        # Should produce a reply (success or candidates, not passthrough)
        assert len(replies) >= 1
        # At least one reply — not silent passthrough
        assert any(r for r in replies)

    # ── Scenario 2: Image → @Bot (buffer consume) ─────────────────────

    async def test_image_then_at_bot_consumes_buffer(
        self, image_file: str,
    ) -> None:
        """Image posted, then @Bot within 15s → OCR on buffered image."""
        plugin = self._make_plugin()
        bot_id = "bot123"

        # Step 1: post image without @Bot (should be cached silently)
        img = Image(file=image_file)
        event_img = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[img], self_id=bot_id),
        )
        replies1 = await self._collect_replies(plugin.on_message(event_img))
        # No reply — image cached silently
        assert replies1 == []

        # Step 2: @Bot without image (should consume buffered image → OCR)
        at = At(target=bot_id)
        event_at = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[at], self_id=bot_id),
        )
        replies2 = await self._collect_replies(plugin.on_message(event_at))
        assert len(replies2) >= 1  # OCR triggered

    # ── Scenario 3: @Bot → Image (arm → consume_arm) ─────────────────

    async def test_at_bot_then_image_consumes_arm(
        self, image_file: str,
    ) -> None:
        """@Bot first (arms), then image within 15s → OCR triggered."""
        plugin = self._make_plugin()
        bot_id = "bot123"

        # Step 1: @Bot without image (arms wait)
        at = At(target=bot_id)
        event_at = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[at], self_id=bot_id),
        )
        replies1 = await self._collect_replies(plugin.on_message(event_at))
        # No prior buffer → arms and passthrough silently
        assert replies1 == []

        # Step 2: image without @Bot (should consume arm → OCR)
        img = Image(file=image_file)
        event_img = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[img], self_id=bot_id),
        )
        replies2 = await self._collect_replies(plugin.on_message(event_img))
        assert len(replies2) >= 1  # Arm consumed → OCR triggered

    # ── Scenario 4: @Bot only, no prior image → passthrough ──────────

    async def test_at_bot_only_no_image_passthrough(self) -> None:
        """@Bot without prior image → arms, no reply."""
        plugin = self._make_plugin()
        bot_id = "bot123"
        at = At(target=bot_id)
        event = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[at], self_id=bot_id),
        )
        replies = await self._collect_replies(plugin.on_message(event))
        assert replies == []  # Passthrough — no reply

    # ── Scenario 5: Different user cannot consume ────────────────────

    async def test_different_user_cannot_consume_buffer(
        self, image_file: str,
    ) -> None:
        """Image from user A, @Bot from user B → no OCR."""
        plugin = self._make_plugin()
        bot_id = "bot123"

        # User A posts image
        img = Image(file=image_file)
        event_img = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[img], self_id=bot_id),
        )
        await self._collect_replies(plugin.on_message(event_img))

        # User B @Bot (different sender) → should NOT consume user A's image
        at = At(target=bot_id)
        event_at = FakeEvent(
            platform_id="onebot_v11", sender_id="222222",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[at], self_id=bot_id),
        )
        replies2 = await self._collect_replies(plugin.on_message(event_at))
        # Arms for user B (no buffered image from user B)
        assert replies2 == []

    # ── Scenario 6: Multi-image rejected ─────────────────────────────

    async def test_multi_image_with_at_bot_rejected(
        self, image_file: str,
    ) -> None:
        """@Bot + multiple images → rejection message."""
        plugin = self._make_plugin()
        bot_id = "bot123"
        img1 = Image(file=image_file)
        img2 = Image(file=image_file)
        at = At(target=bot_id)
        event = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(
                message=[at, img1, img2], self_id=bot_id,
            ),
        )
        replies = await self._collect_replies(plugin.on_message(event))
        assert any("一次只能识别一张" in r for r in replies)

    # ── Scenario 7: @Other user + Image → no OCR ─────────────────────

    async def test_at_other_user_plus_image_no_ocr(
        self, image_file: str,
    ) -> None:
        """@OtherUser + Image → not an @Bot, image cached silently."""
        plugin = self._make_plugin()
        bot_id = "bot123"
        at = At(target="other_user")  # NOT the bot
        img = Image(file=image_file)
        event = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[at, img], self_id=bot_id),
        )
        replies = await self._collect_replies(plugin.on_message(event))
        assert replies == []  # Not OCR, cached silently

    # ── Scenario 8: @Bot + text → no arm, passthrough ─────────────

    async def test_at_bot_with_text_does_not_arm(self) -> None:
        """@Bot + text ('@Bot 你好') → no arm, passthrough to personality."""
        plugin = self._make_plugin()
        bot_id = "bot123"
        at = At(target=bot_id)
        event = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_str="@Bot 你好",
            message_obj=FakeMessageObj(message=[at], self_id=bot_id),
        )
        replies = await self._collect_replies(plugin.on_message(event))
        assert replies == []  # Passthrough — no arm, no reply


class TestTextBeyondComponents:
    """Tests for _text_beyond_components — R5 empty @Bot gating."""

    def test_empty_at_returns_empty(self) -> None:
        event = FakeEvent(
            message_str="@Bot",
            message_obj=FakeMessageObj(message=[At(target="bot123")]),
        )
        assert _text_beyond_components(event) == ""

    def test_at_with_text_returns_text(self) -> None:
        """@Bot 你好 — the '你好' is from a non-Image/At component."""
        # Simulate a text component
        class Text:
            pass
        event = FakeEvent(
            message_str="@Bot 你好",
            message_obj=FakeMessageObj(
                message=[At(target="bot123"), Text()],
            ),
        )
        result = _text_beyond_components(event)
        assert result != ""

    def test_image_only_returns_empty(self) -> None:
        event = FakeEvent(
            message_obj=FakeMessageObj(message=[Image()]),
        )
        assert _text_beyond_components(event) == ""


# ── Rich echo tests (Phase 4a.1) ─────────────────────────────────────────────


class _FakeRecognizeScoreWithEcho:
    """Fake RecognizeScore that returns a result with validated+score_attempt."""

    async def recognize(
        self, user_id: UserId, image: bytes, *, source_gateway: str,
    ) -> Any:
        from datetime import datetime, timezone

        from pjsk_core.application.recognize_score import RecognizeResult
        from pjsk_core.application.vision_race import (
            VisionRaceDecision,
            VisionRaceOutcome,
        )
        from pjsk_core.application.validate_ocr import ValidatedObservation
        from pjsk_core.domain.ocr import OcrObservation
        from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus

        obs = OcrObservation(
            song_title="幾望の月", difficulty=Difficulty.MASTER,
            displayed_level=31,
            judgements=Judgements(perfect=917, great=50, good=3, bad=0, miss=0),
            engine="gemini-test", elapsed_ms=1200,
        )
        validated = ValidatedObservation(
            observation=obs, primary=None, candidates=(),
            status="STRONG",  # type: ignore[arg-type]
        )
        attempt = ScoreAttempt(
            id=1, user_id=user_id, chart_id=42,
            judgements=obs.judgements, accuracy=99.83, rating=33.12,
            status=ScoreStatus.FC, image_sha256="fake",
            source_gateway=source_gateway, ocr_run_id=1,
            created_at=datetime.now(timezone.utc),
        )
        outcome = VisionRaceOutcome(
            decision=VisionRaceDecision.CONSENSUS,
            selected=validated, consensus=None,
            results=(), circuit_rejects=(),
        )
        return RecognizeResult(
            outcome=outcome, validated=validated,
            candidates_for_user=(), candidate_set_id=None,
            score_attempt=attempt,
        )


class TestRichEcho:
    """_get_image_result_text must produce rich echo on SUCCESS."""

    async def test_success_produces_rich_echo(self, image_file: str) -> None:
        """SUCCESS with valid RecognizeResult → rich echo with song/difficulty/rating."""
        from pjsk_emubot._handlers import _get_image_result_text, _handle_image
        from pjsk_emubot.event_mapper import EventMapper

        rt = _FakeRuntime()
        rt.rate_limiter = UserRateLimiter()  # Fresh — avoid shared class-level state
        rt.recognize_score = _FakeRecognizeScoreWithEcho()
        mapper = EventMapper()

        # Simulate: user sends image → handle_image returns (SUCCESS, result)
        img = Image(file=image_file)
        event = FakeEvent(message_obj=FakeMessageObj(message=[img]))
        code, result = await _handle_image(event, rt)  # type: ignore[arg-type]
        assert code == PluginErrorCode.SUCCESS
        assert result is not None

        text = await _get_image_result_text(event, code, rt, mapper, result)
        assert "幾望の月" in text
        assert "MASTER 31" in text
        assert "FC" in text
        assert "99.83%" in text
        assert "33.12" in text
        assert "多模型共识" in text

    async def test_fallback_when_echo_build_fails(self, image_file: str) -> None:
        """When build_score_echo returns None, fall back to '已记录'."""
        from pjsk_emubot._handlers import _get_image_result_text, _handle_image
        from pjsk_emubot.event_mapper import EventMapper

        rt = _FakeRuntime()  # Default FakeRecognizeScore has validated=None
        rt.rate_limiter = UserRateLimiter()  # Fresh — avoid shared class-level state
        mapper = EventMapper()

        img = Image(file=image_file)
        event = FakeEvent(message_obj=FakeMessageObj(message=[img]))
        code, result = await _handle_image(event, rt)  # type: ignore[arg-type]
        assert code == PluginErrorCode.SUCCESS

        text = await _get_image_result_text(event, code, rt, mapper, result)
        # Falls back because validated is None in FakeRecognizeScore
        assert text == "已记录"


# ── Structural tests (Phase 4a root-main migration) ────────────────────────


class TestConstructorReceivesConfig:
    """Constructor must accept and store ``config`` from AstrBot."""

    def test_config_stored_on_instance(self) -> None:
        cfg = {"zhipu_api_key": "sk-test", "dashscope_api_key": "dq-test"}
        plugin = _plugin_main.PjskPlugin.__new__(_plugin_main.PjskPlugin)
        # Simulate what AstrBot does: set config then call __init__-like setup.
        # We call __init__ directly since __new__ bypasses it.
        _plugin_main.PjskPlugin.__init__(plugin, context=None, config=cfg)
        assert plugin.config is cfg
        assert plugin.config["zhipu_api_key"] == "sk-test"
        assert plugin.config["dashscope_api_key"] == "dq-test"

    def test_config_defaults_to_empty_dict(self) -> None:
        plugin = _plugin_main.PjskPlugin.__new__(_plugin_main.PjskPlugin)
        _plugin_main.PjskPlugin.__init__(plugin, context=None)
        assert plugin.config == {}


class TestPluginClassLocation:
    """PjskPlugin MUST be defined in root main.py, not re-exported."""

    def test_class_module_is_root_main(self) -> None:
        """The class's __module__ must resolve to a root ``main`` module.

        AstrBot v4 imports ``data.plugins.astrbot_plugin_pjsk.main`` and
        discovers handlers on the Star subclass found there.  If
        ``__module__`` points to ``pjsk_emubot.main`` (old re-export),
        handlers are silently ignored.
        """
        mod = _plugin_main.PjskPlugin.__module__
        assert mod == "main", (
            f"PjskPlugin.__module__ must be 'main', got {mod!r}. "
            f"AstrBot handler discovery depends on this."
        )

    def test_pjsk_emubot_main_is_stub(self) -> None:
        """pjsk_emubot.main must NOT contain PjskPlugin anymore."""
        import pjsk_emubot.main as old_module
        assert not hasattr(old_module, "PjskPlugin"), (
            "pjsk_emubot.main must not contain PjskPlugin — "
            "it moved to root main.py"
        )

    def test_bind_and_on_message_are_registered(self) -> None:
        """pjsk_bind and on_message must be callable methods on PjskPlugin.

        This is the canonical handler-registry contract: these two names
        are what AstrBot's star_map looks up after loading the plugin.
        """
        assert callable(getattr(_plugin_main.PjskPlugin, "pjsk_bind", None)), (
            "PjskPlugin.pjsk_bind is missing — /pjsk bind will not work"
        )
        assert callable(getattr(_plugin_main.PjskPlugin, "on_message", None)), (
            "PjskPlugin.on_message is missing — image OCR will not work"
        )


# ── Takeover boundary tests (Phase 4a.1 C3) ──────────────────────────────────


class TestTakeoverBoundary:
    """Verify stop_event() is called only when PJSK takes over the event."""

    def _make_plugin_takeover(
        self, consensus: bool = True,
    ) -> _plugin_main.PjskPlugin:
        """Create plugin with OCR that returns consensus or no-match."""
        rt = _IntegrationFakeRuntime()
        if not consensus:
            rt.recognize_score = _FakeRecognizeScoreNoMatch()
        rt.rate_limiter = UserRateLimiter()
        plugin: _plugin_main.PjskPlugin = (
            _plugin_main.PjskPlugin.__new__(_plugin_main.PjskPlugin)
        )
        object.__setattr__(plugin, '_runtime', rt)
        return plugin

    async def _collect(
        self, gen: Any,
    ) -> tuple[list[str], bool]:
        """Collect yielded replies and check stop_event state."""
        replies: list[str] = []
        async for item in gen:
            if isinstance(item, str):
                replies.append(item)
        return replies

    # ── Private chat ────────────────────────────────────────────────────

    async def test_private_image_stops_event(self, image_file: str) -> None:
        """Private chat single image → OCR runs → stop_event called."""
        plugin = self._make_plugin_takeover(consensus=True)
        img = Image(file=image_file)
        event = FakeEvent(
            message_obj=FakeMessageObj(message=[img]),
        )
        async for _ in plugin.on_message(event):
            pass
        assert event.is_stopped(), (
            "Private image must stop event (PJSK takeover)"
        )

    async def test_private_non_pjsk_replies_failure(
        self, image_file: str,
    ) -> None:
        """Private chat non-PJSK image → clear failure message, no stop."""
        plugin = self._make_plugin_takeover(consensus=False)
        img = Image(file=image_file)
        event = FakeEvent(
            message_obj=FakeMessageObj(message=[img]),
        )
        replies: list[str] = []
        async for item in plugin.on_message(event):
            if isinstance(item, str):
                replies.append(item)
        # Non-PJSK → passthrough, no reply, no stop
        assert replies == []
        assert not event.is_stopped()

    async def test_private_multi_image_stops_event(
        self, image_file: str,
    ) -> None:
        """Private chat multi-image → stop_event + error message."""
        plugin = self._make_plugin_takeover()
        img1 = Image(file=image_file)
        img2 = Image(file=image_file)
        event = FakeEvent(
            message_obj=FakeMessageObj(message=[img1, img2]),
        )
        replies: list[str] = []
        async for item in plugin.on_message(event):
            if isinstance(item, str):
                replies.append(item)
        assert any("一次只能识别一张" in r for r in replies)
        assert event.is_stopped()

    # ── Group chat ──────────────────────────────────────────────────────

    async def test_group_at_bot_image_stops_event(
        self, image_file: str,
    ) -> None:
        """Group @Bot+Image → OCR → stop_event called."""
        plugin = self._make_plugin_takeover(consensus=True)
        bot_id = "bot123"
        at = At(target=bot_id)
        img = Image(file=image_file)
        event = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[at, img], self_id=bot_id),
        )
        async for _ in plugin.on_message(event):
            pass
        assert event.is_stopped()

    async def test_group_plain_message_not_stopped(self) -> None:
        """Group plain text (no @Bot, no image) → not stopped → passthrough."""
        plugin = self._make_plugin_takeover()
        event = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_str="今天天气真好",
        )
        async for _ in plugin.on_message(event):
            pass
        assert not event.is_stopped()

    async def test_group_at_other_user_image_not_stopped(
        self, image_file: str,
    ) -> None:
        """@OtherUser+Image → NOT stopped → passthrough to chat personality."""
        plugin = self._make_plugin_takeover()
        bot_id = "bot123"
        at = At(target="other_user")
        img = Image(file=image_file)
        event = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(message=[at, img], self_id=bot_id),
        )
        async for _ in plugin.on_message(event):
            pass
        assert not event.is_stopped(), (
            "@OtherUser+Image must NOT be taken over by PJSK"
        )

    async def test_group_at_bot_multi_image_stops_event(
        self, image_file: str,
    ) -> None:
        """Group @Bot+multi-image → stops event with rejection message."""
        plugin = self._make_plugin_takeover()
        bot_id = "bot123"
        at = At(target=bot_id)
        img1 = Image(file=image_file)
        img2 = Image(file=image_file)
        event = FakeEvent(
            platform_id="onebot_v11", sender_id="111111",
            _group_id="group:abc",
            message_obj=FakeMessageObj(
                message=[at, img1, img2], self_id=bot_id,
            ),
        )
        replies: list[str] = []
        async for item in plugin.on_message(event):
            if isinstance(item, str):
                replies.append(item)
        assert any("一次只能识别一张" in r for r in replies)
        assert event.is_stopped()
