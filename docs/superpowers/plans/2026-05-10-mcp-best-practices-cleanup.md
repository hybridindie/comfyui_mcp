# MCP Best-Practices Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the actionable findings from a best-practices audit of the comfyui_mcp tool surface. Six concrete drift items across pagination, parameter schemas, parameter naming, and docstrings that close gaps with MCP guidance and CLAUDE.md project rules.

**Architecture:** Surgical fixes in the tool layer (`src/comfyui_mcp/tools/*.py`) plus one shared addition to `pagination.py` for reusable `LimitField` / `OffsetField` type aliases. No client-layer or security-layer changes. Two parameter renames (`id` → `node_id`, `format` → `output_format`) are deliberate breaking changes for MCP callers — documented in the relevant commit messages.

**Tech Stack:** Python 3.12, FastMCP, Pydantic `Field`/`Annotated`, pytest with `asyncio_mode = auto`, respx for HTTP mocking.

---

## File Structure

**Modify:**
- `src/comfyui_mcp/pagination.py` — add `LimitField`, `OffsetField` `Annotated` type aliases.
- `src/comfyui_mcp/tools/history.py` — bump cap, use shared fields.
- `src/comfyui_mcp/tools/discovery.py` — paginate three holdout list tools, use shared fields, beef up stub docstrings.
- `src/comfyui_mcp/tools/files.py` — use shared fields on `list_outputs`.
- `src/comfyui_mcp/tools/nodes.py` — rename `id` → `node_id`, add Field constraints, use shared fields on `search_custom_nodes`.
- `src/comfyui_mcp/tools/generation.py` — rename `format` → `output_format`, use `Literal`.
- `src/comfyui_mcp/tools/workflow.py` — fix `validate_workflow` docstring.
- `tests/test_tools_discovery.py` — update tests for newly-paginated tools.
- `tests/test_tools_nodes.py` — update tests for `node_id` rename.
- `tests/test_tools_generation.py` — update tests for `output_format` rename.
- `tests/test_pagination.py` — add tests for new field aliases.
- `tests/test_tools_history.py` — confirm new cap behavior.
- `README.md` — flag the breaking parameter renames.

No new files except the in-place `pagination.py` additions.

---

## Task 1: Fix `comfyui_get_history` pagination cap

The tool internally caps `max_items=100` then paginates the result. The `total` reported is the size of the cap, not the true history count. Fix by bumping to 1000 (the client's hard cap from `client.get_history`'s `min(max_items, 1000)`) and documenting the cap.

**Files:**
- Modify: `src/comfyui_mcp/tools/history.py:42` (and docstring at lines 34-39)
- Test: `tests/test_tools_history.py`

- [ ] **Step 1: Read existing test file to confirm patterns**

Run: `cat tests/test_tools_history.py`

Note the existing test layout, fixture name, and import style — mirror them in step 2.

- [ ] **Step 2: Write a failing test for the bumped cap**

Add to `tests/test_tools_history.py` inside the existing test class (or at module level if no class):

```python
    @respx.mock
    async def test_get_history_passes_1000_cap_to_client(self, components):
        client, audit, limiter = components
        # The tool should request up to 1000 history items from the client
        # so that pagination can report a meaningful `total` for callers paging
        # through history.
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        await tools["comfyui_get_history"]()
        request = route.calls.last.request
        params = dict(request.url.params.multi_items())
        assert params.get("max_items") == "1000"
```

If the existing test file uses a different fixture or import pattern (e.g. `mcp = FastMCP("test")` is already wrapped in a helper), match that.

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_tools_history.py::test_get_history_passes_1000_cap_to_client -v` (use the right test path/class — adjust based on the existing file's structure)
Expected: FAIL — currently the request will have `max_items=100`.

- [ ] **Step 4: Update the tool**

In `src/comfyui_mcp/tools/history.py`, change line 42 from:

```python
        raw = await client.get_history(max_items=100)
```

to:

```python
        raw = await client.get_history(max_items=1000)
```

And update the docstring (lines 34-39) to:

```python
        """Browse ComfyUI execution history (read-only).

        Covers up to the 1000 most recent history entries — older entries are
        unreachable. Pagination operates over that window.

        Args:
            limit: Maximum number of results to return (default: 25, max: 100)
            offset: Starting index for pagination (default: 0)
        """
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_tools_history.py -v`
Expected: all PASS, including pre-existing tests.

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/tools/history.py tests/test_tools_history.py
git commit -m "Bump get_history internal cap from 100 to 1000 to fix pagination total"
```

