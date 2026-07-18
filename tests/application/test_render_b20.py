"""Tests for render_b20."""
from pjsk_core.domain.b20 import B20Entry, B20Result
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.player_class import PlayerClass
from pjsk_core.domain.scores import Judgements, ScoreStatus

_FAKE_PLAYER_CLASS = PlayerClass(name="Master", icon="★3", stars=3, fallback_color="purple")


def _make_entry(
    rank: int = 1,
    song_id: int = 1,
    title: str = "Test Song",
    difficulty: str = "master",
    level: int = 32,
    constant: str = "32.5",
    status: ScoreStatus = ScoreStatus.AP,
    accuracy: float = 101.0,
    rating: float = 3300.0,
) -> B20Entry:
    return B20Entry(
        rank=rank,
        song_id=song_id,
        song_title=title,
        difficulty=Difficulty(difficulty),
        official_level=level,
        community_constant=constant,
        status=status,
        accuracy=accuracy,
        rating=rating,
        judgements=Judgements(perfect=1200, great=0, good=0, bad=0, miss=0),
    )


def _make_result(entries: list[B20Entry] | None = None, append_excluded: bool = False) -> B20Result:
    if entries is None:
        entries = [_make_entry()]
    e = tuple(entries)
    return B20Result(
        entries=e,
        sp=3300.0,
        player_class=_FAKE_PLAYER_CLASS,
        b20_avg=3300.0,
        fc_bonus=0.0,
        ap_bonus=0.0,
        append_excluded=append_excluded,
        chart_data_version="2026-07-12",
    )


class FakeRenderer:
    def __init__(self, png: bytes | None = b"fake-png") -> None:
        self.png = png
        self.calls: list[object] = []

    async def render(self, payload: object) -> bytes | None:
        self.calls.append(payload)
        return self.png


class TestToB20Data:
    def test_ap_maps_status_2_achievement_null(self) -> None:
        from pjsk_core.application.render_b20 import _to_b20_data

        result = _make_result([_make_entry(status=ScoreStatus.AP)])
        data = _to_b20_data(result, {})

        assert data["b20"][0]["status"] == 2
        assert data["b20"][0]["achievementRate"] is None

    def test_fc_maps_status_1_achievement_accuracy(self) -> None:
        from pjsk_core.application.render_b20 import _to_b20_data

        result = _make_result([_make_entry(status=ScoreStatus.FC, accuracy=100.5)])
        data = _to_b20_data(result, {})

        assert data["b20"][0]["status"] == 1
        assert data["b20"][0]["achievementRate"] == 100.5

    def test_append_excluded_propagated(self) -> None:
        from pjsk_core.application.render_b20 import _to_b20_data

        result = _make_result(append_excluded=True)
        data = _to_b20_data(result, {})

        assert data["isAppendExcluded"] is True

    def test_judges_included(self) -> None:
        from pjsk_core.application.render_b20 import _to_b20_data

        entry = _make_entry()
        result = _make_result([entry])
        data = _to_b20_data(result, {})

        j = data["b20"][0]["judges"]
        assert j["great"] == 0
        assert j["good"] == 0
        assert j["bad"] == 0
        assert j["miss"] == 0

    def test_jacket_map_applied(self) -> None:
        from pjsk_core.application.render_b20 import _to_b20_data

        result = _make_result([_make_entry(song_id=42)])
        data = _to_b20_data(result, {42: "data:image/png;base64,abc"})

        assert data["b20"][0]["jacket"] == "data:image/png;base64,abc"

    def test_jacket_none_for_missing(self) -> None:
        from pjsk_core.application.render_b20 import _to_b20_data

        result = _make_result([_make_entry(song_id=99)])
        data = _to_b20_data(result, {})

        assert data["b20"][0]["jacket"] is None

    def test_empty_entries(self) -> None:
        from pjsk_core.application.render_b20 import _to_b20_data

        result = _make_result([])
        data = _to_b20_data(result, {})

        assert data["b20"] == []


class TestRenderB20:
    async def test_returns_png_on_success(self) -> None:
        from pjsk_core.application.render_b20 import render_b20

        renderer = FakeRenderer(b"b20-png-bytes")
        result = _make_result()

        png = await render_b20(result, renderer=renderer, jacket_cache=None)
        assert png == b"b20-png-bytes"
        assert len(renderer.calls) == 1
        assert renderer.calls[0].template_name == "b20"

    async def test_returns_none_on_renderer_failure(self) -> None:
        from pjsk_core.application.render_b20 import render_b20

        renderer = FakeRenderer(None)
        result = _make_result()

        png = await render_b20(result, renderer=renderer, jacket_cache=None)
        assert png is None
