"""File operation tools: upload_image, upload_media, get_image, get_output, list_outputs."""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.pagination import LimitField, OffsetField, PaginationEnvelope, paginate
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tool_types import WorkflowFromImageResult

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Content types safe to inline as a data URI: raster images only.
# Renderable/active types (HTML, JS, CSS, SVG, XML) are excluded on purpose:
# upstream ComfyUI forces them to download via /view for stored-XSS reasons
# (GHSA-779p-m5rp-r4h4), and the MCP server must not become an
# inline-rendering relay. Default-deny: unknown/missing content types are
# rejected too. Note SVG is technically image/* but is an active XML document
# type — must be explicitly blocked.
_INLINE_SAFE_PREFIX = "image/"
_INLINE_BLOCKED_TYPES = frozenset({"image/svg+xml"})

# Inline outputs may also be video or audio; the size cap keeps a data URI
# from blowing up the MCP response. Larger media still gets a /view URL.
_MAX_INLINE_OUTPUT_BYTES = 8 * 1024 * 1024
_INLINE_OUTPUT_PREFIXES = ("image/", "video/", "audio/")

# Multipart content type per upload extension. ComfyUI's /upload/image endpoint
# stores the part as-is and does not inspect the type, but sending the real one
# keeps proxies and logs honest and avoids presenting a video as image/png.
_MEDIA_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


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

    async def _upload_payload(
        *,
        tool: str,
        clean_name: str,
        clean_subfolder: str,
        raw: bytes,
        destination: str,
        overwrite: bool,
        content_type: str,
        kind: str,
        size_hint: str,
    ) -> str:
        """Shared size check + audit + upload for the image and media tools."""
        try:
            features = await client.get_features()
        except Exception:
            features = {}  # older servers may not expose /features
        server_max = features.get("max_upload_size")
        if isinstance(server_max, (int, float)) and server_max > 0 and len(raw) > server_max:
            await audit.async_log(
                tool=tool,
                action="upload_rejected",
                extra={
                    "filename": clean_name,
                    "size_bytes": len(raw),
                    "max_upload_size_bytes": int(server_max),
                },
            )
            raise ValueError(
                f"Payload is {len(raw)} bytes but this ComfyUI server's max_upload_size "
                f"is {int(server_max)} bytes. Reduce the {kind} size ({size_hint}) "
                "before uploading."
            )

        sanitizer.validate_size(len(raw))
        await audit.async_log(
            tool=tool,
            action="uploading",
            extra={
                "filename": clean_name,
                "size_bytes": len(raw),
                "destination": destination,
                "overwrite": overwrite,
            },
        )
        result = await client.upload_image(
            raw,
            clean_name,
            clean_subfolder,
            destination=destination,
            overwrite=overwrite,
            content_type=content_type,
        )
        await audit.async_log(tool=tool, action="uploaded", extra={"result": result})
        return f"Uploaded {result.get('name', clean_name)} to ComfyUI {destination} directory"

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        )
    )
    async def comfyui_upload_image(
        filename: Annotated[
            str,
            Field(description="Name for the uploaded file (e.g. 'reference.png')"),
        ],
        image_data: Annotated[
            str,
            Field(description="Base64-encoded image data"),
        ],
        subfolder: Annotated[
            str,
            Field(default="", description="Optional subfolder within the destination directory"),
        ] = "",
        destination: Annotated[
            Literal["input", "output", "temp"],
            Field(
                default="input",
                description="Destination directory. 'input' (default) is where workflows "
                "read user-supplied images from; 'output' and 'temp' are usually only "
                "useful for testing or scripted setups.",
            ),
        ] = "input",
        overwrite: Annotated[
            bool,
            Field(
                default=False,
                description="If True, replace any existing file with the same name. If False "
                "(default), ComfyUI auto-renames by suffixing ' (N)'.",
            ),
        ] = False,
    ) -> str:
        """Upload an image to ComfyUI.

        Defaults to ComfyUI's input directory (the destination workflows read from).
        Set destination='output' or 'temp' only if you have a specific reason.
        Payload size is checked against ComfyUI's reported ``max_upload_size``
        (from ``/features``) before the request is sent, so oversized uploads get
        a precise local error instead of an opaque HTTP 413. When the server
        doesn't report the feature, only the configured limit applies.
        """
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        raw = base64.b64decode(image_data)
        return await _upload_payload(
            tool="upload_image",
            clean_name=clean_name,
            clean_subfolder=clean_subfolder,
            raw=raw,
            destination=destination,
            overwrite=overwrite,
            content_type="image/png",
            kind="image",
            size_hint="e.g. downscale or re-encode",
        )

    tool_fns["comfyui_upload_image"] = comfyui_upload_image

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        )
    )
    async def comfyui_upload_media(
        filename: Annotated[
            str,
            Field(description="Name for the uploaded file (e.g. 'clip.mp4')"),
        ],
        media_data: Annotated[
            str,
            Field(description="Base64-encoded video or audio data"),
        ],
        subfolder: Annotated[
            str,
            Field(default="", description="Optional subfolder within the destination directory"),
        ] = "",
        destination: Annotated[
            Literal["input", "output", "temp"],
            Field(
                default="input",
                description="Destination directory. 'input' (default) is where workflows "
                "read user-supplied media from; 'output' and 'temp' are usually only "
                "useful for testing or scripted setups.",
            ),
        ] = "input",
        overwrite: Annotated[
            bool,
            Field(
                default=False,
                description="If True, replace any existing file with the same name. If False "
                "(default), ComfyUI auto-renames by suffixing ' (N)'.",
            ),
        ] = False,
    ) -> str:
        """Upload a video or audio file to ComfyUI.

        Use this for video-to-video, audio-driven, and VHS/AnimateDiff inputs.
        ``comfyui_upload_image`` stays raster/JSON-only. The extension must be in
        ``security.allowed_media_extensions``; the part is sent with its real
        video/audio content type. The file is stored under ComfyUI's input
        directory by default and is not transcoded or inspected, so pass a
        container the workflow's loader can read. Payload size is checked against
        ComfyUI's reported ``max_upload_size`` and the configured limit before
        the request is sent.
        """
        clean_name = sanitizer.validate_media_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        raw = base64.b64decode(media_data)
        suffix = PurePosixPath(clean_name).suffix.lower()
        content_type = _MEDIA_CONTENT_TYPES.get(suffix, "application/octet-stream")
        return await _upload_payload(
            tool="upload_media",
            clean_name=clean_name,
            clean_subfolder=clean_subfolder,
            raw=raw,
            destination=destination,
            overwrite=overwrite,
            content_type=content_type,
            kind="media",
            size_hint="e.g. trim or re-encode",
        )

    tool_fns["comfyui_upload_media"] = comfyui_upload_media

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
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
        preview_format: Annotated[
            Literal["webp", "jpeg"] | None,
            Field(
                default=None,
                description="If set with response_format='data_uri', request a server-rendered "
                "thumbnail in this format instead of the original (smaller payload, lossy).",
            ),
        ] = None,
        preview_quality: Annotated[
            int | None,
            Field(
                default=None,
                ge=1,
                le=100,
                description="Encoder quality (1-100) for preview_format. Default: 90 when "
                "preview_format is set.",
            ),
        ] = None,
    ) -> str:
        """Download a generated image from ComfyUI or return a direct view URL.

        Use ``comfyui_get_output`` for video/audio outputs or when you need
        media metadata; this tool stays raster-image-only and supports previews.

        Returns:
            Base64-encoded image data with content type prefix, or a direct image URL.
            When response_format='data_uri' and preview_format is set, ComfyUI re-encodes
            the image server-side as a smaller webp or jpeg thumbnail.
        """

        if preview_quality is not None and preview_format is None:
            raise ValueError("preview_quality is only meaningful when preview_format is also set")

        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        await audit.async_log(
            tool="get_image",
            action="downloading",
            extra={
                "filename": clean_name,
                "response_format": response_format,
                "preview_format": preview_format,
            },
        )

        resolved_base_url = base_url_override or image_view_base_url

        if response_format == "url":
            # Preview params don't apply to URL responses — the returned URL
            # is a direct /view link; callers wanting a thumbnail should
            # request response_format='data_uri'.
            return client.build_image_url(
                clean_name,
                clean_subfolder,
                base_url=resolved_base_url,
            )

        if response_format != "data_uri":
            raise ValueError("response_format must be 'data_uri' or 'url'")

        preview_spec: str | None = None
        if preview_format is not None:
            quality = preview_quality if preview_quality is not None else 90
            preview_spec = f"{preview_format};{quality}"

        data, content_type = await client.get_image(
            clean_name,
            clean_subfolder,
            preview=preview_spec,
        )

        normalized_type = (content_type or "").strip().lower().split(";")[0]
        rejected_type = (
            not normalized_type.startswith(_INLINE_SAFE_PREFIX)
            or normalized_type in _INLINE_BLOCKED_TYPES
        )
        if rejected_type:
            await audit.async_log(
                tool="get_image",
                action="content_type_rejected",
                extra={
                    "filename": clean_name,
                    "content_type": content_type or "<missing>",
                },
            )
            raise ValueError(
                f"Refusing to inline non-image content type {content_type or '<missing>'!r} "
                f"from /view; only raster {_INLINE_SAFE_PREFIX}* types may be returned as a "
                "data URI. Renderable/active types (SVG, HTML, XML) are blocked to prevent "
                "stored-XSS relay (see GHSA-779p-m5rp-r4h4). Use response_format='url' "
                "to hand the caller the /view link instead."
            )

        b64 = base64.b64encode(data).decode()
        return f"data:{normalized_type};base64,{b64}"

    tool_fns["comfyui_get_image"] = comfyui_get_image

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_output(
        filename: Annotated[
            str,
            Field(description="Output filename (video, audio, image, gif, etc.)"),
        ],
        subfolder: Annotated[
            str,
            Field(description="Subfolder within ComfyUI's output directory."),
        ] = "",
        response_format: Annotated[
            Literal["url", "path", "inline"],
            Field(
                description="'url' (default) returns a /view link; 'path' returns the "
                "ComfyUI-relative path; 'inline' returns a data URI for small, "
                "allow-listed media and falls back to a URL otherwise."
            ),
        ] = "url",
        base_url_override: Annotated[
            str | None,
            Field(
                description=(
                    "Optional override for URL responses; falls back to the configured base URL"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Retrieve a video, audio, image, or GIF output produced by ComfyUI.

        Use this for non-image outputs or when you need media metadata; use
        `comfyui_get_image` for raster images with preview thumbnails.

        Returns:
            `{status, filename, subfolder, content_type?, size_bytes?, url?,
            data_uri?, path?, note?}`. `inline` falls back to a URL when the
            type is not allow-listed or the file exceeds the 8 MiB cap.
        """
        clean_name = sanitizer.validate_output_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        await audit.async_log(
            tool="get_output",
            action="downloading",
            extra={
                "filename": clean_name,
                "subfolder": clean_subfolder,
                "response_format": response_format,
            },
        )

        base_url = base_url_override or image_view_base_url
        url = client.build_image_url(clean_name, clean_subfolder, base_url=base_url)

        if response_format == "url":
            return {
                "status": "url",
                "filename": clean_name,
                "subfolder": clean_subfolder,
                "url": url,
            }

        if response_format == "path":
            path = f"{clean_subfolder}/{clean_name}".lstrip("/")
            return {
                "status": "path",
                "filename": clean_name,
                "subfolder": clean_subfolder,
                "path": path,
                "note": "Relative to ComfyUI's output directory on the server, not the MCP host.",
            }

        if response_format != "inline":
            raise ValueError("response_format must be 'url', 'path', or 'inline'")

        data, content_type = await client.get_image(clean_name, clean_subfolder)
        normalized_type = (content_type or "").strip().lower().split(";")[0]
        result: dict[str, Any] = {
            "filename": clean_name,
            "subfolder": clean_subfolder,
            "content_type": normalized_type or None,
            "size_bytes": len(data),
            "url": url,
        }

        if (
            not normalized_type.startswith(_INLINE_OUTPUT_PREFIXES)
            or normalized_type in _INLINE_BLOCKED_TYPES
        ):
            await audit.async_log(
                tool="get_output",
                action="content_type_rejected",
                extra={
                    "filename": clean_name,
                    "content_type": content_type or "<missing>",
                },
            )
            result["status"] = "not_inlined"
            result["note"] = (
                f"Content type {content_type or '<missing>'!r} is not allow-listed for "
                "inline media; use the URL instead."
            )
            return result

        if len(data) > _MAX_INLINE_OUTPUT_BYTES:
            result["status"] = "too_large"
            result["note"] = (
                f"Output is {len(data)} bytes; the inline cap is "
                f"{_MAX_INLINE_OUTPUT_BYTES} bytes. Use the URL instead."
            )
            return result

        b64 = base64.b64encode(data).decode()
        result["status"] = "inline"
        result["data_uri"] = f"data:{normalized_type};base64,{b64}"
        return result

    tool_fns["comfyui_get_output"] = comfyui_get_output

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_list_outputs(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> PaginationEnvelope[dict[str, str]]:
        """List output files from ComfyUI's execution history.

        Args:
            limit: Maximum number of results to return (default: 25, max: 100)
            offset: Starting index for pagination (default: 0)

        Returns:
            JSON envelope with paginated list of objects with 'filename' and
            'subfolder' keys. Pass these values to comfyui_get_image to retrieve files.
        """
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
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        )
    )
    async def comfyui_upload_mask(
        filename: Annotated[
            str,
            Field(description="Name for the uploaded mask file (e.g. 'mask.png')"),
        ],
        mask_data: Annotated[
            str,
            Field(description="Base64-encoded mask image data"),
        ],
        original_image: Annotated[
            str,
            Field(
                description="Filename of the original image the mask applies to "
                "(must already exist in ComfyUI's input directory)"
            ),
        ],
        subfolder: Annotated[
            str,
            Field(description="Optional subfolder for the mask file"),
        ] = "",
        original_subfolder: Annotated[
            str,
            Field(description="Optional subfolder of the original image"),
        ] = "",
        destination: Annotated[
            Literal["input", "output", "temp"],
            Field(
                description="Destination directory. 'input' (default) is where "
                "workflows read user-supplied masks from; 'output' and 'temp' "
                "are usually only useful for testing or scripted setups."
            ),
        ] = "input",
        overwrite: Annotated[
            bool,
            Field(
                description="If True, replace any existing file with the same name. "
                "If False (default), ComfyUI auto-renames by suffixing ' (N)'."
            ),
        ] = False,
    ) -> str:
        """Upload a mask image to ComfyUI.

        The mask's alpha channel is merged into the original image's alpha channel
        by the ComfyUI server. The original image must already exist in ComfyUI.
        Defaults to ComfyUI's input directory.
        """
        clean_name = sanitizer.validate_filename(filename)
        clean_original = sanitizer.validate_filename(original_image)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        clean_original_subfolder = sanitizer.validate_subfolder(original_subfolder)
        raw = base64.b64decode(mask_data)
        sanitizer.validate_size(len(raw))
        original_ref: dict[str, str] = {
            "filename": clean_original,
            "type": "input",
        }
        if clean_original_subfolder:
            original_ref["subfolder"] = clean_original_subfolder
        await audit.async_log(
            tool="upload_mask",
            action="uploading",
            extra={
                "filename": clean_name,
                "original_image": clean_original,
                "size_bytes": len(raw),
                "destination": destination,
                "overwrite": overwrite,
            },
        )
        result = await client.upload_mask(
            raw,
            clean_name,
            original_ref,
            clean_subfolder,
            destination=destination,
            overwrite=overwrite,
        )
        await audit.async_log(tool="upload_mask", action="uploaded", extra={"result": result})
        return f"Uploaded mask {result.get('name', clean_name)} to ComfyUI {destination} directory"

    tool_fns["comfyui_upload_mask"] = comfyui_upload_mask

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_workflow_from_image(
        filename: str, subfolder: str = ""
    ) -> WorkflowFromImageResult:
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
