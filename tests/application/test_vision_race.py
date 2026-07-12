"""Tests for VisionRace — consensus, degradation, circuit-breaker, timeout."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from pjsk_core.application.validate_ocr import (
    ValidatedCandidate,
    ValidatedObservation,
    ValidationStatus,
)
from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy
from pjsk_core.application.vision_race import (
    EngineResultStatus,
    EngineRuntime,
    VisionRace,
    VisionRaceDecision,
)
from pjsk_core.domain.charts import Chart, Difficulty
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionTimeoutError,
)
from pjsk_core.domain.scores import Judgements
from pjsk_core.domain.song_matcher import SongMatch, SongMatchMethod, TitleSource
from pjsk_core.ports.circuit_breaker import (
    CircuitFailure,
    CircuitPermit,
    CircuitState,
)


# ── Fake / Mock helpers ──────────────────────────────────────────────────────


class FakeEngine:
    """Mock VisionEngine that returns predefined results or raises."""

    def __init__(
        self,
        identity: EngineIdentity,
        results: list[OcrObservation | Exception],
    ) -> None:
        self.identity = identity
        self._results = results
        self._calls = 0

    async def recognize(
        self, image: bytes, *, timeout: float
    ) -> OcrObservation:
        if self._calls >= len(self._results):
            raise RuntimeError("No more mock results")
        result = self._results[self._calls]
        self._calls += 1
        if isinstance(result, Exception):
            raise result
        return result


class FakeBreaker:
    """Always-CLOSED breaker for happy-path tests."""

    async def acquire(self, engine_id: str) -> CircuitPermit | None:
        return CircuitPermit(engine_id, probe=False)

    async def record_success(self, permit: CircuitPermit) -> None:
        pass

    async def record_failure(
        self, permit: CircuitPermit, failure: CircuitFailure
    ) -> None:
        pass

    async def release(self, permit: CircuitPermit) -> None:
        pass

    async def state(self, engine_id: str) -> CircuitState:
        return CircuitState.CLOSED


class FakeValidator:
    """Validates by matching song_title to chart_id via a lookup dict."""

    def __init__(self, chart_map: dict[str, int]) -> None:
        self._chart_map = chart_map

    async def validate(
        self, observation: OcrObservation,
    ) -> ValidatedObservation:
        chart_id = self._chart_map.get(observation.song_title)
        if chart_id is None:
            return ValidatedObservation(
                observation=observation,
                primary=None,
                candidates=(),
                status=ValidationStatus.REJECTED,
            )

        total = (
            observation.judgements.perfect
            + observation.judgements.great
            + observation.judgements.good
            + observation.judgements.bad
            + observation.judgements.miss
        )
        chart = Chart(
            id=chart_id,
            song_id=1,
            difficulty=observation.difficulty,
            official_level=observation.displayed_level,
            community_constant="30.0",
            note_count=total,
            data_version="1.0",
        )
        song_match = SongMatch(
            song_id=1,
            score=1.0,
            method=SongMatchMethod.EXACT,
            source=TitleSource.JAPANESE,
        )
        vc = ValidatedCandidate(
            song_match=song_match,
            chart=chart,
            note_distance=0,
            note_validated=True,
            level_validated=True,
            status=ValidationStatus.STRONG,
        )
        return ValidatedObservation(
            observation=observation,
            primary=vc,
            candidates=(vc,),
            status=ValidationStatus.STRONG,
        )


# ── Factory helpers ──────────────────────────────────────────────────────────


def _obs(
    title: str = "Song A",
    perfect: int = 1000,
    great: int = 100,
    good: int = 0,
    bad: int = 0,
    miss: int = 0,
) -> OcrObservation:
    return OcrObservation(
        title,
        Difficulty.MASTER,
        30,
        Judgements(perfect, great, good, bad, miss),
        engine="test",
        elapsed_ms=100,
    )


def _runtime(
    engine_id: str,
    provider: str,
    results: list[OcrObservation | Exception],
    priority: int = 1,
    timeout: float = 15.0,
    max_concurrency: int = 3,
) -> EngineRuntime:
    return EngineRuntime(
        engine=FakeEngine(
            EngineIdentity(engine_id, provider, engine_id), results
        ),
        policy=EnginePolicy(
            engine_id,
            priority=priority,
            enabled=True,
            timeout_seconds=timeout,
            max_concurrency=max_concurrency,
        ),
        semaphore=asyncio.Semaphore(max_concurrency),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


class TestVisionRace:
    """VisionRace test suite."""

    def _race(
        self,
        runtimes: Sequence[EngineRuntime],
        validator: FakeValidator | None = None,
        **policy_kw: Any,
    ) -> VisionRace:
        if validator is None:
            validator = FakeValidator({"Song A": 1, "Song B": 1})
        engines = tuple(r.policy for r in runtimes)
        policy = VisionRacePolicy(
            engines=engines,
            global_timeout_seconds=policy_kw.pop(
                "global_timeout_seconds", 30.0
            ),
            consensus_threshold=policy_kw.pop("consensus_threshold", 2),
        )
        return VisionRace(
            runtimes=runtimes,
            breaker=FakeBreaker(),
            validator=validator,
            policy=policy,
        )

    # ── Consensus tests ─────────────────────────────────────────────────

    async def test_two_providers_agree_consensus(self) -> None:
        """Two independent providers agree -> CONSENSUS."""
        race = self._race(
            [
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [_obs("Song A")]),
                _runtime("s", "stepfun", [_obs("Song A")]),
            ]
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.CONSENSUS
        assert outcome.consensus is not None
        assert outcome.consensus.selected is not None
        # At least 2 providers form the consensus
        assert len(outcome.consensus.supporting_providers) >= 2

    async def test_same_provider_not_independent(self) -> None:
        """Two engines from the same provider cannot form consensus alone."""
        race = self._race(
            [
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("g2", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [_obs("Song A")]),
            ]
        )
        # g + g2 are same provider (google), so need zhipu too = 2 providers
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.CONSENSUS
        assert outcome.consensus is not None
        # Both google and zhipu supported
        assert "google" in outcome.consensus.supporting_providers
        assert "zhipu" in outcome.consensus.supporting_providers

    async def test_disagreement(self) -> None:
        """Three engines each produce a different song -> DISAGREEMENT."""
        validator = FakeValidator({"Song A": 1, "Song B": 2, "Song C": 3})
        race = self._race(
            [
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [_obs("Song B")]),
                _runtime("s", "stepfun", [_obs("Song C")]),
            ],
            validator=validator,
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.DISAGREEMENT

    async def test_degraded_single(self) -> None:
        """One success + others fail -> DEGRADED_SINGLE."""
        race = self._race(
            [
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [VisionTimeoutError("timeout")]),
            ]
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.DEGRADED_SINGLE
        assert outcome.selected is not None

    async def test_all_failed(self) -> None:
        """All engines fail -> ALL_FAILED."""
        race = self._race(
            [
                _runtime("g", "google", [VisionTimeoutError("t")]),
                _runtime("z", "zhipu", [VisionTimeoutError("t")]),
            ]
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.ALL_FAILED

    async def test_one_fails_others_form_consensus(self) -> None:
        """One engine throws but other two agree -> CONSENSUS."""
        race = self._race(
            [
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [VisionTimeoutError("t")]),
                _runtime("s", "stepfun", [_obs("Song A")]),
            ]
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.CONSENSUS
        assert outcome.consensus is not None

    async def test_one_unexpected_exception_others_unaffected(self) -> None:
        """A non-VisionEngineError from one engine does not crash the race."""
        race = self._race(
            [
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [ValueError("unexpected")]),
                _runtime("s", "stepfun", [_obs("Song A")]),
            ]
        )
        outcome = await race.run(b"fake_image")
        # The ValueError is only caught by the broad `except Exception` in
        # _collect's task-await loop, so the worker task itself raises.
        # The engine that raised an unexpected exception is skipped but the
        # remaining two should still form CONSENSUS.
        assert outcome.decision == VisionRaceDecision.CONSENSUS

    # ── Circuit-breaker tests ───────────────────────────────────────────

    async def test_circuit_rejected_engine_skipped(self) -> None:
        """An engine whose circuit is OPEN is skipped; others still run."""

        class SelectiveBreaker(FakeBreaker):
            async def state(self, engine_id: str) -> CircuitState:
                if engine_id == "z":
                    return CircuitState.OPEN  # zhipu is down
                return await super().state(engine_id)

        policy = VisionRacePolicy(
            engines=tuple(
                EnginePolicy(
                    eid,
                    priority=i,
                    enabled=True,
                    timeout_seconds=15.0,
                    max_concurrency=3,
                )
                for i, eid in enumerate(["g", "z", "s"], 1)
            ),
            global_timeout_seconds=30.0,
            consensus_threshold=2,
        )
        race = VisionRace(
            runtimes=[
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [_obs("Song A")]),
                _runtime("s", "stepfun", [_obs("Song A")]),
            ],
            breaker=SelectiveBreaker(),
            validator=FakeValidator({"Song A": 1}),
            policy=policy,
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.CONSENSUS
        assert len(outcome.circuit_rejects) >= 1
        assert any(r.engine_id == "z" for r in outcome.circuit_rejects)

    async def test_all_circuit_rejected(self) -> None:
        """All engines rejected by breaker -> ALL_FAILED."""

        class AllClosedBreaker(FakeBreaker):
            async def state(self, engine_id: str) -> CircuitState:
                return CircuitState.OPEN

        policy = VisionRacePolicy(
            engines=(
                EnginePolicy("g", 1, True, 15.0, 3),
                EnginePolicy("z", 2, True, 15.0, 3),
            ),
            global_timeout_seconds=30.0,
            consensus_threshold=2,
        )
        race = VisionRace(
            runtimes=[
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [_obs("Song A")]),
            ],
            breaker=AllClosedBreaker(),
            validator=FakeValidator({"Song A": 1}),
            policy=policy,
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.ALL_FAILED

    # ── Global timeout tests ────────────────────────────────────────────

    async def test_global_timeout_triggers(self) -> None:
        """Very short global timeout -> GLOBAL_TIMEOUT with partial results."""

        class SlowEngine:
            def __init__(self, identity: EngineIdentity) -> None:
                self.identity = identity

            async def recognize(
                self, image: bytes, *, timeout: float
            ) -> OcrObservation:
                await asyncio.sleep(5.0)
                return _obs("Song A")

        slow = EngineRuntime(
            engine=SlowEngine(EngineIdentity("g", "google", "g")),
            policy=EnginePolicy(
                "g",
                priority=1,
                enabled=True,
                timeout_seconds=15.0,
                max_concurrency=3,
            ),
            semaphore=asyncio.Semaphore(3),
        )
        fast = _runtime("z", "zhipu", [VisionTimeoutError("timeout")])

        race = self._race([slow, fast], global_timeout_seconds=0.1)
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.GLOBAL_TIMEOUT

    async def test_no_available_engines(self) -> None:
        """All engines disabled -> NO_AVAILABLE_ENGINES."""
        # Policy must have at least one enabled engine to pass validation,
        # but the actual runtime passed to VisionRace is disabled.
        policy = VisionRacePolicy(
            engines=(
                EnginePolicy("g", 1, True, 15.0, 3),
                EnginePolicy("z", 2, True, 15.0, 3),
            ),
            global_timeout_seconds=30.0,
            consensus_threshold=2,
        )
        disabled = EngineRuntime(
            engine=FakeEngine(
                EngineIdentity("g", "google", "g"), [_obs("Song A")]
            ),
            policy=EnginePolicy(
                "g",
                priority=1,
                enabled=False,
                timeout_seconds=15.0,
                max_concurrency=3,
            ),
            semaphore=asyncio.Semaphore(3),
        )
        race = VisionRace(
            runtimes=[disabled],
            breaker=FakeBreaker(),
            validator=FakeValidator({"Song A": 1}),
            policy=policy,
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.NO_AVAILABLE_ENGINES
        assert len(outcome.results) == 0

    # ── Consensus match structural tests ────────────────────────────────

    async def test_consensus_returns_proper_match(self) -> None:
        """Verify ConsensusMatch structure when consensus is reached."""
        race = self._race(
            [
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [_obs("Song A")]),
            ]
        )
        outcome = await race.run(b"fake_image")
        assert outcome.decision == VisionRaceDecision.CONSENSUS
        assert outcome.consensus is not None
        assert len(outcome.consensus.supporting_engines) >= 2
        assert len(outcome.consensus.supporting_providers) >= 2
        assert outcome.consensus.selected is not None
        # selected should be a STRONG ValidatedObservation
        assert outcome.consensus.selected.status == ValidationStatus.STRONG

    async def test_engine_result_status_values(self) -> None:
        """Engine results carry correct statuses."""
        race = self._race(
            [
                _runtime("g", "google", [_obs("Song A")]),
                _runtime("z", "zhipu", [VisionTimeoutError("t")]),
            ]
        )
        outcome = await race.run(b"fake_image")
        assert len(outcome.results) == 2

        statuses = {r.identity.engine_id: r.status for r in outcome.results}
        assert statuses["g"] == EngineResultStatus.SUCCESS
        assert statuses["z"] == EngineResultStatus.FAILED
