"""Tests for gateway.health."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway.health import build_health, register_health_route


class TestHealthResponse:
    def test_build_health_structure_and_no_secrets(self):
        state = build_health(bot_count=0)
        assert state["status"] == "degraded"
        assert state["onebot"] == "disconnected"
        assert "gateway_version" in state
        assert "uptime_seconds" in state
        for v in state.values():
            if isinstance(v, str):
                assert "token" not in v.lower()
                assert "key" not in v.lower()
        assert "/opt" not in str(state)

    def test_build_health_when_connected(self):
        state = build_health(bot_count=1)
        assert state["status"] == "ok"
        assert state["onebot"] == "connected"

    def test_health_endpoint_returns_200(self):
        app = FastAPI()
        register_health_route(app)
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded")
        assert "onebot" in body
        assert "gateway_version" in body
        assert "uptime_seconds" in body

    def test_health_endpoint_no_secrets(self):
        app = FastAPI()
        register_health_route(app)
        client = TestClient(app)
        resp = client.get("/health")
        body_str = resp.text.lower()
        assert "token" not in body_str
        assert "key" not in body_str
