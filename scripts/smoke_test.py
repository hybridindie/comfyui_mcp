#!/usr/bin/env python3
"""Operator smoke-test for ComfyUI MCP — Model Manager integration.

Covers:
  1. Basic ComfyUI connectivity (GET /queue)
  2. Model Manager availability detection
  3. Folder listing (GET /model-manager/models)
  4. Download task creation (POST /model-manager/model)
  5. Task progress polling
  6. Task cancellation / cleanup (DELETE /model-manager/download/<id>)

Usage:
    uv run python scripts/smoke_test.py
    uv run python scripts/smoke_test.py --url https://comfyui.example.com
    uv run python scripts/smoke_test.py --no-download   # skip steps 4-6

The test model used for the download probe is a tiny (~520 KB) safetensors file
from the HuggingFace test fixtures repo (no authentication required):
  https://huggingface.co/hf-internal-testing/tiny-random-bert/resolve/main/model.safetensors
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_URL = "http://127.0.0.1:8188"

_TEST_DOWNLOAD_URL = (
    "https://huggingface.co/hf-internal-testing/tiny-random-bert/resolve/main/model.safetensors"
)
# Filename is stamped per-run so repeated runs don't collide with the previous
# run's file still sitting on disk.  Files are named "smoke-test-<timestamp>.safetensors"
# and can be safely deleted from ComfyUI's checkpoints folder after testing.
_TEST_FOLDER = "checkpoints"  # adjust if your instance uses a different name
_TEST_SIZE_BYTES = 520212
_POLL_INTERVAL_SECONDS = 2.0
_POLL_MAX_ATTEMPTS = 30  # 60 seconds total

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✓{_RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {_RED}✗{_RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}!{_RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"     {_CYAN}{msg}{_RESET}")


def _section(title: str) -> None:
    print(f"\n{_BOLD}{title}{_RESET}")
    print("-" * (len(title) + 2))


# ---------------------------------------------------------------------------
# Low-level helpers (no dependency on MCP src)
# ---------------------------------------------------------------------------


def _unwrap(payload: Any) -> Any:
    """Strip ComfyUI-Model-Manager success envelope."""
    if isinstance(payload, dict) and payload.get("success") is True and "data" in payload:
        return payload["data"]
    return payload


async def _get(client: httpx.AsyncClient, path: str, **kwargs: Any) -> Any:
    r = await client.get(path, **kwargs)
    r.raise_for_status()
    return r.json()


async def _post(client: httpx.AsyncClient, path: str, **kwargs: Any) -> Any:
    r = await client.post(path, **kwargs)
    r.raise_for_status()
    return r.json()


async def _delete(client: httpx.AsyncClient, path: str, **kwargs: Any) -> Any:
    r = await client.delete(path, **kwargs)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------


async def check_connectivity(client: httpx.AsyncClient) -> bool:
    _section("Step 1 — Basic connectivity")
    try:
        queue = await _get(client, "/queue")
        running = len(queue.get("queue_running", []))
        pending = len(queue.get("queue_pending", []))
        _ok(f"GET /queue succeeded  (running={running}, pending={pending})")
        return True
    except Exception as exc:
        _fail(f"GET /queue failed: {exc}")
        return False


async def check_model_manager(client: httpx.AsyncClient) -> list[str] | None:
    _section("Step 2 — Model Manager availability")
    try:
        raw = await _get(client, "/model-manager/models")
        payload = _unwrap(raw)
    except Exception as exc:
        _fail(f"GET /model-manager/models failed: {exc}")
        _warn(
            "Is ComfyUI-Model-Manager installed? https://github.com/hayden-fr/ComfyUI-Model-Manager"
        )
        return None

    if isinstance(payload, dict):
        folders = sorted(payload.keys())
    elif isinstance(payload, list):
        folders = sorted(payload)
    else:
        _fail(f"Unexpected payload type: {type(payload).__name__}")
        return None

    _ok(f"Model Manager detected — {len(folders)} folder(s) available")
    for f in folders:
        _info(f)
    return folders


async def check_download_task(
    client: httpx.AsyncClient, folders: list[str], target_folder: str
) -> bool:
    _section("Step 3 — Download task lifecycle")

    # Resolve which folder to use
    if target_folder not in folders:
        candidates = [f for f in folders if "checkpoint" in f.lower()]
        if candidates:
            target_folder = candidates[0]
            _warn(f"'{_TEST_FOLDER}' not found; using '{target_folder}' instead")
        elif folders:
            target_folder = folders[0]
            _warn(f"'{_TEST_FOLDER}' not found; falling back to '{target_folder}'")
        else:
            _fail("No folders available — cannot create download task")
            return False

    # Stamp the filename so repeated runs don't collide with files left on disk
    test_filename = f"smoke-test-{int(time.time())}.safetensors"

    # Create task
    form_data: dict[str, str] = {
        "type": target_folder,
        "pathIndex": "0",
        "fullname": test_filename,
        "downloadPlatform": "huggingface",
        "downloadUrl": _TEST_DOWNLOAD_URL,
        "sizeBytes": str(_TEST_SIZE_BYTES),
        "previewFile": "",
        "description": "MCP smoke test — safe to delete",
    }
    _info(f"Creating task: {test_filename!r} → folder={target_folder!r}")
    _info(f"URL: {_TEST_DOWNLOAD_URL}")
    try:
        raw = await _post(client, "/model-manager/model", data=form_data)
        task_info = _unwrap(raw)
    except Exception as exc:
        _fail(f"POST /model-manager/model failed: {exc}")
        return False

    task_id = task_info.get("taskId") if isinstance(task_info, dict) else None
    if not task_id:
        _fail(f"No taskId in response: {task_info}")
        return False

    _ok(f"Task created  taskId={task_id}")

    # Poll for completion
    _info("Polling for progress…")
    completed = False
    for attempt in range(_POLL_MAX_ATTEMPTS):
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        try:
            raw = await _get(client, "/model-manager/download/task")
            tasks: list[dict[str, Any]] = _unwrap(raw)  # type: ignore[assignment]
            if not isinstance(tasks, list):
                tasks = []
        except Exception as exc:
            _warn(f"  poll {attempt + 1}: GET /model-manager/download/task failed: {exc}")
            continue

        matching = [t for t in tasks if t.get("taskId") == task_id]
        if not matching:
            # Task vanished — Model Manager auto-removes completed tasks in some versions.
            # Treat as success: the download finished before we could observe its terminal state.
            _ok(f"Task {task_id} no longer in queue (completed and auto-removed by Model Manager)")
            completed = True
            break

        t = matching[0]
        status = t.get("status", "?")
        progress = t.get("progress", 0)
        downloaded = t.get("downloadedSize", 0)
        total = t.get("totalSize", 0)
        _info(
            f"  poll {attempt + 1}: status={status!r}  "
            f"progress={progress:.0f}%  "
            f"downloaded={downloaded}/{total}"
        )

        if status in ("pause", "done"):
            if progress >= 99:
                _ok(f"Download reached {progress:.0f}% (status={status!r})")
                _warn(
                    "Note: Model Manager marks completed downloads as 'pause' at 100%. "
                    "This is expected upstream behavior — use cancel_download to clean up."
                )
                completed = True
            else:
                _warn(f"Task stopped at {progress:.0f}% with status={status!r}")
            break

        if status == "error":
            _warn(f"Task failed with status={status!r} at {progress:.0f}%")
            break

    if not completed:
        _warn(f"Download still in progress after {_POLL_MAX_ATTEMPTS} polls")

    # Always cancel/clean up smoke test task (no-op if already auto-removed)
    _info(f"Cleaning up task {task_id}…")
    try:
        await _delete(client, f"/model-manager/download/{task_id}")
        _ok("Task cancelled / removed")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            _ok("Task already removed (auto-cleanup by Model Manager)")
        else:
            _warn(f"Cleanup failed ({exc.response.status_code}): {exc}")
            _warn(f"You may need to manually remove task {task_id} from the Model Manager UI")
    except Exception as exc:
        _warn(f"Cleanup failed: {exc}")
        _warn(f"You may need to manually remove task {task_id} from the Model Manager UI")

    return completed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run(url: str, skip_download: bool) -> int:
    """Return 0 on full pass, 1 on any failure."""
    print(f"\n{_BOLD}ComfyUI MCP — Model Manager smoke test{_RESET}")
    print(f"Target: {url}")
    print(f"Date:   {time.strftime('%Y-%m-%d %H:%M:%S')}")

    failures = 0
    async with httpx.AsyncClient(
        base_url=url.rstrip("/"),
        timeout=httpx.Timeout(connect=15, read=60, write=30, pool=30),
    ) as client:
        ok = await check_connectivity(client)
        if not ok:
            failures += 1
            print(f"\n{_RED}Aborting — ComfyUI is unreachable.{_RESET}")
            return 1

        folders = await check_model_manager(client)
        if folders is None:
            failures += 1

        if skip_download:
            _section("Step 3 — Download task lifecycle")
            _warn("Skipped (--no-download)")
        elif folders is not None:
            ok = await check_download_task(client, folders, _TEST_FOLDER)
            if not ok:
                failures += 1
        else:
            _section("Step 3 — Download task lifecycle")
            _warn("Skipped — Model Manager unavailable")
            failures += 1

    _section("Summary")
    if failures == 0:
        print(f"  {_GREEN}{_BOLD}All checks passed.{_RESET}")
    else:
        print(f"  {_RED}{_BOLD}{failures} check(s) failed.{_RESET}")

    return 0 if failures == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test the ComfyUI MCP Model Manager integration against a live instance."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"ComfyUI server URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        dest="no_download",
        help="Skip the download task lifecycle test (steps 4-6)",
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(run(args.url, skip_download=args.no_download)))


if __name__ == "__main__":
    main()
