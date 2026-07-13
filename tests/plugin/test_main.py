"""Tests for PjskPlugin handler logic."""
import os
import tempfile
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from plugin.main import (
    _get_self_id,
    _handle_image,
    _handle_selection,
    _image_count,
    _is_at_bot,
    _is_group_chat,
)
from plugin.rate_limiter import UserRateLimiter
from plugin.reply_builder import PluginErrorCode
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import QqNumber, User, UserId


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


# ── Fake Runtime dependencies ──────────────────────────────────────────────

class _FakeUserRepo:
    """Simulates a UserRepository that returns a pre-built user."""

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        return User(id=UserId(1), qq_number=qq, game_id=None)

    async def create(self, qq: QqNumber, game_id: str | None) -> User:
        return User(id=UserId(1), qq_number=qq, game_id=game_id)


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
        code = await _handle_image(event, rt)  # type: ignore[arg-type]
        assert code == PluginErrorCode.SUCCESS

    async def test_multiple_images_rejected(self) -> None:
        """More than one image should return MULTIPLE_IMAGES."""
        rt = _FakeRuntime()
        event = FakeEvent(
            message_obj=FakeMessageObj(
                message=[Image(), Image()],
            ),
        )
        code = await _handle_image(event, rt)  # type: ignore[arg-type]
        assert code == PluginErrorCode.MULTIPLE_IMAGES


class TestHandleSelection:
    async def test_no_candidates_returns_none(self) -> None:
        """When no candidates exist, returns (False, None) — not a selection."""
        rt = _FakeRuntime()
        is_sel, err = await _handle_selection(
            "2", UserId(1), "onebot", "cs-1", rt,  # type: ignore[arg-type]
        )
        assert is_sel is False
        assert err is None


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
        from plugin.event_mapper import EventMapper
        mapper = EventMapper()
        event = FakeEvent(platform_id="qq_official", sender_id="openid-abc")
        assert mapper.is_qq_official(event) is True

    def test_onebot_event_is_not_qq_official(self) -> None:
        from plugin.event_mapper import EventMapper
        mapper = EventMapper()
        event = FakeEvent(platform_id="onebot_v11", sender_id="123456")
        assert mapper.is_qq_official(event) is False

    def test_qq_official_context_has_null_qq(self) -> None:
        """QQ Official ImageContext must have qq_number=None, not QqNumber('0')."""
        import asyncio
        from plugin.event_mapper import EventMapper
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
            ctx = asyncio.run(mapper.extract_async(event))
            assert ctx is not None
            assert ctx.qq_number is None
            assert ctx.openid == "openid-abc123"
        finally:
            os.unlink(tmp_path)
