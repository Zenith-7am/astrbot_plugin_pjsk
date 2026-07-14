"""Tests for QueryDifficultyRanking application use case."""

from datetime import datetime, timezone

from pjsk_core.application.query_difficulty_ranking import QueryDifficultyRanking
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.song import Song
from pjsk_core.domain.users import UserId
from pjsk_core.ports.repositories import SongCatalog

NOW = datetime.now(timezone.utc)


def _attempt(
    id_: int, chart_id: int = 1,
    status: ScoreStatus = ScoreStatus.FC,
    rating: float = 30.0, accuracy: float = 99.0,
) -> ScoreAttempt:
    return ScoreAttempt(
        id=id_, user_id=UserId(1), chart_id=chart_id,
        judgements=Judgements(perfect=100, great=0, good=0, bad=0, miss=0),
        accuracy=accuracy, rating=rating, status=status,
        image_sha256="sha", source_gateway="test", ocr_run_id=None,
        created_at=NOW,
    )


class FakeChartRepository:
    def __init__(self, charts: list[Chart] | None = None) -> None:
        self._by_id = {c.id: c for c in (charts or [])}
        self._by_difficulty_level: dict[tuple[Difficulty, int], list[Chart]] = {}

    def set_for_level(
        self, difficulty: Difficulty, level: int, charts: list[Chart],
    ) -> None:
        self._by_difficulty_level[(difficulty, level)] = charts

    async def get_by_id(self, chart_id: int) -> Chart | None:
        return self._by_id.get(chart_id)

    async def list_by_difficulty_level(
        self, difficulty: Difficulty, official_level: int,
    ) -> list[Chart]:
        return self._by_difficulty_level.get((difficulty, official_level), [])

    async def find_by_song_and_difficulty(
        self, song_title: str, difficulty: Difficulty,
    ) -> Chart | None:
        raise NotImplementedError

    async def get_song_catalog(self) -> SongCatalog:
        raise NotImplementedError

    async def get_by_song_and_difficulty(
        self, song_id: int, difficulty: Difficulty,
    ) -> Chart | None:
        raise NotImplementedError


class FakeScoreRepository:
    def __init__(self, bests_by_chart: dict[int, ScoreAttempt] | None = None) -> None:
        self._bests = bests_by_chart or {}

    async def list_personal_bests_for_difficulty(
        self, user_id: UserId, chart_ids: list[int],
    ) -> dict[int, ScoreAttempt]:
        return {cid: s for cid, s in self._bests.items() if cid in chart_ids}

    async def record_attempt(self, attempt: ScoreAttempt) -> ScoreAttempt:
        raise NotImplementedError

    async def get_personal_best(
        self, user_id: UserId, chart_id: int,
    ) -> ScoreAttempt | None:
        raise NotImplementedError

    async def list_personal_bests(
        self, user_id: UserId, status_filter: set[ScoreStatus] | None = None,
    ) -> list[ScoreAttempt]:
        raise NotImplementedError

    async def get_b20(
        self, user_id: UserId, include_append: bool,
    ) -> list[ScoreAttempt]:
        raise NotImplementedError


class FakeSongRepository:
    def __init__(self, songs: list[Song] | None = None) -> None:
        self._songs = {s.id: s for s in (songs or [])}

    async def get_by_id(self, song_id: int) -> Song | None:
        return self._songs.get(song_id)

    async def get_all(self) -> list[Song]:
        return list(self._songs.values())


class TestQueryGlobalRanking:
    async def test_returns_all_charts_sorted(self) -> None:
        """Global ranking returns all charts sorted by constant DESC."""
        charts = [
            Chart(id=1, song_id=1, difficulty=Difficulty.MASTER,
                  official_level=31, community_constant="31.0",
                  note_count=1000, data_version="v1"),
            Chart(id=2, song_id=2, difficulty=Difficulty.MASTER,
                  official_level=31, community_constant="32.5+",
                  note_count=1100, data_version="v1"),
            Chart(id=3, song_id=3, difficulty=Difficulty.MASTER,
                  official_level=31, community_constant="32.0",
                  note_count=1050, data_version="v1"),
        ]
        chart_repo = FakeChartRepository(charts)
        chart_repo.set_for_level(Difficulty.MASTER, 31, charts)
        songs = FakeSongRepository([
            Song(id=1, title_ja="Song A", title_cn="", title_en="", aliases="[]"),
            Song(id=2, title_ja="Song B", title_cn="", title_en="", aliases="[]"),
            Song(id=3, title_ja="Song C", title_cn="", title_en="", aliases="[]"),
        ])

        q = QueryDifficultyRanking(charts=chart_repo, scores=FakeScoreRepository(), songs=songs)
        result = await q.query_global(Difficulty.MASTER, 31)

        assert result.mode == "global"
        assert len(result.entries) == 3
        assert result.entries[0].community_constant == "32.5+"
        assert result.entries[1].community_constant == "32.0"
        assert result.entries[2].community_constant == "31.0"

    async def test_empty_level_returns_empty_ranking(self) -> None:
        """No charts at this level returns empty ranking."""
        chart_repo = FakeChartRepository()
        chart_repo.set_for_level(Difficulty.MASTER, 99, [])
        q = QueryDifficultyRanking(
            charts=chart_repo,
            scores=FakeScoreRepository(),
            songs=FakeSongRepository(),
        )
        result = await q.query_global(Difficulty.MASTER, 99)
        assert len(result.entries) == 0


