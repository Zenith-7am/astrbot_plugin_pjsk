"""Vision race orchestrator — concurrent engines, consensus, degradation."""
from __future__ import annotations

import asyncio
import time as _time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from pjsk_core.application.validate_ocr import (
    ValidatedObservation,
    ValidationStatus,
)
from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy
from pjsk_core.domain.charts import Difficulty
from pjsk_core.domain.ocr import (
    EngineIdentity,
    OcrObservation,
    VisionEngineError,
    VisionResponseError,
)
from pjsk_core.domain.scores import Judgements
from pjsk_core.ports.circuit_breaker import (
    CircuitBreaker,
    CircuitFailure,
)
from pjsk_core.ports.vision import VisionEngine


class EngineResultStatus(Enum):
    """Outcome of a single engine's attempt in the race."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED_BY_CONSENSUS = "cancelled_by_consensus"
    CANCELLED_BY_CALLER = "cancelled_by_caller"


class VisionRaceDecision(Enum):
    """Final decision type for the entire vision race."""

    CONSENSUS = "consensus"
    DEGRADED_SINGLE = "degraded_single"
    DISAGREEMENT = "disagreement"
    ALL_FAILED = "all_failed"
    NO_AVAILABLE_ENGINES = "no_available_engines"
    GLOBAL_TIMEOUT = "global_timeout"


@dataclass(frozen=True)
class EngineResult:
    """Result from a single engine worker."""

    identity: EngineIdentity
    status: EngineResultStatus
    observation: OcrObservation | None
    validated: ValidatedObservation | None
    error: VisionEngineError | None
    elapsed_ms: int


@dataclass(frozen=True)
class ConsensusMatch:
    """Details about a consensus reached among multiple providers."""

    selected: ValidatedObservation
    supporting_engines: tuple[EngineIdentity, ...]
    supporting_providers: tuple[str, ...]


@dataclass(frozen=True)
class VisionRaceOutcome:
    """Aggregated outcome of a vision race."""

    decision: VisionRaceDecision
    selected: ValidatedObservation | None
    consensus: ConsensusMatch | None
    results: tuple[EngineResult, ...]
    circuit_rejects: tuple[EngineIdentity, ...]


@dataclass
class EngineRuntime:
    """A running engine bundle with its semaphore and policy."""

    engine: VisionEngine
    policy: EnginePolicy
    semaphore: asyncio.Semaphore


@dataclass
class _RaceContext:
    """Per-invocation mutable state for a single vision race run."""

    worker_results: list[EngineResult] = field(default_factory=list)
    rejects: list[EngineIdentity] = field(default_factory=list)
    active_tasks: set[asyncio.Task[EngineResult]] = field(default_factory=set)


class ObservationValidator(Protocol):
    """Validates a raw OCR observation against known chart data."""

    async def validate(
        self, observation: OcrObservation,
    ) -> ValidatedObservation: ...


# ── Helpers ──────────────────────────────────────────────────────────────────


def _error_to_failure(e: VisionEngineError) -> CircuitFailure:
    """Map a VisionEngineError subtype to the appropriate CircuitFailure.

    This import is deferred to avoid circular dependencies at module level.
    """
    from pjsk_core.domain.ocr import (
        VisionConnectionError,
        VisionRateLimitError,
        VisionServerError,
        VisionTimeoutError,
    )

    if isinstance(e, VisionTimeoutError):
        return CircuitFailure.TIMEOUT
    if isinstance(e, VisionConnectionError):
        return CircuitFailure.CONNECTION
    if isinstance(e, VisionRateLimitError):
        return CircuitFailure.RATE_LIMITED
    if isinstance(e, VisionServerError):
        return CircuitFailure.SERVER_ERROR
    return CircuitFailure.INVALID_RESPONSE


def _get_chart_id(v: ValidatedObservation) -> int | None:
    """Safely extract the chart id from a validated observation."""
    if v.primary is None or v.primary.chart is None:
        return None
    return v.primary.chart.id


# ── VisionRace orchestrator ──────────────────────────────────────────────────


class VisionRace:
    """Run multiple vision engines concurrently, detect consensus,
    handle degradation, and manage circuit-breaker lifecycle.

    **Permit ownership rule:** every worker owns its own permit.
    The orchestrator *only* checks circuit state for filtering;
    it never calls ``record_success``, ``record_failure``, or ``release``.
    """

    def __init__(
        self,
        runtimes: Sequence[EngineRuntime],
        breaker: CircuitBreaker,
        validator: ObservationValidator,
        policy: VisionRacePolicy,
    ) -> None:
        # Validate identity consistency
        for r in runtimes:
            if r.policy.engine_id != r.engine.identity.engine_id:
                raise ValueError(
                    f"Engine {r.policy.engine_id}: policy.engine_id does not "
                    f"match engine.identity.engine_id "
                    f"({r.engine.identity.engine_id})"
                )

        # Validate provider constraints among enabled runtimes
        enabled = [r for r in runtimes if r.policy.enabled]
        enabled_providers = [r.engine.identity.provider for r in enabled]
        if len(set(enabled_providers)) != len(enabled_providers):
            raise ValueError(
                f"Duplicate providers among enabled engines: "
                f"{enabled_providers}"
            )
        if len(set(enabled_providers)) > 3:
            raise ValueError(
                f"At most 3 distinct providers allowed, "
                f"got {len(set(enabled_providers))}"
            )

        self._runtimes = tuple(runtimes)
        self._breaker = breaker
        self._validator = validator
        self._policy = policy

    # ── Public entry point ───────────────────────────────────────────────

    async def run(self, image: bytes) -> VisionRaceOutcome:
        """Run the vision race against *image*.

        Steps:
        1. Filter to enabled runtimes.
        2. Create per-invocation context.
        3. Start all enabled workers concurrently (circuit-breaker
           state is managed per-worker via acquire()).
        4. Wait for first consensus, all finished, or global timeout.
        """
        runtimes = [r for r in self._runtimes if r.policy.enabled]
        if not runtimes:
            return VisionRaceOutcome(
                decision=VisionRaceDecision.NO_AVAILABLE_ENGINES,
                selected=None,
                consensus=None,
                results=(),
                circuit_rejects=(),
            )

        ctx = _RaceContext()
        active = sorted(runtimes, key=lambda r: r.policy.priority)

        try:
            async with asyncio.timeout(self._policy.global_timeout_seconds):
                return await self._collect(ctx, image, active)
        except TimeoutError:
            return await self._finish_global_timeout(ctx)
        except asyncio.CancelledError:
            await self._cancel_all(ctx)
            raise

    # ── Internal helpers ────────────────────────────────────────────────

    async def _collect(
        self,
        ctx: _RaceContext,
        image: bytes,
        active: list[EngineRuntime],
    ) -> VisionRaceOutcome:
        """Create worker tasks and process results as they arrive.

        Returns as soon as consensus is reached or all workers finish.
        """
        ctx.worker_results.clear()
        ctx.active_tasks.clear()

        for r in active:
            task = asyncio.create_task(self._worker(ctx, r, image))
            ctx.active_tasks.add(task)

        pending = set(ctx.active_tasks)
        while pending:
            done, pending = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Await each finished task so exceptions surface
            for task in done:
                try:
                    await task
                except Exception:
                    pass  # Worker already appended to ctx.worker_results

            # Check for consensus (discard outcome — rebuild after drain)
            decision, _ = self._evaluate_consensus(ctx)
            if decision is not None:
                # Cancel remaining workers first, then drain so their
                # CANCELLED_BY_CONSENSUS results are collected into
                # ctx.worker_results before building the final outcome.
                for t in pending:
                    t.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                # Rebuild outcome with all results including cancelled ones
                _, outcome = self._evaluate_consensus(ctx)
                assert outcome is not None
                return outcome

        # All workers finished, no consensus
        return self._final_decision(ctx)

    def _evaluate_consensus(
        self,
        ctx: _RaceContext,
    ) -> tuple[VisionRaceDecision | None, VisionRaceOutcome | None]:
        """Check current results for consensus.

        Returns ``(CONSENSUS, outcome)`` if enough providers agree on the
        same (chart_id, difficulty, judgements) tuple, or ``(None, None)``.
        """
        successes = [
            r
            for r in ctx.worker_results
            if r.status == EngineResultStatus.SUCCESS
            and r.validated is not None
            and r.validated.status == ValidationStatus.STRONG
        ]

        # Group by (chart_id, difficulty, judgements) -> providers
        groups: dict[
            tuple[int | None, Difficulty, Judgements],
            dict[str, tuple[EngineIdentity, ValidatedObservation]],
        ] = {}
        for r in successes:
            v = r.validated
            obs = r.observation
            if v is None or obs is None:
                continue
            chart_id = _get_chart_id(v)
            key = (
                chart_id,
                obs.difficulty,
                obs.judgements,
            )
            if key[0] is None:
                continue
            if key not in groups:
                groups[key] = {}
            provider = r.identity.provider
            if provider not in groups[key]:
                groups[key][provider] = (r.identity, v)

        for _key, provider_votes in groups.items():
            if len(provider_votes) >= self._policy.consensus_threshold:
                supporting_ids = tuple(
                    sorted(
                        (v[0] for v in provider_votes.values()),
                        key=lambda eid: eid.engine_id,
                    )
                )
                supporting_providers = tuple(sorted(provider_votes.keys()))
                selected_v = next(iter(provider_votes.values()))[1]

                return VisionRaceDecision.CONSENSUS, VisionRaceOutcome(
                    decision=VisionRaceDecision.CONSENSUS,
                    selected=selected_v,
                    consensus=ConsensusMatch(
                        selected=selected_v,
                        supporting_engines=supporting_ids,
                        supporting_providers=supporting_providers,
                    ),
                    results=tuple(
                        sorted(
                            ctx.worker_results,
                            key=lambda r: r.identity.engine_id,
                        )
                    ),
                    circuit_rejects=tuple(ctx.rejects),
                )

        return None, None

    def _final_decision(self, ctx: _RaceContext) -> VisionRaceOutcome:
        """Produce final decision when all workers finished without consensus."""
        successes = [
            r
            for r in ctx.worker_results
            if r.status == EngineResultStatus.SUCCESS
        ]
        strong = [
            r
            for r in successes
            if r.validated and r.validated.status == ValidationStatus.STRONG
        ]

        all_results = tuple(
            sorted(ctx.worker_results, key=lambda r: r.identity.engine_id)
        )

        if not successes:
            return VisionRaceOutcome(
                decision=VisionRaceDecision.ALL_FAILED,
                selected=None,
                consensus=None,
                results=all_results,
                circuit_rejects=tuple(ctx.rejects),
            )

        # Single engine returned a STRONG result (others failed/timeout)
        if len(successes) == 1 and len(strong) == 1:
            return VisionRaceOutcome(
                decision=VisionRaceDecision.DEGRADED_SINGLE,
                selected=strong[0].validated,
                consensus=None,
                results=all_results,
                circuit_rejects=tuple(ctx.rejects),
            )

        # Multiple successes but no consensus
        return VisionRaceOutcome(
            decision=VisionRaceDecision.DISAGREEMENT,
            selected=None,
            consensus=None,
            results=all_results,
            circuit_rejects=tuple(ctx.rejects),
        )

    async def _finish_global_timeout(self, ctx: _RaceContext) -> VisionRaceOutcome:
        """Called when the global timeout fires before all workers finished.

        Cancels remaining workers and collects whatever completed results
        are available.
        """
        # Cancel still-running workers
        for t in ctx.active_tasks:
            if not t.done():
                t.cancel()
        if ctx.active_tasks:
            await asyncio.gather(*ctx.active_tasks, return_exceptions=True)

        # Filter out results from cancelled workers
        real_results = [
            r
            for r in ctx.worker_results
            if r.status
            not in (
                EngineResultStatus.CANCELLED_BY_CONSENSUS,
                EngineResultStatus.CANCELLED_BY_CALLER,
            )
        ]

        all_results = tuple(
            sorted(real_results, key=lambda r: r.identity.engine_id)
        )

        # Check for a single STRONG result (degraded recovery within timeout)
        strong = [
            r.validated
            for r in real_results
            if r.status == EngineResultStatus.SUCCESS
            and r.validated
            and r.validated.status == ValidationStatus.STRONG
        ]

        selected = strong[0] if len(strong) == 1 else None
        return VisionRaceOutcome(
            decision=VisionRaceDecision.GLOBAL_TIMEOUT,
            selected=selected,
            consensus=None,
            results=all_results,
            circuit_rejects=tuple(ctx.rejects),
        )

    async def _cancel_all(self, ctx: _RaceContext) -> None:
        """Cancel all active worker tasks and drain them."""
        for t in ctx.active_tasks:
            if not t.done():
                t.cancel()
        if ctx.active_tasks:
            await asyncio.gather(*ctx.active_tasks, return_exceptions=True)

    async def _worker(
        self,
        ctx: _RaceContext,
        runtime: EngineRuntime,
        image: bytes,
    ) -> EngineResult:
        """Run a single engine, manage its circuit-breaker permit.

        **Permit ownership:** the worker acquires, records (success or
        failure), and releases its own permit. The orchestrator never
        touches it after acquisition.

        **settled flag:** once ``record_success`` or ``record_failure``
        has been called, the permit is *settled* — a subsequent
        ``CancelledError`` releases the permit only if it was never
        settled (cleanup safety net).
        """
        async with runtime.semaphore:
            permit = await self._breaker.acquire(
                runtime.engine.identity.engine_id,
            )
            if permit is None:
                ctx.rejects.append(runtime.engine.identity)
                result = EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.FAILED,
                    observation=None,
                    validated=None,
                    error=None,
                    elapsed_ms=0,
                )
                ctx.worker_results.append(result)
                return result

            settled = False
            started = _time.monotonic()
            try:
                async with asyncio.timeout(runtime.policy.timeout_seconds):
                    observation = await runtime.engine.recognize(
                        image, timeout=runtime.policy.timeout_seconds,
                    )

                # Breaker success recorded BEFORE validation
                # (vendor health != match quality)
                await self._breaker.record_success(permit)
                settled = True

                validated = await self._validator.validate(observation)
                elapsed = int((_time.monotonic() - started) * 1000)
                result = EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.SUCCESS,
                    observation=observation,
                    validated=validated,
                    error=None,
                    elapsed_ms=elapsed,
                )
                ctx.worker_results.append(result)
                return result

            except asyncio.TimeoutError:
                await self._breaker.record_failure(
                    permit, CircuitFailure.TIMEOUT,
                )
                settled = True
                elapsed = int((_time.monotonic() - started) * 1000)
                result = EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.TIMED_OUT,
                    observation=None,
                    validated=None,
                    error=VisionEngineError("timeout"),
                    elapsed_ms=elapsed,
                )
                ctx.worker_results.append(result)
                return result

            except VisionEngineError as e:
                await self._breaker.record_failure(
                    permit, _error_to_failure(e),
                )
                settled = True
                elapsed = int((_time.monotonic() - started) * 1000)
                result = EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.FAILED,
                    observation=None,
                    validated=None,
                    error=e,
                    elapsed_ms=elapsed,
                )
                ctx.worker_results.append(result)
                return result

            except Exception as e:
                # Catch non-VisionEngineError exceptions (e.g. TypeError,
                # ValueError from unexpected data) and wrap them as a
                # VisionResponseError so the worker returns a FAILED result
                # instead of silently vanishing.
                await self._breaker.record_failure(
                    permit, _error_to_failure(VisionEngineError(str(e))),
                )
                settled = True
                elapsed = int((_time.monotonic() - started) * 1000)
                result = EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.FAILED,
                    observation=None,
                    validated=None,
                    error=VisionResponseError(
                        f"Unexpected error from {runtime.engine.identity.engine_id}: {e}"
                    ),
                    elapsed_ms=elapsed,
                )
                ctx.worker_results.append(result)
                return result

            except asyncio.CancelledError:
                if not settled:
                    await self._breaker.release(permit)
                    settled = True
                elapsed = int((_time.monotonic() - started) * 1000)
                result = EngineResult(
                    identity=runtime.engine.identity,
                    status=EngineResultStatus.CANCELLED_BY_CONSENSUS,
                    observation=None,
                    validated=None,
                    error=None,
                    elapsed_ms=elapsed,
                )
                ctx.worker_results.append(result)
                return result
