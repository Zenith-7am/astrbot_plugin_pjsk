"""Tests for PjskPlugin handler logic."""
import os
import tempfile
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from plugin.main import _handle_image, _handle_selection, _image_count
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
class FakeMessageObj:
    message: list[Any] = field(default_factory=list)


@dataclass
class FakeEvent:
    message_obj: FakeMessageObj = field(default_factory=FakeMessageObj)
    platform_id: str = "onebot_v11"
    sender_id: str = "123456789"

    def get_platform_id(self) -> str:
        return self.platform_id

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_group_id(self) -> str | None:
        return None

    def get_message_type(self) -> str:
        return "private"


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

    def set_pending(self, uid: int, cid: str, csid: str, display: str) -> None:
        self._pending_sets[(uid, cid)] = csid
        self._pending_display[(uid, cid)] = display

    def get_pending_candidate_set_id(self, uid: int, cid: str) -> str | None:
        return self._pending_sets.get((uid, cid))

    def get_pending_display_text(self, uid: int, cid: str) -> str | None:
        return self._pending_display.get((uid, cid))

    def clear_pending(self, uid: int, cid: str) -> None:
        self._pending_sets.pop((uid, cid), None)
        self._pending_display.pop((uid, cid), None)

    _pending_sets: dict[tuple[int, str], str] = {}
    _pending_display: dict[tuple[int, str], str] = {}

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
            "2", UserId(1), "cs-1", rt,  # type: ignore[arg-type]
        )
        assert is_sel is False
        assert err is None
