"""Plugin-layer result DTOs — echo-ready fields from OCR recognition.

These lightweight dataclasses carry the minimal information needed
to display a score-recognition result to the user.  They are NOT
domain types — they are a plugin-level boundary that maps from the
application layer's :class:`~pjsk_core.application.recognize_score.RecognizeResult`.
"""
from __future__ import annotations

from dataclasses import dataclass

from pjsk_core.application.vision_race import VisionRaceDecision
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.scores import ScoreStatus


# ── Decision source text mapping ──────────────────────────────────────────

_DECISION_SOURCE_TEXT: dict[VisionRaceDecision, str] = {
    VisionRaceDecision.CONSENSUS: "多模型共识",
    VisionRaceDecision.DEGRADED_SINGLE: "单模型强校验降级",
    VisionRaceDecision.GLOBAL_TIMEOUT: "超时后强校验降级",
}


def decision_source_text(decision: VisionRaceDecision) -> str:
    """Return the Chinese label for a vision race decision type."""
    return _DECISION_SOURCE_TEXT.get(decision, str(decision.value))


# ── DTO ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoreEcho:
    """Minimal, safe-to-display fields from a successful score recognition.

    All fields are plain strings/numbers — no nested domain objects,
    no QQ numbers, no internal IDs.  Safe to format into chat replies.
    """

    song_title: str
    difficulty: Difficulty
    displayed_level: int
    status: ScoreStatus
    accuracy: float
    rating: float
    decision_source: str


# ── Formatting ─────────────────────────────────────────────────────────────

_STATUS_LABEL: dict[ScoreStatus, str] = {
    ScoreStatus.AP: "AP",
    ScoreStatus.FC: "FC",
    ScoreStatus.CLEAR: "CLEAR",
}

_DIFFICULTY_LABEL: dict[Difficulty, str] = {
    Difficulty.EASY: "EASY",
    Difficulty.NORMAL: "NORMAL",
    Difficulty.HARD: "HARD",
    Difficulty.EXPERT: "EXPERT",
    Difficulty.MASTER: "MASTER",
    Difficulty.APPEND: "APPEND",
}


def format_score_echo(echo: ScoreEcho) -> str:
    """Format a ScoreEcho as a one-line chat reply.

    Output format::

        已记录：歌曲名 · MASTER 31 · FC · 99.83% · Rating 33.12（多模型共识）

    The trailing parenthetical shows the decision source and is omitted
    only when the source text is empty.
    """
    diff_label = _DIFFICULTY_LABEL.get(echo.difficulty, str(echo.difficulty.name))
    status_label = _STATUS_LABEL.get(echo.status, str(echo.status.value))
    accuracy_str = f"{echo.accuracy:.2f}%"
    rating_str = f"{echo.rating:.2f}"

    base = (
        f"已记录：{echo.song_title} · "
        f"{diff_label} {echo.displayed_level} · "
        f"{status_label} · "
        f"{accuracy_str} · "
        f"Rating {rating_str}"
    )

    if echo.decision_source:
        return f"{base}（{echo.decision_source}）"
    return base
