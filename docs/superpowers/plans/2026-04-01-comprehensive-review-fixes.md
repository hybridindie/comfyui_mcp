# Comprehensive Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address all findings from the comprehensive code review (P0 through P2 + impactful P3), covering security, reliability, performance, CI/CD, and code quality improvements.

**Architecture:** Changes are grouped by file to minimize conflicts. Each task is independent and can be committed separately. The server.py refactor (Task 4) depends on client.py changes (Task 2) being complete first. CI/CD changes (Task 7) are fully independent.

**Tech Stack:** Python 3.12, FastMCP 1.26.0, httpx, pydantic, pytest, GitHub Actions

---

## File Map

| File | Changes |
|------|---------|
| `src/comfyui_mcp/audit.py` | TOCTOU fix (O_NOFOLLOW), recursive redaction, expanded sensitive keys |
| `src/comfyui_mcp/client.py` | asyncio.Lock, 5xx retry, path validation, get_history max_items, get_object_info cache, remove external URL path in get_image |
| `src/comfyui_mcp/config.py` | TLS bypass warning, repr=False on tokens |
| `src/comfyui_mcp/server.py` | Full refactor: lifespan, SSE wiring, rate limiter mapping, dependency container |
| `src/comfyui_mcp/progress.py` | Exponential backoff, extract output helper |
| `src/comfyui_mcp/security/inspector.py` | Expanded suspicious patterns |
| `src/comfyui_mcp/workflow/validation.py` | Narrow exception catch |
| `src/comfyui_mcp/tools/generation.py` | Extract validators, remove dead sanitizer fallback, consolidate txt2img, JSON size limit |
| `src/comfyui_mcp/tools/workflow.py` | JSON size limit |
| `src/comfyui_mcp/tools/files.py` | PNG metadata total size limit |
| `src/comfyui_mcp/tools/jobs.py` | Standardize returns to str |
| `src/comfyui_mcp/tools/history.py` | Pass max_items, standardize returns |
| `src/comfyui_mcp/tools/discovery.py` | Standardize returns to str, parallel get_system_info |
| `src/comfyui_mcp/tools/models.py` | HF model_id validation |
| `src/comfyui_mcp/tools/nodes.py` | Relevance-ranked search |
| `.github/workflows/ci.yml` | Coverage threshold |
| `.github/workflows/docker.yml` | Gate on CI |
| `.github/workflows/pypi.yml` | Gate on CI, pin actions |
| `.github/dependabot.yml` | New: dependency update automation |
| `docker-compose.yml` | Fix volume paths, remove deprecated version |
| `CLAUDE.md` | Fix _build_server() return type, update project structure |
| `tests/test_client.py` | 5xx retry, concurrent _get_client, build_image_url scheme |
| `tests/test_blocked_endpoints.py` | New: regression test for blocked endpoints |
| `tests/test_audit.py` | TOCTOU O_NOFOLLOW verification |

---

### Task 1: Fix audit.py — TOCTOU, recursive redaction, expanded keys

**Files:**
- Modify: `src/comfyui_mcp/audit.py`
- Test: `tests/test_audit.py`

**Findings:** CQ-C1, SEC-L1

- [ ] **Step 1: Fix TOCTOU race — use `os.open()` with O_NOFOLLOW**

In `audit.py`, replace the `open()` call with `os.open()` + `os.fdopen()`:

```python
# In _write_record, replace:
#   with open(self._audit_file, "a") as f:
#       f.write(record.model_dump_json() + "\n")
# With:
import os as _os
fd = _os.open(
    str(self._audit_file),
    _os.O_WRONLY | _os.O_APPEND | _os.O_CREAT | _os.O_NOFOLLOW,
    0o600,
)
try:
    _os.write(fd, (record.model_dump_json() + "\n").encode())
finally:
    _os.close(fd)
```

Add `import os as _os` at top of file (rename to avoid shadowing).

- [ ] **Step 2: Expand sensitive keys and make redaction recursive**

Replace `_SENSITIVE_KEYS` and `_redact_sensitive`:

