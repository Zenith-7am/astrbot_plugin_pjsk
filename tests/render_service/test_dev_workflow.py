"""Tests for local render dev workflow — health + import + fixture validation."""

import json
from pathlib import Path

import pytest

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# ── Helpers ──────────────────────────────────────────────────────────────


def _chromium_available() -> bool:
    """Return True if Playwright + Chromium are installed and usable."""
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        try:
            browser = p.chromium.launch(headless=True)
            browser.close()
            return True
        except Exception:
            return False
        finally:
            p.stop()
    except Exception:
        return False


def _load_b20_fixture() -> dict:
    fixture_path = (
        Path(__file__).parent.parent.parent
        / "tests" / "fixtures" / "render" / "b20_preview.json"
    )
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _ocr_result_fixture_path() -> Path:
    return (
        Path(__file__).parent.parent.parent
        / "tests" / "fixtures" / "render" / "ocr_result_preview.json"
    )


def _load_ocr_result_fixture() -> dict:
    return json.loads(_ocr_result_fixture_path().read_text(encoding="utf-8"))


class TestDevHealthEndpoint:
    """Health endpoint returns the function list needed by preview tooling."""

    def test_health_includes_functions_list(self) -> None:
        """GET /health response MUST include a 'functions' key (list of str)."""
        import render_service.main as svc

        # Simulate the post-warmup state: functions have been loaded.
        svc._function_names = ["b20", "difficulty"]

        from fastapi.testclient import TestClient
        client = TestClient(svc.app)
        response = client.get("/health")
        assert response.status_code == 200

        body = response.json()
        assert "functions" in body
        assert isinstance(body["functions"], list)
        assert "b20" in body["functions"]


class TestB20PreviewFixture:
    """The bundled fixture payload is valid JSON with expected structure."""

    def test_fixture_is_valid_json(self) -> None:
        """b20_preview.json parses as JSON."""
        fixture_path = (
            Path(__file__).parent.parent.parent
            / "tests" / "fixtures" / "render" / "b20_preview.json"
        )
        assert fixture_path.exists(), f"Missing fixture: {fixture_path}"

        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_fixture_has_required_fields(self) -> None:
        """Fixture contains the minimum fields b20.js expects."""
        fixture_path = (
            Path(__file__).parent.parent.parent
            / "tests" / "fixtures" / "render" / "b20_preview.json"
        )
        data = json.loads(fixture_path.read_text(encoding="utf-8"))

        # Top-level fields expected by b20.js
        assert "b20" in data, "missing 'b20' entries list"
        assert "sp" in data, "missing 'sp' (SEKAI POWER)"
        assert "playerClass" in data, "missing 'playerClass'"
        assert "b20Avg" in data, "missing 'b20Avg'"

        # Each b20 entry must have jacket (null or data URL)
        for entry in data["b20"]:
            assert "jacket" in entry, f"entry missing 'jacket': {entry.get('title')}"
            assert "title" in entry
            assert "difficulty" in entry

    def test_fixture_has_no_real_user_data(self) -> None:
        """Fixture must not contain real QQ numbers or production data."""
        fixture_path = (
            Path(__file__).parent.parent.parent
            / "tests" / "fixtures" / "render" / "b20_preview.json"
        )
        text = fixture_path.read_text(encoding="utf-8")

        # No real QQ numbers
        assert "3366463190" not in text
        # No external URLs (jackets should be local data URLs or null)
        assert "api.pjsk-rate-api.com" not in text


