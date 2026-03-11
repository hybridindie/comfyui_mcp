# `get_workflow_from_image` Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `get_workflow_from_image` tool that extracts embedded workflow and prompt metadata from ComfyUI-generated PNG files.

**Architecture:** A stdlib PNG chunk parser (`_extract_png_metadata`) reads `tEXt`/`zTXt` chunks from image bytes. The tool fetches the image via `client.get_image()`, extracts metadata, parses JSON, and returns structured results. Lives in `tools/files.py` alongside existing file tools.

**Tech Stack:** Python 3.12 stdlib (`struct`, `zlib`, `json`), existing project infrastructure

---

## Chunk 1: PNG parser and tool

### Task 1: Add `_extract_png_metadata` parser with tests

**Files:**
- Modify: `src/comfyui_mcp/tools/files.py` (add imports for `json`, `struct`, `zlib`; add `_extract_png_metadata` function before `register_file_tools`)
- Test: `tests/test_tools_files.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools_files.py`:

```python
import json
import struct
import zlib

from comfyui_mcp.tools.files import _extract_png_metadata


def _build_png_with_text_chunks(text_chunks: dict[str, str]) -> bytes:
    """Build a minimal valid PNG with tEXt chunks for testing."""
    png_signature = b"\x89PNG\r\n\x1a\n"

    # Minimal IHDR chunk (13 bytes of data)
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1 RGB
    ihdr = _build_chunk(b"IHDR", ihdr_data)

    # tEXt chunks
    text_chunks_bytes = b""
    for key, value in text_chunks.items():
        chunk_data = key.encode("latin-1") + b"\x00" + value.encode("latin-1")
        text_chunks_bytes += _build_chunk(b"tEXt", chunk_data)

    # Minimal IDAT chunk (empty compressed data)
    idat = _build_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))

    # IEND chunk
    iend = _build_chunk(b"IEND", b"")

    return png_signature + ihdr + text_chunks_bytes + idat + iend


def _build_png_with_ztxt_chunks(text_chunks: dict[str, str]) -> bytes:
    """Build a minimal valid PNG with zTXt chunks for testing."""
    png_signature = b"\x89PNG\r\n\x1a\n"

    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = _build_chunk(b"IHDR", ihdr_data)

    ztxt_chunks_bytes = b""
    for key, value in text_chunks.items():
        compressed = zlib.compress(value.encode("utf-8"))
        chunk_data = key.encode("latin-1") + b"\x00" + b"\x00" + compressed
        ztxt_chunks_bytes += _build_chunk(b"zTXt", chunk_data)

    idat = _build_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
    iend = _build_chunk(b"IEND", b"")

    return png_signature + ihdr + ztxt_chunks_bytes + idat + iend


def _build_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build a PNG chunk: length + type + data + CRC."""
    import binascii

    chunk_body = chunk_type + data
    crc = binascii.crc32(chunk_body) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_body + struct.pack(">I", crc)


class TestExtractPngMetadata:
    def test_extracts_text_chunks(self):
        workflow = json.dumps({"1": {"class_type": "KSampler", "inputs": {}}})
        prompt = json.dumps({"1": {"class_type": "KSampler", "inputs": {}}})
        png_data = _build_png_with_text_chunks({"workflow": workflow, "prompt": prompt})
        result = _extract_png_metadata(png_data)
        assert "workflow" in result
        assert "prompt" in result
        assert result["workflow"] == workflow
        assert result["prompt"] == prompt

    def test_extracts_ztxt_compressed_chunks(self):
        workflow = json.dumps({"1": {"class_type": "KSampler", "inputs": {}}})
        png_data = _build_png_with_ztxt_chunks({"workflow": workflow})
        result = _extract_png_metadata(png_data)
        assert "workflow" in result
        assert result["workflow"] == workflow

    def test_returns_empty_for_no_metadata(self):
        png_data = _build_png_with_text_chunks({})
        result = _extract_png_metadata(png_data)
        assert result == {}

    def test_returns_empty_for_non_png(self):
        result = _extract_png_metadata(b"not a png file at all")
        assert result == {}

    def test_returns_empty_for_truncated_png(self):
        result = _extract_png_metadata(b"\x89PNG\r\n\x1a\n\x00")
        assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_files.py::TestExtractPngMetadata -v`
