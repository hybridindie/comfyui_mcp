---
type: guide
title: "Install the server"
description: "Install from PyPI, from source, or run the Docker image."
created: 2026-10-06
updated: 2026-10-06
---

# Install the server

## Option A: from PyPI

```bash
pip install comfyui-mcp-secure
```

For an isolated CLI install:

```bash
uv tool install comfyui-mcp-secure
# or
pipx install comfyui-mcp-secure
```

For a one-shot run without installing:

```bash
uvx comfyui-mcp-secure --help
```

## Option B: from source

```bash
git clone https://github.com/hybridindie/comfyui_mcp.git
cd comfyui_mcp
uv sync
```

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). Run with
`uv run comfyui-mcp-secure` from the repo root.

## Option C: Docker

```bash
docker pull ghcr.io/hybridindie/comfyui_mcp:latest
```

The image runs as a non-root user and speaks stdio — see
[Docker deployment](./guides-docker.md) for full usage including compose and
config mounting.

## Verify the install

```bash
uvx comfyui-mcp-secure --help
```

or, from source:

```bash
uv run comfyui-mcp-secure --help
```

Next: [configure the server](./getting-started-configure.md) to point at your
ComfyUI instance.