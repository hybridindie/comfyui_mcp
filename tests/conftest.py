"""Shared test fixtures."""

import pytest

from comfyui_mcp.client import ComfyUIClient

# Capture the real method at import time, before any test fixture patches it.
_real_get_node_replacements = ComfyUIClient.get_node_replacements


@pytest.fixture(autouse=True)
def _mock_node_replacements(monkeypatch):
    """Default /node_replacements to empty so workflow-submit tests don't need
    to mock it individually. Tests that exercise the real replacement path live
    in test_node_replacements.py; opt out by re-applying ``_real_get_node_replacements``
    in a local autouse fixture."""

    async def _empty(self):
        return {}

    monkeypatch.setattr(ComfyUIClient, "get_node_replacements", _empty)
