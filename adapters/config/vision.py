"""Parse AstrBot config dict into VisionRacePolicy."""
from __future__ import annotations

from typing import Any, cast

from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy


def load_vision_race_policy(raw: dict[str, Any]) -> VisionRacePolicy:
    """Build a :class:`VisionRacePolicy` from a raw config dictionary.

    Parameters
    ----------
    raw:
        Expected shape::

            {
                "engines": {
                    "<engine_id>": {
                        "provider": str,      # used by adapter wiring, not stored
                        "enabled": bool,       # default True
                        "priority": int,       # default len(engines) + 1
                        "timeout": float,      # per-call timeout, default 15.0
                        "max_concurrency": int, # default 3
                    },
                    ...
                },
                "global_timeout_seconds": float,  # default 30.0
                "consensus_threshold": int,       # default 2
            }

    Returns
    -------
    VisionRacePolicy
        A validated policy instance.

    Raises
    ------
    ValueError
        If ``engines`` is missing, empty, or all engines are disabled
        (or any field violates :class:`VisionRacePolicy` invariants).
    """
    engines_raw = cast("dict[str, dict[str, Any]]", raw.get("engines", {}))
    if not engines_raw:
        raise ValueError("'engines' must be a non-empty dict")

    policies: list[EnginePolicy] = []
    for engine_id, cfg in engines_raw.items():
        policies.append(EnginePolicy(
            engine_id=engine_id,
            priority=int(cfg.get("priority", len(policies) + 1)),
            enabled=bool(cfg.get("enabled", True)),
            timeout_seconds=float(cfg.get("timeout", 15.0)),
            max_concurrency=int(cfg.get("max_concurrency", 3)),
        ))

    return VisionRacePolicy(
        engines=tuple(policies),
        global_timeout_seconds=float(raw.get("global_timeout_seconds", 30.0)),
        consensus_threshold=int(raw.get("consensus_threshold", 2)),
    )
