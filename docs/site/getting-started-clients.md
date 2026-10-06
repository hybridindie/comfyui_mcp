---
type: guide
title: "Add to your MCP client"
description: "Connect the server to OpenCode, Claude Desktop, Cursor, Docker, or any stdio MCP client."
created: 2026-10-06
updated: 2026-10-06
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

## Streamable HTTP (remote)

If you enabled the remote transport in config, point HTTP-capable clients at
it instead of spawning a process:

```json
{
  "mcpServers": {
    "comfyui": {
      "url": "http://127.0.0.1:8080/mcp"
    }
  }
}
```

## What the client sees

On connect, the client discovers 53 tools, 5 resources
(`comfyui://models/{folder}`, `comfyui://nodes/installed`,
`comfyui://queue`, `comfyui://system`, `comfyui://settings`), and 4 prompt
recipes. Tool descriptions are written for agents — what the tool does, when
to use it, and what shape comes back.

## Optional: OpenCode skills for this repo's development

This repository ships its own agent configuration under `.opencode/` for
developing the server itself — path-scoped rules, a pre-PR review subagent,
and `skills/` recipes (`gen`, `workflow`, `status`, `models`, ...) that wrap
common multi-tool flows. These are for contributing to comfyui_mcp, not
required for *using* the server — any MCP client gets the full tool surface.