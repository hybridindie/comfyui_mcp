---
name: batch
description: Generate a prompt or seed matrix with ComfyUI
---

# Batch generation

The user wants several variants. Request: "$ARGUMENTS".

## Steps

1. **Build the matrix.** Prompts × seeds, or a count with random seeds. Confirm the Cartesian size with the user; default to four variants unless they asked for more.

2. **Fix the settings.** One model, one resolution, one sampler configuration for the whole batch — mixed settings make the results hard to compare. Pick the model from `comfyui_list_models(folder="checkpoints")`.

3. **Submit in batches.** Call `comfyui_generate_batch(prompts=..., seeds=...)` with at most eight variants per call. It returns `{status, count, variants, errors}` with a `prompt_id` per variant, and counts as one generation call — wait for the batch to finish before starting another.

4. **Track progress.** Poll `comfyui_get_progress` (or `comfyui_list_jobs` for the wider queue) per prompt ID. A failed variant reports its error through `comfyui_get_job`; stop that variant only.

5. **Collect outputs.** Fetch each completed result with `comfyui_get_image(preview_format="webp", preview_quality=80)` and present a table: seed, prompt, status, filename.

## Notes

- Warn about GPU time before a large matrix; a 20-image batch is not a quick request.
- Keep the prompt list and seed list visible in the final report so the run is reproducible.
- For a custom graph, use `comfyui_run_workflow` per variant instead of `generate_batch`.
- Enforce mode may ask for confirmation per variant; tell the user before starting a wave.
