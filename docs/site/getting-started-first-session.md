---
type: walkthrough
title: "First session"
description: "A complete end-to-end first session: list models, generate, fetch the result — with what the server does at each step."
created: 2026-10-06
updated: 2026-10-06
---

# First session

Everything below is what the **agent** does — you prompt in plain language
and the calls are listed so you can follow along in your MCP client's tool
trace.

## 1. Ask for an image

> Generate a yellow apple, photorealistic, 4k

## 2. The agent discovers what's available

The agent first browses or lists models rather than guessing a filename:

```text
> comfyui_list_models(folder="checkpoints")

{ "items": [{ "filename": "sd_xl_base_1.0.safetensors", ... }, ...],
  "total": 2, "offset": 0, "limit": 50, "has_more": false }
```

## 3. The agent generates

```text
> comfyui_generate_image(prompt="a yellow apple, photorealistic, 4k",
                         model="sd_xl_base_1.0.safetensors",
                         width=1024, height=1024, steps=20, cfg=7.0,
                         wait=True)

{ "status": "completed", "prompt_id": "b0f6...e21",
  "outputs": [{ "node_id": "9", "filename": "ComfyUI_00001_.png",
                "subfolder": "" }],
  "elapsed_seconds": 14.2, "step": 20, "total_steps": 20 }
```

`wait=True` makes the call block until the job finishes (the client can also
poll with `comfyui_get_progress` instead, or take a task handle over the
HTTP transport when background tasks are enabled).

**What the server did silently:** inspected the generated workflow (a clean
built-in template → no warnings), rate-limited the call under the
generation bucket, and wrote two audit records (`called` from the
middleware, `submitted` → `completed` from the tool).

## 4. The agent fetches the image

```text
> comfyui_get_image(filename="ComfyUI_00001_.png", subfolder="",
                    preview_format="webp", preview_quality=80)

{ "data_uri": "data:image/webp;base64,UklGR...", "content_type": "image/webp" }
```

The thumbnail is ~90 KB instead of multiple MB — the LLM displays it inline
without eating the context window. `response_format="url"` returns a direct
`/view` link instead. Either way, the server has already verified the
content type is a raster image and the filename passed the sanitizer.

## 5. The audit trail

```bash
tail -2 ~/.comfyui-mcp/audit.log
```

One JSON line per call, secrets redacted — this is the record you'll grep
when you ask "what did the agent actually run?"

## When something is flagged

In audit mode, a workflow containing, say, an `ExecutePython` node returns
`status: "completed"`-shaped results with a `warnings` array naming the
node, and the audit log carries the same warnings. The expected agent
behavior is to tell you and ask before proceeding.

In enforce mode the difference is visible to *you* directly: the MCP client
prompts for confirmation ("allow workflow with warnings?") and a decline
blocks the submission — no ComfyUI call happens. See
[enforce mode & elicitation](./security-enforce-mode.md).

## Where to go next

- [Generate images](./guides-generate.md) — params, thumbnails, upscaling, inpainting
- [Custom workflows](./guides-custom-workflows.md) — templates, batch modification, validation
- [Manage models](./guides-manage-models.md) — search, download, presets, prompting guidance