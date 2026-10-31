---
read_when: "Writing async code, transports, background jobs, or anything with timeouts"
---

# Async: Never Block, Always Time Out

Stack rules (e.g. Godot) refine this for their runtime.

## MUST

- Every call that crosses a process, network, or disk boundary has a timeout
  and a defined failure on expiry.
- No blocking calls in an async path (`time.sleep`, sync HTTP/DB/file IO,
  CPU-heavy work). Move unavoidable sync work to an executor.
- Background tasks are owned: keep a reference, surface their exceptions, and
  cancel and await them on shutdown.
- Fan-out over input is bounded.
- Retries use bounded exponential backoff with jitter and only retry
  idempotent operations.

## SHOULD

- Structured concurrency (`asyncio.TaskGroup`, `anyio`).
- Propagate a request/command id through logs, errors, and retries.

## ANTI-PATTERNS

- `asyncio.run()` inside a running loop.
- Holding a lock across an `await` that does IO.
- A timeout that fails with no message.
