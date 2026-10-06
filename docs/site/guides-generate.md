---
type: guide
title: "Generate images"
description: "The generation loop — model discovery, the five generation tools, thumbnails, and when to use each."
created: 2026-10-06
updated: 2026-10-06
---

# Generate images

Five tools cover generation. All accept `wait=True` to block until done;
all return the uniform envelope (`status`, `prompt_id`, `outputs`, ...).

## The loop

1. **Find a model** — the agent browses or lists:

   ```text
   comfyui_list_models(folder="checkpoints")
   → { "items": [...], "has_more": false }
   ```

   Model names passed to generation are preflighted — a wrong name fails
   instantly, no `/prompt` round-trip.

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
| Full control over the graph | `comfyui_run_workflow` / `comfyui_run_workflow_stream` |

## Payload sanity: thumbnails

Generated PNGs are multiple MB — fatal for LLM context. Default to
thumbnails for display:

```text
comfyui_get_image(..., preview_format="webp", preview_quality=80)
```

Server-side re-encode → ~90 KB webp. Fetch full-quality only when the user
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
- `wait=False` returns immediately; poll `comfyui_get_progress(prompt_id)`
- Streaming: `comfyui_run_workflow_stream` returns the raw event stream
- Multi-client HTTP deployments: enable [background tasks](./architecture/tasks.md)
  and take a task handle