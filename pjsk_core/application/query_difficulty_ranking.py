"""QueryDifficultyRanking use case — global and personal difficulty rankings."""

from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.difficulty_ranking import (
    DifficultyRankEntry,
    DifficultyRanking,
    sort_charts_by_constant,
)
from pjsk_core.domain.users import UserId
from pjsk_core.ports.repositories import (
    ChartRepository,
    ScoreRepository,
    SongRepository,
)


class QueryDifficultyRanking:
    """Fetch difficulty rankings — global (all charts) or personal (with bests)."""

    def __init__(
        self,
        charts: ChartRepository,
        scores: ScoreRepository,
        songs: SongRepository,
    ) -> None:
        self._charts = charts
        self._scores = scores
        self._songs = songs

    async def query_global(
        self, difficulty: Difficulty, official_level: int,
    ) -> DifficultyRanking:
        """Return all charts for a difficulty+level sorted by community constant."""
        charts = await self._charts.list_by_difficulty_level(
            difficulty, official_level,
        )
        return await self._build_ranking(
            difficulty, official_level, "global", charts, None,
        )

    async def query_personal(
        self, user_id: UserId, difficulty: Difficulty, official_level: int,
    ) -> DifficultyRanking:
        """Return all charts for a difficulty+level with user's personal bests."""
        charts = await self._charts.list_by_difficulty_level(
            difficulty, official_level,
        )
        return await self._build_ranking(
            difficulty, official_level, "personal", charts, user_id,
        )

    async def _build_ranking(
        self,
        difficulty: Difficulty,
        official_level: int,
        mode: str,
        charts: list,
        user_id: UserId | None,
    ) -> DifficultyRanking:
        if not charts:
            return DifficultyRanking(
                difficulty=difficulty, official_level=official_level,
                mode=mode, entries=(),
            )

        # Resolve personal bests for personal mode
        personal_bests: dict[int, object] = {}
        if user_id is not None:
            chart_ids = [c.id for c in charts]
            personal_bests = await self._scores.list_personal_bests_for_difficulty(
                user_id, chart_ids,
            )

        # Resolve song titles
        song_ids = {c.song_id for c in charts}
        song_titles: dict[int, str] = {}
        for sid in song_ids:
            song = await self._songs.get_by_id(sid)
            song_titles[sid] = song.title_ja if song else f"Song #{sid}"

        # Determine const_tag from community_constant
        entries: list[DifficultyRankEntry] = []
        for chart in charts:
            cc = chart.community_constant
            tag = ""
            if cc.endswith("+"):
                tag = "+"
            elif cc.endswith("-"):
                tag = "-"

            best = personal_bests.get(chart.id)
            entries.append(DifficultyRankEntry(
                song_id=chart.song_id,
                song_title=song_titles.get(chart.song_id, f"Song #{chart.song_id}"),
                chart_id=chart.id,
                community_constant=cc,
                const_tag=tag,
                official_level=chart.official_level,
                note_count=chart.note_count,
                personal_best=best,
                is_played=best is not None,
            ))

        # Sort by community constant DESC
        sorted_entries = sort_charts_by_constant(entries)

        return DifficultyRanking(
            difficulty=difficulty,
            official_level=official_level,
            mode=mode,
            entries=tuple(sorted_entries),
        )
