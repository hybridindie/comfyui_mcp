---
type: guide
title: "Work with custom workflows"
description: "Template → modify → validate → run, plus partial re-execution, subgraphs, and reading existing PNGs."
created: 2026-10-06
updated: 2026-10-06
---

# Work with custom workflows

An agent can author and iterate on full graphs — not just fire the canned
generators. The loop: **create** from a template, **modify** with batch
operations, **validate**, **run** (or re-run partially).

## 1. Create from a template

```text
comfyui_create_workflow(template="txt2img",
                        params='{"prompt": "...", "model": "..." }')
```

14 templates: txt2img, img2img, upscale, inpaint, txt2vid_animatediff,
txt2vid_wan, controlnet_canny, controlnet_depth, controlnet_openpose,
ip_adapter, lora_stack, face_restore, flux_txt2img, sdxl_txt2img.

## 2. Modify with batch operations

```text
comfyui_modify_workflow(workflow_id="...",
    operations='[
      {"op": "add_node", "node": {"id": "12", "class_type": "LoraLoader",
                                  "inputs": {...}}},
      {"op": "connect", "from_node": "12", "input_name": "...", "to_node": "3"},
      {"op": "set_input", "node": "6", "input_name": "text", "value": "..."}
    ]')
```

Every operation's per-op JSON shape is spelled out in the tool's docstring —
read it in your client's tool list rather than guessing field names.

## 3. Validate before spending a GPU-second

```text
comfyui_validate_workflow(workflow_id="...")
→ { "valid": true, "errors": [], "warnings": [{ "type": "dangerous_node", ... }] }
```

Checks: graph structure, broken links, server compatibility, security
(inspector), and **loop integrity** — orphaned `StartLoop`/`EndLoop`,
ambiguously nested loops, edges escaping a loop body, accumulate-from-body
errors. Mirrors ComfyUI's own `validate_loops`, so errors here mean errors
at `/prompt` too.

See also `comfyui_analyze_workflow` (structured dict: node count, class
types, data flow, models) and `comfyui_summarize_workflow(output_format="mermaid")`
(renderable diagram).

## 4. Run — or re-run partially

```text
comfyui_run_workflow(workflow_id="...", wait=True)
```

Iteration trick: after a full run, re-launch only the parts that depend on
a change — `partial_execution_targets=[node_id, ...]` runs just those nodes
and serves everything else from the server's execution cache:

```text
comfyui_run_workflow(workflow_id="...",
                     partial_execution_targets=["6"],
                     wait=True)
```

Node IDs are validated locally first; empty lists are rejected.

## Subgraphs

Reusable subgraph templates (custom-node + blueprint subgraphs) list via
`comfyui_list_subgraphs`; `comfyui_get_subgraph` fetches one's JSON. The
inspector recurses into embedded subgraph node maps — dangerous nodes
inside subgraphs are caught — and warns explicitly when a reference is
unexpanded and inspection is incomplete.

## Starting from an existing PNG

ComfyUI embeds the workflow in generated PNGs. Recover it instead of
recreating:

```text
comfyui_get_workflow_from_image(filename="ComfyUI_00001_.png", subfolder="")
```

Then modify/validate/run as above.

## Security posture along the way

Every submit path inspects — including template-modified and
subgraph-embedded graphs. Audit mode attaches `warnings` to every result;
enforce mode elicits you before flagged submissions. Security-shaped
failures are listed under [errors & recovery](./reference-errors.md).