Expected: FAIL with `ImportError: cannot import name '_extract_png_metadata'`

- [ ] **Step 3: Write the implementation**

Add these imports at the top of `src/comfyui_mcp/tools/files.py`:

```python
import json
import struct
import zlib
```

Add this function before `register_file_tools`:

```python
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _extract_png_metadata(data: bytes) -> dict[str, str]:
    """Extract tEXt and zTXt metadata from PNG data.

    Returns a dict of key-value pairs from PNG text chunks.
    Returns an empty dict if the data is not valid PNG or has no text chunks.
    """
    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        return {}

    metadata: dict[str, str] = {}
    offset = 8  # Skip PNG signature

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

        elif chunk_type == b"zTXt":
            null_idx = chunk_data.find(b"\x00")
            if null_idx > 0 and null_idx + 2 <= len(chunk_data):
                key = chunk_data[:null_idx].decode("latin-1")
                # Skip compression method byte (always 0 = zlib)
                compressed = chunk_data[null_idx + 2 :]
                try:
                    value = zlib.decompress(compressed).decode("utf-8")
                    metadata[key] = value
                except (zlib.error, UnicodeDecodeError):
                    pass

        elif chunk_type == b"IEND":
            break

        # Move to next chunk: length(4) + type(4) + data(length) + crc(4)
        offset += 12 + length

    return metadata
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_files.py::TestExtractPngMetadata -v`
Expected: PASS

- [ ] **Step 5: Run lint and type check**

