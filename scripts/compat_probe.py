#!/usr/bin/env python3
"""Compatibility probe: this client against a live ComfyUI.

Runs the read-only endpoints the MCP server depends on, then (unless
``--no-execute``) submits a model-free ``EmptyImage -> SaveImage`` graph and
reads the result back through ``/api/jobs``, ``/history`` and ``/view``.

Used by the nightly ``ComfyUI compatibility`` workflow and safe to run by hand:

    uv run python scripts/compat_probe.py
    uv run python scripts/compat_probe.py --url http://gpu-box:8188
    uv run python scripts/compat_probe.py --no-execute

Exits 0 when every check passes, 1 on the first drift (all checks still run and
are reported). The execution probe leaves one small PNG in the ComfyUI output
directory, named ``compat-probe-*``; CI containers are ephemeral, and local
runs can delete it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from comfyui_mcp.client import ComfyUIClient

DEFAULT_URL = "http://127.0.0.1:8188"
EXECUTION_TIMEOUT_SECONDS = 120.0
POLL_INTERVAL_SECONDS = 0.5


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _shape(value: Any) -> str:
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    return type(value).__name__


async def _check(
    checks: list[Check],
    name: str,
    fn: Callable[[], Awaitable[Any]],
    validate: Callable[[Any], bool] | None = None,
) -> Any:
    try:
        value = await fn()
    except Exception as exc:
        checks.append(Check(name, False, f"{type(exc).__name__}: {exc}"))
        return None
    if validate is not None and not validate(value):
        checks.append(Check(name, False, f"unexpected shape: {_shape(value)}"))
        return value
    checks.append(Check(name, True, _shape(value)))
    return value


def _execution_workflow(prefix: str) -> dict[str, Any]:
    return {
        "1": {
            "class_type": "EmptyImage",
            "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 0},
        },
        "2": {
            "class_type": "SaveImage",
            "inputs": {"images": ["1", 0], "filename_prefix": prefix},
        },
    }


async def _run_execution_probe(client: ComfyUIClient, checks: list[Check]) -> None:
    prefix = f"compat-probe-{int(time.time())}"
    try:
        submitted = await client.post_prompt(_execution_workflow(prefix))
    except Exception as exc:
        checks.append(Check("execute: submit", False, f"{type(exc).__name__}: {exc}"))
        return

    prompt_id = submitted.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id:
        checks.append(Check("execute: submit", False, f"no prompt_id: {submitted!r}"))
        return
    checks.append(Check("execute: submit", True, prompt_id))

    deadline = time.monotonic() + EXECUTION_TIMEOUT_SECONDS
    job: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            job = await client.get_job(prompt_id)
        except Exception as exc:
            checks.append(Check("execute: job", False, f"{type(exc).__name__}: {exc}"))
            return
        if job.get("status") in {"completed", "failed", "cancelled"}:
            break
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    else:
        checks.append(Check("execute: job", False, "timed out waiting for completion"))
        return

    status = job.get("status")
    checks.append(Check("execute: job", status == "completed", f"status={status}"))
    if status != "completed":
        return

    try:
        history = await client.get_history()
        entry = history.get(prompt_id, {})
        images = [
            image
            for node_output in (entry.get("outputs") or {}).values()
            for image in (node_output or {}).get("images", [])
        ]
    except Exception as exc:
        checks.append(Check("execute: history", False, f"{type(exc).__name__}: {exc}"))
        return
    if not images:
        checks.append(Check("execute: history", False, "no images in history entry"))
        return
    checks.append(Check("execute: history", True, images[0].get("filename", "")))

    image = images[0]
    try:
        data, mime = await client.get_image(image["filename"], image.get("subfolder", ""))
    except Exception as exc:
        checks.append(Check("execute: view", False, f"{type(exc).__name__}: {exc}"))
        return
    is_png = data[:8].hex() == "89504e470d0a1a0a"
    checks.append(
        Check(
            "execute: view",
            is_png,
            f"{len(data)} bytes, mime={mime}, png={is_png}, file={image['filename']}",
        )
    )


async def run(url: str, *, execute: bool) -> list[Check]:
    client = ComfyUIClient(base_url=url)
    checks: list[Check] = []
    try:
        stats = await _check(
            checks,
            "system_stats",
            client.get_system_stats,
            lambda v: isinstance(v, dict) and {"system", "devices"} <= set(v),
        )
        await _check(
            checks,
            "queue",
            client.get_queue,
            lambda v: isinstance(v, dict) and {"queue_running", "queue_pending"} <= set(v),
        )
        await _check(
            checks, "object_info", client.get_object_info, lambda v: isinstance(v, dict) and v
        )
        await _check(checks, "features", client.get_features, lambda v: isinstance(v, dict))
        await _check(checks, "settings", client.get_settings, lambda v: isinstance(v, dict))
        await _check(
            checks, "node_replacements", client.get_node_replacements, lambda v: isinstance(v, dict)
        )
        await _check(
            checks, "global_subgraphs", client.get_global_subgraphs, lambda v: isinstance(v, dict)
        )
        await _check(
            checks,
            "workflow_templates",
            client.get_workflow_templates,
            lambda v: isinstance(v, dict),
        )
        await _check(checks, "extensions", client.get_extensions, lambda v: isinstance(v, list))
        await _check(checks, "embeddings", client.get_embeddings, lambda v: isinstance(v, list))
        await _check(checks, "jobs", client.get_jobs, lambda v: isinstance(v, dict) and "jobs" in v)
        await _check(checks, "history", client.get_history, lambda v: isinstance(v, dict))

        folders = await _check(
            checks,
            "model_types",
            client.get_model_types,
            lambda v: isinstance(v, list) and bool(v),
        )
        if isinstance(folders, list) and folders and isinstance(folders[0], str):
            folder = folders[0]
            await _check(
                checks,
                f"models[{folder}]",
                lambda: client.get_models(folder),
                lambda v: isinstance(v, list),
            )
            await _check(
                checks,
                f"models_detailed[{folder}]",
                lambda: client.get_models_detailed(folder),
                lambda v: isinstance(v, list),
            )

        if execute:
            await _run_execution_probe(client, checks)

        if isinstance(stats, dict):
            checks.insert(
                0,
                Check(
                    "server_version",
                    True,
                    str((stats.get("system") or {}).get("comfyui_version", "unknown")),
                ),
            )
    finally:
        await client.close()
    return checks


def _print_report(url: str, checks: list[Check]) -> None:
    print(f"ComfyUI compatibility probe -> {url}")
    width = max(len(check.name) for check in checks) if checks else 0
    for check in checks:
        marker = "ok  " if check.ok else "FAIL"
        print(f"  [{marker}] {check.name:<{width}}  {check.detail}")
    failed = [check for check in checks if not check.ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    if failed:
        print("drift: " + ", ".join(check.name for check in failed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"ComfyUI base URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Skip the model-free /prompt round trip (read-only checks only).",
    )
    args = parser.parse_args(argv)

    checks = asyncio.run(run(args.url, execute=not args.no_execute))
    _print_report(args.url, checks)
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
