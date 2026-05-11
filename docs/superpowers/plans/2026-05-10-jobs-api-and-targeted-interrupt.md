# Unified Jobs API + Targeted Interrupt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire two upstream ComfyUI improvements into the MCP. (1) Use the unified `/api/jobs` and `/api/jobs/{job_id}` endpoints to fix the existing `comfyui_get_job` tool (which today only sees completed jobs because it calls `/history/{prompt_id}`) and add a new `comfyui_list_jobs` tool with status/sort/pagination. (2) Extend `POST /interrupt` and the `comfyui_interrupt` tool to accept an optional `prompt_id` so callers can target a specific running prompt instead of always doing a global interrupt.

**Architecture:** Three new client methods (`get_job`, `get_jobs`, an extended `interrupt`) follow the existing `client.py` patterns: validate input up front (UUID for IDs, allowlist for sort/status), call `self._request(...)`, parse JSON. Tool layer changes follow CLAUDE.md rules — every tool calls `limiter.check()` and `audit.async_log()` first, returns `dict[str, Any]` for structured responses, uses `Annotated[type, Field(...)]` for parameters with constraints. The response shape of `comfyui_get_job` changes (was `{prompt_id: {...}}`, now the bare job object) — this is a deliberate fix because the old shape was already broken for queued/running jobs.

**Tech Stack:** Python 3.12, httpx (async), respx (HTTP mocking), pytest with `asyncio_mode = auto`, FastMCP, Pydantic `Field`.

---

## File Structure

**Modify:**
- `src/comfyui_mcp/client.py` — add `get_job`, `get_jobs`; extend `interrupt`
- `src/comfyui_mcp/tools/jobs.py` — change `comfyui_get_job` body, add `comfyui_list_jobs`, extend `comfyui_interrupt`
- `tests/test_client.py` — tests for new client methods
- `tests/test_tools_jobs.py` — update `TestGetJob`, `TestInterrupt`; add `TestListJobs`
- `README.md` — tool table updates

No new files. The new tool fits in `tools/jobs.py` since it's a job-management read.

---

## Task 1: Client `get_job(job_id)` method

**Files:**
- Modify: `src/comfyui_mcp/client.py` (add method near line 167, after `get_history_item`)
- Test: `tests/test_client.py` (add to `TestComfyUIClient` class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_client.py` inside `class TestComfyUIClient:` (after `test_get_history` around line 56):

```python
    @respx.mock
    async def test_get_job_returns_job_object(self, client):
        job_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        respx.get(f"http://test-comfyui:8188/api/jobs/{job_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "prompt_id": job_id,
                    "status": "in_progress",
                    "outputs": {},
                },
            )
        )
        result = await client.get_job(job_id)
        assert result["prompt_id"] == job_id
        assert result["status"] == "in_progress"

    async def test_get_job_rejects_non_uuid(self, client):
        with pytest.raises(ValueError, match="Invalid prompt_id"):
            await client.get_job("not-a-uuid")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py::TestComfyUIClient::test_get_job_returns_job_object tests/test_client.py::TestComfyUIClient::test_get_job_rejects_non_uuid -v`
Expected: both FAIL with `AttributeError: 'ComfyUIClient' object has no attribute 'get_job'`

- [ ] **Step 3: Implement the method**

Add to `src/comfyui_mcp/client.py` immediately after `get_history_item` (around line 167):

```python
    async def get_job(self, job_id: str) -> dict:
        """GET /api/jobs/{job_id} — unified job lookup across queue + history."""
        _validate_prompt_id(job_id)
        r = await self._request("get", f"/api/jobs/{job_id}")
        return r.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py::TestComfyUIClient::test_get_job_returns_job_object tests/test_client.py::TestComfyUIClient::test_get_job_rejects_non_uuid -v`
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add src/comfyui_mcp/client.py tests/test_client.py
git commit -m "Add ComfyUIClient.get_job for /api/jobs/{job_id}"
```

---

## Task 2: Client `get_jobs(...)` method