```python
_SENSITIVE_PATTERNS = frozenset({
    "token", "password", "secret", "api_key", "authorization",
    "access_token", "refresh_token", "credential", "private_key",
    "bearer", "session_id",
})

def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return any(p in lower for p in _SENSITIVE_PATTERNS)

def _redact_sensitive(data: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for k, v in data.items():
        if _is_sensitive_key(k):
            continue
        if isinstance(v, dict):
            result[k] = _redact_sensitive(v)
        else:
            result[k] = v
    return result
```

- [ ] **Step 3: Update tests for TOCTOU and recursive redaction**

Add test for O_NOFOLLOW behavior and nested redaction in `tests/test_audit.py`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_audit.py -v`

- [ ] **Step 5: Commit**

```
fix(audit): use O_NOFOLLOW to prevent TOCTOU symlink race, expand sensitive redaction
```

---

### Task 2: Fix client.py — Lock, retry, validation, caching, history limit

**Files:**
- Modify: `src/comfyui_mcp/client.py`
- Test: `tests/test_client.py`

**Findings:** CQ-H1, PERF-H3, SEC-M2, SEC-M3, PERF-H1, PERF-H2, CQ-H3

- [ ] **Step 1: Add asyncio.Lock to _get_client()**

```python
def __init__(self, ...):
    ...
    self._init_lock = asyncio.Lock()

async def _get_client(self) -> httpx.AsyncClient:
    if self._client is not None:
        return self._client
    async with self._init_lock:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                verify=self._tls_verify,
            )
    return self._client
```

- [ ] **Step 2: Add 5xx retry logic**

Add `_RETRYABLE_STATUS_CODES` constant and update `_request()`:

```python
_RETRYABLE_STATUS_CODES = frozenset({502, 503, 504})

async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
    normalized = method.upper()
    if normalized not in _ALLOWED_HTTP_METHODS:
        raise ValueError(f"HTTP method not allowed: {method!r}")
    last_exception: Exception | None = None
    for attempt in range(self._max_retries):
        try:
            c = await self._get_client()
            r = await c.request(normalized, path, **kwargs)
            if r.status_code in _RETRYABLE_STATUS_CODES and attempt < self._max_retries - 1:
                last_exception = httpx.HTTPStatusError(
                    f"Server returned {r.status_code}", request=r.request, response=r
                )
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except httpx.RequestError as e:
            last_exception = e
            if attempt < self._max_retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
            continue
    raise last_exception or RuntimeError("Request failed")
```

- [ ] **Step 3: Add _validate_path_segment to get_models and get_view_metadata**

```python
async def get_models(self, folder: str) -> list:
    _validate_path_segment(folder, label="folder")
    r = await self._request("get", f"/models/{folder}")
    return r.json()

async def get_view_metadata(self, folder: str, filename: str) -> dict:
    _validate_path_segment(folder, label="folder")
    _validate_path_segment(filename, label="filename")
    r = await self._request("get", f"/view_metadata/{folder}", params={"filename": filename})
    return r.json()
```

- [ ] **Step 4: Add max_items to get_history()**

```python
async def get_history(self, max_items: int | None = None) -> dict:
    params: dict[str, int] = {}
    if max_items is not None:
        params["max_items"] = max_items
    r = await self._request("get", "/history", params=params or None)
    return r.json()
```

- [ ] **Step 5: Add TTL cache to get_object_info()**

Add `import time` at top if not present. Add cache fields to `__init__` and update method:

```python
# In __init__:
self._object_info_cache: dict | None = None
self._object_info_ts: float = 0.0
_OBJECT_INFO_TTL = 300.0  # 5 minutes

async def get_object_info(self, node_class: str | None = None) -> dict:
    if node_class is not None:
        _validate_path_segment(node_class, label="node_class")
        r = await self._request("get", f"/object_info/{node_class}")
        return r.json()
    now = time.monotonic()
    if self._object_info_cache is not None and (now - self._object_info_ts) < self._OBJECT_INFO_TTL:
        return self._object_info_cache
    r = await self._request("get", "/object_info")
    self._object_info_cache = r.json()
    self._object_info_ts = now
    return self._object_info_cache
