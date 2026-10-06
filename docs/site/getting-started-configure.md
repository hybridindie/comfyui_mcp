---
type: guide
title: "Configure"
description: "Point the server at your ComfyUI instance — config file, environment overrides, security mode, remote transport."
created: 2026-10-06
updated: 2026-10-06
---

# Configure

## Minimal config

```bash
mkdir -p ~/.comfyui-mcp
cat > ~/.comfyui-mcp/config.yaml << 'EOF'
comfyui:
  url: "http://127.0.0.1:8188"
EOF
```

For a remote server:

```yaml
comfyui:
  url: "https://your-gpu-server:8188"
  tls_verify: true
```

The full config lives at `~/.comfyui-mcp/config.yaml` — every field with its
default is in the [configuration reference](./reference-config.md).

## Environment variables override config

The essentials:

```bash
export COMFYUI_URL="http://127.0.0.1:8188"
export COMFYUI_SECURITY_MODE="enforce"   # "audit" (default) or "enforce"
```

The complete variable table is on the [env vars](./reference-env-vars.md) page.

## Choose a security mode

**Audit mode (default)** — every workflow is inspected and logged; dangerous
nodes produce warnings but do not block. Right for development and solo use.

**Enforce mode** — unapproved nodes are blocked hard; flagged workflows
trigger a user-confirmation gate (MCP elicitation). Right for shared or
exposed deployments:

```yaml
security:
  mode: "enforce"
  allowed_nodes:
    - "KSampler"
    - "CheckpointLoaderSimple"
    - "CLIPTextEncode"
    - "VAEDecode"
    - "EmptyLatentImage"
    - "SaveImage"
    - "LoadImage"
    - "LoraLoader"
```

The migration path: run `comfyui_audit_dangerous_nodes` once, work in audit
mode to see which nodes you actually use, then paste the allowlist and switch.
Details in [audit mode](./security-audit-mode.md) and
[enforce mode](./security-enforce-mode.md).

## Remote transport (Streamable HTTP)

The server speaks stdio by default. For remote/multi-client access:

```yaml
transport:
  remote:
    enabled: true
    host: "127.0.0.1"
    port: 8080
```

Keep this bound to localhost unless you are running behind an authenticated
TLS reverse proxy. Background tasks (optional, for long-running workflows over
HTTP) are covered in [background tasks](./architecture/tasks.md).

## Verify

```bash
# From source
uv run python -c "from comfyui_mcp.server import mcp; print(f'Server {mcp.name!r} ready')"

# Docker
docker run --rm ghcr.io/hybridindie/comfyui_mcp:latest --help
```

Against a live ComfyUI instance, the smoke test checks connectivity and
folder listing:

```bash
uv run python scripts/smoke_test.py --no-download
```

Next: [add the server to your MCP client](./getting-started-clients.md).