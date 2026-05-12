---
name: status
description: Show ComfyUI queue status with running and pending jobs
---

# Queue Status

Show the current ComfyUI queue status.

Call `comfyui_get_queue` and format the response as:

- **Running jobs**: count and list of prompt IDs currently executing
- **Pending jobs**: count and list of prompt IDs waiting in queue

If `comfyui_get_queue` returns an error or unexpected data, respond with an appropriate error message indicating the issue.

If both the count of running jobs and the count of pending jobs are zero, report that the queue is idle.
