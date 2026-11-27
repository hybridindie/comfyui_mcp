"""Runnable eval examples must not name retired models (follow-up to #217/#240)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RETIRED_MODELS = {"ollama/qwen3-coder:480b-cloud"}

SCAN_GLOBS = (
    "AGENTS.md",
    "README.md",
    ".claude/rules/**/*.md",
    "evals/**/*.py",
    "scripts/**/*.py",
)


def _scanned_files() -> list[Path]:
    files: set[Path] = set()
    for pattern in SCAN_GLOBS:
        files.update(ROOT.glob(pattern))
    return sorted(files)


def _first_model_after(relative: str, marker: str) -> str | None:
    """Return the first --model value within four lines after ``marker``."""
    lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if marker not in line:
            continue
        for follow in lines[index + 1 : index + 5]:
            match = re.search(r"--model\s+(\S+)", follow)
            if match:
                return match.group(1)
    return None


class TestRetiredModels:
    def test_no_retired_model_in_runnable_examples(self):
        hits = [
            f"{path.relative_to(ROOT)}: {model}"
            for path in _scanned_files()
            for model in RETIRED_MODELS
            if model in path.read_text(encoding="utf-8")
        ]
        assert not hits, "retired eval model still referenced: " + ", ".join(hits)

    def test_phase4_examples_use_the_same_model(self):
        canonical = _first_model_after("evals/comfyui_mcp_task.py", "comfyui_mcp_task.py")

        assert canonical, "the eval docstring has no Phase 4 command"
        assert canonical not in RETIRED_MODELS
        for relative in ("AGENTS.md", "README.md", ".claude/rules/workflow.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            assert canonical in text, f"{relative} does not use the Phase 4 model {canonical}"