**Files:**
- Modify: `src/comfyui_mcp/client.py` (add method right after `get_job`)
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client.py` inside `class TestComfyUIClient:`:

```python
    @respx.mock
    async def test_get_jobs_no_params(self, client):
        respx.get("http://test-comfyui:8188/api/jobs").mock(
            return_value=httpx.Response(
                200,
                json={"jobs": [], "pagination": {"offset": 0, "limit": None, "total": 0, "has_more": False}},
            )
        )
        result = await client.get_jobs()
        assert "jobs" in result
        assert "pagination" in result

    @respx.mock
    async def test_get_jobs_passes_filters(self, client):
        route = respx.get("http://test-comfyui:8188/api/jobs").mock(
            return_value=httpx.Response(
                200, json={"jobs": [], "pagination": {"offset": 5, "limit": 10, "total": 0, "has_more": False}}
            )
        )
        await client.get_jobs(
            status=["pending", "in_progress"],
            workflow_id="wf-123",
            sort_by="execution_duration",
            sort_order="asc",
            limit=10,
            offset=5,
        )
        request = route.calls.last.request
        params = dict(request.url.params.multi_items())
        assert params["status"] == "pending,in_progress"
        assert params["workflow_id"] == "wf-123"
        assert params["sort_by"] == "execution_duration"
        assert params["sort_order"] == "asc"
        assert params["limit"] == "10"
        assert params["offset"] == "5"

    async def test_get_jobs_rejects_invalid_status(self, client):
        with pytest.raises(ValueError, match="Invalid status"):
            await client.get_jobs(status=["bogus"])

    async def test_get_jobs_rejects_invalid_sort_by(self, client):
        with pytest.raises(ValueError, match="sort_by"):
            await client.get_jobs(sort_by="random")

    async def test_get_jobs_rejects_invalid_sort_order(self, client):
        with pytest.raises(ValueError, match="sort_order"):
            await client.get_jobs(sort_order="sideways")

    async def test_get_jobs_rejects_negative_limit(self, client):
        with pytest.raises(ValueError, match="limit"):
            await client.get_jobs(limit=0)

    async def test_get_jobs_rejects_negative_offset(self, client):
        with pytest.raises(ValueError, match="offset"):
            await client.get_jobs(offset=-1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v -k "get_jobs"`
Expected: all FAIL with `AttributeError: ... 'get_jobs'`

- [ ] **Step 3: Add validation constants and the method**

Edit `src/comfyui_mcp/client.py`. Add module-level constants near the top (after `_SAFE_SEGMENT_RE` around line 18):

```python
_VALID_JOB_STATUSES = frozenset({"pending", "in_progress", "completed", "failed"})
_VALID_JOB_SORT_BY = frozenset({"created_at", "execution_duration"})
_VALID_JOB_SORT_ORDER = frozenset({"asc", "desc"})
```

Add the method to `ComfyUIClient` immediately after `get_job`:

```python
    async def get_jobs(
        self,
        *,
        status: list[str] | None = None,
        workflow_id: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        """GET /api/jobs — unified, paginated, filterable job list."""
        if status is not None:
            invalid = [s for s in status if s not in _VALID_JOB_STATUSES]
            if invalid:
                raise ValueError(
                    f"Invalid status value(s): {invalid}. "
                    f"Valid: {sorted(_VALID_JOB_STATUSES)}"
                )
        if sort_by not in _VALID_JOB_SORT_BY:
            raise ValueError(
                f"sort_by must be one of {sorted(_VALID_JOB_SORT_BY)}, got {sort_by!r}"
            )
        if sort_order not in _VALID_JOB_SORT_ORDER:
            raise ValueError(
                f"sort_order must be one of {sorted(_VALID_JOB_SORT_ORDER)}, got {sort_order!r}"
            )
        if limit is not None and limit <= 0:
            raise ValueError("limit must be a positive integer")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        params: dict[str, str] = {
            "sort_by": sort_by,
            "sort_order": sort_order,
            "offset": str(offset),
        }
        if status:
            params["status"] = ",".join(status)
        if workflow_id:
            params["workflow_id"] = workflow_id
        if limit is not None:
            params["limit"] = str(limit)

        r = await self._request("get", "/api/jobs", params=params)
        return r.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v -k "get_jobs"`
Expected: all 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/comfyui_mcp/client.py tests/test_client.py
git commit -m "Add ComfyUIClient.get_jobs for paginated /api/jobs"
```

---

## Task 3: Extend `ComfyUIClient.interrupt` to accept optional `prompt_id`

**Files:**
- Modify: `src/comfyui_mcp/client.py:169-170` (the `interrupt` method)
- Test: `tests/test_client.py` (add to `TestComfyUIClient`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client.py` inside `class TestComfyUIClient:`:

```python
    @respx.mock
    async def test_interrupt_with_prompt_id_sends_body(self, client):
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        route = respx.post("http://test-comfyui:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.interrupt(prompt_id=prompt_id)
        request = route.calls.last.request
        body = json.loads(request.content)
        assert body == {"prompt_id": prompt_id}

    @respx.mock
    async def test_interrupt_without_prompt_id_sends_no_body(self, client):
        route = respx.post("http://test-comfyui:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.interrupt()
        request = route.calls.last.request
        # Either no body or empty body — definitely no prompt_id
        assert request.content in (b"", b"{}", None)

    async def test_interrupt_rejects_non_uuid_prompt_id(self, client):
        with pytest.raises(ValueError, match="Invalid prompt_id"):
            await client.interrupt(prompt_id="not-a-uuid")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v -k "interrupt"`
Expected: 2 new tests FAIL (`test_interrupt_with_prompt_id_sends_body`, `test_interrupt_rejects_non_uuid_prompt_id`); existing `test_interrupt` and the new `test_interrupt_without_prompt_id_sends_no_body` PASS.

- [ ] **Step 3: Update the method**

In `src/comfyui_mcp/client.py`, replace the existing `interrupt` method:

```python
    async def interrupt(self, prompt_id: str | None = None) -> None:
        """POST /interrupt — global interrupt, or targeted if prompt_id is given.

        Without prompt_id, interrupts whatever is currently executing.
        With prompt_id, ComfyUI only interrupts if that prompt is the running one;
        otherwise the call is a no-op (server returns 200 either way).
        """
        if prompt_id is not None:
            _validate_prompt_id(prompt_id)
            await self._request("post", "/interrupt", json={"prompt_id": prompt_id})
        else:
            await self._request("post", "/interrupt")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v -k "interrupt"`
Expected: all 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/comfyui_mcp/client.py tests/test_client.py
git commit -m "Allow targeted interrupt via optional prompt_id"
```

---

## Task 4: Migrate `comfyui_get_job` tool to `/api/jobs/{job_id}`

This task **changes the response shape** of `comfyui_get_job`. The old shape was `{prompt_id: {<execution_data>}}` (envelope keyed by prompt_id, returning empty `{}` for queued/running). The new shape is the bare job object including queued/running jobs. The existing tool was effectively broken for non-history jobs, so this is a fix.

**Files:**
- Modify: `src/comfyui_mcp/tools/jobs.py:53-60`
- Test: `tests/test_tools_jobs.py:70-83` (the `TestGetJob` class)

- [ ] **Step 1: Update the failing test to the new shape**

Replace `class TestGetJob` in `tests/test_tools_jobs.py` (lines 70-83) with:

```python
class TestGetJob:
    @respx.mock
    async def test_get_job_returns_unified_job_object(self, components):
        client, audit, limiter = components
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "prompt_id": prompt_id,
                    "status": "in_progress",
                    "outputs": {},
                },
            )
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_job"](prompt_id=prompt_id)
        assert result["prompt_id"] == prompt_id
        assert result["status"] == "in_progress"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_tools_jobs.py::TestGetJob -v`
Expected: FAIL — the tool currently calls `/history/{prompt_id}`, not `/api/jobs/{prompt_id}`, so the respx mock isn't matched and the call 404s (or hits an unmocked URL).

- [ ] **Step 3: Update the tool**

In `src/comfyui_mcp/tools/jobs.py`, replace the body of `comfyui_get_job` (around line 53-58):

```python
    async def comfyui_get_job(prompt_id: str) -> dict[str, Any]:
        """Look up a single job by prompt_id across queue + history.

        Returns the unified job object: status (pending/in_progress/completed/failed),
        timing, outputs, etc. Use this to check on a job that may be queued, running,
        or already finished.
        """
        rl = read_limiter if read_limiter is not None else limiter
        rl.check("get_job")
        await audit.async_log(tool="get_job", action="called", extra={"prompt_id": prompt_id})
        return await client.get_job(prompt_id)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_tools_jobs.py::TestGetJob -v`
Expected: PASS

- [ ] **Step 5: Run the full jobs test file to catch regressions**

Run: `uv run pytest tests/test_tools_jobs.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/tools/jobs.py tests/test_tools_jobs.py
git commit -m "Migrate comfyui_get_job to unified /api/jobs/{job_id}"
```

---

## Task 5: Add `comfyui_list_jobs` tool

**Files:**
- Modify: `src/comfyui_mcp/tools/jobs.py` (add tool, register in `tool_fns`)
- Test: `tests/test_tools_jobs.py` (new `TestListJobs` class)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools_jobs.py` after the existing `TestGetJob` class:

```python
class TestListJobs:
    @respx.mock
    async def test_list_jobs_default(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/api/jobs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [{"prompt_id": "abc", "status": "completed"}],
                    "pagination": {"offset": 0, "limit": None, "total": 1, "has_more": False},
                },
            )
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_list_jobs"]()
        assert "jobs" in result
        assert "pagination" in result
        assert result["jobs"][0]["status"] == "completed"

    @respx.mock
    async def test_list_jobs_passes_filters(self, components):
        client, audit, limiter = components
        route = respx.get("http://test:8188/api/jobs").mock(
            return_value=httpx.Response(
                200,
                json={"jobs": [], "pagination": {"offset": 0, "limit": 5, "total": 0, "has_more": False}},
            )
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        await tools["comfyui_list_jobs"](
            status=["pending", "in_progress"],
            sort_by="execution_duration",
            sort_order="asc",
            limit=5,
            offset=0,
        )
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["status"] == "pending,in_progress"
        assert params["sort_by"] == "execution_duration"
        assert params["sort_order"] == "asc"
        assert params["limit"] == "5"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_jobs.py::TestListJobs -v`
Expected: FAIL with `KeyError: 'comfyui_list_jobs'`

- [ ] **Step 3: Add the tool**

In `src/comfyui_mcp/tools/jobs.py`:

(a) Update imports at the top of the file (after the existing imports):

```python
from typing import Annotated, Any, Literal

from pydantic import Field
```

Note: `Any` is already imported; replace the existing `from typing import Any` line with `from typing import Annotated, Any, Literal`.

(b) Insert the new tool inside `register_job_tools`, immediately after `comfyui_get_job` is registered (after the line `tool_fns["comfyui_get_job"] = comfyui_get_job`):

```python
    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_list_jobs(
        status: Annotated[
            list[Literal["pending", "in_progress", "completed", "failed"]] | None,
            Field(
                default=None,
                description="Filter by job status (any combination).",
            ),
        ] = None,
        workflow_id: Annotated[
            str | None,
            Field(default=None, description="Filter by workflow ID set in extra_data."),
        ] = None,
        sort_by: Annotated[
            Literal["created_at", "execution_duration"],
            Field(default="created_at", description="Sort field."),
        ] = "created_at",
        sort_order: Annotated[
            Literal["asc", "desc"],
            Field(default="desc", description="Sort direction."),
        ] = "desc",
        limit: Annotated[
            int | None,
            Field(default=None, ge=1, le=1000, description="Max jobs to return."),
        ] = None,
        offset: Annotated[
            int,
            Field(default=0, ge=0, description="Jobs to skip for pagination."),
        ] = 0,
    ) -> dict[str, Any]:
        """List jobs across queue and history with filtering, sorting, and pagination.

        Returns {"jobs": [...], "pagination": {"offset", "limit", "total", "has_more"}}.
        Each job includes prompt_id, status (pending/in_progress/completed/failed),
        timing, and outputs (when completed).
        """
        rl = read_limiter if read_limiter is not None else limiter
        rl.check("list_jobs")
        await audit.async_log(
            tool="list_jobs",
            action="called",
            extra={
                "status": status,
                "workflow_id": workflow_id,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "limit": limit,
                "offset": offset,
            },
        )
        return await client.get_jobs(
            status=status,
            workflow_id=workflow_id,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    tool_fns["comfyui_list_jobs"] = comfyui_list_jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_jobs.py::TestListJobs -v`
Expected: both PASS

- [ ] **Step 5: Verify security invariants still hold**

Run: `uv run pytest tests/test_security_invariants.py -v`
Expected: PASS — `comfyui_list_jobs` closure captures `audit`, `limiter`/`read_limiter`, `client`, satisfying rate-limit and audit invariants.

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/tools/jobs.py tests/test_tools_jobs.py
git commit -m "Add comfyui_list_jobs tool for paginated unified job listing"
```

---

## Task 6: Extend `comfyui_interrupt` tool with optional `prompt_id`

**Files:**
- Modify: `src/comfyui_mcp/tools/jobs.py:87-92`
- Test: `tests/test_tools_jobs.py:57-67` (`TestInterrupt`)

- [ ] **Step 1: Write the failing tests**

Replace `class TestInterrupt` in `tests/test_tools_jobs.py` (lines 57-67) with:

```python
class TestInterrupt:
    @respx.mock
    async def test_interrupt_global(self, components):
        client, audit, limiter = components
        route = respx.post("http://test:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_interrupt"]()
        assert route.called
        body = route.calls.last.request.content
        # No prompt_id sent → no body, or empty
        assert body in (b"", b"{}", None)
        assert "current" in result.lower() or "global" in result.lower()

    @respx.mock
    async def test_interrupt_targeted(self, components):
        import json as _json
        client, audit, limiter = components
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        route = respx.post("http://test:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_interrupt"](prompt_id=prompt_id)
        assert route.called
        body = _json.loads(route.calls.last.request.content)
        assert body == {"prompt_id": prompt_id}
        assert prompt_id in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_jobs.py::TestInterrupt -v`
Expected: `test_interrupt_targeted` FAILS (`comfyui_interrupt` doesn't accept `prompt_id`); `test_interrupt_global` may pass or fail depending on the assertion change.

- [ ] **Step 3: Update the tool**

Replace `comfyui_interrupt` in `src/comfyui_mcp/tools/jobs.py` (around lines 79-94):

```python
    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_interrupt(prompt_id: str | None = None) -> str:
        """Interrupt the currently executing workflow.

        Without prompt_id: global interrupt — stops whatever is running now.
        With prompt_id: targeted — only interrupts if that prompt is the
        running one. ComfyUI silently no-ops if prompt_id is queued but
        not yet running.
        """
        limiter.check("interrupt")
        await audit.async_log(
            tool="interrupt", action="called", extra={"prompt_id": prompt_id}
        )
        await client.interrupt(prompt_id=prompt_id)
        if prompt_id is None:
            return "Interrupted current execution (global)"
        return f"Requested interrupt for prompt {prompt_id} (no-op if not running)"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_jobs.py::TestInterrupt -v`
Expected: both PASS

- [ ] **Step 5: Run the full jobs test file**

Run: `uv run pytest tests/test_tools_jobs.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/tools/jobs.py tests/test_tools_jobs.py
git commit -m "Allow targeted interrupt via optional prompt_id in comfyui_interrupt"
```

---

## Task 7: README updates

**Files:**
- Modify: `README.md:227-237` (Job Management table)

- [ ] **Step 1: Update the Job Management table**

In `README.md`, replace lines 232 and 234 and insert a new row for `comfyui_list_jobs`:

Before:
```markdown
| `comfyui_get_queue` | Get current execution queue state. |
| `comfyui_get_job` | Check status of a job by prompt_id. |
| `comfyui_cancel_job` | Cancel a running or queued job. |
| `comfyui_interrupt` | Interrupt the currently executing workflow. |
```

After:
```markdown
| `comfyui_get_queue` | Get current execution queue state. |
| `comfyui_list_jobs` | List jobs across queue + history with status filter, sorting, and pagination. |
| `comfyui_get_job` | Look up a single job (queued/running/finished) by prompt_id. |
| `comfyui_cancel_job` | Cancel a running or queued job. |
| `comfyui_interrupt` | Interrupt the running workflow (global, or targeted via optional prompt_id). |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document comfyui_list_jobs and targeted interrupt"
```

---

## Task 8: Final verification sweep

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS (no skipped, no errors).

- [ ] **Step 2: Run the linter**

Run: `uv run ruff check src/ tests/`
Expected: no diagnostics.

- [ ] **Step 3: Run the formatter check**

Run: `uv run ruff format --check src/ tests/`
Expected: no diff. If it fails, run `uv run ruff format src/ tests/` and amend the relevant commit (or add a follow-up format commit).

- [ ] **Step 4: Run the type checker**

Run: `uv run mypy src/comfyui_mcp/`
Expected: 0 errors.

- [ ] **Step 5: Run pre-commit hooks**

Run: `uv run pre-commit run --all-files`
Expected: all hooks pass.

If any of the above fail, fix and amend the appropriate commit (or add a fixup commit) before declaring the plan complete.

---

## Out of scope (deliberately not in this plan)

- `/history?offset=N` pagination — separate, smaller change.
- `/view?preview=...` server-side thumbnails — separate plan; affects `tools/files.py`.
- `/upload/image` `type` and `overwrite` params — separate; raises security surface.
- Surfacing new `object_info` fields (`deprecated`, `experimental`, etc.) in `list_nodes` — separate.
- `partial_execution_targets` on `POST /prompt` — niche, separate.
