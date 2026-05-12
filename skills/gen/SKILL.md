---
name: gen
description: Generate an image with ComfyUI from a text prompt
---

# Generate Image

Generate an image using ComfyUI based on the user's prompt "$ARGUMENTS".

## Steps

1. **Parse the prompt.** Extract any explicit parameters (dimensions, steps, cfg, model name) from the user's request. Reject and ask for clarification only in these specific cases:
   - The prompt is empty or whitespace-only
   - The prompt is a question or meta-request rather than a scene description (e.g., "what can you do?", "how does this work?")
   - The user passed a parameter outside its valid range (steps < 1, cfg < 0, width/height not divisible by 8)

   Otherwise, apply these defaults for the listed parameters (and only these) when not specified:
   - width: 512, height: 512
   - steps: 20
   - cfg: 7.0
   - negative_prompt: "bad quality, blurry"

2. **Select a model.** If the user specified a model name, use it. Otherwise, call `comfyui_list_models` with folder `"checkpoints"`, pick one from the returned `items`, and ask the user to confirm before proceeding (offer to swap if they want a different one).

3. **Generate the image.** Call `comfyui_generate_image` with the parsed parameters and `wait=True` so we block until completion.

4. **Fetch the result.** The response is a dict envelope with keys `status` (expect `"completed"`), `prompt_id`, `outputs`, `elapsed_seconds`, and optionally `warnings`. `outputs` is a list of `{node_id, filename, subfolder}` entries — read the first entry's `filename` and `subfolder` and call `comfyui_get_image` with those. (Tip: pass `preview_format="webp"` and `preview_quality=80` to `comfyui_get_image` for a thumbnail instead of the full PNG — much cheaper context.)

5. **Present the result.** Show the image and a summary of the generation parameters used (prompt, model, dimensions, steps, cfg).

## Notes

- If generation fails, check `comfyui_get_queue` to see if ComfyUI is busy or stuck.
- For img2img, ControlNet, or other advanced workflows, use `/comfy:workflow` instead.
