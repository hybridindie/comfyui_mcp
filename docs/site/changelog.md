---
type: index
title: "Changelog"
description: "Release history for comfyui-mcp-secure."
created: 2026-10-06
updated: 2026-10-06
---

# Changelog

Full release notes live on
[GitHub Releases](https://github.com/hybridindie/comfyui_mcp/releases), and
the complete technical changelog is
[`CHANGELOG.md`](https://github.com/hybridindie/comfyui_mcp/blob/main/CHANGELOG.md)
in the repo. This page summarizes recent ones.

## 2.3.0 — 2026-10-06

Additive minor release. **Security fix** for inline content types; new
partial-execution and loop-validation features; fastmcp off the beta.

- **Partial execution targets (#112)** — `comfyui_run_workflow` /
  `comfyui_run_workflow_stream` accept `partial_execution_targets` (re-run
  listed nodes, serve the rest from the server's execution cache) with
  local node-ID validation.
- **Loop-structure validation (#180)** — the validator now mirrors
  ComfyUI's server-side loop pairing/escape/accumulate rules; orphaned
  StartLoop/EndLoop graphs no longer pass silently.
- **Content-type allow-list for inline images (#177)** *(security)* —
  `comfyui_get_image` allow-lists raster `image/*` only (blocking
  `image/svg+xml`), default-denies unknown/missing types, closes an XSS
  relay path (GHSA-779p-m5rp-r4h4 follow-up).
- **`max_upload_size` enforcement (#178)** — uploads rejected locally with
  the byte budget instead of opaque HTTP 413; `/features` cached 5 min.
- **Capability flags documented + recorded (#179)** — `/features` keys
  documented for agents; startup snapshot in the audit trail.
- **fastmcp 4.0.0b3 → stable 4.0.11 (#176)** — off the beta; mypy 2.4.0,
  openai 3.24.0.

## 2.2.0 — 2026-08-29

The FastMCP 4 release. Resources, prompts, middleware, DI, elicitation,
background tasks, and a big surface cleanup.

- **Resources** — `comfyui://models/{folder}`, `comfyui://nodes/installed`,
  `comfyui://queue`, `comfyui://system` — browsable read-only state
- **Prompts** — 4 workflow-recipe prompts (txt2img, img2img, inpaint, upscale)
- **SecurityMiddleware** — centralized rate limiting + entry audit across
  every tool call; 43 in-tool limiter calls and 22 audit boilerplate calls
  dropped
- **Elicitation gate (Phase 5)** — enforce mode asks the user to confirm
  flagged workflows before submission
- **Background tasks (optional)** — TasksExtension (Docket), `memory://` or
  Redis backends
- **Migrated to FastMCP 4** (from 1.0-style `mcp.server.fastmcp`); typed
  returns with generated `outputSchema`; `CLAUDE.md` consolidated into
  `AGENTS.md`
- **135 first-party cloud API nodes flagged** — prompts/images to paid
  services (BFL, Gemini, Runway, OpenAI, ...) warn by default
- **Subgraph inspection** — inspector recurses into subgraph node maps;
  unexpanded references warn explicitly

## 2.1.0 — 2026-05-12

- **`comfyui_analyze_workflow`** — structured workflow analysis as a dict
- **Inspect AI eval harness** — Phase 4 (10 static questions) + Phase 5
  (5 live-execution questions) task suites with tagged JSONL datasets
- **Docstring pass** — workflow-tool docs enumerate every operation shape
- Non-breaking `params` default fix (`"{}"` → `""` still accepted)

## 2.0.0 — 2026-05-11

Major release with breaking changes — unified wait envelope, flattened job
objects, pagination envelopes, parameter renames (`id` → `node_id`,
`format` → `output_format`). See the full
[CHANGELOG](https://github.com/hybridindie/comfyui_mcp/blob/main/CHANGELOG.md#200--2026-05-11)
for migration details.