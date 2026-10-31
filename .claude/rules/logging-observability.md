---
read_when: "Adding logs, metrics, tracing, or debugging a production issue"
---

# Observability: Structured, Correlated, Secret-Free

## MUST

- Operational logs are structured (JSON or key=value) and go through the
  logging library, not `print()`. CLI data output on stdout is not logging.
- Log lines carry the request/command id where one exists.
- Levels mean something: `error` needs action, `warning` is degraded, `info`
  is lifecycle, `debug` is diagnostics.
- Log an error once, at the boundary, with context.
- Never log secrets, tokens, full payloads, file contents, or home paths.

## SHOULD

- Services that run continuously expose a health endpoint and basic latency /
  error metrics.
- Long operations report progress.
- Aggregate per-item detail instead of logging inside a hot loop.
