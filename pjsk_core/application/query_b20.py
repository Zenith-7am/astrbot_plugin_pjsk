"""QueryB20 use case — orchestrate repositories to produce a B20Result."""

from pjsk_core.domain.b20 import B20Entry, B20Result, compute_sp
from pjsk_core.domain.player_class import calc_player_class
from pjsk_core.domain.users import UserId
from pjsk_core.ports.repositories import (
    ChartRepository,
    ScoreRepository,
    SongRepository,
    UserRepository,
)


class QueryB20:
    """Fetch and assemble a user's B20 ranking with resolved metadata."""

    def __init__(
        self,
        scores: ScoreRepository,
        songs: SongRepository,
        charts: ChartRepository,
        users: UserRepository,
    ) -> None:
        self._scores = scores
        self._songs = songs
        self._charts = charts
        self._users = users

    async def query(self, user_id: UserId) -> B20Result:
        """Fetch user's B20: filter FC/AP bests, exclude APPEND per preference,
        sort by rating DESC, resolve song/chart titles, compute SP."""
        append_excluded = await self._users.get_append_excluded(user_id)
        include_append = not append_excluded

        attempts = await self._scores.get_b20(user_id, include_append=include_append)

        entries: list[B20Entry] = []
        chart_data_version = "unknown"

        for rank_idx, attempt in enumerate(attempts, start=1):
            chart = await self._charts.get_by_id(attempt.chart_id)
            if chart is None:
                continue

            # Capture chart data version from first entry
            if rank_idx == 1:
                chart_data_version = chart.data_version

            song = await self._songs.get_by_id(chart.song_id)
            song_title = song.title_ja if song else f"Song #{chart.song_id}"

            entries.append(B20Entry(
                rank=rank_idx,
                song_id=chart.song_id,
                song_title=song_title,
                difficulty=chart.difficulty,
                official_level=chart.official_level,
                community_constant=chart.community_constant,
                status=attempt.status,
                accuracy=attempt.accuracy,
                rating=attempt.rating,
                judgements=attempt.judgements,
            ))

        entry_tuple = tuple(entries)
        sp, b20_avg, fc_bonus, ap_bonus = compute_sp(entry_tuple)
        player_class = calc_player_class(sp)

        return B20Result(
            entries=entry_tuple,
            sp=sp,
            player_class=player_class,
            b20_avg=b20_avg,
            fc_bonus=fc_bonus,
            ap_bonus=ap_bonus,
            append_excluded=append_excluded,
            chart_data_version=chart_data_version,
        )
