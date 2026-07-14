"""Contract tests: every Protocol has a fake implementation that type-checks
and passes a basic async smoke call."""

import asyncio
from datetime import datetime, timezone


from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import EngineIdentity, OcrObservation
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import QqNumber, User, UserId
from pjsk_core.ports.cache import (
    CandidateConsumeResult,
    CandidateConsumeStatus,
    CandidateSet,
    CandidateStore,
)
from pjsk_core.ports.identity import IdentityResolver
from pjsk_core.ports.renderer import RenderPayload, Renderer
from pjsk_core.ports.repositories import (
    ChartRepository,
    ScoreRepository,
    SongCatalog,
    UserRepository,
)
from pjsk_core.ports.vision import VisionEngine
from pjsk_core.domain.ocr_runs import OcrEngineRecord, OcrRunRecord
from pjsk_core.ports.circuit_breaker import (
    CircuitBreaker,
    CircuitPermit,
    CircuitState,
)
from pjsk_core.ports.ocr_runs import OcrRunRepository


# ── Fake implementations ────────────────────────────────────────────

class FakeUserRepository:
    def __init__(self) -> None:
        self._users: dict[int, User] = {}
        self._next_id = 1

    async def get_by_id(self, user_id: UserId) -> User | None:
        return self._users.get(user_id.value)

    async def get_by_qq(self, qq: QqNumber) -> User | None:
        for u in self._users.values():
            if u.qq_number == qq:
                return u
        return None

    async def create(self, qq: QqNumber, game_id: str | None) -> User:
        uid = UserId(self._next_id)
        self._next_id += 1
        user = User(id=uid, qq_number=qq, game_id=game_id)
        self._users[uid.value] = user
        return user

    async def get_or_create(self, qq: QqNumber) -> User:
        existing = await self.get_by_qq(qq)
        if existing is not None:
            return existing
        return await self.create(qq, game_id=None)

    async def bind_game_id(self, user_id: UserId, game_id: str) -> User:
        from pjsk_core.ports.repositories import (
            AlreadyBoundError,
            DuplicateGameIdError,
        )
        old = self._users[user_id.value]
        if old.game_id is not None and old.game_id != game_id:
            raise AlreadyBoundError(
                f"User {user_id.value} already bound to '{old.game_id}'"
            )
        if old.game_id == game_id:
            return old  # idempotent
        for u in self._users.values():
            if u.game_id == game_id and u.id != user_id:
                raise DuplicateGameIdError(
                    f"game_id '{game_id}' is already bound to another user"
                )
        updated = User(
            id=old.id, qq_number=old.qq_number, game_id=game_id,
        )
        self._users[user_id.value] = updated
        return updated


class FakeChartRepository:
    def __init__(self) -> None:
        self._charts: dict[int, Chart] = {}

    async def get_by_id(self, chart_id: int) -> Chart | None:
        return self._charts.get(chart_id)

    async def find_by_song_and_difficulty(
        self, song_title: str, difficulty: Difficulty
    ) -> Chart | None:
        for c in self._charts.values():
            if c.difficulty == difficulty:
                return c
        return None

    async def list_by_difficulty_level(
        self, difficulty: Difficulty, official_level: int
    ) -> list[Chart]:
        return [
            c
            for c in self._charts.values()
            if c.difficulty == difficulty and c.official_level == official_level
        ]

    async def get_song_catalog(self) -> SongCatalog:
        return SongCatalog(version="test-v1", candidates=())

    async def get_by_song_and_difficulty(
        self, song_id: int, difficulty: Difficulty,
    ) -> Chart | None:
        for c in self._charts.values():
            if c.song_id == song_id and c.difficulty == difficulty:
                return c
        return None


class FakeScoreRepository:
    def __init__(self) -> None:
        self._attempts: dict[int, ScoreAttempt] = {}
        self._bests: dict[tuple[int, int], ScoreAttempt] = {}
        self._next_id = 1

    async def record_attempt(self, attempt: ScoreAttempt) -> ScoreAttempt:
        saved = ScoreAttempt(
            id=self._next_id,
            user_id=attempt.user_id,
            chart_id=attempt.chart_id,
            judgements=attempt.judgements,
            accuracy=attempt.accuracy,
            rating=attempt.rating,
            status=attempt.status,
            image_sha256=attempt.image_sha256,
            source_gateway=attempt.source_gateway,
            ocr_run_id=attempt.ocr_run_id,
            created_at=attempt.created_at,
        )
        self._next_id += 1
        self._attempts[saved.id] = saved  # type: ignore[index]
        key = (saved.user_id.value, saved.chart_id)
        current = self._bests.get(key)
        if current is None or saved.rating >= current.rating:
            self._bests[key] = saved
        return saved

    async def get_personal_best(
        self, user_id: UserId, chart_id: int
    ) -> ScoreAttempt | None:
        return self._bests.get((user_id.value, chart_id))

    async def list_personal_bests(
        self, user_id: UserId, status_filter: set[ScoreStatus] | None = None,
    ) -> list[ScoreAttempt]:
        results = [
            v for k, v in self._bests.items() if k[0] == user_id.value
        ]
        if status_filter is not None:
            results = [r for r in results if r.status in status_filter]
        return results


