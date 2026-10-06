---
type: concept
title: "Audit mode"
description: "The default mode — every workflow inspected and logged, nothing blocked."
created: 2026-10-06
updated: 2026-10-06
---

# Audit mode

The default. Every workflow is inspected and logged, but nothing is blocked.
Use it during development to understand what nodes your workflows actually
use.

```yaml
security:
  mode: "audit"
```

## What the tool response looks like

When a dangerous node is detected, warnings ride along in the response:

```text
Workflow submitted. prompt_id: abc123

⚠️ Warnings detected:
  - Dangerous node type: ExecutePython
  - Suspicious input in node 5 (ExecutePython), field 'code'
```

The structured form is a `warnings` array on the result dict — the same
warnings the MCP instructions tell the LLM to relay to the user before
proceeding. That relay is best-effort by design; enforcing it is what
[enforce mode](./security-enforce-mode.md) is for.

## What the audit log looks like

```json
{
  "timestamp": "2026-02-25T14:30:00+00:00",
  "tool": "run_workflow",
  "action": "inspected",
  "nodes_used": ["KSampler", "CLIPTextEncode", "VAEDecode", "SaveImage"],
  "warnings": []
}
```

Every tool call also gets a `called` entry record from the
`SecurityMiddleware`; tools add lifecycle records (`submitted`,
`completed`, `inspected`, ...). See [the audit log](./security-audit-log.md)
for the queries that matter.

## Building your dangerous-node list

`comfyui_audit_dangerous_nodes` scans all installed nodes and classifies
them:

```text
comfyui_audit_dangerous_nodes() → {
  "total_nodes": 456,
  "dangerous": {
    "count": 12,
    "nodes": [
      { "class": "ExecutePython", "reason": "Name matches pattern: \\bexec\\b" },
      { "class": "RunPython",     "reason": "Name matches pattern: \\brunpython\\b" },
      { "class": "ShellCommand",  "reason": "Name matches pattern: \\bshell\\b" }
    ]
  },
  "suspicious": { ... }
}
```

Feed these into your config — they're appended to the built-in default list
(~150 confirmed nodes grouped by code-execution / network / filesystem
threat categories):

```yaml
security:
  mode: "audit"
  dangerous_nodes:
    - "ExecutePython"      # from audit_dangerous_nodes
    - "RunPython"
    - "ShellCommand"
```

This is the intended migration path: audit first, watch the warnings,
then move to [enforce mode](./security-enforce-mode.md) with a real allowlist.