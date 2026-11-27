---
name: batch
description: Generate a prompt or seed matrix with ComfyUI
---

# Batch generation

The user wants several variants. Request: "$ARGUMENTS".

## Steps

1. **Build the matrix.** Prompts × seeds, or a count with random seeds. Confirm the Cartesian size with the user; default to four variants unless they asked for more.

2. **Fix the settings.** One model, one resolution, one sampler configuration for the whole batch — mixed settings make the results hard to compare. Pick the model from `comfyui_list_models(folder="checkpoints")`.

3. **Submit in waves.** Call `comfyui_generate_image(wait=False)` for at most eight variants at a time and record every `prompt_id`. The generation limiter is 10 requests/minute, so wait for the previous wave to finish before starting the next; do not hold one call open for the whole batch.

4. **Track progress.** Poll `comfyui_get_progress` (or `comfyui_list_jobs` for the wider queue) per prompt ID. A failed variant reports its error through `comfyui_get_job`; stop that variant only.

5. **Collect outputs.** Fetch each completed result with `comfyui_get_image(preview_format="webp", preview_quality=80)` and present a table: seed, prompt, status, filename.

## Notes

- Warn about GPU time before a large matrix; a 20-image batch is not a quick request.
- Keep the prompt list and seed list visible in the final report so the run is reproducible.
- For a custom graph, use `comfyui_run_workflow` per variant instead of `generate_image`.
- Enforce mode may ask for confirmation per variant; tell the user before starting a wave.
