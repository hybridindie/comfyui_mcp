# AGENTS.md

Entry point for OpenCode, Claude Code and other agentic clients working in **comfyui_mcp**.

## Independent & harness-agnostic

comfyui_mcp is a **standalone MCP server** — a secure Model Context Protocol
server for [ComfyUI](https://github.com/comfyanonymous/ComfyUI). It is usable by
**any** AI agent harness (OpenCode, or any MCP client over stdio or Streamable
HTTP) and exposes ComfyUI's workflow / generation / discovery / security API.

It has **no dependency on any specific consumer.** The server is the product;
the `/comfy:*` skills shipped in this repo are convenience recipes that wrap
multi-tool flows — they are not coupled to any one harness.

The rules in [`.claude/rules/`](./.claude/rules/) are the source of truth for
how to build here. Claude Code loads them by `paths:`; for any client, read the
ones whose "Read when" matches the task. When a rule and this file disagree,
the rule wins. `security.md` holds the security invariants the tests enforce.

## Rule Index

| Rule file | Read when |
|---|---|
| `.claude/rules/architecture.md` | Changing server wiring, module layout, middleware, resources/prompts, the Model Manager client, or the dangerous-nodes list |
| `.claude/rules/async-patterns.md` | Writing async code, transports, background jobs, or anything with timeouts |
| `.claude/rules/cicd.md` | Changing CI workflows, build steps, caching, or release automation |
| `.claude/rules/documentation-standards.md` | Writing a README, ADR, API reference, or agent-facing docs (AGENTS.md included) |
| `.claude/rules/enforcement.md` | Before committing or opening a PR, or when cutting a release |
| `.claude/rules/graphify.md` | Running graphify, editing .graphifyignore or the graphify git hooks, or refreshing the knowledge graph |
| `.claude/rules/logging-observability.md` | Adding logs, metrics, tracing, or debugging a production issue |
| `.claude/rules/packaging.md` | Changing packaging, entry points, versions, or the Python floor |
| `.claude/rules/security.md` | Touching client endpoints, file-handling or workflow-submitting tools, rate limiting, audit logging, or dependencies |
| `.claude/rules/testing.md` | Writing or fixing tests, mocks, or the security-invariant tests |
| `.claude/rules/tools.md` | Adding or changing an MCP tool, its parameters, docstring, or return shape |
| `.claude/rules/workflow.md` | Starting or finishing a change, opening a PR, or changing anything an agent sees (tool descriptions, schemas, return shapes) |

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
- **MCP Framework**: fastmcp[tasks] 4.x (standalone FastMCP 4, built on MCP
  SDK v2)
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
    ├── history_di.py      # get_history (DI version — Depends())
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
bash .claude/hooks/check-no-skipped-tests.sh   # zero-skip scan

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

## Checklists

Step-by-step procedures live with the rule they serve:

- Adding a new tool — `tools.md`
- Adding a new client method, security check, resource or prompt — `architecture.md`
- Model Manager API quirks and maintaining the dangerous-nodes list — `architecture.md`
- Cutting a release — `enforcement.md`
- Running the Phase 4 eval before merging a tool-surface change — `workflow.md`

## Harness

Both harnesses come from genesis (`.claude/harness.json` records the stacks:
python, mcp). Claude Code reads `CLAUDE.md` (imports this file and
`my-workflows.md`); OpenCode reads `.opencode/opencode.json`, which loads this
file, `my-workflows.md` and `.wiki-overlay.md` as `instructions`. Agents,
commands and skills are mirrored in `.claude/` and `.opencode/` with the same
body; `python3 .claude/hooks/check-project-drift.py` checks the harness.

### Commands

- /preflight — the CI checks plus the harness gates, before a PR
- /ship-pr — open a PR, watch CI and review, merge on request
- /harness-eval — check the rules still fit the code

### Skills

- `ship-pr` — scripts behind the ship-pr command
- `customize-harness` — tailor the harness after an eval
- `test-hygiene-scanner` — find weak or skipped tests

### Agents

- review — read-only pre-PR review against the gates and contracts

### OpenCode extras

`.opencode/opencode.json` also wires `context7` (MCP / FastMCP / Pydantic /
httpx docs) and `graphify` (live knowledge-graph query server over stdio) as
MCP servers, the graphify plugin, and a `watcher.ignore` that keeps the
regenerable `graphify-out/`, `.venv`, caches, `uv.lock`, `dist/`, and `logs/`
off the file watcher.

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

## wiki-fabric (opencode)
## wiki-fabric

This project is connected to a knowledge fabric (`.wiki-overlay.md` declares the namespace; the fabric lives at `~/.local/share/wiki-fabric/` by default — `WIKI_FABRIC_DIR` overrides).

Rules:
- Before starting a task, run `wf context --task "<task>" --write-receipt` (0 tokens) — it compiles a scoped manifest of relevant claims, patterns, and decisions (project > domain > global precedence) with exclusion reasons. The `--write-receipt` flag persists a delivery record (the manifest + provenance, still on stdout) so outcomes can later be reviewed against what was known: receipts are the default delivery record, zero extra cost.
- For codebase/architecture questions, run `wf query "<question>"` (0 tokens) before grepping — evidence-backed answers with locators.
- Health before commit: `wf lint` (0-error gate). Status: `wf status`. Before mutating the repo, confirm it is clean: `git status --porcelain` should be empty — if it lists many uncommitted changes (a dirty restructure), surface that to the user rather than branching/committing over it. If `wf status` reports a STALE installed CLI, run the harness script directly (`bash scripts/wiki-fabric.sh ...`) or `wf update` before relying on `wf` subcommands.
- After solving a non-trivial problem, log it: `wf log --project <slug> --receipt <receipt-id>` (the receipt id is in the `wf context --write-receipt` stderr output) — receipt ↔ outcome linkage is the delivery/outcome evidence plane mining uses.
- Never re-ingest a source whose sha256 is already recorded — the CLI skips it and tells you.
- Promotion is human-gated: `wf` proposes dossiers, only you promote.
- At session start, run `wf gate` — it aggregates every pending human decision (overdue/stale claims, promotion dossiers awaiting review, newly-proposed domains, open questions awaiting triage) into one report; `wf gate --deliveries` surfaces recent context receipts for delivery-vs-outcome review. Surface whichever are actionable to the user before proceeding. Resolve with: `wf review --auto-reverify`, `wf promote --promote <dossier>`, `python3 scripts/cmd/promote-domains.py --apply <dossier>`, `python3 scripts/cmd/promote-questions.py --apply <id>`. If the git hook ran, it already persisted these to `registry/pending-gate.md` — read that instead of running commands (0 tokens).
- **Procedures on demand:** run `wf skill <name>` before these workflows — `ingest`, `promote`, `refresh`. `wf skill --list` summarizes them. Read the procedure before running the workflow the first time in a session.

CLI: `wf help` | When graphify is also installed: graphify owns code-symbol/call-graph questions; wiki-fabric owns evidence-backed knowledge (`wf query` — claims with doc locators). Prefer `wf context` for task scoping. They complement — neither replaces the other.
<!-- /wiki-fabric:opencode -->

## wiki-fabric (codex)
## wiki-fabric

This project is connected to a knowledge fabric (`.wiki-overlay.md` declares the namespace; the fabric lives at `~/.local/share/wiki-fabric/` by default — `WIKI_FABRIC_DIR` overrides).

Rules:
- Before starting a task, run `wf context --task "<task>" --write-receipt` (0 tokens) — it compiles a scoped manifest of relevant claims, patterns, and decisions (project > domain > global precedence) with exclusion reasons. The `--write-receipt` flag persists a delivery record (the manifest + provenance, still on stdout) so outcomes can later be reviewed against what was known: receipts are the default delivery record, zero extra cost.
- For codebase/architecture questions, run `wf query "<question>"` (0 tokens) before grepping — evidence-backed answers with locators.
- Health before commit: `wf lint` (0-error gate). Status: `wf status`. Before mutating the repo, confirm it is clean: `git status --porcelain` should be empty — if it lists many uncommitted changes (a dirty restructure), surface that to the user rather than branching/committing over it. If `wf status` reports a STALE installed CLI, run the harness script directly (`bash scripts/wiki-fabric.sh ...`) or `wf update` before relying on `wf` subcommands.
- After solving a non-trivial problem, log it: `wf log --project <slug> --receipt <receipt-id>` (the receipt id is in the `wf context --write-receipt` stderr output) — receipt ↔ outcome linkage is the delivery/outcome evidence plane mining uses.
- Never re-ingest a source whose sha256 is already recorded — the CLI skips it and tells you.
- Promotion is human-gated: `wf` proposes dossiers, only you promote.
- At session start, run `wf gate` — it aggregates every pending human decision (overdue/stale claims, promotion dossiers awaiting review, newly-proposed domains, open questions awaiting triage) into one report; `wf gate --deliveries` surfaces recent context receipts for delivery-vs-outcome review. Surface whichever are actionable to the user before proceeding. Resolve with: `wf review --auto-reverify`, `wf promote --promote <dossier>`, `python3 scripts/cmd/promote-domains.py --apply <dossier>`, `python3 scripts/cmd/promote-questions.py --apply <id>`. If the git hook ran, it already persisted these to `registry/pending-gate.md` — read that instead of running commands (0 tokens).
- **Procedures on demand:** run `wf skill <name>` before these workflows — `ingest`, `promote`, `refresh`. `wf skill --list` summarizes them. Read the procedure before running the workflow the first time in a session.

CLI: `wf help` | When graphify is also installed: graphify owns code-symbol/call-graph questions; wiki-fabric owns evidence-backed knowledge (`wf query` — claims with doc locators). Prefer `wf context` for task scoping. They complement — neither replaces the other.
<!-- /wiki-fabric:codex -->