```bash
uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/comfyui_mcp/tools/files.py
```

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/tools/files.py tests/test_tools_files.py
git commit -m "feat: add _extract_png_metadata helper for PNG text chunk parsing"
```

---

### Task 2: Add `get_workflow_from_image` tool with tests

**Files:**
- Modify: `src/comfyui_mcp/tools/files.py` (add tool inside `register_file_tools`, update module docstring)
- Test: `tests/test_tools_files.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools_files.py`:

```python
class TestGetWorkflowFromImage:
    @respx.mock
    async def test_extracts_workflow_and_prompt(self, components):
        client, audit, limiter, sanitizer = components
        workflow_json = json.dumps({"1": {"class_type": "KSampler", "inputs": {}}})
        prompt_json = json.dumps({"1": {"class_type": "KSampler", "inputs": {}}})
        png_data = _build_png_with_text_chunks({"workflow": workflow_json, "prompt": prompt_json})
        respx.get("http://test:8188/view").mock(
            return_value=httpx.Response(200, content=png_data, headers={"content-type": "image/png"})
        )
        mcp_server = FastMCP("test")
        tools = register_file_tools(mcp_server, client, audit, limiter, sanitizer)
        result = await tools["get_workflow_from_image"](filename="test.png")
        assert result["workflow"] == {"1": {"class_type": "KSampler", "inputs": {}}}
        assert result["prompt"] == {"1": {"class_type": "KSampler", "inputs": {}}}
        assert "workflow" in result["message"].lower()
        assert "prompt" in result["message"].lower()

    @respx.mock
    async def test_extracts_ztxt_workflow(self, components):
        client, audit, limiter, sanitizer = components
        workflow_json = json.dumps({"1": {"class_type": "SaveImage", "inputs": {}}})
        png_data = _build_png_with_ztxt_chunks({"workflow": workflow_json})
        respx.get("http://test:8188/view").mock(
            return_value=httpx.Response(200, content=png_data, headers={"content-type": "image/png"})
        )
        mcp_server = FastMCP("test")
        tools = register_file_tools(mcp_server, client, audit, limiter, sanitizer)
        result = await tools["get_workflow_from_image"](filename="test.png")
        assert result["workflow"] == {"1": {"class_type": "SaveImage", "inputs": {}}}

    @respx.mock
    async def test_returns_none_when_no_metadata(self, components):
        client, audit, limiter, sanitizer = components
        png_data = _build_png_with_text_chunks({})
        respx.get("http://test:8188/view").mock(
            return_value=httpx.Response(200, content=png_data, headers={"content-type": "image/png"})
        )
        mcp_server = FastMCP("test")
        tools = register_file_tools(mcp_server, client, audit, limiter, sanitizer)
        result = await tools["get_workflow_from_image"](filename="test.png")
        assert result["workflow"] is None
        assert result["prompt"] is None
        assert "no workflow metadata" in result["message"].lower()

    @respx.mock
    async def test_rejects_non_png(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/view").mock(
            return_value=httpx.Response(200, content=b"\xff\xd8\xff\xe0JFIF", headers={"content-type": "image/jpeg"})
        )
        mcp_server = FastMCP("test")
        tools = register_file_tools(mcp_server, client, audit, limiter, sanitizer)
        with pytest.raises(ValueError, match="not a PNG"):
            await tools["get_workflow_from_image"](filename="photo.png")

    async def test_path_traversal_blocked(self, components):
        client, audit, limiter, sanitizer = components
        mcp_server = FastMCP("test")
        tools = register_file_tools(mcp_server, client, audit, limiter, sanitizer)
        with pytest.raises(PathValidationError):
            await tools["get_workflow_from_image"](filename="../../../etc/passwd.png")

    @respx.mock
    async def test_handles_malformed_json_in_chunk(self, components):
        client, audit, limiter, sanitizer = components
        png_data = _build_png_with_text_chunks({"workflow": "not valid json{{"})
        respx.get("http://test:8188/view").mock(
            return_value=httpx.Response(200, content=png_data, headers={"content-type": "image/png"})
        )
        mcp_server = FastMCP("test")
        tools = register_file_tools(mcp_server, client, audit, limiter, sanitizer)
        result = await tools["get_workflow_from_image"](filename="test.png")
        assert result["workflow"] is None
        assert "malformed" in result["message"].lower() or "no workflow" in result["message"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_files.py::TestGetWorkflowFromImage -v`
Expected: FAIL with `KeyError: 'get_workflow_from_image'`

- [ ] **Step 3: Write the implementation**

Update the module docstring of `src/comfyui_mcp/tools/files.py`:

```python
"""File operation tools: upload_image, get_image, list_outputs, get_workflow_from_image."""
```

Add this tool inside `register_file_tools`, after `upload_mask` and before `return tool_fns`:

```python
    @mcp.tool()
    async def get_workflow_from_image(filename: str, subfolder: str = "output") -> dict:
        """Extract embedded workflow and prompt metadata from a ComfyUI-generated PNG.

        ComfyUI embeds the full workflow JSON and prompt data in PNG text chunks.
        This enables extracting the exact settings used to generate an image
        for inspection or re-execution.

        Args:
            filename: Name of the PNG file to extract metadata from
            subfolder: Directory to look in (default: 'output')

        Returns:
            Dict with 'workflow' (parsed JSON or None), 'prompt' (parsed JSON or None),
            and 'message' (human-readable status).
        """
        limiter.check("get_workflow_from_image")
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        audit.log(
            tool="get_workflow_from_image",
            action="extracting",
            extra={"filename": clean_name, "subfolder": clean_subfolder},
        )

        data, _ = await client.get_image(clean_name, clean_subfolder)

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

        audit.log(
            tool="get_workflow_from_image",
            action="extracted",
            extra={
                "filename": clean_name,
                "has_workflow": workflow is not None,
                "has_prompt": prompt is not None,
            },
        )

        return {"workflow": workflow, "prompt": prompt, "message": message}

    tool_fns["get_workflow_from_image"] = get_workflow_from_image
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_files.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite, lint, and type check**

```bash
uv run pytest -v
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/comfyui_mcp/
```

Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/tools/files.py tests/test_tools_files.py
git commit -m "feat: add get_workflow_from_image tool for PNG metadata extraction

Closes #4"
```

---

### Task 3: Update README tools table

**Files:**
- Modify: `README.md` (add `get_workflow_from_image` to File Operations table, update project structure)

- [ ] **Step 1: Add entry to tools table**

In the File Operations table, add a row:

| `get_workflow_from_image` | Extract embedded workflow and prompt metadata from a ComfyUI-generated PNG. |

Update the project structure comment for `files.py`:

```
    └── files.py           # upload_image, get_image, list_outputs, upload_mask, get_workflow_from_image
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add get_workflow_from_image to README tools table"
```
