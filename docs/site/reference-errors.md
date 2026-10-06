---
type: reference
title: "Errors & recovery"
description: "The failure shapes tools return and how to recover from each."
created: 2026-10-06
updated: 2026-10-06
---

# Errors & recovery

Structured errors, not tracebacks: the server masks internal exception
details (`mask_error_details=true`), so clients see either a controlled
message or a structured result. The failure shapes agents encounter:

## The wait-envelope statuses

generation/workflow tools return `status`, and each value means something
different:

| Status | Meaning | Recovery |
|---|---|---|
| `submitted` | Accepted by ComfyUI; you didn't wait | Poll `comfyui_get_progress(prompt_id)` |
| `completed` | Finished; `outputs` populated | Fetch via `comfyui_get_image` |
| `interrupted` | Cancelled or interrupted (incl. targeted interrupt) | Inspect, fix, resubmit — `prompt_id` remains valid for history |
| `error` | ComfyUI failed the job (bad node, OOM, ...) | Read `outputs`/error fields; `comfyui_get_job(prompt_id)` for detail |
| `timeout` | Wait budget exhausted; job may still run | Check `comfyui_get_job`; interrupt if unwanted |

## Validation failures

`comfyui_validate_workflow` returns non-blocking `warnings` and blocking
`errors`. The loop-integrity conditions mirror upstream: a
`loop_end_without_start` error means an orphaned EndLoop; `loop_escape`
means a connection crosses a loop boundary. Both are fixed by restructuring
the loop pair — `comfyui_list_subgraphs` + `comfyui_get_subgraph` can fetch
known-good loop patterns.

## Security-shaped failures

| Signal | Where | Meaning | Recovery |
|---|---|---|---|
| `warnings` array with `dangerous_node` | workflow/generation tools | Inspector flagged node types | Audit mode: proceed informed. Enforce mode: you'll be asked to confirm |
| `WorkflowBlockedError` | generation tools | Enforce-mode decline or unapproved node | Add the node to `allowed_nodes` if legitimate, or use different nodes |
| `upload_rejected` audit record | audit log | Sanitizer/size rejection | Fix filename/extension/size; see the message fields |
| content-type rejection | `comfyui_get_image` | Non-raster content (SVG/HTML/unknown) refused | Use `response_format="url"` for such content — no inline render |

## Missing infrastructure

| Signal | Meaning | Recovery |
|---|---|---|
| Model-Manager tools error | ComfyUI-Model-Manager not installed | Install the plugin, or use `comfyui_search_models` (no plugin needed) |
| Node-management tools error | ComfyUI-Manager not installed | Install ComfyUI-Manager |
| Model-not-found preflight error | `comfyui_generate_image` named model absent | `comfyui_list_models(folder="checkpoints")` for real names |
| HTTP 413 on upload | Exceeded server `max_upload_size` (now rejected locally with the byte budget) | Downscale or compress the image |

## Connection failures

The client retries connection errors 3× with backoff; genuine failures
surface as connection errors to the caller. Check in order:

1. `COMFYUI_URL` / `comfyui.url` actually points at the right host:port
2. ComfyUI is up: `curl http://127.0.0.1:8188/system_stats` (from the
   server's host)
3. TLS: for remote hosts with self-signed certs, decide *deliberately* —
   `tls_verify: false` is a config choice, not a fix