"""Inspect AI task definition for the ComfyUI MCP Phase 4 evaluation.

Run with:

    uv run inspect eval evals/comfyui_mcp_task.py \\
        --model ollama/qwen3-coder:480b-cloud

For a multi-model run:

    uv run inspect eval-set evals/comfyui_mcp_task.py \\
        --model ollama/gpt-oss:120b-cloud \\
        --model ollama/qwen3-coder:480b-cloud \\
        --model anthropic/claude-sonnet-4-6 \\
        --log-dir ./logs/phase4

Browse the resulting traces:

    uv run inspect view --log-dir ./logs/phase4

Requires the ComfyUI MCP server's CLI entry point (``comfyui-mcp-secure``)
to be importable in this venv (it is, via the project's own install).
``COMFYUI_URL`` is read from the inspect process environment and passed
through to the MCP server subprocess.
"""

from __future__ import annotations

import os
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import FieldSpec, json_dataset
from inspect_ai.scorer import match
from inspect_ai.tool import mcp_server_stdio, mcp_tools

_THIS_DIR = Path(__file__).parent
_DATASET_PHASE4 = _THIS_DIR / "2026-05-11-comfyui-mcp-v1.jsonl"
_DATASET_PHASE5 = _THIS_DIR / "2026-05-12-comfyui-mcp-phase5.jsonl"

_SYSTEM_PROMPT = """\
You are evaluating a ComfyUI MCP server's tools. Use the tools available to
complete each task, then give your final answer.

Answer format:
- For numeric answers, output just the number (e.g. ``48``).
- For names or identifiers, output exactly the requested string (e.g.
  ``flux_txt2img``, ``sd3``, ``img2img -> upscale``).
- For true/false questions, answer ``true`` or ``false`` (lowercase).
- Put your final answer as the last line of your reply.
"""


@task
def comfyui_mcp_phase4() -> Task:
    """ComfyUI MCP Phase 4 evaluation — workflow templates, presets, validation."""
    server = mcp_server_stdio(
        name="comfyui_mcp",
        command="comfyui-mcp-secure",
        env={"COMFYUI_URL": os.environ.get("COMFYUI_URL", "http://localhost:8188")},
    )
    return Task(
        dataset=json_dataset(
            str(_DATASET_PHASE4),
            FieldSpec(input="input", target="target", id="id", metadata=["tags"]),
        ),
        solver=react(
            prompt=_SYSTEM_PROMPT,
            tools=[mcp_tools(server)],
            # Without submit=False, react() appends its submit() tool call to
            # the final assistant text, which match(location="end") then sees
            # as trailing junk after the real answer (caught by qwen3:8b on q3).
            submit=False,
        ),
        scorer=match(location="end", ignore_case=True, numeric=True),
        message_limit=30,
        time_limit=10 * 60,
    )


@task
def comfyui_mcp_phase5() -> Task:
    """ComfyUI MCP Phase 5 evaluation — live-execution tool chains and recovery.

    Each question requires the model to chain multiple MCP tool calls,
    pass state (like prompt_id) between them, and recover from at least
    one intentional failure. Targets are deterministic single strings or
    integers so match() scoring works without an LLM judge.

    Generated images and queue artifacts accumulate on the connected
    ComfyUI server; users should clean those manually if needed.
    """
    server = mcp_server_stdio(
        name="comfyui_mcp",
        command="comfyui-mcp-secure",
        env={"COMFYUI_URL": os.environ.get("COMFYUI_URL", "http://localhost:8188")},
    )
    return Task(
        dataset=json_dataset(
            str(_DATASET_PHASE5),
            FieldSpec(input="input", target="target", id="id", metadata=["tags"]),
        ),
        solver=react(
            prompt=_SYSTEM_PROMPT,
            tools=[mcp_tools(server)],
            submit=False,
        ),
        scorer=match(location="end", ignore_case=True, numeric=True),
        message_limit=50,
        time_limit=15 * 60,
    )
