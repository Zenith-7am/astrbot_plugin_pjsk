"""Tests for pjsk_core.application.replies — unified reply types."""

from pjsk_core.application.replies import (
    CandidateReply,
    ErrorReply,
    ImageReply,
    ProgressReply,
    TextReply,
)
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.scores import Judgements

import pytest


class TestTextReply:
    def test_creation(self) -> None:
        reply = TextReply(text="Hello, world!")
        assert reply.text == "Hello, world!"

    def test_frozen(self) -> None:
        reply = TextReply(text="test")
        with pytest.raises(Exception):
            reply.text = "changed"  # type: ignore[misc]


class TestImageReply:
    def test_creation(self) -> None:
        reply = ImageReply(image_bytes=b"\x89PNG", mime_type="image/png")
        assert reply.image_bytes == b"\x89PNG"
        assert reply.mime_type == "image/png"

    def test_frozen(self) -> None:
        reply = ImageReply(image_bytes=b"", mime_type="image/jpeg")
        with pytest.raises(Exception):
            reply.mime_type = "image/png"  # type: ignore[misc]


class TestCandidateReply:
    def test_creation(self) -> None:
        obs = OcrObservation(
            song_title="Test", difficulty=Difficulty.EXPERT,
            displayed_level=25,
            judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
            engine="gemini", elapsed_ms=500,
        )
        reply = CandidateReply(
            candidate_set_id="abc-123",
            candidates=[obs],
        )
        assert reply.candidate_set_id == "abc-123"
        assert len(reply.candidates) == 1

    def test_frozen(self) -> None:
        reply = CandidateReply(candidate_set_id="x", candidates=[])
        with pytest.raises(Exception):
            reply.candidate_set_id = "y"  # type: ignore[misc]


class TestProgressReply:
    def test_creation(self) -> None:
        reply = ProgressReply(message="Processing...", current=2, total=5)
        assert reply.message == "Processing..."
        assert reply.current == 2
        assert reply.total == 5

    def test_frozen(self) -> None:
        reply = ProgressReply(message="test", current=0, total=1)
        with pytest.raises(Exception):
            reply.current = 1  # type: ignore[misc]


class TestErrorReply:
    def test_recoverable_error(self) -> None:
        reply = ErrorReply(message="Timeout, retrying...", recoverable=True)
        assert reply.message == "Timeout, retrying..."
        assert reply.recoverable is True

    def test_non_recoverable_error(self) -> None:
        reply = ErrorReply(message="Chart not found", recoverable=False)
        assert reply.recoverable is False

    def test_frozen(self) -> None:
        reply = ErrorReply(message="test", recoverable=False)
        with pytest.raises(Exception):
            reply.message = "changed"  # type: ignore[misc]
