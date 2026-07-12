"""SQLite ScoreRepository contract tests."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from adapters.database.connection import get_connection
from adapters.database.migrator import run_migrations
from adapters.database.repository import (
    SqliteChartRepository,
    SqliteScoreRepository,
    SqliteUserRepository,
)
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import QqNumber, UserId

_Repos = tuple[SqliteScoreRepository, SqliteUserRepository, SqliteChartRepository]


@pytest.fixture
async def repos(tmp_path: Path) -> AsyncGenerator[_Repos, None]:
    db = tmp_path / "test.db"
    await run_migrations(db)
    conn = await get_connection(db)
    user_repo = SqliteUserRepository(conn)
    chart_repo = SqliteChartRepository(conn)
    score_repo = SqliteScoreRepository(conn)
    try:
        # Seed a user and a chart
        await user_repo.create(QqNumber("123456789"), game_id="player1")
        await conn.execute(
            "INSERT INTO songs(id, title_ja) VALUES (1, 'Test')"
        )
        await conn.execute(
            "INSERT INTO charts(id, song_id, difficulty, official_level, community_constant, note_count, chart_data_version) "
            "VALUES (1, 1, 'master', 30, '30.5', 1200, '2026-07-12')"
        )
        await conn.commit()
        yield score_repo, user_repo, chart_repo
    finally:
        await conn.close()


class TestSqliteScoreRepository:
    async def test_record_attempt_returns_with_id(self, repos: _Repos) -> None:
        score_repo, _, _ = repos
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None,
            user_id=UserId(1),
            chart_id=1,
            judgements=Judgements(perfect=1000, great=100, good=0, bad=0, miss=0),
            accuracy=100.5,
            rating=3100.0,
            status=ScoreStatus.FC,
            image_sha256="abc123",
            source_gateway="astrbot",
            ocr_run_id=None,
            created_at=now,
        )
        saved = await score_repo.record_attempt(attempt)
        assert saved.id == 1
        assert saved.user_id == UserId(1)

    async def test_record_attempt_updates_personal_best(self, repos: _Repos) -> None:
        score_repo, _, _ = repos
        now = datetime.now(timezone.utc)
        attempt = ScoreAttempt(
            id=None, user_id=UserId(1), chart_id=1,
            judgements=Judgements(perfect=800, great=200, good=0, bad=0, miss=0),
            accuracy=99.0, rating=2900.0, status=ScoreStatus.FC,
            image_sha256="def456", source_gateway="astrbot", ocr_run_id=None,
            created_at=now,
        )
        await score_repo.record_attempt(attempt)

        best = await score_repo.get_personal_best(UserId(1), 1)
        assert best is not None
        assert best.rating == 2900.0

        # Better score replaces personal best
        better = ScoreAttempt(
            id=None, user_id=UserId(1), chart_id=1,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            accuracy=101.0, rating=3200.0, status=ScoreStatus.AP,
            image_sha256="ghi789", source_gateway="astrbot", ocr_run_id=None,
            created_at=now,
        )
        await score_repo.record_attempt(better)

        best = await score_repo.get_personal_best(UserId(1), 1)
        assert best is not None
        assert best.rating == 3200.0

    async def test_get_personal_best_not_found(self, repos: _Repos) -> None:
        score_repo, _, _ = repos
        assert await score_repo.get_personal_best(UserId(1), 999) is None

    async def test_list_personal_bests(self, repos: _Repos) -> None:
        score_repo, _, _ = repos
        now = datetime.now(timezone.utc)
        await score_repo.record_attempt(ScoreAttempt(
            id=None, user_id=UserId(1), chart_id=1,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            accuracy=101.0, rating=3200.0, status=ScoreStatus.AP,
            image_sha256="img1", source_gateway="astrbot", ocr_run_id=None,
            created_at=now,
        ))
        bests = await score_repo.list_personal_bests(UserId(1))
        assert len(bests) == 1

    async def test_list_personal_bests_with_status_filter(self, repos: _Repos) -> None:
        score_repo, _, _ = repos
        now = datetime.now(timezone.utc)
        await score_repo.record_attempt(ScoreAttempt(
            id=None, user_id=UserId(1), chart_id=1,
            judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
            accuracy=101.0, rating=3200.0, status=ScoreStatus.AP,
            image_sha256="img1", source_gateway="astrbot", ocr_run_id=None,
            created_at=now,
        ))
        # FC-only filter should exclude AP
        fc_only = await score_repo.list_personal_bests(
            UserId(1), status_filter={ScoreStatus.FC}
        )
        assert len(fc_only) == 0
        # AP+FC filter should include AP
        both = await score_repo.list_personal_bests(
            UserId(1), status_filter={ScoreStatus.FC, ScoreStatus.AP}
        )
        assert len(both) == 1
