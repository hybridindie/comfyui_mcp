---
type: reference
title: "Resources & prompts"
description: "The browsable comfyui:// surface and the workflow-recipe prompts."
created: 2026-10-06
updated: 2026-10-06
---

# Resources & prompts

Tools are for acting; resources are for browsing, prompts are for recipes.
All three are first-class MCP components here, all covered by the
`SecurityMiddleware` (rate limiting + entry audit), all with in-process
tests.

## Resources — read-only state by URI

The LLM can read state without spending a tool call:

| URI | Content |
|---|---|
| `comfyui://models/{folder}` | Models in a folder (checkpoints, loras, vae, ...) |
| `comfyui://nodes/installed` | Sorted list of all available node class types from `/object_info` |
| `comfyui://queue` | Current queue state — running and pending job counts |
| `comfyui://system` | Whitelisted system info: ComfyUI version, GPU VRAM, queue counts |
| `comfyui://settings` | ComfyUI server settings read from `GET /settings` |

Templated resources (`comfyui://models/{folder}`) inherit FastMCP 4's
built-in path-traversal screening — and the code anchors the final path
against an allowed root and confirms containment before reading anyway
(screening and containment are complementary layers).

`ReadResource` is also *used* internally: model preflight checks read
`comfyui://models/checkpoints` to fail fast on missing models.

## Prompts — parameterized recipes

Prompt functions return a plain string (auto-wrapped as a user message) or
`list[Message]` for multi-turn — not raw dicts:

| Prompt | Params |
|---|---|
| `txt2img_prompt` | `prompt`, `style="photorealistic"` |
| `img2img_prompt` | `image`, `prompt`, `style="photorealistic"` |
| `inpaint_prompt` | `image`, `mask`, `prompt`, `style="photorealistic"` |
| `upscale_prompt` | `image`, `upscale_model="RealESRGAN_x4plus.pth"` |

The recipes encode the workflow-template shape (model selection, sampler
defaults, sensible negatives) so an agent can follow them without trial and
error.

## Why resources for discovery

A tool call costs context and selection accuracy: every extra tool the LLM
must choose among blurs the ones that matter. Browsable resources keep
discovery out of the tool surface — the model lists stay in schema, and
`search_models`/`list_models` remain for when filtering or pagination is
needed.