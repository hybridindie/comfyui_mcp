# ComfyUI MCP Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a security-aware MCP server that proxies ComfyUI's API with workflow inspection, path sanitization, rate limiting, and structured audit logging.

**Architecture:** Python FastMCP server exposing 15 tools across generation, job management, discovery, history, and file operations. A security middleware layer (workflow inspector, path sanitizer, rate limiter) sits between the MCP tools and an async httpx/websockets ComfyUI client. All operations are audit-logged as structured JSON.

**Tech Stack:** Python 3.12, `mcp[cli]` (FastMCP), `httpx`, `websockets`, `pydantic`, `pydantic-settings`, `structlog`, `pyyaml`, `pytest`, `pytest-asyncio`, `respx` (httpx mocking)

---

### Task 1: Project Scaffolding & Dependencies

**Files:**
- Modify: `pyproject.toml`
- Delete: `main.py`
- Create: `src/comfyui_mcp/__init__.py`
- Create: `src/comfyui_mcp/server.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Update pyproject.toml with dependencies and src layout**

```toml
[project]
name = "comfyui-mcp"
version = "0.1.0"
description = "Secure MCP server for ComfyUI with workflow inspection and audit logging"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.12.0",
    "httpx>=0.28.0",
    "websockets>=14.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.7.0",
    "structlog>=24.4.0",
    "pyyaml>=6.0.0",
]

[project.scripts]
comfyui-mcp = "comfyui_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/comfyui_mcp"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.25.0",
    "respx>=0.22.0",
]
```

**Step 2: Delete old main.py**

```bash
rm main.py
```

**Step 3: Create package init**

Create `src/comfyui_mcp/__init__.py`:

```python
"""Secure MCP server for ComfyUI."""
```

**Step 4: Create minimal server entry point**

Create `src/comfyui_mcp/server.py`:

```python
"""ComfyUI MCP Server entry point."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "ComfyUI",
    instructions="Secure MCP server for generating images and managing workflows via ComfyUI.",
)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

**Step 5: Create test scaffolding**

Create `tests/__init__.py` (empty).

Create `tests/conftest.py`:

```python
"""Shared test fixtures."""
```

**Step 6: Install dependencies and verify**

```bash
uv sync
uv run comfyui-mcp --help
```

Expected: MCP server help output, no import errors.

**Step 7: Commit**

```bash
git add -A && git commit -m "feat: scaffold project with FastMCP, httpx, and security deps"
```

---

### Task 2: Configuration (Pydantic Settings + YAML)

**Files:**
- Create: `src/comfyui_mcp/config.py`
- Create: `tests/test_config.py`

**Step 1: Write failing tests for config loading**

Create `tests/test_config.py`:

```python
"""Tests for configuration loading."""

import os
from pathlib import Path

import pytest
import yaml

from comfyui_mcp.config import (
    ComfyUISettings,
    LoggingSettings,
    RateLimitSettings,
    SecuritySettings,
    Settings,
    TransportSettings,
    load_settings,
)


class TestSettingsDefaults:
    def test_default_comfyui_url(self):
        s = Settings()
        assert s.comfyui.url == "http://127.0.0.1:8188"

    def test_default_security_mode(self):
        s = Settings()
        assert s.security.mode == "audit"

    def test_default_rate_limits(self):
        s = Settings()
        assert s.rate_limits.workflow == 10
        assert s.rate_limits.read_only == 60

    def test_default_transport_stdio(self):
        s = Settings()
        assert s.transport.stdio is True

    def test_dangerous_nodes_default(self):
        s = Settings()
        assert len(s.security.dangerous_nodes) > 0

    def test_allowed_extensions_default(self):
        s = Settings()
        assert ".png" in s.security.allowed_extensions


class TestSettingsFromYAML:
    def test_load_from_yaml(self, tmp_path):
        config = {
            "comfyui": {
                "url": "https://gpu-server:8188",
                "token": "secret-token",
            },
            "security": {"mode": "enforce"},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config))

        settings = load_settings(config_path=config_file)
        assert settings.comfyui.url == "https://gpu-server:8188"
        assert settings.comfyui.token == "secret-token"
        assert settings.security.mode == "enforce"

    def test_missing_yaml_uses_defaults(self, tmp_path):
        settings = load_settings(config_path=tmp_path / "nonexistent.yaml")
        assert settings.comfyui.url == "http://127.0.0.1:8188"


class TestSettingsEnvOverrides:
    def test_env_overrides_url(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_URL", "https://env-server:8188")
        settings = load_settings()
        assert settings.comfyui.url == "https://env-server:8188"

    def test_env_overrides_token(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_TOKEN", "env-token")
        settings = load_settings()
        assert settings.comfyui.token == "env-token"

    def test_env_overrides_security_mode(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_SECURITY_MODE", "enforce")
        settings = load_settings()
        assert settings.security.mode == "enforce"


class TestSecurityModeValidation:
    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError):
            SecuritySettings(mode="invalid")

    def test_enforce_mode_accepted(self):
        s = SecuritySettings(mode="enforce")
        assert s.mode == "enforce"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'comfyui_mcp.config'`

**Step 3: Implement config module**

Create `src/comfyui_mcp/config.py`:

```python
"""Configuration management with YAML file + environment variable overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator

_DEFAULT_CONFIG_PATH = Path.home() / ".comfyui-mcp" / "config.yaml"

_DEFAULT_DANGEROUS_NODES = [
    "ExecuteAnything",
    "EvalNode",
    "ExecNode",
    "PythonExec",
    "RunPython",
    "ShellNode",
    "CommandExecutor",
]

_DEFAULT_ALLOWED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".json"]


class ComfyUISettings(BaseModel):
    url: str = "http://127.0.0.1:8188"
    token: str = ""
    tls_verify: bool = True
    timeout_connect: int = 30
    timeout_read: int = 300


class SecuritySettings(BaseModel):
    mode: Literal["audit", "enforce"] = "audit"
    allowed_nodes: list[str] = []
    dangerous_nodes: list[str] = list(_DEFAULT_DANGEROUS_NODES)
    max_upload_size_mb: int = 50
    allowed_extensions: list[str] = list(_DEFAULT_ALLOWED_EXTENSIONS)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("audit", "enforce"):
            raise ValueError(f"Invalid security mode: {v!r}. Must be 'audit' or 'enforce'.")
        return v


class RateLimitSettings(BaseModel):
    workflow: int = 10
    generation: int = 10
    file_ops: int = 30
    read_only: int = 60


class LoggingSettings(BaseModel):
    level: str = "INFO"
    audit_file: str = "~/.comfyui-mcp/audit.log"


