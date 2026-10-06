---
type: concept
title: "What & why"
description: "The problems comfyui-mcp-secure solves, and why it is built the way it is."
created: 2026-10-06
updated: 2026-10-06
---

# What & why

## The problem it solves

An LLM agent with a raw ComfyUI HTTP endpoint is a **remote-code-execution
hazard wearing an API costume**:

- **Workflows are code.** ComfyUI custom nodes can execute arbitrary Python
  (`ExecutePython`, eval-based interpreter nodes), make network calls, and
  read/write the filesystem. An agent following a prompt-injected instruction
  can assemble a workflow that runs whatever it likes — on the host running
  ComfyUI.
- **Endpoints are dangerous.** ComfyUI exposes `/userdata` (arbitrary file
  read/write), `/free` (unload models — a DoS vector), and user management —
  right next to the harmless generation API. A naive proxy exposes all of it.
- **Paths are attack surface.** Filename and subfolder parameters are natural
  path-traversal targets (`../../etc/`, null bytes, percent-encoded tricks).
- **Agents flood.** A looping agent can submit generation after generation
  with no throttle, hammering a GPU host.
- **"Trust me" is not a security model.** Telling the client "please be
  careful" is unenforceable; an MCP client is a different process with
  different goals.

comfyui-mcp-secure closes that gap: the agent talks to the MCP server, and the
server is the only thing that talks to ComfyUI. Every control lives in the
server, where the client cannot reach it.

## The reasoning behind the design

**The server owns security; the client only sees results.** All six controls
(inspector, sanitizer, rate limiter, audit log, blocked-endpoint list,
elicitation gate) execute server-side. Invariant tests assert the controls
fire for *every* tool — a new tool that skips them fails CI, so the guarantee
does not erode over time.

**There are two modes because two audiences exist.** A solo developer
experimenting wants to know about dangerous nodes, not be stopped. A shared
or exposed deployment wants hard refusal. Audit mode is the default so the
project is usable day one; enforce mode is one config key away, and the
migration path is `comfyui_audit_dangerous_nodes` → paste your allowlist.

**Warnings travel with the result, and enforce mode asks a human.** In audit
mode, warnings ride along in the tool response so the LLM can relay them. In
enforce mode, a flagged workflow triggers MCP **elicitation**: the server (not
the LLM) pauses the tool call and asks the user to confirm. Decline → the
submission never reaches ComfyUI. This matters because warnings alone rely on
the LLM reading them; elicitation makes the gate the server's behavior.

**Structured returns, not strings.** Tools return typed dicts (FastMCP 4
generates `outputSchema` from return types), so no client has to `json.loads`
a string, and tests assert fields directly.

**Discovery is browsing, not tool calls.** Read-only state (models, installed
nodes, queue, system info, settings) is exposed as `comfyui://` resources so
the LLM can look things up without spending a tool call — with the same rate
limiting and audit coverage as tools.

**The eval harness keeps the surface honest.** Phase 4 (static) and Phase 5
(live execution) Inspect AI suites run the server against real models before
any change to tool descriptions or schemas merges — the LLM-facing surface is
test-covered like code.

## What it is not

- **Not a ComfyUI replacement or wrapper UI** — it is a protocol adapter; the
  ComfyUI UI does everything it always did.
- **Not a sandbox.** The inspector's static analysis can be bypassed by
  obfuscated custom nodes it has never seen. Enforce mode plus a tight
  allowlist is the real containment; run ComfyUI itself in a container for
  defense in depth.
- **Not multi-tenant.** The audit log and rate limiter are per-process.
  Point untrusted third parties at their own server instance.