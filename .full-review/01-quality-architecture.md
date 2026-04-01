# Phase 1: Code Quality & Architecture Review

## Code Quality Findings

### Critical

| ID | Finding | File | Description |
|----|---------|------|-------------|
| CQ-C1 | TOCTOU race in audit logger symlink check | `audit.py:63-102` | `_write_record` checks `_is_path_safe()` then opens file — symlink swap between check and open can redirect/silence audit logs. Fix: use `os.open()` with `O_NOFOLLOW`. |

### High

| ID | Finding | File | Description |
|----|---------|------|-------------|
| CQ-H1 | HTTP client retries only on RequestError | `client.py:67-78` | `raise_for_status()` inside retry loop raises `HTTPStatusError` (not caught) on transient 502/503/429. First transient server error fails immediately. |
| CQ-H2 | Module-level server construction at import time | `server.py:235` | `_build_server()` runs at import, triggering config loading, HTTP client creation, atexit registration. Complicates testing and tooling. |
| CQ-H3 | `get_image` with `base_url` bypasses retry logic | `client.py:157-161` | External URL path uses `c.get()` directly, skipping `_request()` retry/validation/error handling. |

### Medium

| ID | Finding | File | Description |
|----|---------|------|-------------|
| CQ-M1 | Duplicated validation logic across generation tools | `generation.py:463-470,565-570,631-636` | steps/cfg/strength validation copy-pasted across generate_image, transform_image, inpaint_image. Extract shared validators. |
| CQ-M2 | Duplicated output extraction in progress.py | `progress.py:103-112,133-143,265-276` | `("images","gifs")` iteration pattern repeated 3 times. Extract helper. |
| CQ-M3 | Duplicate txt2img workflow definition | `generation.py:142-182` vs `templates.py:9-49` | `_DEFAULT_TXT2IMG` duplicates `_TXT2IMG` template. generate_image should use `create_from_template`. |
| CQ-M4 | Inline sanitizer fallback duplicates PathSanitizer | `generation.py:33-49` | Dead code path when sanitizer is None; partially reimplements sanitizer with bugs. Remove. |
| CQ-M5 | Fragile negative prompt assignment by index | `templates.py:670-673` | `clip_nodes[1]` assumed to be negative prompt. Breaks with 3+ CLIPTextEncode nodes. |
| CQ-M6 | ModelManagerDetector and ComfyUIManagerDetector near-identical | `model_manager.py` / `node_manager.py` | Same pattern: asyncio.Lock, `_probe`, `_checked`/`_available`. Extract base class. |
| CQ-M7 | Broad `except Exception` in validate_workflow | `validation.py:272-273` | Silently swallows bugs (TypeError, AttributeError) as "internal errors". |
| CQ-M8 | Inconsistent rate limiter category assignment | `server.py:80-87`, tool files | `get_queue` (read-only) uses workflow limiter (10/min); `create_workflow`/`modify_workflow` use read limiter despite being write ops. |

### Low

| ID | Finding | File | Description |
|----|---------|------|-------------|
| CQ-L1 | `ProgressState.to_dict()` manual serialization | `progress.py:37-52` | Manual None-check per field; use `dataclasses.asdict` with filter or Pydantic. |
| CQ-L2 | Fragile env var type coercion | `config.py:158-172` | Hardcoded key-name check for int casting; adding new int fields requires list update. |
| CQ-L3 | `_cleanup` uses `asyncio.run()` in atexit | `server.py:238-250` | May conflict with running event loop; suppressed but cleanup may silently fail. |
| CQ-L4 | Node auditor patterns may be overly broad | `node_auditor.py:23-31` | `python` pattern flags benign nodes. Consider allowlist for false positives. |
| CQ-L5 | Missing specific type annotations on dict returns | Multiple client/tool files | Bare `dict`/`list` return types reduce IDE support. Use `dict[str, Any]`. |
| CQ-L6 | `_redact_sensitive` only checks top-level keys | `audit.py:19-21` | Nested dicts not redacted. Apply recursively. |
| CQ-L7 | Fixed 1-second polling interval | `progress.py:254` | Use exponential backoff (0.5s to 5s) for long workflows. |
| CQ-L8 | search_custom_nodes order-dependent results | `nodes.py:196-219` | Linear scan with break at limit; results not relevance-ranked. |

---

## Architecture Findings

### High

| ID | Finding | Impact | Description |
|----|---------|--------|-------------|
| AR-H1 | Module-level `_build_server()` import-time side effects | Testability, tooling | Same as CQ-H2. Config loading, HTTP client, atexit all fire on import. Defer behind lazy accessor. |
| AR-H2 | Dual code paths in `get_image` with different security properties | Security consistency | Same as CQ-H3. External URL path bypasses `_request()` safeguards entirely. Isolate or remove. |

### Medium

| ID | Finding | Impact | Description |
|----|---------|--------|-------------|
| AR-M1 | Duplicate txt2img workflow definition | Drift risk | Same as CQ-M3. generate_image maintains separate template. |
| AR-M2 | Fallback sanitizer dead code | Security surface inconsistency | Same as CQ-M4. Remove and make sanitizer required. |
| AR-M3 | `_register_all_tools` has 16 parameters | Fragility | Wiring function signature grows with each tool group. Introduce dependency container dataclass. |
| AR-M4 | Inconsistent return types across tools | API predictability | Mix of str (JSON), dict, list. Standardize: all tools return str with JSON for structured data. |
| AR-M5 | `get_models` client method doesn't validate folder segment | Defense-in-depth gap | Add `_validate_path_segment(folder)` to client for defense-in-depth. |
| AR-M6 | No caching for `get_object_info()` | Performance | Full node registry fetched on every call. Add 60s TTL cache with invalidation on restart. |
| AR-M7 | `_handle_restart` crosses multiple concerns | Testability | Queue safety, rebooting, polling, and auditing bundled. Split into composable functions. |

### Low

| ID | Finding | Impact | Description |
|----|---------|--------|-------------|
| AR-L1 | discovery.py growing beyond its domain | Cohesion | Model presets and prompting guides are generation knowledge, not discovery. Consider extraction. |
| AR-L2 | `search_http` client lifecycle via atexit | Resource management | May leak on process exit. Consider per-request client or FastMCP lifecycle hooks. |
| AR-L3 | Mixed data model approaches (TypedDict, dataclass, Pydantic) | Cognitive overhead | Contextually appropriate but undocumented convention. |
| AR-L4 | Sync vs async audit logging inconsistency in docs | Documentation | CLAUDE.md says `audit.log()` but tools use `audit.async_log()`. Update docs. |
| AR-L5 | Node auditor false positives may erode trust | Operational | Broad patterns flag benign nodes. Consider two-tier approach. |

---

## Critical Issues for Phase 2 Context

1. **TOCTOU race in audit logger** (CQ-C1) — security implications for audit integrity
2. **HTTP retry gaps** (CQ-H1, CQ-H3) — transient failures not handled consistently; external URL path bypasses all safeguards
3. **Inconsistent rate limiter mapping** (CQ-M8) — read-only ops on write limiter and vice versa
4. **Broad exception catch in validation** (CQ-M7) — can mask security-related errors
5. **Client missing path validation on `get_models`** (AR-M5) — defense-in-depth gap
6. **No object_info caching** (AR-M6) — repeated full registry fetches
