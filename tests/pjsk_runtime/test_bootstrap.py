"""Tests for AdapterBundle."""
from pjsk_runtime.bootstrap import AdapterBundle


class _FakeRepo:
    pass


class TestAdapterBundle:
    def test_creation(self) -> None:
        user = _FakeRepo()
        bundle = AdapterBundle(
            user_repo=user,
            chart_repo=_FakeRepo(),
            score_repo=_FakeRepo(),
            song_repo=_FakeRepo(),
            ocr_run_repo=_FakeRepo(),
            candidate_store=_FakeRepo(),
        )
        assert bundle.user_repo is user
