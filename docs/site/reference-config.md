---
type: reference
title: "Configuration"
description: "Every config.yaml field with its default — comfyui, security, rate_limits, model_search, logging, transport, tasks."
created: 2026-10-06
updated: 2026-10-06
---

# Configuration

Config file: `~/.comfyui-mcp/config.yaml` (path override: none — this is
fixed). Every field below is read somewhere; unused fields are removed by
policy (dead config is a bug here).

```yaml
comfyui:
  url: "http://127.0.0.1:8188"   # ComfyUI server URL
  external_url: null               # Optional public URL for get_image URL responses
                                   # If unset, URL responses use comfyui.url
  tls_verify: true                 # TLS certificate verification
  timeout_connect: 30              # Connection timeout (seconds)
  timeout_read: 300                # Read timeout (seconds)

security:
  mode: "audit"                    # "audit" (log only) or "enforce" (block unapproved)
  allowed_nodes: []                # Enforce mode: only these nodes can run
  dangerous_nodes: []              # Appended to the built-in default list (~150 nodes).
                                   # Always flagged in audit log / enforcement.
                                   # Full built-in list: config.py _DEFAULT_DANGEROUS_NODES
  max_upload_size_mb: 50
  allowed_extensions:
    - ".png"
    - ".jpg"
    - ".jpeg"
    - ".webp"
    - ".gif"
    - ".json"

rate_limits:                       # Requests per minute per category
  workflow: 10
  generation: 10
  file_ops: 30
  read_only: 60

model_search:
  huggingface_token: ""            # Optional; needed for gated/private HF models
  civitai_api_key: ""              # Optional; needed for auth-only CivitAI access
  max_search_results: 10

logging:
  audit_file: "~/.comfyui-mcp/audit.log"

transport:
  remote:
    enabled: false                 # true → Streamable HTTP instead of stdio
    host: "127.0.0.1"
    port: 8080

tasks:                             # Optional background tasks (FastMCP 4 TasksExtension)
  enabled: false
  backend_url: "memory://"         # or "redis://localhost:6379/0"
```

## Field notes

- `security.mode` — see [audit mode](./security-audit-mode.md) and
  [enforce mode](./security-enforce-mode.md). The default is audit.
- `security.allowed_nodes` — only consulted in enforce mode. Nodes not in
  the list are hard-blocked before elicitation.
- `security.dangerous_nodes` — *additional* entries; the built-in default
  list always applies. Get candidates via `comfyui_audit_dangerous_nodes`.
- `security.max_upload_size_mb` — local cap; also cross-checked against the
  server's reported `max_upload_size` when `/features` exposes it (the
  stricter of the two applies, when both are known).
- `comfyui.external_url` — for deployments where the ComfyUI host is
  reachable from the client's browser/sandbox only via a different URL.
- `transport.remote.*` — Streamable HTTP mode; keep `host` on localhost
  unless behind an authenticated TLS reverse proxy.
- `tasks.*` — off by default; see [background tasks](./architecture/tasks.md).

Environment variables override any of these — see
[env vars](reference-env-vars.md).