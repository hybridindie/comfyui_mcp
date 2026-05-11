# Unified `wait=True` Return Envelope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop returning two different shapes from the same tool. Today, every workflow-submitting generation tool returns either a free-form sentence (when `wait=False`) or a JSON-serialized string (when `wait=True`/stream). Callers have to try both shapes. After this PR, all of them return a single uniform `dict[str, Any]` envelope regardless of mode.

**Architecture:** Refactor the shared `_submit_workflow` helper in `tools/generation.py` to build and return a `dict[str, Any]` instead of `json.dumps(...)`/free-form string. Update the six tools that call it (`comfyui_run_workflow`, `comfyui_run_workflow_stream`, `comfyui_generate_image`, `comfyui_transform_image`, `comfyui_inpaint_image`, `comfyui_upscale_image`) so their return annotations change from `-> str` to `-> dict[str, Any]`. Update the existing test assertions accordingly. This is a deliberate breaking change for MCP callers — flagged in commit messages and the README.

**Tech Stack:** Python 3.12, FastMCP, pytest with `asyncio_mode = auto`, respx, json.

---

## File Structure

**Modify:**
- `src/comfyui_mcp/tools/generation.py` — `_submit_workflow` body + 6 tool signatures.
- `tests/test_tools_generation.py` — assertions across many tests (substring checks → dict-key checks).
- `tests/test_integration.py` — 2 callsite assertions for `comfyui_generate_image` and `comfyui_run_workflow`.
- `README.md` — flag the breaking change in the Recent Breaking Changes section.

No new files.

---

## Unified envelope shape

The new return is always `dict[str, Any]`. Keys:

