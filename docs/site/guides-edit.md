---
type: guide
title: "Edit images"
description: "Restyle an image, replace a region, or upscale it — by talking to your assistant."
created: 2026-11-27
updated: 2026-11-27
---

# Edit images

Editing uses one of three tools. You describe the result; the assistant picks
the mode and the parameters.

| You want… | Mode | Tool |
|---|---|---|
| The whole image restyled or changed | img2img | `comfyui_transform_image` |
| One region replaced or repaired | inpaint | `comfyui_inpaint_image` |
| A larger, cleaner copy | upscale | `comfyui_upscale_image` |

## Before you start

The input must be in ComfyUI's **input** folder. Two ways:

- The assistant uploads it with `comfyui_upload_image` if it can read the file
  (some clients hand it a path to your attachment).
- You upload it in the ComfyUI UI (or a previous run already put it there), and
  tell the assistant the filename.

For **inpaint**, also upload a mask: white means "regenerate this", black means
"keep". The mask must match the image's dimensions.

## Example: restyle a photo

> Turn `portrait.png` into an oil painting, but keep it recognisable.

The assistant calls:

```text
comfyui_transform_image(image="portrait.png",
                        prompt="oil painting, visible brush strokes, keep the face",
                        negative_prompt="photo, blurry, deformed",
                        strength=0.55, steps=24, cfg=7.0, wait=True)
```

`strength` is the main dial:

| Strength | Effect |
|---|---|
| 0.30–0.45 | Subtle grade, lighting, or cleanup |
| 0.45–0.65 | Balanced restyle (a good default) |
| 0.65–0.85 | Large change; the original composition may move |

The tool default is 0.75 — strong. Ask for a lower value when the subject must
stay recognizable.

## Example: remove something

> Remove the lamp post from the left side of `street.png`.

The assistant makes or uploads a mask where the lamp post is white, then:

```text
comfyui_inpaint_image(image="street.png", mask="street-mask.png",
                      prompt="empty pavement, overcast light",
                      strength=0.8, wait=True)
```

Inpaint works best when the mask is a little larger than the object and the
prompt describes what should replace it, not what to remove.

## Example: upscale

> Make `result.png` twice as sharp.

```text
comfyui_list_models(folder="upscale_models")
comfyui_upscale_image(image="result.png",
                      upscale_model="RealESRGAN_x4plus.pth", wait=True)
```

The scale factor belongs to the model (RealESRGAN_x4plus is 4x); do not promise
an exact size without checking the model's factor.

## Fetch the result

The assistant reads the output filename from the response and fetches a
preview:

```text
comfyui_get_image(filename="ComfyUI_00007_.png", subfolder="",
                  preview_format="webp", preview_quality=80)
```

Ask for the full-size file only when you need to download it.

## Notes

- If the model is missing, ask for `comfyui_list_models(folder="checkpoints")`
  and use an exact filename.
- Warnings about dangerous nodes mean the workflow touched code/network nodes;
  in enforce mode you are asked to approve before it runs.
- Video/audio results are not images — ask for `comfyui_get_output` instead.
- The assistant can follow the [`edit` skill](reference-skills.md) for the same
  procedure with its decision rules.
