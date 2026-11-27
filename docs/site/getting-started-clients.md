---
type: guide
title: "Add to your MCP client"
description: "Connect the server to OpenCode, Claude Desktop, Cursor, Docker, or any MCP client — stdio or Streamable HTTP with bearer auth."
created: 2026-10-06
updated: 2026-11-27
---

# Add to your MCP client

The server communicates over stdio by default. Add one of the following
configurations to your MCP client (OpenCode, Claude Desktop, Cursor, or any
stdio MCP client) depending on how you installed.

## From PyPI / pipx / uv tool install

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "comfyui-mcp-secure"
    }
  }
}
```

## From PyPI without a persistent install (uvx)

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "uvx",
      "args": ["comfyui-mcp-secure"]
    }
  }
}
```

## From source (uv)

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "uv",
      "args": ["--directory", "/path/to/comfyui_mcp", "run", "comfyui-mcp-secure"]
    }
  }
}
```

## Docker (GitHub Container Registry)

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

> [!NOTE]
> `host.docker.internal` routes to your host machine from inside Docker. If
> ComfyUI runs on a remote server, replace it with that server's URL. On
> Linux, add `--add-host=host.docker.internal:host-gateway`.

## Streamable HTTP (remote, with bearer auth)

The HTTP transport is enabled in config (`transport.remote.enabled: true`) and
should have auth enabled whenever it is reachable beyond loopback:

```yaml
transport:
  remote:
    enabled: true
    host: "127.0.0.1"     # 0.0.0.0 requires auth (or an explicit override)
    port: 8080
    auth:
      enabled: true
      tokens:
        operator: COMFYUI_MCP_HTTP_TOKEN
```

```bash
export COMFYUI_MCP_HTTP_TOKEN=$(openssl rand -hex 32)
```

The token is read from the named environment variable at startup; the config
never contains it. A non-loopback bind without auth is refused, and startup
fails closed if auth is enabled but the variable is unset.

### Claude Code

```bash
claude mcp add --transport http comfyui \
  http://127.0.0.1:8080/mcp \
  --header "Authorization: Bearer $COMFYUI_MCP_HTTP_TOKEN"
```

### Claude Desktop

Recent versions accept remote servers in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "comfyui": {
      "url": "http://127.0.0.1:8080/mcp",
      "headers": {
        "Authorization": "Bearer <paste-token-here>"
      }
    }
  }
}
```

> [!NOTE]
> Claude Desktop does not expand environment variables in every version.
> Keep the file readable only by you (`chmod 600`) if you paste the token, or
> point the client at a local proxy that injects the header.

### Cursor

`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project):

```json
{
  "mcpServers": {
    "comfyui": {
      "url": "http://127.0.0.1:8080/mcp",
      "headers": {
        "Authorization": "Bearer ${env:COMFYUI_MCP_HTTP_TOKEN}"
      }
    }
  }
}
```

### OpenCode

Project `.opencode/opencode.json` (the shape this repo uses):

```json
{
  "mcp": {
    "comfyui": {
      "type": "remote",
      "url": "http://127.0.0.1:8080/mcp",
      "headers": {
        "Authorization": "Bearer {env:COMFYUI_MCP_HTTP_TOKEN}"
      },
      "enabled": true
    }
  }
}
```

OpenCode 2 nests servers under `mcp.servers` and uses `"disabled": false`
instead of `"enabled": true`.

### Any other HTTP client

Send `Authorization: Bearer <token>` on every request to
`http://<host>:<port>/mcp`. A missing or invalid token returns **401**; the
identity label from `transport.remote.auth.tokens` appears in the audit log and
scopes the client's rate-limit bucket.

For TLS and OIDC, terminate at a reverse proxy and forward to the plain HTTP
listener on loopback.

## What the client sees

On connect, the client discovers 55 tools, 7 resources
(`comfyui://models/{folder}`, `comfyui://nodes/installed`,
`comfyui://queue`, `comfyui://jobs`, `comfyui://outputs`,
`comfyui://system`, `comfyui://settings`), and 4 prompt recipes. Tool descriptions are written for agents — what the tool does, when
to use it, and what shape comes back.

## Optional: OpenCode skills for this repo's development

This repository ships its own agent configuration under `.opencode/` and
`.claude/` for developing the server itself — path-scoped rules, a pre-PR
review subagent, and `skills/` recipes (`gen`, `workflow`, `status`, `models`, ...) that wrap
common multi-tool flows. These are for contributing to comfyui_mcp, not
required for *using* the server — any MCP client gets the full tool surface.
