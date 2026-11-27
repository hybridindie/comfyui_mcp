"""Static bearer auth for the Streamable HTTP transport (#207).

Covers token verification, env resolution, the config bind guard, the startup
provider, audit identity attribution, and per-identity rate-limit buckets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken
from pydantic import ValidationError

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.config import (
    RemoteAuthSettings,
    RemoteTransportSettings,
    Settings,
    TransportSettings,
)
from comfyui_mcp.middleware import SecurityMiddleware
from comfyui_mcp.security.auth import StaticBearerAuth, resolve_bearer_tokens
from comfyui_mcp.security.rate_limit import RateLimiter, RateLimitError
from comfyui_mcp.server import _build_auth_provider


class TestStaticBearerAuth:
    async def test_valid_token_returns_identity(self):
        provider = StaticBearerAuth({"s3cret": "operator"})

        token = await provider.verify_token("s3cret")

        assert token is not None
        assert token.client_id == "operator"
        assert token.token == "s3cret"  # noqa: S105

    async def test_unknown_and_empty_tokens_are_rejected(self):
        provider = StaticBearerAuth({"s3cret": "operator"})

        assert await provider.verify_token("wrong") is None
        assert await provider.verify_token("") is None

    def test_resolve_tokens_reads_env_and_skips_unset(self, monkeypatch):
        monkeypatch.setenv("ALICE_TOKEN", "abc")
        monkeypatch.delenv("BOB_TOKEN", raising=False)

        resolved = resolve_bearer_tokens({"alice": "ALICE_TOKEN", "bob": "BOB_TOKEN"})

        assert resolved == {"abc": "alice"}


class TestTransportConfigGuard:
    def test_public_bind_without_auth_is_rejected(self):
        with pytest.raises(ValidationError, match="not a loopback address"):
            RemoteTransportSettings(enabled=True, host="0.0.0.0")  # noqa: S104

    def test_public_bind_can_be_explicitly_allowed(self):
        settings = RemoteTransportSettings(
            enabled=True,
            host="0.0.0.0",  # noqa: S104
            allow_unauthenticated=True,
        )
        assert settings.allow_unauthenticated is True

    def test_public_bind_with_auth_is_allowed(self):
        settings = RemoteTransportSettings(
            enabled=True,
            host="0.0.0.0",  # noqa: S104
            auth=RemoteAuthSettings(enabled=True),
        )
        assert settings.auth.enabled is True

    def test_loopback_bind_needs_no_auth(self):
        settings = RemoteTransportSettings(enabled=True, host="127.0.0.1")
        assert settings.auth.enabled is False

    def test_auth_without_any_token_entry_is_rejected(self):
        with pytest.raises(ValidationError, match="requires at least one"):
            RemoteTransportSettings(
                enabled=True,
                auth=RemoteAuthSettings(enabled=True, tokens={}),
            )


def _settings(**remote_kwargs) -> Settings:
    return Settings(transport=TransportSettings(remote=RemoteTransportSettings(**remote_kwargs)))


class TestBuildAuthProvider:
    def test_disabled_transport_has_no_provider(self, monkeypatch):
        monkeypatch.setenv("ALICE_TOKEN", "s3cret")
        settings = _settings(auth=RemoteAuthSettings(enabled=True))

        assert _build_auth_provider(settings) is None

    def test_auth_disabled_has_no_provider(self):
        settings = _settings(enabled=True, host="127.0.0.1")

        assert _build_auth_provider(settings) is None

    def test_auth_enabled_builds_provider_from_env(self, monkeypatch):
        monkeypatch.setenv("ALICE_TOKEN", "s3cret")
        settings = _settings(
            enabled=True,
            auth=RemoteAuthSettings(enabled=True, tokens={"alice": "ALICE_TOKEN"}),
        )

        provider = _build_auth_provider(settings)

        assert isinstance(provider, StaticBearerAuth)

    def test_auth_enabled_with_unset_tokens_fails_closed(self, monkeypatch):
        monkeypatch.delenv("ALICE_TOKEN", raising=False)
        settings = _settings(
            enabled=True,
            auth=RemoteAuthSettings(enabled=True, tokens={"alice": "ALICE_TOKEN"}),
        )

        with pytest.raises(RuntimeError, match="none of the configured"):
            _build_auth_provider(settings)


class TestRateLimitIdentityIsolation:
    def test_identities_have_separate_buckets(self):
        limiter = RateLimiter(max_per_minute=1)

        limiter.check("comfyui_get_queue", identity="alice")
        limiter.check("comfyui_get_queue", identity="bob")  # bob still has a token

        with pytest.raises(RateLimitError):
            limiter.check("comfyui_get_queue", identity="alice")

    def test_no_identity_keeps_the_shared_bucket(self):
        limiter = RateLimiter(max_per_minute=1)

        limiter.check("comfyui_get_queue")

        with pytest.raises(RateLimitError):
            limiter.check("comfyui_get_queue")


class TestAuditIdentity:
    async def test_identity_is_serialized_when_present(self, tmp_path: Path):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")

        await audit.async_log(tool="get_queue", action="called", identity="alice")

        record = json.loads((tmp_path / "audit.log").read_text().splitlines()[0])
        assert record["identity"] == "alice"

    async def test_identity_is_omitted_when_empty(self, tmp_path: Path):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")

        await audit.async_log(tool="get_queue", action="called")

        record = json.loads((tmp_path / "audit.log").read_text().splitlines()[0])
        assert "identity" not in record


class TestMiddlewareIdentity:
    async def test_middleware_records_the_caller_identity(self, tmp_path, monkeypatch):
        from comfyui_mcp import middleware as middleware_module

        monkeypatch.setattr(
            middleware_module,
            "get_access_token",
            lambda: AccessToken(token="s3cret", client_id="alice", scopes=[]),
        )
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        mcp = FastMCP("test")
        mcp.add_middleware(
            SecurityMiddleware(
                audit=audit,
                rate_limiters={"read": RateLimiter(max_per_minute=10)},
                tool_categories={"comfyui_get_queue": "read"},
            )
        )

        @mcp.tool
        async def comfyui_get_queue() -> dict:
            return {"queue_running": [], "queue_pending": []}

        await mcp.call_tool("comfyui_get_queue", {})

        records = [
            json.loads(line) for line in (tmp_path / "audit.log").read_text().splitlines() if line
        ]
        assert any(r.get("identity") == "alice" for r in records)


class TestHttpAppAuth:
    _BODY: ClassVar[dict[str, object]] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    _HEADERS: ClassVar[dict[str, str]] = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    async def _post(self, app, headers: dict[str, str]) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/mcp", json=self._BODY, headers=headers)

    async def test_missing_token_returns_401(self):
        mcp = FastMCP("test", auth=StaticBearerAuth({"s3cret": "operator"}))
        app = mcp.http_app()

        response = await self._post(app, self._HEADERS)

        assert response.status_code == 401

    async def test_invalid_token_returns_401(self):
        mcp = FastMCP("test", auth=StaticBearerAuth({"s3cret": "operator"}))
        app = mcp.http_app()

        response = await self._post(app, {**self._HEADERS, "Authorization": "Bearer nope"})

        assert response.status_code == 401

    async def test_valid_token_completes_initialize(self):
        mcp = FastMCP("test", auth=StaticBearerAuth({"s3cret": "operator"}))
        app = mcp.http_app()

        async with app.router.lifespan_context(app):
            response = await self._post(app, {**self._HEADERS, "Authorization": "Bearer s3cret"})

        assert response.status_code == 200
        assert "mcp-session-id" in response.headers
