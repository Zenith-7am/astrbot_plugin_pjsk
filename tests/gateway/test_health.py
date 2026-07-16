"""Tests for gateway.health."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway.health import build_health, register_health_route


class TestHealthResponse:
    def test_build_health_structure_and_no_secrets(self) -> None:
        state = build_health(bot_count=0)
        assert state["status"] == "degraded"
        assert state["gateway"] == "ok"
        assert state["onebot"] == "disconnected"
        assert state["runtime"] == "unknown"
        assert state["database"] == "unknown"
        assert "gateway_version" in state
        assert "uptime_seconds" in state
        for v in state.values():
            if isinstance(v, str):
                assert "token" not in v.lower()
                assert "key" not in v.lower()
        assert "/opt" not in str(state)

    def test_build_health_when_connected(self) -> None:
        state = build_health(bot_count=1)
        assert state["status"] == "degraded"  # runtime is unknown (no Runtime set)
        assert state["onebot"] == "connected"
        assert state["gateway"] == "ok"

    def test_build_health_all_fields_present(self) -> None:
        state = build_health(bot_count=2)
        for field in ("status", "gateway", "onebot", "runtime", "database",
                       "gateway_version", "uptime_seconds"):
            assert field in state, f"Missing field: {field}"

    def test_health_endpoint_returns_200(self) -> None:
        app = FastAPI()
        register_health_route(app)
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded")
        assert "gateway" in body
        assert "onebot" in body
        assert "runtime" in body
        assert "database" in body
        assert "gateway_version" in body
        assert "uptime_seconds" in body

    def test_health_endpoint_no_secrets(self) -> None:
        app = FastAPI()
        register_health_route(app)
        client = TestClient(app)
        resp = client.get("/health")
        body_str = resp.text.lower()
        assert "token" not in body_str
        assert "key" not in body_str
        assert "/opt" not in body_str
