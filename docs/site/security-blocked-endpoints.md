---
type: reference
title: "Blocked endpoints"
description: "The ComfyUI endpoints this server never proxies — and why."
created: 2026-10-06
updated: 2026-10-06
---

# Blocked endpoints

These ComfyUI endpoints are **never** proxied, regardless of config:

| Endpoint | Why it's dangerous |
|---|---|
| `/userdata` | Arbitrary file read/write on the ComfyUI host |
| `/free` | Unload models — a denial-of-service vector against a GPU host |
| `/users` | User management — account manipulation |
| `/history` POST (delete) | Destructive history deletion |

`/system_stats` is a special case: it **is** called internally, but **only**
by `comfyui_get_system_info`, which applies a strict output whitelist
(GPU VRAM, queue counts, ComfyUI version) and never returns the raw
response. No other code path touches it.

## How it's enforced

By omission plus a test. `client.py` contains no method that reaches these
endpoints, and `tests/test_blocked_endpoints.py` fails CI if one appears.
The same tests assert that a `/system_stats` caller beyond
`get_system_info()` would be a violation.

This is the design principle the whole project follows: **the client cannot
make the server proxy something the server does not implement.** A malicious
or confused LLM can only pick from the 53 tools that exist — and every one
of those has passed the [security model](./security-model.md) checks.