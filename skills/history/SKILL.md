---
name: history
description: Show recent ComfyUI generation history
---

# Generation History

Show recent ComfyUI completions.

1. **Fetch history.** Call `comfyui_get_history`. The response is a pagination envelope: `{items, count, offset, limit, has_more, total}` where `total` is set only on the last page.

2. **Display results.** The MCP returns items in most-recent-first order — display them in the returned order; do not re-sort client-side. Iterate `result["items"]` and for each item show:
   - **Prompt ID**: the unique job identifier
   - **Status**: whether it completed successfully or failed
   - **Outputs**: filenames of generated images (if any)

3. **Follow-up options.** If the user wants to view a specific output, they can use `comfyui_get_image` with the filename. For a more unified view that also includes queued and currently-running jobs, use `comfyui_list_jobs` instead.
