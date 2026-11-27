---
type: concept
title: "How it compares"
description: "comfyui-mcp-secure vs raw ComfyUI HTTP, vs the official Comfy MCP, vs a thin wrapper, and which to pick."
created: 2026-10-06
updated: 2026-11-27
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

## vs a thin community ComfyUI MCP wrapper

Thin wrappers map endpoints 1:1 and call it a day. The difference here is
**what the server refuses to do**: a thin wrapper forwards `/userdata`
because it exists; this one treats API surface *selection* as a security
decision with tests enforcing it. Also: the inspector is workflow-aware
(parses graphs, warns on `ExecutePython`-class nodes and suspicious
inputs), not just proxy plumbing.

## vs the official Comfy MCP (`comfy-mcp`)

Comfy ships two first-party servers: the hosted **Comfy Cloud MCP**
(`cloud.comfy.org/mcp` — remote HTTP, OAuth, execution on Comfy Cloud GPUs)
and the local **[`comfy-mcp`](https://github.com/Comfy-Org/comfy-mcp)** —
a `stdio` server with 42 tools that shells out to `comfy-cli`. The local one
is the like-for-like comparison: both drive a ComfyUI you control.

`comfy-mcp` is not a thin passthrough. It has a written threat model,
argument-hygiene guards (no `shell=True`, NUL and flag-injection rejection)
and fail-closed elicitation for third-party code, version switches, network
exposure and credit spend. What it does not have is a policy layer between
the agent and the graph — by design. Its `CONTRIBUTING.md` requires every
tool to be a `comfy` passthrough with no HTTP client of its own, and its
`SECURITY.md` lists arbitrary workflow execution and filesystem access as
accepted capabilities.

| | comfyui-mcp-secure | comfy-mcp (official local) |
|---|---|---|
| Transport | stdio or Streamable HTTP; direct HTTP to any ComfyUI URL | stdio only; subprocess of `comfy-cli` |
| Runtime requirements | A reachable ComfyUI | `comfy-cli` ≥ 1.14 + a ComfyUI workspace (running server for execution tools) |
| License | MIT | AGPL-3.0-or-later or commercial |
| Workflow inspection | ~150 dangerous node classes plus patterns, subgraph recursion, replacement warnings; audit/enforce modes with elicitation | None — arbitrary execution is documented as accepted |
| Path handling | Every filename, subfolder and URL segment sanitized | Verbatim paths after argument-hygiene guards; not a filesystem sandbox |
| Rate limiting | Token bucket per tool category | No per-tool request throttling — internal timeouts, output caps and single-flight locks only |
| Audit trail | Structured JSON per call, sensitive args redacted | Opt-in debug failure log, not an operation audit |
| System info | Whitelisted — `/system_stats` filtered to VRAM, queue counts, version | Full passthrough, including ComfyUI's `argv` and Python version |
| MCP surface | 53 tools, 5 resources, 4 prompts, `outputSchema` on structured-returning tools | 42 tools; no resources or prompts (handshake instructions instead) |
| Breadth | Generation, jobs, discovery, nodes, models, history, files | Plus lifecycle (launch/stop/update/version switch), template gallery, slot editing, node-graph routing, partner models + billing, media preview |
| Spend consent | Flags cloud/partner API nodes as dangerous by default | Per-call elicitation with fail-closed spend gates |

### Where the official server is the better choice

- **You want the widest ComfyUI surface with the least setup.** Lifecycle
  management, the template gallery, `partner_generate` partner runs and
  graph-routing tools have no equivalent here.
- **You are on one workstation and want first-party maintenance.**
  `comfy-cli` absorbs most ComfyUI API churn; this server re-implements it
  endpoint by endpoint.
- **You want hardware-aware routing out of the box.** `comfy-mcp` puts a
  machine snapshot (GPU, VRAM, RAM) into the handshake instructions and
  steers the agent toward local, partner or cloud execution.

### Where this server is the better choice

- **ComfyUI is not on the same machine as the client** — a GPU box, Docker,
  CI, or a shared endpoint. `comfy-mcp` is a `stdio` child of one client and
  expects a local workspace; this server speaks Streamable HTTP and can talk
  to any URL.
- **You need to enforce or audit what the agent runs.** If "what did the
  agent submit at 14:02, and was it allowed?" has to have an answer, this is
  the one with an inspector, a policy mode, rate limits and an audit log.
- **You embed the server in a proprietary product or hosted service.** MIT
  versus AGPL-or-commercial is a licensing decision, not a preference.
- **You want resources and prompts**, not just tools.

Running both is normal: they register under different names and do not
conflict. Use the official server for lifecycle and partner models, this one
for anything that needs policy.

## vs the ComfyUI UI itself

Orthogonal. The UI is for humans hand-authoring — keep using it. The MCP
server is for agents acting on your behalf: batch generation, workflow
iteration driven by conversation, auditing what the agent did. Both talk to
the same ComfyUI instance; both can be open at once.

## When you *don't* need this

- You never point an LLM at ComfyUI — use the UI
- You only drive a local workstation install and don't need policy, audit or
  HTTP transport — the official [`comfy-mcp`](https://github.com/Comfy-Org/comfy-mcp)
  is the better default
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