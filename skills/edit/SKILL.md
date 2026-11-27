---
name: edit
description: Edit an image with ComfyUI — img2img, inpaint, or upscale
---

# Edit an image

The user wants to edit an existing image. Request: "$ARGUMENTS".

Pick one mode first; do not run several unless asked:

| Goal | Tool |
|---|---|
| Change style, lighting, or detail across the whole image | `comfyui_transform_image` (img2img) |
| Replace or repair a selected region | `comfyui_inpaint_image` |
| Enlarge without changing content | `comfyui_upscale_image` |

## Steps

1. **Find the input.** If the image is already in ComfyUI's input folder (the user named the file, or it was uploaded earlier), use that filename. Otherwise:
   - If the client gave you a readable local path, base64-encode the file and call `comfyui_upload_image` with `filename`, `image_data`, and `destination="input"`.
   - If you cannot read the file, ask the user to upload it and tell you the filename. MCP has no attachment path of its own.
   For inpaint, also upload the mask with `comfyui_upload_mask`; the mask must match the image dimensions, white = regenerate, black = keep.

2. **Choose parameters.**
   - `strength` (img2img/inpaint): 0.30–0.45 subtle, 0.45–0.65 balanced (the default 0.75 is strong), 0.65–0.85 a large change.
   - `steps` 20–30, `cfg` 6–8; keep the source dimensions.
   - `model`: leave empty for the server default, or pass an exact filename from `comfyui_list_models(folder="checkpoints")`.
   - Upscale: pick a model from `comfyui_list_models(folder="upscale_models")`; the scale factor belongs to the model (RealESRGAN_x4plus = 4x).

3. **Run it** with `wait=True`. In enforce mode, relay any `warnings` and wait for confirmation before submitting.

4. **Fetch the result** from `outputs[0]` with `comfyui_get_image(filename=..., subfolder=..., preview_format="webp", preview_quality=80)` — the thumbnail is far cheaper context than the full PNG.

5. **Report** the mode, strength/model used, and the output filename.

## Notes

- For a new scene rather than an edit, use `/comfy:gen`.
- Never guess model filenames; `comfyui_list_models` shows what the server actually has.
- Do not upscale a mask, and do not use upscale as a substitute for inpainting.
