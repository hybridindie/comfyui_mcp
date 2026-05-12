---
name: workflow
description: Create a ComfyUI workflow from a template
---

# Create Workflow

Create and optionally run a ComfyUI workflow. Template or description provided by the user as input: "$ARGUMENTS".

## Steps

1. **Pick a template.** If no specific template was requested, choose from the built-in template names accepted by `comfyui_create_workflow`: `txt2img`, `img2img`, `upscale`, `inpaint`, `txt2vid_animatediff`, `txt2vid_wan`, `controlnet_canny`, `controlnet_depth`, `controlnet_openpose`, `ip_adapter`, `lora_stack`, `face_restore`, `flux_txt2img`, `sdxl_txt2img`. The full list is also in `comfyui_create_workflow`'s docstring. (Note: `comfyui_list_workflows` returns server-side `/workflow_templates` from front-end packages — *not* these MCP-built-in templates.) If the user provides a template name that is not in this list, respond with an error message and list the valid options above.

2. **Create the workflow.**
   - If the user did not specify any parameter overrides, call `comfyui_create_workflow` with only the template name (omit `params`; it defaults to `""`, which applies the predefined settings for the selected template).
   - If the user specified overrides (e.g., prompt, dimensions), pass them as a JSON string in the `params` argument:
     ```
     create_workflow(template="txt2img", params='{"prompt": "a sunset", "width": 768}')
     ```

3. **Validate the workflow.** Call `comfyui_validate_workflow` with the workflow JSON returned from step 2. The response is a dict `{valid, errors, warnings, node_count, pipeline}`. Report any entries in `errors` (blocking) and `warnings` (non-blocking).

4. **Present the workflow.** Show a summary of what the workflow does (nodes, connections, key parameters). Offer the user two options:
   - **Run it** — call `comfyui_run_workflow` with `wait=True`. The response is a dict envelope: `{status, prompt_id, outputs, elapsed_seconds, warnings?}`. Read `status` to confirm completion.
   - **Modify it** — use `comfyui_modify_workflow` to add/remove nodes or change parameters, then re-validate

## Notes

- Use `comfyui_summarize_workflow` for a human-readable text or Mermaid overview (`output_format="text"` or `"mermaid"`).
- Use `comfyui_analyze_workflow` if you need the structured analysis as a dict (fields like `pipeline`, `models`, `parameters`) without parsing prose.
- For simple text-to-image generation, `/comfy:gen` is faster.
