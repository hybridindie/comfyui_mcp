---
type: index
title: "Architecture"
description: "How the server is built — the middleware stack, the client, the workflow pipeline, resources and prompts, background tasks."
created: 2026-10-06
updated: 2026-10-06
---

# Architecture

The server is a FastMCP 4 application with a strict layering rule: tools
carry behavior, the client carries transport, security modules carry
controls, and nothing skips a layer.

```mermaid
flowchart TB
    subgraph Client["LLM Client"]
        MC[AI Assistant / MCP Client]
    end

    subgraph MCP["ComfyUI MCP Server (FastMCP 4)"]
        CONFIG[Config<br/>YAML/env]

        subgraph Security["Security Layers"]
            WI[Workflow Inspector<br/>dangerous nodes · suspicious input<br/>+ elicitation gate]
            PS[Path Sanitizer<br/>traversal block · extension filter]
            RL[Rate Limiter<br/>token-bucket]
        end

        MW[SecurityMiddleware<br/>rate limit + entry audit<br/>on_call_tool hook]
        DI[Dependencies<br/>Depends() providers]

        subgraph Tools["Tool Groups"]
            T1[generation · workflow · jobs]
            T2[discovery · files · models · nodes]
        end

        RES[Resources<br/>comfyui://models · nodes · queue · system · settings]
        PR[Prompts<br/>txt2img · img2img · inpaint · upscale]
        TASKS[TasksExtension<br/>optional, Docket-backed]

        API[ComfyUI Client<br/>httpx, retries, envelope unwrap]
        WS[WebSocket Progress<br/>HTTP polling fallback]
    end

    subgraph ComfyUI["ComfyUI Server"]
        CS[REST API<br/>port 8188]
        CWS[WebSocket<br/>/ws]
    end

    MC <-->|"stdio or Streamable HTTP"| MCP
    CONFIG --> MCP
    MCP --> MW
    MW --> Security
    MW --> Tools
    DI --> Tools
    Security --> Tools
    Tools --> API
    Tools --> WS
    API -->|httpx| CS
    WS -->|websockets| CWS
```

## The pages

- **[Server & middleware](./server.md)** — entry point, the middleware stack, DI
- **[Client & transport](./client.md)** — httpx access, envelope unwrapping, progress tracking
- **[Workflow pipeline](./workflow-pipeline.md)** — what happens between a tool call and `/prompt`
- **[Resources & prompts](./resources-prompts.md)** — the browsable surface and recipe surface
- **[Background tasks](./tasks.md)** — optional Docket-backed execution over HTTP

## The layering rules (as enforced in the repo)

- Tools never call `httpx` directly — all transport is in `ComfyUIClient`
- Security concerns are enforced for every call, either in-tool or by
  middleware — asserted by invariant tests
- New tools follow a written checklist (rate limiting, audit, sanitization,
  inspection, typed params/returns) — see `AGENTS.md` in the repo
- No duplicate tools: two tools calling the same client method is a bug