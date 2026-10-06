---
type: reference
title: "Client & transport"
description: "The centralized ComfyUI client — request plumbing, envelope unwrapping, progress tracking, blocked endpoints."
created: 2026-10-06
updated: 2026-10-06
---

# Client & transport

Tools never talk to ComfyUI directly. `ComfyUIClient` (`client.py`) owns
every HTTP interaction — the single place that knows about URLs, headers,
retries, and response envelope quirks.

## Request plumbing

- `self._request(method, path, ...)` is the funnel: it handles retries on
  connection errors with backoff (3 by default); HTTP 4xx/5xx raise
  immediately rather than retrying
- TLS verification and connect/read timeouts are configurable in config +
  env overrides
- Endpoint access is centralized *and negative-selected*: `/userdata`,
  `/free`, `/users`, and `/history` POST have no methods at all — enforced
  by `tests/test_blocked_endpoints.py`. See
  [blocked endpoints](../security-blocked-endpoints.md)

## Envelope unwrapping

[ComfyUI-Model-Manager](https://github.com/hayden-cn/ComfyUI-Model-Manager)
wraps responses in `{"success": bool, "data": <payload>}`;
`_unwrap_model_manager_response()` normalizes this at the boundary so tools
see bare payloads. Known upstream quirks are handled in the client:

- `previewFile` must always accompany a model save (empty string is fine) —
  omitting it causes the task to be silently deleted
- completed download tasks stay as `status: "pause"`, `progress: 100` —
  removal is via the cancel endpoint

## Progress tracking

`progress.py` gives real-time execution state with a fallback story:

1. **WebSocket** — on-demand connection to ComfyUI's `/ws`, filtered
   per-prompt (ignores events from concurrent jobs), TLS passthrough for
   secure hosts
2. **HTTP polling fallback** — if the WebSocket fails, poll until a
   terminal status (`completed`, `error`, `interrupted`)

On top of that, generation tools report step/total through MCP progress
notifications (`ctx.report_progress`) so connected clients get live
updates without polling.

## System stats, whitelist-filtered

`get_system_stats()` may call `/system_stats` — but its **only** permitted
caller is the `comfyui_get_system_info` tool, which passes the response
through a strict whitelist (ComfyUI version, GPU VRAM, queue counts) and
never returns raw fields (hostname, OS, CPU, paths are dropped). Both the
single-caller rule and the whitelist are test-pinned.