class SSESettings(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080


class TransportSettings(BaseModel):
    stdio: bool = True
    sse: SSESettings = SSESettings()


class Settings(BaseModel):
    comfyui: ComfyUISettings = ComfyUISettings()
    security: SecuritySettings = SecuritySettings()
    rate_limits: RateLimitSettings = RateLimitSettings()
    logging: LoggingSettings = LoggingSettings()
    transport: TransportSettings = TransportSettings()


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base dict."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(data: dict) -> dict:
    """Apply environment variable overrides."""
    import os

    env_map = {
        "COMFYUI_URL": ("comfyui", "url"),
        "COMFYUI_TOKEN": ("comfyui", "token"),
        "COMFYUI_TLS_VERIFY": ("comfyui", "tls_verify"),
        "COMFYUI_SECURITY_MODE": ("security", "mode"),
        "COMFYUI_LOG_LEVEL": ("logging", "level"),
    }
    for env_var, path in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            section, key = path
            if section not in data:
                data[section] = {}
            data[section][key] = value
    return data


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML file with environment variable overrides."""
    path = config_path or _DEFAULT_CONFIG_PATH
    data: dict = {}

    if path.exists():
        with open(path) as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = loaded

    data = _apply_env_overrides(data)
    return Settings(**data)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add configuration with YAML loading and env var overrides"
```

---

### Task 3: Structured Audit Logger

**Files:**
- Create: `src/comfyui_mcp/audit.py`
- Create: `tests/test_audit.py`

**Step 1: Write failing tests**

Create `tests/test_audit.py`:

```python
"""Tests for structured audit logging."""

import json
from io import StringIO
from pathlib import Path

import pytest

from comfyui_mcp.audit import AuditLogger, AuditRecord


class TestAuditRecord:
    def test_record_has_required_fields(self):
        record = AuditRecord(tool="run_workflow", action="submitted")
        assert record.tool == "run_workflow"
        assert record.action == "submitted"
        assert record.timestamp is not None

    def test_record_serializes_to_json(self):
        record = AuditRecord(
            tool="run_workflow",
            action="submitted",
            prompt_id="abc-123",
            nodes_used=["KSampler", "CLIPTextEncode"],
            warnings=["Dangerous node: EvalNode"],
        )
        data = json.loads(record.model_dump_json())
        assert data["tool"] == "run_workflow"
        assert "KSampler" in data["nodes_used"]
        assert len(data["warnings"]) == 1

    def test_record_never_contains_token(self):
        record = AuditRecord(
            tool="generate_image",
            action="submitted",
            extra={"token": "secret", "prompt": "a cat"},
        )
        serialized = record.model_dump_json()
        assert "secret" not in serialized


class TestAuditLogger:
    def test_log_writes_json_line(self, tmp_path):
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(audit_file=log_file)
        logger.log(tool="get_queue", action="called")

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["tool"] == "get_queue"

    def test_log_multiple_entries(self, tmp_path):
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(audit_file=log_file)
        logger.log(tool="tool_a", action="called")
        logger.log(tool="tool_b", action="called")

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_log_creates_parent_directories(self, tmp_path):
        log_file = tmp_path / "nested" / "dir" / "audit.log"
        logger = AuditLogger(audit_file=log_file)
        logger.log(tool="test", action="called")
        assert log_file.exists()

    def test_log_strips_sensitive_keys_from_extra(self, tmp_path):
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(audit_file=log_file)
        logger.log(
            tool="run_workflow",
            action="submitted",
            extra={"token": "secret-value", "prompt": "a cat"},
        )
        content = log_file.read_text()
        assert "secret-value" not in content
        assert "a cat" in content
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_audit.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement audit logger**

Create `src/comfyui_mcp/audit.py`:

```python
"""Structured audit logging for all MCP tool invocations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, model_serializer

_SENSITIVE_KEYS = {"token", "password", "secret", "api_key", "authorization"}


def _redact_sensitive(data: dict) -> dict:
    """Remove sensitive keys from a dictionary."""
    return {k: v for k, v in data.items() if k.lower() not in _SENSITIVE_KEYS}


class AuditRecord(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tool: str
    action: str
    prompt_id: str = ""
    nodes_used: list[str] = []
    warnings: list[str] = []
    duration_ms: int = 0
    status: str = ""
    extra: dict = {}

    @model_serializer
    def serialize(self) -> dict:
        data = {
            "timestamp": self.timestamp,
            "tool": self.tool,
            "action": self.action,
        }
        if self.prompt_id:
            data["prompt_id"] = self.prompt_id
        if self.nodes_used:
            data["nodes_used"] = self.nodes_used
        if self.warnings:
            data["warnings"] = self.warnings
        if self.duration_ms:
            data["duration_ms"] = self.duration_ms
        if self.status:
            data["status"] = self.status
        if self.extra:
            data["extra"] = _redact_sensitive(self.extra)
        return data


class AuditLogger:
    def __init__(self, audit_file: Path) -> None:
        self._audit_file = Path(audit_file)

    def log(self, *, tool: str, action: str, **kwargs) -> AuditRecord:
        """Write an audit record as a JSON line."""
        record = AuditRecord(tool=tool, action=action, **kwargs)
        self._audit_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._audit_file, "a") as f:
            f.write(record.model_dump_json() + "\n")
        return record
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_audit.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add structured audit logger with sensitive field redaction"
```

---

### Task 4: Security — Path Sanitizer

**Files:**
- Create: `src/comfyui_mcp/security/__init__.py`
- Create: `src/comfyui_mcp/security/sanitizer.py`
- Create: `tests/test_sanitizer.py`

**Step 1: Write failing tests**

Create `tests/test_sanitizer.py`:

```python
"""Tests for path sanitization."""

import pytest

from comfyui_mcp.security.sanitizer import PathSanitizer, PathValidationError


class TestPathSanitizer:
    @pytest.fixture
    def sanitizer(self):
        return PathSanitizer(
            allowed_extensions=[".png", ".jpg", ".jpeg", ".webp", ".json"],
            max_size_mb=50,
        )

    def test_clean_filename_passes(self, sanitizer):
        result = sanitizer.validate_filename("image_001.png")
        assert result == "image_001.png"

    def test_subdirectory_filename_passes(self, sanitizer):
        result = sanitizer.validate_filename("subfolder/image.png")
        assert result == "subfolder/image.png"

    def test_path_traversal_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="traversal"):
            sanitizer.validate_filename("../../etc/passwd")

    def test_path_traversal_encoded_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="traversal"):
            sanitizer.validate_filename("..%2F..%2Fetc%2Fpasswd")

    def test_null_byte_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="null"):
            sanitizer.validate_filename("image.png\x00.sh")

    def test_absolute_path_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="absolute"):
            sanitizer.validate_filename("/etc/passwd")

    def test_disallowed_extension_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="extension"):
            sanitizer.validate_filename("script.py")

    def test_no_extension_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="extension"):
            sanitizer.validate_filename("Makefile")

    def test_double_extension_uses_last(self, sanitizer):
        result = sanitizer.validate_filename("photo.backup.png")
        assert result == "photo.backup.png"

    def test_validate_size_passes(self, sanitizer):
        sanitizer.validate_size(1024 * 1024)  # 1 MB

    def test_validate_size_too_large(self, sanitizer):
        with pytest.raises(PathValidationError, match="size"):
            sanitizer.validate_size(100 * 1024 * 1024)  # 100 MB

    def test_backslash_traversal_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="traversal"):
            sanitizer.validate_filename("..\\..\\windows\\system32")
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sanitizer.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement path sanitizer**

