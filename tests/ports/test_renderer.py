"""Tests for Renderer port and RenderPayload."""

import pytest

from pjsk_core.ports.renderer import RenderPayload


class TestRenderPayload:
    def test_is_frozen(self) -> None:
        payload = RenderPayload(template_name="b20", data={"key": "value"})
        with pytest.raises(Exception):
            payload.template_name = "difficulty"  # type: ignore[misc]

    def test_defaults(self) -> None:
        payload = RenderPayload(template_name="b20")
        assert payload.template_name == "b20"
        assert payload.data == {}

    def test_with_data(self) -> None:
        payload = RenderPayload(template_name="b20", data={"entries": []})
        assert payload.data == {"entries": []}
