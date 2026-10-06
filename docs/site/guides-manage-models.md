---
type: guide
title: "Manage models"
description: "Search, download, and curate models — HF/CivitAI search, the Model-Manager download lifecycle, presets, and metadata."
created: 2026-10-06
updated: 2026-10-06
---

# Manage models

## Find a model

Two discovery paths:

- **What's installed**: browse `comfyui://models/checkpoints` or
  `comfyui_list_models(folder=...)` (paginated). Metadata per file:
  `comfyui_list_models_detailed` (`size`, `modified`, `pathIndex`, ...).
- **What exists upstream**: `comfyui_search_models(query="sdxl lighting",
  source="huggingface"|"civitai")` — returns name, download URL, size, and
  stats. Needs no plugin.

## Download a model

Downloads run in ComfyUI-Model-Manager — the agent queues the download and
polls:

```text
comfyui_download_model(url="https://huggingface.co/.../model.safetensors",
                       folder="checkpoints", filename="my-model.safetensors")
→ { "taskId": "abc123", ... }

comfyui_get_download_tasks()
→ { "tasks": [{ "taskId": "abc123", "status": "running", "progress": 42, ... }] }
```

URLs and extensions are validated before submission (domain allowlist).

### The lifecycle quirks (upstream behavior)

- Completed tasks **stay in the list** as `status: "pause"`,
  `progress: 100`. That is Model-Manager's convention for done. Remove
  finished tasks with `comfyui_cancel_download(task_id=...)`.
- `comfyui_download_model` always sends `previewFile` (empty string is
  fine) — Model-Manager requires the field and silently deletes tasks
  without it. The client handles this; you don't need to.

## Model metadata & previews

- `comfyui_get_model_metadata` — per-file metadata
- `comfyui_get_model_preview` — fetch a model's preview image (base64 +
  mime, or `{"available": false}`); needs the `pathIndex` from
  `comfyui_list_models_detailed`

## Prompting and settings guidance

Instead of guessing sampler settings per model family:

```text
comfyui_get_model_presets(model_family="sdxl")
→ recommended sampler, scheduler, steps, cfg

comfyui_get_prompting_guide(model_family="sdxl")
→ prompt engineering tips + negative-prompt guidance
```

## What needs credentials

`comfyui_search_models` / `comfyui_download_model` work without API keys
for many public models. Keys (config or env) are needed for gated/private
HuggingFace models or auth-only CivitAI access — see
[configuration](./reference-config.md). Keys are redacted from audit logs.

## Custom nodes are a similar flow

Searching/installing/updating *custom nodes* goes through ComfyUI-Manager
(`comfyui_search_custom_nodes` → `comfyui_install_custom_node` → optional
restart + post-install security audit) — see
[the tools reference](./reference-tools.md#custom-node-management).