---

## Task 2: Fix `comfyui_validate_workflow` docstring

The docstring says it returns a JSON string; the function actually returns a `dict[str, Any]`. One-line edit.

**Files:**
- Modify: `src/comfyui_mcp/tools/workflow.py:183-185`

- [ ] **Step 1: Apply the docstring fix**

In `src/comfyui_mcp/tools/workflow.py`, replace lines 183-185:

```python
        Returns:
            JSON string with: valid (bool), errors (list), warnings (list),
            node_count (int), pipeline (str).
        """
```

with:

```python
        Returns:
            Dict with keys: valid (bool), errors (list), warnings (list),
            node_count (int), pipeline (str).
        """
```

- [ ] **Step 2: Run existing tests to confirm no regression**

Run: `uv run pytest tests/test_tools_workflow.py -v`
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add src/comfyui_mcp/tools/workflow.py
git commit -m "Fix validate_workflow docstring: returns dict, not JSON string"
```

---

## Task 3: Add `LimitField` / `OffsetField` type aliases

Promote the standard pagination params to reusable `Annotated[int, Field(...)]` aliases so list tools can declare schema constraints in one line. Keep the existing `paginate(...)` runtime helper unchanged.

**Files:**
- Modify: `src/comfyui_mcp/pagination.py` (add new aliases)
- Test: `tests/test_pagination.py`

- [ ] **Step 1: Write a failing test for the new aliases**

Add to `tests/test_pagination.py`:

```python
def test_limit_field_default_and_bounds():
    from typing import get_type_hints

    from pydantic import BaseModel

    from comfyui_mcp.pagination import LimitField, OffsetField

    class _Model(BaseModel):
        limit: LimitField = 25
        offset: OffsetField = 0

    schema = _Model.model_json_schema()
    assert schema["properties"]["limit"]["minimum"] == 1
    assert schema["properties"]["limit"]["maximum"] == 100
    assert schema["properties"]["offset"]["minimum"] == 0
    # Description present
    assert "results" in schema["properties"]["limit"]["description"].lower()
    assert "pagination" in schema["properties"]["offset"]["description"].lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_pagination.py::test_limit_field_default_and_bounds -v`
Expected: FAIL with `ImportError: cannot import name 'LimitField' from 'comfyui_mcp.pagination'`.

- [ ] **Step 3: Add the aliases**

Append to `src/comfyui_mcp/pagination.py`:

```python
from typing import Annotated  # noqa: E402

from pydantic import Field  # noqa: E402

LimitField = Annotated[
    int,
    Field(
        ge=1,
        le=100,
        description="Maximum number of results to return (1-100, default varies by tool).",
    ),
]

OffsetField = Annotated[
    int,
    Field(
        ge=0,
        description="Zero-based starting index for pagination.",
    ),
]
```

(The `# noqa: E402` annotations are because these new imports come after the existing `paginate` function — ruff would otherwise flag module-level imports below code. If the existing import block is at the top of the file with no code in between, omit the `# noqa` markers and put the imports there instead.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_pagination.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and format**

Run: `uv run ruff check src/comfyui_mcp/pagination.py && uv run ruff format src/comfyui_mcp/pagination.py && uv run mypy src/comfyui_mcp/pagination.py`
Expected: clean. If ruff complains about import order, move the imports to the top of the file.

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/pagination.py tests/test_pagination.py
git commit -m "Add LimitField and OffsetField shared pagination type aliases"
```

---

## Task 4: Apply `LimitField` / `OffsetField` to existing paginated tools

Update list tools that currently take bare `limit: int = 25, offset: int = 0` to use the shared aliases so MCP schemas advertise the `ge`/`le` constraints. Tools with non-default bounds (e.g., `search_custom_nodes` max=25) keep inline `Field` since their bounds differ.

**Files:**
- Modify: `src/comfyui_mcp/tools/history.py:33`
- Modify: `src/comfyui_mcp/tools/discovery.py:170-171, 196`
- Modify: `src/comfyui_mcp/tools/files.py:207`

- [ ] **Step 1: Update `comfyui_get_history`**

In `src/comfyui_mcp/tools/history.py`, replace the existing import block at the top with (preserving existing imports):

```python
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.pagination import LimitField, OffsetField, paginate
from comfyui_mcp.security.rate_limit import RateLimiter
```

Replace the function signature on line 33:

```python
    async def comfyui_get_history(limit: int = 25, offset: int = 0) -> dict[str, Any]:
