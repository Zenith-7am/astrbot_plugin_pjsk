"""Tests for B20 render payload assembly and render_b20 wrapper."""
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


class TestB20PayloadShape:
    """Verify _build_b20_payload produces a COMPLETE dict for b20.js."""

    def test_root_has_all_fields(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(_make_result(), {})
        required = [
            "sp", "b20Avg", "fcBonus", "masterBonus",
            "playerClass", "isAppendExcluded",
            "currentPercentile", "displayRank", "b20",
        ]
        for key in required:
            assert key in payload, f"Missing root field: {key}"

    def test_song_has_all_fields(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(
            _make_result([_make_entry(status=ScoreStatus.FC, accuracy=100.5)]),
            {},
        )
        song = payload["b20"][0]
        required = [
            "jacket", "difficulty", "level", "displayLevel",
            "title", "status", "achievementRate", "power",
            "gradeLabel", "gradeClass", "judges",
        ]
        for key in required:
            assert key in song, f"Missing song field: {key}"

    def test_ap_maps_status_2_achievement_null(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(
            _make_result([_make_entry(status=ScoreStatus.AP)]),
            {},
        )
        s = payload["b20"][0]
        assert s["status"] == 2
        assert s["achievementRate"] is None

    def test_fc_maps_status_1_achievement_accuracy(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(
            _make_result([_make_entry(status=ScoreStatus.FC, accuracy=100.5)]),
            {},
        )
        s = payload["b20"][0]
        assert s["status"] == 1
        assert s["achievementRate"] == 100.5

    def test_b20_avg_from_result(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(_make_result(), {})
        assert payload["b20Avg"] == 3300.0
        assert payload["fcBonus"] == 0.0
        assert payload["masterBonus"] == 0.0

    def test_jacket_map_applied(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(
            _make_result([_make_entry(song_id=42)]),
            {42: "http://127.0.0.1:3000/jacket/42"},
        )
        assert payload["b20"][0]["jacket"] == "http://127.0.0.1:3000/jacket/42"

    def test_jacket_none_for_missing(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(
            _make_result([_make_entry(song_id=99)]),
            {},
        )
        assert payload["b20"][0]["jacket"] is None

    def test_sp_from_result(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(_make_result(), {})
        assert payload["sp"] == 3300.0

    def test_grade_label_included(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(
            _make_result([_make_entry(status=ScoreStatus.FC, accuracy=100.8)]),
            {},
        )
        assert payload["b20"][0]["gradeLabel"] == "SSS"
        assert payload["b20"][0]["gradeClass"] == "sss"

    def test_empty_entries(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(_make_result([]), {})
        assert payload["b20"] == []

    def test_append_excluded_propagated(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        payload = _build_b20_payload(_make_result(append_excluded=True), {})
        assert payload["isAppendExcluded"] is True

    def test_judges_included(self) -> None:
        from gateway.matchers.command_handler import _build_b20_payload

        entry = _make_entry()
        result = _make_result([entry])
        payload = _build_b20_payload(result, {})
        j = payload["b20"][0]["judges"]
        assert j["great"] == 0
        assert j["good"] == 0
        assert j["bad"] == 0
        assert j["miss"] == 0


class TestRenderB20:
    """Thin wrapper tests — render_b20 just POSTs the given dict."""

    async def test_returns_png_on_success(self) -> None:
        from pjsk_core.application.render_b20 import render_b20

        renderer = FakeRenderer(b"b20-png-bytes")
        png = await render_b20({"b20": [], "sp": 0.0}, renderer=renderer)
        assert png == b"b20-png-bytes"
        assert len(renderer.calls) == 1
        assert renderer.calls[0].template_name == "b20"
        assert renderer.calls[0].data == {"b20": [], "sp": 0.0}

    async def test_returns_none_on_renderer_failure(self) -> None:
        from pjsk_core.application.render_b20 import render_b20

        renderer = FakeRenderer(None)
        png = await render_b20({"b20": []}, renderer=renderer)
        assert png is None