```

- [ ] **Step 6: Remove external URL path from get_image()**

Remove the `base_url` parameter branch. The `get_image` method should always use `_request`:

```python
async def get_image(
    self,
    filename: str,
    subfolder: str = "output",
) -> tuple[bytes, str]:
    r = await self._request(
        "get",
        "/view",
        params={"filename": filename, "subfolder": subfolder, "type": "output"},
    )
    content_type = r.headers.get("content-type", "image/png")
    return r.content, content_type
```

Update `tools/files.py` `get_image` tool to remove `base_url` usage in the `data_uri` path (it's already not passing it — just confirm).

- [ ] **Step 7: Write tests for all client changes**

In `tests/test_client.py`, add:
- `test_concurrent_get_client_returns_same_instance`
- `test_retry_on_502_then_succeed`
- `test_no_retry_on_4xx`
- `test_get_models_validates_path_segment`
- `test_get_view_metadata_validates_path_segment`
- `test_get_history_max_items`
- `test_get_object_info_cache_ttl`
- `test_build_image_url_rejects_javascript_scheme`

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/test_client.py -v`

- [ ] **Step 9: Commit**

```
fix(client): add init lock, 5xx retry, path validation, history limit, object_info cache
```

---

### Task 3: Fix config.py — TLS warning, token repr

**Files:**
- Modify: `src/comfyui_mcp/config.py`

**Findings:** SEC-M8, SEC-M6

- [ ] **Step 1: Add TLS bypass warning**

Add a `field_validator` for `tls_verify` on `ComfyUISettings`:

```python
@field_validator("tls_verify")
@classmethod
def warn_tls_disabled(cls, v: bool) -> bool:
    if not v:
        import logging
        logging.getLogger("comfyui_mcp.config").warning(
            "TLS verification disabled — connections are vulnerable to MITM attacks. "
            "Only use for local development.",
        )
    return v
```

- [ ] **Step 2: Add repr=False to sensitive fields**

```python
class ModelSearchSettings(BaseModel):
    huggingface_token: str = Field(default="", repr=False)
    civitai_api_key: str = Field(default="", repr=False)
    max_search_results: int = 10
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_config.py -v`

- [ ] **Step 4: Commit**

```
fix(config): warn on TLS verify disabled, hide tokens from repr
```

---

### Task 4: Refactor server.py — lifespan, SSE, rate limiters, dependency container

**Files:**
- Modify: `src/comfyui_mcp/server.py`
- Test: `tests/test_server.py` (if exists)

**Findings:** FW-H1, FW-H2, CQ-H2, CQ-M8, AR-M3, SEC-M4

**Depends on:** Task 2 (client.py changes)

- [ ] **Step 1: Create ToolDependencies dataclass**

Replace the 16-param `_register_all_tools` with a dependency container:

```python
from dataclasses import dataclass

@dataclass
class ToolDependencies:
    client: ComfyUIClient
    audit: AuditLogger
    rate_limiters: dict[str, RateLimiter]
    inspector: WorkflowInspector
    sanitizer: PathSanitizer
    node_auditor: NodeAuditor
    progress: WebSocketProgress
    model_sanitizer: PathSanitizer
    download_validator: DownloadValidator
    model_checker: ModelChecker
    model_search_settings: ModelSearchSettings
    search_http: httpx.AsyncClient
    image_view_base_url: str | None
    detector: ModelManagerDetector
    node_manager: ComfyUIManagerDetector
```

- [ ] **Step 2: Fix rate limiter category assignments**

In the new `_register_all_tools` (which takes `deps: ToolDependencies`):
- `get_queue`, `get_queue_status` → `deps.rate_limiters["read"]`
- `cancel_job`, `interrupt`, `clear_queue` → `deps.rate_limiters["workflow"]`
- `install_custom_node`, `uninstall_custom_node`, `update_custom_node` → `deps.rate_limiters["workflow"]` (keep)

Update `register_job_tools` call: pass `read_limiter` as the primary limiter for `get_queue`/`get_queue_status`, and `workflow` limiter for mutating ops. The `register_job_tools` already takes both `limiter` and `read_limiter` — swap which is which:

