"""Tests for adapters.config.vision -- load_vision_race_policy."""
from __future__ import annotations

import pytest

from adapters.config.vision import load_vision_race_policy


class TestLoadVisionRacePolicy:
    """Cover normal, empty, and all-disabled configs."""

    def test_minimal_config(self) -> None:
        """A well-formed dict with two engines produces a valid policy."""
        raw = {
            "engines": {
                "gemini-2.5-flash": {
                    "provider": "google",
                    "enabled": True,
                    "priority": 1,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
                "zhipu-glm-4v-flash": {
                    "provider": "zhipu",
                    "enabled": True,
                    "priority": 2,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
            },
            "global_timeout_seconds": 30.0,
            "consensus_threshold": 2,
        }

        policy = load_vision_race_policy(raw)

        assert len(policy.engines) == 2
        assert policy.global_timeout_seconds == 30.0
        assert policy.consensus_threshold == 2
        assert policy.engines[0].engine_id == "gemini-2.5-flash"
        assert policy.engines[0].enabled is True
        assert policy.engines[1].engine_id == "zhipu-glm-4v-flash"

    def test_zero_engines_raises(self) -> None:
        """An empty engines dict must raise ValueError."""
        with pytest.raises(ValueError):
            load_vision_race_policy({"engines": {}})

    def test_disabled_engines_filtered_correctly(self) -> None:
        """All engines disabled must raise ValueError because no engine is enabled."""
        raw = {
            "engines": {
                "g": {
                    "provider": "google",
                    "enabled": False,
                    "priority": 1,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
            },
            "global_timeout_seconds": 30.0,
        }

        with pytest.raises(ValueError, match="at least one"):
            load_vision_race_policy(raw)

    def test_missing_provider_raises(self) -> None:
        """Engine without a provider field must raise ValueError."""
        raw = {
            "engines": {
                "g": {
                    "enabled": True,
                    "priority": 1,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
            },
            "global_timeout_seconds": 30.0,
        }
        with pytest.raises(ValueError, match="required and must be non-empty"):
            load_vision_race_policy(raw)

    def test_empty_provider_raises(self) -> None:
        """Engine with empty provider must raise ValueError."""
        raw = {
            "engines": {
                "g": {
                    "provider": "",
                    "enabled": True,
                    "priority": 1,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
            },
            "global_timeout_seconds": 30.0,
        }
        with pytest.raises(ValueError, match="required and must be non-empty"):
            load_vision_race_policy(raw)

    def test_duplicate_provider_raises(self) -> None:
        """Two enabled engines with the same provider must raise ValueError."""
        raw = {
            "engines": {
                "g": {
                    "provider": "google",
                    "enabled": True,
                    "priority": 1,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
                "g2": {
                    "provider": "google",
                    "enabled": True,
                    "priority": 2,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
            },
            "global_timeout_seconds": 30.0,
        }
        with pytest.raises(ValueError, match="Duplicate provider"):
            load_vision_race_policy(raw)

    def test_same_provider_disabled_does_not_raise(self) -> None:
        """Two engines with same provider, one disabled, should not raise."""
        raw = {
            "engines": {
                "g": {
                    "provider": "google",
                    "enabled": True,
                    "priority": 1,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
                "g2": {
                    "provider": "google",
                    "enabled": False,
                    "priority": 2,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
                "z": {
                    "provider": "zhipu",
                    "enabled": True,
                    "priority": 3,
                    "timeout": 15.0,
                    "max_concurrency": 3,
                },
            },
            "global_timeout_seconds": 30.0,
        }
        policy = load_vision_race_policy(raw)
        assert len(policy.engines) == 3
        assert policy.engines[0].enabled is True
        assert policy.engines[1].enabled is False
