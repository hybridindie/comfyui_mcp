---
type: reference
title: "Background tasks"
description: "Optional Docket-backed background execution for long-running workflows over the HTTP transport."
created: 2026-10-06
updated: 2026-10-06
---

# Background tasks

Optional. Disabled by default; most useful over the HTTP/remote transport
where a 2-minute generation shouldn't hold an HTTP request open.

```yaml
tasks:
  enabled: true
  backend_url: "memory://"                     # in-memory (default, single-process)
  # backend_url: "redis://localhost:6379/0"    # persistent, survives restarts
```

Env overrides: `COMFYUI_TASKS_ENABLED`, `COMFYUI_TASKS_BACKEND_URL`.

## What enabling does

When enabled, the server registers FastMCP 4's `TasksExtension` (backed by
[Docket](https://github.com/chrisguidry/docket)) and async tools become
task-capable:

- A client that **opts in** to the tasks capability submits work and gets a
  task handle immediately; it polls for the result
- A client that **does not** opt in gets synchronous execution — unchanged
  behavior

Stdio single-user mode gains little from this (the MCP call can just block);
that's why it's off by default.

## The elicitation caveat

`ctx.elicit()` is not supported inside a background task — there is no
request-scoped connection to ask through. Mid-task user input in enforce
mode uses the **guard pattern** instead: the tool returns an
`InputRequiredResult` carrying the confirmation request, and the client
resolves it and resubmits. Branch on
`ctx.request_context.protocol_version` only if both eras must be served;
the guard pattern is the general form on 2026-07-28 connections.

## Backend selection

| Backend | When |
|---|---|
| `memory://` | Single process; tasks lost on restart |
| `redis://host:port/db` | Tasks must survive restarts or run across workers |

Tasks are for *waiting differently*, not for more parallelism — ComfyUI
itself queues work; the tasks layer is about not holding transport
connections open.