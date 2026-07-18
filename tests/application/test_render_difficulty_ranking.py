"""Tests for render_difficulty_ranking."""
from datetime import datetime, timezone

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.difficulty_ranking import (
    DifficultyRankEntry,
    DifficultyRanking,
)
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus

_FAKE_CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _make_attempt(
    attempt_id: int = 1,
    status: ScoreStatus = ScoreStatus.AP,
    accuracy: float = 101.0,
    rating: float = 3300.0,
) -> ScoreAttempt:
    return ScoreAttempt(
        id=attempt_id,
        user_id=1,
        chart_id=1,
        judgements=Judgements(perfect=1200, great=0, good=0, bad=0, miss=0),
        accuracy=accuracy,
        rating=rating,
        status=status,
        image_sha256="a" * 64,
        source_gateway="test",
        ocr_run_id=None,
        created_at=_FAKE_CREATED,
    )


def _make_entry(
    song_id: int = 1,
    title: str = "Test",
    chart_id: int = 1,
    constant: str = "32.5",
    const_tag: str = "",
    level: int = 32,
    played: bool = True,
    status: ScoreStatus = ScoreStatus.AP,
    accuracy: float = 101.0,
    rating: float = 3300.0,
) -> DifficultyRankEntry:
    return DifficultyRankEntry(
        song_id=song_id,
        song_title=title,
        chart_id=chart_id,
        community_constant=constant,
        const_tag=const_tag,
        official_level=level,
        note_count=1200,
        personal_best=_make_attempt(status=status, accuracy=accuracy, rating=rating) if played else None,
        is_played=played,
    )


class FakeRenderer:
    def __init__(self, png: bytes | None = b"fake-png") -> None:
        self.png = png
        self.calls: list[object] = []

    async def render(self, payload: object) -> bytes | None:
        self.calls.append(payload)
        return self.png


class TestToRankingData:
    def test_personal_mode_title(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import _to_ranking_data

        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER,
            official_level=31,
            mode="personal",
            entries=(),
        )
        data = _to_ranking_data(ranking, {})
        assert data["title"] == "MA 31"
        assert data["mode"] == "personal"

    def test_global_mode_title(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import _to_ranking_data

        ranking = DifficultyRanking(
            difficulty=Difficulty.EXPERT,
            official_level=28,
            mode="global",
            entries=(),
        )
        data = _to_ranking_data(ranking, {})
        assert data["title"] == "EX 28"
        assert data["mode"] == "global"

    def test_tiers_grouped_by_constant(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import _to_ranking_data

        e1 = _make_entry(song_id=1, constant="32.5")
        e2 = _make_entry(song_id=2, constant="32.5")
        e3 = _make_entry(song_id=3, constant="32.0")
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e1, e2, e3),
        )
        data = _to_ranking_data(ranking, {})
        # First two share same constant → one tier with 2 songs
        assert len(data["tiers"]) == 2
        assert len(data["tiers"][0]["songs"]) == 2

    def test_unplayed_chart_status_zero(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import _to_ranking_data

        e = _make_entry(song_id=1, played=False)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _to_ranking_data(ranking, {})
        assert data["tiers"][0]["songs"][0]["status"] == 0
        assert data["tiers"][0]["songs"][0]["judges"] is None

    def test_ap_chart_status_two(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import _to_ranking_data

        e = _make_entry(song_id=1, status=ScoreStatus.AP)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _to_ranking_data(ranking, {})
        assert data["tiers"][0]["songs"][0]["status"] == 2

    def test_fc_chart_status_one(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import _to_ranking_data

        e = _make_entry(song_id=1, status=ScoreStatus.FC)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _to_ranking_data(ranking, {})
        assert data["tiers"][0]["songs"][0]["status"] == 1

    def test_clear_chart_status_zero(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import _to_ranking_data

        e = _make_entry(song_id=1, status=ScoreStatus.CLEAR, accuracy=95.0, rating=2900.0)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _to_ranking_data(ranking, {})
        assert data["tiers"][0]["songs"][0]["status"] == 0

    def test_jacket_map_applied(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import _to_ranking_data

        e = _make_entry(song_id=42)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _to_ranking_data(ranking, {42: "data:image/png;base64,abc"})
        assert data["tiers"][0]["songs"][0]["jacket"] == "data:image/png;base64,abc"


class TestRenderDifficultyRanking:
    async def test_returns_png_on_success(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import render_difficulty_ranking

        renderer = FakeRenderer(b"ranking-png")
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=31,
            mode="personal", entries=(_make_entry(),),
        )
        png = await render_difficulty_ranking(ranking, renderer=renderer, jacket_cache=None)
        assert png == b"ranking-png"
        assert renderer.calls[0].template_name == "difficulty"

    async def test_returns_none_on_renderer_failure(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import render_difficulty_ranking

        renderer = FakeRenderer(None)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=31,
            mode="personal", entries=(),
        )
        png = await render_difficulty_ranking(ranking, renderer=renderer, jacket_cache=None)
        assert png is None