class FakeVisionEngine:
    identity = EngineIdentity(engine_id="fake-vision", provider="test", model="test-v1")

    async def recognize(self, image: bytes, *, timeout: float) -> OcrObservation:
        return OcrObservation(
            song_title="Test Song",
            difficulty=Difficulty.EXPERT,
            displayed_level=25,
            judgements=Judgements(perfect=800, great=0, good=0, bad=0, miss=0),
            engine=self.identity.engine_id,
            elapsed_ms=100,
        )


class FakeRenderer:
    async def render(self, payload: RenderPayload) -> bytes | None:
        return b"fake-png-data"


class FakeIdentityResolver:
    async def resolve(self, platform: str, external_id: str) -> QqNumber | None:
        return QqNumber("123456789") if external_id == "known" else None


class FakeCandidateStore:
    def __init__(self) -> None:
        self._store: dict[str, tuple[UserId, CandidateSet]] = {}
        self._lock = asyncio.Lock()

    async def put(
        self, user_id: UserId, candidate_set: CandidateSet, ttl_seconds: int,
    ) -> str:
        key = f"cs-{len(self._store)}"
        async with self._lock:
            self._store[key] = (user_id, candidate_set)
        return key

    async def consume_selection(
        self, candidate_set_id: str, user_id: UserId, selection: int,
    ) -> CandidateConsumeResult:
        async with self._lock:
            entry = self._store.pop(candidate_set_id, None)
        if entry is None:
            return CandidateConsumeResult(
                status=CandidateConsumeStatus.NOT_FOUND,
                candidate=None, candidate_set=None,
            )
        owner, cs = entry
        if owner != user_id:
            return CandidateConsumeResult(
                status=CandidateConsumeStatus.FORBIDDEN,
                candidate=None, candidate_set=None,
            )
        if selection < 1 or selection > len(cs.candidates):
            return CandidateConsumeResult(
                status=CandidateConsumeStatus.INVALID_SELECTION,
                candidate=None, candidate_set=None,
            )
        return CandidateConsumeResult(
            status=CandidateConsumeStatus.OK,
            candidate=cs.candidates[selection - 1],
            candidate_set=cs,
        )


# ── Contract tests ──────────────────────────────────────────────────


async def test_user_repository_contract() -> None:
    repo: UserRepository = FakeUserRepository()
    assert await repo.get_by_id(UserId(1)) is None

    qq = QqNumber("123456789")
    user = await repo.create(qq, None)
    assert user.id == UserId(1)

    fetched = await repo.get_by_qq(qq)
    assert fetched == user


async def test_chart_repository_contract() -> None:
    repo: ChartRepository = FakeChartRepository()
    assert await repo.get_by_id(999) is None

    chart = Chart(
        id=1, song_id=10, difficulty=Difficulty.MASTER,
        official_level=31, community_constant="31.2", note_count=1200,
        data_version="v1",
    )
    repo._charts[1] = chart  # type: ignore[attr-defined]
    assert await repo.get_by_id(1) == chart


async def test_score_repository_contract() -> None:
    repo: ScoreRepository = FakeScoreRepository()
    now = datetime.now(timezone.utc)
    attempt = ScoreAttempt(
        id=None,
        user_id=UserId(1),
        chart_id=42,
        judgements=Judgements(perfect=1000, great=0, good=0, bad=0, miss=0),
        accuracy=101.0,
        rating=3500.0,
        status=ScoreStatus.AP,
        image_sha256="abc",
        source_gateway="astrbot",
        ocr_run_id=None,
        created_at=now,
    )
    saved = await repo.record_attempt(attempt)
    assert saved.id is not None

    best = await repo.get_personal_best(UserId(1), 42)
    assert best is not None


async def test_vision_engine_contract() -> None:
    engine: VisionEngine = FakeVisionEngine()
    obs = await engine.recognize(b"fake-image", timeout=10.0)
    assert obs.engine == "fake-vision"
    assert obs.song_title == "Test Song"


async def test_renderer_contract() -> None:
    renderer: Renderer = FakeRenderer()
    payload = RenderPayload(template_name="b20", data={"entries": []})
    result = await renderer.render(payload)
    assert result == b"fake-png-data"


async def test_identity_resolver_contract() -> None:
    resolver: IdentityResolver = FakeIdentityResolver()
    result = await resolver.resolve("qq_official", "known")
    assert result == QqNumber("123456789")

    result = await resolver.resolve("qq_official", "unknown")
    assert result is None


