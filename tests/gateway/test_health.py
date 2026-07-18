"""Tests for gateway.health."""
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway.health import build_health, register_health_route, set_runtime


class _FakeRuntime:
    """Minimal Runtime stub for health tests."""

    def __init__(self, status_value: str = "ready") -> None:
        from pjsk_runtime.runtime import RuntimeStatus
        self.status = RuntimeStatus(status_value)
        self.db_conn = AsyncMock()
        self.db_conn.execute_fetchall = AsyncMock(return_value=[{"ok": 1}])
        self.chart_db_conn = AsyncMock()
        self.chart_db_conn.execute_fetchall = AsyncMock(return_value=[{"ok": 1}])
        self.score_db_conn = AsyncMock()
        self.close = AsyncMock()


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


class TestHealthWithRuntime:
    """Health reports runtime=ready and database=ok when set_runtime is called."""

    def teardown_method(self) -> None:
        # Reset runtime global after each test
        set_runtime(None)

    def test_runtime_ready_after_set(self) -> None:
        """After set_runtime(ready_runtime), health shows runtime=ready, database=ok."""
        rt = _FakeRuntime("ready")
        set_runtime(rt)

        state = build_health(bot_count=1)
        assert state["runtime"] == "ready"
        assert state["database"] == "ok"
        assert state["status"] == "ok"

    def test_runtime_starting_shows_degraded(self) -> None:
        """While runtime is starting, overall is degraded."""
        rt = _FakeRuntime("starting")
        set_runtime(rt)

        state = build_health(bot_count=1)
        assert state["runtime"] == "starting"
        assert state["status"] == "degraded"

    def test_runtime_stopped_shows_down(self) -> None:
        """After shutdown, runtime=stopped → overall=down."""
        rt = _FakeRuntime("stopped")
        set_runtime(rt)

        state = build_health(bot_count=1)
        assert state["runtime"] == "stopped"
        assert state["status"] == "down"

    def test_endpoint_reflects_runtime(self) -> None:
        """GET /health returns runtime=ready, database=ok after set_runtime.
        (bot_count=0 in test → overall=degraded even with ready runtime)"""
        rt = _FakeRuntime("ready")
        set_runtime(rt)

        app = FastAPI()
        register_health_route(app)
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["runtime"] == "ready"
        assert body["database"] == "ok"

    def test_set_runtime_none_resets_to_unknown(self) -> None:
        """set_runtime(None) → runtime=unknown again."""
        rt = _FakeRuntime("ready")
        set_runtime(rt)
        set_runtime(None)

        state = build_health(bot_count=0)
        assert state["runtime"] == "unknown"
        assert state["database"] == "unknown"
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
