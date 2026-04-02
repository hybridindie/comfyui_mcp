"""File operation tools: upload_image, get_image, list_outputs, get_workflow_from_image."""

from __future__ import annotations

import base64
import json
import struct
import zlib
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.pagination import paginate
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


_MAX_TEXT_CHUNK_BYTES = 10 * 1024 * 1024  # 10 MB limit for decompressed text chunks
_MAX_TOTAL_METADATA_BYTES = 50 * 1024 * 1024  # 50 MB total


def _extract_png_metadata(
    data: bytes, max_text_bytes: int = _MAX_TEXT_CHUNK_BYTES
) -> dict[str, str]:
    """Extract tEXt and zTXt metadata from PNG data.

    Returns a dict of key-value pairs from PNG text chunks.
    Returns an empty dict if the data is not valid PNG or has no text chunks.
    """
    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        return {}

    metadata: dict[str, str] = {}
    offset = 8  # Skip PNG signature
    total_metadata_size = 0

    while offset + 8 <= len(data):
        try:
            length = struct.unpack(">I", data[offset : offset + 4])[0]
        except struct.error:
            break
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]

        if len(chunk_data) < length:
            break  # Truncated chunk

        if chunk_type == b"tEXt":
            null_idx = chunk_data.find(b"\x00")
            if null_idx > 0:
                key = chunk_data[:null_idx].decode("latin-1")
                value = chunk_data[null_idx + 1 :].decode("latin-1")
                metadata[key] = value
                total_metadata_size += len(value)
                if total_metadata_size > _MAX_TOTAL_METADATA_BYTES:
                    break

        elif chunk_type == b"zTXt":
            null_idx = chunk_data.find(b"\x00")
            if null_idx > 0 and null_idx + 2 <= len(chunk_data):
                key = chunk_data[:null_idx].decode("latin-1")
                # Compression method must be 0 (zlib) per PNG spec
                compression_method = chunk_data[null_idx + 1]
                if compression_method == 0:
                    compressed = chunk_data[null_idx + 2 :]
                    try:
                        decompressor = zlib.decompressobj()
                        raw = decompressor.decompress(compressed, max_text_bytes)
                        if not decompressor.unconsumed_tail:
                            value = raw.decode("utf-8")
                            metadata[key] = value
                            total_metadata_size += len(value)
                            if total_metadata_size > _MAX_TOTAL_METADATA_BYTES:
                                break
                    except (zlib.error, UnicodeDecodeError, OverflowError):
                        pass

        elif chunk_type == b"IEND":
            break

        # Move to next chunk: length(4) + type(4) + data(length) + crc(4)
        offset += 12 + length

    return metadata


