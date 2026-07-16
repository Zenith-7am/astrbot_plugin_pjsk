"""Backward-compat re-export of Runtime as PluginRuntime."""
from pjsk_runtime.runtime import EphemeralImageBuffer  # noqa: F401
from pjsk_runtime.runtime import Runtime as PluginRuntime
from pjsk_runtime.runtime import RuntimeStatus

__all__ = ["EphemeralImageBuffer", "PluginRuntime", "RuntimeStatus"]
