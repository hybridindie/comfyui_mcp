---
type: reference
title: "Server capability flags"
description: "The /features keys comfyui_get_server_features exposes, and the run-mode flags worth knowing."
created: 2026-10-06
updated: 2026-11-27
---

# Server capability flags

ComfyUI (v0.38+; verified against v0.46.3) advertises its capabilities at
`GET /features`. The server fetches this once at startup (recorded to the
audit trail) and `comfyui_get_server_features` exposes it to agents.
Meaningful keys:

| Key | Meaning |
|-----|---------|
| `supports_preview_metadata` | Server-rendered preview thumbnails (webp/jpeg) available via `comfyui_get_image(preview_format=...)` |
| `supports_model_type_tags` | Model listings carry type tags |
| `max_upload_size` | Maximum upload payload in **bytes** — enforced locally by `comfyui_upload_image` and `comfyui_upload_media` before the request |
| `node_replacements` | Server exposes a node replacement map (`/node_replacements`) — the inspector warns on submissions containing to-be-replaced nodes |
| `assets` | The SQLite asset catalogue is enabled (`--enable-assets`); output/model trees are indexed server-side |
| `partner_run_gate_enabled` | Upstream gates the local Run button behind sign-in when a graph contains partner (paid) nodes — a second layer beneath the inspector's dangerous-node warnings |
| `partner_node_token` | Local API-node prompts are queued with a renewable partner-node token instead of the workspace token |
| `local_web_sso` | ComfyUI offers browser sign-in (Cloud OAuth + PKCE) on `localhost`/`127.0.0.1`, so the local UI/API has an auth surface |
| `deploy_to_cloud` | This install can deploy workflows to Comfy Cloud — network egress beyond the local box |
| `extension.manager.supports_v4` | ComfyUI-Manager exposes its v4 API |
| `extension.manager.supports_csrf_post` | ComfyUI-Manager 4.2.1+ accepts CSRF-protected POST state mutations (absence means an older manager) |

The same payload also carries frontend flags (`show_signin_button`,
`enable_telemetry`); the server exposes them but does not act on them.

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