# Design: `get_workflow_from_image` tool

## Summary

Add a `get_workflow_from_image` MCP tool that extracts embedded workflow and prompt metadata from ComfyUI-generated PNG files. Uses a stdlib PNG chunk reader (no new dependencies).

Addresses: Issue #4

## Tool signature

```python
@mcp.tool()
async def get_workflow_from_image(filename: str, subfolder: str = "output") -> dict:
```

- **Input**: Filename and subfolder (same pattern as `get_image`)
- **Output**: Dict with `workflow`, `prompt`, and `message` keys
- **Location**: `tools/files.py` (alongside `get_image`)
- **Rate limit**: `file` category
- **Path sanitization**: `sanitizer.validate_filename()` and `sanitizer.validate_subfolder()`

## PNG chunk parser

Private function `_extract_png_metadata(data: bytes) -> dict[str, str]`:

1. Validates 8-byte PNG signature
2. Iterates chunks: 4-byte length, 4-byte type, data, 4-byte CRC
3. `tEXt` chunks: split on null byte for key/value
4. `zTXt` chunks: split on null byte for key, skip compression method byte, `zlib.decompress()` the rest
5. Stops at `IEND`
6. Returns dict of all text metadata (keys: `workflow`, `prompt`, etc.)
7. Returns empty dict if not valid PNG or no metadata — no exception from parser

## Return format

```python
{
    "workflow": {...},    # parsed JSON or None
    "prompt": {...},      # parsed JSON or None
    "message": "Extracted workflow (N nodes) and prompt from image"
}
```

- Both found: `"Extracted workflow (N nodes) and prompt from image"`
- One found: `"Extracted workflow from image"` / `"Extracted prompt from image"`
- Neither: `"No workflow metadata found in this image"`
- Not PNG: raises `ValueError("File is not a PNG image")`
- Malformed JSON in chunk: key set to `None`, noted in message

## Security

- Read-only, no execution
- Path sanitized through `PathSanitizer` (same as `get_image`)
- `limiter.check()` and `audit.log()` called per project rules
- PNG parser is defensive — malformed chunks return empty dict
- No new dependencies (stdlib `struct` + `zlib`)

## Tests

In `tests/test_tools_files.py`:

1. Extracts workflow and prompt from PNG with `tEXt` chunks
2. Extracts `zTXt` compressed metadata
3. Returns empty when no metadata in PNG
4. Rejects non-PNG data with `ValueError`
5. Path sanitization enforced (traversal blocked)
6. Unit test `_extract_png_metadata` directly