```

with:

```python
    async def comfyui_get_history(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> dict[str, Any]:
```

- [ ] **Step 2: Update `comfyui_list_models` and `comfyui_list_nodes`**

In `src/comfyui_mcp/tools/discovery.py`, add `LimitField, OffsetField` to the existing pagination import:

Find the line:

```python
from comfyui_mcp.pagination import paginate
```

Replace with:

```python
from comfyui_mcp.pagination import LimitField, OffsetField, paginate
```

Then replace the `comfyui_list_models` signature (lines 170-171 are inside the function definition; the signature spans multiple lines):

```python
        limit: int = 25,
        offset: int = 0,
```

with:

```python
        limit: LimitField = 25,
        offset: OffsetField = 0,
```

And `comfyui_list_nodes` line 196:

```python
    async def comfyui_list_nodes(limit: int = 25, offset: int = 0) -> dict[str, Any]:
```

with:

```python
    async def comfyui_list_nodes(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> dict[str, Any]:
```

- [ ] **Step 3: Update `comfyui_list_outputs`**

In `src/comfyui_mcp/tools/files.py`, find the existing import:

```python
from comfyui_mcp.pagination import paginate
```

Replace with:

```python
from comfyui_mcp.pagination import LimitField, OffsetField, paginate
```

Then replace the `comfyui_list_outputs` signature on line 207:

```python
    async def comfyui_list_outputs(limit: int = 25, offset: int = 0) -> dict[str, Any]:
```

with:

```python
    async def comfyui_list_outputs(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> dict[str, Any]:
```

- [ ] **Step 4: Run the affected test files**

Run: `uv run pytest tests/test_tools_history.py tests/test_tools_discovery.py tests/test_tools_files.py -v`
Expected: all PASS — these are pure type-annotation refactors, runtime behavior unchanged.

- [ ] **Step 5: Lint and format**

Run: `uv run ruff check src/ && uv run ruff format --check src/ && uv run mypy src/comfyui_mcp/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/tools/history.py src/comfyui_mcp/tools/discovery.py src/comfyui_mcp/tools/files.py
git commit -m "Use shared LimitField/OffsetField in paginated list tools"
```

---

## Task 5: Paginate the holdout list tools

`comfyui_list_extensions`, `comfyui_list_model_folders`, and `comfyui_list_workflows` return bare lists with no pagination. Wrap with `paginate()` so they match the project's contract.

**Files:**
- Modify: `src/comfyui_mcp/tools/discovery.py:236-242, 252-258, 284-290`
- Test: `tests/test_tools_discovery.py:95-106, 123-135`

### Step 1: Update `comfyui_list_extensions`

- [ ] In `src/comfyui_mcp/tools/discovery.py`, replace the body of `comfyui_list_extensions` (lines 252-256):

```python
    async def comfyui_list_extensions() -> list[Any]:
        """List available ComfyUI extensions."""
        limiter.check("list_extensions")
        await audit.async_log(tool="list_extensions", action="called")
        return await client.get_extensions()
```

with:

```python
    async def comfyui_list_extensions(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> dict[str, Any]:
        """List installed ComfyUI extensions (front-end / back-end JavaScript modules
        registered with the ComfyUI server).

        Returns a paginated envelope: ``{items, total, offset, limit, has_more}``.
        Each item is the extension's URL/path string.
        """
        limiter.check("list_extensions")
        await audit.async_log(tool="list_extensions", action="called")
        extensions = await client.get_extensions()
        return paginate(extensions, offset, limit, default_limit=25, max_limit=100)
```

### Step 2: Update `comfyui_list_model_folders`

- [ ] Replace the body (lines 284-288):

```python
    async def comfyui_list_model_folders() -> list[Any]:
        """List available model folder types (checkpoints, loras, vae, etc.)."""
        limiter.check("list_model_folders")
        await audit.async_log(tool="list_model_folders", action="called")
        return await client.get_model_types()
```

with:

```python
    async def comfyui_list_model_folders(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> dict[str, Any]:
        """List the model-folder types ComfyUI recognizes (checkpoints, loras, vae,
        controlnet, etc.). Pass any returned name as the ``folder`` argument to
        ``comfyui_list_models`` or ``comfyui_get_model_metadata``.

        Returns a paginated envelope: ``{items, total, offset, limit, has_more}``.
        """
        limiter.check("list_model_folders")
        await audit.async_log(tool="list_model_folders", action="called")
        folders = await client.get_model_types()
        return paginate(folders, offset, limit, default_limit=25, max_limit=100)
```

### Step 3: Update `comfyui_list_workflows`

- [ ] Replace the body (lines 236-240):

```python
    async def comfyui_list_workflows() -> dict[str, Any]:
        """List available workflow templates."""
        limiter.check("list_workflows")
        await audit.async_log(tool="list_workflows", action="called")
        return await client.get_workflow_templates()
```

with:

```python
    async def comfyui_list_workflows(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> dict[str, Any]:
        """List workflow templates registered on the ComfyUI server (the ``/workflow_templates``
        endpoint, populated by installed front-end packages).

        This is distinct from ``comfyui_create_workflow``'s built-in template names
        (txt2img, img2img, etc.) which are hard-coded in the MCP for graph generation.

        Returns a paginated envelope: ``{items, total, offset, limit, has_more}``.
        Each item is ``{"package": str, "templates": [...]}`` from the server.
        """
        limiter.check("list_workflows")
        await audit.async_log(tool="list_workflows", action="called")
        templates_by_package = await client.get_workflow_templates()
        # client.get_workflow_templates returns dict[package_name, list[template]];
        # flatten to a list of {package, templates} so paginate() can slice it.
        items = [
            {"package": package, "templates": templates}
            for package, templates in (templates_by_package or {}).items()
        ]
        return paginate(items, offset, limit, default_limit=25, max_limit=100)
```

### Step 4: Update `tests/test_tools_discovery.py`

- [ ] Replace `class TestListExtensions` (lines 95-106) with:

```python
class TestListExtensions:
    @respx.mock
    async def test_list_extensions(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/extensions").mock(
            return_value=httpx.Response(200, json=["ext1", "ext2"])
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)

        result = await tools["comfyui_list_extensions"]()
        assert result["items"] == ["ext1", "ext2"]
        assert result["total"] == 2
        assert result["offset"] == 0
        assert result["has_more"] is False
```

- [ ] Replace `class TestListModelFolders` (lines 123-135) with:

```python
class TestListModelFolders:
    @respx.mock
    async def test_list_model_folders(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/models").mock(
            return_value=httpx.Response(200, json=["checkpoints", "loras", "vae"])
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)

        result = await tools["comfyui_list_model_folders"]()
        assert "checkpoints" in result["items"]
        assert "loras" in result["items"]
        assert result["total"] == 3
        assert result["has_more"] is False
```

### Step 5: Verify or add a `TestListWorkflows` test

- [ ] Search for existing tests for `comfyui_list_workflows` in `tests/test_tools_discovery.py`:

Run: `grep -n "list_workflows\|TestListWorkflows" tests/test_tools_discovery.py`

If a test exists, update its assertions to match the new envelope (`result["items"]`, `result["total"]`). If none exists, add this minimal test inside `tests/test_tools_discovery.py`:

```python
class TestListWorkflows:
    @respx.mock
    async def test_list_workflows_paginates(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/workflow_templates").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ComfyUI-Manager": ["templ_a", "templ_b"],
                    "ComfyUI-Frontend": ["templ_c"],
                },
            )
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)

        result = await tools["comfyui_list_workflows"]()
        assert "items" in result
        assert result["total"] == 2  # two packages, not three templates
        assert result["has_more"] is False
        package_names = {entry["package"] for entry in result["items"]}
        assert package_names == {"ComfyUI-Manager", "ComfyUI-Frontend"}
```

### Step 6: Run all discovery tests

- [ ] Run: `uv run pytest tests/test_tools_discovery.py -v`
Expected: all PASS.

### Step 7: Commit

- [ ] ```bash
git add src/comfyui_mcp/tools/discovery.py tests/test_tools_discovery.py
git commit -m "Paginate comfyui_list_extensions, _model_folders, _workflows"
```

---

## Task 6: Rename `id` → `node_id` in custom-node tools (BREAKING)

The three node-management tools (`install_custom_node`, `uninstall_custom_node`, `update_custom_node`) currently use `id: str` as the parameter name with `# noqa: A002`. Rename to `node_id`, drop the noqa, add `Field` constraints. **This is a breaking change for MCP callers.**

**Files:**
- Modify: `src/comfyui_mcp/tools/nodes.py:273-326, 335-378, 388-440`
- Test: `tests/test_tools_nodes.py`

### Step 1: Update tool signatures and bodies in `nodes.py`

- [ ] First, ensure `Annotated` and `Field` are imported in `nodes.py`. Check the imports at the top of the file. If they aren't already present, add to the existing typing import:

```python
from typing import Annotated, Any
```

and to a third-party import block:

```python
from pydantic import Field
```

Then replace the `comfyui_install_custom_node` signature (around line 273-277):

```python
    async def comfyui_install_custom_node(
        id: str,  # noqa: A002
        version: str = "",
        restart: bool = False,
    ) -> str:
```

with:

```python
    async def comfyui_install_custom_node(
        node_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Custom-node pack ID from the ComfyUI Manager registry. "
                "Use comfyui_search_custom_nodes to discover IDs.",
            ),
        ],
        version: Annotated[
            str,
            Field(default="", description="Specific version to install. Empty string = latest."),
        ] = "",
        restart: Annotated[
            bool,
            Field(
                default=False,
                description="If True, restart ComfyUI after install and run a security audit.",
            ),
        ] = False,
    ) -> str:
```

Then in the body (lines 281-323), replace **every** occurrence of `id` with `node_id`. Concretely:

- `Args:` block: replace `id:` with `node_id:`.
- `_validate_node_id(id)` → `_validate_node_id(node_id)`
- `extra={"id": id, ...}` → `extra={"node_id": node_id, ...}` (both occurrences)
- `params={...}` block: `"id": id,` → `"id": node_id,` (the wire-level key stays `id` because that's the upstream ComfyUI Manager API; only the Python parameter name changes)
- `node_id=id,` → `node_id=node_id,` (this kwarg to `_execute_node_operation` already used `node_id` as the keyword)

The same renames apply to `comfyui_uninstall_custom_node` (lines 335-378) and `comfyui_update_custom_node` (lines 388-440).

For `comfyui_uninstall_custom_node`, the `params={...}` block uses `"node_name": id` — change to `"node_name": node_id`.

For `comfyui_update_custom_node`, the `params={...}` block uses `"node_name": id` — change to `"node_name": node_id`.

After all three tools are updated, signature for `uninstall`:

```python
    async def comfyui_uninstall_custom_node(
        node_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Custom-node pack ID to uninstall.",
            ),
        ],
        restart: Annotated[
            bool,
            Field(default=False, description="If True, restart ComfyUI after uninstall."),
        ] = False,
    ) -> str:
```

And `update`:

```python
    async def comfyui_update_custom_node(
        node_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Custom-node pack ID to update to the latest version.",
            ),
        ],
        restart: Annotated[
            bool,
            Field(
                default=False,
                description="If True, restart ComfyUI after update and run a security audit.",
            ),
        ] = False,
    ) -> str:
```

Update the docstring `Args:` blocks for all three tools to reflect the rename.

### Step 2: Update `comfyui_search_custom_nodes` to use shared fields

- [ ] In `src/comfyui_mcp/tools/nodes.py`, find the existing `from comfyui_mcp.pagination import paginate` line and replace with:

```python
from comfyui_mcp.pagination import OffsetField, paginate
```

(Note: we use `OffsetField` here but keep the inline `LimitField` in this tool because its max is 25, not 100.)

Then replace the `comfyui_search_custom_nodes` signature (lines 184-188):

```python
    async def comfyui_search_custom_nodes(
        query: str,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
```

with:

```python
    async def comfyui_search_custom_nodes(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Search term matched against installed node-pack name, "
                "ID, description, and author.",
            ),
        ],
        limit: Annotated[
            int,
            Field(
                default=10,
                ge=1,
                le=25,
                description="Maximum number of matches to return (1-25).",
            ),
        ] = 10,
        offset: OffsetField = 0,
    ) -> dict[str, Any]:
```

### Step 3: Update tests for the rename

- [ ] In `tests/test_tools_nodes.py`, find every test invocation that passes `id=` to the install/uninstall/update tools and rename to `node_id=`.

Run: `grep -n 'tools\["comfyui_\(install\|uninstall\|update\)_custom_node"\](' tests/test_tools_nodes.py` to find call sites.

For each call site, change:

```python
await tools["comfyui_install_custom_node"](id="some-pack")
```

to:

```python
await tools["comfyui_install_custom_node"](node_id="some-pack")
```

Same for `uninstall` and `update`.

If any test passes `id` positionally without a keyword, leave it unchanged (positional still works, just the named argument changes).

### Step 4: Run node tests

- [ ] Run: `uv run pytest tests/test_tools_nodes.py -v`
Expected: all PASS. If any test still passes `id=`, rename it.

### Step 5: Run full test suite to catch any other callers

- [ ] Run: `uv run pytest -v 2>&1 | tail -20`
Expected: 0 failures.

If anything fails because a test passed `id=` as a kwarg, rename it.

### Step 6: Lint and format

- [ ] Run: `uv run ruff check src/comfyui_mcp/tools/nodes.py && uv run ruff format src/comfyui_mcp/tools/nodes.py && uv run mypy src/comfyui_mcp/tools/nodes.py`
Expected: clean. The `# noqa: A002` markers should now be gone with the parameter rename.

### Step 7: Commit

- [ ] ```bash
git add src/comfyui_mcp/tools/nodes.py tests/test_tools_nodes.py
git commit -m "Rename id->node_id in custom-node tools (BREAKING)

Adds Field constraints (min_length=1, max_length=200) and removes the
noqa A002 builtin-shadowing markers. MCP callers passing 'id' as a kwarg
must update to 'node_id'."
```

---

## Task 7: Rename `format` → `output_format` in `comfyui_summarize_workflow` (BREAKING)

The tool's `format: str` parameter shadows the `format` builtin (silenced with `# noqa: A002`) and is hand-validated against `{"text", "mermaid"}`. Rename to `output_format` and use `Literal["text", "mermaid"]` so the schema advertises the choices.

**Files:**
- Modify: `src/comfyui_mcp/tools/generation.py:553-597`
- Test: `tests/test_tools_generation.py`

### Step 1: Update the tool signature and body

- [ ] In `src/comfyui_mcp/tools/generation.py`, ensure `Literal` is imported (the file already imports `Annotated`, `Any`; check whether `Literal` is in the `from typing import` line — if not, add it).

Then replace lines 553-597 (whole function), starting from:

```python
    async def comfyui_summarize_workflow(workflow: str, format: str = "text") -> str:  # noqa: A002
        """Summarize a ComfyUI workflow's structure, data flow, and key parameters.
```

with:

```python
    async def comfyui_summarize_workflow(
        workflow: Annotated[
            str,
            Field(
                description="JSON string of a ComfyUI workflow (API format). "
                "Each top-level key is a node ID, each value has 'class_type' and 'inputs'.",
            ),
        ],
        output_format: Annotated[
            Literal["text", "mermaid"],
            Field(
                default="text",
                description="Output format: 'text' (human-readable summary) or "
                "'mermaid' (Mermaid flowchart markup).",
            ),
        ] = "text",
    ) -> str:
        """Summarize a ComfyUI workflow's structure, data flow, and key parameters.

        Parses the workflow graph, extracts models, parameters, and execution flow.
        Enriches with display names from the ComfyUI server when available.
        """
        summary_limiter = read_limiter if read_limiter is not None else limiter
        summary_limiter.check("summarize_workflow")

        try:
            wf = json.loads(workflow)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON workflow: {e}") from e

        if not isinstance(wf, dict):
            raise ValueError("Workflow must be a JSON object keyed by node IDs")

        # Best-effort API enrichment
        object_info: dict[str, Any] | None = None
        with contextlib.suppress(httpx.HTTPError, OSError):
            object_info = await client.get_object_info()

        analysis = _analyze_workflow(wf, object_info)
        await audit.async_log(
            tool="summarize_workflow",
            action="summarized",
            extra={
                "node_count": analysis["node_count"],
                "pipeline": analysis["pipeline"],
                "format": output_format,
            },
        )
        if output_format == "mermaid":
            return _format_mermaid(analysis)
        return _format_summary(analysis)
```

The hand-written `output_format = format.lower().strip()` and `if output_format not in {"text", "mermaid"}` checks are removed because pydantic's `Literal` enforces them at the schema/validation boundary.

### Step 2: Update tests for the rename

- [ ] In `tests/test_tools_generation.py`, find every call to `comfyui_summarize_workflow` and rename `format=` to `output_format=`.

Run: `grep -n 'comfyui_summarize_workflow' tests/test_tools_generation.py`

For each call site that passes `format="..."` rename to `output_format="..."`. Calls that pass only `workflow=...` are unaffected.

### Step 3: Run tests

- [ ] Run: `uv run pytest tests/test_tools_generation.py -v -k summarize`
Expected: all PASS.

### Step 4: Lint and format

- [ ] Run: `uv run ruff check src/comfyui_mcp/tools/generation.py && uv run ruff format src/comfyui_mcp/tools/generation.py && uv run mypy src/comfyui_mcp/tools/generation.py`
Expected: clean. The `# noqa: A002` should be gone.

### Step 5: Commit

- [ ] ```bash
git add src/comfyui_mcp/tools/generation.py tests/test_tools_generation.py
git commit -m "Rename summarize_workflow format->output_format with Literal type (BREAKING)

Replaces hand-rolled validation with pydantic Literal['text', 'mermaid'].
MCP callers passing 'format' as a kwarg must update to 'output_format'."
```

---

## Task 8: Beef up stub docstrings

Improve four stub-quality docstrings (`list_extensions`, `list_model_folders`, `get_server_features`, `get_node_info`) and add cross-references between `comfyui_run_workflow` and `comfyui_run_workflow_stream`.

Note: `comfyui_list_extensions` and `comfyui_list_model_folders` already had docstring upgrades in Task 5 (the new docstrings include detail and pagination shape). This task covers the remaining three plus the run_workflow cross-references.

**Files:**
- Modify: `src/comfyui_mcp/tools/discovery.py` (`get_server_features`, `get_node_info`)
- Modify: `src/comfyui_mcp/tools/generation.py` (`run_workflow`, `run_workflow_stream` docstrings)

### Step 1: Update `comfyui_get_server_features` docstring

- [ ] In `src/comfyui_mcp/tools/discovery.py`, replace lines 268-272:

```python
    async def comfyui_get_server_features() -> dict[str, Any]:
        """Get ComfyUI server features and capabilities."""
        limiter.check("get_server_features")
        await audit.async_log(tool="get_server_features", action="called")
        return await client.get_features()
```

with:

```python
    async def comfyui_get_server_features() -> dict[str, Any]:
        """Get the feature flags advertised by the ComfyUI server.

        Returns the raw ``/features`` response — typically a dict of
        {feature_name: bool}. Useful for capability-based branching, e.g.
        checking ``supports_preview_metadata`` before requesting preview-format
        images via ``comfyui_get_image``.
        """
        limiter.check("get_server_features")
        await audit.async_log(tool="get_server_features", action="called")
        return await client.get_features()
```

### Step 2: Update `comfyui_get_node_info` to add Field description

- [ ] In `src/comfyui_mcp/tools/discovery.py`, find the `comfyui_get_node_info` definition. The current signature (line 218) is:

```python
    async def comfyui_get_node_info(node_class: str) -> dict[str, Any]:
        """Get detailed information about a specific node type."""
```

Replace with:

```python
    async def comfyui_get_node_info(
        node_class: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Node class name (e.g. 'KSampler', 'CLIPTextEncode'). "
                "Use comfyui_list_nodes to discover available class names.",
            ),
        ],
    ) -> dict[str, Any]:
        """Get the input/output schema and metadata for a single ComfyUI node type.

        Returns a dict with keys: input, input_order, is_input_list, output,
        output_is_list, output_name, name, display_name, description, python_module,
        category, output_node, search_aliases, plus optional flags like deprecated,
        experimental, and api_node when set on the node.
        """
```

Ensure `Annotated` and `Field` are already imported in `discovery.py`. If not, add them — check the existing imports.

### Step 3: Cross-reference run_workflow and run_workflow_stream

- [ ] In `src/comfyui_mcp/tools/generation.py`, find `comfyui_run_workflow` and `comfyui_run_workflow_stream`. Add a "See also:" line to each docstring pointing at the other.

For `comfyui_run_workflow`, locate its docstring (search for `async def comfyui_run_workflow(`) and append at the end of the existing docstring (before the closing `"""`):

```
        See also: comfyui_run_workflow_stream for a streaming variant that emits
        per-node progress events while the workflow executes.
```

For `comfyui_run_workflow_stream`, append:

```
        See also: comfyui_run_workflow for a non-streaming variant. Use this
        streaming version when you need real-time per-node progress events
        (intended for tooling that surfaces progress to a user); use the
        non-streaming variant for fire-and-forget submission or when you only
        need the final result.
```

### Step 4: Run tests

- [ ] Run: `uv run pytest tests/test_tools_discovery.py tests/test_tools_generation.py -v`
Expected: all PASS — pure docstring/annotation changes, no runtime behavior change.

### Step 5: Lint and format

- [ ] Run: `uv run ruff check src/ && uv run ruff format --check src/ && uv run mypy src/comfyui_mcp/`
Expected: clean.

### Step 6: Commit

- [ ] ```bash
git add src/comfyui_mcp/tools/discovery.py src/comfyui_mcp/tools/generation.py
git commit -m "Improve stub docstrings and cross-reference run_workflow variants"
```

---

## Task 9: README update

Document the breaking parameter renames so callers know to update.

**Files:**
- Modify: `README.md`

### Step 1: Find the right section

- [ ] Run: `grep -n "comfyui_install_custom_node\|comfyui_summarize_workflow\|## Breaking Changes\|## Migration" README.md`

Note where the custom-node and summarize tools are mentioned.

### Step 2: Add a Breaking Changes section near the top of the README

- [ ] Find the line after the README's main description (typically near the top, after the title/badges/intro paragraph but before the install section). Search for a line like `## Installation` or `## Quick Start`.

Insert this block immediately before that section:

```markdown
## Recent Breaking Changes (2026-05)

**Parameter renames** — update keyword arguments (positional calls are unaffected):
- `comfyui_install_custom_node`, `comfyui_uninstall_custom_node`,
  `comfyui_update_custom_node`: `id` → `node_id`.
- `comfyui_summarize_workflow`: `format` → `output_format`, restricted to
  `text` or `mermaid` via a Pydantic `Literal`.

**Response-shape changes** — these tools now return the standard pagination envelope
`{items, total, offset, limit, has_more}` instead of bare lists or raw dicts:
- `comfyui_list_extensions` (was: `list[str]`)
- `comfyui_list_model_folders` (was: `list[str]`)
- `comfyui_list_workflows` (was: `dict[package_name, list[template]]`; now flattened
  to `items: [{package, templates}]`)

Callers must update to read `result["items"]` instead of indexing the response
directly. The new envelope also exposes `limit` and `offset` parameters for
pagination.
```

### Step 3: Commit

- [ ] ```bash
git add README.md
git commit -m "Document Task 6 and Task 7 parameter renames in README"
```

---

## Task 10: Final verification sweep

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v 2>&1 | tail -20`
Expected: ALL PASS, no skipped, no errors.

- [ ] **Step 2: Run the linter**

Run: `uv run ruff check src/ tests/`
Expected: no diagnostics.

- [ ] **Step 3: Run the formatter check**

Run: `uv run ruff format --check src/ tests/`
Expected: no diff.

- [ ] **Step 4: Run the type checker**

Run: `uv run mypy src/comfyui_mcp/`
Expected: 0 errors.

- [ ] **Step 5: Run pre-commit (only on tracked files we touched)**

Run: `uv run pre-commit run --files $(git diff --name-only main...HEAD | grep -v graphify-out)`
Expected: all hooks pass.

If unrelated files in the working tree get reformatted (preexisting drift like `tests/test_blocked_endpoints.py`), restore them with `git checkout -- <file>` and document the drift outside this PR.

- [ ] **Step 6: Verify tool surface unchanged in count**

Run: `grep -rn "@mcp.tool" src/comfyui_mcp/tools/ | wc -l`
Expected: same number as before this work began (this PR adds zero new tools — only modifies existing ones).

- [ ] **Step 7: Confirm no `# noqa: A002` markers remain in the touched tools**

Run: `grep -n "noqa: A002" src/comfyui_mcp/tools/`
Expected: no matches in `nodes.py` or `generation.py`. If any other file still has `# noqa: A002`, that's outside this plan's scope and can stay.

If any verification step fails, fix and amend the appropriate commit (or add a fixup commit) before declaring the plan complete.

---

## Out of scope (deliberately not in this plan)

- Audit Important #6 generic upload-tool Field annotation drift (`comfyui_upload_image`, `comfyui_upload_mask`). Touching these would interact with the security/sanitizer layer which was excluded from the audit; defer.
- Minor #10 unified return envelope for `wait=True` generation tools — larger refactor.
- Minor #14 `comfyui_search_models` redundant validation — cosmetic.
- Project observation A cursor-based pagination — none of the tools' datasets warrant it yet.
