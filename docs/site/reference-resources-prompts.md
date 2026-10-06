---
type: reference
title: "Resources & prompts"
description: "The comfyui:// resource URIs and the 4 prompt recipes."
created: 2026-10-06
updated: 2026-10-06
---

# Resources & prompts

## Resources

Read-only state the LLM can browse by URI without a tool call. Templated
resources inherit FastMCP 4's built-in path-traversal screening; the code
additionally anchors paths against an allowed root.

| URI | Content |
|-----|---------|
| `comfyui://models/{folder}` | List models in a folder (checkpoints, loras, vae, ...). Path-traversal in `{folder}` is screened. |
| `comfyui://nodes/installed` | Sorted list of all available ComfyUI node class types from `/object_info`. |
| `comfyui://queue` | Current queue state — running and pending job counts. |
| `comfyui://system` | Whitelisted system info: ComfyUI version, GPU VRAM, queue counts. Sensitive fields (hostname, OS, CPU, paths) excluded. |
| `comfyui://settings` | ComfyUI server settings (sampler defaults, UI prefs, feature flags) from `GET /settings`. |

## Prompts

Reusable, parameterized prompt recipes for the built-in workflow templates.
Each returns a plain string the LLM uses as guidance:

| Prompt | Params | Recipe |
|--------|---------|--------|
| `txt2img_prompt` | `prompt`, `style="photorealistic"` | Text-to-image: model selection, sampler defaults, negative-prompt shape |
| `img2img_prompt` | `image`, `prompt`, `style="photorealistic"` | Image-to-image with strength guidance |
| `inpaint_prompt` | `image`, `mask`, `prompt`, `style="photorealistic"` | Masked inpainting flow |
| `upscale_prompt` | `image`, `upscale_model="RealESRGAN_x4plus.pth"` | Model-based upscaling |

Prompt functions may also return `list[Message]` for multi-turn recipes;
these four are single-message strings. See
[architecture: resources & prompts](./architecture/resources-prompts.md) for
why discovery lives here rather than in tools.