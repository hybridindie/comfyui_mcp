---
type: concept
title: "Enforce mode & elicitation"
description: "Hard blocks, allowlists, and the MCP elicitation gates that ask the human before flagged workflows, node installs, or settings mutations run."
created: 2026-10-06
updated: 2026-11-27
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

On **sessionless 2026-07-28+** connections there is no server-initiated
back-channel, so `ctx.elicit()` is unavailable. The gate returns an
`InputRequiredResult` carrying a boolean approval request instead; the client
fulfills it and retries the call with the answer, which the gate reads from
`ctx.input_responses`. A decline still blocks, and both eras fail closed.

The gate covers `comfyui_run_workflow`, `comfyui_generate_image`,
`comfyui_transform_image`, `comfyui_inpaint_image`, and
`comfyui_upscale_image`.

## Mutating operations beyond workflows

Enforce mode gates the tools that run code or change configuration outside a
workflow with the same contract:

| Tool | What the user is asked to approve |
|---|---|
| `comfyui_install_custom_node` | Installing a registry pack — runs `pip` plus the pack's install script |
| `comfyui_update_custom_node` | Updating a pack to its latest version |
| `comfyui_uninstall_custom_node` | Removing a pack |
| `comfyui_update_settings` | Merging settings into the ComfyUI config |

Accept proceeds; decline or cancel raises `ConsentDeniedError` and the
ComfyUI call is never made. Without a live MCP context, enforce mode fails
closed. Audit mode logs and proceeds, as before.

## Declarative policy

For deployments with no human to prompt — CI, batch jobs, an unattended
agent — `security.policy` replaces "any warning prompts" with explicit rules:

```yaml
security:
  mode: enforce
  policy:
    deny_nodes: ["ExecutePython", "Terminal"]
    warn_nodes: ["SomeRiskyNode"]
    on_warning: "block"        # elicit (default) | block | allow
    max_nodes: 200
    allowed_model_folders: ["checkpoints", "loras"]
```

| Key | Behavior |
|---|---|
| `deny_nodes` | Hard block in enforce mode; warning in audit mode |
| `max_nodes` | Hard block above the node count in enforce mode; warning in audit mode (`0` disables) |
| `allowed_model_folders` | Hard block when a loader reads from another folder; warning in audit mode (`[]` disables) |
| `warn_nodes` | Adds class types to the warning set |
| `on_warning` | `elicit` asks (default), `block` refuses, `allow` logs and proceeds |

Unknown keys are rejected at startup. The node cap and folder check count
nodes nested inside inline subgraphs, and every fired rule names itself in the
warning text and the `inspected` audit record's `policy` snapshot. The
allowlist (`security.allowed_nodes`) still applies on top of the policy.

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