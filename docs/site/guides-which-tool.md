---
type: guide
title: "Which interface?"
description: "MCP, comfy CLI, the official local server, the hosted Cloud MCP, or the UI — pick by task, not by preference."
created: 2026-11-27
updated: 2026-11-27
---

# Which interface should I use?

There are now five ways to drive ComfyUI. They are not competitors — each
owns a layer. Pick by the task, not by which one you installed first.

| Interface | Where it runs | What it owns |
|---|---|---|
| **This server** (`comfyui-mcp-secure`) | Anywhere; HTTP to any ComfyUI URL, stdio or Streamable HTTP | Agent execution, workflow inspection/policy, audit, rate limits, remote access |
| **`comfy` CLI** ([comfy-cli](https://github.com/Comfy-Org/comfy-cli)) | Your workstation / workspace | Launch, stop, update, version switch, logs, templates, partner models, node-pack lifecycle |
| **Official local server** ([`comfy-mcp`](https://github.com/Comfy-Org/comfy-mcp)) | Your workstation, stdio | The widest local tool surface (lifecycle, gallery, graph routing, partner models) |
| **Comfy Cloud MCP** | Hosted HTTP + OAuth | Cloud GPUs, cloud queue, partner models, billing |
| **ComfyUI UI** | Browser | Hand-authoring, visual debugging, canvas work |

## Task → interface

| You want to… | Use |
|---|---|
| Go from a prompt to an image from chat | **This server** — `comfyui_generate_image` |
| Build, validate, modify, or run a custom graph | **This server** — `validate_workflow` / `run_workflow` / `get_progress` |
| Generate a seed or prompt matrix | **This server** — loop, or `comfyui_generate_batch` once available |
| Reach a ComfyUI on a GPU box, in Docker, or behind a shared endpoint | **This server** over Streamable HTTP, with bearer auth |
| Audit what the agent ran, or enforce a node policy | **This server** — inspector + audit log + enforce mode |
| Start, stop, restart, or update ComfyUI; tail its logs | **`comfy` CLI** (or the official local server) |
| Switch ComfyUI versions or update custom-node packs in bulk | **`comfy` CLI** |
| Run hosted partner models or check credits | **Comfy Cloud MCP** |
| Hand-author a graph, debug node wiring, or inspect an output visually | **ComfyUI UI** |
| Drive ComfyUI from a CI job or shell script | **`comfy` CLI**, or this server's HTTP transport |

## The rule of thumb

1. **The UI authors, the MCP executes, the CLI installs.** Reach for the UI
   when a human is shaping the graph; the MCP when an agent acts on it; the
   CLI when the ComfyUI process or workspace itself changes.
2. **If it changes the ComfyUI process, the workspace, or the install, use the
   CLI.** Launch/stop/update/version-switch are not in this server's tool set,
   by design.
3. **If it has to be shared, audited, or policy-checked, use this server over
   HTTP with auth.** Those controls are the reason this server exists.

## Boundary cases

- **“Let the agent install a custom node.”** This server can queue it through
  ComfyUI-Manager and, in enforce mode, asks you first. The CLI is still the
  right answer for a human at a terminal, and the official server exposes the
  same flow without the policy layer.
- **“Let the agent update ComfyUI itself.”** Not this server. Core updates,
  version switches, and process lifecycle belong to `comfy-cli` (or the
  official local server).
- **“I only have a laptop with a local ComfyUI.”** The official `comfy-mcp` is
  simpler: no policy model, no HTTP transport, one `pip install` plus
  `comfy-cli`. Use this server when you need the controls, not by default.
- **“I want cloud GPUs.”** Comfy Cloud MCP. This server talks to a ComfyUI you
  control.
- **“I have both.”** Running this server and the official one side by side is
  normal: different tool names, no conflict. See
  [How it compares](./comparison.md).

## What this server deliberately does not do

Lifecycle management, partner/cloud generation and billing, the template
gallery, and node-graph routing all live elsewhere. See the
[comparison](./comparison.md) and the [roadmap](https://github.com/hybridindie/comfyui_mcp/blob/main/ROADMAP.md)
for the reasoning.