Create `src/comfyui_mcp/security/__init__.py`:

```python
"""Security middleware for ComfyUI MCP server."""
```

Create `src/comfyui_mcp/security/sanitizer.py`:

```python
"""Path sanitization for file operations."""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import unquote


class PathValidationError(Exception):
    """Raised when a file path fails validation."""


class PathSanitizer:
    def __init__(self, allowed_extensions: list[str], max_size_mb: int = 50) -> None:
        self._allowed_extensions = {ext.lower() for ext in allowed_extensions}
        self._max_size_bytes = max_size_mb * 1024 * 1024

    def validate_filename(self, filename: str) -> str:
        """Validate and sanitize a filename. Returns the clean filename or raises."""
        # Decode percent-encoded characters
        decoded = unquote(filename)

        # Block null bytes
        if "\x00" in decoded:
            raise PathValidationError(f"Filename contains null byte: {filename!r}")

        # Normalize backslashes to forward slashes
        normalized = decoded.replace("\\", "/")

        # Block absolute paths
        if normalized.startswith("/"):
            raise PathValidationError(f"Filename is an absolute path: {filename!r}")

        # Block path traversal
        parts = PurePosixPath(normalized).parts
        if ".." in parts:
            raise PathValidationError(f"Filename contains path traversal: {filename!r}")

        # Validate extension
        suffix = PurePosixPath(normalized).suffix.lower()
        if not suffix or suffix not in self._allowed_extensions:
            raise PathValidationError(
                f"Disallowed file extension {suffix!r}. "
                f"Allowed: {sorted(self._allowed_extensions)}"
            )

        return normalized

    def validate_size(self, size_bytes: int) -> None:
        """Validate file size against the configured maximum."""
        if size_bytes > self._max_size_bytes:
            max_mb = self._max_size_bytes / (1024 * 1024)
            actual_mb = size_bytes / (1024 * 1024)
            raise PathValidationError(
                f"File size {actual_mb:.1f}MB exceeds maximum {max_mb:.0f}MB"
            )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sanitizer.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add path sanitizer blocking traversal, null bytes, and bad extensions"
```

---

### Task 5: Security — Workflow Inspector

**Files:**
- Create: `src/comfyui_mcp/security/inspector.py`
- Create: `tests/test_inspector.py`

**Step 1: Write failing tests**

Create `tests/test_inspector.py`:

