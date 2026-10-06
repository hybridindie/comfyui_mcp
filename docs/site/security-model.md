---
type: concept
title: "The security model"
description: "The six server-side controls, how they compose, and where enforcement lives."
created: 2026-10-06
updated: 2026-10-06
---

# The security model

Every control lives in the server process, where no MCP client can disable
it. Six controls compose into one pipeline.

## The six controls

| Control | Module | What it does |
|---|---|---|
| Workflow Inspector | `security/inspector.py` | Parses workflow JSON before submission: dangerous nodes, suspicious inputs, server-side replacements, subgraph recursion |
| Path Sanitizer | `security/sanitizer.py` | Validates every filename/subfolder/URL segment: traversal, null bytes, control chars, extension allowlist |
| Rate Limiter | `security/rate_limit.py` | Token-bucket per category: workflow 10/min, generation 10/min, file_ops 30/min, read_only 60/min |
| Audit Logger | `audit.py` | One structured JSON line per call, sensitive fields redacted |
| Blocked endpoints | `client.py` (by omission) | `/userdata`, `/free`, `/users`, `/history` POST are never proxied — enforced by tests |
| Elicitation gate | generation tools | Enforce mode: the tool pauses and asks the user before submitting a flagged workflow |

Cross-cutting plumbing: `SecurityMiddleware` (FastMCP 4 `on_call_tool` hook)
applies rate limiting and the entry audit record to **every** tool call,
with sensitive arguments redacted before the record is written.

## How they compose on one call

A `comfyui_upload_image` call passes through, in order:

```text
SecurityMiddleware   → rate-limit check (file_ops bucket) + entry audit record
  Path Sanitizer     → filename/subfolder validated, extension allowlisted
  server features    → max_upload_size fetched (5-min TTL cache), enforced locally
  ComfyUIClient      → the only code that touches httpx
Audit Logger         → result/audit entries (e.g. upload_rejected)
```

A `comfyui_run_workflow` call adds the inspector between the middleware and
the client, and the elicitation gate before submission in enforce mode.

## Enforcement is test-pinned

The invariants are enforced by `tests/test_blocked_endpoints.py` and
`tests/test_security_invariants.py`:

- every tool is rate-limited (in-tool or middleware) — asserted, not assumed
- every tool is audit-logged (in-tool or middleware)
- every file tool sanitizes
- every workflow submit inspects
- blocked endpoints never appear in `client.py`

A new tool that skips a control fails CI. The guarantee has the same status
as a type check.

## What the model does not cover

The inspector is **static** analysis against a known-node list plus name
patterns. It cannot catch:

- unknown obfuscated custom nodes
- a compromised ComfyUI installation itself
- social engineering of the user through the conversation (that's what
  enforce mode's hard allowlist is for)

Run ComfyUI in a container if the host matters. Full detail in the
[threat model](./security-threat-model.md).