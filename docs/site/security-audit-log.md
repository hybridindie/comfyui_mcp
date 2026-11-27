---
type: reference
title: "The audit log"
description: "Schema, redaction rules, and the queries worth keeping."
created: 2026-10-06
updated: 2026-11-27
---

# The audit log

All tool invocations are logged as JSON lines to `~/.comfyui-mcp/audit.log`
(configurable via `logging.audit_file` / `COMFYUI_AUDIT_FILE`).

## Rotation

The file rotates at `logging.max_bytes` (default 10 MiB) and keeps
`logging.backup_count` files (default 5) as `audit.log.1` … `audit.log.N`.
Records are appended atomically under a lock; rotation refuses to run through
a symlinked backup path. Set `max_bytes: 0` to disable rotation, or
`backup_count: 0` to truncate instead of keeping history.

## Schema

Every line is one JSON object. Two kinds of records:

**Entry records** — one per tool call, written by `SecurityMiddleware`:

```json
{
  "timestamp": "2026-10-06T14:30:00+00:00",
  "tool": "comfyui_generate_image",
  "action": "called",
  "params": { "prompt": "a yellow apple", "model": "sd_xl_base_1.0.safetensors" }
}
```

**Lifecycle records** — written by tools as work progresses:

```json
{ "tool": "comfyui_run_workflow", "action": "submitted",  "prompt_id": "b0f6...e21", "nodes_used": ["KSolver"] }
{ "tool": "comfyui_run_workflow", "action": "completed",  "prompt_id": "b0f6...e21" }
{ "tool": "comfyui_run_workflow", "action": "inspected",  "nodes_used": ["KSampler"], "warnings": [] }
{ "tool": "comfyui_upload_image", "action": "upload_rejected", "reason": "..." }
{ "tool": "comfyui_update_settings", "action": "settings_updated" }
```

The server's startup capability snapshot is recorded once per server run
(`action: "server_features"`) so runs against capability-differing ComfyUI
servers are distinguishable after the fact.

## Redaction

Sensitive fields — `token`, `password`, `secret`, `api_key`,
`authorization` — are redacted before the record is written, at both the
middleware (argument redaction) and logger (payload redaction) layers.

## Turning the log into a policy

`scripts/policy_init.py` reads this file and produces a reviewable
`security.allowed_nodes` fragment: it counts `nodes_used` per inspected
workflow, excludes dangerous and policy-denied nodes, and flags allowlist
entries that were never observed. `--apply` writes the result (keeping a
`.bak`); nothing changes until `security.mode` is `enforce`.

```bash
uv run python scripts/policy_init.py
uv run python scripts/policy_init.py --apply
```

## Useful queries

```bash
# Watch it in real time
tail -f ~/.comfyui-mcp/audit.log | python -m json.tool

# Find all workflows that used dangerous nodes
grep '"warnings":\[' ~/.comfyui-mcp/audit.log | grep -v '"warnings":\[\]'

# Everything a session submitted
grep '"action":"submitted"' ~/.comfyui-mcp/audit.log

# Upload rejections (sanitizer or size enforcement)
grep '"action":"upload_rejected"' ~/.comfyui-mcp/audit.log

# Confirm a tool was never called
grep '"tool":"comfyui_update_settings"' ~/.comfyui-mcp/audit.log
```

The log is the "what did the agent actually do?" ground truth — grep it
before trusting a recap. Also see [enforce mode](./security-enforce-mode.md)
for the elicitation-recorded decisions and the
[threat model](./security-threat-model.md) for what the log does not prove.