async def test_candidate_store_contract() -> None:
    store: CandidateStore = FakeCandidateStore()
    from pjsk_core.domain.ocr import Candidate
    obs = OcrObservation(
        song_title="Test", difficulty=Difficulty.HARD,
        displayed_level=15,
        judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
        engine="test", elapsed_ms=0,
    )
    candidate = Candidate(
        observation=obs, model_support=1, note_validated=True,
        title_similarity=1.0, note_distance=0, matched_chart_id=1,
    )
    cs = CandidateSet(
        candidates=(candidate,), image_sha256="a" * 64,
        source_gateway="astrbot", ocr_run_id=1, chart_data_version="v1",
    )
    cid = await store.put(UserId(1), cs, ttl_seconds=300)
    assert cid is not None

    result = await store.consume_selection(cid, UserId(1), 1)
    assert result.status == CandidateConsumeStatus.OK
    assert result.candidate is not None
    assert result.candidate_set is not None

    # Second consume returns NOT_FOUND
    result2 = await store.consume_selection(cid, UserId(1), 1)
    assert result2.status == CandidateConsumeStatus.NOT_FOUND

    # Wrong user
    cid2 = await store.put(UserId(1), cs, ttl_seconds=300)
    result3 = await store.consume_selection(cid2, UserId(2), 1)
    assert result3.status == CandidateConsumeStatus.FORBIDDEN

    # Invalid selection
    cid3 = await store.put(UserId(1), cs, ttl_seconds=300)
    result4 = await store.consume_selection(cid3, UserId(1), 5)
    assert result4.status == CandidateConsumeStatus.INVALID_SELECTION


# ── CircuitBreaker contract tests ──────────────────────────────────


class TestCircuitBreakerContract:
    def test_protocol_methods_exist(self) -> None:
        """CircuitBreaker Protocol defines all required methods."""
        assert hasattr(CircuitBreaker, "acquire")
        assert hasattr(CircuitBreaker, "record_success")
        assert hasattr(CircuitBreaker, "record_failure")
        assert hasattr(CircuitBreaker, "release")
        assert hasattr(CircuitBreaker, "state")

    def test_circuit_permit_fields(self) -> None:
        permit = CircuitPermit("eng", probe=True)
        assert permit.engine_id == "eng"
        assert permit.probe is True

    def test_circuit_state_values(self) -> None:
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


# ── VisionEngine identity contract tests ─────────────────────────────


class TestVisionEngineRevisedContract:
    def test_identity_attribute(self) -> None:
        """VisionEngine no longer has 'name'; it has 'identity'."""
        annotations = VisionEngine.__annotations__
        assert "identity" in annotations
        assert "name" not in annotations


# ── ChartRepository extended contract tests ──────────────────────────


class TestChartRepositoryExtended:
    def test_get_song_catalog_exists(self) -> None:
        assert hasattr(ChartRepository, "get_song_catalog")

    def test_get_by_song_and_difficulty_exists(self) -> None:
        assert hasattr(ChartRepository, "get_by_song_and_difficulty")


# ── OcrRunRepository contract tests ──────────────────────────────────


class FakeOcrRunRepository:
    def __init__(self) -> None:
        self._store: dict[int, OcrRunRecord] = {}
        self._next_id = 1

    async def save(self, record: OcrRunRecord) -> OcrRunRecord:
        stored = OcrRunRecord(
            id=self._next_id, user_id=record.user_id,
            image_sha256=record.image_sha256,
            source_gateway=record.source_gateway,
            final_state=record.final_state,
            selected_engine=record.selected_engine,
            observations=record.observations,
            created_at=record.created_at,
        )
        self._next_id += 1
        assert stored.id is not None
        self._store[stored.id] = stored
        return stored

    async def get_by_id(self, run_id: int) -> OcrRunRecord | None:
        return self._store.get(run_id)


async def test_ocr_run_repository_contract() -> None:
    repo: OcrRunRepository = FakeOcrRunRepository()
    obs = OcrEngineRecord(
        engine_id="g", provider="google", result_status="success",
        elapsed_ms=500, song_title="Test", difficulty=Difficulty.MASTER,
        displayed_level=30,
        judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
        matched_chart_id=1, validation_status="strong", error_type=None,
    )
    record = OcrRunRecord(
        id=None, user_id=UserId(1),
        image_sha256="a" * 64, source_gateway="astrbot",
        final_state="consensus", selected_engine="g",
        observations=(obs,), created_at=datetime.now(timezone.utc),
    )
    saved = await repo.save(record)
    assert saved.id is not None
    assert saved.id == 1

    fetched = await repo.get_by_id(1)
    assert fetched is not None
    assert fetched.final_state == "consensus"

    not_found = await repo.get_by_id(999)
    assert not_found is None
