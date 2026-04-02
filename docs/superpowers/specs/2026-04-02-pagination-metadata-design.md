# Pagination Metadata for List Tools

**Issue:** #39
**Date:** 2026-04-02
**Status:** Approved

## Summary

Add offset-based pagination with a consistent response envelope to 6 tools that return lists of items. This prevents context window flooding for LLM clients and gives callers control over result set size.

## Scope

### In scope (6 tools)

| Tool | File | Default Limit | Max Cap |
|------|------|---------------|---------|
| `list_models` | `tools/discovery.py` | 25 | 100 |
| `list_nodes` | `tools/discovery.py` | 25 | 100 |
| `get_history` | `tools/history.py` | 25 | 100 |
| `list_outputs` | `tools/files.py` | 25 | 100 |
| `search_models` | `tools/models.py` | 5 | 10 (existing config-driven) |
| `search_custom_nodes` | `tools/nodes.py` | 10 | 25 |

### Out of scope

- `list_model_folders`, `list_extensions`, `list_workflows`, `get_queue`, `get_download_tasks` — result sets too small to need pagination.
- Config-driven defaults/caps — hardcoded per-tool for now.
- Cursor-based pagination — offset-based is sufficient for in-memory list slicing.
- Changes to `client.py` — all pagination is tool-side.

## Design

### Pagination helper

New module: `src/comfyui_mcp/pagination.py`

A single pure function. `limit` of `None` or `0` uses `default_limit` (Python falsiness of `0` makes this natural). Negative `offset` is clamped to `0`.

```python
def paginate(
    items: list[Any],
    offset: int = 0,
    limit: int | None = None,
    default_limit: int = 25,
    max_limit: int = 100,
) -> dict[str, Any]:
    effective_limit = min(limit or default_limit, max_limit)
    effective_offset = max(offset, 0)
    total = len(items)
    page = items[effective_offset : effective_offset + effective_limit]
    return {
        "items": page,
        "total": total,
        "offset": effective_offset,
        "limit": effective_limit,
        "has_more": (effective_offset + effective_limit) < total,
    }
```

No config, no classes. Pure function, easy to unit test.

### Response envelope

All 6 tools return this consistent shape:

```json
{
  "items": [...],
  "total": 150,
  "offset": 0,
  "limit": 25,
  "has_more": true
}
```

This is a **breaking change** for all 6 tools:
- `list_models`, `list_nodes` currently return bare arrays
- `list_outputs` returns a bare array of dicts
- `get_history` returns a dict keyed by prompt_id
- `search_models` returns `{"results": [...], "query": "...", "source": "..."}`
- `search_custom_nodes` returns `{"results": [...], "query": "..."}`

For search tools, metadata fields (`query`, `source`) move into the envelope as extra top-level keys alongside the pagination fields.

### Tool signature changes

Each tool gets `limit: int` and `offset: int = 0` optional parameters. The `limit` default varies per tool (see table above).

**List tools pattern:**
```python
async def list_models(
    folder: str = "checkpoints",
    limit: int = 25,
    offset: int = 0,
) -> str:
    # ... existing fetch logic ...
    return json.dumps(paginate(models, offset, limit, default_limit=25, max_limit=100))
```

**Search tools pattern:**
```python
async def search_models(
    query: str,
    source: str = "civitai",
    model_type: str = "",
    limit: int = 5,
    offset: int = 0,
) -> str:
    # ... existing fetch/score logic ...
    result = paginate(results, offset, limit, default_limit=5, max_limit=cap)
    result["query"] = query
    result["source"] = source
    return json.dumps(result)
```

### get_history special handling

ComfyUI's `/history` endpoint returns a dict keyed by prompt_id, not a list. The tool:

1. Requests `max_items=100` from ComfyUI (our max cap, down from the current hardcoded 200)
2. Converts to a list with `prompt_id` injected into each entry
3. Applies `paginate()` on the list

```python
async def get_history(limit: int = 25, offset: int = 0) -> str:
    raw = await client.get_history(max_items=100)
    entries = [{"prompt_id": k, **v} for k, v in raw.items()]
    return json.dumps(paginate(entries, offset, limit, default_limit=25, max_limit=100))
```

### list_outputs special handling

Continues to derive data from `client.get_history(max_items=100)`, extract unique `(filename, subfolder)` pairs, dedup, and sort. The `paginate()` call wraps the final sorted list. No change to internal data source logic.

### search_custom_nodes changes

The hardcoded `_MAX_SEARCH_RESULTS = 10` constant is removed. The scoring/ranking logic stays, but the final slice is handled by `paginate()` with `default_limit=10, max_limit=25`.

## Testing

### New: `tests/test_pagination.py`

Unit tests for the `paginate()` helper:
- Basic slicing (offset=0, limit=5 on a 20-item list)
- Offset beyond end returns empty `items`, `has_more: false`
- Limit clamped to max_limit
- Negative offset treated as 0
- `None` limit uses default_limit
- `has_more` boundary: true when more items exist, false at exact end

### Updated: existing tool test files

In each tool's existing test file:
- Verify paginated tools return the envelope shape (`items`, `total`, `offset`, `limit`, `has_more`)
- Verify default limit/offset when params omitted
- Verify `has_more` correctness
- For search tools: verify `query`/`source` metadata preserved alongside pagination fields
