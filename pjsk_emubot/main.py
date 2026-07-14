"""Compatibility re-export — PjskPlugin lives in root ``main.py``.

AstrBot v4 plugin discovery may resolve to this module.  Forward
everything to the root plugin entry point so old references keep working.
"""

from __future__ import annotations

# Re-export from the canonical location at plugin root.
from main import PjskPlugin  # noqa: F401 — compatibility shim
