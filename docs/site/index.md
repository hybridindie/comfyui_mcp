---
layout: home

hero:
  name: 'comfyui-mcp-secure'
  text: 'Drive ComfyUI from an AI agent — securely'
  tagline: 'A security-first MCP server for ComfyUI: generate images, run workflows, and manage models from any MCP client. Workflow inspection, path sanitization, rate limiting, and structured audit logging are built in, not bolted on.'
  actions:
    - theme: brand
      text: What & why
      link: ./what-why
    - theme: alt
      text: Getting Started
      link: ./getting-started
    - theme: alt
      text: LLM docs (llms.txt)
      link: /comfyui_mcp/llms.txt

features:
  - title: Security is the product, not a flag
    details: Every workflow submission goes through the inspector. File operations pass through a path sanitizer. Every tool call is rate-limited and audit-logged. Dangerous ComfyUI endpoints are never proxied — enforced by tests, not convention.
  - title: Two security modes
    details: Audit mode logs dangerous-node warnings and lets work proceed. Enforce mode blocks unapproved nodes hard, and asks the user to confirm (MCP elicitation) before submitting flagged workflows.
  - title: 53 tools, a real surface
    details: Generation, workflow authoring, job management, discovery, file operations, model search/download, and custom-node management — all typed with structured returns, not loose strings.
  - title: An agent can author workflows
    details: Create workflows from 14 built-in templates, modify them with batch graph operations, validate structure and loop integrity, and render Mermaid diagrams of the data flow.
---

## The path an image takes

Every generation crosses three hops — each one inspected, sanitized, and logged:

```mermaid
flowchart LR
    AI["AI client (OpenCode / Claude / any MCP host)"]
    SRV["MCP server (FastMCP 4)\ninspector · sanitizer · limiter · audit"]
    CS[("ComfyUI server\nREST + WebSocket")]
    AI -->|"stdio or Streamable HTTP (MCP)"| SRV
    SRV -->|"httpx, path- and node-vetted"| CS
    CS -.->|"progress events"| SRV
    SRV -.->|"typed results + warnings"| AI
```

The server is a gatekeeper, not a proxy: it understands the workflow JSON it
forwards, warns on dangerous nodes, and refuses endpoints it does not trust.

## The security surface in one example

Submit a workflow containing a code-execution node:

```text
> comfyui_validate_workflow(workflow='{"nodes": {"5": {"class_type": "ExecutePython", ...}}}')

{ "valid": true, "errors": [],
  "warnings": [{ "type": "dangerous_node",
                 "node": "5", "class_type": "ExecutePython",
                 "reason": "code execution node" }] }
```

In audit mode the submission proceeds and the warning lands in the audit log.
In enforce mode the server **asks the user to confirm before anything runs**
(MCP elicitation) — a decline blocks the submission without calling ComfyUI.
That gate is the tool's own behavior, not the client's discretion.

Run it yourself: [getting started](./getting-started.md) — the full security
model is pinned by invariant tests.

> [!WARNING]
> **Security is enforced server-side.** An MCP client that ignores warnings
> cannot bypass enforce mode or the elicitation gate — blocking happens inside
> the server. The docs' [threat model](./security-threat-model.md) covers what
> each control does and does not defend against.

---

## Where to go next

- **[What & why](./what-why.md)** — the reasoning behind every major design decision
- **[Core concepts](./concepts.md)** — the vocabulary the rest of the docs assume
- **[Security model](./security-model.md)** — the six controls and how they compose
- **[Architecture](./architecture/.md)** — the server, the client, the workflow pipeline
- **[Reference](./reference.md)** — every tool, resource, config knob, env var
- **[Guides](./guides-generate.md)** — generate images, author workflows, deploy in production