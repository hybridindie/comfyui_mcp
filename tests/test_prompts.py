"""Tests for MCP prompts (workflow template recipes for the LLM)."""

from __future__ import annotations

from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.prompts import register_prompts
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer

_ALLOWED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".safetensors"]


def _components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    sanitizer = PathSanitizer(allowed_extensions=_ALLOWED_EXTENSIONS)
    return client, audit, limiter, sanitizer


class TestTxt2imgPrompt:
    async def test_returns_string_mentioning_tool_and_prompt(self, tmp_path):
        client, audit, limiter, sanitizer = _components(tmp_path)
        mcp = FastMCP("test")
        fns = register_prompts(mcp, client, audit, limiter, sanitizer)

        result = await fns["txt2img_prompt"](prompt="a serene mountain lake")
        assert isinstance(result, str)
        assert "comfyui_generate_image" in result
        assert "a serene mountain lake" in result

    async def test_style_default_is_photorealistic(self, tmp_path):
        client, audit, limiter, sanitizer = _components(tmp_path)
        mcp = FastMCP("test")
        fns = register_prompts(mcp, client, audit, limiter, sanitizer)

        result = await fns["txt2img_prompt"](prompt="a cat")
        assert "photorealistic" in result.lower()

    async def test_style_override_changes_guidance(self, tmp_path):
        client, audit, limiter, sanitizer = _components(tmp_path)
        mcp = FastMCP("test")
        fns = register_prompts(mcp, client, audit, limiter, sanitizer)

        result = await fns["txt2img_prompt"](prompt="a cat", style="anime")
        assert "anime" in result.lower()


class TestImg2imgPrompt:
    async def test_returns_string_mentioning_transform_and_image(self, tmp_path):
        client, audit, limiter, sanitizer = _components(tmp_path)
        mcp = FastMCP("test")
        fns = register_prompts(mcp, client, audit, limiter, sanitizer)

        result = await fns["img2img_prompt"](image="photo.png", prompt="make it watercolor")
        assert isinstance(result, str)
        assert "comfyui_transform_image" in result
        assert "photo.png" in result
        assert "make it watercolor" in result


class TestInpaintPrompt:
    async def test_returns_string_mentioning_inpaint_and_mask(self, tmp_path):
        client, audit, limiter, sanitizer = _components(tmp_path)
        mcp = FastMCP("test")
        fns = register_prompts(mcp, client, audit, limiter, sanitizer)

        result = await fns["inpaint_prompt"](
            image="photo.png", mask="mask.png", prompt="remove the background"
        )
        assert isinstance(result, str)
        assert "comfyui_inpaint_image" in result
        assert "mask.png" in result


class TestUpscalePrompt:
    async def test_returns_string_mentioning_upscale(self, tmp_path):
        client, audit, limiter, sanitizer = _components(tmp_path)
        mcp = FastMCP("test")
        fns = register_prompts(mcp, client, audit, limiter, sanitizer)

        result = await fns["upscale_prompt"](image="photo.png")
        assert isinstance(result, str)
        assert "comfyui_upscale_image" in result


class TestRegistration:
    async def test_register_prompts_returns_callable_dict(self, tmp_path):
        client, audit, limiter, sanitizer = _components(tmp_path)
        mcp = FastMCP("test")
        fns = register_prompts(mcp, client, audit, limiter, sanitizer)
        assert isinstance(fns, dict)
        assert "txt2img_prompt" in fns
        assert "img2img_prompt" in fns
        assert "inpaint_prompt" in fns
        assert "upscale_prompt" in fns
