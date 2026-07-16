"""Tests for gateway.adapters.config_loader."""
import pytest
from gateway.adapters.config_loader import load_config, ConfigError


class TestAccessTokenRequired:
    def test_missing_token_raises_config_error(self, monkeypatch: object) -> None:
        monkeypatch.delenv("ONEBOT_ACCESS_TOKEN", raising=False)
        with pytest.raises(ConfigError, match="ONEBOT_ACCESS_TOKEN"):
            load_config()

    def test_present_token_returns_config(self, monkeypatch: object) -> None:
        monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", "test-token-123")
        cfg = load_config()
        assert cfg.onebot_access_token == "test-token-123"

    def test_token_not_visible_in_repr(self, monkeypatch: object) -> None:
        monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", "secret-abc")
        cfg = load_config()
        assert "secret-abc" not in repr(cfg)

    def test_token_is_never_logged(self, monkeypatch: object, caplog: object) -> None:
        monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", "secret-abc")
        load_config()
        assert "secret-abc" not in caplog.text
