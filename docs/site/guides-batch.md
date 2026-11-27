---
type: guide
title: "Batch generation"
description: "Generate a prompt or seed matrix without flooding the queue — one bounded call per wave."
created: 2026-11-27
updated: 2026-11-27
---

# Batch generation

Use a batch when you want several variants of the same idea: different seeds,
different prompts, or both.

## The shape of a batch

- **Prompts × seeds.** Two prompts with two seeds is four variants.
- **One seed per prompt.** If you give no seeds, each prompt gets one random
  seed and the seed is reported back.
- **Eight variants per call.** `comfyui_generate_batch` caps a batch at 8; for
  more, send another batch after the first finishes.

## Example: four seeds of one prompt

> Give me four different takes on "a lighthouse at dawn, oil painting".

```text
comfyui_generate_batch(prompts=["a lighthouse at dawn, oil painting"],
                       seeds=[101, 102, 103, 104],
                       width=1024, height=1024, steps=24, cfg=7.0)
```

It returns:

```json
{
  "status": "submitted",
  "count": 4,
  "variants": [
    {"prompt": "...", "seed": 101, "prompt_id": "...", "status": "submitted"},
    ...
  ],
  "errors": []
}
```

## Example: two prompts, two seeds

```text
comfyui_generate_batch(
  prompts=["a cabin in snow, watercolour", "a cabin in snow, photograph"],
  seeds=[7, 8],
  width=1024, height=1024
)
```

Four variants. Keep one model and one resolution for the whole batch — mixed
settings make the comparison meaningless.

## Collect the results

Batch submission is asynchronous. Poll each prompt id:

```text
comfyui_get_progress(prompt_id="...")
comfyui_get_job(prompt_id="...")        # error detail if one failed
comfyui_list_jobs(status=["completed"]) # the wider queue/history
```

Then fetch the files:

```text
comfyui_get_image(filename=..., subfolder=..., preview_format="webp")
```

A failed variant does not lose the batch: `status` is `partial`, the successful
`variants` keep their prompt ids, and `errors` names the prompt/seed that
failed. A workflow blocked by enforce mode stops the rest of the batch rather
than prompting for every remaining variant.

## Rate limits and GPU time

The server's generation bucket is 10 requests/minute, and a whole batch counts
as **one** call. Wait for a wave to finish before sending the next one; a
20-image matrix is two waves, not twenty separate calls.

Warn the user before a long batch — a 1024×1024 24-step run is minutes per
variant on a small GPU.

## Reproducibility

Keep the prompt list and seed list in the final report. The same seeds with the
same model and settings reproduce the variants; changing the model or sampler
invalidates the comparison.

## Notes

- The batch tool builds the default **txt2img** graph only. It cannot produce
  video or audio; submit a graph with `comfyui_run_workflow` per variant and
  fetch with `comfyui_get_output`.
- For any other custom graph, use `comfyui_run_workflow` per variant instead of
  the txt2img batch tool.
- `tools.profile: "core"` hides `comfyui_generate_batch` and
  `comfyui_get_output`; use the default `full` profile for batches and media
  outputs.
- The assistant can follow the [`batch` skill](reference-skills.md) for the
  wave-by-wave procedure.