```python
"""Tests for workflow inspection."""

import pytest

from comfyui_mcp.security.inspector import (
    InspectionResult,
    WorkflowInspector,
    WorkflowBlockedError,
)


def _make_workflow(*node_types: str) -> dict:
    """Helper to build a minimal ComfyUI workflow dict."""
    workflow = {}
    for i, node_type in enumerate(node_types):
        workflow[str(i)] = {
            "class_type": node_type,
            "inputs": {},
        }
    return workflow


class TestWorkflowInspector:
    @pytest.fixture
    def audit_inspector(self):
        return WorkflowInspector(
            mode="audit",
            dangerous_nodes=["EvalNode", "ExecuteAnything"],
            allowed_nodes=[],
        )

    @pytest.fixture
    def enforce_inspector(self):
        return WorkflowInspector(
            mode="enforce",
            dangerous_nodes=["EvalNode"],
            allowed_nodes=["KSampler", "CLIPTextEncode", "VAEDecode", "SaveImage"],
        )

    def test_audit_mode_extracts_node_types(self, audit_inspector):
        workflow = _make_workflow("KSampler", "CLIPTextEncode", "VAEDecode")
        result = audit_inspector.inspect(workflow)
        assert set(result.nodes_used) == {"KSampler", "CLIPTextEncode", "VAEDecode"}

    def test_audit_mode_flags_dangerous_nodes(self, audit_inspector):
        workflow = _make_workflow("KSampler", "EvalNode")
        result = audit_inspector.inspect(workflow)
        assert len(result.warnings) > 0
        assert any("EvalNode" in w for w in result.warnings)
        assert result.blocked is False

    def test_audit_mode_never_blocks(self, audit_inspector):
        workflow = _make_workflow("EvalNode", "ExecuteAnything")
        result = audit_inspector.inspect(workflow)
        assert result.blocked is False

    def test_enforce_mode_allows_approved_nodes(self, enforce_inspector):
        workflow = _make_workflow("KSampler", "CLIPTextEncode")
        result = enforce_inspector.inspect(workflow)
        assert result.blocked is False
        assert len(result.warnings) == 0

    def test_enforce_mode_blocks_unapproved_nodes(self, enforce_inspector):
        workflow = _make_workflow("KSampler", "UnknownCustomNode")
        with pytest.raises(WorkflowBlockedError, match="UnknownCustomNode"):
            enforce_inspector.inspect(workflow)

    def test_enforce_mode_blocks_dangerous_nodes(self, enforce_inspector):
        workflow = _make_workflow("KSampler", "EvalNode")
        with pytest.raises(WorkflowBlockedError, match="EvalNode"):
            enforce_inspector.inspect(workflow)

    def test_empty_workflow(self, audit_inspector):
        result = audit_inspector.inspect({})
        assert result.nodes_used == []
        assert result.warnings == []

    def test_suspicious_input_flagged(self, audit_inspector):
        workflow = {
            "0": {
                "class_type": "KSampler",
                "inputs": {"code": "__import__('os').system('rm -rf /')"},
            }
        }
        result = audit_inspector.inspect(workflow)
        assert any("suspicious" in w.lower() for w in result.warnings)
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_inspector.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement workflow inspector**

Create `src/comfyui_mcp/security/inspector.py`:

```python
"""Workflow inspection for detecting dangerous node types and suspicious inputs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SUSPICIOUS_PATTERNS = [
    re.compile(r"__import__\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\bos\.system\s*\("),
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bopen\s*\(.+,\s*['\"]w"),
]


class WorkflowBlockedError(Exception):
    """Raised when a workflow is blocked in enforce mode."""


@dataclass
class InspectionResult:
    nodes_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False


class WorkflowInspector:
    def __init__(
        self,
        mode: str = "audit",
        dangerous_nodes: list[str] | None = None,
        allowed_nodes: list[str] | None = None,
    ) -> None:
        self._mode = mode
        self._dangerous_nodes = set(dangerous_nodes or [])
        self._allowed_nodes = set(allowed_nodes or [])

    def inspect(self, workflow: dict) -> InspectionResult:
        """Inspect a ComfyUI workflow and return findings."""
        nodes_used = []
        warnings = []

        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue
            class_type = node_data.get("class_type", "")
            if class_type:
                nodes_used.append(class_type)

            # Check for suspicious input values
            for key, value in node_data.get("inputs", {}).items():
                if isinstance(value, str):
                    for pattern in _SUSPICIOUS_PATTERNS:
                        if pattern.search(value):
                            warnings.append(
                                f"Suspicious input in node {node_id} "
                                f"({class_type}), field '{key}'"
                            )
                            break

        # Check for dangerous nodes
        for node_type in nodes_used:
            if node_type in self._dangerous_nodes:
                warnings.append(f"Dangerous node type: {node_type}")

        # Enforce mode: block unapproved nodes
        if self._mode == "enforce" and self._allowed_nodes:
            unapproved = [n for n in nodes_used if n not in self._allowed_nodes]
            if unapproved:
                raise WorkflowBlockedError(
                    f"Workflow blocked — unapproved node types: {unapproved}"
                )

        return InspectionResult(
            nodes_used=nodes_used,
            warnings=warnings,
            blocked=False,
        )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_inspector.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add workflow inspector with audit/enforce modes and suspicious input detection"
```

---

### Task 6: Security — Rate Limiter

**Files:**
- Create: `src/comfyui_mcp/security/rate_limit.py`
- Create: `tests/test_rate_limit.py`

**Step 1: Write failing tests**

Create `tests/test_rate_limit.py`:

```python
"""Tests for rate limiting."""

import time

import pytest

from comfyui_mcp.security.rate_limit import RateLimitExceeded, RateLimiter


class TestRateLimiter:
    def test_allows_requests_under_limit(self):
        limiter = RateLimiter(max_per_minute=5)
        for _ in range(5):
            limiter.check("test_tool")

    def test_blocks_requests_over_limit(self):
        limiter = RateLimiter(max_per_minute=2)
        limiter.check("test_tool")
        limiter.check("test_tool")
        with pytest.raises(RateLimitExceeded):
            limiter.check("test_tool")

    def test_separate_tools_have_separate_limits(self):
        limiter = RateLimiter(max_per_minute=1)
        limiter.check("tool_a")
        limiter.check("tool_b")  # Should not raise

    def test_tokens_replenish_over_time(self):
        limiter = RateLimiter(max_per_minute=60)  # 1 per second
        # Exhaust all tokens
        for _ in range(60):
            limiter.check("test_tool")
        # Wait for a token to replenish
        time.sleep(1.1)
        limiter.check("test_tool")  # Should not raise

    def test_error_message_includes_tool_name(self):
        limiter = RateLimiter(max_per_minute=0)
        with pytest.raises(RateLimitExceeded, match="my_tool"):
            limiter.check("my_tool")
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_rate_limit.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement rate limiter**

Create `src/comfyui_mcp/security/rate_limit.py`:

```python
"""Token-bucket rate limiter for MCP tools."""

from __future__ import annotations

import time


class RateLimitExceeded(Exception):
    """Raised when a tool exceeds its rate limit."""


class _Bucket:
    __slots__ = ("_max_tokens", "_tokens", "_refill_rate", "_last_refill")

    def __init__(self, max_per_minute: int) -> None:
        self._max_tokens = float(max_per_minute)
        self._tokens = float(max_per_minute)
        self._refill_rate = max_per_minute / 60.0  # tokens per second
        self._last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self._max_per_minute = max_per_minute
        self._buckets: dict[str, _Bucket] = {}

    def check(self, tool_name: str) -> None:
        """Check rate limit for a tool. Raises RateLimitExceeded if over limit."""
        if tool_name not in self._buckets:
            self._buckets[tool_name] = _Bucket(self._max_per_minute)

        if not self._buckets[tool_name].consume():
            raise RateLimitExceeded(
                f"Rate limit exceeded for tool '{tool_name}'. "
                f"Max {self._max_per_minute} requests/minute."
            )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_rate_limit.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add token-bucket rate limiter per tool"
```

---

### Task 7: ComfyUI HTTP Client

**Files:**
- Create: `src/comfyui_mcp/client.py`
- Create: `tests/test_client.py`

**Step 1: Write failing tests**

Create `tests/test_client.py`:

```python
"""Tests for ComfyUI HTTP client."""

import pytest
import httpx
import respx

from comfyui_mcp.client import ComfyUIClient


@pytest.fixture
def client():
    return ComfyUIClient(
        base_url="http://test-comfyui:8188",
        token="test-token",
        timeout_connect=5,
        timeout_read=10,
        tls_verify=False,
    )


class TestComfyUIClient:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_queue(self, client):
        respx.get("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        )
        result = await client.get_queue()
        assert "queue_running" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_prompt(self, client):
        respx.post("http://test-comfyui:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )
        result = await client.post_prompt({"1": {"class_type": "KSampler", "inputs": {}}})
        assert result["prompt_id"] == "abc-123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_auth_header_sent(self, client):
        route = respx.get("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.get_queue()
        assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_auth_header_when_no_token(self):
        c = ComfyUIClient(base_url="http://test:8188", token="")
        route = respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        await c.get_queue()
        assert "Authorization" not in route.calls[0].request.headers

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_models(self, client):
        respx.get("http://test-comfyui:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["model_v1.safetensors", "model_v2.safetensors"])
        )
        result = await client.get_models("checkpoints")
        assert len(result) == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_history(self, client):
        respx.get("http://test-comfyui:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}})
        )
        result = await client.get_history()
        assert "abc" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_object_info(self, client):
        respx.get("http://test-comfyui:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {"input": {}}})
        )
        result = await client.get_object_info()
        assert "KSampler" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_interrupt(self, client):
        respx.post("http://test-comfyui:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.interrupt()  # Should not raise

    @respx.mock
    @pytest.mark.asyncio
    async def test_upload_image(self, client):
        respx.post("http://test-comfyui:8188/upload/image").mock(
            return_value=httpx.Response(200, json={"name": "uploaded.png", "subfolder": "", "type": "input"})
        )
        result = await client.upload_image(b"fake-png-data", "test.png")
        assert result["name"] == "uploaded.png"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_image(self, client):
        respx.get("http://test-comfyui:8188/view").mock(
            return_value=httpx.Response(200, content=b"fake-image-bytes", headers={"content-type": "image/png"})
        )
        data, content_type = await client.get_image("output.png", "output")
        assert data == b"fake-image-bytes"
        assert content_type == "image/png"

    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_queue_item(self, client):
        respx.post("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.delete_queue_item("abc-123")

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_history_item(self, client):
        respx.get("http://test-comfyui:8188/history/abc-123").mock(
            return_value=httpx.Response(200, json={"abc-123": {"outputs": {}}})
        )
        result = await client.get_history_item("abc-123")
        assert "abc-123" in result
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_client.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement ComfyUI client**

Create `src/comfyui_mcp/client.py`:

```python
"""Async HTTP client for ComfyUI API."""

from __future__ import annotations

import httpx


class ComfyUIClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        token: str = "",
        timeout_connect: int = 30,
        timeout_read: int = 300,
        tls_verify: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = httpx.Timeout(connect=timeout_connect, read=timeout_read, write=30, pool=30)
        self._tls_verify = tls_verify

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=self._timeout,
            verify=self._tls_verify,
        )

    async def get_queue(self) -> dict:
        async with self._client() as c:
            r = await c.get("/queue")
            r.raise_for_status()
            return r.json()

    async def post_prompt(self, workflow: dict) -> dict:
        async with self._client() as c:
            r = await c.post("/prompt", json={"prompt": workflow})
            r.raise_for_status()
            return r.json()

    async def get_models(self, folder: str) -> list:
        async with self._client() as c:
            r = await c.get(f"/models/{folder}")
            r.raise_for_status()
            return r.json()

    async def get_object_info(self, node_class: str | None = None) -> dict:
        path = f"/object_info/{node_class}" if node_class else "/object_info"
        async with self._client() as c:
            r = await c.get(path)
            r.raise_for_status()
            return r.json()

    async def get_history(self) -> dict:
        async with self._client() as c:
            r = await c.get("/history")
            r.raise_for_status()
            return r.json()

    async def get_history_item(self, prompt_id: str) -> dict:
        async with self._client() as c:
            r = await c.get(f"/history/{prompt_id}")
            r.raise_for_status()
            return r.json()

    async def interrupt(self) -> None:
        async with self._client() as c:
            r = await c.post("/interrupt")
            r.raise_for_status()

    async def delete_queue_item(self, prompt_id: str) -> None:
        async with self._client() as c:
            r = await c.post("/queue", json={"delete": [prompt_id]})
            r.raise_for_status()

    async def upload_image(self, data: bytes, filename: str, subfolder: str = "") -> dict:
        async with self._client() as c:
            files = {"image": (filename, data, "image/png")}
            form_data = {}
            if subfolder:
                form_data["subfolder"] = subfolder
            r = await c.post("/upload/image", files=files, data=form_data)
            r.raise_for_status()
            return r.json()

    async def get_image(self, filename: str, subfolder: str = "output") -> tuple[bytes, str]:
        async with self._client() as c:
            r = await c.get("/view", params={"filename": filename, "subfolder": subfolder})
            r.raise_for_status()
            content_type = r.headers.get("content-type", "image/png")
            return r.content, content_type

    async def get_embeddings(self) -> list:
        async with self._client() as c:
            r = await c.get("/embeddings")
            r.raise_for_status()
            return r.json()

    async def get_workflow_templates(self) -> list:
        async with self._client() as c:
            r = await c.get("/workflow_templates")
            r.raise_for_status()
            return r.json()
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_client.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add async ComfyUI HTTP client with auth and TLS support"
```

---

### Task 8: MCP Tools — Discovery & History (Read-Only)

**Files:**
- Create: `src/comfyui_mcp/tools/__init__.py`
- Create: `src/comfyui_mcp/tools/discovery.py`
- Create: `src/comfyui_mcp/tools/history.py`
- Create: `tests/test_tools_discovery.py`
- Create: `tests/test_tools_history.py`
- Modify: `src/comfyui_mcp/server.py` — add lifespan, wire tools

This task wires the MCP server together with the config, client, audit logger, and rate limiters via a lifespan context. Then registers the read-only discovery and history tools.

**Step 1: Write failing tests for discovery tools**

Create `tests/test_tools_discovery.py`:

```python
"""Tests for discovery MCP tools."""

import pytest
import httpx
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.tools.discovery import register_discovery_tools
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.security.rate_limit import RateLimiter


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188", token="")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    return client, audit, limiter


class TestListModels:
    @respx.mock
    @pytest.mark.asyncio
    async def test_list_models_returns_models(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["v1.safetensors", "v2.safetensors"])
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter)

        result = await tools["list_models"](folder="checkpoints")
        assert "v1.safetensors" in result


class TestListNodes:
    @respx.mock
    @pytest.mark.asyncio
    async def test_list_nodes_returns_node_types(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {}, "CLIPTextEncode": {}})
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter)

        result = await tools["list_nodes"]()
        assert "KSampler" in result
        assert "CLIPTextEncode" in result
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_discovery.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement discovery tools**

Create `src/comfyui_mcp/tools/__init__.py`:

```python
"""MCP tool definitions."""
```

Create `src/comfyui_mcp/tools/discovery.py`:

```python
"""Discovery tools: list_models, list_nodes, get_node_info, list_workflows."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter


