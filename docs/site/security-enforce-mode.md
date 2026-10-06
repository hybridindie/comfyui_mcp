---
type: concept
title: "Enforce mode & elicitation"
description: "Hard blocks, allowlists, and the MCP elicitation gate that asks the human before flagged workflows run."
created: 2026-10-06
updated: 2026-10-06
---

# Enforce mode & elicitation

Enforce mode is for deployments where "the LLM was supposed to relay the
warning" is not good enough: shared servers, exposed transports, untrusted
prompts.

```yaml
security:
  mode: "enforce"
  allowed_nodes:
    - "KSampler"
    - "CheckpointLoaderSimple"
    - "CLIPTextEncode"
    - "VAEDecode"
    - "EmptyLatentImage"
    - "SaveImage"
    - "LoadImage"
    - "LoraLoader"
```

## Two distinct gates, in order

**1. The allowlist (hard block).** Any workflow containing a node not in
`allowed_nodes` is rejected inside the inspector — before anything else, no
conversation involved. `dangerous_nodes` are always flagged regardless of
mode.

**2. The elicitation gate (the human).** When the inspector produces
warnings (dangerous-node types, suspicious inputs like `eval()`/`exec()`,
or missing models), the generation tools call MCP elicitation —
`ctx.elicit(..., response_type=bool)` — and the client shows *you* the
warnings:

```text
⚠ This workflow contains flagged nodes:
   - node 5 (ExecutePython): code execution
Allow submission? [y/N]
```

- **Confirm** → the workflow proceeds to ComfyUI.
- **Decline/cancel** → `WorkflowBlockedError`; `post_prompt` is never called.

The gate covers `comfyui_run_workflow`, `comfyui_generate_image`,
`comfyui_transform_image`, `comfyui_inpaint_image`, and
`comfyui_upscale_image`.

## Why elicitation matters

Audit-mode warnings rely on the LLM reading the `warnings` array and
choosing to relay it. That is a suggestion. Elicitation moves the gate into
the server: the tool call itself blocks until a human decides, regardless of
what the LLM would prefer. An MCP client cannot skip the question and the
LLM cannot answer it — the answer comes from the user's client session.

Programmatic callers without a live MCP context (tests, scripts) keep the
pre-elicitation behavior: immediate `WorkflowBlockedError` in enforce mode
with warnings.

## Recommended migration

1. Stay in [audit mode](./security-audit-mode.md); run
   `comfyui_audit_dangerous_nodes` once.
2. Work normally; the audit log shows which nodes your workflows actually
   use.
3. Paste the honest allowlist into `security.allowed_nodes`; switch
   `mode: "enforce"`.
4. The elicitation gate now covers everything the allowlist missed —
   including newly installed custom nodes you haven't reviewed yet.