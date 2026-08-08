---
paths:
  - "**/*"
---

# Workflow Pipeline (canonical)

Applies to every change in comfyui_mcp — a one-line fix and a multi-issue
feature follow the same order, only the size of each step varies. The roadmap
is issue-driven (`gh issue list`); the issue is the unit of merge.

If you skip a step, name which one and why, in the same turn.

```
1. Issue exists      →  GitHub issue tracking the work (one issue per merge)
2. Failing test      →  Red test pinning the behavior or reproducing the bug
3. Green code        →  Minimal change that turns it green
4. Preflight clean   →  tests / type / lint / format all green
5. PR opened         →  Branch pushed, PR references the issue (closes #N)
6. Comments addressed →  Every review comment resolved or replied to
7. Merge             →  Only after preflight green AND comments resolved
```

Each step gates the next.

## Eval-gated changes (rule 22)

Run the Phase 4 eval **before merging anything that changes tool descriptions,
parameter schemas, or return shapes.** The eval is the regression signal for
LLM-facing tool surface changes. Single-model run takes 1-6 min depending on
model.

```bash
uv run inspect eval evals/comfyui_mcp_task.py@comfyui_mcp_phase4 \
    --model ollama/qwen3-coder:480b-cloud --log-dir ./logs/phase4-pre-merge
```

Compare eval runs with `scripts/compare_evals.py` — it shows per-sample
PASS/FAIL plus a per-tag breakdown so you can answer "which tag of questions
regressed?".

```bash
uv run python scripts/compare_evals.py logs/phase4-before logs/phase4-after
```

Tag new eval questions. Every JSONL sample must have a `tags` field listing
what it tests (e.g. `["template", "recovery"]`). See existing entries for the
canonical tag taxonomy. The task module's `FieldSpec(... metadata=["tags"])`
carries them through into the `.eval` log.

Don't commit `.eval` logs. `logs/` is gitignored and `.graphifyignore`'d.
Generated images on the ComfyUI server from Phase 5 runs accumulate — clean
those manually if needed.

## Anti-patterns

- "I'll open the issue later." Bundling unrelated drive-by fixes into a feature
  PR.
- Pushing a failing test "to get CI to run it."
- Resolving a review comment with neither a change nor a reply.
- Changing a tool's description/schema/return shape without running the Phase 4
  eval first.

State, in one line, which step you are on and the evidence the previous step
is done.
