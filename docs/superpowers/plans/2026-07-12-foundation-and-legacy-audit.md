> **Status: Superseded** by Phase 5 standalone OneBot gateway direction.
> **Historical reference only.** Do not use as current implementation authority.
> Current spec: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`
> Current governance: `CLAUDE.md` §18.

# PJSK AstrBot Foundation and Legacy Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the new repository's executable architecture, verified pure business rules, port contracts, and a read-only audit of the legacy production database without implementing AstrBot or writing production data.

**Architecture:** Build inward from synchronous domain models to application-facing protocols. Extract only behavior proven by old tests and source. Inspect a copied legacy SQLite database through a read-only audit adapter; this phase neither defines final migration SQL nor changes the old database.

**Tech Stack:** Python 3.11, pytest, pytest-asyncio, dataclasses, typing.Protocol, SQLite read-only URI.

## Global Constraints

- The new repository is `D:\pjsk-astrbot`; the old repository is read-only input.
- Git is the only source of truth; every task ends in a focused commit.
- Domain code is synchronous and performs no I/O.
- Application code depends only on ports, never AstrBot, SQLite, Redis, HTTP, or vendor SDKs.
- No production VPS mutation, database write, service restart, or secret read is allowed in this phase.
- Do not copy old modules wholesale; extract behavior with tests.
- Python 3.11 is the minimum version.

---

## Delivery Roadmap

1. Foundation and legacy audit — this plan.
2. Versioned chart data and SQLite schema/migration.
3. Multi-model vision adapters, race, validation, and candidate flow.
4. Score submission transaction, B20, global ranking, and personal ranking.
5. Renderer contract and FastAPI/Playwright extraction.
6. AstrBot plugin integration and shadow comparison.
7. Atomic HK VPS deployment, final incremental migration, and OneBot fallback adapter.
8. Official QQ identity binding adapter.

Each later phase receives its own implementation plan after the previous phase's interfaces and tests are accepted.

### Task 1: Create the Python Project Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `pjsk_core/__init__.py`
- Create: `pjsk_core/domain/__init__.py`
- Create: `pjsk_core/application/__init__.py`
- Create: `pjsk_core/ports/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_package_boundaries.py`

**Interfaces:**
- Produces: installable package `pjsk_core` requiring Python `>=3.11`.

- [ ] **Step 1: Write the boundary test**

```python
import ast
from pathlib import Path


def test_domain_does_not_import_outer_layers():
    forbidden = ("pjsk_core.application", "pjsk_core.ports", "adapters", "plugin")
    for path in Path("pjsk_core/domain").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(name.startswith(forbidden) for name in imports), path
```

- [ ] **Step 2: Run the test and confirm collection fails before project configuration exists**

Run: `python -m pytest tests/test_package_boundaries.py -v`

- [ ] **Step 3: Add minimal packaging configuration**

Configure setuptools package discovery, Python `>=3.11`, and dev dependencies `pytest`, `pytest-asyncio`, `ruff`, and `mypy`. Do not add AstrBot, HTTP, Redis, or database dependencies yet.

- [ ] **Step 4: Install and verify**

Run: `python -m venv .venv`, `.venv\Scripts\python -m pip install -e ".[dev]"`, then `.venv\Scripts\python -m pytest -v`.

- [ ] **Step 5: Commit**

Run: `git add pyproject.toml .gitignore README.md pjsk_core tests && git commit -m "build: establish core package boundaries"`

### Task 2: Extract Score Status and Accuracy Rules

**Files:**
- Create: `pjsk_core/domain/scores.py`
- Create: `tests/domain/test_scores.py`
- Reference only: `D:\emu-bot\src\core\calc_accuracy.py`
- Reference only: `D:\emu-bot\tests\test_accuracy.py`

**Interfaces:**
- Produces: `Judgements`, `ScoreStatus`, `calculate_accuracy()`, and `classify_status()`.

- [ ] **Step 1: Write behavior tests before copying formulas**

Cover AP, FC with GREAT, CLEAR with GOOD/BAD/MISS, zero-note rejection, negative judgement rejection, and exact legacy fixtures from `test_accuracy.py`.

```python
def test_ap_requires_no_non_perfect_judgements():
    j = Judgements(perfect=1000, great=0, good=0, bad=0, miss=0)
    assert classify_status(j) is ScoreStatus.AP


def test_fc_allows_great_but_no_combo_break():
    j = Judgements(perfect=990, great=10, good=0, bad=0, miss=0)
    assert classify_status(j) is ScoreStatus.FC