```python
register_job_tools(
    server,
    deps.client,
    deps.audit,
    deps.rate_limiters["workflow"],  # for cancel/interrupt/clear
    read_limiter=deps.rate_limiters["read"],  # for get_queue, get_queue_status, get_progress
    progress=deps.progress,
)
```

Then in `jobs.py`, switch `get_queue` and `get_queue_status` to use `read_limiter`:

```python
# get_queue: change limiter.check to read_limiter
rl = read_limiter if read_limiter is not None else limiter
rl.check("get_queue")

# get_queue_status: same pattern
rl = read_limiter if read_limiter is not None else limiter
rl.check("get_queue_status")
```

- [ ] **Step 3: Add lifespan context manager, replace atexit**

```python
import contextlib
from collections.abc import AsyncIterator

@contextlib.asynccontextmanager
async def _lifespan(app: FastMCP) -> AsyncIterator[None]:
    yield
    # Cleanup on shutdown
    await _client.close()
    await _search_http.aclose()
```

Pass `lifespan=_lifespan` to `FastMCP()` constructor. Remove `atexit.register(_cleanup)` and the `_cleanup` function.

- [ ] **Step 4: Fix SSE wiring — pass host/port to FastMCP constructor**

```python
server_kwargs: dict[str, Any] = {
    "name": "ComfyUI",
    "instructions": "...",
    "lifespan": _lifespan,
}

# Add SSE host/port to constructor if SSE is enabled
if settings.transport.sse.enabled:
    server_kwargs["host"] = settings.transport.sse.host
    server_kwargs["port"] = settings.transport.sse.port

server = FastMCP(**server_kwargs)
```

Then in `main()`:
```python
def main() -> None:
    if _settings.transport.sse.enabled:
        mcp.run(transport="sse")
    else:
        mcp.run()
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest -v`

- [ ] **Step 6: Commit**

```
refactor(server): add lifespan, fix SSE wiring, fix rate limiter categories, add ToolDependencies
```

---

### Task 5: Fix tool files — validators, returns, limits, dedup

**Files:**
- Modify: `src/comfyui_mcp/tools/generation.py`
- Modify: `src/comfyui_mcp/tools/workflow.py`
- Modify: `src/comfyui_mcp/tools/files.py`
- Modify: `src/comfyui_mcp/tools/jobs.py`
- Modify: `src/comfyui_mcp/tools/history.py`
- Modify: `src/comfyui_mcp/tools/discovery.py`
- Modify: `src/comfyui_mcp/tools/models.py`
- Modify: `src/comfyui_mcp/tools/nodes.py`

**Findings:** CQ-M1, CQ-M3, CQ-M4, AR-M4, SEC-L4, SEC-L5, PERF-M8, SEC-M9

- [ ] **Step 1: generation.py — extract shared validators, remove dead code, add JSON size limit**

Add shared validators at module level:

```python
_MAX_WORKFLOW_JSON_BYTES = 10 * 1024 * 1024  # 10 MB

def _validate_steps(steps: int) -> None:
    if steps < 1 or steps > 100:
        raise ValueError("steps must be between 1 and 100")

def _validate_cfg(cfg: float) -> None:
    if cfg < 1.0 or cfg > 30.0:
        raise ValueError("cfg must be between 1.0 and 30.0")

def _validate_strength(strength: float) -> None:
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength must be between 0.0 and 1.0")

def _validate_workflow_json(raw: str) -> dict:
    if len(raw) > _MAX_WORKFLOW_JSON_BYTES:
        raise ValueError(f"Workflow JSON exceeds maximum size ({_MAX_WORKFLOW_JSON_BYTES} bytes)")
    try:
        wf = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON workflow: {e}") from e
    return wf
```

Replace inline validation calls in `generate_image`, `transform_image`, `inpaint_image` with these helpers.

Remove `_validate_image_filename` fallback branch (make `sanitizer` required — `PathSanitizer` type, not `PathSanitizer | None`).

