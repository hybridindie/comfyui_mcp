---
name: models
description: List available ComfyUI models, optionally filtered by type
---

# List Models

List models available in ComfyUI. Filter type: "$ARGUMENTS".

1. **Determine the folder type.**
   - If "$ARGUMENTS" is provided, use it as the folder type. Common values: `"checkpoints"`, `"loras"`, `"vae"`, `"controlnet"`, `"upscale_models"`.
   - If "$ARGUMENTS" is not provided, default to `"checkpoints"`.
   - If step 2 fails because the folder type is invalid, recover by:
     1. Printing `"Invalid folder type. Valid options:"`
     2. Calling `comfyui_list_model_folders` and listing its `items` as the valid options
     3. Asking the user to retry with one of those

2. **Call `comfyui_list_models`** with the determined folder type.

3. **Process the response.** The response is a pagination envelope `{items, total, offset, limit, has_more}` — iterate `result["items"]` for the model filenames. Format them as a clean list. If `has_more` is true, mention that there are additional results and the user can request a higher `limit` (max 100) or pass `offset` for the next page.
