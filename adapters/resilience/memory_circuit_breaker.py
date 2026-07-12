"""In-process memory-based circuit breaker for vision engine resilience.

Uses asyncio.Lock for thread-safe state transitions.
"""
from __future__ import annotations

import asyncio
import time as _time

from pjsk_core.ports.circuit_breaker import (
    CircuitFailure,
    CircuitPermit,
    CircuitState,
)


class MemoryCircuitBreaker:
    """In-memory circuit breaker implementing the CircuitBreaker protocol.

    Each engine has a per-engine-id state machine.  The threshold of
    consecutive failures opens the circuit.  After cooldown_seconds the
    circuit transitions to HALF_OPEN, where at most one probe request
    is allowed at a time.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._states: dict[str, CircuitState] = {}
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._probe_active: dict[str, bool] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, engine_id: str) -> CircuitPermit | None:
        async with self._lock:
            state = self._states.get(engine_id, CircuitState.CLOSED)
            if state == CircuitState.CLOSED:
                return CircuitPermit(engine_id, probe=False)
            if state == CircuitState.OPEN:
                if _time.monotonic() >= self._open_until.get(engine_id, 0.0):
                    self._states[engine_id] = CircuitState.HALF_OPEN
                    state = CircuitState.HALF_OPEN
                else:
                    return None
            if state == CircuitState.HALF_OPEN:
                if self._probe_active.get(engine_id, False):
                    return None
                self._probe_active[engine_id] = True
                return CircuitPermit(engine_id, probe=True)
            # Should not reach here, but for exhaustiveness:
            return CircuitPermit(engine_id, probe=False)

    async def record_success(self, permit: CircuitPermit) -> None:
        async with self._lock:
            self._failures[permit.engine_id] = 0
            if permit.probe:
                self._states[permit.engine_id] = CircuitState.CLOSED
                self._probe_active[permit.engine_id] = False

    async def record_failure(
        self,
        permit: CircuitPermit,
        failure: CircuitFailure,
    ) -> None:
        _ = failure  # all failures counted equally
        async with self._lock:
            eid = permit.engine_id
            self._failures[eid] = self._failures.get(eid, 0) + 1
            if permit.probe:
                self._states[eid] = CircuitState.OPEN
                self._open_until[eid] = _time.monotonic() + self._cooldown
                self._probe_active[eid] = False
            elif self._failures[eid] >= self._threshold:
                self._states[eid] = CircuitState.OPEN
                self._open_until[eid] = _time.monotonic() + self._cooldown

    async def release(self, permit: CircuitPermit) -> None:
        if not permit.probe:
            return
        async with self._lock:
            self._states[permit.engine_id] = CircuitState.OPEN
            self._probe_active[permit.engine_id] = False

    async def state(self, engine_id: str) -> CircuitState:
        return self._states.get(engine_id, CircuitState.CLOSED)
