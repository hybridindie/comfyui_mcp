"""Regression tests for CLAUDE.md security rule 1: blocked endpoints."""

from __future__ import annotations

import inspect

from comfyui_mcp.client import ComfyUIClient


class TestBlockedEndpoints:
    """Verify that blocked ComfyUI endpoints are never exposed in the client."""

    def test_no_userdata_endpoint(self):
        source = inspect.getsource(ComfyUIClient)
        assert "/userdata" not in source

    def test_no_free_endpoint(self):
        source = inspect.getsource(ComfyUIClient)
        assert '"/free"' not in source

    def test_no_users_endpoint(self):
        source = inspect.getsource(ComfyUIClient)
        assert '"/users"' not in source

    def test_no_history_delete(self):
        """Verify /history is only used with GET, never DELETE/POST for deletion."""
        source = inspect.getsource(ComfyUIClient)
        # /history GET is allowed (get_history, get_history_item)
        # /history POST with {"delete": ...} is blocked
        lines = source.split("\n")
        for line in lines:
            if "/history" in line and "delete" in line.lower():
                raise AssertionError(f"History delete endpoint found: {line.strip()}")
