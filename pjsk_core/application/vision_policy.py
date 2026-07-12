"""Vision race engine policies.

EnginePolicy defines per-engine configuration (timeout, concurrency, priority).
VisionRacePolicy wraps multiple EnginePolicies with global timeout and consensus
threshold.  Both are frozen dataclasses validated in ``__post_init__``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnginePolicy:
    """Configuration for a single vision engine.

    Parameters
    ----------
    engine_id:
        Unique identifier for the engine (e.g. ``"gemini-2.5-flash"``).
    priority:
        Starting priority (1 = highest).  Must be >= 1.
    enabled:
        Whether the engine is active for race participation.
    timeout_seconds:
        Per-call timeout in seconds.  Must be > 0.
    max_concurrency:
        Maximum parallel calls to this engine.  Must be >= 1.
    """

    engine_id: str
    priority: int
    enabled: bool
    timeout_seconds: float
    max_concurrency: int

    def __post_init__(self) -> None:
        if not self.engine_id:
            raise ValueError("engine_id must not be empty")
        if self.priority < 1:
            raise ValueError(f"priority must be >= 1, got {self.priority}")
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be > 0, got {self.timeout_seconds}"
            )
        if self.max_concurrency < 1:
            raise ValueError(
                f"max_concurrency must be >= 1, got {self.max_concurrency}"
            )


@dataclass(frozen=True)
class VisionRacePolicy:
    """High-level race configuration that wraps one or more
    :class:`EnginePolicy` instances.

    Parameters
    ----------
    engines:
        Tuple of :class:`EnginePolicy` entries for all candidate engines.
        At least one must be enabled; IDs must be unique.
    global_timeout_seconds:
        Wall-clock timeout for the entire race.  Must be > 0.
    consensus_threshold:
        Number of matching results required for strong consensus.
        Must be >= 2 and <= number of enabled engines.
    """

    engines: tuple[EnginePolicy, ...]
    global_timeout_seconds: float
    consensus_threshold: int = 2

    def __post_init__(self) -> None:
        if self.global_timeout_seconds <= 0:
            raise ValueError(
                f"global_timeout_seconds must be > 0, "
                f"got {self.global_timeout_seconds}"
            )
        if self.consensus_threshold < 2:
            raise ValueError(
                f"consensus_threshold must be >= 2, got {self.consensus_threshold}"
            )

        enabled = [e for e in self.engines if e.enabled]
        if not enabled:
            raise ValueError("at least one engine must be enabled")

        ids = [e.engine_id for e in self.engines]
        if len(ids) != len(set(ids)):
            raise ValueError("engine_id must be unique across engines")

        if self.consensus_threshold > len(enabled):
            raise ValueError(
                f"consensus_threshold ({self.consensus_threshold}) "
                f"exceeds enabled engines ({len(enabled)})"
            )
