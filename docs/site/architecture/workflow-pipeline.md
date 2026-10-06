---
type: reference
title: "Workflow pipeline"
description: "What happens between a workflow tool call and ComfyUI's /prompt endpoint — inspection, validation, elicitation, submission."
created: 2026-10-06
updated: 2026-10-06
---

# Workflow pipeline

Every workflow-submitting tool funnels through `_submit_workflow` — one
chokepoint means no tool can forget a step.

## The sequence

```mermaid
sequenceDiagram
    participant A as Agent (MCP client)
    participant T as Tool (_submit_workflow)
    participant I as Inspector
    participant U as User (via elicitation)
    participant C as ComfyUIClient
    participant S as ComfyUI

    A->>T: run_workflow(json, wait=True)
    T->>I: inspect(workflow)
    I-->>T: warnings[] (+ /node_replacements check)
    alt enforce mode AND warnings
        T->>U: elicit "allow submission?"
        U-->>T: confirm / decline
        T-->>A: WorkflowBlockedError (on decline)
    end
    T->>C: post_prompt(workflow)
    C->>S: POST /prompt
    S-->>C: prompt_id
    T-->>A: envelope (submitted | completed | error | interrupted | timeout)
```

## What the inspector checks

1. **Dangerous nodes** — curated list (~150 real `class_type`s in three
   categories: code execution, network access, filesystem access) plus
   regex name-pattern matching for unknown packages
2. **Suspicious inputs** — recursive matching for `__import__()`, `eval()`,
   `exec()`, `os.system()`, `subprocess` across all input values
3. **Server-side replacements** — `/node_replacements` map consulted so a
   node that will be rewritten server-side is known *before* submission
   (recursing into subgraphs)
4. **Subgraph recursion** — embedded subgraph node maps are inspected too;
   unexpanded references produce an explicit "cannot fully inspect" warning

## What the validator adds

`comfyui_validate_workflow` runs the inspector's checks plus structural
analysis:

- graph structure and broken links (V3-schema-aware link detection —
  `DynamicCombo` values are not links)
- server compatibility
- **loop integrity** — pairing/escape/accumulate rules mirroring ComfyUI's
  own `validate_loops`: `loop_end_without_start`, `loop_start_without_end`,
  `ambiguous_loop_nesting`, `loop_escape`, `loop_accumulate_from_body`.
  Zero cost when no loop nodes exist.

## The wait envelope

All workflow/generation tools return a uniform dict:

```json
{
  "status": "completed",
  "prompt_id": "b0f6...e21",
  "outputs": [{...}],
  "elapsed_seconds": 14.2,
  "step": 20, "total_steps": 20,
  "warnings": []
}
```

`status` is one of `submitted` / `completed` / `interrupted` / `error` /
`timeout`. `warnings` travels with every result — in audit mode it is the
whole security story; in enforce mode it is what elicitation already asked
about.

## Partial execution

`comfyui_run_workflow` / `comfyui_run_workflow_stream` accept an optional
`partial_execution_targets` list — re-run just those nodes, serving the rest
from the server's execution cache. Node IDs are validated locally before
submit; an empty list is rejected; the key is omitted from the request body
when unset so the historical wire shape doesn't change.