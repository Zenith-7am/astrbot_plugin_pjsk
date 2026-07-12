"""Circuit breaker port for vision engine resilience."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitFailure(Enum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class CircuitPermit:
    engine_id: str
    probe: bool  # True = HALF_OPEN probe request


class CircuitBreaker(Protocol):
    async def acquire(self, engine_id: str) -> CircuitPermit | None: ...
    async def record_success(self, permit: CircuitPermit) -> None: ...
    async def record_failure(
        self, permit: CircuitPermit, failure: CircuitFailure,
    ) -> None: ...
    async def release(self, permit: CircuitPermit) -> None: ...
    async def state(self, engine_id: str) -> CircuitState: ...
