"""Render the OCR result card as a PNG image via the render service.

Posts pre-computed HTML to ``POST /render/html`` and returns PNG bytes.
Callers must degrade to text fallback on ``None`` return.
"""
from __future__ import annotations

import logging
from pathlib import Path

from pjsk_core.ports.renderer import RenderPayload, Renderer

_logger = logging.getLogger(__name__)

_TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent
    / "render_service" / "templates" / "ocr_card.html"
)
_TEMPLATE: str | None = None


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
            f'<div class="grade-rainbow">{label}</div>'
            '</div>'
        )
    bg = _GRADE_BG_COLORS.get(css_class, "#f43f5e")
    return (
        '<div class="grade-badge">'
        f'<div class="grade-solid" style="background:{bg}">{label}</div>'
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
    jacket_data_url: str | None,
    renderer: Renderer,
) -> bytes | None:
    """Render OCR result card via the render service. Returns PNG bytes or None.

    Falls back to ``None`` on any render failure — callers must degrade to text.
    """
    template = _get_template()

    diff_class = _DIFF_CLASSES.get(difficulty.lower(), "expert")
    diff_label = difficulty.upper()
    grade_label, acc_class = _get_acc_grade(accuracy)

    # Jacket HTML
    if jacket_data_url:
        jacket_html = (
            '<div class="jacket">'
            f'<img src="{jacket_data_url}" alt="jacket" />'
            '</div>'
        )
    else:
        jacket_html = '<div class="jacket-placeholder">&#9834;</div>'

    status_html = _build_status_html(status)
    grade_html = _build_grade_html(grade_label, acc_class)

    # Template variable substitution
    html = template
    replacements: dict[str, str] = {
        "{{title_ja}}": title_ja,
        "{{title_cn}}": title_cn or "",
        "{{diff_class}}": diff_class,
        "{{diff_label}}": diff_label,
        "{{level}}": str(level),
        "{{constant}}": constant,
        "{{perfect}}": f"{perfect:,}",
        "{{great}}": f"{great:,}",
        "{{good}}": f"{good:,}",
        "{{bad}}": f"{bad:,}",
        "{{miss}}": f"{miss:,}",
        "{{rating}}": f"{rating:.1f}",
        "{{accuracy}}": f"{accuracy:.4f}%",
        "{{acc_class}}": acc_class,
        "{{sp}}": sp,
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
