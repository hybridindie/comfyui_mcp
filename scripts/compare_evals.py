"""Compare two Inspect AI eval runs and print a per-sample PASS/FAIL diff.

Usage:

    uv run python scripts/compare_evals.py <path-a> <path-b>

Each path can be either:
- A specific ``.eval`` file, or
- A directory containing ``.eval`` files (the most recent ``.eval`` by mtime
  is used).

Output: a Markdown table on stdout with one row per sample, columns for
A's and B's PASS/FAIL, and a delta column. Followed by a summary line
listing samples that improved (FAIL → PASS) or regressed (PASS → FAIL).

Example workflows:

    # Same model, two harnesses (regression-check a refactor):
    uv run python scripts/compare_evals.py logs/before logs/after

    # Cross-model on the same eval:
    uv run python scripts/compare_evals.py \\
        logs/phase4-multimodel/gpt-oss.eval \\
        logs/phase4-multimodel/qwen3-coder.eval
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inspect_ai.log import EvalLog, read_eval_log


def _resolve_log_path(path_str: str) -> Path:
    """Resolve a CLI arg to a concrete .eval file path."""
    path = Path(path_str)
    if path.is_file():
        return path
    if path.is_dir():
        evals = sorted(path.glob("*.eval"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not evals:
            print(f"error: no .eval files found in {path}", file=sys.stderr)
            sys.exit(2)
        return evals[0]
    print(f"error: path not found: {path}", file=sys.stderr)
    sys.exit(2)


def _sample_scores(log: EvalLog) -> dict[str, str]:
    """Return {sample_id: 'PASS'|'FAIL'|'?'} for every sample in an eval log."""
    out: dict[str, str] = {}
    for s in log.samples or []:
        # Inspect AI samples may have multiple scorers; we assume a single
        # 'match' scorer (which matches what evals/comfyui_mcp_task.py uses).
        score = s.scores.get("match") if s.scores else None
        sid = str(s.id)
        if score is None:
            out[sid] = "?"
        else:
            out[sid] = "PASS" if score.value == "C" else "FAIL"
    return out


def _sort_key(sample_id: str) -> tuple[int, str | int]:
    """Sort q1, q2, ..., q10 numerically; fall back to alphabetic for others."""
    if sample_id.startswith("q"):
        try:
            return (0, int(sample_id[1:]))
        except ValueError:
            pass
    return (1, sample_id)


def _render_diff(a_log: EvalLog, b_log: EvalLog, a_label: str, b_label: str) -> str:
    a_scores = _sample_scores(a_log)
    b_scores = _sample_scores(b_log)
    all_ids = sorted(set(a_scores) | set(b_scores), key=_sort_key)

    improved: list[str] = []
    regressed: list[str] = []
    rows: list[str] = []
    for sid in all_ids:
        a = a_scores.get(sid, "—")
        b = b_scores.get(sid, "—")
        if a == "FAIL" and b == "PASS":
            delta = "+"
            improved.append(sid)
        elif a == "PASS" and b == "FAIL":
            delta = "-"
            regressed.append(sid)
        elif a == b:
            delta = "="
        else:
            delta = "?"
        rows.append(f"| {sid} | {a} | {b} | {delta} |")

    a_pass = sum(1 for v in a_scores.values() if v == "PASS")
    b_pass = sum(1 for v in b_scores.values() if v == "PASS")
    a_total = len(a_scores) or 1
    b_total = len(b_scores) or 1

    lines: list[str] = [
        "## Comparison",
        "",
        f"- **A**: `{a_label}` ({a_log.eval.model})",
        f"- **B**: `{b_label}` ({b_log.eval.model})",
        f"- Dataset: {a_log.eval.dataset.name} ({len(all_ids)} samples)",
        "",
        "| Sample | A | B | Δ |",
        "|--------|---|---|---|",
        *rows,
        "",
        "**Summary:**",
        f"- A: {a_pass}/{a_total} ({a_pass / a_total * 100:.0f}%)",
        f"- B: {b_pass}/{b_total} ({b_pass / b_total * 100:.0f}%)",
        f"- Delta: {b_pass - a_pass:+d}",
    ]
    if improved:
        lines.append(f"- Improved (FAIL -> PASS): {', '.join(improved)}")
    if regressed:
        lines.append(f"- Regressed (PASS -> FAIL): {', '.join(regressed)}")
    if not improved and not regressed:
        lines.append("- No PASS/FAIL changes")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two Inspect AI eval runs and print a sample-level diff.",
    )
    parser.add_argument("path_a", help="A .eval file or a directory containing one")
    parser.add_argument("path_b", help="A .eval file or a directory containing one")
    args = parser.parse_args()

    a_path = _resolve_log_path(args.path_a)
    b_path = _resolve_log_path(args.path_b)
    a_log = read_eval_log(str(a_path))
    b_log = read_eval_log(str(b_path))

    a_dataset = a_log.eval.dataset.name
    b_dataset = b_log.eval.dataset.name
    if a_dataset != b_dataset:
        print(
            f"warning: datasets differ — A: {a_dataset}, B: {b_dataset}",
            file=sys.stderr,
        )

    print(_render_diff(a_log, b_log, str(a_path), str(b_path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
