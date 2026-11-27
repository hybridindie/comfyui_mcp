"""Consent gates for non-workflow mutations (issue #205).

Enforce mode must ask before the server runs third-party code (node-pack
install/update/uninstall) or changes configuration (`update_settings`).
Declines and missing elicitation channels fail closed; audit mode keeps the
previous non-blocking behavior.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.node_manager import ComfyUIManagerDetector
from comfyui_mcp.security.consent import ConsentDeniedError, require_confirmation
from comfyui_mcp.security.node_auditor import NodeAuditor
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools.nodes import register_node_tools
from comfyui_mcp.tools.settings import register_settings_tools


@pytest.fixture
def audit(tmp_path: Path) -> AuditLogger:
    return AuditLogger(audit_file=tmp_path / "audit.log")


def _records(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "audit.log"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestRequireConfirmationHelper:
    async def test_audit_mode_never_elicits(self, audit, tmp_path):
        ctx = AsyncMock()
        await require_confirmation(
            ctx,
            mode="audit",
            audit=audit,
            tool="install_custom_node",
            prompt="Install?",
            extra={"node_id": "pack"},
        )
        ctx.elicit.assert_not_awaited()
        assert _records(tmp_path) == []

    async def test_enforce_without_channel_fails_closed(self, audit, tmp_path):
        with pytest.raises(ConsentDeniedError, match="no elicitation channel"):
            await require_confirmation(
                None,
                mode="enforce",
                audit=audit,
                tool="install_custom_node",
                prompt="Install?",
                extra={"node_id": "pack"},
            )
        assert any(r["action"] == "confirmation_unavailable" for r in _records(tmp_path))

    async def test_accept_proceeds_and_audits(self, audit, tmp_path):
        ctx = AsyncMock()
        ctx.elicit = AsyncMock(return_value=AcceptedElicitation(data=True))
        await require_confirmation(
            ctx,
            mode="enforce",
            audit=audit,
            tool="install_custom_node",
            prompt="Install?",
            extra={"node_id": "pack"},
        )
        actions = [r["action"] for r in _records(tmp_path)]
        assert "eliciting_confirmation" in actions
        assert "confirmed" in actions

    @pytest.mark.parametrize(
        "result",
        [DeclinedElicitation(), CancelledElicitation(), AcceptedElicitation(data=False)],
        ids=["declined", "cancelled", "accepted-false"],
    )
    async def test_non_accept_blocks_and_audits(self, audit, tmp_path, result):
        ctx = AsyncMock()
        ctx.elicit = AsyncMock(return_value=result)
        with pytest.raises(ConsentDeniedError):
            await require_confirmation(
                ctx,
                mode="enforce",
                audit=audit,
                tool="install_custom_node",
                prompt="Install?",
                extra={"node_id": "pack"},
            )
        assert any(r["action"] == "elicitation_declined" for r in _records(tmp_path))


@pytest.fixture
def settings_build(audit):
    client = ComfyUIClient(base_url="http://test:8188")
    sanitizer = PathSanitizer(allowed_extensions=[".png", ".json"])
    limiter = RateLimiter(max_per_minute=10)
    mcp = FastMCP("consent-settings-test")

    def build(mode: str) -> dict[str, Any]:
        return register_settings_tools(mcp, client, audit, limiter, sanitizer, mode=mode)

    return build


class TestSettingsConsent:
    @respx.mock
    async def test_enforce_accept_posts(self, settings_build):
        build = settings_build
        route = respx.post("http://test:8188/settings").mock(
            return_value=httpx.Response(200, json={})
        )
        ctx = AsyncMock()
        ctx.elicit = AsyncMock(return_value=AcceptedElicitation(data=True))

        tools = build("enforce")
        result = await tools["comfyui_update_settings"](
            settings={"default_sampler": "dpmpp_2m"}, ctx=ctx
        )

        assert result["status"] == "updated"
        assert route.called

    @respx.mock
    async def test_enforce_decline_never_posts(self, settings_build):
        build = settings_build
        route = respx.post("http://test:8188/settings").mock(
            return_value=httpx.Response(200, json={})
        )
        ctx = AsyncMock()
        ctx.elicit = AsyncMock(return_value=DeclinedElicitation())

        tools = build("enforce")
        with pytest.raises(ConsentDeniedError):
            await tools["comfyui_update_settings"](
                settings={"default_sampler": "dpmpp_2m"}, ctx=ctx
            )
        assert not route.called

    @respx.mock
    async def test_enforce_without_ctx_never_posts(self, settings_build):
        build = settings_build
        route = respx.post("http://test:8188/settings").mock(
            return_value=httpx.Response(200, json={})
        )
        tools = build("enforce")
        with pytest.raises(ConsentDeniedError):
            await tools["comfyui_update_settings"](settings={"default_sampler": "euler"})
        assert not route.called

    @respx.mock
    async def test_audit_mode_without_ctx_still_posts(self, settings_build):
        build = settings_build
        route = respx.post("http://test:8188/settings").mock(
            return_value=httpx.Response(200, json={})
        )
        tools = build("audit")
        await tools["comfyui_update_settings"](settings={"default_sampler": "euler"})
        assert route.called


@pytest.fixture
def node_tools(audit):
    client = ComfyUIClient(base_url="http://test:8188")
    client.queue_manager_task = AsyncMock(return_value={})
    client.start_custom_node_queue = AsyncMock(return_value={})
    client.get_custom_node_queue_status = AsyncMock(return_value={"is_processing": False})
    node_manager = ComfyUIManagerDetector(client)
    node_manager.require_available = AsyncMock()
    mcp = FastMCP("consent-nodes-test")

    def build(mode: str) -> dict[str, Any]:
        return register_node_tools(
            mcp=mcp,
            client=client,
            audit=audit,
            wf_limiter=RateLimiter(max_per_minute=10),
            read_limiter=RateLimiter(max_per_minute=10),
            node_manager=node_manager,
            node_auditor=NodeAuditor(),
            mode=mode,
        )

    return client, build


MUTATING_TOOLS = {
    "comfyui_install_custom_node": {"node_id": "comfyui-impact-pack"},
    "comfyui_uninstall_custom_node": {"node_id": "comfyui-impact-pack"},
    "comfyui_update_custom_node": {"node_id": "comfyui-impact-pack"},
}


class TestNodePackConsent:
    @pytest.mark.parametrize("tool_name", sorted(MUTATING_TOOLS))
    async def test_enforce_decline_never_mutates(self, node_tools, tool_name):
        client, build = node_tools
        ctx = AsyncMock()
        ctx.elicit = AsyncMock(return_value=DeclinedElicitation())
        tools = build("enforce")

        with pytest.raises(ConsentDeniedError):
            await tools[tool_name](**MUTATING_TOOLS[tool_name], ctx=ctx)

        client.queue_manager_task.assert_not_awaited()

    async def test_enforce_accept_runs_operation(self, node_tools):
        client, build = node_tools
        ctx = AsyncMock()
        ctx.elicit = AsyncMock(return_value=AcceptedElicitation(data=True))
        tools = build("enforce")

        result = await tools["comfyui_install_custom_node"](node_id="comfyui-impact-pack", ctx=ctx)

        assert "comfyui-impact-pack" in result
        client.queue_manager_task.assert_awaited_once()
        client.start_custom_node_queue.assert_awaited_once()

    async def test_enforce_without_ctx_fails_closed(self, node_tools):
        client, build = node_tools
        tools = build("enforce")
        with pytest.raises(ConsentDeniedError):
            await tools["comfyui_update_custom_node"](node_id="comfyui-impact-pack")
        client.queue_manager_task.assert_not_awaited()

    async def test_audit_mode_without_ctx_runs_operation(self, node_tools):
        client, build = node_tools
        tools = build("audit")
        await tools["comfyui_install_custom_node"](node_id="comfyui-impact-pack")
        client.queue_manager_task.assert_awaited_once()


class TestMutatingToolContract:
    def test_every_mutating_tool_exposes_a_consent_context(self, node_tools, settings_build):
        _, build_nodes = node_tools
        tools = {**build_nodes("audit"), **settings_build("audit")}

        for name in [*MUTATING_TOOLS, "comfyui_update_settings"]:
            assert "ctx" in inspect.signature(tools[name]).parameters, name
