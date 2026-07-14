"""Tests for QueryB20 application use case."""

from datetime import datetime, timezone

from pjsk_core.application.query_b20 import QueryB20
from pjsk_core.ports.repositories import SongCatalog
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.song import Song
from pjsk_core.domain.users import QqNumber, User, UserId

NOW = datetime.now(timezone.utc)


def _attempt(
    id_: int,
    user_id: int = 1,
    chart_id: int = 1,
    status: ScoreStatus = ScoreStatus.FC,
    rating: float = 30.0,
    accuracy: float = 99.0,
) -> ScoreAttempt:
    return ScoreAttempt(
        id=id_,
        user_id=UserId(user_id),
        chart_id=chart_id,
        judgements=Judgements(perfect=100, great=0, good=0, bad=0, miss=0),
        accuracy=accuracy,
        rating=rating,
        status=status,
        image_sha256="sha",
        source_gateway="test",
        ocr_run_id=None,
        created_at=NOW,
    )


def _song(song_id: int, title_ja: str = "Test") -> Song:
    return Song(id=song_id, title_ja=title_ja, title_cn="", title_en="", aliases="[]")


def _chart(
    chart_id: int,
    song_id: int = 1,
    difficulty: Difficulty = Difficulty.MASTER,
    official_level: int = 31,
    community_constant: str = "31.0",
) -> Chart:
    return Chart(
        id=chart_id, song_id=song_id, difficulty=difficulty,
        official_level=official_level, community_constant=community_constant,
        note_count=1000, data_version="v1",
    )


class FakeScoreRepository:
    """Fake ScoreRepository returning pre-configured B20 attempts."""

    def __init__(self, attempts: list[ScoreAttempt] | None = None) -> None:
        self._attempts = attempts or []
        self._get_b20_calls: list[tuple[UserId, bool]] = []

    async def get_b20(
        self, user_id: UserId, include_append: bool,
    ) -> list[ScoreAttempt]:
        self._get_b20_calls.append((user_id, include_append))
        return self._attempts

    # Unused methods from protocol — raise if called by accident
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

    async def list_personal_bests_for_difficulty(
        self, user_id: UserId, chart_ids: list[int],
    ) -> dict[int, ScoreAttempt]:
        raise NotImplementedError


class FakeSongRepository:
    def __init__(self, songs: list[Song] | None = None) -> None:
        self._songs = {s.id: s for s in (songs or [])}

    async def get_by_id(self, song_id: int) -> Song | None:
        return self._songs.get(song_id)

    async def get_all(self) -> list[Song]:
        return list(self._songs.values())


class FakeChartRepository:
    def __init__(self, charts: list[Chart] | None = None) -> None:
        self._charts = {c.id: c for c in (charts or [])}

    async def get_by_id(self, chart_id: int) -> Chart | None:
        return self._charts.get(chart_id)

    # Unused methods
    async def find_by_song_and_difficulty(
        self, song_title: str, difficulty: Difficulty,
    ) -> Chart | None:
        raise NotImplementedError

    async def list_by_difficulty_level(
        self, difficulty: Difficulty, official_level: int,
    ) -> list[Chart]:
        raise NotImplementedError

    async def get_song_catalog(self) -> SongCatalog:
        raise NotImplementedError

    async def get_by_song_and_difficulty(
        self, song_id: int, difficulty: Difficulty,
    ) -> Chart | None:
        raise NotImplementedError


class FakeUserRepository:
    def __init__(self, append_excluded: bool = True) -> None:
        self._append_excluded = append_excluded
        self._set_calls: list[tuple[UserId, bool]] = []

    async def get_append_excluded(self, user_id: UserId) -> bool:
        return self._append_excluded

    async def set_append_excluded(self, user_id: UserId, excluded: bool) -> None:
        self._set_calls.append((user_id, excluded))
        self._append_excluded = excluded

    # Unused methods
    async def get_by_id(self, user_id: UserId) -> User | None:
        raise NotImplementedError

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        raise NotImplementedError

    async def create(self, qq: QqNumber, game_id: str | None) -> User:
        raise NotImplementedError

    async def get_or_create(self, qq: QqNumber) -> User:
        raise NotImplementedError

    async def bind_game_id(self, user_id: UserId, game_id: str) -> User:
        raise NotImplementedError


