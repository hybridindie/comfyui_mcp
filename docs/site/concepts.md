---
type: concept
title: "Core concepts"
description: "The vocabulary the rest of the docs assume — tools, resources, prompts, the inspector, the sanitizer, elicitation."
created: 2026-10-06
updated: 2026-10-06
---

# Core concepts

Six ideas cover most of the surface. Everything else in the docs builds on
these.

## The server chain

```text
MCP client ──► SecurityMiddleware ──► tool ──► ComfyUIClient ──► ComfyUI
                 (rate limit +
                  entry audit)         (inspector/
                                       sanitizer as
                                       applicable)
```

Tools never call `httpx` directly — all ComfyUI HTTP access is centralized in
`ComfyUIClient`, which normalizes responses, retries connection errors, and
unwraps the Model Manager envelope. Transport details live in one place.

## Tools, resources, prompts

Three component types, all served over MCP:

- **Tools** (`comfyui_*`) — actions and queries the LLM calls explicitly.
  53 of them across generation, workflow authoring, jobs, discovery, files,
  models, and custom nodes. Structured `dict` returns with generated
  `outputSchema`.
- **Resources** (`comfyui://...`) — read-only state the LLM browses by URI
  without a tool call: `comfyui://models/{folder}`,
  `comfyui://nodes/installed`, `comfyui://queue`, `comfyui://system`,
  `comfyui://settings`.
- **Prompts** — parameterized workflow recipes (`txt2img_prompt`,
  `img2img_prompt`, `inpaint_prompt`, `upscale_prompt`) that expand into
  user-message guidance for the LLM.

All three are rate-limited and audit-logged — the middleware covers every
component type, not just tools.

## The workflow inspector

The security centerpiece. Before any workflow reaches `/prompt`, the
inspector parses the graph and checks:

- **Dangerous nodes** — against a curated list of ~150 real custom-node
  `class_type`s grouped by threat (code execution, network access,
  filesystem access), plus name-pattern matching for unknown packages.
- **Suspicious inputs** — recursive pattern matching for `__import__()`,
  `eval()`, `exec()`, `os.system()`, `subprocess` in node inputs, including
  nested dicts/lists.
- **Server-side replacements** — fetches ComfyUI's `/node_replacements` map
  and warns when a submitted node will be silently rewritten before
  validation (recursing into subgraphs).
- **Subgraphs** — recurses into embedded subgraph node maps; emits an
  explicit warning when a reference has no inline map and inspection is
  incomplete.

Mode decides what warnings mean: log-and-continue (audit) or block (enforce).

## Audit mode vs enforce mode

| | Audit (default) | Enforce |
|---|---|---|
| Dangerous node found | Warning in response + log | Elicit user confirmation; decline blocks |
| Node not in `allowed_nodes` | — (no allowlist) | Hard block before elicitation |
| Suspicious input | Warning | Elicit |
| Use when | Development, solo | Shared / exposed deployments |

The two modes share the same detection code — only the response differs.

## Elicitation

MCP's mechanism for a tool to ask the user a question mid-call. Enforce mode
uses it for the confirmation gate: the flagged workflow pauses, the user
sees the warnings, and a boolean confirm/decline decides. A decline raises
`WorkflowBlockedError` without calling `post_prompt`. This is server
behavior — an LLM cannot choose to skip the question.

## The path sanitizer

Every filename/subfolder parameter flows through it: path traversal (`..`,
absolute paths), null bytes, control characters, percent-encoded tricks, and
an extension allowlist (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.json`
by default). Discovery tools sanitize URL path segments too. Uploads are
size-capped by config and by the server's reported `max_upload_size`.

## The audit log

One structured JSON line per tool call at `~/.comfyui-mcp/audit.log`:
timestamp, tool, action, relevant payload. Sensitive fields (`token`,
`password`, `secret`, `api_key`, `authorization`) are redacted before
write. The `SecurityMiddleware` writes the entry record for every call;
tools add lifecycle records (`submitted`, `completed`, `inspected`,
`upload_rejected`, ...).