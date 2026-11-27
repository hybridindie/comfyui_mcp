"""Operator diagnostics for a ComfyUI MCP deployment (issue #226).

Checks the things that make a server look broken but are configuration or
environment problems: the config file, audit-path writability, transport auth,
ComfyUI reachability and capabilities, and the two optional plugins.

The installed entry point is ``comfyui-mcp-doctor``; ``scripts/doctor.py`` is
the same command for a repo checkout. No LLM calls, no writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.config import Settings, load_settings
from comfyui_mcp.security.auth import resolve_bearer_tokens

PASS = "PASS"  # noqa: S105 - status label, not a credential
WARN = "WARN"
FAIL = "FAIL"

_DEFAULT_CONFIG = Path("~/.comfyui-mcp/config.yaml")


def _out(message: str = "") -> None:
    sys.stdout.write(message + "\n")


def _err(message: str) -> None:
    sys.stderr.write(message + "\n")


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(
        self,
        name: str,
        status: str,
        detail: str = "",
        fix: str = "",
    ) -> None:
        self.checks.append(Check(name=name, status=status, detail=detail, fix=fix))

    @property
    def failed(self) -> bool:
        return any(check.status == FAIL for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": [
                {
                    "name": check.name,
                    "status": check.status,
                    "detail": check.detail,
                    **({"fix": check.fix} if check.fix else {}),
                }
                for check in self.checks
            ],
            "failed": self.failed,
        }


def _audit_check(settings: Settings, report: Report) -> None:
    path = Path(settings.logging.audit_file).expanduser()
    rotation = (
        f"rotation={settings.logging.max_bytes}B/{settings.logging.backup_count} backups"
        if settings.logging.max_bytes
        else "rotation disabled"
    )
    if path.exists():
        if os.access(path, os.W_OK):
            report.add("audit", PASS, f"{path} is writable ({rotation})")
        else:
            report.add(
                "audit",
                FAIL,
                f"{path} is not writable",
                "fix the file permissions or point logging.audit_file elsewhere",
            )
        return

    if path.parent.exists() and not path.parent.is_dir():
        report.add(
            "audit",
            FAIL,
            f"cannot create {path}: {path.parent} is not a directory",
            "choose a different logging.audit_file",
        )
        return

    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if parent.is_dir() and os.access(parent, os.W_OK):
        report.add("audit", PASS, f"{path} will be created ({rotation})")
    else:
        report.add(
            "audit",
            FAIL,
            f"cannot create {path}",
            f"create {path.parent} with write access for this user",
        )


def _transport_check(settings: Settings, report: Report) -> None:
    remote = settings.transport.remote
    if not remote.enabled:
        report.add("transport", PASS, "stdio (HTTP transport disabled)")
        return

    if not remote.auth.enabled:
        report.add(
            "transport",
            WARN,
            f"HTTP on {remote.host}:{remote.port} without bearer auth",
            "enable transport.remote.auth or keep the bind on loopback behind a proxy",
        )
        return

    tokens = resolve_bearer_tokens(remote.auth.tokens)
    identities = ", ".join(sorted(tokens.values()))
    if tokens:
        report.add(
            "transport",
            PASS,
            f"HTTP on {remote.host}:{remote.port}, {len(tokens)} token(s): {identities}",
        )
    else:
        names = ", ".join(sorted(remote.auth.tokens.values()))
        report.add(
            "transport",
            FAIL,
            f"HTTP auth is enabled but no token variable is set ({names})",
            f"export one of: {names}",
        )


async def _comfyui_checks(
    client: ComfyUIClient,
    report: Report,
) -> None:
    try:
        queue = await client.get_queue()
    except Exception as exc:  # a diagnostic reports, never crashes
        report.add(
            "comfyui",
            FAIL,
            f"{client.base_url}: {type(exc).__name__}: {exc}",
            "start ComfyUI or point comfyui.url at the right instance",
        )
        return

    running = len(queue.get("queue_running") or [])
    pending = len(queue.get("queue_pending") or [])
    report.add("comfyui", PASS, f"{client.base_url} (running={running}, pending={pending})")

    try:
        features = await client.get_features()
    except httpx.HTTPStatusError as exc:
        report.add(
            "features",
            WARN,
            f"/features returned {exc.response.status_code}",
            "the server predates /features; previews/uploads fall back",
        )
    except Exception as exc:
        report.add("features", WARN, f"{type(exc).__name__}: {exc}")
    else:
        manager = (features.get("extension") or {}).get("manager") or {}
        report.add(
            "features",
            PASS,
            f"{len(features)} key(s), max_upload_size={features.get('max_upload_size')}, "
            f"manager_v4={manager.get('supports_v4')}",
        )

    try:
        values = await client.get_settings()
        version = values.get("Comfy.InstalledVersion") or "unknown"
        report.add("version", PASS, str(version))
    except Exception as exc:
        report.add("version", WARN, f"/settings unavailable: {type(exc).__name__}")

    try:
        manager_version = await client.get_manager_version()
    except Exception:
        report.add("manager", WARN, "ComfyUI-Manager not available (optional)")
    else:
        report.add("manager", PASS, manager_version.strip() or "available")

    try:
        folders = await client.get_model_manager_folders()
    except httpx.HTTPStatusError as exc:
        report.add(
            "model-manager",
            WARN,
            f"/model-manager/models returned {exc.response.status_code} (optional plugin)",
            "install ComfyUI-Model-Manager to enable download tools",
        )
    except Exception as exc:
        report.add("model-manager", WARN, f"{type(exc).__name__}: {exc}")
    else:
        report.add("model-manager", PASS, f"{len(folders)} folder type(s)")


def _policy_check(settings: Settings, report: Report) -> None:
    policy = settings.security.policy
    configured = bool(
        policy.deny_nodes
        or policy.warn_nodes
        or policy.max_nodes
        or policy.allowed_model_folders
        or policy.on_warning != "elicit"
    )
    detail = (
        f"mode={settings.security.mode}, profile={settings.tools.profile}, "
        f"allowed_nodes={len(settings.security.allowed_nodes)}, "
        f"policy={'custom' if configured else 'default'}"
    )
    if configured:
        detail += f", on_warning={policy.on_warning}, deny_nodes={len(policy.deny_nodes)}"
    report.add("policy", PASS, detail)


async def run_checks(
    settings: Settings,
    *,
    config_path: Path,
    url_override: str | None = None,
) -> Report:
    """Run every diagnostic check and return the report."""
    report = Report()

    if config_path.exists():
        report.add("config", PASS, str(config_path))
    else:
        report.add(
            "config",
            WARN,
            f"{config_path} not found; built-in defaults are in use",
            "copy config.example.yaml or create the file to persist settings",
        )

    _audit_check(settings, report)
    _transport_check(settings, report)
    _policy_check(settings, report)

    client = ComfyUIClient(
        base_url=url_override or settings.comfyui.url,
        timeout_connect=5,
        timeout_read=15,
    )
    try:
        await _comfyui_checks(client, report)
    finally:
        await client.close()

    return report


def _print_report(report: Report, config_path: Path) -> None:
    _out("ComfyUI MCP doctor")
    _out(f"Config: {config_path}")
    _out()
    width = max((len(check.name) for check in report.checks), default=0)
    for check in report.checks:
        _out(f"[{check.status}] {check.name:<{width}}  {check.detail}")
    passed = sum(1 for check in report.checks if check.status == PASS)
    warned = sum(1 for check in report.checks if check.status == WARN)
    failed = sum(1 for check in report.checks if check.status == FAIL)
    _out()
    _out(f"{passed} passed, {warned} warning(s), {failed} failure(s)")

    fixes = [check for check in report.checks if check.fix]
    if fixes:
        _out()
        _out("Next steps:")
        for check in fixes:
            _out(f"  - {check.name}: {check.fix}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose a ComfyUI MCP configuration, transport, and install."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help=f"Config path (default: {_DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Override comfyui.url for this run",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args(argv)

    config_path = args.config.expanduser()
    try:
        settings = load_settings(config_path=config_path)
    except Exception as exc:  # a bad config is the diagnosis
        _err(f"FAIL config: {type(exc).__name__}: {exc}")
        return 1

    report = asyncio.run(run_checks(settings, config_path=config_path, url_override=args.url))
    if args.json:
        _out(json.dumps(report.to_dict(), indent=2))
    else:
        _print_report(report, config_path)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
