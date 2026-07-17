# OCR Result Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independently previewable `ocr_result` Canvas image template for OCR score results.

**Architecture:** `render_service/functions/ocr_result.js` is a presentation-only function registered through the existing loader.  A fictional JSON fixture drives the existing FastAPI/Playwright service, and the preview CLI chooses that fixture when requested.  No gateway, OCR, database, or renderer-port changes occur.

**Tech Stack:** JavaScript Canvas 2D, FastAPI, Playwright, pytest.

## Global Constraints

- Canvas dimensions are exactly 1200 x 800.
- JavaScript renders only precomputed input values; it never calculates rating or accuracy.
- No external URLs, fonts, character art, user logs, or filesystem output are used by the template.
- Fixture data is fictional and must not include a real QQ number.
- A missing/invalid jacket renders an in-card placeholder rather than failing the request.

---

### Task 1: Define the fixture and preview entrypoint

**Files:**
- Create: `tests/fixtures/render/ocr_result_preview.json`
- Modify: `tools/render_preview.py:24-47`
- Modify: `tests/render_service/test_dev_workflow.py`

**Interfaces:**
- Consumes: `tools.render_preview._DEFAULT_FIXTURES: dict[str, Path]`.
- Produces: `ocr_result_preview.json`, accepted by `python tools/render_preview.py --template ocr_result`.

- [ ] **Step 1: Write the failing tests**

```python
def test_ocr_result_fixture_is_valid_and_fictional() -> None:
    data = json.loads(_ocr_fixture_path().read_text(encoding="utf-8"))
    assert data["title"] == "Render Preview Song"
    assert data["qqNumber"] == "10000001"
    assert set(data["judges"]) == {"perfect", "great", "good", "bad", "miss"}

def test_preview_parser_accepts_ocr_result() -> None:
    args = render_preview.build_parser().parse_args(["--template", "ocr_result"])
    assert args.template == "ocr_result"
```

- [ ] **Step 2: Run the focused test and verify it fails because the fixture and CLI choice are absent**

Run: `python -m pytest tests/render_service/test_dev_workflow.py -k ocr_result -v`

Expected: FAIL with a missing fixture or invalid `--template` choice.

- [ ] **Step 3: Add the fixture and CLI mapping**

```python
_DEFAULT_FIXTURES = {
    "b20": _PROJECT_ROOT / "tests" / "fixtures" / "render" / "b20_preview.json",
    "ocr_result": _PROJECT_ROOT / "tests" / "fixtures" / "render" / "ocr_result_preview.json",
}
# choices=["b20", "difficulty", "ocr_result"]
```

Use the exact input contract from the design document and `jacket: null`.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `python -m pytest tests/render_service/test_dev_workflow.py -k ocr_result -v`

Expected: PASS.

### Task 2: Implement and exercise the Canvas template

**Files:**
- Create: `render_service/functions/ocr_result.js`
- Modify: `tests/render_service/test_dev_workflow.py`

**Interfaces:**
- Consumes: the fixture fields in Task 1.
- Produces: `window.__renderFunctions["ocr_result"]`, an async function that draws `#render-canvas` at 1200 x 800.

- [ ] **Step 1: Write the failing visual integration test**

```python
def test_render_ocr_result_fixture(self) -> None:
    with TestClient(svc.app) as client:
        response = client.post("/render/ocr_result", json=_load_ocr_result_fixture())
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == _PNG_SIGNATURE
    assert len(response.content) > 1000
```

Also assert that `/health` lists `ocr_result` after startup.

- [ ] **Step 2: Run it and verify it fails because `/render/ocr_result` is unknown**

Run: `python -m pytest tests/render_service/test_dev_workflow.py -k ocr_result -v`

Expected: FAIL with HTTP 404, or skipped only when Chromium is unavailable.

- [ ] **Step 3: Implement the minimal Canvas renderer**

Implement `ocr_result.js` with these helpers:

```javascript
function textOr(value, fallback) { return String(value ?? fallback); }
function numberOr(value, fallback = 0) { return Number.isFinite(Number(value)) ? Number(value) : fallback; }
function drawCoverOrPlaceholder(ctx, image, x, y, size) { /* clip cover or draw placeholder */ }
function drawFittedText(ctx, text, x, y, maxWidth, startSize, minSize) { /* shrink, then ellipsise */ }
```

Set `canvas.width = 1200` and `canvas.height = 800`; draw the light header,
metadata, five-row judgement panel, right-side Rating/ACC stack, and full QQ
number at the lower-right.  Await jacket loading only for a non-empty data URL
and catch its failure locally.

- [ ] **Step 4: Run the focused visual test and verify it passes**

Run: `python -m pytest tests/render_service/test_dev_workflow.py -k ocr_result -v`

Expected: PASS, or one explicitly reported visual skip when Chromium is absent.

- [ ] **Step 5: Manually generate a local preview**

Run: `python tools/render_preview.py --template ocr_result`

Expected: an `artifacts/render-preview/ocr_result_<timestamp>.png` file after the local render service is running.

### Task 3: Verify the template does not regress existing render templates

**Files:**
- Verify only: `tests/render_service/test_render_service.py`
- Verify only: `tests/render_service/test_dev_workflow.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: verified function discovery and PNG response behaviour for `b20`, `difficulty`, and `ocr_result`.

- [ ] **Step 1: Run renderer unit and workflow tests**

Run: `python -m pytest tests/render_service/test_render_service.py tests/render_service/test_dev_workflow.py -v`

Expected: PASS, with visual tests skipped only if Chromium is unavailable.

- [ ] **Step 2: Run the project quality checks required by this scope**

Run: `python -m ruff check render_service/functions/ocr_result.js tools/render_preview.py tests/render_service`

Expected: the command either reports clean Python files or excludes the JavaScript file according to the existing Ruff configuration; no newly introduced Python lint failures.

- [ ] **Step 3: Commit the focused change**

```bash
git add render_service/functions/ocr_result.js tests/fixtures/render/ocr_result_preview.json tools/render_preview.py tests/render_service/test_dev_workflow.py docs/superpowers/specs/2026-07-17-ocr-result-card-design.md docs/superpowers/plans/2026-07-17-ocr-result-card.md
git commit -m "feat: add OCR result render template"
```
