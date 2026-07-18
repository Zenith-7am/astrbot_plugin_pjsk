"""Tests for difficulty ranking payload assembly and render wrapper."""
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


class TestRankingPayloadShape:
    """Verify _build_ranking_payload produces a COMPLETE dict for difficulty.js."""

    def test_personal_mode_title(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER,
            official_level=31,
            mode="personal",
            entries=(),
        )
        data = _build_ranking_payload(ranking, {})
        assert data["title"] == "MA 31"
        assert data["mode"] == "personal"

    def test_global_mode_title(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        ranking = DifficultyRanking(
            difficulty=Difficulty.EXPERT,
            official_level=28,
            mode="global",
            entries=(),
        )
        data = _build_ranking_payload(ranking, {})
        assert data["title"] == "EX 28"
        assert data["mode"] == "global"

    def test_tiers_grouped_by_constant(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        e1 = _make_entry(song_id=1, constant="32.5")
        e2 = _make_entry(song_id=2, constant="32.5")
        e3 = _make_entry(song_id=3, constant="32.0")
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e1, e2, e3),
        )
        data = _build_ranking_payload(ranking, {})
        assert len(data["tiers"]) == 2
        assert len(data["tiers"][0]["songs"]) == 2

    def test_unplayed_chart_status_zero(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        e = _make_entry(song_id=1, played=False)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _build_ranking_payload(ranking, {})
        assert data["tiers"][0]["songs"][0]["status"] == 0
        assert data["tiers"][0]["songs"][0]["judges"] is None

    def test_ap_chart_status_two(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        e = _make_entry(song_id=1, status=ScoreStatus.AP)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _build_ranking_payload(ranking, {})
        assert data["tiers"][0]["songs"][0]["status"] == 2

    def test_fc_chart_status_one(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        e = _make_entry(song_id=1, status=ScoreStatus.FC)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _build_ranking_payload(ranking, {})
        assert data["tiers"][0]["songs"][0]["status"] == 1

    def test_clear_chart_status_zero(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        e = _make_entry(song_id=1, status=ScoreStatus.CLEAR, accuracy=95.0, rating=2900.0)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _build_ranking_payload(ranking, {})
        assert data["tiers"][0]["songs"][0]["status"] == 0

    def test_jacket_map_applied(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        e = _make_entry(song_id=42)
        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(e,),
        )
        data = _build_ranking_payload(ranking, {42: "http://127.0.0.1:3000/jacket/42"})
        assert data["tiers"][0]["songs"][0]["jacket"] == "http://127.0.0.1:3000/jacket/42"

    def test_root_has_all_fields(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=31,
            mode="personal", entries=(),
        )
        data = _build_ranking_payload(ranking, {})
        for key in ("mode", "title", "tiers"):
            assert key in data, f"Missing root field: {key}"

    def test_song_has_all_fields(self) -> None:
        from gateway.matchers.command_handler import _build_ranking_payload

        ranking = DifficultyRanking(
            difficulty=Difficulty.MASTER, official_level=32,
            mode="personal", entries=(_make_entry(played=True),),
        )
        data = _build_ranking_payload(ranking, {})
        song = data["tiers"][0]["songs"][0]
        for key in ("jacket", "status", "judges", "accuracy", "power"):
            assert key in song, f"Missing song field: {key}"


class TestRenderDifficultyRanking:
    """Thin wrapper tests — render_difficulty_ranking just POSTs the given dict."""

    async def test_returns_png_on_success(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import render_difficulty_ranking

        renderer = FakeRenderer(b"ranking-png")
        png = await render_difficulty_ranking(
            {"mode": "personal", "title": "MA 31", "tiers": []},
            renderer=renderer,
        )
        assert png == b"ranking-png"
        assert renderer.calls[0].template_name == "difficulty"
        assert renderer.calls[0].data == {"mode": "personal", "title": "MA 31", "tiers": []}

    async def test_returns_none_on_renderer_failure(self) -> None:
        from pjsk_core.application.render_difficulty_ranking import render_difficulty_ranking

        renderer = FakeRenderer(None)
        png = await render_difficulty_ranking(
            {"mode": "global", "title": "EX 28", "tiers": []},
            renderer=renderer,
        )
        assert png is None
