"""Core tool profile (issue #212)."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import NotFoundError
from pydantic import ValidationError

from comfyui_mcp.config import Settings, ToolsSettings, load_settings
from comfyui_mcp.server import _CORE_TOOL_NAMES, _build_server


class TestProfileConfig:
    def test_default_is_full(self):
        assert Settings().tools.profile == "full"

    def test_invalid_profile_is_rejected(self):
        with pytest.raises(ValidationError):
            ToolsSettings(profile="minimal")

    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COMFYUI_TOOLS_PROFILE", "core")

        settings = load_settings(config_path=tmp_path / "missing.yaml")

        assert settings.tools.profile == "core"


class TestCoreProfile:
    async def test_lists_only_core_tools(self):
        server, *_ = _build_server(settings=Settings(tools=ToolsSettings(profile="core")))

        names = {tool.name for tool in await server.list_tools()}

        assert names == set(_CORE_TOOL_NAMES)
        assert "comfyui_upload_media" in names
        assert len(names) <= 26

    async def test_hidden_tool_cannot_be_called(self):
        server, *_ = _build_server(settings=Settings(tools=ToolsSettings(profile="core")))

        with pytest.raises(NotFoundError):
            await server.call_tool("comfyui_get_history", {})

    async def test_prompts_and_resources_stay_available(self):
        server, *_ = _build_server(settings=Settings(tools=ToolsSettings(profile="core")))

        prompts = {prompt.name for prompt in await server.list_prompts()}

        assert {"txt2img_prompt", "img2img_prompt", "inpaint_prompt", "upscale_prompt"} <= prompts


class TestFullProfile:
    async def test_lists_every_tool_and_contains_the_core_set(self):
        server, *_ = _build_server(settings=Settings())

        names = {tool.name for tool in await server.list_tools()}

        assert names >= _CORE_TOOL_NAMES
        assert "comfyui_get_history" in names
        assert len(names) >= 50

    async def test_core_names_are_real_tools(self):
        """Pins the hand-maintained core list against registration typos."""
        server, *_ = _build_server(settings=Settings())

        names = {tool.name for tool in await server.list_tools()}

        assert not (set(_CORE_TOOL_NAMES) - names)
