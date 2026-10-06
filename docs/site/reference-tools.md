---
type: reference
title: "Tools"
description: "All 53 comfyui_* tools, grouped by module, with parameters and return shapes."
created: 2026-10-06
updated: 2026-10-06
---

# Tools

All 53 tools. Generation/workflow/job tools return a uniform envelope
(`status`, `prompt_id`, `outputs`, ...) — see the
[workflow pipeline](./architecture/workflow-pipeline.md). List tools return
the pagination envelope `{items, total, offset, limit, has_more}`.

## Generation & workflows

| Tool | Description |
|------|-------------|
| `comfyui_generate_image` | Text-to-image using a built-in workflow. Params: prompt, negative_prompt, width, height, steps, cfg, model. Set `wait=True` to block until complete and return outputs. Preflights the named model and fails fast (no `/prompt` round-trip) when absent. |
| `comfyui_transform_image` | Image-to-image transformation. Params: image (filename), prompt, negative_prompt, strength (0.0–1.0), steps, cfg, model. Input must be uploaded via `comfyui_upload_image` first. |
| `comfyui_inpaint_image` | Inpaint masked regions of an image. Params: image, mask (filenames), prompt, negative_prompt, strength, steps, cfg, model. Both files must be uploaded first. |
| `comfyui_upscale_image` | Upscale an image using a model-based upscaler. Params: image (filename), upscale_model (default: `RealESRGAN_x4plus.pth`). |
| `comfyui_run_workflow` | Submit arbitrary ComfyUI workflow JSON. Inspected for dangerous nodes before execution. Set `wait=True` to block until complete. `partial_execution_targets` (optional node-ID list) re-runs just those nodes, serving the rest from the server's execution cache. |
| `comfyui_run_workflow_stream` | Submit workflow JSON and capture ComfyUI websocket stream events (`progress`, `executing`, `executed`, ...) until terminal status, returning events plus final outputs/status. Also accepts `partial_execution_targets`. |
| `comfyui_summarize_workflow` | Summarize a workflow's structure, data flow, models, and parameters. `output_format="text"` (default) or `"mermaid"` for diagram markup. |
| `comfyui_create_workflow` | Create a workflow from 14 built-in templates: txt2img/img2img/upscale/inpaint, txt2vid_animatediff/txt2vid_wan, controlnet_canny/depth/openpose, ip_adapter, lora_stack, face_restore, flux_txt2img, sdxl_txt2img. |
| `comfyui_modify_workflow` | Apply batch operations (`add_node`, `remove_node`, `set_input`, `connect`, `disconnect`) to a workflow. |
| `comfyui_analyze_workflow` | Structured analysis as a dict (`node_count`, `class_types`, `flow`, `models`, `parameters`, `pipeline`, `prompt_nodes`, `negative_nodes`). Read `pipeline` programmatically; use `summarize_workflow` for human/Mermaid rendering. |
| `comfyui_validate_workflow` | Validate structure, server compatibility, security, and loop integrity (paired Start/End Loops, no escapes, no accumulate-from-body — mirrors upstream Core Loops validation). |

## Job management

| Tool | Description |
|------|-------------|
| `comfyui_get_queue` | Current execution queue state. |
| `comfyui_list_jobs` | List jobs across queue + history with status filter, sorting, pagination. |
| `comfyui_get_job` | Look up a single job (queued/running/finished) by `prompt_id`. |
| `comfyui_cancel_job` | Cancel a running or queued job. Uses the native `/api/jobs/{id}/cancel` endpoint, falls back to the legacy `/queue` delete on 404 (older ComfyUI). |
| `comfyui_cancel_jobs` | Batch-cancel one or more jobs by `prompt_id` via `/api/jobs/cancel`. |
| `comfyui_interrupt` | Interrupt the running workflow (global, or targeted via optional `prompt_id`). |
| `comfyui_get_queue_status` | Detailed queue status including running and pending prompts. |
| `comfyui_clear_queue` | Clear pending and/or running items from the queue. |
| `comfyui_get_progress` | Execution progress by `prompt_id`: status, queue position, outputs. |

## Discovery