Remove `_DEFAULT_TXT2IMG` and `_build_txt2img_workflow`. Replace with `create_from_template("txt2img", params)` in `generate_image`.

Use `_validate_workflow_json` in `run_workflow` and `run_workflow_stream`.

- [ ] **Step 2: workflow.py — add JSON size limit**

Use the same `_MAX_WORKFLOW_JSON_BYTES` pattern for `create_workflow`, `modify_workflow`, `validate_workflow` — add size check before `json.loads()`.

- [ ] **Step 3: files.py — add total metadata size limit**

In `_extract_png_metadata`, add total size tracking:

```python
_MAX_TOTAL_METADATA_BYTES = 50 * 1024 * 1024  # 50 MB total

# Inside the while loop, after extracting value:
total_metadata_size += len(value)
if total_metadata_size > _MAX_TOTAL_METADATA_BYTES:
    break
```

- [ ] **Step 4: Standardize tool return types to str (JSON)**

Tools that currently return `dict` or `list` need to return `json.dumps(...)`:

**jobs.py:**
- `get_queue() -> str`: return `json.dumps(await client.get_queue())`
- `get_job() -> str`: return `json.dumps(await client.get_history_item(prompt_id))`
- `get_queue_status() -> str`: return `json.dumps(await client.get_prompt_status())`

**history.py:**
- `get_history() -> str`: return `json.dumps(await client.get_history(max_items=200))`

**discovery.py:**
- `list_models() -> str`: return `json.dumps(await client.get_models(folder))`
- `list_nodes() -> str`: return `json.dumps(sorted(info.keys()))`
- `get_node_info() -> str`: return `json.dumps(await client.get_object_info(node_class))`
- `list_workflows() -> str`: return `json.dumps(await client.get_workflow_templates())`
- `list_extensions() -> str`: return `json.dumps(await client.get_extensions())`
- `get_server_features() -> str`: return `json.dumps(await client.get_features())`
- `list_model_folders() -> str`: return `json.dumps(await client.get_model_types())`
- `get_model_metadata() -> str`: return `json.dumps(await client.get_view_metadata(...))`
- `audit_dangerous_nodes() -> str`: return `json.dumps(output)`
- `get_system_info() -> str`: return `json.dumps(result)` (also parallelize the two API calls with `asyncio.gather`)
- `get_model_presets() -> str`: return `json.dumps({...})`
- `get_prompting_guide() -> str`: return `json.dumps({...})`

**files.py:**
- `list_outputs() -> str`: return `json.dumps(sorted(filenames))`
- `get_workflow_from_image() -> str`: return `json.dumps({...})`

- [ ] **Step 5: models.py — validate HuggingFace model_id**

In `_fetch_hf_model_detail`, add validation:

```python
import re
_HF_REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")

model_id = model.get("id", "")
if not _HF_REPO_RE.match(model_id):
    return {"name": model_id, "type": "", "url": "", "filename": "", "size_mb": 0, "downloads": 0, "likes": 0, "source": "huggingface"}
```

- [ ] **Step 6: nodes.py — relevance-ranked search**

Replace the linear scan in `search_custom_nodes`:

```python
scored: list[tuple[float, dict[str, str]]] = []
for pack_id, pack_info in node_packs.items():
    if not isinstance(pack_info, dict):
        continue
    name = pack_info.get("name", "")
    description = pack_info.get("description", "")
    author = pack_info.get("author", "")
    name_lower = name.lower()
    score = 0.0
    if query_lower == name_lower:
        score = 3.0
    elif query_lower in name_lower:
        score = 2.0
    elif query_lower in description.lower():
        score = 1.0
    elif query_lower in author.lower():
        score = 0.5
    else:
        continue
    scored.append((score, {
        "id": pack_id,
        "name": name,
        "description": description,
        "author": author,
        "installed": pack_info.get("installed", "false"),
    }))

scored.sort(key=lambda x: -x[0])
results = [item for _, item in scored[:_MAX_SEARCH_RESULTS]]
```

- [ ] **Step 7: Run all tests, fix any that break from return type changes**

Run: `uv run pytest -v`