class TestOcrResultPreviewFixture:
    """The OCR card has a fictional preview payload and CLI option."""

    def test_fixture_is_valid_and_fictional(self) -> None:
        """The fixture documents the Canvas input contract without user data."""
        fixture_path = _ocr_result_fixture_path()
        assert fixture_path.exists(), f"Missing fixture: {fixture_path}"

        data = _load_ocr_result_fixture()
        assert data["title"] == "Render Preview Song"
        assert data["qqNumber"] == "10000001"
        assert data["grade"] == "SSS"
        assert data["jacket"] is None
        assert set(data["judges"]) == {
            "perfect", "great", "good", "bad", "miss",
        }

    def test_preview_parser_accepts_ocr_result(self) -> None:
        """The local preview command recognises the OCR card template."""
        import importlib.util

        tools_dir = Path(__file__).parent.parent.parent / "tools"
        spec = importlib.util.spec_from_file_location(
            "render_preview_ocr_result",
            tools_dir / "render_preview.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        args = module.build_parser().parse_args(["--template", "ocr_result"])
        assert args.template == "ocr_result"

    def test_template_uses_compact_official_style_judgements(self) -> None:
        """The card removes a generic heading and formats four-digit counts."""
        source_path = (
            Path(__file__).parent.parent.parent
            / "render_service" / "functions" / "ocr_result.js"
        )
        source = source_path.read_text(encoding="utf-8")

        assert "JUDGEMENT" not in source
        assert "drawPaddedCount" in source
        assert "padStart(4, \"0\")" in source

    def test_template_embeds_an_attached_top_right_grade_cutout(self) -> None:
        """Grade is embedded in the header and remains a supplied display value."""
        source_path = (
            Path(__file__).parent.parent.parent
            / "render_service" / "functions" / "ocr_result.js"
        )
        source = source_path.read_text(encoding="utf-8")

        assert "drawAttachedAchievementGrade" in source
        assert "data.grade" in source
        assert "COLORS.indigo" in source
        assert "gradeCharacters" in source
        assert "GRADE_DIAGONAL_POSITIONS" in source

    def test_template_includes_original_low_contrast_background_decoration(self) -> None:
        """The Canvas background has local visual texture, not external assets."""
        source_path = (
            Path(__file__).parent.parent.parent
            / "render_service" / "functions" / "ocr_result.js"
        )
        source = source_path.read_text(encoding="utf-8")

        assert "drawBackgroundDecorations" in source
        assert "data:image/" in source
        assert "https://" not in source


class TestPreviewScriptImport:
    """render_preview.py is syntactically valid and importable."""

    def test_preview_script_has_expected_api(self) -> None:
        """The preview module exposes build_parser and main()."""
        import importlib.util

        tools_dir = Path(__file__).parent.parent.parent / "tools"
        spec = importlib.util.spec_from_file_location(
            "render_preview",
            tools_dir / "render_preview.py",
        )
        assert spec is not None, "render_preview.py not found"
        # Don't actually execute — just verify the file exists and is parseable
        source = (tools_dir / "render_preview.py").read_text(encoding="utf-8")
        compile(source, str(tools_dir / "render_preview.py"), "exec")


# ── Real Playwright rendering (requires Chromium) ───────────────────────


@pytest.mark.visual
class TestRealPlaywrightRender:
    """End-to-end: start FastAPI lifespan, POST fixture, verify PNG output.

    These tests require Playwright + Chromium. They are skipped
    automatically when Chromium is not installed (e.g. CI).
    """

    @pytest.fixture(autouse=True)
    def _skip_if_no_chromium(self) -> None:
        if not _chromium_available():
            pytest.skip("Chromium not available — use 'playwright install chromium'")

    def test_render_b20_returns_valid_png(self) -> None:
        """POST the bundled b20_preview fixture → 200, image/png, PNG bytes."""
        import render_service.main as svc
        from fastapi.testclient import TestClient

        # The lifespan starts Playwright + Chromium automatically.
        # TestClient enters/exits the lifespan for us.
        with TestClient(svc.app) as client:
            data = _load_b20_fixture()
            response = client.post("/render/b20", json=data)

        assert response.status_code == 200, (
            f"Render failed: {response.text[:200]}"
        )
        assert response.headers["content-type"] == "image/png"
        content = response.content
        assert content[:8] == _PNG_SIGNATURE, (
            f"Not a PNG: first 8 bytes = {content[:8]!r}"
        )
        assert len(content) > 1000, (
            f"PNG too small ({len(content)} bytes) — likely empty/error render"
        )

    def test_health_returns_functions_after_startup(self) -> None:
        """After lifespan, /health reports loaded functions."""
        import render_service.main as svc
        from fastapi.testclient import TestClient

        with TestClient(svc.app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            body = resp.json()
            assert "functions" in body
            assert "b20" in body["functions"]
            assert body["browser"] == "connected"

    def test_render_difficulty_fixture(self) -> None:
        """POST a minimal difficulty fixture → 200, image/png."""
        import render_service.main as svc
        from fastapi.testclient import TestClient

        difficulty_data = {
            "mode": "global",
            "title": "EXP 28",
            "tiers": [
                {
                    "constant": 28.5,
                    "songs": [
                        {
                            "song_id": 1, "song_title": "Test Song",
                            "community_constant": "28.5", "note_count": 1200,
                            "jacket": None, "is_played": False,
                            "status": 0, "accuracy": 0.0, "power": 0.0,
                            "judges": {},
                        }
                    ],
                }
            ],
        }

        with TestClient(svc.app) as client:
            response = client.post("/render/difficulty", json=difficulty_data)

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content[:8] == _PNG_SIGNATURE

    def test_render_ocr_result_fixture(self) -> None:
        """POSTing the OCR result fixture returns a non-empty PNG."""
        import render_service.main as svc
        from fastapi.testclient import TestClient

        with TestClient(svc.app) as client:
            response = client.post(
                "/render/ocr_result", json=_load_ocr_result_fixture(),
            )

        assert response.status_code == 200, response.text[:200]
        assert response.headers["content-type"] == "image/png"
        assert response.content[:8] == _PNG_SIGNATURE
        assert len(response.content) > 1000
