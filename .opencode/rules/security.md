---
paths:
  - "src/comfyui_mcp/security/**/*.py"
  - "src/comfyui_mcp/client.py"
  - "src/comfyui_mcp/config.py"
  - "tests/test_blocked_endpoints.py"
  - "tests/test_security_invariants.py"
---

# Security Rules (non-negotiable)

This is a security-focused project. The rules below are invariants enforced by
`tests/test_blocked_endpoints.py` and `tests/test_security_invariants.py` — a
change that violates one is not "done."

## 1. Never expose blocked ComfyUI endpoints

The following are deliberately excluded from `client.py`: `/userdata`, `/free`,
`/users`, `/history` POST (delete). They must never be added to `client.py`.
Before adding any new client method, verify the endpoint is not on this list.

`/system_stats` is a special case: it **may** be called internally by
`get_system_stats()` in `client.py`, but **only** to serve the `get_system_info`
tool, which applies a strict output whitelist (GPU VRAM, queue counts, ComfyUI
version only). No raw `/system_stats` response is ever returned to any caller.
Do not add any other callers of `get_system_stats()`.

## 2. All file-handling tools must use PathSanitizer

Every tool that accepts a filename or subfolder parameter must call
`sanitizer.validate_filename()` and/or `sanitizer.validate_subfolder()` before
passing values to the client. No exceptions. URL path segments on discovery
tools (`comfyui_list_models`, `comfyui_get_model_metadata`) are also sanitized
to prevent folder/filename injection.

## 3. All tools must go through the rate limiter

Every tool function must be rate-limited. This may be enforced either by
calling `limiter.check("tool_name")` inside the tool body, *or* by
`RateLimitingMiddleware` (built-in, token-bucket) configured at the server
level. One of the two must be in effect for every tool call.

## 4. All tools must audit log

Every tool function must emit a structured audit record. This may be enforced
either by calling `audit.async_log(tool="...", action="...")` inside the tool
body, *or* by a custom `AuditMiddleware` using the `on_call_tool` hook that
emits one structured record per call (with sensitive arguments redacted). One
of the two must be in effect for every tool call.

## 5. Workflow execution must go through the inspector

Any tool that submits a workflow via `client.post_prompt()` must first call
`inspector.inspect()` and include warnings in the response.

## 6. No new dependencies without a real import

Every dependency in `pyproject.toml` must be imported somewhere in `src/`. Do
not add speculative or "might need later" dependencies.

## Anti-patterns

- A new client method that proxies `/userdata`, `/free`, `/users`, or `/history`
  POST delete.
- A file-handling tool that passes a raw filename/subfolder straight to the
  client without sanitization.
- A tool that skips both `limiter.check()` AND `RateLimitingMiddleware`
  (neither enforcement path in effect).
- A tool that skips both `audit.async_log()` AND `AuditMiddleware`
  (neither enforcement path in effect).
- A workflow-submitting tool that calls `client.post_prompt()` without first
  running `inspector.inspect()`.