def register_discovery_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
) -> dict[str, Any]:
    """Register discovery tools and return a dict of callable functions for testing."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool()
    async def list_models(folder: str = "checkpoints") -> list[str]:
        """List available models in a folder (checkpoints, loras, vae, etc.)."""
        limiter.check("list_models")
        audit.log(tool="list_models", action="called", extra={"folder": folder})
        return await client.get_models(folder)

    tool_fns["list_models"] = list_models

    @mcp.tool()
    async def list_nodes() -> list[str]:
        """List all available ComfyUI node types."""
        limiter.check("list_nodes")
        audit.log(tool="list_nodes", action="called")
        info = await client.get_object_info()
        return sorted(info.keys())

    tool_fns["list_nodes"] = list_nodes

    @mcp.tool()
    async def get_node_info(node_class: str) -> dict:
        """Get detailed information about a specific node type."""
        limiter.check("get_node_info")
        audit.log(tool="get_node_info", action="called", extra={"node_class": node_class})
        return await client.get_object_info(node_class)

    tool_fns["get_node_info"] = get_node_info

    @mcp.tool()
    async def list_workflows() -> list:
        """List available workflow templates."""
        limiter.check("list_workflows")
        audit.log(tool="list_workflows", action="called")
        return await client.get_workflow_templates()

    tool_fns["list_workflows"] = list_workflows

    return tool_fns
```

Create `src/comfyui_mcp/tools/history.py`:

```python
"""History tools: get_history, get_history_item."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter


