# Add `comfyui_` Prefix to All Tool Names

**Issue:** #37
**Date:** 2026-04-02
**Status:** Approved

## Summary

Rename all 44 MCP tool functions from `{action}` to `comfyui_{action}` for multi-server namespace compatibility. Clean break, no backwards compatibility.

## Approach

Rename the Python functions directly (Approach B). The function name IS the MCP tool name — single source of truth, no drift.

## Scope

### Per tool module (8 modules in `src/comfyui_mcp/tools/`)

1. Rename function: `async def generate_image(...)` → `async def comfyui_generate_image(...)`
2. Update `tool_fns` dict key: `tool_fns["generate_image"]` → `tool_fns["comfyui_generate_image"]`

### What stays unchanged

- `register_*_tools()` function names — internal wiring, not client-visible
- `client.py` methods — HTTP layer, unrelated
- `server.py` wiring — calls register functions, doesn't reference tool names by string
- `limiter.check("tool_name")` calls — internal rate limiter labels, not client-visible
- `audit.async_log(tool="tool_name")` calls — internal log identifiers, not client-visible

### Files touched

| Category | Files |
|----------|-------|
| Tool modules | `src/comfyui_mcp/tools/{generation,workflow,jobs,discovery,history,models,files,nodes}.py` |
| Test files | `tests/test_tools_{generation,workflow,jobs,discovery,history,models,files,nodes}.py` |
| Integration test | `tests/test_integration.py` |
| Documentation | `README.md` (tools table), tool docstrings with cross-references |
| Security | `src/comfyui_mcp/security/model_checker.py` (warning messages) |

### Tool rename table

All 44 tools get the `comfyui_` prefix. Examples:

| Old Name | New Name |
|----------|----------|
| `generate_image` | `comfyui_generate_image` |
| `run_workflow` | `comfyui_run_workflow` |
| `list_models` | `comfyui_list_models` |
| `get_history` | `comfyui_get_history` |
| `search_models` | `comfyui_search_models` |
| ... (all 44 tools follow this pattern) | |

## Testing

- All existing tests updated to reference new names via `tools["comfyui_..."]`
- No new test logic needed — this is a rename, not a behavior change
- Full test suite must pass after rename
