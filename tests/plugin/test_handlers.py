"""Tests for handler helpers — render payload builders + jacket wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from pjsk_emubot._handlers import (
    _b20_render_payload,
    _difficulty_render_payload,
    _pjsk_b20,
    _pjsk_difficulty,
    _unique_song_ids_from_entries,
)
from pjsk_emubot.runtime import PluginRuntime
from pjsk_core.domain.charts import Difficulty
from pjsk_core.ports.renderer import RenderPayload


# ── Dummy domain objects for tests ──────────────────────────────────────


class _FakeB20Entry:
    def __init__(self, rank: int, song_id: int, title: str, const: str,
                 level: int, status_val: str, accuracy: float, rating: float):
        self.rank = rank
        self.song_id = song_id
        self.song_title = title
        self.community_constant = const
        self.official_level = level
        self.accuracy = accuracy
        self.rating = rating
        from pjsk_core.domain.charts import Difficulty as D
        self.difficulty = D.MASTER
        from pjsk_core.domain.scores import ScoreStatus
        self.status = ScoreStatus(status_val)
        from pjsk_core.domain.scores import Judgements
        self.judgements = Judgements(perfect=1000, great=10, good=0, bad=0, miss=0)


class _FakeB20Result:
    def __init__(self, entries: list[_FakeB20Entry]):
        self.entries = tuple(entries)
        self.sp = 34567.89
        self.b20_avg = 34000.0
        self.fc_bonus = 0.0
        self.ap_bonus = 0.0
        self.append_excluded = True
        from pjsk_core.domain.player_class import PlayerClass
        self.player_class = PlayerClass(
            name="Diamond", icon="💎", stars=3, fallback_color="blue",
        )


class _FakeRankEntry:
    def __init__(self, song_id: int, title: str, const: str, is_played: bool,
                 status_val: str | None = None, accuracy: float = 0.0,
                 rating: float = 0.0):
        self.song_id = song_id
        self.song_title = title
        self.community_constant = const
        self.note_count = 1000
        self.chart_id = song_id * 10
        self.is_played = is_played
        from pjsk_core.domain.scores import ScoreStatus
        self.status: Any = ScoreStatus(status_val) if (is_played and status_val) else None
        self.accuracy = accuracy
        self.rating = rating
        self.personal_best = None if not is_played else MagicMock()


class _FakeRanking:
    def __init__(self, entries: list[_FakeRankEntry]):
        self.entries = tuple(entries)
        self.played_count = sum(1 for e in entries if e.is_played)
        self.total_count = len(entries)


# ── Unit: _unique_song_ids_from_entries ─────────────────────────────────


class TestUniqueSongIds:
    def test_dedup_duplicates(self) -> None:
        """Same song_id appearing multiple times → returned once."""
        entries = [_FakeB20Entry(i, 1, "", "", 31, "fc", 99.0, 30.0) for i in range(5)]
        result = _unique_song_ids_from_entries(entries)
        assert result == [1]

    def test_preserves_first_occurrence_order(self) -> None:
        """Ids are returned in first-seen order."""
        entries = [
            _FakeB20Entry(1, 10, "", "", 31, "fc", 99.0, 30.0),
            _FakeB20Entry(2, 5, "", "", 31, "fc", 99.0, 30.0),
            _FakeB20Entry(3, 10, "", "", 31, "ap", 101.0, 35.0),
            _FakeB20Entry(4, 7, "", "", 31, "fc", 99.0, 30.0),
        ]
        result = _unique_song_ids_from_entries(entries)
        assert result == [10, 5, 7]

    def test_empty_list(self) -> None:
        assert _unique_song_ids_from_entries([]) == []


# ── Unit: _b20_render_payload ───────────────────────────────────────────


class TestB20RenderPayload:
    def test_jacket_injected_when_available(self) -> None:
        """Jacket data URL from prefetch is placed in payload entry."""
        entries = [_FakeB20Entry(1, 42, "幾望の月", "32.5+", 32, "fc", 99.83, 33.12)]
        result = _FakeB20Result(entries)
        jackets = {42: "data:image/webp;base64,Zm9v"}

        payload = _b20_render_payload(result, jackets)
        assert payload["b20"][0]["jacket"] == "data:image/webp;base64,Zm9v"

    def test_jacket_null_when_not_prefetched(self) -> None:
        """Song not in jackets dict → jacket is None."""
        entries = [_FakeB20Entry(1, 42, "", "", 31, "fc", 99.0, 30.0)]
        result = _FakeB20Result(entries)

        payload = _b20_render_payload(result, {})
        assert payload["b20"][0]["jacket"] is None

    def test_jacket_null_when_jackets_is_none(self) -> None:
        """jackets=None (no cache) → all jackets are None."""
        entries = [_FakeB20Entry(1, 42, "", "", 31, "fc", 99.0, 30.0)]
        result = _FakeB20Result(entries)

        payload = _b20_render_payload(result, None)
        assert payload["b20"][0]["jacket"] is None

    def test_partial_prefetch_some_null(self) -> None:
        """One jacket available, another failed → mixed null/url."""
        e1 = _FakeB20Entry(1, 1, "", "", 31, "fc", 99.0, 30.0)
        e2 = _FakeB20Entry(2, 2, "", "", 31, "ap", 101.0, 35.0)
        result = _FakeB20Result([e1, e2])
        jackets = {1: "data:image/webp;base64,Zm9v"}  # song 2 failed

        payload = _b20_render_payload(result, jackets)
        assert payload["b20"][0]["jacket"] == "data:image/webp;base64,Zm9v"
        assert payload["b20"][1]["jacket"] is None


# ── Unit: _difficulty_render_payload ────────────────────────────────────


class TestDifficultyRenderPayload:
    def test_jacket_in_personal_mode(self) -> None:
        """Played entries get jacket data URL."""
        entries = [
            _FakeRankEntry(1, "幾望の月", "32.5+", True, "fc", 99.83, 33.12),
            _FakeRankEntry(2, "Don't Fight The Music", "32.5", False),
        ]
        ranking = _FakeRanking(entries)
        jackets: dict[int, str] = {1: "data:image/webp;base64,Zm9v"}

        payload = _difficulty_render_payload(
            ranking, Difficulty.MASTER, 32, False, jackets,
        )
        # Flatten tiers to find entries
        all_songs = [s for t in payload["tiers"] for s in t["songs"]]
        played = [s for s in all_songs if s["is_played"]]
        unplayed = [s for s in all_songs if not s["is_played"]]

        assert len(played) == 1
        assert played[0]["jacket"] == "data:image/webp;base64,Zm9v"
        assert played[0]["song_title"] == "幾望の月"

        assert len(unplayed) == 1
        assert unplayed[0]["jacket"] is None
        assert not unplayed[0]["is_played"]

    def test_unplayed_has_null_jacket(self) -> None:
        """Unplayed entries should still be in payload with jacket=null."""
        entries = [_FakeRankEntry(1, "Unknown", "31.0", False)]
        ranking = _FakeRanking(entries)

        payload = _difficulty_render_payload(
            ranking, Difficulty.MASTER, 31, True, None,
        )
        all_songs = [s for t in payload["tiers"] for s in t["songs"]]
        assert len(all_songs) == 1
        assert all_songs[0]["jacket"] is None
        assert not all_songs[0]["is_played"]

    def test_global_mode_no_jacket_cache(self) -> None:
        """Global mode without jacket cache → all jackets null."""
        entries = [_FakeRankEntry(i, f"Song {i}", "31.0", False) for i in range(3)]
        ranking = _FakeRanking(entries)

        payload = _difficulty_render_payload(
            ranking, Difficulty.MASTER, 31, True, None,
        )
        all_songs = [s for t in payload["tiers"] for s in t["songs"]]
        assert all(s["jacket"] is None for s in all_songs)


# ── Integration: handler with mock jacket_cache ─────────────────────────


class TestHandlerJacketIntegration:
    """End-to-end: handler → jacket_cache → render payload."""

    async def test_b20_calls_prefetch_with_unique_song_ids(self) -> None:
        """Handler calls prefetch_jackets with deduped song_ids."""
        from pjsk_emubot._handlers import _pjsk_b20

        # Build minimal runtime with mock jacket_cache + renderer
        mock_jacket_cache = MagicMock()
        mock_jacket_cache.prefetch_jackets = AsyncMock(return_value={})

        mock_renderer = MagicMock()
        mock_renderer.render = AsyncMock(return_value=b"png-data")

        mock_user_repo = MagicMock()
        mock_user = MagicMock()
        mock_user.id = MagicMock(value=1)
        mock_user_repo.get_by_qq = AsyncMock(return_value=mock_user)

        mock_query_b20 = MagicMock()
        e1 = _FakeB20Entry(1, 42, "Song A", "32.5+", 32, "fc", 99.0, 33.0)
        e2 = _FakeB20Entry(2, 42, "Song A", "32.5+", 32, "ap", 101.0, 35.0)
        mock_query_b20.query = AsyncMock(return_value=_FakeB20Result([e1, e2]))  # same song_id

        rt = MagicMock(spec=PluginRuntime)
        rt.query_b20 = mock_query_b20
        rt.jacket_cache = mock_jacket_cache
        rt.renderer = mock_renderer
        rt.user_repo = mock_user_repo

        mapper = MagicMock()
        mapper.extract_qq = MagicMock(return_value=MagicMock())

        event = MagicMock()

        text, image_bytes = await _pjsk_b20(rt, mapper, event)

        # Should have prefetched only unique song_ids
        mock_jacket_cache.prefetch_jackets.assert_called_once()
        called_ids = mock_jacket_cache.prefetch_jackets.call_args[0][0]
        assert called_ids == [42]  # deduped

        # Renderer was called (and returned bytes)
        mock_renderer.render.assert_called_once()
        assert image_bytes == b"png-data"

    async def test_b20_no_cache_still_renders(self) -> None:
        """jacket_cache=None → still renders with all-null jackets."""
        mock_renderer = MagicMock()
        mock_renderer.render = AsyncMock(return_value=b"png-data")

        mock_user_repo = MagicMock()
        mock_user = MagicMock()
        mock_user.id = MagicMock(value=1)
        mock_user_repo.get_by_qq = AsyncMock(return_value=mock_user)

        mock_query_b20 = MagicMock()
        mock_query_b20.query = AsyncMock(return_value=_FakeB20Result([
            _FakeB20Entry(1, 1, "Song", "31.0", 31, "fc", 99.0, 30.0),
        ]))

        rt = MagicMock(spec=PluginRuntime)
        rt.query_b20 = mock_query_b20
        rt.jacket_cache = None  # <- no cache
        rt.renderer = mock_renderer
        rt.user_repo = mock_user_repo

        mapper = MagicMock()
        mapper.extract_qq = MagicMock(return_value=MagicMock())

        event = MagicMock()
        text, image_bytes = await _pjsk_b20(rt, mapper, event)

        # Still renders
        mock_renderer.render.assert_called_once()
        payload: RenderPayload = mock_renderer.render.call_args[0][0]
        assert payload.data["b20"][0]["jacket"] is None
        assert image_bytes == b"png-data"

    async def test_difficulty_with_jacket_cache(self) -> None:
        """Difficulty ranking with jacket_cache — jackets in payload."""
        mock_jacket_cache = MagicMock()
        mock_jacket_cache.prefetch_jackets = AsyncMock(return_value={
            1: "data:image/webp;base64,Zm9v",
        })

        mock_renderer = MagicMock()
        mock_renderer.render = AsyncMock(return_value=b"png-data")

        mock_query = MagicMock()
        entries = [
            _FakeRankEntry(1, "Song A", "32.5+", True, "fc", 99.0, 33.0),
            _FakeRankEntry(2, "Song B", "32.5+", False),
        ]
        mock_query.query_personal = AsyncMock(return_value=_FakeRanking(entries))

        mock_user_repo = MagicMock()
        mock_user = MagicMock()
        mock_user.id = MagicMock(value=1)
        mock_user_repo.get_by_qq = AsyncMock(return_value=mock_user)

        rt = MagicMock(spec=PluginRuntime)
        rt.query_difficulty_ranking = mock_query
        rt.jacket_cache = mock_jacket_cache
        rt.renderer = mock_renderer
        rt.user_repo = mock_user_repo

        mapper = MagicMock()
        mapper.extract_qq = MagicMock(return_value=MagicMock())

        event = MagicMock()

        text, image_bytes = await _pjsk_difficulty(
            rt, mapper, event, "ma", 32, False,
        )

        # Deduped call
        mock_jacket_cache.prefetch_jackets.assert_called_once()
        called_ids = mock_jacket_cache.prefetch_jackets.call_args[0][0]
        assert called_ids == [1, 2]

        # Render called
        mock_renderer.render.assert_called_once()
        payload: RenderPayload = mock_renderer.render.call_args[0][0]
        all_songs = [s for t in payload.data["tiers"] for s in t["songs"]]
        jackets = {s["song_id"]: s["jacket"] for s in all_songs}
        assert jackets[1] == "data:image/webp;base64,Zm9v"
        assert jackets[2] is None  # not in prefetch result

    async def test_renderer_unavailable_still_returns_text(self) -> None:
        """When renderer is None, jacket_cache is never called, text returned."""
        mock_query_b20 = MagicMock()
        mock_query_b20.query = AsyncMock(return_value=_FakeB20Result([
            _FakeB20Entry(1, 1, "Song", "31.0", 31, "fc", 99.0, 30.0),
        ]))

        mock_user_repo = MagicMock()
        mock_user = MagicMock()
        mock_user.id = MagicMock(value=1)
        mock_user_repo.get_by_qq = AsyncMock(return_value=mock_user)

        rt = MagicMock(spec=PluginRuntime)
        rt.query_b20 = mock_query_b20
        rt.jacket_cache = None
        rt.renderer = None  # <- no renderer
        rt.user_repo = mock_user_repo

        mapper = MagicMock()
        mapper.extract_qq = MagicMock(return_value=MagicMock())

        event = MagicMock()
        text, image_bytes = await _pjsk_b20(rt, mapper, event)

        assert image_bytes is None
        assert "SP" in text
