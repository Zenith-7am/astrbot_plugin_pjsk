"""Render the OCR result card as a PNG image via the render service.

Posts pre-computed HTML to ``POST /render/html`` and returns PNG bytes.
Callers must degrade to text fallback on ``None`` return.
"""
from __future__ import annotations

import html as _html_module
import logging
import re
from pathlib import Path

from pjsk_core.ports.renderer import RenderPayload, Renderer

_logger = logging.getLogger(__name__)

_TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent
    / "render_service" / "templates" / "ocr_card.html"
)
_TEMPLATE: str | None = None

# Only data: URLs with base64 PNG/JPEG/WebP are allowed for jacket images.
_JACKET_RE = re.compile(r"^data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+$")


def _get_template() -> str:
    global _TEMPLATE
    if _TEMPLATE is not None:
        return _TEMPLATE
    _TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return _TEMPLATE


# ── Grade lookup ─────────────────────────────────────────────────────────

_ACC_GRADES: list[tuple[float, str, str]] = [
    (101.0,  "SSS+", "rainbow"),
    (100.75, "SSS",  "sss"),
    (100.5,  "SS+",  "ss-plus"),
    (100.0,  "SS",   "ss"),
    (99.5,   "S+",   "s-plus"),
    (99.0,   "S",    "s"),
    (98.0,   "A",    "a"),
    (95.0,   "B",    "b"),
    (90.0,   "C",    "c"),
]

_GRADE_BG_COLORS: dict[str, str] = {
    "sss-plus": "#df57f4", "sss": "#b270f0", "ss-plus": "#9a69ee",
    "ss": "#4c80f0", "s-plus": "#32b0d0", "s": "#1fb384",
    "a": "#7ebc26", "b": "#e4a827", "c": "#fa8029", "d": "#f43f5e",
}

_DIFF_CLASSES: dict[str, str] = {
    "master": "master", "expert": "expert", "append": "append",
    "hard": "hard", "normal": "normal", "easy": "easy",
}


def _esc(text: str) -> str:
    """Escape text for safe HTML insertion. Quotes are escaped too."""
    return _html_module.escape(text, quote=True)


def _get_acc_grade(accuracy: float) -> tuple[str, str]:
    """Return (grade_label, css_class) for the given accuracy."""
    for threshold, label, css_class in _ACC_GRADES:
        if accuracy >= threshold:
            return label, css_class
    return "D", "d"


def _build_grade_html(label: str, css_class: str) -> str:
    """Generate the grade badge HTML snippet."""
    if css_class == "rainbow":
        return (
            '<div class="grade-badge">'
            f'<div class="grade-rainbow">{_esc(label)}</div>'
            '</div>'
        )
    bg = _GRADE_BG_COLORS.get(css_class, "#f43f5e")
    return (
        '<div class="grade-badge">'
        f'<div class="grade-solid" style="background:{_esc(bg)}">{_esc(label)}</div>'
        '</div>'
    )


def _build_status_html(status: str) -> str:
    """Generate the status badge HTML snippet."""
    if status == "ap":
        return '<span class="badge badge-ap">ALL PERFECT</span>'
    elif status == "fc":
        return '<span class="badge badge-fc">FULL COMBO</span>'
    else:
        return '<span class="badge badge-clear">CLEAR</span>'


def _build_jacket_html(jacket_data_url: str | None) -> str:
    """Build jacket img HTML, validating the data URL format."""
    if not jacket_data_url:
        return '<div class="jacket-placeholder">&#9834;</div>'
    if not _JACKET_RE.match(jacket_data_url):
        _logger.warning("Rejected non-data-URL jacket: %.60s...", jacket_data_url)
        return '<div class="jacket-placeholder">&#9834;</div>'
    escaped_url = _esc(jacket_data_url)
    return (
        '<div class="jacket">'
        f'<img src="{escaped_url}" alt="jacket" />'
        '</div>'
    )


def _build_title_cn_html(title_cn: str) -> str:
    """Build the Chinese title div, or empty string if no title."""
    if not title_cn.strip():
        return ""
    return f'<div class="title-cn">{_esc(title_cn.strip())}</div>'


# ── Main render function ─────────────────────────────────────────────────


async def render_ocr_card(
    *,
    song_id: int,
    title_ja: str,
    title_cn: str,
    difficulty: str,
    level: int,
    constant: str,
    accuracy: float,
    rating: float,
    sp: str,
    perfect: int,
    great: int,
    good: int,
    bad: int,
    miss: int,
    status: str,
    qq_id: str,
    jacket_data_url: str | None,
    renderer: Renderer,
) -> bytes | None:
    """Render OCR result card via the render service. Returns PNG bytes or None.

    Falls back to ``None`` on any render failure — callers must degrade to text.
    All user-provided text fields are HTML-escaped for security.
    """
    template = _get_template()

    diff_class = _DIFF_CLASSES.get(difficulty.lower(), "expert")
    diff_label = difficulty.upper()
    grade_label, acc_class = _get_acc_grade(accuracy)

    jacket_html = _build_jacket_html(jacket_data_url)
    status_html = _build_status_html(status)
    grade_html = _build_grade_html(grade_label, acc_class)
    title_cn_html = _build_title_cn_html(title_cn)

    # Template variable substitution — all user text escaped
    html = template
    replacements: dict[str, str] = {
        "{{qq_id}}": _esc(qq_id),
        "{{title_ja}}": _esc(title_ja),
        "{{title_cn_html}}": title_cn_html,
        "{{diff_class}}": _esc(diff_class),
        "{{diff_label}}": _esc(diff_label),
        "{{level}}": _esc(str(level)),
        "{{constant}}": _esc(constant),
        "{{perfect}}": _esc(f"{perfect:,}"),
        "{{great}}": _esc(f"{great:,}"),
        "{{good}}": _esc(f"{good:,}"),
        "{{bad}}": _esc(f"{bad:,}"),
        "{{miss}}": _esc(f"{miss:,}"),
        "{{rating}}": _esc(f"{rating:.1f}"),
        "{{accuracy}}": _esc(f"{accuracy:.4f}%"),
        "{{acc_class}}": _esc(acc_class),
        "{{sp}}": _esc(sp),
        "{{jacket_html}}": jacket_html,
        "{{status_badge_html}}": status_html,
        "{{grade_badge_html}}": grade_html,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    payload = RenderPayload(
        template_name="html",
        data={"html": html, "width": 960, "height": 600},
    )

    try:
        png = await renderer.render(payload)
        if png is None:
            _logger.warning("Render service returned None for OCR card")
        return png
    except Exception:
        _logger.warning("Render service call failed for OCR card", exc_info=True)
        return None
