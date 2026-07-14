"""Tests for PluginRuntime."""
from pjsk_emubot.rate_limiter import UserRateLimiter
from pjsk_emubot.runtime import PluginRuntime
from pjsk_core.domain.users import UserId
from pjsk_core.domain.song import Song


class _FakeRepo:
    async def get_by_id(self, uid: UserId) -> None:
        return None
    async def get_all(self) -> list[Song]:
        return []


class _FakeRecognizeScore:
    pass


class _FakeConfirmCandidate:
    pass


class _FakeCandidateStore:
    pass


class _FakeQueryB20:
    pass


class _FakeQueryDifficultyRanking:
    pass


class _FakeToggleAppend:
    pass


class _FakeImageBuffer:
    def put(self, *a: object, **kw: object) -> None: ...
    def consume(self, *a: object, **kw: object) -> bytes | None: ...
    def arm(self, *a: object, **kw: object) -> None: ...
    def consume_arm(self, *a: object, **kw: object) -> bool:
        return False
    async def close(self) -> None: ...


def _make_runtime(**overrides: object) -> PluginRuntime:
    """Build a PluginRuntime with all required fields filled by fakes."""
    kwargs: dict[str, object] = dict(
        user_repo=_FakeRepo(),
        chart_repo=_FakeRepo(),
        score_repo=_FakeRepo(),
        song_repo=_FakeRepo(),
        ocr_run_repo=_FakeRepo(),
        confirm_candidate=_FakeConfirmCandidate(),
        candidate_store=_FakeCandidateStore(),
        image_buffer=_FakeImageBuffer(),
        rate_limiter=UserRateLimiter(),
        query_b20=_FakeQueryB20(),
        query_difficulty_ranking=_FakeQueryDifficultyRanking(),
        toggle_append=_FakeToggleAppend(),
        recognize_score=_FakeRecognizeScore(),
    )
    kwargs.update(overrides)
    return PluginRuntime(**kwargs)  # type: ignore[arg-type]


class TestPluginRuntime:
    def test_runtime_creation(self) -> None:
        rt = _make_runtime()
        assert rt.user_repo is not None
        assert rt.image_buffer is not None

    async def test_close_does_not_raise(self) -> None:
        rt = _make_runtime()
        await rt.close()