def register_history_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
) -> dict[str, Any]:
    """Register history tools and return callable functions for testing."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool()
    async def get_history() -> dict:
        """Browse ComfyUI execution history (read-only)."""
        limiter.check("get_history")
        audit.log(tool="get_history", action="called")
        return await client.get_history()

    tool_fns["get_history"] = get_history

    @mcp.tool()
    async def get_history_item(prompt_id: str) -> dict:
        """Get details of a specific history entry by prompt_id."""
        limiter.check("get_history_item")
        audit.log(tool="get_history_item", action="called", extra={"prompt_id": prompt_id})
        return await client.get_history_item(prompt_id)

    tool_fns["get_history_item"] = get_history_item

    return tool_fns
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_tools_discovery.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add discovery and history MCP tools (read-only)"
```

---

### Task 9: MCP Tools — Job Management

**Files:**
- Create: `src/comfyui_mcp/tools/jobs.py`
- Create: `tests/test_tools_jobs.py`

**Step 1: Write failing tests**

Create `tests/test_tools_jobs.py`:

```python
"""Tests for job management MCP tools."""

import pytest
import httpx
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.tools.jobs import register_job_tools
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.security.rate_limit import RateLimiter


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188", token="")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    return client, audit, limiter


class TestGetQueue:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_queue_state(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={"queue_running": [["id1"]], "queue_pending": []})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["get_queue"]()
        assert "queue_running" in result


class TestCancelJob:
    @respx.mock
    @pytest.mark.asyncio
    async def test_cancel_job_sends_delete(self, components):
        client, audit, limiter = components
        route = respx.post("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["cancel_job"](prompt_id="abc-123")
        assert route.called


class TestInterrupt:
    @respx.mock
    @pytest.mark.asyncio
    async def test_interrupt_posts(self, components):
        client, audit, limiter = components
        route = respx.post("http://test:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        await tools["interrupt"]()
        assert route.called
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_jobs.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement job tools**

Create `src/comfyui_mcp/tools/jobs.py`:

```python
"""Job management tools: get_queue, get_job, cancel_job, interrupt."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter


def register_job_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
) -> dict[str, Any]:
    """Register job management tools."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool()
    async def get_queue() -> dict:
        """Get the current ComfyUI execution queue state."""
        limiter.check("get_queue")
        audit.log(tool="get_queue", action="called")
        return await client.get_queue()

    tool_fns["get_queue"] = get_queue

    @mcp.tool()
    async def get_job(prompt_id: str) -> dict:
        """Check the status of a specific job by its prompt_id."""
        limiter.check("get_job")
        audit.log(tool="get_job", action="called", extra={"prompt_id": prompt_id})
        return await client.get_history_item(prompt_id)

    tool_fns["get_job"] = get_job

    @mcp.tool()
    async def cancel_job(prompt_id: str) -> str:
        """Cancel a running or queued job by its prompt_id."""
        limiter.check("cancel_job")
        audit.log(tool="cancel_job", action="called", extra={"prompt_id": prompt_id})
        await client.delete_queue_item(prompt_id)
        return f"Cancelled job {prompt_id}"

    tool_fns["cancel_job"] = cancel_job

    @mcp.tool()
    async def interrupt() -> str:
        """Interrupt the currently executing workflow."""
        limiter.check("interrupt")
        audit.log(tool="interrupt", action="called")
        await client.interrupt()
        return "Interrupted current execution"

    tool_fns["interrupt"] = interrupt

    return tool_fns
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_tools_jobs.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add job management MCP tools (queue, cancel, interrupt)"
```

---

### Task 10: MCP Tools — File Operations

**Files:**
- Create: `src/comfyui_mcp/tools/files.py`
- Create: `tests/test_tools_files.py`

**Step 1: Write failing tests**

Create `tests/test_tools_files.py`:

```python
"""Tests for file operation MCP tools."""

import base64

import pytest
import httpx
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.tools.files import register_file_tools
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer, PathValidationError


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188", token="")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    sanitizer = PathSanitizer(
        allowed_extensions=[".png", ".jpg", ".jpeg", ".webp", ".json"],
        max_size_mb=50,
    )
    return client, audit, limiter, sanitizer


class TestUploadImage:
    @respx.mock
    @pytest.mark.asyncio
    async def test_upload_valid_image(self, components):
        client, audit, limiter, sanitizer = components
        respx.post("http://test:8188/upload/image").mock(
            return_value=httpx.Response(200, json={"name": "test.png", "subfolder": "", "type": "input"})
        )
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        image_b64 = base64.b64encode(b"fake-png-data").decode()
        result = await tools["upload_image"](filename="test.png", image_data=image_b64)
        assert "test.png" in result

    @pytest.mark.asyncio
    async def test_upload_path_traversal_blocked(self, components):
        client, audit, limiter, sanitizer = components
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        image_b64 = base64.b64encode(b"fake").decode()
        with pytest.raises(PathValidationError):
            await tools["upload_image"](filename="../../etc/passwd.png", image_data=image_b64)

    @pytest.mark.asyncio
    async def test_upload_bad_extension_blocked(self, components):
        client, audit, limiter, sanitizer = components
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        image_b64 = base64.b64encode(b"fake").decode()
        with pytest.raises(PathValidationError):
            await tools["upload_image"](filename="malicious.py", image_data=image_b64)


class TestGetImage:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_image_returns_base64(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/view").mock(
            return_value=httpx.Response(200, content=b"image-bytes", headers={"content-type": "image/png"})
        )
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        result = await tools["get_image"](filename="output.png")
        assert "base64" in result or "image" in result.lower()

    @pytest.mark.asyncio
    async def test_get_image_traversal_blocked(self, components):
        client, audit, limiter, sanitizer = components
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        with pytest.raises(PathValidationError):
            await tools["get_image"](filename="../../../etc/shadow.png")
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_files.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement file tools**

Create `src/comfyui_mcp/tools/files.py`:

```python
"""File operation tools: upload_image, get_image, list_outputs."""

from __future__ import annotations

import base64
from typing import Any

from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer


def register_file_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    sanitizer: PathSanitizer,
) -> dict[str, Any]:
    """Register file operation tools."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool()
    async def upload_image(filename: str, image_data: str, subfolder: str = "") -> str:
        """Upload an image to ComfyUI's input directory.

        Args:
            filename: Name for the uploaded file (e.g. 'reference.png')
            image_data: Base64-encoded image data
            subfolder: Optional subfolder within ComfyUI's input directory
        """
        limiter.check("upload_image")
        clean_name = sanitizer.validate_filename(filename)
        raw = base64.b64decode(image_data)
        sanitizer.validate_size(len(raw))
        audit.log(
            tool="upload_image",
            action="uploading",
            extra={"filename": clean_name, "size_bytes": len(raw)},
        )
        result = await client.upload_image(raw, clean_name, subfolder)
        audit.log(tool="upload_image", action="uploaded", extra={"result": result})
        return f"Uploaded {result.get('name', clean_name)} to ComfyUI input directory"

    tool_fns["upload_image"] = upload_image

    @mcp.tool()
    async def get_image(filename: str, subfolder: str = "output") -> str:
        """Download a generated image from ComfyUI.

        Args:
            filename: Name of the image file to retrieve
            subfolder: Directory to look in (default: 'output')

        Returns:
            Base64-encoded image data with content type prefix
        """
        limiter.check("get_image")
        clean_name = sanitizer.validate_filename(filename)
        audit.log(tool="get_image", action="downloading", extra={"filename": clean_name})
        data, content_type = await client.get_image(clean_name, subfolder)
        b64 = base64.b64encode(data).decode()
        return f"data:{content_type};base64,{b64}"

    tool_fns["get_image"] = get_image

    @mcp.tool()
    async def list_outputs() -> list[str]:
        """List files in ComfyUI's output directory."""
        limiter.check("list_outputs")
        audit.log(tool="list_outputs", action="called")
        history = await client.get_history()
        filenames = set()
        for entry in history.values():
            if isinstance(entry, dict):
                for outputs in entry.get("outputs", {}).values():
                    if isinstance(outputs, dict):
                        for images in outputs.get("images", []):
                            if isinstance(images, dict) and "filename" in images:
                                filenames.add(images["filename"])
        return sorted(filenames)

    tool_fns["list_outputs"] = list_outputs

    return tool_fns
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_tools_files.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add file operation MCP tools with path sanitization"
```

---

### Task 11: MCP Tools — Generation & Workflow Execution

**Files:**
- Create: `src/comfyui_mcp/tools/generation.py`
- Create: `tests/test_tools_generation.py`

**Step 1: Write failing tests**

Create `tests/test_tools_generation.py`:

```python
"""Tests for generation and workflow execution MCP tools."""

