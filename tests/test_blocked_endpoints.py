"""Regression tests for CLAUDE.md security rule 1: blocked endpoints."""

from __future__ import annotations

import inspect

import comfyui_mcp.client as client_module


class TestBlockedEndpoints:
    """Verify that blocked ComfyUI endpoints are never exposed in client.py."""

    def test_no_userdata_endpoint(self):
        source = inspect.getsource(client_module)
        assert "/userdata" not in source

    def test_no_free_endpoint(self):
        source = inspect.getsource(client_module)
        assert '"/free"' not in source

    def test_no_users_endpoint(self):
        source = inspect.getsource(client_module)
        assert '"/users"' not in source

    def test_no_history_delete(self):
        """Verify /history is only used with GET, never POST/DELETE for mutation."""
        source = inspect.getsource(client_module)
        forbidden_patterns = [
            '_request("post", "/history"',
            "_request('post', '/history'",
            '_request("delete", "/history"',
            "_request('delete', '/history'",
        ]
        for pattern in forbidden_patterns:
            assert (
                pattern not in source
            ), f"Blocked history mutation endpoint found in client.py: {pattern}"
