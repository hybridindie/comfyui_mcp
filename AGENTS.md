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

The full project context and the grounding-rule index are in
[`CLAUDE.md`](./CLAUDE.md) — read it first. The constitutional rules themselves
live in [`.opencode/rules/`](./.opencode/rules/), loaded as `instructions` in
[`opencode.json`](./.opencode/opencode.json), and are the source of truth for
how to build here:

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
