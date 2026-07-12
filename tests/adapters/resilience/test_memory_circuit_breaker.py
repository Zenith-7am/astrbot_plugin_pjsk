"""Tests for MemoryCircuitBreaker."""
from __future__ import annotations

import asyncio

import pytest

from adapters.resilience.memory_circuit_breaker import MemoryCircuitBreaker
from pjsk_core.ports.circuit_breaker import CircuitFailure, CircuitPermit, CircuitState


class TestMemoryCircuitBreaker:
    @pytest.mark.asyncio
    async def test_closed_returns_permit(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=3)
        permit = await cb.acquire("gemini")
        assert permit is not None
        assert permit.probe is False

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=3)
        for _ in range(3):
            p = await cb.acquire("gemini")
            assert p is not None
            await cb.record_failure(p, CircuitFailure.TIMEOUT)
        assert await cb.state("gemini") == CircuitState.OPEN
        assert await cb.acquire("gemini") is None

    @pytest.mark.asyncio
    async def test_cooldown_enters_half_open(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p = await cb.acquire("gemini")
        assert p is not None
        await cb.record_failure(p, CircuitFailure.TIMEOUT)
        assert await cb.state("gemini") == CircuitState.OPEN
        await asyncio.sleep(0.02)
        p2 = await cb.acquire("gemini")
        assert p2 is not None
        assert p2.probe is True

    @pytest.mark.asyncio
    async def test_probe_success_closes(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p = await cb.acquire("gemini")
        assert p is not None
        await cb.record_failure(p, CircuitFailure.TIMEOUT)
        await asyncio.sleep(0.02)
        p2 = await cb.acquire("gemini")
        assert p2 is not None
        await cb.record_success(p2)
        assert await cb.state("gemini") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_probe_failure_reopens(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p = await cb.acquire("gemini")
        assert p is not None
        await cb.record_failure(p, CircuitFailure.TIMEOUT)
        await asyncio.sleep(0.02)
        p2 = await cb.acquire("gemini")
        assert p2 is not None
        await cb.record_failure(p2, CircuitFailure.SERVER_ERROR)
        assert await cb.state("gemini") == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_two_concurrent_half_open_only_one_probe(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p0 = await cb.acquire("gemini")
        assert p0 is not None
        await cb.record_failure(p0, CircuitFailure.TIMEOUT)
        await asyncio.sleep(0.02)

        async def acq() -> CircuitPermit | None:
            return await cb.acquire("gemini")

        p1, p2 = await asyncio.gather(acq(), acq())
        permits = [p for p in (p1, p2) if p is not None]
        assert len(permits) == 1
        assert permits[0].probe is True

    @pytest.mark.asyncio
    async def test_release_probe_frees_slot(self) -> None:
        cb = MemoryCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        p0 = await cb.acquire("gemini")
        assert p0 is not None
        await cb.record_failure(p0, CircuitFailure.TIMEOUT)
        await asyncio.sleep(0.02)
        p = await cb.acquire("gemini")
        assert p is not None
        await cb.release(p)
        assert await cb.state("gemini") == CircuitState.OPEN
        # After another cooldown, should be able to probe again
        await asyncio.sleep(0.02)
        p2 = await cb.acquire("gemini")
        assert p2 is not None
        assert p2.probe is True
