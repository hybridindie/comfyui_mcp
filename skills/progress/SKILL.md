---
name: progress
description: Show execution progress for a ComfyUI job
---

# Job Progress

Show progress for a specific ComfyUI job. Prompt ID: "$ARGUMENTS".

1. **Get the prompt_id.** Extract it from "$ARGUMENTS". If "$ARGUMENTS" is empty or contains no recognizable id, suggest the user run `/comfy:status` first to find active job IDs, or `/comfy:history` for recent completions, and stop here.

2. **Fetch progress.** Call `comfyui_get_progress` with the prompt_id. Do not pre-validate the id format — the tool returns `status="unknown"` if the job is not found, which step 3 surfaces to the user.

3. **Format the response.** The response is a dict. Format it to include the following fields:
   - **Current node**: which node is executing (`current_node` field)
   - **Progress**: `step` X of `total_steps` Y (percentage)
   - **Status**: one of `queued`, `running`, `completed`, `error`, `interrupted` (mapped from the unified `/api/jobs/{id}` endpoint), or `unknown` if the job is not found
