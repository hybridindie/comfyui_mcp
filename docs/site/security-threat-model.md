---
type: reference
title: "Threat model"
description: "What each control defends against, what it does not, and the assumption behind every row."
created: 2026-10-06
updated: 2026-10-06
---

# Threat model

The server is a trust boundary between an LLM agent and a ComfyUI host.
Every mitigation below is enforced server-side and test-pinned; the
"assumes" column names what still has to hold.

| Threat | Impact | Mitigation | Assumes |
|---|---|---|---|
| Arbitrary code execution via workflow nodes | Critical | Workflow inspector (audit/enforce mode); elicitation gate in enforce mode | The dangerous-node list covers the nodes in play; no obfuscating custom nodes |
| Path traversal via file operations | High | Path sanitizer blocks `..`, null bytes, encoded attacks, absolute paths; extension allowlist | ComfyUI itself honors the sanitized paths |
| XSS relay through inline image content | High | `comfyui_get_image` allow-lists raster `image/*` only; `image/svg+xml` and unknown types rejected; missing content types default-deny | Data-URI consumers render as claimed |
| Denial of service via request flooding | Medium | Token-bucket rate limiter per tool category, enforced by `SecurityMiddleware` | Single server process (in-memory buckets) |
| Oversized uploads | Medium | Local config cap + server-reported `max_upload_size` enforced before the request | `/features` reachable or config cap set |
| Credential leakage in logs | Medium | Automatic redaction of `token`, `password`, `secret`, `api_key`, `authorization` | Field names are honest |
| Information disclosure via API | Low | Dangerous endpoints never proxied; `/system_stats` whitelist-filtered by `comfyui_get_system_info` | The blocklist is maintained (test-enforced) |
| Cloud/API nodes silently spending money | Low (money) | 135 first-party cloud API node types flagged by default (BFL, Gemini, Ideogram, Kling, Luma, Minimax, OpenAI, Pika, PixVerse, Recraft, Rodin, Runway, Stability AI, Tripo, Veo2/Veo3, Moonvalley) | You read the warnings |
| MITM on ComfyUI connection | Medium | Configurable TLS verification | You kept it on for remote hosts |

## Compensating controls for what's left

The residual risks are real; the standard mitigations live outside this
server:

- **Unknown obfuscated nodes** — run ComfyUI itself in a container
  (filesystem + network isolation). The inspector narrows the surface but is
  not a sandbox.
- **Multi-tenancy** — one server process per tenant. The audit log and rate
  limiter are per-process; nothing here arbitrates between users.
- **Prompt injection into the conversation** — the elicitation gate means a
  hijacked conversation still needs *you* to press the confirm button on
  flagged workflows in enforce mode. Keep enforce mode on where prompts you
  don't control meet a ComfyUI host you care about.

## Security rules as governance

The project's own contributions are held to the same model:
`.opencode/rules/security.md` in the repo encodes the six controls as
non-negotiable rules, and `tests/test_blocked_endpoints.py` /
`tests/test_security_invariants.py` enforce them mechanically in CI. See
[the security model](./security-model.md) for how enforcement is structured.