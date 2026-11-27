"""Media output retrieval (issue #228)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer, PathValidationError
from comfyui_mcp.tools import files
from comfyui_mcp.tools.files import register_file_tools

VIEW = "http://test:8188/view"


@pytest.fixture
def tools(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    # Deliberately excludes media extensions: output reads must not depend on
    # the upload allow-list.
    sanitizer = PathSanitizer(allowed_extensions=[".png", ".json"])
    mcp = FastMCP("get-output-test")
    return register_file_tools(mcp, client, audit, limiter, sanitizer), audit


class TestResponseFormats:
    async def test_url_is_the_default(self, tools):
        tools, _ = tools

        result = await tools["comfyui_get_output"](filename="clip.mp4")

        assert result["status"] == "url"
        assert "filename=clip.mp4" in result["url"]
        assert "content_type" not in result

    async def test_path_is_comfyui_relative(self, tools):
        tools, _ = tools

        result = await tools["comfyui_get_output"](
            filename="clip.mp4", subfolder="clips", response_format="path"
        )

        assert result["status"] == "path"
        assert result["path"] == "clips/clip.mp4"
        assert "not the MCP host" in result["note"]

    @respx.mock
    async def test_inline_video(self, tools):
        tools, _ = tools
        payload = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
        respx.get(VIEW).mock(
            return_value=httpx.Response(200, content=payload, headers={"content-type": "video/mp4"})
        )

        result = await tools["comfyui_get_output"](filename="clip.mp4", response_format="inline")

        assert result["status"] == "inline"
        assert result["content_type"] == "video/mp4"
        assert result["size_bytes"] == len(payload)
        assert result["data_uri"].startswith("data:video/mp4;base64,")

    @respx.mock
    async def test_inline_audio(self, tools):
        tools, _ = tools
        respx.get(VIEW).mock(
            return_value=httpx.Response(
                200, content=b"RIFF....WAVE", headers={"content-type": "audio/wav"}
            )
        )

        result = await tools["comfyui_get_output"](filename="voice.wav", response_format="inline")

        assert result["status"] == "inline"
        assert result["data_uri"].startswith("data:audio/wav;base64,")


class TestInlineFallsBack:
    @respx.mock
    async def test_html_is_not_inlined(self, tools):
        tools, audit = tools
        respx.get(VIEW).mock(
            return_value=httpx.Response(
                200, content=b"<html>", headers={"content-type": "text/html"}
            )
        )

        result = await tools["comfyui_get_output"](filename="page.mp4", response_format="inline")

        assert result["status"] == "not_inlined"
        assert "data_uri" not in result
        assert result["url"]
        records = [json.loads(line) for line in audit._audit_file.read_text().splitlines() if line]
        assert any(record["action"] == "content_type_rejected" for record in records)

    @respx.mock
    async def test_svg_is_not_inlined(self, tools):
        tools, _ = tools
        respx.get(VIEW).mock(
            return_value=httpx.Response(
                200, content=b"<svg/>", headers={"content-type": "image/svg+xml"}
            )
        )

        result = await tools["comfyui_get_output"](filename="drawing.png", response_format="inline")

        assert result["status"] == "not_inlined"
        assert "data_uri" not in result

    @respx.mock
    async def test_oversized_media_falls_back_to_url(self, tools, monkeypatch):
        tools, _ = tools
        monkeypatch.setattr(files, "_MAX_INLINE_OUTPUT_BYTES", 4)
        respx.get(VIEW).mock(
            return_value=httpx.Response(
                200, content=b"12345", headers={"content-type": "video/mp4"}
            )
        )

        result = await tools["comfyui_get_output"](filename="big.mp4", response_format="inline")

        assert result["status"] == "too_large"
        assert result["size_bytes"] == 5
        assert "data_uri" not in result
        assert result["url"]

    async def test_media_extension_is_allowed_for_outputs(self, tools):
        tools, _ = tools

        # .mp4 is not in the upload allow-list, but outputs may be media.
        result = await tools["comfyui_get_output"](filename="clip.mp4")
        assert result["status"] == "url"

    async def test_traversal_is_still_blocked(self, tools):
        tools, _ = tools

        with pytest.raises(PathValidationError):
            await tools["comfyui_get_output"](filename="../clip.mp4")


class TestUploadsStayRestricted:
    async def test_upload_rejects_a_media_extension(self, tools):
        tools, _ = tools
        payload = base64.b64encode(b"data").decode()

        with pytest.raises(PathValidationError):
            await tools["comfyui_upload_image"](filename="clip.mp4", image_data=payload)
