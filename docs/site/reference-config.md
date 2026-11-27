---
type: reference
title: "Configuration"
description: "Every config.yaml field with its default — comfyui, security, rate_limits, model_search, logging, transport, tasks."
created: 2026-10-06
updated: 2026-11-27
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
  policy:                          # Optional declarative policy
    deny_nodes: []                 # Hard block in enforce, warning in audit
    warn_nodes: []                 # Extra class types to warn on
    on_warning: "elicit"           # elicit | block | allow
    max_nodes: 0                   # 0 disables the cap
    allowed_model_folders: []      # [] allows every model folder
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
  max_bytes: 10485760            # rotate at 10 MiB; 0 disables
  backup_count: 5                # audit.log.1 … audit.log.5

transport:
  remote:
    enabled: false                 # true → Streamable HTTP instead of stdio
    host: "127.0.0.1"
    port: 8080
    allow_unauthenticated: false   # refused for non-loopback binds
    auth:
      enabled: false
      tokens:                      # identity label → token env var name
        operator: COMFYUI_MCP_HTTP_TOKEN

tools:                             # Tool-surface profile
  profile: "full"                  # "full" or "core"

tasks:                             # Optional background tasks (FastMCP 4 TasksExtension)
  enabled: false
  backend_url: "memory://"         # or "redis://localhost:6379/0"
```

## Field notes

- `security.mode` — see [audit mode](./security-audit-mode.md) and
  [enforce mode](./security-enforce-mode.md). The default is audit.
- `security.allowed_nodes` — only consulted in enforce mode. Nodes not in
  the list are hard-blocked before elicitation.
- `security.policy` — declarative rules for enforce mode. `deny_nodes`,
  `max_nodes`, and `allowed_model_folders` hard-block in enforce mode and warn
  in audit mode; `on_warning` decides what a remaining warning means
  (`elicit`/`block`/`allow`). Unknown keys are rejected at startup. See
  [enforce mode](./security-enforce-mode.md#declarative-policy).
- `security.dangerous_nodes` — *additional* entries; the built-in default
  list always applies. Get candidates via `comfyui_audit_dangerous_nodes`.
- `security.max_upload_size_mb` — local cap; also cross-checked against the
  server's reported `max_upload_size` when `/features` exposes it (the
  stricter of the two applies, when both are known).
- `logging.max_bytes` / `logging.backup_count` — size-based audit rotation;
  `max_bytes: 0` disables it, `backup_count: 0` truncates instead of keeping
  history. Rotation refuses a symlinked backup path.
- `comfyui.external_url` — for deployments where the ComfyUI host is
  reachable from the client's browser/sandbox only via a different URL.
- `transport.remote.*` — Streamable HTTP mode. A non-loopback `host` is
  refused unless `auth.enabled` or `allow_unauthenticated` is set; prefer the
  former.
- `transport.remote.auth.tokens` — maps an identity label to the *environment
  variable name* holding that identity's bearer token. The token is read at
  startup and never written to config; the label lands in the audit log and
  scopes per-identity rate limits. Startup fails closed if no configured
  variable is set. OIDC/TLS stay at the reverse proxy.
- `tools.profile` — `full` (default) exposes every tool; `core` exposes the
  generation, jobs, files, and discovery loop (25 tools) and hides the rest.
  Hidden tools are neither listed nor callable by name. Prompts/resources are
  unaffected.
- `tasks.*` — off by default; see [background tasks](./architecture/tasks.md).

Environment variables override any of these — see
[env vars](reference-env-vars.md).