"""Tests for server initialization and tool registration."""

import pytest

from comfyui_mcp.config import ComfyUISettings, Settings
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
                "https://comfy.example.com",
            ),
        ],
    )
    def test_select_image_view_base_url(self, comfyui_url, external_url, expected):
        settings = Settings(comfyui=ComfyUISettings(url=comfyui_url, external_url=external_url))
        assert _select_image_view_base_url(settings) == expected
