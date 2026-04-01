# Phase 3: Testing & Documentation Review

## Test Coverage Findings

**Overall: 441 tests, 93% line coverage, all passing.**

### High

| ID | Finding | Description |
|----|---------|-------------|
| TST-H1 | No concurrency test for `_get_client()` | Race condition on lazy init: two concurrent coroutines can create duplicate httpx clients. No test exercises this. |
| TST-H2 | No test for 5xx HTTP retry behavior | `test_no_retry_on_http_error` verifies current behavior (no retry on 5xx). No test for desired retry-on-transient-5xx behavior. |
| TST-H3 | Audit logger TOCTOU gap: detection tested, prevention untested | Symlink detection works, but `open()` uses plain mode (no `O_NOFOLLOW`). Test verifies detection, not atomic prevention. |
| TST-H4 | No regression test for blocked endpoints | CLAUDE.md rule 1 blocks `/userdata`, `/free`, `/users`, `/history POST`. No test scans client.py to enforce this invariant. |

### Medium

| ID | Finding | Description |
|----|---------|-------------|
| TST-M1 | No test for rate-limiter-to-tool category mapping | No verification that each tool uses the correct limiter category (e.g., `get_queue` on read vs. workflow). |
| TST-M2 | No test for `get_object_info` caching | No TTL or invalidation tests (cache not yet implemented). |
| TST-M3 | `build_image_url` scheme validation untested | `javascript:` and `file:` URL schemes not tested. |
| TST-M4 | No concurrent tool invocation tests | Rate limiter only unit-tested, not under concurrent load. |

### Low

| ID | Finding | Description |
|----|---------|-------------|
| TST-L1 | `test_tokens_replenish_over_time` uses real `time.sleep(1.1)` | Potential flakiness under CI load. Use time-mocking. |
| TST-L2 | Some tool tests assert loosely on string containment | e.g., `"test.png" in result` — could match spuriously if format changes. |
| TST-L3 | Tests access private `audit._audit_file` | Couples tests to internal storage implementation. |
| TST-L4 | `close()` / context manager not tested | `client.py:80-89` uncovered. |
| TST-L5 | Disallowed HTTP method rejection not tested | `_request` method validation at line 65. |
| TST-L6 | 13 uncovered lines in `workflow/operations.py` error branches | May include dead code. |
| TST-L7 | No test for repeated WS disconnection resilience | Only single fallback tested. |

---

## Documentation Findings

### High

| ID | Finding | Description |
|----|---------|-------------|
| DOC-H1 | `_build_server()` return type wrong in CLAUDE.md | Rule 10 says `tuple[FastMCP, Settings]` but actual is `tuple[FastMCP, Settings, ComfyUIClient, httpx.AsyncClient]`. |

### Medium

| ID | Finding | Description |
|----|---------|-------------|
| DOC-M1 | Project structure trees missing files | CLAUDE.md and README omit `tools/nodes.py`, `node_manager.py`, `model_registry.py`. `files.py` description missing `get_workflow_from_image`. |
| DOC-M2 | Missing config docs for model extensions/download domains | `allowed_model_extensions` and `allowed_download_domains` not in README YAML example. |
| DOC-M3 | SSE env vars undocumented | No env var support for SSE transport config; not documented as YAML-only. |
| DOC-M4 | `ComfyUIClient` class lacks docstrings | No class docstring, many public methods undocumented. |
| DOC-M5 | Template `_apply_params` positional convention undocumented | First CLIPTextEncode=prompt, second=negative prompt — fragile and unexplained. |
| DOC-M6 | Rate limit categories not mapped to tools | Config shows 4 categories but doesn't explain which tools belong to which. |

### Low

| ID | Finding | Description |
|----|---------|-------------|
| DOC-L1 | Missing class docstrings on `PathSanitizer`, `WorkflowInspector` | Purpose and config not documented at class level. |
| DOC-L2 | Several tools lack `Returns:` sections | `list_models`, `get_queue`, `get_job`, `get_history` missing return descriptions. |
| DOC-L3 | `websockets` dependency not in CLAUDE.md tech stack | Used by `progress.py` but omitted from tech stack section. |
| DOC-L4 | README version tag example is stale | Uses `v0.1.7`, current is `v0.1.10`. Use placeholder. |
| DOC-L5 | Mermaid architecture diagram incomplete | Missing Model Manager Detector, Download Validator, Model Checker. |
| DOC-L6 | `create_workflow` lacks parameter example | Complex `params` JSON has no usage example in docstring. |
| DOC-L7 | `max_search_results` security cap behavior undocumented | Server-side cap on search results not explained in config docs. |
