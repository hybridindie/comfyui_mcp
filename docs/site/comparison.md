---
type: concept
title: "How it compares"
description: "comfyui-mcp-secure vs raw ComfyUI HTTP, vs a thin MCP wrapper, and which to pick."
created: 2026-10-06
updated: 2026-10-06
---

# How it compares

## vs giving the agent raw ComfyUI HTTP

| | Raw ComfyUI API | comfyui-mcp-secure |
|---|---|---|
| Dangerous endpoints (`/userdata`, `/free`, `/users`) | Exposed | Never proxied (test-enforced) |
| Workflow safety | Trusts the client | Inspected server-side; enforce mode elicits the human |
| Paths | Raw trust | Sanitized (traversal/null-byte/encoded/extension) |
| Request volume | Unlimited | Token-bucket per category |
| API knowledge the agent needs | Full — every endpoint, every quirk | 53 documented tools with typed results |
| Model-Manager envelope quirks | Yours to handle | Normalized in the client |
| Progress | Raw WebSocket protocol | Typed progress events + notifications |

## vs a thin ComfyUI MCP wrapper

Thin wrappers map endpoints 1:1 and call it a day. The difference here is
**what the server refuses to do**: a thin wrapper forwards `/userdata`
because it exists; this one treats API surface *selection* as a security
decision with tests enforcing it. Also: the inspector is workflow-aware
(parses graphs, warns on `ExecutePython`-class nodes and suspicious
inputs), not just proxy plumbing.

## vs the ComfyUI UI itself

Orthogonal. The UI is for humans hand-authoring — keep using it. The MCP
server is for agents acting on your behalf: batch generation, workflow
iteration driven by conversation, auditing what the agent did. Both talk to
the same ComfyUI instance; both can be open at once.

## When you *don't* need this

- You never point an LLM at ComfyUI — use the UI
- You already have a full application layer in front of ComfyUI with its
  own auth — this server's security work would duplicate it
- You want a multi-user SaaS gateway — this is single-tenant; one process
  per tenant

## The security posture in one paragraph

Server-side, test-pinned enforcement: rate limiting + entry audit on every
call by middleware, path sanitization on every file op, workflow inspection
with a curated dangerous-node list of ~150 real nodes plus pattern
matching, four endpoints never proxied, elicitation-based human
confirmation in enforce mode, and a whitelist-only system-info tool. The
[security model](./security-model.md) details each control; the
[threat model](./security-threat-model.md) states the assumptions openly.