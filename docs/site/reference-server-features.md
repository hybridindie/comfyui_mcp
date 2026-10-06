---
type: reference
title: "Server capability flags"
description: "The /features keys comfyui_get_server_features exposes, and the run-mode flags worth knowing."
created: 2026-10-06
updated: 2026-10-06
---

# Server capability flags

ComfyUI (v0.38+) advertises its capabilities at `GET /features`. The server
fetches this once at startup (recorded to the audit trail) and
`comfyui_get_server_features` exposes it to agents. Meaningful keys:

| Key | Meaning |
|-----|---------|
| `supports_preview_metadata` | Server-rendered preview thumbnails (webp/jpeg) available via `comfyui_get_image(preview_format=...)` |
| `supports_model_type_tags` | Model listings carry type tags |
| `max_upload_size` | Maximum upload payload in **bytes** — enforced locally by `comfyui_upload_image` before the request |
| `node_replacements` | Server exposes a node replacement map (`/node_replacements`) — the inspector warns on submissions containing to-be-replaced nodes |
| `assets` | The SQLite asset catalogue is enabled (`--enable-assets`); output/model trees are indexed server-side |
| `extension.manager.supports_v4` | ComfyUI-Manager exposes its v4 API |

Older servers may omit keys — always treat every flag as optional.

## ComfyUI run-mode flags worth knowing

Upstream ComfyUI (v0.38+) has two flags relevant to agent deployments:

- `--offline` — no outbound calls at all
- `--disable-partner-nodes` — deprecates `--disable-api-nodes`; gates
  third-party API nodes (BFL/Ideogram/HeyGen and friends — the same nodes
  the [dangerous list](./security-audit-mode.md) flags as money-spenders)

## Why the server records them at startup

Runs against capability-differing ComfyUI servers produce confusing
behavior differences (previews work here, not there; uploads capped here,
not there). The startup audit snapshot makes "what did the server claim at
session start?" answerable from `~/.comfyui-mcp/audit.log` — see
[the audit log](./security-audit-log.md).