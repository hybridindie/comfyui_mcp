# Phase 4: Best Practices & Standards

## Framework & Language Findings

### High

| ID | Finding | Description |
|----|---------|-------------|
| FW-H1 | SSE transport config uses deprecated pattern | `mcp.run(transport="sse", host=..., port=...)` with `type: ignore`. Host/port should be in `FastMCP()` constructor. |
| FW-H2 | `atexit` cleanup instead of FastMCP `lifespan` | `asyncio.run()` in atexit is fragile. FastMCP v1.26 supports `lifespan` async context manager for proper resource cleanup. |
| FW-H3 | `_get_client()` race condition (confirmed) | No `asyncio.Lock` on lazy httpx client init. Concurrent coroutines can leak connection pools. |
| FW-H4 | No retry on transient 5xx (confirmed) | `HTTPStatusError` from `raise_for_status()` not caught for 502/503/504. |

### Medium

| ID | Finding | Description |
|----|---------|-------------|
| FW-M1 | SSE transport deprecated in MCP SDK | MCP spec now prefers "Streamable HTTP". SSE maintained for backward compat but is legacy. |
| FW-M2 | Unbounded `get_history()` (confirmed) | No `max_items` parameter. Multi-MB responses on busy servers. |
| FW-M3 | No `get_object_info()` cache (confirmed) | 2-10 MB per call, used by 4+ tools. Add TTL cache. |
| FW-M4 | TOCTOU in audit logger (confirmed) | Race window between symlink check and `open()`. Partially mitigated. |
| FW-M5 | `pytest-asyncio` floor version outdated | Floor at `>=0.25.0`, installed is `1.3.0`. Major version jump undocumented. |

### Low

| ID | Finding | Description |
|----|---------|-------------|
| FW-L1 | `from __future__ import annotations` unnecessary | Python 3.12+ has native support. ~25 files with redundant import. |
| FW-L2 | Pre-commit ruff/mypy versions behind installed | `ruff v0.8.6` vs installed `v0.15.4`; `mypy v1.13.0` vs `v1.19.1`. |
| FW-L3 | `ProgressState.to_dict()` manual serialization | Could use `dataclasses.asdict()` with filter. |
| FW-L4 | `pydantic-settings` installed but not leveraged | Transitive dep from `mcp[cli]`. Could replace manual env override logic. |
| FW-L5 | Streamable HTTP transport not offered | MCP SDK v1.26 supports it; only stdio and SSE available. |
| FW-L6 | mypy `strict = false` | Good type annotations exist but not fully enforced. |
| FW-L7 | No Python 3.13 testing or classifier | Only 3.12 tested; 3.13 has been stable since Oct 2024. |

---

## CI/CD & DevOps Findings

### High

| ID | Finding | Description |
|----|---------|-------------|
| CD-H1 | Docker build not gated on CI passing | `docker.yml` triggers independently. Broken images can be published to GHCR. |
| CD-H2 | PyPI publish not gated on CI | `pypi.yml` on tag push with no test gate. Untested packages can ship. |
| CD-H3 | No security scanning in CI | No SAST, dependency scanning, or container image scanning. Critical gap for security-focused project. |
| CD-H4 | docker-compose volume paths mismatch user | Mounts to `/root/` but container runs as `app` user. Config and audit logs inaccessible. |

### Medium

| ID | Finding | Description |
|----|---------|-------------|
| CD-M1 | No coverage threshold enforcement | `--cov` runs but no `--cov-fail-under`. Coverage can silently regress. |
| CD-M2 | No health check in Dockerfile/compose | Orchestrators can't detect unresponsive server. |
| CD-M3 | No log rotation for audit logs | Single file grows unbounded. Risk: disk exhaustion. |
| CD-M4 | No structured metrics or health endpoint | Only JSON audit log. No rate limiter, error rate, or latency monitoring. |
| CD-M5 | Audit log failures silently swallowed | `_logger.error()` only. No alerting, no fail-closed option. |
| CD-M6 | No changelog | Release notes only in git commits. |
| CD-M7 | Manual version bumping | Hardcoded in pyproject.toml, bundled with feature commits. |
| CD-M8 | No Dependabot/Renovate | Dependencies won't get automated update PRs. |
| CD-M9 | No branch protection enforcement evidence | Docker/PyPI workflows trigger independently of CI. |
| CD-M10 | Some GitHub Actions not pinned to SHA | `upload-artifact`, `download-artifact`, `pypi-publish` use floating tags. |
| CD-M11 | No resource limits in docker-compose | No mem_limit or CPU constraints. |

### Low

| ID | Finding | Description |
|----|---------|-------------|
| CD-L1 | No Python version matrix in CI | Only 3.12 tested; `>=3.12` in pyproject.toml. |
| CD-L2 | docker-compose uses deprecated `version` key | Ignored by Docker Compose v2+, generates warnings. |
| CD-L3 | No `.env.example` | Supported env vars documented only in code. |
| CD-L4 | Smoke test not integrated into CI | Manual-only; no `workflow_dispatch` job. |
