"""Tests for server initialization and tool registration."""

import pytest

from comfyui_mcp.config import ComfyUISettings, Settings
from comfyui_mcp.middleware import SecurityMiddleware
from comfyui_mcp.server import _build_server, _select_image_view_base_url


class TestServerSetup:
    def test_server_has_name(self):
        settings = Settings(comfyui=ComfyUISettings(url="http://test:8188"))
        server, *_ = _build_server(settings)
        assert server.name == "ComfyUI"

    def test_build_server_returns_settings(self):
        settings = Settings(comfyui=ComfyUISettings(url="http://test:8188"))
        _, returned_settings, *_ = _build_server(settings)
        assert returned_settings.comfyui.url == "http://test:8188"

    def test_build_server_wires_security_middleware(self):
        """Phase 3: SecurityMiddleware is registered so rate limiting +
        entry audit are enforced centrally (testing rule 19 covers both
        enforcement paths)."""
        settings = Settings(comfyui=ComfyUISettings(url="http://test:8188"))
        server, *_ = _build_server(settings)
        # FastMCP stores middleware on the server; reach it via the private
        # attribute the framework exposes. If the attribute moves, the test
        # fails loudly rather than silently skipping enforcement.
        stack = getattr(server, "_middleware", None) or getattr(server, "middleware", None)
        assert stack is not None, "Could not locate middleware list on FastMCP server"
        assert any(isinstance(m, SecurityMiddleware) for m in stack), (
            "SecurityMiddleware not registered — per-tool rate limit + audit "
            "boilerplate cannot be dropped without it (security rules 3, 4)"
        )


class TestImageViewBaseUrlSelection:
    @pytest.mark.parametrize(
        ("comfyui_url", "external_url", "expected"),
        [
            ("https://comfy.example.com", None, "https://comfy.example.com"),
            (
                "https://comfy.example.com",
                "https://images.example.com/comfyui",
                "https://images.example.com/comfyui",
            ),
            (
                "https://comfy.example.com",
                "http://comfyui.default.svc.cluster.local:8188",
                "http://comfyui.default.svc.cluster.local:8188",
            ),
        ],
    )
    def test_select_image_view_base_url(self, comfyui_url, external_url, expected):
        settings = Settings(comfyui=ComfyUISettings(url=comfyui_url, external_url=external_url))
        assert _select_image_view_base_url(settings) == expected

    def test_select_image_view_base_url_falls_back_to_localhost_when_urls_empty(self):
        settings = Settings(comfyui=ComfyUISettings.model_construct(url="", external_url=None))
        assert _select_image_view_base_url(settings) == "http://127.0.0.1:8188"