Expected: Many tests will need updating to handle `str` returns instead of `dict`/`list`. Parse with `json.loads()` in tests.

- [ ] **Step 8: Commit**

```
refactor(tools): standardize returns to JSON str, extract validators, add size limits
```

---

### Task 6: Fix progress.py, validation.py, inspector.py

**Files:**
- Modify: `src/comfyui_mcp/progress.py`
- Modify: `src/comfyui_mcp/workflow/validation.py`
- Modify: `src/comfyui_mcp/security/inspector.py`

**Findings:** PERF-M3, CQ-M2, CQ-M7, SEC-L2

- [ ] **Step 1: progress.py — exponential backoff and extract output helper**

Replace fixed `await asyncio.sleep(1.0)` in `_poll_until_complete` with exponential backoff:

```python
async def _poll_until_complete(self, prompt_id: str, start_time: float) -> ProgressState:
    interval = 1.0
    while True:
        elapsed = time.monotonic() - start_time
        if elapsed >= self._timeout:
            state = ProgressState(prompt_id=prompt_id, status="timeout")
            state.elapsed_seconds = round(elapsed, 2)
            return state
        state = await self.get_state(prompt_id)
        if state.status in ("completed", "error"):
            state.elapsed_seconds = round(time.monotonic() - start_time, 2)
            return state
        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 10.0)
```

Extract output helper to DRY the 3 copies:

```python
@staticmethod
def _extract_outputs(node_id: str, node_output: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key in ("images", "gifs"):
        for item in node_output.get(key, []):
            items.append({
                "node_id": node_id,
                "filename": item.get("filename", ""),
                "subfolder": item.get("subfolder", ""),
            })
    return items
```

Replace the 3 duplication sites with calls to this helper.

- [ ] **Step 2: validation.py — narrow exception catch**

Replace:
```python
except Exception as e:
    errors.append(f"Security inspection failed due to an internal error: {e}")
```
With:
```python
except Exception:
    import logging
    logging.getLogger(__name__).exception("Security inspection failed unexpectedly")
    errors.append("Security inspection failed due to an internal error")
```

- [ ] **Step 3: inspector.py — expand suspicious patterns**

Add additional patterns:
```python
_SUSPICIOUS_PATTERNS = [
    re.compile(r"__import__\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\bos\.system\s*\("),
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bopen\s*\(.+,\s*['\"]w"),
    re.compile(r"\bimportlib\b"),
    re.compile(r"\bpickle\.loads?\b"),
    re.compile(r"\bos\.(popen|execv|spawn)"),
    re.compile(r"\bctypes\b"),
]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -v`

- [ ] **Step 5: Commit**

```
fix: exponential backoff in polling, narrow exception catch, expand suspicious patterns
```

---

### Task 7: CI/CD fixes — gates, scanning, docker-compose

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/docker.yml`
- Modify: `.github/workflows/pypi.yml`
- Create: `.github/dependabot.yml`
- Modify: `docker-compose.yml`

**Findings:** CD-H1, CD-H2, CD-H3, CD-H4, CD-M1, CD-M10

- [ ] **Step 1: Add coverage threshold to CI**

In `ci.yml`, update the pytest command:
```yaml
- name: Run tests
  run: uv run pytest -v --cov=src/comfyui_mcp --cov-report=term-missing --cov-fail-under=90
```

- [ ] **Step 2: Add pip-audit to CI**

Add a `security` job to `ci.yml`:
```yaml
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4
      - name: Install uv
        uses: astral-sh/setup-uv@e4db8464a088ece1b920f60402e813ea4de65b8f  # v4
      - name: Set up Python
        run: uv python install 3.12
      - name: Install dependencies
        run: uv sync
      - name: Audit dependencies
        run: uv run pip-audit
```

Add `pip-audit` to dev dependencies in `pyproject.toml`.

- [ ] **Step 3: Gate docker.yml on CI**

Add `workflow_call` trigger to `ci.yml` and `needs` to `docker.yml`. Or simpler: add CI jobs directly:

```yaml
# docker.yml - add at the top of jobs:
  ci:
    uses: ./.github/workflows/ci.yml

  docker:
    needs: [ci]
    runs-on: ubuntu-latest
    # ... rest unchanged
