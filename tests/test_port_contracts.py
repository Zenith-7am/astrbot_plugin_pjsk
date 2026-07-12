"""Contract tests: every Protocol has a fake implementation that type-checks
and passes a basic async smoke call."""

from datetime import datetime, timezone


from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import OcrObservation
from pjsk_core.domain.scores import Judgements, ScoreAttempt, ScoreStatus
from pjsk_core.domain.users import QqNumber, User, UserId
from pjsk_core.ports.cache import CandidateStore
from pjsk_core.ports.identity import IdentityResolver
from pjsk_core.ports.renderer import RenderRequest, RenderResult, Renderer
from pjsk_core.ports.repositories import (
    ChartRepository,
    ScoreRepository,
    UserRepository,
)
from pjsk_core.ports.vision import VisionEngine
from pjsk_core.ports.circuit_breaker import (
    CircuitBreaker,
    CircuitPermit,
    CircuitState,
)


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
    name = "fake-vision"

    async def recognize(self, image: bytes, *, timeout: float) -> OcrObservation:
        return OcrObservation(
            song_title="Test Song",
            difficulty=Difficulty.EXPERT,
            displayed_level=25,
            judgements=Judgements(perfect=800, great=0, good=0, bad=0, miss=0),
            engine=self.name,
            elapsed_ms=100,
        )


class FakeRenderer:
    async def render(self, request: RenderRequest) -> RenderResult:
        return RenderResult(
            image_bytes=b"fake-png-data",
            renderer_version="fake-1.0",
            template_version=request.template + "-v1",
        )


class FakeIdentityResolver:
    async def resolve(self, platform: str, external_id: str) -> QqNumber | None:
        return QqNumber("123456789") if external_id == "known" else None


class FakeCandidateStore:
    def __init__(self) -> None:
        self._store: dict[str, tuple[UserId, list[OcrObservation]]] = {}
        self._consumed: set[str] = set()

    async def put(
        self, user_id: UserId, candidates: list[OcrObservation], ttl_seconds: int
    ) -> str:
        key = f"candidate-{len(self._store)}"
        self._store[key] = (user_id, candidates)
        return key

    async def consume(
        self, candidate_set_id: str, user_id: UserId,
    ) -> list[OcrObservation] | None:
        if candidate_set_id in self._consumed:
            return None
        entry = self._store.get(candidate_set_id)
        if entry is None or entry[0] != user_id:
            return None  # not found or wrong owner
        self._consumed.add(candidate_set_id)
        return entry[1]


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
    req = RenderRequest(template="b20", data={}, width=800, height=600)
    result = await renderer.render(req)
    assert result.image_bytes == b"fake-png-data"


async def test_identity_resolver_contract() -> None:
    resolver: IdentityResolver = FakeIdentityResolver()
    result = await resolver.resolve("qq_official", "known")
    assert result == QqNumber("123456789")

    result = await resolver.resolve("qq_official", "unknown")
    assert result is None


async def test_candidate_store_contract() -> None:
    store: CandidateStore = FakeCandidateStore()
    obs = OcrObservation(
        song_title="Test", difficulty=Difficulty.HARD,
        displayed_level=15,
        judgements=Judgements(perfect=1, great=0, good=0, bad=0, miss=0),
        engine="test", elapsed_ms=0,
    )
    cid = await store.put(UserId(1), [obs], ttl_seconds=60)
    assert cid is not None

    result = await store.consume(cid, UserId(1))
    assert result == [obs]

    # Second consume returns None (already consumed)
    result2 = await store.consume(cid, UserId(1))
    assert result2 is None


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