| Tool | Description |
|------|-------------|
| `comfyui_list_models` | List available models by folder (checkpoints, loras, vae, ...). |
| `comfyui_list_models_detailed` | List models with file metadata (name, `pathIndex`, `modified`, `created`, `size`) from `/experiment/models/{folder}`. Provides the `pathIndex` for preview lookups. |
| `comfyui_get_model_preview` | Fetch a model's preview image. Returns base64 data + mime type, or `{"available": false}` on 404. |
| `comfyui_list_nodes` | List all available node types. |
| `comfyui_get_node_info` | Detailed info for a specific node type. |
| `comfyui_list_workflows` | List saved workflow templates. |
| `comfyui_list_extensions` | List available ComfyUI extensions. |
| `comfyui_get_server_features` | Server features from `/features` — see [capability flags](reference-server-features.md). |
| `comfyui_list_model_folders` | List available model folder types. |
| `comfyui_get_model_metadata` | Metadata for a specific model file. |
| `comfyui_audit_dangerous_nodes` | Scan all installed nodes; returns dangerous/suspicious ones with reasons. The input to building your allowlist/dangerous list. |
| `comfyui_list_subgraphs` | List reusable subgraph templates from `/global_subgraphs`. |
| `comfyui_get_subgraph` | Fetch one subgraph's JSON (node map) for inspection or insertion. |
| `comfyui_get_system_info` | Sanitized GPU VRAM, queue depth, ComfyUI version (whitelist-filtered from `/system_stats`). |
| `comfyui_get_settings` | Read ComfyUI server settings (sampler defaults, UI prefs, feature flags). |
| `comfyui_update_settings` | Merge new settings into the server config via `POST /settings` (audit-logged; mutating). |

## Custom node management

> Requires ComfyUI-Manager on the target server; without it these tools
> return a helpful error.

| Tool | Description |
|------|-------------|
| `comfyui_search_custom_nodes` | Search the ComfyUI Manager registry by name/description/author. |
| `comfyui_install_custom_node` | Queue install for a custom node pack by `node_id`; optional restart and post-install security audit. |
| `comfyui_uninstall_custom_node` | Queue uninstall by `node_id`; optional restart. |
| `comfyui_update_custom_node` | Queue update by `node_id`; optional restart and post-update security audit. |
| `comfyui_get_custom_node_status` | Custom node queue status (pending/running/completed). |

## History

| Tool | Description |
|------|-------------|
| `comfyui_get_history` | Browse execution history (read-only). Server-side paging via `limit` (1–100, default 25) and `offset`. Returns `{items, count, offset, limit, has_more, total}`; `total` is only set on the last page (upstream exposes no count). |

## Model search & download

> Requires [ComfyUI-Model-Manager](https://github.com/hayden-cn/ComfyUI-Model-Manager)
> for download tools (lazy-detected — helpful error if missing).
> `comfyui_search_models` works without it.

| Tool | Description |
|------|-------------|
| `comfyui_search_models` | Search HuggingFace or CivitAI for models. Returns name, download URL, size, stats. |
| `comfyui_download_model` | Download a model via ComfyUI-Model-Manager. URL domain and extension validated. |
| `comfyui_get_download_tasks` | Check status of active model downloads (progress, speed, status). |
| `comfyui_cancel_download` | Cancel or clean up a model download task. Doubles as cleanup: completed tasks stay as `status: "pause", progress: 100` upstream. |
| `comfyui_get_model_presets` | Recommended sampler/scheduler/steps/CFG defaults for a model family. |
| `comfyui_get_prompting_guide` | Model-family prompt engineering tips and negative-prompt guidance. |

## File operations

| Tool | Description |
|------|-------------|
| `comfyui_upload_image` | Upload a base64 image. Path-sanitized; size enforced against server `max_upload_size`. Params: filename, image_data, subfolder, `destination="input"\|"output"\|"temp"` (default input), `overwrite` (default False — ComfyUI auto-renames duplicates). |
| `comfyui_get_image` | Download a generated image. `response_format="data_uri"` (default) returns inline base64 — **raster `image/*` allow-listed** (SVG/unknown/missing content types rejected); `response_format="url"` returns a direct `/view` URL. Optional `preview_format="webp"\|"jpeg"` + `preview_quality=1-100` for server-rendered thumbnails. Optional `base_url_override`. Path-sanitized. |
| `comfyui_list_outputs` | List generated output filenames from history. |
| `comfyui_upload_mask` | Upload a mask image. Path-sanitized. Params: filename, mask_data, original_image, subfolder, original_subfolder, `destination`, `overwrite`. |
| `comfyui_get_workflow_from_image` | Extract embedded workflow and prompt metadata from a ComfyUI-generated PNG. |