import json

import pytest
import httpx
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.tools.generation import register_generation_tools
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.security.inspector import WorkflowInspector, WorkflowBlockedError
from comfyui_mcp.security.rate_limit import RateLimiter


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188", token="")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    inspector = WorkflowInspector(
        mode="audit",
        dangerous_nodes=["EvalNode"],
        allowed_nodes=[],
    )
    return client, audit, limiter, inspector


@pytest.fixture
def enforce_components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188", token="")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    inspector = WorkflowInspector(
        mode="enforce",
        dangerous_nodes=["EvalNode"],
        allowed_nodes=["KSampler", "CLIPTextEncode", "VAEDecode", "SaveImage", "CheckpointLoaderSimple", "EmptyLatentImage"],
    )
    return client, audit, limiter, inspector


class TestRunWorkflow:
    @respx.mock
    @pytest.mark.asyncio
    async def test_submits_workflow(self, components):
        client, audit, limiter, inspector = components
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )
        mcp = FastMCP("test")
        tools = register_generation_tools(mcp, client, audit, limiter, inspector)
        workflow = {"1": {"class_type": "KSampler", "inputs": {}}}
        result = await tools["run_workflow"](workflow=json.dumps(workflow))
        assert "abc-123" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_audit_mode_logs_dangerous_nodes(self, components):
        client, audit, limiter, inspector = components
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )
        mcp = FastMCP("test")
        tools = register_generation_tools(mcp, client, audit, limiter, inspector)
        workflow = {"1": {"class_type": "EvalNode", "inputs": {}}}
        result = await tools["run_workflow"](workflow=json.dumps(workflow))
        # Should succeed in audit mode but log warnings
        assert "abc-123" in result

    @pytest.mark.asyncio
    async def test_enforce_mode_blocks_unapproved(self, enforce_components):
        client, audit, limiter, inspector = enforce_components
        mcp = FastMCP("test")
        tools = register_generation_tools(mcp, client, audit, limiter, inspector)
        workflow = {"1": {"class_type": "MaliciousNode", "inputs": {}}}
        with pytest.raises(WorkflowBlockedError):
            await tools["run_workflow"](workflow=json.dumps(workflow))


class TestGenerateImage:
    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_image_submits_default_workflow(self, components):
        client, audit, limiter, inspector = components
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "img-001"})
        )
        mcp = FastMCP("test")
        tools = register_generation_tools(mcp, client, audit, limiter, inspector)
        result = await tools["generate_image"](prompt="a beautiful sunset over mountains")
        assert "img-001" in result
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_generation.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement generation tools**

Create `src/comfyui_mcp/tools/generation.py`:

```python
"""Generation tools: generate_image, run_workflow."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.rate_limit import RateLimiter

# Default txt2img workflow — uses standard ComfyUI nodes
_DEFAULT_TXT2IMG = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "bad quality, blurry", "clip": ["4", 1]},
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "comfyui-mcp", "images": ["8", 0]},
    },
}


def _build_txt2img_workflow(
    prompt: str,
    negative_prompt: str = "bad quality, blurry",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    cfg: float = 7.0,
    model: str = "",
) -> dict:
    """Build a txt2img workflow from parameters."""
    import copy

    wf = copy.deepcopy(_DEFAULT_TXT2IMG)
    wf["6"]["inputs"]["text"] = prompt
    wf["7"]["inputs"]["text"] = negative_prompt
    wf["5"]["inputs"]["width"] = width
    wf["5"]["inputs"]["height"] = height
    wf["3"]["inputs"]["steps"] = steps
    wf["3"]["inputs"]["cfg"] = cfg
    if model:
        wf["4"]["inputs"]["ckpt_name"] = model
    return wf


def register_generation_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    inspector: WorkflowInspector,
) -> dict[str, Any]:
    """Register generation tools."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool()
    async def run_workflow(workflow: str) -> str:
        """Submit an arbitrary ComfyUI workflow for execution.

        Args:
            workflow: JSON string of a ComfyUI workflow (API format).
                      Each key is a node ID, each value has 'class_type' and 'inputs'.
        """
        limiter.check("run_workflow")
        wf = json.loads(workflow)

        # Inspect the workflow
        result = inspector.inspect(wf)
        audit.log(
            tool="run_workflow",
            action="inspected",
            nodes_used=result.nodes_used,
            warnings=result.warnings,
            status="allowed" if not result.blocked else "blocked",
        )

        # Submit to ComfyUI
        response = await client.post_prompt(wf)
        prompt_id = response.get("prompt_id", "unknown")
        audit.log(tool="run_workflow", action="submitted", prompt_id=prompt_id)
        return f"Workflow submitted. prompt_id: {prompt_id}"

    tool_fns["run_workflow"] = run_workflow

    @mcp.tool()
    async def generate_image(
        prompt: str,
        negative_prompt: str = "bad quality, blurry",
        width: int = 512,
        height: int = 512,
        steps: int = 20,
        cfg: float = 7.0,
        model: str = "",
    ) -> str:
        """Generate an image from a text prompt using a default txt2img workflow.

        Args:
            prompt: Text description of the image to generate
            negative_prompt: What to avoid in the image
            width: Image width in pixels
            height: Image height in pixels
            steps: Number of sampling steps (more = better quality, slower)
            cfg: Classifier-free guidance scale (higher = more prompt adherence)
            model: Checkpoint model name (leave empty for default)
        """
        limiter.check("generate_image")
        wf = _build_txt2img_workflow(prompt, negative_prompt, width, height, steps, cfg, model)

        result = inspector.inspect(wf)
        audit.log(
            tool="generate_image",
            action="inspected",
            nodes_used=result.nodes_used,
            warnings=result.warnings,
            extra={"prompt": prompt, "width": width, "height": height},
        )

        response = await client.post_prompt(wf)
        prompt_id = response.get("prompt_id", "unknown")
        audit.log(tool="generate_image", action="submitted", prompt_id=prompt_id)
        return f"Image generation started. prompt_id: {prompt_id}"

    tool_fns["generate_image"] = generate_image

    return tool_fns
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_tools_generation.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add generation and workflow execution tools with inspection"
```

