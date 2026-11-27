---
type: guide
title: "Generate images"
description: "The generation loop — model discovery, the one-shot generation tools, thumbnails, and when to use each."
created: 2026-10-06
updated: 2026-11-27
---

# Generate images

Seven tools cover generation. `generate_image`, `transform_image`,
`inpaint_image`, `upscale_image`, and `run_workflow` share the uniform envelope
(`status`, `prompt_id`, `outputs`, ...); `generate_batch` returns a variant
list; `run_workflow_stream` returns the raw event stream.

`wait` defaults to **`False`** on the non-streaming tools, so a call without it
returns `status: "submitted"` and a prompt id. Pass `wait=True` to block, or
poll `comfyui_get_progress`.

## The loop

1. **Find a model** — the agent browses or lists:

   ```text
   comfyui_list_models(folder="checkpoints")
   → { "items": [...], "has_more": false }
   ```

   `comfyui_generate_image` and `comfyui_generate_batch` preflight a named
   checkpoint through the models resource — a wrong name fails instantly, no
   `/prompt` round-trip. `transform`/`inpaint` pass `model` straight into the
   workflow and fail at submission instead.

2. **Generate**:

   ```text
   comfyui_generate_image(prompt="a yellow apple, photorealistic, 4k",
                          model="sd_xl_base_1.0.safetensors",
                          width=1024, height=1024,
                          wait=True)
   ```

   Prompting guidance (sampler/step/cfg defaults, negative-prompt shape)
   per model family: `comfyui_get_model_presets` + `comfyui_get_prompting_guide`.

3. **Fetch**:

   ```text
   comfyui_get_image(filename="ComfyUI_00001_.png", subfolder="",
                     preview_format="webp", preview_quality=80)
   ```

## Which generation tool

| Task | Tool |
|---|---|
| Text → image | `comfyui_generate_image` |
| Existing image, restyled | `comfyui_transform_image` (upload first) |
| Fill a masked region | `comfyui_inpaint_image` (upload image + mask) |
| Enlarge/clean up | `comfyui_upscale_image` (model-based, `RealESRGAN_x4plus.pth` default) |
| Several prompt/seed variants | `comfyui_generate_batch` (up to 8; see [Batch generation](guides-batch.md)) |
| Full control over the graph | `comfyui_run_workflow` / `comfyui_run_workflow_stream` |

## Payload sanity: thumbnails

Generated PNGs are multiple MB — fatal for LLM context. Default to
thumbnails for display:

```text
comfyui_get_image(..., preview_format="webp", preview_quality=80)
```

Server-side re-encode → ~90 KB webp. The tool default is the full image, so
pass `preview_format` explicitly. Fetch full-quality only when the user
actually wants the file. Thumbnails need server support
(`supports_preview_metadata` on [`/features`](reference-server-features.md)).

## Uploads first, then transform/inpaint

`transform`/`inpaint` reference previously-uploaded files:

```text
comfyui_upload_image(filename="photo.png", image_data="<base64>",
                     destination="input")
comfyui_transform_image(image="photo.png",
                        prompt="turn it into an oil painting",
                        strength=0.6, wait=True)
```

Uploads are sanitized (traversal, extension allowlist) and size-checked
against the server's `max_upload_size` — an oversized payload is rejected
locally with the byte budget named, before any HTTP.

## Long waits

- `wait=True` blocks the tool call (bounded by the timeout config)
- `wait=False` (the default) returns immediately; poll
  `comfyui_get_progress(prompt_id)`
- Streaming: `comfyui_run_workflow_stream` returns the raw event stream
- Multi-client HTTP deployments: enable [background tasks](./architecture/tasks.md)
  and take a task handle