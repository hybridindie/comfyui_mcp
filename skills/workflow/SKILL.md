---
description: Create a ComfyUI workflow from a template
---

# Create Workflow

Create and optionally run a ComfyUI workflow. Template or description: "$ARGUMENTS".

## Steps

1. **Pick a template.** If no specific template was requested, choose from the built-in template names accepted by `comfyui_create_workflow`: `txt2img`, `img2img`, `upscale`, `inpaint`, `txt2vid_animatediff`, `txt2vid_wan`, `controlnet_canny`, `controlnet_depth`, `controlnet_openpose`, `ip_adapter`, `lora_stack`, `face_restore`, `flux_txt2img`, `sdxl_txt2img`. The full list is also in `comfyui_create_workflow`'s docstring. (Note: `comfyui_list_workflows` returns server-side `/workflow_templates` from front-end packages — *not* these MCP-built-in templates.)

2. **Create the workflow.** Call `comfyui_create_workflow` with the chosen template name and any parameters the user specified (as a JSON string). For example:
   ```
   create_workflow(template="txt2img", params='{"prompt": "a sunset", "width": 768}')
   ```

3. **Validate the workflow.** Call `comfyui_validate_workflow` with the workflow JSON returned from step 2. Report any warnings or errors.

4. **Present the workflow.** Show a summary of what the workflow does (nodes, connections, key parameters). Offer the user two options:
   - **Run it** — call `comfyui_run_workflow` with `wait=True`
   - **Modify it** — use `comfyui_modify_workflow` to add/remove nodes or change parameters, then re-validate

## Notes

- Use `comfyui_summarize_workflow` to get a readable overview of any workflow JSON.
- For simple text-to-image generation, `/comfy:gen` is faster.