```

Wait — that requires ci.yml to support `workflow_call`. Add trigger:

```yaml
# ci.yml - update on:
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_call:
```

Then docker.yml:
```yaml
jobs:
  ci:
    uses: ./.github/workflows/ci.yml
  docker:
    needs: [ci]
    # ... existing steps
```

- [ ] **Step 4: Gate pypi.yml on CI and pin actions**

Same pattern for pypi.yml. Also pin the floating action tags to SHAs.

- [ ] **Step 5: Create .github/dependabot.yml**

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: docker
    directory: /
    schedule:
      interval: monthly
```

- [ ] **Step 6: Fix docker-compose.yml**

```yaml
services:
  comfyui-mcp-secure:
    build: .
    image: comfyui-mcp-secure:latest
    container_name: comfyui-mcp-secure
    environment:
      - COMFYUI_URL=${COMFYUI_URL:-http://comfyui:8188}
      - COMFYUI_SECURITY_MODE=${COMFYUI_SECURITY_MODE:-audit}
    volumes:
      - ./config.yaml:/home/app/.comfyui-mcp/config.yaml:ro
      - comfyui-mcp-secure-data:/home/app/.comfyui-mcp/logs
    restart: unless-stopped

volumes:
  comfyui-mcp-secure-data:
```

(Remove `version: "3.8"`, fix `/root/` to `/home/app/`)

- [ ] **Step 7: Commit**

```
fix(ci): gate publish on CI, add dep scanning, fix docker-compose paths
```

---

### Task 8: Tests — blocked endpoints, rate limiter mapping

**Files:**
- Create: `tests/test_blocked_endpoints.py`
- Modify: existing test files as needed

**Findings:** TST-H4, TST-M1

- [ ] **Step 1: Create blocked endpoint regression test**

```python
"""Regression tests for CLAUDE.md security rules."""
import inspect
from comfyui_mcp.client import ComfyUIClient

class TestBlockedEndpoints:
    def test_client_does_not_expose_blocked_endpoints(self):
        source = inspect.getsource(ComfyUIClient)
        blocked = ["/userdata", '"/free"', '"/users"']
        for endpoint in blocked:
            assert endpoint not in source, f"Blocked endpoint {endpoint} found in client.py"

    def test_no_history_delete(self):
        source = inspect.getsource(ComfyUIClient)
        assert "delete" not in source.lower() or "/history" not in source, \
            "History DELETE endpoint must not be exposed"
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest -v`

- [ ] **Step 3: Commit**

```
test: add blocked endpoint regression tests
```

---

### Task 9: Documentation — CLAUDE.md, README fixes

**Files:**
- Modify: `CLAUDE.md`

**Findings:** DOC-H1, DOC-M1

- [ ] **Step 1: Fix _build_server() return type**

Update rule 10 in CLAUDE.md:
```
10. **`_build_server()` returns `tuple[FastMCP, Settings, ComfyUIClient, httpx.AsyncClient]`.**
```

- [ ] **Step 2: Update project structure**

Add missing files to the tree:
- `tools/nodes.py` — Custom node management tools
- `node_manager.py` — ComfyUI Manager detector
- `model_registry.py` — Canonical model loader registry

Update `files.py` description to include `get_workflow_from_image`.

- [ ] **Step 3: Commit**

```
docs: fix _build_server return type, update project structure in CLAUDE.md
```

---

### Task 10: Lint, format, type-check, full test run

- [ ] **Step 1: Run ruff check and fix**

Run: `uv run ruff check src/ tests/ --fix`

- [ ] **Step 2: Run ruff format**

Run: `uv run ruff format src/ tests/`

- [ ] **Step 3: Run mypy**

Run: `uv run mypy src/comfyui_mcp/`

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v --cov=src/comfyui_mcp --cov-report=term-missing`

- [ ] **Step 5: Fix any failures and commit**

```
chore: fix lint, format, and type errors from review fixes
```