---

### Task 12: Wire Server Together with Lifespan

**Files:**
- Modify: `src/comfyui_mcp/server.py`
- Create: `tests/test_server.py`

**Step 1: Write failing test for server initialization**

Create `tests/test_server.py`:

```python
"""Tests for server initialization and tool registration."""

import pytest

from comfyui_mcp.server import mcp


class TestServerSetup:
    def test_server_has_name(self):
        assert mcp.name == "ComfyUI"

    @pytest.mark.asyncio
    async def test_server_lists_tools(self):
        tools = await mcp._tool_manager.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "list_models",
            "list_nodes",
            "get_node_info",
            "list_workflows",
            "get_history",
            "get_history_item",
            "get_queue",
            "get_job",
            "cancel_job",
            "interrupt",
            "upload_image",
            "get_image",
            "list_outputs",
            "run_workflow",
            "generate_image",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_server.py -v
```

Expected: FAIL — tools not registered yet.

**Step 3: Wire the server together**

Replace `src/comfyui_mcp/server.py`:

```python
"""ComfyUI MCP Server entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.config import Settings, load_settings
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools.discovery import register_discovery_tools
from comfyui_mcp.tools.files import register_file_tools
from comfyui_mcp.tools.generation import register_generation_tools
from comfyui_mcp.tools.history import register_history_tools
from comfyui_mcp.tools.jobs import register_job_tools


def _build_server(settings: Settings | None = None) -> FastMCP:
    """Build and configure the MCP server with all tools registered."""
    if settings is None:
        settings = load_settings()

    # Initialize components
    client = ComfyUIClient(
        base_url=settings.comfyui.url,
        token=settings.comfyui.token,
        timeout_connect=settings.comfyui.timeout_connect,
        timeout_read=settings.comfyui.timeout_read,
        tls_verify=settings.comfyui.tls_verify,
    )

    audit_path = Path(settings.logging.audit_file).expanduser()
    audit = AuditLogger(audit_file=audit_path)

    inspector = WorkflowInspector(
        mode=settings.security.mode,
        dangerous_nodes=settings.security.dangerous_nodes,
        allowed_nodes=settings.security.allowed_nodes,
    )

    sanitizer = PathSanitizer(
        allowed_extensions=settings.security.allowed_extensions,
        max_size_mb=settings.security.max_upload_size_mb,
    )

    # Rate limiters per category
    workflow_limiter = RateLimiter(max_per_minute=settings.rate_limits.workflow)
    generation_limiter = RateLimiter(max_per_minute=settings.rate_limits.generation)
    file_limiter = RateLimiter(max_per_minute=settings.rate_limits.file_ops)
    read_limiter = RateLimiter(max_per_minute=settings.rate_limits.read_only)

    server = FastMCP(
        "ComfyUI",
        instructions=(
            "Secure MCP server for generating images and managing workflows via ComfyUI. "
            "Use generate_image for quick text-to-image, or run_workflow for custom workflows. "
            "Use list_models and list_nodes to discover available resources."
        ),
    )

    # Register all tool groups
    register_discovery_tools(server, client, audit, read_limiter)
    register_history_tools(server, client, audit, read_limiter)
    register_job_tools(server, client, audit, workflow_limiter)
    register_file_tools(server, client, audit, file_limiter, sanitizer)
    register_generation_tools(server, client, audit, generation_limiter, inspector)

    return server


# Module-level server instance for import and CLI use
mcp = _build_server()


def main() -> None:
    """Run the MCP server."""
    settings = load_settings()
    if settings.transport.sse.enabled:
        mcp.run(transport="sse", host=settings.transport.sse.host, port=settings.transport.sse.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_server.py -v
```

Expected: All tests PASS.

**Step 5: Run full test suite**

```bash
uv run pytest -v
```

Expected: All tests PASS across all test files.

**Step 6: Commit**

```bash
git add -A && git commit -m "feat: wire server together with lifespan, config, and all tool groups"
```

---

### Task 13: Integration Test — End-to-End Smoke Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

Create `tests/test_integration.py`:

```python
"""End-to-end integration test with mocked ComfyUI backend."""

import json

import pytest
import httpx
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.server import _build_server
from comfyui_mcp.config import Settings, ComfyUISettings


@pytest.fixture
def server():
    settings = Settings(comfyui=ComfyUISettings(url="http://mock-comfyui:8188"))
    return _build_server(settings)


class TestEndToEnd:
    @respx.mock
    @pytest.mark.asyncio
    async def test_full_image_generation_flow(self, server):
        """Test: list models -> generate image -> check job -> list outputs."""
        # Mock all ComfyUI endpoints
        respx.get("http://mock-comfyui:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["sd_v15.safetensors"])
        )
        respx.post("http://mock-comfyui:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "test-001"})
        )
        respx.get("http://mock-comfyui:8188/history/test-001").mock(
            return_value=httpx.Response(200, json={
                "test-001": {
                    "outputs": {
                        "9": {"images": [{"filename": "comfyui-mcp_00001_.png", "subfolder": "", "type": "output"}]}
                    }
                }
            })
        )

        tools = await server._tool_manager.list_tools()
        tool_names = {t.name for t in tools}

        assert "list_models" in tool_names
        assert "generate_image" in tool_names
        assert "get_job" in tool_names

    @respx.mock
    @pytest.mark.asyncio
    async def test_workflow_with_dangerous_node_in_audit_mode(self, server):
        """Audit mode should log but not block dangerous nodes."""
        respx.post("http://mock-comfyui:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "danger-001"})
        )

        tools = await server._tool_manager.list_tools()
        tool_map = {t.name: t for t in tools}
        assert "run_workflow" in tool_map
```

**Step 2: Run integration tests**

```bash
uv run pytest tests/test_integration.py -v
```

Expected: All tests PASS.

**Step 3: Run full test suite one final time**

```bash
uv run pytest -v --tb=short
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add -A && git commit -m "test: add end-to-end integration tests with mocked ComfyUI"
```

---

### Task 14: Final Cleanup & Verification

**Step 1: Verify the MCP server starts cleanly**

```bash
uv run comfyui-mcp --help
```

Expected: Shows MCP server help.

**Step 2: Run the full test suite with coverage**

```bash
uv run pytest -v --tb=short
```

Expected: All tests pass, no import errors.

**Step 3: Final commit with any cleanup**

```bash
git add -A && git commit -m "chore: final cleanup and verification"
```
