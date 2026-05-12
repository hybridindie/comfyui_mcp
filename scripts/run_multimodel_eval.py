"""Run a single Inspect AI Task against multiple models in one invocation.

The CLI's ``--model`` flag is single-value (Click's default), so
``inspect eval-set --model A --model B`` silently drops the first one. This
wrapper bridges that gap by calling the ``eval_set()`` Python API directly,
which DOES accept a list of model IDs.

Usage:

    uv run python scripts/run_multimodel_eval.py \\
        evals/comfyui_mcp_task.py@comfyui_mcp_phase4 \\
        --models ollama/gpt-oss:120b-cloud,ollama/qwen3-coder:480b-cloud \\
        --log-dir ./logs/phase4-multimodel

The wrapper passes through ``COMFYUI_URL`` (and any other env vars) to the
MCP server subprocess via the Task definition's own ``os.environ.get(...)``
default, so set them before invoking this script.
"""

from __future__ import annotations

import argparse
import sys

from inspect_ai import eval_set


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an Inspect AI Task against multiple models in one invocation.",
    )
    parser.add_argument(
        "task",
        help="Task reference, e.g. 'evals/comfyui_mcp_task.py@comfyui_mcp_phase4'",
    )
    parser.add_argument(
        "--models",
        required=True,
        help=(
            "Comma-separated list of model IDs, e.g. "
            "'ollama/gpt-oss:120b-cloud,ollama/qwen3-coder:480b-cloud'"
        ),
    )
    parser.add_argument(
        "--log-dir",
        required=True,
        help="Directory to write .eval logs to. Must be empty or hold a matching eval-set.",
    )
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        print("error: --models requires at least one model", file=sys.stderr)
        return 2

    success, _logs = eval_set(
        tasks=[args.task],
        model=models,
        log_dir=args.log_dir,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
