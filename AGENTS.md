# AGENTS.md

Entry point for OpenCode and other agentic clients working in **comfyui_mcp**.

## Independent & harness-agnostic

comfyui_mcp is a **standalone MCP server** — a secure Model Context Protocol
server for [ComfyUI](https://github.com/comfyanonymous/ComfyUI). It is usable by
**any** AI agent harness (OpenCode, or any MCP client over stdio or Streamable
HTTP) and exposes ComfyUI's workflow / generation / discovery / security API.

It has **no dependency on any specific consumer.** The server is the product;
the `/comfy:*` skills shipped in this repo are convenience recipes that wrap
multi-tool flows — they are not coupled to any one harness.

The constitutional rules themselves live in [`.opencode/rules/`](./.opencode/rules/),
loaded as `instructions` in [`opencode.json`](./.opencode/opencode.json), and
are the source of truth for how to build here:

- `security.md` — blocked endpoints, PathSanitizer, rate limiter, audit log,
  workflow inspector (the non-negotiable security invariants)
- `architecture.md` — layout, `_build_server()`, tool registration contract,
  Model Manager envelope, dangerous-nodes list maintenance
- `tools.md` — the `@mcp.tool()` contract and the new-tool checklist
- `testing.md` — `respx` mocks, `asyncio_mode = auto`, real tool functions
- `workflow.md` — issue → red test → green → preflight → PR → merge pipeline
  + the eval-gated change rule (Phase 4 before merge)
- `enforcement.md` — gates, PR checklist, lint/format/type, release & versioning
- `graphify.md` — graphify LLM-extraction policy: always run graphify via
  `scripts/graphify.sh` so the repo `.env` is observed

These rules are path-scoped; apply the one(s) matching the files you touch.
When a rule and this file disagree, the rule wins.

## Project Overview

A secure MCP (Model Context Protocol) server for ComfyUI, built on
**FastMCP 4**. Enables AI assistants to generate images, run workflows, and
manage jobs through ComfyUI with built-in security controls:
- Workflow Inspector (detects dangerous nodes like `eval`, `exec`) with
  **user elicitation** — enforce mode asks the user to confirm before
  submitting a flagged workflow
- Path Sanitizer (blocks path traversal attacks)
- **SecurityMiddleware** — centralized rate limiting + entry audit logging
  (FastMCP 4 `on_call_tool` hook) across every tool call
- Audit Logger (structured JSON logging with redaction)
- Selective API surface (blocks dangerous endpoints)
- **Resources** — read-only ComfyUI state the LLM can browse by URI
  (`comfyui://models/{folder}`, `comfyui://nodes/installed`, `comfyui://queue`,
  `comfyui://system`)
- **Prompts** — reusable workflow-template recipes (txt2img, img2img,
  inpaint, upscale)
- **Dependency injection** — `Depends()` providers for the
  `client`/`audit`/`inspector`/`limiter` singletons (opt-in per tool module;
  the `register_*_tools()` factory remains valid)
- **Background tasks** (optional) — `TasksExtension` (Docket-backed) for
  long-running workflows over the HTTP transport

## Tech Stack

- **Python**: 3.12
- **Package Manager**: uv
- **MCP Framework**: fastmcp[tasks] 4.0.0b1 (standalone FastMCP 4 beta,
  built on MCP SDK v2)
- **HTTP Client**: httpx (async)
- **Validation**: pydantic
- **Config**: pyyaml

## Project Structure

```
src/comfyui_mcp/
├── server.py              # MCP server entry, wires all components + middleware
├── config.py              # Pydantic settings, YAML loading, env overrides
├── client.py              # Async HTTP client for ComfyUI API
├── audit.py               # Structured JSON audit logger
├── middleware.py          # SecurityMiddleware (rate limit + entry audit, on_call_tool)
├── dependencies.py        # Depends() providers (client/audit/inspector/limiter singletons)
├── resources.py           # @mcp.resource URIs (models, nodes, queue, system)
├── prompts.py             # @mcp.prompt workflow-template recipes
├── model_manager.py       # Lazy Model Manager detection and folder caching
├── model_registry.py      # Canonical model loader field registry
├── node_manager.py        # ComfyUI Manager detector
├── progress.py            # WebSocket progress tracking with HTTP polling fallback
├── pagination.py          # Offset-based pagination helper for list tools
├── security/
│   ├── inspector.py       # Workflow node inspection (audit/enforce)
│   ├── node_auditor.py    # Scans installed nodes for dangerous patterns
│   ├── sanitizer.py       # File path validation
│   ├── rate_limit.py      # Token-bucket rate limiter
│   ├── download_validator.py  # URL domain/path and extension validation
│   └── model_checker.py   # Proactive model availability checking
├── workflow/
│   ├── templates.py       # Built-in workflow templates (txt2img, img2img, etc.)
│   ├── operations.py      # Workflow graph operations (add/remove nodes, connect)
│   └── validation.py      # Workflow analysis and validation
└── tools/
    ├── generation.py      # generate_image, run_workflow, summarize_workflow (elicitation-gated)
    ├── workflow.py        # create_workflow, modify_workflow, validate_workflow
    ├── jobs.py            # get_queue, get_job, cancel_job, interrupt, get_progress
    ├── discovery.py       # list_models, list_nodes, audit_dangerous_nodes, etc.
    ├── history.py         # get_history (factory version)
    ├── history_di.py      # get_history (DI version — Depends() proof module)
    ├── files.py           # upload_image, get_image, list_outputs, upload_mask, get_workflow_from_image
    ├── models.py          # search_models, download_model, get_download_tasks, cancel_download
    └── nodes.py           # search/install/uninstall/update custom nodes

scripts/
├── smoke_test.py          # Operator smoke-test against a live ComfyUI instance
├── compare_evals.py       # Diff two Inspect AI eval runs (PASS/FAIL + per-tag breakdown)
├── run_multimodel_eval.py # Run one Task against N models in a single invocation
├── graphify.sh            # graphify wrapper — sources .env, picks pinned interpreter
└── hooks/                 # graphify git hooks (post-commit/post-merge auto-refresh)

tests/                     # pytest with asyncio_mode = auto
pyproject.toml            # Project config (hatchling build)
```

## Development Commands

```bash
uv sync                    # Install dependencies
uv run pytest -v           # Run tests
uv run pytest --cov=src/comfyui_mcp --cov-report=term-missing  # Coverage
uv run ruff check src/ tests/         # Lint
uv run ruff format src/ tests/        # Format (in-place)
uv run ruff format --check src/ tests/  # Format check (CI)
uv run mypy src/comfyui_mcp/          # Type check
uv run pre-commit run --all-files     # Run all pre-commit hooks

# Preflight gate (workflow step 4 before a PR): zero-skip + ruff + format + mypy + pytest
./.opencode/hooks/check-no-skipped-tests.sh   # zero-skip scan

# graphify (knowledge graph) — always via the wrapper so .env is observed
scripts/graphify.sh update .          # AST-only structure refresh (no LLM)
scripts/graphify.sh label .           # regenerate community names via the gateway
scripts/graphify.sh query "..."       # scoped subgraph for a question
scripts/hooks/install.sh              # activate graphify git hooks (once per clone)

# Smoke-test against a live ComfyUI instance
uv run python scripts/smoke_test.py                          # Full (connectivity + folders + download)
uv run python scripts/smoke_test.py --no-download            # Connectivity + folder listing only
uv run python scripts/smoke_test.py --url http://host:8188   # Target a specific server

# Run the Phase 4 evaluation against a model
uv run inspect eval evals/comfyui_mcp_task.py \
    --model ollama/qwen3-coder:480b-cloud \
    --log-dir ./logs/phase4
uv run inspect view --log-dir ./logs/phase4        # browse traces in the UI

# Run the Phase 5 live-execution eval (5 agentic questions, ~5-10 min)
uv run inspect eval evals/comfyui_mcp_task.py@comfyui_mcp_phase5 \
    --model ollama/gpt-oss:120b-cloud \
    --log-dir ./logs/phase5

# Run the eval across multiple models in one shot
# (inspect's --model flag is single-value; the wrapper calls eval_set()
# directly with model=[...] to work around that)
uv run python scripts/run_multimodel_eval.py evals/comfyui_mcp_task.py@comfyui_mcp_phase4 \
    --models ollama/gpt-oss:120b-cloud,ollama/qwen3-coder:480b-cloud,anthropic/claude-sonnet-4-6 \
    --log-dir ./logs/phase4-cross-model

# Compare two eval runs (or two .eval files) side-by-side
uv run python scripts/compare_evals.py logs/phase4 logs/phase4-cross-model
```

## Configuration

Config file: `~/.comfyui-mcp/config.yaml`

Key settings:
- `comfyui.url` — ComfyUI server URL
- `security.mode` — "audit" (log only) or "enforce" (block unapproved nodes, elicit user on warnings)
- `security.dangerous_nodes` — List of node types to flag/warn
- `rate_limits.*` — Requests per minute per category
- `tasks.enabled` — Optional background tasks (Phase 6); `tasks.backend_url` selects memory vs redis

Environment variables override config: `COMFYUI_URL`, `COMFYUI_SECURITY_MODE`, `COMFYUI_TASKS_ENABLED`, `COMFYUI_TASKS_BACKEND_URL`, etc.

## Testing Notes

- Uses `pytest-asyncio` with `asyncio_mode = auto`
- Mock ComfyUI API responses with `respx`
- Tests mirror `src/comfyui_mcp/` structure

## ComfyUI-Model-Manager API notes

The [ComfyUI-Model-Manager](https://github.com/hayden-fr/ComfyUI-Model-Manager)
plugin wraps all its responses in a `{"success": bool, "data": <payload>}` envelope. The MCP client normalizes this in `_unwrap_model_manager_response()` before returning data to callers. All `respx` mocks for Model Manager endpoints must use this shape.

Two known quirks discovered against the live API:

1. **`previewFile` is always required** — `POST /model-manager/model` calls `save_model_preview()` server-side regardless. Omitting the field causes the task to be silently deleted with a misleading "Task not found" error. The client always sends `previewFile` (empty string is fine).
2. **Completed tasks stay as `pause`** — After a download finishes, the task remains in the list with `status: "pause"` and `progress: 100`. This is upstream behavior. Use `cancel_download` (which calls `DELETE /model-manager/download/{task_id}`) to remove it.

## Adding a new tool (checklist)

1. Add the tool function in the appropriate `tools/*.py`
2. Use `@mcp.tool()` decorator with a clear docstring
3. Ensure rate limiting is in effect — in-tool `limiter.check("tool_name")`
   OR rely on `SecurityMiddleware` (wired in `server.py`); add the tool to
   `_TOOL_CATEGORIES` if using the middleware path
4. Ensure audit logging is in effect — in-tool `audit.async_log(...)` OR
   rely on `SecurityMiddleware` (it writes the `action="called"` entry
   record; keep lifecycle logs like `submitted`/`completed` in the tool)
5. If it handles files: validate through `sanitizer`
6. If it submits workflows: inspect through `inspector` (and pass `ctx` to
   `_submit_workflow` for the elicitation gate in enforce mode)
7. Use `Annotated[type, Field(...)]` for parameters with constraints (3+ params)
8. Return `dict[str, Any]` if all code paths return structured data; use `-> str` only for mixed return paths
9. Either add the function to the `tool_fns` dict and return it (factory
   pattern), *or* define it as a module-level decorated function with
   `Depends()` for DI (see `tools/history_di.py` for the pattern)
10. Wire it in `server.py` `_register_all_tools()` if it uses the factory
    pattern and needs new dependencies (module-level decorated functions
    with `Depends()` skip this — the decorator registers them)
11. Add tests in `tests/test_tools_*.py` that call the function directly
12. Update the Tools table in `README.md`

## Adding a new client method (checklist)

1. Verify the ComfyUI endpoint is not on the blocked list (see rule 1)
2. Add the method to `ComfyUIClient` in `client.py`
3. Use `self._request(method, path, ...)` — this handles retries on connection errors
4. Add a test in `test_client.py` with `@respx.mock`

## Adding a new security check (checklist)

1. Add to the appropriate module in `security/`
2. Wire it in `server.py` `_build_server()` and pass to tool registration
   (or add to `SecurityMiddleware` if it is a cross-cutting concern)
3. Add config fields to `config.py` if needed — every field must be read somewhere
4. Add tests in `tests/test_*.py`

## Adding a new resource or prompt (checklist)

1. Add the `@mcp.resource("comfyui://...")` function in `resources.py` (for
   read-only state) or the `@mcp.prompt` function in `prompts.py` (for
   workflow recipes). Register in `server.py` `_register_all_tools()`.
2. Templated resources (`comfyui://.../{param}`) inherit FastMCP 4's
   path-traversal screening (on by default); still anchor the final path
   against an allowed root and confirm containment before reading.
3. Prompts return a plain string (auto-wrapped as a user message) or
   `list[Message]` for multi-turn — not `mcp.types.PromptMessage` or raw
   role/content dicts.
4. Resources/prompts use the read-only rate limiter; add a `limiter.check()`
   call and an `audit.async_log()` entry record (or rely on
   `SecurityMiddleware`).
5. Add tests in `tests/test_resources.py` / `tests/test_prompts.py` that call
   the function directly.

## Maintaining the dangerous nodes list

The `_DEFAULT_DANGEROUS_NODES` list in `config.py` contains real ComfyUI custom node `class_type` values grouped by threat category (code execution, network access, filesystem access). To audit a new custom node package:

1. Check the package source for calls to `exec`, `eval`, `subprocess`, `os.system`, `open()`, `requests`, `urllib`, or `httpx`
2. Look for nodes that accept arbitrary file paths, URLs, or code as input
3. Add confirmed dangerous nodes to the appropriate category in `_DEFAULT_DANGEROUS_NODES` with a comment noting the source package and reason
4. If the node follows a naming pattern not yet covered, add a regex to `_DANGEROUS_NAME_PATTERNS` in `node_auditor.py`
5. Add tests for any new patterns

## OpenCode tooling (opt-in)

Project config (`.opencode/opencode.json`) wires `context7` (MCP / FastMCP /
Pydantic / httpx docs) and `graphify` (live knowledge-graph query server over
stdio) as MCP servers, a `review` subagent (read-only pre-PR check), a
`/preflight` command, the graphify plugin, and a `watcher.ignore` that keeps
the regenerable `graphify-out/`, `.venv`, caches, `uv.lock`, `dist/`, and
`logs/` off the file watcher.

Two built-in tools are **off by default** and need an env var to activate —
uncomment them in [`.env.example`](./.env.example), then
`set -a; . ./.env; set +a` before launching opencode:

- `websearch` — `OPENCODE_ENABLE_EXA=1` (Exa-hosted, no API key). Surfaces web
  results alongside Context7 (which is library-docs-only).
- `lsp` (experimental) — `OPENCODE_EXPERIMENTAL_LSP_TOOL=true` (or
  `OPENCODE_EXPERIMENTAL=true`). Gives the agent go-to-def / find-references /
  hover via the configured LSP servers. Opt in only if you want it; it's
  experimental and not required for any workflow.

## graphify

This project has a knowledge graph at `graphify-out/` with god nodes, community
structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or
instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when
  `graphify-out/graph.json` exists. Use `graphify path "<A>" "<B>"` for
  relationships and `graphify explain "<concept>"` for focused concepts. These
  return a scoped subgraph, usually much smaller than `GRAPH_REPORT.md` or raw
  grep output.
- Dirty `graphify-out/` files are expected after hooks or incremental updates;
  dirty graph files are not a reason to skip graphify. Only skip graphify if the
  task is about stale or incorrect graph output, or the user explicitly says not
  to use it.
- If `graphify-out/wiki/index.md` exists, use it for broad navigation instead of
  raw source browsing.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or when
  query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current
  (AST-only, no API cost).
