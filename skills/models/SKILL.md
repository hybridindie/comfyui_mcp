---
description: List available ComfyUI models, optionally filtered by type
---

# List Models

List models available in ComfyUI. Filter type: "$ARGUMENTS".

Call `comfyui_list_models` with the folder argument. If "$ARGUMENTS" is provided, use it as the folder type (e.g., "checkpoints", "loras", "vae", "controlnet", "upscale_models"). If no argument is given, default to `"checkpoints"`.

The response is a pagination envelope `{items, total, offset, limit, has_more}` — iterate `result["items"]` for the model filenames. Format them as a clean list. If `has_more` is true, mention that there are additional results and the user can request a higher `limit` (max 100) or pass `offset` for the next page.

To see all available model folder types, call `comfyui_list_model_folders` and iterate its `items` the same way.