def register_file_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    sanitizer: PathSanitizer,
    image_view_base_url: str | None = None,
) -> dict[str, Any]:
    """Register file operation tools."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def comfyui_upload_image(filename: str, image_data: str, subfolder: str = "") -> str:
        """Upload an image to ComfyUI's input directory.

        Args:
            filename: Name for the uploaded file (e.g. 'reference.png')
            image_data: Base64-encoded image data
            subfolder: Optional subfolder within ComfyUI's input directory
        """
        limiter.check("upload_image")
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        raw = base64.b64decode(image_data)
        sanitizer.validate_size(len(raw))
        await audit.async_log(
            tool="upload_image",
            action="uploading",
            extra={"filename": clean_name, "size_bytes": len(raw)},
        )
        result = await client.upload_image(raw, clean_name, clean_subfolder)
        await audit.async_log(tool="upload_image", action="uploaded", extra={"result": result})
        return f"Uploaded {result.get('name', clean_name)} to ComfyUI input directory"

    tool_fns["comfyui_upload_image"] = comfyui_upload_image

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_get_image(
        filename: Annotated[str, Field(description="Name of the image file to retrieve")],
        subfolder: Annotated[
            str,
            Field(
                description="Subfolder within ComfyUI's output directory. "
                "Use the subfolder value from comfyui_list_outputs or generation results."
            ),
        ] = "",
        response_format: Annotated[
            Literal["data_uri", "url"],
            Field(description="'data_uri' to inline the image, or 'url' to return a /view URL"),
        ] = "data_uri",
        base_url_override: Annotated[
            str | None,
            Field(
                description="Optional override for URL responses; falls back to configured base URL"
            ),
        ] = None,
    ) -> str:
        """Download a generated image from ComfyUI or return a direct view URL.

        Returns:
            Base64-encoded image data with content type prefix, or a direct image URL
        """
        limiter.check("get_image")
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        await audit.async_log(
            tool="get_image",
            action="downloading",
            extra={"filename": clean_name, "response_format": response_format},
        )

        resolved_base_url = base_url_override or image_view_base_url

        if response_format == "url":
            return client.build_image_url(
                clean_name,
                clean_subfolder,
                base_url=resolved_base_url,
            )

        if response_format != "data_uri":
            raise ValueError("response_format must be 'data_uri' or 'url'")

        data, content_type = await client.get_image(
            clean_name,
            clean_subfolder,
        )
        b64 = base64.b64encode(data).decode()
        return f"data:{content_type};base64,{b64}"

    tool_fns["comfyui_get_image"] = comfyui_get_image

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_list_outputs(limit: int = 25, offset: int = 0) -> dict[str, Any]:
        """List output files from ComfyUI's execution history.

        Args:
            limit: Maximum number of results to return (default: 25, max: 100)
            offset: Starting index for pagination (default: 0)

        Returns:
            JSON envelope with paginated list of objects with 'filename' and
            'subfolder' keys. Pass these values to comfyui_get_image to retrieve files.
        """
        limiter.check("list_outputs")
        await audit.async_log(tool="list_outputs", action="called")
        history = await client.get_history(max_items=100)
        seen: set[tuple[str, str]] = set()
        results: list[dict[str, str]] = []
        for entry in history.values():
            if isinstance(entry, dict):
                for outputs in entry.get("outputs", {}).values():
                    if isinstance(outputs, dict):
                        for images in outputs.get("images", []):
                            if isinstance(images, dict) and "filename" in images:
                                fn = images["filename"]
                                sf = images.get("subfolder", "")
                                key = (fn, sf)
                                if key not in seen:
                                    seen.add(key)
                                    results.append({"filename": fn, "subfolder": sf})
        results.sort(key=lambda item: (item["subfolder"], item["filename"]))
        return paginate(results, offset, limit, default_limit=25, max_limit=100)

    tool_fns["comfyui_list_outputs"] = comfyui_list_outputs

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def comfyui_upload_mask(filename: str, mask_data: str, subfolder: str = "") -> str:
        """Upload a mask image to ComfyUI's input directory.

        Args:
            filename: Name for the uploaded mask file (e.g. 'mask.png')
            mask_data: Base64-encoded mask image data
            subfolder: Optional subfolder within ComfyUI's input directory
        """
        limiter.check("upload_mask")
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        raw = base64.b64decode(mask_data)
        sanitizer.validate_size(len(raw))
        await audit.async_log(
            tool="upload_mask",
            action="uploading",
            extra={"filename": clean_name, "size_bytes": len(raw)},
        )
        result = await client.upload_mask(raw, clean_name, clean_subfolder)
        await audit.async_log(tool="upload_mask", action="uploaded", extra={"result": result})
        return f"Uploaded mask {result.get('name', clean_name)} to ComfyUI input directory"

    tool_fns["comfyui_upload_mask"] = comfyui_upload_mask

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_get_workflow_from_image(filename: str, subfolder: str = "") -> dict[str, Any]:
        """Extract embedded workflow and prompt metadata from a ComfyUI-generated PNG.

        ComfyUI embeds the full workflow JSON and prompt data in PNG text chunks.
        This enables extracting the exact settings used to generate an image
        for inspection or re-execution.

        Args:
            filename: Name of the PNG file to extract metadata from
            subfolder: Subfolder within ComfyUI's output directory (default: empty)

        Returns:
            Dict with 'workflow' (parsed JSON or None), 'prompt' (parsed JSON or None),
            and 'message' (human-readable status).
        """
        limiter.check("get_workflow_from_image")
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        await audit.async_log(
            tool="get_workflow_from_image",
            action="extracting",
            extra={"filename": clean_name, "subfolder": clean_subfolder},
        )

        data, _ = await client.get_image(clean_name, clean_subfolder)
        sanitizer.validate_size(len(data))

        if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
            raise ValueError("File is not a PNG image")

        raw_metadata = _extract_png_metadata(data)

        workflow = None
        prompt = None
        parts: list[str] = []

        if "workflow" in raw_metadata:
            try:
                workflow = json.loads(raw_metadata["workflow"])
                node_count = len(workflow) if isinstance(workflow, dict) else 0
                parts.append(f"workflow ({node_count} nodes)")
            except (json.JSONDecodeError, TypeError):
                parts.append("workflow (malformed JSON)")

        if "prompt" in raw_metadata:
            try:
                prompt = json.loads(raw_metadata["prompt"])
                parts.append("prompt")
            except (json.JSONDecodeError, TypeError):
                parts.append("prompt (malformed JSON)")

        if parts:
            message = f"Extracted {' and '.join(parts)} from image"
        else:
            message = "No workflow metadata found in this image"

        await audit.async_log(
            tool="get_workflow_from_image",
            action="extracted",
            extra={
                "filename": clean_name,
                "has_workflow": workflow is not None,
                "has_prompt": prompt is not None,
            },
        )

        return {"workflow": workflow, "prompt": prompt, "message": message}

    tool_fns["comfyui_get_workflow_from_image"] = comfyui_get_workflow_from_image

    return tool_fns
