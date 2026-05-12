---
description: Show execution progress for a ComfyUI job
---

# Job Progress

Show progress for a specific ComfyUI job. Prompt ID: "$ARGUMENTS".

Call `comfyui_get_progress` with the prompt_id from "$ARGUMENTS". The response is a dict; format it showing:

- **Current node**: which node is executing (`current_node` field)
- **Progress**: `step` X of `total_steps` Y (percentage)
- **Status**: one of `queued`, `running`, `completed`, `error`, `interrupted` (mapped from the unified `/api/jobs/{id}` endpoint), or `unknown` if the job is not found

If no prompt_id is provided, suggest the user check `/comfy:status` first to find active job IDs, or `/comfy:history` for recent completions.
