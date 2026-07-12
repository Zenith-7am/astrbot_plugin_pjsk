"""Tests for vision engine / race policies."""

import pytest
from pjsk_core.application.vision_policy import EnginePolicy, VisionRacePolicy


class TestEnginePolicy:
    """Cover valid construction and boundary violations."""

    def test_valid_engine_policy(self) -> None:
        ep = EnginePolicy(
            "gemini-2.5-flash",
            priority=1,
            enabled=True,
            timeout_seconds=15.0,
            max_concurrency=3,
        )
        assert ep.engine_id == "gemini-2.5-flash"
        assert ep.priority == 1

    def test_empty_engine_id_raises(self) -> None:
        with pytest.raises(ValueError, match="engine_id"):
            EnginePolicy(
                "", priority=1, enabled=True, timeout_seconds=15.0, max_concurrency=3
            )

    def test_priority_below_1_raises(self) -> None:
        with pytest.raises(ValueError, match="priority"):
            EnginePolicy(
                "g", priority=0, enabled=True, timeout_seconds=15.0, max_concurrency=3
            )

    def test_timeout_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout"):
            EnginePolicy(
                "g", priority=1, enabled=True, timeout_seconds=0, max_concurrency=3
            )

    def test_max_concurrency_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="max_concurrency"):
            EnginePolicy(
                "g", priority=1, enabled=True, timeout_seconds=15.0, max_concurrency=0
            )


class TestVisionRacePolicy:
    """Cover valid construction and combinatorial validation."""

    @staticmethod
    def _make_policy(
        engines: tuple[EnginePolicy, ...] | None = None,
        global_timeout_seconds: float | None = None,
        consensus_threshold: int | None = None,
    ) -> VisionRacePolicy:
        return VisionRacePolicy(
            engines=engines
            if engines is not None
            else (
                EnginePolicy(
                    "g", priority=1, enabled=True, timeout_seconds=15.0, max_concurrency=3
                ),
                EnginePolicy(
                    "z", priority=2, enabled=True, timeout_seconds=15.0, max_concurrency=3
                ),
            ),
            global_timeout_seconds=(
                global_timeout_seconds if global_timeout_seconds is not None else 30.0
            ),
            consensus_threshold=(
                consensus_threshold if consensus_threshold is not None else 2
            ),
        )

    def test_valid_policy(self) -> None:
        policy = self._make_policy()
        assert policy.global_timeout_seconds == 30.0

    def test_zero_enabled_engines_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            self._make_policy(
                engines=(
                    EnginePolicy(
                        "g",
                        priority=1,
                        enabled=False,
                        timeout_seconds=15.0,
                        max_concurrency=3,
                    ),
                )
            )

    def test_duplicate_engine_id_raises(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            self._make_policy(
                engines=(
                    EnginePolicy(
                        "g",
                        priority=1,
                        enabled=True,
                        timeout_seconds=15.0,
                        max_concurrency=3,
                    ),
                    EnginePolicy(
                        "g",
                        priority=2,
                        enabled=True,
                        timeout_seconds=15.0,
                        max_concurrency=3,
                    ),
                )
            )

    def test_consensus_threshold_exceeds_enabled_raises(self) -> None:
        with pytest.raises(ValueError, match="consensus_threshold"):
            self._make_policy(consensus_threshold=3)

    def test_consensus_threshold_below_2_raises(self) -> None:
        with pytest.raises(ValueError, match="consensus_threshold"):
            self._make_policy(consensus_threshold=1)

    def test_global_timeout_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="global_timeout"):
            self._make_policy(global_timeout_seconds=0)
