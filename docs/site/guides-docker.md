---
type: guide
title: "Docker deployment"
description: "The GHCR image, stdio wiring, config mounting, and compose."
created: 2026-10-06
updated: 2026-10-06
---

# Docker deployment

A pre-built image is published to the GitHub Container Registry — no clone
required:

```bash
docker pull ghcr.io/hybridindie/comfyui_mcp:latest
```

The container runs as a non-root `app` user with
`uv run comfyui-mcp-secure` as the entrypoint, speaking stdio — compatible
with OpenCode, Claude Desktop, Cursor, any stdio MCP client.

## Standalone

```bash
docker run --rm -i \
  -e COMFYUI_URL=http://host.docker.internal:8188 \
  -v ~/.comfyui-mcp:/home/app/.comfyui-mcp:ro \
  ghcr.io/hybridindie/comfyui_mcp:latest
```

> [!NOTE]
> On Linux, add `--add-host=host.docker.internal:host-gateway` if
> ComfyUI runs on the host. If ComfyUI is on another server, point
> `COMFYUI_URL` there directly.

## MCP client wiring

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "COMFYUI_URL=http://host.docker.internal:8188",
        "-v", "~/.comfyui-mcp:/home/app/.comfyui-mcp:ro",
        "ghcr.io/hybridindie/comfyui_mcp:latest"
      ]
    }
  }
}
```

Key points: `--rm -i` (interactive, no detach — stdio needs the pipe), the
config mount is read-only, and **audit logs written inside the container
are not persisted** unless you mount that directory too (compose below
does).

## Docker Compose

`deploy/docker/docker-compose.yml` in the repo, for persistent
deployments:

```bash
COMFYUI_URL=http://your-comfyui:8188 docker compose \
    -f deploy/docker/docker-compose.yml up -d
```

The compose file mounts `config.yaml` from the repo root and persists audit
logs to a named volume:

```yaml
services:
  comfyui-mcp-secure:
    build:
      context: ../..
      dockerfile: deploy/docker/Dockerfile
    image: comfyui-mcp-secure:latest
    container_name: comfyui-mcp-secure
    environment:
      - COMFYUI_URL=${COMFYUI_URL:-http://comfyui:8188}
      - COMFYUI_SECURITY_MODE=${COMFYUI_SECURITY_MODE:-audit}
    volumes:
      - ../../config.yaml:/home/app/.comfyui-mcp/config.yaml:ro
      - comfyui-mcp-secure-data:/home/app/.comfyui-mcp/logs
    restart: unless-stopped

volumes:
  comfyui-mcp-secure-data:
```

## Production notes

Docker gives you containment (the
[production guide](guides-production.md) recommends running **ComfyUI** in
a container too). Set `COMFYUI_SECURITY_MODE=enforce` in the environment
rather than relying on the mounted config, keep the remote/HTTP transport
off unless a proxy fronts it, and ship the audit-log volume to your log
infrastructure.