```

- [ ] **Step 2: Verify tests fail because the domain module is absent**

Run: `.venv\Scripts\python -m pytest tests/domain/test_scores.py -v`

- [ ] **Step 3: Implement immutable value objects and pure functions**

Use frozen dataclasses and an enum. Validation occurs in `Judgements.__post_init__`; no logging or exception swallowing belongs in the domain.

- [ ] **Step 4: Compare every legacy accuracy fixture**

Run old and new functions against the same fixed inputs in a parametrized compatibility test. Any difference is documented and approved rather than silently normalized.

- [ ] **Step 5: Run tests and commit**

Run: `.venv\Scripts\python -m pytest tests/domain/test_scores.py -v`
Commit: `git add pjsk_core/domain/scores.py tests/domain/test_scores.py && git commit -m "feat: define score accuracy and status rules"`

### Task 3: Extract Rating and B20 Rules

**Files:**
- Create: `pjsk_core/domain/rating.py`
- Create: `pjsk_core/domain/b20.py`
- Create: `tests/domain/test_rating.py`
- Create: `tests/domain/test_b20.py`
- Reference only: `D:\emu-bot\src\core\kn_power.py`
- Reference only: `D:\emu-bot\tests\test_kn_power.py`
- Reference only: `D:\emu-bot\src\features\handler_b20.py`

**Interfaces:**
- Produces: `calculate_rating(constant, accuracy) -> float` and `select_b20(best_scores, limit=20) -> tuple[BestScore, ...]`.

- [ ] **Step 1: Write exact legacy rating compatibility tests**

Reuse all fixed constants and accuracies from the old suite, including boundary and monotonicity cases.

- [ ] **Step 2: Write B20 eligibility tests**

Assert CLEAR is excluded, FC and AP are eligible, ordering is Rating descending, only 20 remain, ties are deterministic by chart ID, and fewer than 20 scores are valid.

- [ ] **Step 3: Implement pure rating and selection functions**

`BestScore` carries chart ID, Rating, accuracy, and status. B20 selection never queries a repository and never knows about rendering.

- [ ] **Step 4: Verify focused and cumulative domain tests**

Run: `.venv\Scripts\python -m pytest tests/domain -v`

- [ ] **Step 5: Commit**

Run: `git add pjsk_core/domain tests/domain && git commit -m "feat: define rating and B20 selection rules"`

### Task 4: Define User, Chart, OCR, and Candidate Models

**Files:**
- Create: `pjsk_core/domain/users.py`
- Create: `pjsk_core/domain/charts.py`
- Create: `pjsk_core/domain/ocr.py`
- Create: `tests/domain/test_users.py`
- Create: `tests/domain/test_charts.py`
- Create: `tests/domain/test_ocr.py`

**Interfaces:**
- Produces: `UserId`, `QqNumber`, `Chart`, `Difficulty`, `OcrObservation`, `OcrConsensus`, and `Candidate`.

- [ ] **Step 1: Test identity invariants**

QQ numbers normalize to decimal strings, blank/invalid values fail, and OpenID is not accepted as a QQ number.

- [ ] **Step 2: Test chart invariants**

Difficulty is one of easy/normal/hard/expert/master/append; official level, community constant, Note count, song ID, and data version are required.

- [ ] **Step 3: Test OCR consensus behavior**

Two observations agree only when normalized chart, difficulty, and all judgements agree. Vendor confidence alone never creates consensus.

- [ ] **Step 4: Test deterministic candidate ranking**

Order by model support count, Note validation, title similarity, Note distance, then chart ID. Tests use fixed values, not random inputs.

- [ ] **Step 5: Implement immutable models and pure comparison functions**

No model contains AstrBot events, HTTP responses, SQLite rows, Redis keys, or vendor names beyond an engine identifier string.

- [ ] **Step 6: Run and commit**

Run: `.venv\Scripts\python -m pytest tests/domain -v`
Commit: `git add pjsk_core/domain tests/domain && git commit -m "feat: define identity chart and OCR domain models"`

### Task 5: Define Application Ports

**Files:**
- Create: `pjsk_core/ports/repositories.py`
- Create: `pjsk_core/ports/vision.py`
- Create: `pjsk_core/ports/renderer.py`
- Create: `pjsk_core/ports/identity.py`
- Create: `pjsk_core/ports/cache.py`
- Create: `tests/test_port_contracts.py`

**Interfaces:**
- Produces: async protocols `UserRepository`, `ScoreRepository`, `ChartRepository`, `VisionEngine`, `Renderer`, `IdentityResolver`, and `CandidateStore`.

- [ ] **Step 1: Write fake implementations in tests**

Each fake implements the intended method signatures and is assigned to a typed protocol variable. Include an async smoke call for every method.

- [ ] **Step 2: Define narrow protocols**

Repository methods return domain objects, not dictionaries or SQLite rows. `ScoreRepository.record_attempt()` accepts a complete attempt and best-update policy as one transactional operation.

- [ ] **Step 3: Add runtime protocol checks only where useful**

Use `@runtime_checkable` for plugin startup validation; domain code must not call `isinstance` against ports.

- [ ] **Step 4: Run typing and tests**

Run: `.venv\Scripts\python -m mypy pjsk_core tests/test_port_contracts.py` and `.venv\Scripts\python -m pytest tests/test_port_contracts.py -v`.

- [ ] **Step 5: Commit**

Run: `git add pjsk_core/ports tests/test_port_contracts.py && git commit -m "feat: define application adapter contracts"`

### Task 6: Build a Read-Only Legacy Database Auditor

**Files:**
- Create: `tools/audit_legacy_db.py`
- Create: `tests/tools/test_audit_legacy_db.py`
- Create: `docs/migration/legacy-database-audit-format.md`

**Interfaces:**
- Produces: `audit_database(path: Path) -> AuditReport`; CLI emits JSON without row contents, QQ numbers, game IDs, OCR text, or secrets.

- [ ] **Step 1: Create a synthetic legacy database fixture**

Build temporary tables matching the discovered legacy schema and insert normal users/scores plus duplicate game IDs, orphan scores, null identity fields, and invalid judgement totals.

- [ ] **Step 2: Test strict read-only behavior**

Open with `file:<absolute path>?mode=ro`; record file hash and modification time before and after audit and assert both remain unchanged.

- [ ] **Step 3: Implement schema and integrity counters**

Report table names, columns, row counts, duplicate identity counts, orphan counts, null counts, invalid score counts, min/max timestamps, and source SHA-256. Never emit source row values.

- [ ] **Step 4: Test missing and unexpected schema handling**

Missing required tables exits nonzero with table names only; additional tables appear under `unrecognized_tables` and do not crash the audit.

- [ ] **Step 5: Run the synthetic test suite**

Run: `.venv\Scripts\python -m pytest tests/tools/test_audit_legacy_db.py -v`.

- [ ] **Step 6: Commit before touching any real snapshot**

Run: `git add tools tests/tools docs/migration && git commit -m "feat: audit legacy database without exposing user data"`

### Task 7: Audit a Production Database Snapshot

**Files:**
- Create: `docs/migration/legacy-database-audit-summary.md`
- Never add: database snapshots or raw audit JSON containing paths outside the repository.

**Interfaces:**
- Consumes: a read-only copied snapshot of `/opt/pjsk-emu-bot/data/bot.db`.
- Produces: aggregate migration facts needed for Phase 2.

- [ ] **Step 1: Copy the VPS database into an external temporary audit directory**

Use `scp` without modifying the VPS. Compute the remote and local SHA-256 and require equality. Do not place the snapshot under either Git repository.

- [ ] **Step 2: Run the committed auditor**

Run: `.venv\Scripts\python -m tools.audit_legacy_db <external-snapshot> --output <external-report.json>`.

- [ ] **Step 3: Manually inspect only aggregate output**

Confirm the report contains no QQ number, game ID, OCR text, image URL, API key, or Redis URL.

- [ ] **Step 4: Write the sanitized summary**

Record schema version evidence, table/row counts, integrity issue counts, migration blockers, and the source hash prefix. Do not include user-level records.

- [ ] **Step 5: Re-run the complete verification suite**

Run: `.venv\Scripts\python -m ruff check .`, `.venv\Scripts\python -m mypy pjsk_core tools`, and `.venv\Scripts\python -m pytest`.

- [ ] **Step 6: Commit the summary only**

Run: `git add docs/migration/legacy-database-audit-summary.md && git commit -m "docs: record legacy database migration facts"`

## Completion Gate

Phase 1 is complete only when the package installs from a clean environment, all domain behavior tests pass, dependency directions are mechanically checked, the legacy database was opened read-only, and the committed audit summary contains aggregates only. No AstrBot plugin, production schema, OCR HTTP call, Redis client, renderer call, or VPS deployment belongs in this phase.
