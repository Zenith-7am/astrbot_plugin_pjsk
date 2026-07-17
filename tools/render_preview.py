#!/usr/bin/env python3
"""POST a render payload to a render service and save the resulting PNG.

Usage::

    python tools/render_preview.py --template b20
    python tools/render_preview.py --template difficulty --payload my_data.json
    python tools/render_preview.py --template b20 --output my_snapshot.png

The script verifies the response is a valid PNG and prints the file path
and size on success. On failure it prints a concise error to stderr and
exits with code 1.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# ── Path resolution ──────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_FIXTURES: dict[str, Path] = {
    "b20": _PROJECT_ROOT / "tests" / "fixtures" / "render" / "b20_preview.json",
    "ocr_result": (
        _PROJECT_ROOT / "tests" / "fixtures" / "render" / "ocr_result_preview.json"
    ),
}
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "artifacts" / "render-preview"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# ── CLI ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview a PJSK render template against a local render service.",
    )
    parser.add_argument(
        "--template", required=True,
        choices=["b20", "difficulty", "ocr_result"],
        help="Render template name (b20, difficulty, or ocr_result).",
    )
    parser.add_argument(
        "--payload", default=None,
        help="Path to a JSON payload file. Uses a bundled fixture when omitted.",
    )
    parser.add_argument(
        "--url", default="http://127.0.0.1:3001",
        help="Render service base URL (default: http://127.0.0.1:3001).",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output PNG path. Default: artifacts/render-preview/{template}_{ts}.png",
    )
    return parser


# ── Main ─────────────────────────────────────────────────────────────────────


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # ── Resolve payload ───────────────────────────────────────────────────
    if args.payload:
        payload_path = Path(args.payload)
        if not payload_path.exists():
            print(f"Error: payload file not found: {payload_path}", file=sys.stderr)
            return 1
        try:
            data = json.loads(payload_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in {payload_path}: {e}", file=sys.stderr)
            return 1
    elif args.template in _DEFAULT_FIXTURES:
        fixture = _DEFAULT_FIXTURES[args.template]
        if not fixture.exists():
            print(
                f"Error: no --payload given and fixture not found: {fixture}",
                file=sys.stderr,
            )
            return 1
        data = json.loads(fixture.read_text(encoding="utf-8"))
    else:
        print(
            f"Error: --payload is required for template '{args.template}' "
            f"(no bundled fixture available)",
            file=sys.stderr,
        )
        return 1

    # ── Resolve output path ────────────────────────────────────────────────
    if args.output:
        output_path = Path(args.output)
    else:
        ts = int(time.time())
        _DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = _DEFAULT_OUTPUT_DIR / f"{args.template}_{ts}.png"

    # ── POST to render service ─────────────────────────────────────────────
    url = f"{args.url.rstrip('/')}/render/{args.template}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=data)
    except httpx.ConnectError:
        print(
            f"Error: cannot connect to {args.url}. Is the dev render service running?",
            file=sys.stderr,
        )
        print(
            "Start it with: ops/run-render-dev.ps1 (PowerShell) "
            "or: python -m uvicorn render_service.main:app --host 127.0.0.1 --port 3001",
            file=sys.stderr,
        )
        return 1
    except Exception as e:
        print(f"Error: request failed: {e}", file=sys.stderr)
        return 1

    # ── Validate response ──────────────────────────────────────────────────
    if resp.status_code != 200:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("detail", "")
        except Exception:
            detail = resp.text[:200]
        print(
            f"Error: render service returned {resp.status_code}: {detail}",
            file=sys.stderr,
        )
        return 1

    content_type = resp.headers.get("content-type", "")
    if "image/png" not in content_type:
        print(
            f"Error: response is not PNG (Content-Type: {content_type})",
            file=sys.stderr,
        )
        return 1

    png_bytes = resp.content
    if not png_bytes[:8] == _PNG_SIGNATURE:
        print(
            f"Error: response does not have PNG signature "
            f"(got {png_bytes[:8]!r})",
            file=sys.stderr,
        )
        return 1

    # ── Write output ───────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png_bytes)
    size_kb = len(png_bytes) / 1024

    print(f"OK  {output_path}  ({size_kb:.1f} KB, {resp.status_code})")
    return 0


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
