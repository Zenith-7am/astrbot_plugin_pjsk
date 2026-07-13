"""Tests for PluginRuntime."""
from plugin.rate_limiter import UserRateLimiter
from plugin.runtime import PluginRuntime
from pjsk_core.domain.users import UserId


class _FakeRepo:
    async def get_by_id(self, uid: UserId) -> None:
        return None


class _FakeRecognizeScore:
    pass


class _FakeConfirmCandidate:
    pass


class _FakeCandidateStore:
    pass


class _FakeImageBuffer:
    def put(self, *a: object, **kw: object) -> None: ...
    def consume(self, *a: object, **kw: object) -> bytes | None: ...
    def arm(self, *a: object, **kw: object) -> None: ...
    def consume_arm(self, *a: object, **kw: object) -> bool:
        return False
    async def close(self) -> None: ...


class TestPluginRuntime:
    def test_runtime_creation(self) -> None:
        rt = PluginRuntime(
            user_repo=_FakeRepo(),                 # type: ignore[arg-type]
            chart_repo=_FakeRepo(),                # type: ignore[arg-type]
            score_repo=_FakeRepo(),                # type: ignore[arg-type]
            ocr_run_repo=_FakeRepo(),              # type: ignore[arg-type]
            recognize_score=_FakeRecognizeScore(),  # type: ignore[arg-type]
            confirm_candidate=_FakeConfirmCandidate(),  # type: ignore[arg-type]
            candidate_store=_FakeCandidateStore(),      # type: ignore[arg-type]
            image_buffer=_FakeImageBuffer(),
            rate_limiter=UserRateLimiter(),
        )
        assert rt.user_repo is not None
        assert rt.recognize_score is not None
        assert rt.image_buffer is not None

    async def test_close_does_not_raise(self) -> None:
        rt = PluginRuntime(
            user_repo=_FakeRepo(),                 # type: ignore[arg-type]
            chart_repo=_FakeRepo(),                # type: ignore[arg-type]
            score_repo=_FakeRepo(),                # type: ignore[arg-type]
            ocr_run_repo=_FakeRepo(),              # type: ignore[arg-type]
            recognize_score=_FakeRecognizeScore(),  # type: ignore[arg-type]
            confirm_candidate=_FakeConfirmCandidate(),  # type: ignore[arg-type]
            candidate_store=_FakeCandidateStore(),      # type: ignore[arg-type]
            image_buffer=_FakeImageBuffer(),
            rate_limiter=UserRateLimiter(),
        )
        await rt.close()