class TestQueryPersonalRanking:
    async def test_shows_unplayed_charts(self) -> None:
        """Personal ranking includes unplayed charts with personal_best=None."""
        charts = [
            Chart(id=1, song_id=1, difficulty=Difficulty.MASTER,
                  official_level=31, community_constant="31.0",
                  note_count=1000, data_version="v1"),
            Chart(id=2, song_id=2, difficulty=Difficulty.MASTER,
                  official_level=31, community_constant="32.0",
                  note_count=1100, data_version="v1"),
        ]
        chart_repo = FakeChartRepository(charts)
        chart_repo.set_for_level(Difficulty.MASTER, 31, charts)
        songs = FakeSongRepository([
            Song(id=1, title_ja="Song A", title_cn="", title_en="", aliases="[]"),
            Song(id=2, title_ja="Song B", title_cn="", title_en="", aliases="[]"),
        ])
        # Only chart 1 is played
        scores = FakeScoreRepository({
            1: _attempt(id_=1, chart_id=1, rating=30.0),
        })

        q = QueryDifficultyRanking(charts=chart_repo, scores=scores, songs=songs)
        result = await q.query_personal(UserId(1), Difficulty.MASTER, 31)

        assert result.mode == "personal"
        assert len(result.entries) == 2
        # Find the played entry
        played = [e for e in result.entries if e.is_played]
        assert len(played) == 1
        assert played[0].chart_id == 1
        assert played[0].personal_best is not None
        assert played[0].rating == 30.0
        # Find the unplayed entry
        unplayed = [e for e in result.entries if not e.is_played]
        assert len(unplayed) == 1
        assert unplayed[0].personal_best is None
        assert unplayed[0].status is None

    async def test_resolves_song_titles(self) -> None:
        """Song titles are resolved via SongRepository."""
        charts = [
            Chart(id=1, song_id=1, difficulty=Difficulty.MASTER,
                  official_level=31, community_constant="31.0",
                  note_count=1000, data_version="v1"),
        ]
        chart_repo = FakeChartRepository(charts)
        chart_repo.set_for_level(Difficulty.MASTER, 31, charts)
        songs = FakeSongRepository([
            Song(id=1, title_ja="幾望の月", title_cn="", title_en="", aliases="[]"),
        ])

        q = QueryDifficultyRanking(charts=chart_repo, scores=FakeScoreRepository(), songs=songs)
        result = await q.query_personal(UserId(1), Difficulty.MASTER, 31)

        assert result.entries[0].song_title == "幾望の月"

    async def test_const_tag_detection(self) -> None:
        """const_tag is extracted from community_constant suffix."""
        charts = [
            Chart(id=1, song_id=1, difficulty=Difficulty.MASTER,
                  official_level=32, community_constant="32.5+",
                  note_count=1000, data_version="v1"),
            Chart(id=2, song_id=2, difficulty=Difficulty.MASTER,
                  official_level=32, community_constant="32.5-",
                  note_count=1000, data_version="v1"),
            Chart(id=3, song_id=3, difficulty=Difficulty.MASTER,
                  official_level=32, community_constant="32.5",
                  note_count=1000, data_version="v1"),
        ]
        chart_repo = FakeChartRepository(charts)
        chart_repo.set_for_level(Difficulty.MASTER, 32, charts)
        songs = FakeSongRepository([
            Song(id=sid, title_ja=f"Song{sid}", title_cn="", title_en="", aliases="[]")
            for sid in range(1, 4)
        ])

        q = QueryDifficultyRanking(charts=chart_repo, scores=FakeScoreRepository(), songs=songs)
        result = await q.query_personal(UserId(1), Difficulty.MASTER, 32)

        tags = {e.community_constant: e.const_tag for e in result.entries}
        assert tags["32.5+"] == "+"
        assert tags["32.5"] == ""
        assert tags["32.5-"] == "-"
