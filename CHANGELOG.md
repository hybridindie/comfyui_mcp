# Changelog

All notable changes to **comfyui-mcp-secure** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] — 2026-05-11

Major release. Adopts ComfyUI's unified `/api/jobs` job-tracking endpoints, harmonizes
return shapes across workflow-submitting tools, and tightens parameter naming. The
**breaking** entries below require call-site updates for MCP clients that consumed
this server's tools as strings or that passed the renamed parameters by keyword.

### Added

- **`comfyui_list_jobs`** — paginated cross-cut view of running, queued, and historical
  jobs, with filtering by `status` / `workflow_id` and sorting. Backed by ComfyUI's
  unified `/api/jobs` endpoint (#69).
- **Targeted interrupt** — `comfyui_interrupt` now accepts an optional `prompt_id`
  so callers can interrupt a specific running prompt instead of always doing a
  global interrupt (#69). Closes a multi-user safety footgun.
- **`comfyui_get_image` thumbnail support** — new `preview_format` (`webp` /
  `jpeg`) and `preview_quality` (1-100) parameters request server-side re-encoded
  thumbnails via `/view?preview=…;…`. Returning a 90 KB webp instead of a multi-MB
  PNG is a real bandwidth/context-window win for LLM clients (#72).
- **Upload destination controls** — `comfyui_upload_image` and `comfyui_upload_mask`
  gain `destination` (`Literal["input", "output", "temp"]`, default `input`) and
  `overwrite` (bool, default `False`) parameters. Restricted via `Literal` and
  validated again at the client layer for defense-in-depth (#72, #74).
- **`client.get_history` offset kwarg** — server-side `/history?offset=N` paging
  via the client API (the tool layer adopted it in 2.0.0 too, see _Changed_) (#72).
- **Phase 4 evaluation suite** — 10 static-only questions exercising the MCP's
  built-in templates, prompting guides, model presets, and validator/summarizer
  behavior. Reproducible by anyone with the MCP server running (#75).
- **Ollama eval runner** — `scripts/run_eval_ollama.py` mirrors the upstream
  Anthropic eval harness but targets Ollama (including `*-cloud` models). Adds a
  one-shot prompt-format nudge and a last-line fallback extractor to handle OSS
  models that don't reliably emit `<response>` XML tags (#75).
- **`LimitField` / `OffsetField` type aliases** — shared `Annotated[int, Field(...)]`
  aliases in `pagination.py` so list tools advertise pagination constraints in
  their JSON schema (#70).

### Changed

- **Unified wait-envelope** *(breaking)* — `comfyui_run_workflow`,
  `comfyui_run_workflow_stream`, `comfyui_generate_image`, `comfyui_transform_image`,
  `comfyui_inpaint_image`, and `comfyui_upscale_image` now all return a uniform
  `dict[str, Any]` regardless of `wait`/`stream` mode. The envelope has `status`
  (one of `submitted` / `completed` / `interrupted` / `error` / `timeout`),
  `prompt_id`, optional `warnings`, plus `outputs` / `elapsed_seconds` / `step` /
  `total_steps` etc. when `wait=True`, and `events` when streaming. Callers that
  parsed the return as a string (`wait=False` legacy path) or via `json.loads()`
  (`wait=True` legacy path) must update to read fields directly off the dict (#79).
- **`comfyui_get_job` response shape** *(breaking)* — was the legacy `/history`
  envelope `{prompt_id: {…}}`; now returns the flat unified job object from
  `/api/jobs/{id}`, including queued and running jobs (which the old endpoint
  couldn't see). Callers must read fields directly off the returned dict (#69).
- **List-tool response shapes** *(breaking)* — `comfyui_list_extensions`,
  `comfyui_list_model_folders`, and `comfyui_list_workflows` now return the
  standard pagination envelope `{items, total, offset, limit, has_more}` instead
  of bare lists or raw dicts. `comfyui_list_workflows` additionally flattens the
  upstream `dict[package, list[template]]` into `items: [{package, templates}]`.
  Callers must read `result["items"]` rather than indexing the response directly
  (#70).
- **`comfyui_get_history` envelope** *(breaking)* — now uses server-side
  `/history?offset=N` paging instead of fetching up to 1000 entries and slicing
  client-side. Envelope adds `count` (items in this page) and `total: int | None`
  (set only when the true count is provable: `offset + count` on the last page,
  `0` for an empty history at `offset=0`, `None` when paging is active or has
  paged past the end). The previous 1000-entry ceiling is gone (#78). Callers
  must handle `total: None`; use `has_more` as the canonical end-of-history signal.
- **`id` → `node_id` parameter rename** *(breaking)* — `comfyui_install_custom_node`,
  `comfyui_uninstall_custom_node`, and `comfyui_update_custom_node` now accept
  `node_id` instead of `id`. Drops the `# noqa: A002` builtin-shadow markers and
  adds `Field` constraints (`min_length=1, max_length=200`). The wire-level field
  sent to the ComfyUI Manager API is unchanged. MCP callers passing `id=` as a
  keyword must update; positional calls are unaffected (#70).
- **`format` → `output_format` parameter rename** *(breaking)* — `comfyui_summarize_workflow`
  now accepts `output_format` instead of `format`, with values restricted to
  `text` or `mermaid` via a Pydantic `Literal`. MCP callers passing `format=`
  as a keyword must update (#70).
- **`comfyui_get_progress` now sources job data from `/api/jobs/{id}`** instead of
  `/history/{prompt_id}` + `/queue`, matching `comfyui_get_job`. Adds a status
  mapping (`pending` → `queued`, `in_progress` → `running`, `completed` →
  `completed`, `failed` → `error`, `cancelled` → `interrupted`). The pre-flight
  check in the WebSocket-wait path also uses the unified endpoint now. `cancelled`
  → `interrupted` was previously unreachable via the legacy code path (#76).
- **`preflight_history` event renamed to `preflight_terminal`** *(minor breaking
  for stream consumers)* — the marker event in `comfyui_run_workflow_stream`'s
  output that signals "the job was already terminal before the WebSocket attached"
  used the old endpoint name. Renamed to describe what was detected (#80).
- **`get_history` internal cap bump 100 → 1000** — pagination's `total` now
  reflects the actual ceiling. Earlier version capped at 100 silently and
  reported the cap as the total (#70).
- **`limit` parameter constraints surfaced in JSON schema** — list tools now
  advertise `ge=1, le=100` via `Annotated[..., Field(...)]`, satisfying
  CLAUDE.md rule 13 (3+ params should use Field) (#70, #74).
- **Defense-in-depth on `destination` enum** — `comfyui_upload_image` /
  `comfyui_upload_mask` validate `destination` at both the FastMCP/Pydantic
  boundary and the client layer's runtime check (#72, #74).
- **Pre-commit `ruff` pinned to `v0.15.12`** (was `v0.8.6`) — aligns with the
  ruff version that `uv sync` installs in the venv, eliminating spurious
  reformat diffs (#71).

### Fixed

- **`analyze_workflow` crash on `txt2vid_*` templates** — the analyzer's
  `display_name` fallback only kicked in when the upstream `object_info` key was
  *absent*, not when it was explicitly `None`. ComfyUI returns
  `{"display_name": None}` for some nodes (e.g. `SaveAnimatedWEBP`), which
  propagated into the flow list and crashed `' -> '.join(flow_parts)` with
  `sequence item N: expected str instance, NoneType found`. Now falls back to
  `class_type` for any falsy `display_name`. Surfaced by the Phase 4 eval
  drafting work (#75).
- **`comfyui_get_history` pagination total bug** — silently capped at 100 and
  reported that cap as `total`, hiding the existence of older entries (#70).
- **`comfyui_validate_workflow` docstring** lied about return shape (claimed
  JSON string; actually returns a dict) (#70).
- **`_VALID_JOB_STATUSES` allowlist missing `cancelled`** — callers passing
  `status=["cancelled"]` to `client.get_jobs` or `comfyui_list_jobs` hit a
  spurious client-side `ValueError` even though ComfyUI's `JobStatus.ALL`
  includes `cancelled`. Now in sync with upstream (#77).
- **`_submit_workflow` missing `prompt_id` no longer silently fabricated** —
  an empty/missing/non-string `prompt_id` in the upstream response now raises
  `RuntimeError` and audit-logs the response payload, rather than returning a
  successful-looking envelope with `prompt_id="unknown"` (#79).
- **`wait=True` with `progress=None` now fails fast** — previously the wait
  branch was silently skipped, returning a `submitted` envelope and breaking the
  `wait` contract. Matches the existing `stream_events` check (#79).
- **HTTP-polling fallback's terminal-status set** — `_poll_until_complete` only
  broke on `completed`/`error`. A cancelled job during WS-fallback polling would
  loop until timeout and surface as `status='timeout'` instead of `'interrupted'`.
  Now includes `interrupted` in the terminal set (#76).
- **PR review-comment fixes** along the way — `tmp_path: Any` → `tmp_path: Path`
  in `test_security_invariants.py`'s `all_tools` fixture; `httpx.AsyncClient`
  cleanup in the same fixture; misnamed `test_get_jobs_rejects_negative_limit`
  that actually tested `limit=0`; `_validate_node_id` error messages aligned
  with the renamed parameter (#71, #77).

### Removed

- **`ComfyUIClient.get_history_item`** — dead code after `comfyui_get_progress`
  was migrated to `/api/jobs/{id}` in #76. No production callers remained (#76).
- **`_format_warnings` helper** — was used to build the human-readable warning
  blurb appended to the old `wait=False` string return. With the unified dict
  envelope, warnings live in `result["warnings"]` directly (#79).

### Security

- No security-impact changes beyond the defense-in-depth `destination` enum
  validation listed under *Changed* above.

### Internal

- New `evals/` directory with the Phase 4 evaluation file and Ollama-runner
  reports (gpt-oss-120b baseline: 40% raw, 80% with one-shot prompt-format
  nudge + last-line fallback extractor).
- Plan archive at `docs/superpowers/plans/` for the major refactor PRs.

## [1.0.1] — 2025

Initial public release on PyPI. See git history prior to v2.0.0 for changes.
