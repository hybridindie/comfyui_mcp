# Phase 2: Security & Performance Review

## Security Findings

### High

| ID | CWE | Finding | File | Description |
|----|-----|---------|------|-------------|
| SEC-H1 | CWE-367 | TOCTOU race in audit logger symlink check | `audit.py:85-102` | `_write_record` checks `_is_path_safe()` then opens file. Symlink swap between check and open redirects/silences audit logs. Fix: `os.open()` with `O_NOFOLLOW`. |
| SEC-H2 | CWE-755 | HTTP retry does not catch HTTPStatusError | `client.py:61-78` | `raise_for_status()` raises `HTTPStatusError` (not `RequestError`). Transient 502/503/429 fail immediately without retry. |

### Medium

| ID | CWE | Finding | File | Description |
|----|-----|---------|------|-------------|
| SEC-M1 | CWE-918 | Latent SSRF via `get_image` base_url parameter | `client.py:144-163` | External URL path bypasses `_request()` safeguards. Currently not triggered by tool code, but latent vector. |
| SEC-M2 | CWE-20 | Missing path validation on `get_models` | `client.py:109-111` | `folder` interpolated into URL without `_validate_path_segment()`. Defense-in-depth gap. |
| SEC-M3 | CWE-20 | Missing path validation on `get_view_metadata` | `client.py:200-202` | Same defense-in-depth gap as SEC-M2. |
| SEC-M4 | CWE-770 | Inconsistent rate limiter category assignments | `server.py:109-159` | Read-only `get_queue` on workflow limiter (10/min); write ops `create_workflow`/`modify_workflow` on read limiter (60/min). Caller can starve workflow submissions via `get_queue`. |
| SEC-M5 | CWE-755 | Broad exception catch masks security errors | `validation.py:267-273` | Bare `except Exception` swallows inspector bugs as "internal errors", leaks exception text to caller. |
| SEC-M6 | CWE-312 | API tokens in plaintext config | `config.py:94-97` | `huggingface_token`/`civitai_api_key` stored plaintext. No file permission enforcement on config. |
| SEC-M7 | CWE-306 | SSE transport lacks authentication | `server.py:255-262` | Network-exposed SSE port has no auth. All tools accessible to any client on `0.0.0.0`. |
| SEC-M8 | CWE-295 | TLS verification bypass without warning | `config.py:53` | `tls_verify=False` disables cert validation on both httpx and WebSocket. No warning logged. |
| SEC-M9 | CWE-918 | `search_http` model_id not validated | `models.py:78-113` | HuggingFace `model_id` from API response interpolated into URL. Compromised API could inject path traversal. |

### Low

| ID | CWE | Finding | File | Description |
|----|-----|---------|------|-------------|
| SEC-L1 | CWE-532 | Incomplete sensitive field redaction | `audit.py:16-21` | Only top-level keys checked. Misses nested dicts, `access_token`, `refresh_token`, etc. |
| SEC-L2 | CWE-184 | Incomplete dangerous pattern detection | `inspector.py:9-16` | Missing `importlib`, `pickle.loads`, `os.popen`, `ctypes`, template injection. |
| SEC-L3 | CWE-362 | Rate limiter not thread-safe | `rate_limit.py:20-30` | No locking on `_tokens`/`_last_refill`. Safe in single-threaded asyncio; theoretical in multi-thread. |
| SEC-L4 | CWE-400 | No size limit on workflow JSON parsing | `generation.py:387` | Oversized JSON payload can cause memory pressure. |
| SEC-L5 | CWE-409 | No total metadata size limit in PNG parsing | `files.py:24-79` | Thousands of small tEXt chunks could accumulate. Mitigated by `validate_size` check. |

---

## Performance Findings

### High

| ID | Finding | File | Impact |
|----|---------|------|--------|
| PERF-H1 | `get_history()` returns unbounded full history | `client.py:120-121` | Memory spike proportional to ComfyUI history size (multi-MB). Use `?max_items=N` parameter. |
| PERF-H2 | `get_object_info()` has no caching | `client.py:113-118` | 2-10 MB allocation per call, used by 4+ tools. Add TTL cache (5 min). |
| PERF-H3 | `_get_client()` race condition on lazy init | `client.py:52-58` | Concurrent coroutines can create multiple clients, leaking connection pools. Add `asyncio.Lock`. |
| PERF-H4 | HTTP retry ignores transient 502/503/429 | `client.py:61-78` | Same as SEC-H2. Transient errors cause immediate failure. |

### Medium

| ID | Finding | File | Impact |
|----|---------|------|--------|
| PERF-M1 | `get_custom_node_list()` not cached | `nodes.py:196` | 1-5 second latency per search. Add TTL cache. |
| PERF-M2 | Model folder listings not cached across submissions | `model_checker.py:49-53` | Repeated folder listings on every workflow submission. Add 30-60s TTL. |
| PERF-M3 | Fixed 1-second polling interval | `progress.py:254` | 300 round-trips for 5-min generation. Use exponential backoff (1s to 10s cap). |
| PERF-M4 | `get_image` loads full image for base64 | `files.py:158-163` | 20+ MB raw, 27+ MB base64 for 4K images. Add size check. |
| PERF-M5 | `get_workflow_from_image` downloads full image for metadata | `files.py:235` | Full image download just for PNG text chunks. ComfyUI limitation. |
| PERF-M6 | N+1 in workflow validation model checking | `validation.py:250-256` | 1 object_info + N folder fetches. Mitigated by `asyncio.gather`. |
| PERF-M7 | HuggingFace search N+1 detail fetches | `models.py:116-137` | 11 HTTP calls for limit=10. Consider HF `?expand=siblings` parameter. |
| PERF-M8 | `search_custom_nodes` linear scan, no relevance ranking | `nodes.py:199-219` | Order-dependent results; first 10 matches by insertion order. Score by relevance. |
| PERF-M9 | Audit log opens/closes file per write | `audit.py:99` | Two syscalls + symlink checks per audit entry. Keep handle open with flush. |
| PERF-M10 | Module-level server init blocks import | `server.py:235` | Cold start latency; all setup at import time. |

### Low

| ID | Finding | File | Impact |
|----|---------|------|--------|
| PERF-L1 | Detector caching is one-shot, never invalidated | `model_manager.py`, `node_manager.py` | Stale state if plugins installed during session. Add `reset()`. |
| PERF-L2 | `get_system_info` sequential API calls | `discovery.py:307-308` | Two sequential calls could be parallelized with `asyncio.gather`. |
| PERF-L3 | All state in-process, no horizontal scaling | `server.py` | Cannot run multiple instances. Acceptable for single-user MCP. |

---

## Critical Issues for Phase 3 Context

1. **TOCTOU audit logger race** (SEC-H1) — tests should verify `O_NOFOLLOW` remediation
2. **HTTP retry gap** (SEC-H2/PERF-H4) — tests should cover transient 5xx retry behavior
3. **Client lazy init race** (PERF-H3) — tests should verify concurrent `_get_client()` safety
4. **Missing client-layer validation** (SEC-M2, SEC-M3) — tests should cover path traversal at client level
5. **Rate limiter category mapping** (SEC-M4) — tests should verify correct limiter-to-tool assignments
6. **No `get_object_info` caching** (PERF-H2) — tests should verify cache TTL behavior
7. **Unbounded `get_history`** (PERF-H1) — tests should verify `max_items` parameter
