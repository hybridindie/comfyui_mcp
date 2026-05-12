---
description: Show recent ComfyUI generation history
---

# Generation History

Show recent ComfyUI completions.

Call `comfyui_get_history` and iterate `result["items"]` (the response is a pagination envelope: `{items, count, offset, limit, has_more, total}` where `total` is set only on the last page). For each item, show:

- **Prompt ID**: the unique job identifier
- **Status**: whether it completed successfully or failed
- **Outputs**: filenames of generated images (if any)

Show the most recent entries first. If the user wants to view a specific output, they can use `comfyui_get_image` with the filename. For a more unified view that also includes queued and currently-running jobs, use `comfyui_list_jobs` instead.
