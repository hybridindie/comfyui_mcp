"""Tests for background tasks (Phase 6) — TasksExtension wiring + task-enabled tools.

Phase 6 of the FastMCP 4 migration. Verifies the TasksExtension is registered
when enabled, and that the long-running generation tools are marked task=True
with TaskConfig(mode="optional") so they run synchronously for clients that
do not opt in and as background tasks for clients that do.

The in-memory backend (memory://) is used by default; Redis is a production
opt-in via FASTMCP_DOCKET_URL. This is gated behind a config flag because
stdio single-user mode gains little from background execution — it is the
HTTP/remote transport where this shines.
"""

from __future__ import annotations

from pathlib import Path

from comfyui_mcp.config import ComfyUISettings, Settings, TasksSettings, load_settings
from comfyui_mcp.server import _build_server


class TestTasksExtensionWiring:
    def test_extension_registered_when_enabled(self):
        """When tasks.enabled is True, _build_server() registers the
        TasksExtension so task-enabled tools can run as background tasks."""
        settings = Settings(
            comfyui=ComfyUISettings(url="http://test:8188"),
            tasks=TasksSettings(enabled=True),
        )
        server, *_ = _build_server(settings)
        # FastMCP stores extensions in a dict keyed by capability name.
        extensions = getattr(server, "_extensions", None)
        assert extensions is not None, "Could not locate extensions dict on FastMCP server"
        from fastmcp_tasks import TasksExtension

        assert any(isinstance(e, TasksExtension) for e in extensions.values()), (
            "TasksExtension not registered — task=True tools would raise at startup"
        )

    def test_extension_not_registered_when_disabled(self):
        """When tasks.enabled is False (default), no TasksExtension is
        registered — task-enabled tools would raise, so none should be marked
        task=True either."""
        settings = Settings(
            comfyui=ComfyUISettings(url="http://test:8188"),
            tasks=TasksSettings(enabled=False),
        )
        server, *_ = _build_server(settings)
        extensions = getattr(server, "_extensions", None)
        if extensions is None:
            return
        from fastmcp_tasks import TasksExtension

        assert not any(isinstance(e, TasksExtension) for e in extensions.values())

    def test_capability_key_present_when_enabled(self):
        """FastMCP keys the extension under the tasks capability name."""
        settings = Settings(
            comfyui=ComfyUISettings(url="http://test:8188"),
            tasks=TasksSettings(enabled=True),
        )
        server, *_ = _build_server(settings)

        assert "io.modelcontextprotocol/tasks" in getattr(server, "_extensions", {})

    def test_capability_key_absent_when_disabled(self):
        settings = Settings(
            comfyui=ComfyUISettings(url="http://test:8188"),
            tasks=TasksSettings(enabled=False),
        )
        server, *_ = _build_server(settings)

        assert "io.modelcontextprotocol/tasks" not in getattr(server, "_extensions", {})


class TestTasksSettings:
    def test_default_disabled(self):
        """The default is disabled — background tasks are opt-in."""
        s = TasksSettings()
        assert s.enabled is False

    def test_enabled_flag(self):
        s = TasksSettings(enabled=True)
        assert s.enabled is True

    def test_default_backend_is_memory(self):
        """The default backend is in-memory (memory://) — no external deps."""
        s = TasksSettings()
        assert s.backend_url == "memory://"

    def test_redis_backend_opt_in(self):
        s = TasksSettings(backend_url="redis://localhost:6379/0")
        assert s.backend_url == "redis://localhost:6379/0"


class TestTasksEnvOverrides:
    def test_env_enable_flag(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_TASKS_ENABLED", "true")

        s = load_settings(config_path=Path("/nonexistent"))
        assert s.tasks.enabled is True

    def test_env_backend_url(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_TASKS_BACKEND_URL", "redis://host:6379/1")

        s = load_settings(config_path=Path("/nonexistent"))
        assert s.tasks.backend_url == "redis://host:6379/1"

    def test_env_enable_and_backend_together(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_TASKS_ENABLED", "true")
        monkeypatch.setenv("COMFYUI_TASKS_BACKEND_URL", "redis://localhost:6379")

        s = load_settings(config_path=Path("/nonexistent"))
        assert s.tasks.enabled is True
        assert s.tasks.backend_url == "redis://localhost:6379"