| key | type | when |
|---|---|---|
| `status` | str | always — one of `submitted`, `completed`, `interrupted`, `error`, `timeout`, `running` |
| `prompt_id` | str | always (or `"unknown"` if upstream didn't return one) |
| `warnings` | `list[str]` | only when the inspector produced warnings (omitted otherwise) |
| `outputs` | `list[dict]` | when `wait=True` and the run produced outputs (from `ProgressState`) |
| `elapsed_seconds` | float | when `wait=True` |
| `step` / `total_steps` / `current_node` / `queue_position` | int / int / str / int | from `ProgressState.to_dict()` when set |
| `events` | `list[dict]` | only `comfyui_run_workflow_stream` |

For `wait=False`, only `status="submitted"`, `prompt_id`, and (when applicable) `warnings` appear. No more human-readable sentence — callers consume structured fields.

---

## Task 1: Migrate `_submit_workflow` + 6 tool signatures + tests

**Files:**
- Modify: `src/comfyui_mcp/tools/generation.py:112-191` (`_submit_workflow`) and the 6 tool function return annotations
- Modify: `tests/test_tools_generation.py` (many sites — see steps)

This task is one large but cohesive unit. Splitting across commits would leave the codebase in an inconsistent state (some tools returning dict, some str). Do all changes in a single commit.

### Step 1: Update failing tests first (TDD red phase)

Open `tests/test_tools_generation.py`. The tests below currently assert against string returns; rewrite them to assert against dict returns.

Replace lines around 90-91 in `test_run_workflow_audit_mode_warning_passthrough` (the first `test_run_workflow` style test — class is `TestRunWorkflow`):

Find:
```python
        result = await tools["comfyui_run_workflow"](workflow=json.dumps(workflow))
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in result
```

Replace with:
```python
        result = await tools["comfyui_run_workflow"](workflow=json.dumps(workflow))
        assert result["status"] == "submitted"
        assert result["prompt_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
```

Around lines 106-108 (`test_audit_mode_logs_dangerous_nodes`):

Find:
```python
        result = await tools["comfyui_run_workflow"](workflow=json.dumps(workflow))
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in result
        assert "EvalNode" in result
```

Replace with:
```python
        result = await tools["comfyui_run_workflow"](workflow=json.dumps(workflow))
        assert result["status"] == "submitted"
        assert result["prompt_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        # Inspector warning about EvalNode is now in result["warnings"]:
        assert any("EvalNode" in w for w in result.get("warnings", []))
```

Around line 161-162 (`test_run_workflow_stream` style — `TestRunWorkflowStream` class):

Find:
```python
        result = await tools["comfyui_run_workflow_stream"](workflow=json.dumps(workflow))
        parsed = json.loads(result)
```

Replace with:
```python
        result = await tools["comfyui_run_workflow_stream"](workflow=json.dumps(workflow))
        parsed = result  # already a dict — no json.loads needed
```

(Keep the rest of that test's assertions unchanged — they use `parsed["..."]` which still works.)

Around line 183 (`test_generate_image_minimal`):

Find:
```python
        result = await tools["comfyui_generate_image"](prompt="a beautiful sunset over mountains")
        assert "img-001" in result
```

Replace with:
```python
        result = await tools["comfyui_generate_image"](prompt="a beautiful sunset over mountains")
        assert result["status"] == "submitted"
        assert result["prompt_id"] == "img-001"
```

Around lines 829-833 (`TestGenerateImageWait::test_wait_true_returns_structured_result`):

Find:
```python
        result = await tools["comfyui_generate_image"](prompt="a cat", wait=True)
        data = json.loads(result)
        assert data["prompt_id"] == "img-wait-1"
        assert data["status"] == "completed"
        assert len(data["outputs"]) == 1
```

Replace with:
```python
        result = await tools["comfyui_generate_image"](prompt="a cat", wait=True)
        # result is already a dict — no json.loads needed.
        assert result["prompt_id"] == "img-wait-1"
        assert result["status"] == "completed"
        assert len(result["outputs"]) == 1
```

Around lines 851-853 (`TestGenerateImageWait::test_wait_false_returns_prompt_id_string`):

The test name itself is now misleading — rename and rewrite. Find:
```python
    async def test_wait_false_returns_prompt_id_string(self, progress_components):
        ...
        result = await tools["comfyui_generate_image"](prompt="a dog", wait=False)
        assert "img-nowait" in result
        assert not result.startswith("{")
```

Replace with:
```python
    async def test_wait_false_returns_submitted_envelope(self, progress_components):
        ...
        result = await tools["comfyui_generate_image"](prompt="a dog", wait=False)
        assert result["status"] == "submitted"
        assert result["prompt_id"] == "img-nowait"
```

(Keep the `...` body inside the test unchanged — only the assertions and method name change.)

Then continue through `TestRunWorkflowWait` and any analogous tests for `transform_image`, `inpaint_image`, `upscale_image`. For each:

- Find any `assert "<prompt-id>" in result` substring check → replace with `assert result["prompt_id"] == "<prompt-id>"`.
- Find any `data = json.loads(result)` followed by `data["..."]` access → replace with `result["..."]` direct access (drop the `json.loads`).
- Find any substring check for a class_type/warning string (e.g. `assert "EvalNode" in result`) → replace with `assert any("EvalNode" in w for w in result.get("warnings", []))`.

Run: `grep -nE 'in result$|in result\)|in result\s|json\.loads\(result\)' tests/test_tools_generation.py` to find every remaining call site that needs updating.

### Step 2: Run the tests to confirm they all fail

Run: `uv run pytest tests/test_tools_generation.py -v 2>&1 | tail -30`
Expected: many FAILures with `TypeError` (object is not subscriptable on a str), `AssertionError` on prompt_id keys, etc.

### Step 3: Update `_submit_workflow` to return `dict[str, Any]`

In `src/comfyui_mcp/tools/generation.py`, replace the `_submit_workflow` function (around lines 112-191). The current return signature is `-> str`. The new signature is `-> dict[str, Any]`.

The current function ends with these return paths:
```python
        return json.dumps(result_dict)  # stream path (line ~176)
        ...
        return json.dumps(result_dict)  # wait path (line ~189)
        ...
        return f"{success_message} prompt_id: {prompt_id}{warning_msg}"  # wait=False path (line ~191)
```

Rewrite the function as follows. The key changes are at the bottom (the three return statements). Keep the inspector / model-checker / submission logic in place.

```python
async def _submit_workflow(
    *,
    wf: dict[str, Any],
    tool_name: str,
    success_message: str,
    wait: bool,
    client: ComfyUIClient,
    audit: AuditLogger,
    inspector: WorkflowInspector,
    progress: WebSocketProgress | None,
    stream_events: bool = False,
    model_checker: ModelChecker | None = None,
    inspect_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect, submit, and optionally wait for a workflow.

    Returns a unified envelope:

        {
            "status": "submitted" | "completed" | "interrupted" | "error" | "timeout",
            "prompt_id": "<uuid>",
            "warnings": [...]              # only when inspector produced warnings
            # The following appear only when wait=True or stream_events=True:
            "outputs": [...],
            "elapsed_seconds": float,
            "step" / "total_steps" / ...   # from ProgressState.to_dict() when set
            "events": [...]                # only stream_events=True
        }

    The ``success_message`` argument is preserved for the audit log but is no
    longer surfaced in the return value — callers consume structured fields.
    """
    inspection = inspector.inspect(wf)
    if model_checker is not None:
        model_warnings = await model_checker.check_models(wf, client)
        if model_warnings:
            inspection.warnings.extend(model_warnings)
            if inspector.mode == "enforce":
                raise WorkflowBlockedError(f"Workflow blocked — missing models: {model_warnings}")

    log_kwargs: dict[str, Any] = {
        "tool": tool_name,
        "action": "inspected",
        "nodes_used": inspection.nodes_used,
        "warnings": inspection.warnings,
    }
    if inspect_extra:
        log_kwargs["extra"] = inspect_extra
    if model_checker is not None:
        log_kwargs["status"] = "allowed"
    await audit.async_log(**log_kwargs)

    should_use_ws = wait or stream_events
    ws_client_id = progress.new_client_id() if should_use_ws and progress is not None else None
    response = await client.post_prompt(wf, client_id=ws_client_id)
    prompt_id = response.get("prompt_id", "unknown")
    await audit.async_log(
        tool=tool_name, action="submitted", prompt_id=prompt_id, extra={"success_message": success_message}
    )

    def _attach_warnings(envelope: dict[str, Any]) -> dict[str, Any]:
        if inspection.warnings:
            envelope["warnings"] = list(inspection.warnings)
        return envelope

    if stream_events:
        if progress is None:
            raise RuntimeError("Progress tracking is not configured")
        state, events = await progress.wait_for_completion_with_events(
            prompt_id,
            client_id=ws_client_id,
        )
        await audit.async_log(
            tool=tool_name,
            action="stream_completed",
            prompt_id=prompt_id,
            extra={"status": state.status, "elapsed": state.elapsed_seconds, "events": len(events)},
        )
        envelope = state.to_dict()
        envelope["events"] = events
        return _attach_warnings(envelope)

    if wait and progress is not None:
        state = await progress.wait_for_completion(prompt_id, client_id=ws_client_id)
        await audit.async_log(
            tool=tool_name,
            action="completed",
            prompt_id=prompt_id,
            extra={"status": state.status, "elapsed": state.elapsed_seconds},
        )
        envelope = state.to_dict()
        return _attach_warnings(envelope)

    return _attach_warnings({"status": "submitted", "prompt_id": prompt_id})
```

Note: the `success_message` parameter is now passed to the audit log's `extra` so we don't lose that information, but it no longer appears in the caller-facing return.

### Step 4: Update the six tool function signatures

Find each of these tool definitions in `src/comfyui_mcp/tools/generation.py` and change `-> str` to `-> dict[str, Any]`:

1. `comfyui_run_workflow` (around line 435):
   ```python
   async def comfyui_run_workflow(workflow: str, wait: bool = False) -> str:
   ```
   →
   ```python
   async def comfyui_run_workflow(workflow: str, wait: bool = False) -> dict[str, Any]:
   ```

2. `comfyui_run_workflow_stream` (around line 474):
   ```python
   async def comfyui_run_workflow_stream(workflow: str) -> str:
   ```
   →
   ```python
   async def comfyui_run_workflow_stream(workflow: str) -> dict[str, Any]:
   ```

3. `comfyui_generate_image` (around line 517 — `-> str` at the end of its multi-line signature):

   Find:
   ```python
       ) -> str:
   ```
   in the `comfyui_generate_image` definition (it's the closing of that long Annotated signature). Replace with:
   ```python
       ) -> dict[str, Any]:
   ```

4. `comfyui_transform_image` (around line 631) — same pattern.

5. `comfyui_inpaint_image` (around line 688) — same pattern.

6. `comfyui_upscale_image` (around line 750) — same pattern.

Each tool's body just returns `await _submit_workflow(...)` so no body changes are needed beyond the return type annotation.

### Step 5: Run the tests

Run: `uv run pytest tests/test_tools_generation.py -v 2>&1 | tail -20`
Expected: all PASS. If any fail, the failure is likely a test assertion that still uses substring style on a now-dict result — fix that test.

### Step 6: Run the rest of the test suite

Run: `uv run pytest -q 2>&1 | tail -5`
Expected: all PASS, except possibly tests in `test_integration.py` (handled in Task 2).

If `test_integration.py` fails, that's expected — we'll fix it in Task 2.

### Step 7: Lint + format + mypy

Run: `uv run ruff check src/comfyui_mcp/tools/generation.py tests/test_tools_generation.py && uv run ruff format --check src/comfyui_mcp/tools/generation.py tests/test_tools_generation.py && uv run mypy src/comfyui_mcp/`
Expected: clean.

### Step 8: Commit

```bash
git add src/comfyui_mcp/tools/generation.py tests/test_tools_generation.py
git commit -m "Unify wait=True/wait=False return envelopes (BREAKING)

All six workflow-submitting tools (run_workflow, run_workflow_stream,
generate_image, transform_image, inpaint_image, upscale_image)
previously returned two different shapes:

  wait=False: free-form sentence \"Workflow submitted. prompt_id: ...\"
  wait=True:  json.dumps() of a result dict
  stream:     json.dumps() of a result+events dict

This forced every caller to try both shapes and removed any benefit
from the FastMCP outputSchema auto-generation (which can't infer a
schema from a union return type).

After this commit, all six tools return dict[str, Any] regardless of
mode. The envelope is:

  {
    'status': 'submitted' | 'completed' | 'interrupted' | 'error'
              | 'timeout',
    'prompt_id': '<uuid>',
    'warnings': [...] (only if inspector produced warnings)
    # When wait=True or stream:
    'outputs': [...],
    'elapsed_seconds': float,
    'step' / 'total_steps' / 'current_node' / 'queue_position': ...,
    # When stream:
    'events': [...]
  }

The success_message string previously embedded in the wait=False
return is preserved in the audit log (action='submitted', extra) but
no longer appears in the caller-facing response.

BREAKING for MCP callers that read the return value as a string. JSON
callers that used json.loads() on wait=True results must now skip
that step. Test assertions in test_tools_generation.py updated in this
commit."
```

---

## Task 2: Update `test_integration.py`

**Files:**
- Modify: `tests/test_integration.py:127-128, 147-149`

The integration tests assert against the old string return shape for `comfyui_generate_image` and `comfyui_run_workflow`. Update them to match the new envelope.

### Step 1: Update `test_generate_image_lists_models_then_generates`

In `tests/test_integration.py` around lines 127-128:

Find:
```python
        # Step 2: Generate an image
        result = await integration_stack["comfyui_generate_image"](prompt="a sunset over mountains")
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in result
```

Replace with:
```python
        # Step 2: Generate an image
        result = await integration_stack["comfyui_generate_image"](prompt="a sunset over mountains")
        assert result["status"] == "submitted"
        assert result["prompt_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
```

### Step 2: Update `test_run_workflow_with_dangerous_node_in_audit_mode`

In the same file around lines 147-149:

Find:
```python
        workflow = json.dumps({"1": {"class_type": "Terminal", "inputs": {}}})
        result = await integration_stack["comfyui_run_workflow"](workflow=workflow)
        assert "11111111-2222-3333-4444-555555555555" in result
        assert "Terminal" in result
```

Replace with:
```python
        workflow = json.dumps({"1": {"class_type": "Terminal", "inputs": {}}})
        result = await integration_stack["comfyui_run_workflow"](workflow=workflow)
        assert result["status"] == "submitted"
        assert result["prompt_id"] == "11111111-2222-3333-4444-555555555555"
        # Inspector flagged 'Terminal' as a dangerous node — warning surfaces
        # in the envelope's warnings list.
        assert any("Terminal" in w for w in result.get("warnings", []))
```

### Step 3: Run the integration tests

Run: `uv run pytest tests/test_integration.py -v 2>&1 | tail -10`
Expected: all PASS.

### Step 4: Commit

```bash
git add tests/test_integration.py
git commit -m "Update integration tests for unified wait-envelope dict return"
```

---

## Task 3: Document the breaking change

**Files:**
- Modify: `README.md`

### Step 1: Find the existing "Recent Breaking Changes" section

Run: `grep -n "^## Recent Breaking Changes" README.md`

If the section exists from earlier PRs, append a new entry. If not, add the section near the top after the introductory paragraphs.

### Step 2: Add the entry

Locate the "Recent Breaking Changes (2026-05)" section. Append a new sub-bullet (or new dated subsection if appropriate):

```markdown
**Unified return envelope for workflow-submitting tools** (replaces the previous
str / json-string asymmetry):

- `comfyui_run_workflow`, `comfyui_run_workflow_stream`, `comfyui_generate_image`,
  `comfyui_transform_image`, `comfyui_inpaint_image`, `comfyui_upscale_image`
  now all return a uniform `dict[str, Any]` regardless of `wait`/`stream` mode.
- The envelope has `status` (one of `submitted` / `completed` / `interrupted`
  / `error` / `timeout`), `prompt_id`, optional `warnings`, plus `outputs` /
  `elapsed_seconds` / `step` / `total_steps` etc. when `wait=True`, and
  `events` when `stream`.
- Callers that previously parsed the return as a free-form string (for
  `wait=False`) or via `json.loads()` (for `wait=True`) must update to read
  fields directly off the dict.
```

### Step 3: Commit

```bash
git add README.md
git commit -m "Document unified wait-envelope breaking change in README"
```

---

## Task 4: Final verification sweep

### Step 1: Full test suite

Run: `uv run pytest -q 2>&1 | tail -5`
Expected: all pass; count should be `>= main's count` (no tests removed).

### Step 2: Lint and format

Run: `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`
Expected: clean.

### Step 3: Type checker

Run: `uv run mypy src/comfyui_mcp/`
Expected: no issues.

### Step 4: Pre-commit on the diff

Run: `uv run pre-commit run --files $(git diff --name-only main...HEAD)`
Expected: all hooks pass.

### Step 5: Spot-check that no `-> str` remains on workflow-submitting tools

Run: `grep -nE 'async def comfyui_(run_workflow|generate_image|transform_image|inpaint_image|upscale_image)' src/comfyui_mcp/tools/generation.py`
Expected output: every line ends with `-> dict[str, Any]:` or has the return annotation on a later line. Verify the multi-line signatures (e.g. `comfyui_generate_image`) end with `) -> dict[str, Any]:`.

Run: `grep -nE '^        \) -> str:' src/comfyui_mcp/tools/generation.py`
Expected: no matches.

### Step 6: Spot-check no leftover `json.dumps` in `_submit_workflow`

Run: `grep -n 'json.dumps' src/comfyui_mcp/tools/generation.py`
Expected: no matches in the `_submit_workflow` body. Other helper functions in this file (e.g., `_format_summary`) may legitimately use `json.dumps` for their own purposes — only flag a match inside `_submit_workflow`.

If any step fails, fix and amend the appropriate commit (or add a fixup commit) before declaring the plan complete.

---

## Out of scope

- **Backward-compatible shim that accepts a `return_format='legacy'` kwarg** — would clutter every tool's signature for a transient need. The breaking change is documented; callers must update.
- **Adding new fields to the envelope** beyond what `ProgressState.to_dict()` already provides (e.g., `submitted_at` timestamp). This task is a refactor, not a feature.
- **Updating `comfyui_summarize_workflow`** — that tool already returns `str` for a different reason (it's literally a human-readable summary) and isn't affected by this work.