class TestQueryB20:
    async def test_resolves_song_and_chart_metadata(self) -> None:
        """QueryB20 resolves song titles and chart constants for each entry."""
        attempts = [_attempt(id_=1, chart_id=1, rating=33.0)]
        charts = [_chart(chart_id=1, song_id=1, difficulty=Difficulty.MASTER,
                         official_level=31, community_constant="31.5+")]
        songs = [_song(song_id=1, title_ja="幾望の月")]

        q = QueryB20(
            scores=FakeScoreRepository(attempts),
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(),
        )
        result = await q.query(UserId(1))

        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.song_title == "幾望の月"
        assert entry.difficulty == Difficulty.MASTER
        assert entry.official_level == 31
        assert entry.community_constant == "31.5+"
        assert entry.rating == 33.0

    async def test_computes_sp_correctly(self) -> None:
        """SP equals B20 average (bonuses are zero for now)."""
        attempts = [
            _attempt(id_=1, chart_id=1, rating=33.0),
            _attempt(id_=2, chart_id=2, rating=29.0),
        ]
        charts = [
            _chart(chart_id=1, song_id=1),
            _chart(chart_id=2, song_id=2),
        ]
        songs = [_song(song_id=1), _song(song_id=2)]

        q = QueryB20(
            scores=FakeScoreRepository(attempts),
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(),
        )
        result = await q.query(UserId(1))

        assert result.b20_avg == 31.0
        assert result.sp == 31.0
        assert result.fc_bonus == 0.0
        assert result.ap_bonus == 0.0

    async def test_passes_include_append_to_repository(self) -> None:
        """When append_excluded is False, include_append=True is passed."""
        attempts = [_attempt(id_=1, chart_id=1, rating=33.0)]
        charts = [_chart(chart_id=1, song_id=1)]
        songs = [_song(song_id=1)]
        scores = FakeScoreRepository(attempts)

        # append_excluded=False → include_append=True
        q = QueryB20(
            scores=scores,
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(append_excluded=False),
        )
        await q.query(UserId(1))
        assert scores._get_b20_calls == [(UserId(1), True)]

    async def test_passes_exclude_append_to_repository(self) -> None:
        """When append_excluded=True, include_append=False is passed."""
        attempts = [_attempt(id_=1, chart_id=1, rating=33.0)]
        charts = [_chart(chart_id=1, song_id=1)]
        songs = [_song(song_id=1)]
        scores = FakeScoreRepository(attempts)

        q = QueryB20(
            scores=scores,
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(append_excluded=True),
        )
        await q.query(UserId(1))
        assert scores._get_b20_calls == [(UserId(1), False)]

    async def test_empty_b20_returns_zero_sp(self) -> None:
        """User with no scores gets zero SP and Beginner class."""
        q = QueryB20(
            scores=FakeScoreRepository([]),
            songs=FakeSongRepository([]),
            charts=FakeChartRepository([]),
            users=FakeUserRepository(),
        )
        result = await q.query(UserId(1))

        assert len(result.entries) == 0
        assert result.sp == 0.0
        assert result.b20_avg == 0.0
        assert result.player_class.name == "Beginner"

    async def test_skips_missing_chart(self) -> None:
        """Chart missing from DB is skipped without crashing."""
        attempts = [
            _attempt(id_=1, chart_id=1, rating=33.0),
            _attempt(id_=2, chart_id=999, rating=35.0),  # missing chart
            _attempt(id_=3, chart_id=2, rating=29.0),
        ]
        charts = [
            _chart(chart_id=1, song_id=1),
            _chart(chart_id=2, song_id=2),
        ]
        songs = [_song(song_id=1), _song(song_id=2)]

        q = QueryB20(
            scores=FakeScoreRepository(attempts),
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(),
        )
        result = await q.query(UserId(1))

        assert len(result.entries) == 2

    async def test_ranks_entries_correctly(self) -> None:
        """Entries are numbered 1-based in order."""
        attempts = [
            _attempt(id_=1, chart_id=1, rating=33.0),
            _attempt(id_=2, chart_id=2, rating=29.0),
        ]
        charts = [_chart(chart_id=1, song_id=1), _chart(chart_id=2, song_id=2)]
        songs = [_song(song_id=1), _song(song_id=2)]

        q = QueryB20(
            scores=FakeScoreRepository(attempts),
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(),
        )
        result = await q.query(UserId(1))

        assert result.entries[0].rank == 1
        assert result.entries[1].rank == 2

    async def test_includes_player_class(self) -> None:
        """B20Result includes the computed player class."""
        attempts = [_attempt(id_=1, chart_id=1, rating=33.0)]
        charts = [_chart(chart_id=1, song_id=1)]
        songs = [_song(song_id=1)]

        q = QueryB20(
            scores=FakeScoreRepository(attempts),
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(),
        )
        result = await q.query(UserId(1))

        assert result.player_class.name == "Beginner"

    async def test_includes_chart_data_version(self) -> None:
        """chart_data_version is captured from the first chart."""
        attempts = [_attempt(id_=1, chart_id=1, rating=33.0)]
        charts = [_chart(chart_id=1, song_id=1)]
        songs = [_song(song_id=1)]

        q = QueryB20(
            scores=FakeScoreRepository(attempts),
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(),
        )
        result = await q.query(UserId(1))

        assert result.chart_data_version == "v1"

    async def test_records_append_excluded_in_result(self) -> None:
        """B20Result records whether APPEND was excluded."""
        attempts = [_attempt(id_=1, chart_id=1, rating=33.0)]
        charts = [_chart(chart_id=1, song_id=1)]
        songs = [_song(song_id=1)]

        # append_excluded=True → recorded as True
        q = QueryB20(
            scores=FakeScoreRepository(attempts),
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(append_excluded=True),
        )
        result = await q.query(UserId(1))
        assert result.append_excluded is True

        # append_excluded=False → recorded as False
        q2 = QueryB20(
            scores=FakeScoreRepository(attempts),
            songs=FakeSongRepository(songs),
            charts=FakeChartRepository(charts),
            users=FakeUserRepository(append_excluded=False),
        )
        result2 = await q2.query(UserId(1))
        assert result2.append_excluded is False
