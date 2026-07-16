"""Tests for Runtime lifecycle states."""
from pjsk_emubot.rate_limiter import UserRateLimiter
from pjsk_runtime.runtime import Runtime, RuntimeStatus


class _FakeRepo:
    async def get_by_id(self, uid: object) -> None:
        return None
    async def get_all(self) -> list:
        return []


class _FakeUseCase:
    pass


class _FakeImageBuffer:
    def put(self, *a: object, **kw: object) -> None: ...
    def consume(self, *a: object, **kw: object) -> bytes | None: ...
    def arm(self, *a: object, **kw: object) -> None: ...
    def consume_arm(self, *a: object, **kw: object) -> bool:
        return False
    async def close(self) -> None: ...


def _make_runtime(**overrides: object) -> Runtime:
    kwargs: dict[str, object] = dict(
        user_repo=_FakeRepo(),
        chart_repo=_FakeRepo(),
        score_repo=_FakeRepo(),
        song_repo=_FakeRepo(),
        ocr_run_repo=_FakeRepo(),
        confirm_candidate=_FakeUseCase(),
        candidate_store=_FakeUseCase(),
        query_b20=_FakeUseCase(),
        query_difficulty_ranking=_FakeUseCase(),
        toggle_append=_FakeUseCase(),
        image_buffer=_FakeImageBuffer(),
        rate_limiter=UserRateLimiter(),
    )
    kwargs.update(overrides)
    return Runtime(**kwargs)  # type: ignore[arg-type]


class TestRuntimeLifecycle:
    def test_initial_status_is_starting(self) -> None:
        rt = _make_runtime()
        assert rt.status == RuntimeStatus.STARTING

    def test_mark_ready_transitions_to_ready(self) -> None:
        rt = _make_runtime()
        rt.mark_ready()
        assert rt.status == RuntimeStatus.READY

    def test_mark_ready_is_idempotent(self) -> None:
        rt = _make_runtime()
        rt.mark_ready()
        rt.mark_ready()
        assert rt.status == RuntimeStatus.READY

    def test_mark_degraded(self) -> None:
        rt = _make_runtime()
        rt.mark_ready()
        rt.mark_degraded("renderer unreachable")
        assert rt.status == RuntimeStatus.DEGRADED

    async def test_close_transitions_to_stopped(self) -> None:
        rt = _make_runtime()
        rt.mark_ready()
        await rt.close()
        assert rt.status == RuntimeStatus.STOPPED

    async def test_close_is_idempotent(self) -> None:
        rt = _make_runtime()
        rt.mark_ready()
        await rt.close()
        await rt.close()  # second call must not raise
        assert rt.status == RuntimeStatus.STOPPED


class TestRuntimeCandidateState:
    def test_set_and_get_pending(self) -> None:
        rt = _make_runtime()
        rt.set_pending(1, "onebot", "private", "cid-1", "display text")
        assert rt.get_pending_candidate_set_id(1, "onebot", "private") == "cid-1"
        assert (
            rt.get_pending_display_text(1, "onebot", "private") == "display text"
        )

    def test_clear_pending(self) -> None:
        rt = _make_runtime()
        rt.set_pending(1, "onebot", "private", "cid-1", "display text")
        rt.clear_pending(1, "onebot", "private")
        assert rt.get_pending_candidate_set_id(1, "onebot", "private") is None
        assert rt.get_pending_display_text(1, "onebot", "private") is None

    def test_pending_scoped_by_conversation(self) -> None:
        rt = _make_runtime()
        rt.set_pending(1, "onebot", "private", "cid-p", "private display")
        rt.set_pending(1, "onebot", "group_123", "cid-g", "group display")
        assert rt.get_pending_candidate_set_id(1, "onebot", "private") == "cid-p"
        assert rt.get_pending_candidate_set_id(1, "onebot", "group_123") == "cid-g"
