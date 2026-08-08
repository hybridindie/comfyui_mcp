---
paths:
  - ".env"
  - ".graphifyignore"
  - "graphify-out/**"
  - "scripts/graphify*"
  - "scripts/hooks/*"
---

# Graphify (LLM extraction policy)

The project's knowledge graph (`graphify-out/`) is built with the **graphify**
CLI. The LLM backend, model, and tuning live in the repo-root `.env`
(gitignored), not on the command line. The default backend is the **MLflow AI
Gateway** (OpenAI-compatible); local **ollama** is the fallback.
`detect_backend()` checks `openai` **before** `ollama`, so the gateway wins
whenever its key is present (an incidental `OLLAMA_BASE_URL` never shadows it):

```
# Primary: MLflow AI Gateway (OpenAI-compatible /deployments route)
OPENAI_BASE_URL=https://mlflow.johndstudios.net/gateway/mlflow/v1  # base ends at /v1
OPENAI_API_KEY=gateway                    # placeholder — the gateway needs no secret
GRAPHIFY_OPENAI_MODEL=gpt-oss-120b-cloud  # or glm-5.2-cloud
GRAPHIFY_API_TIMEOUT=600

# Fallback: local ollama (used only if the OPENAI_* block is removed, or with
# an explicit `--backend ollama`)
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen3-coder-next:cloud
OLLAMA_API_KEY=ollama
GRAPHIFY_OLLAMA_KEEP_ALIVE=30m
```

## The rule: always observe `.env` when running graphify

**Never invoke `graphify` (or `python -m graphify`) directly. Run it through
`scripts/graphify.sh`**, which sources `.env` and uses a pinned interpreter:

```bash
scripts/graphify.sh label . --update
scripts/graphify.sh query "How does the rate limiter work?"
```

If you must call graphify by hand, source `.env` into the environment first:

```bash
set -a; . ./.env; set +a
graphify <args>
```

## Why this matters

graphify reads `os.environ` but **does not load `.env` itself**, and shells
spawned by tooling don't auto-source it. Without these vars `detect_backend()`
returns `None` — no LLM backend, so community labeling falls back to
`Community N` placeholders and any extraction/label step errors out.

Sourcing `.env` makes auto-detect resolve to `openai` pointed at the gateway
(no `--backend`/`--model` flags needed). The `/graphify` *skill* flow is
separate: it dispatches subagents — the CLI backend in this rule covers
`scripts/graphify.sh` only.

## Auto-refresh on commit (git hooks)

Tracked git hooks keep the graph **structure** in sync with the code. After a
commit or merge that touches `src/comfyui_mcp/**/*.py`,
`scripts/hooks/{post-commit,post-merge}` run `scripts/graphify.sh update .` —
AST-only, **LLM-free** (~1-2s), and `graphify-out/` is gitignored so there's no
commit churn. They no-op when no graph-relevant source changed.

Activate once per clone (sets the per-checkout `core.hooksPath`):

```bash
scripts/hooks/install.sh
```

`update` re-clusters, which resets community **labels** to `Community N`
placeholders. Names are cosmetic for `query`/`explain` (which traverse
nodes/edges); refresh them on demand — or on a cadence — with
`scripts/graphify.sh label .`.

## Refresh the graph before a significant PR

The commit hooks keep the graph **structure** current (AST, free) but reset
community **labels** on every re-cluster. Before opening a PR whose change is
**significant to the graph** — a new tool / module / security check, a moved
or renamed file, or an architectural shift (a new god-node, a new cross-layer
edge) — refresh the map so it's accurate for reviewers and the
`query`/`explain` flows, then read it as a lightweight architecture self-review:

```bash
scripts/graphify.sh update .    # structure reflects the branch (free, AST-only)
scripts/graphify.sh label .     # regenerate community names via the gateway
```

Then glance at `graphify-out/GRAPH_REPORT.md` — **God Nodes** + **Surprising
Connections** make architectural drift visible: a security helper leaking out
of `security/`, a tool reaching into `client.py` transport details directly,
or an unexpected new god-node. Fold anything surprising into the PR description
or a follow-up issue.

**Skip it** for a one-line fix, a doc/test-only change, or a rename with no
new symbols. `graphify-out/` is gitignored, so this is a pre-PR sanity pass —
it never adds commit churn.

## Maintenance

- The `openai` package must be present in graphify's tool env (it is imported
  lazily for the gateway/ollama backends). If a run errors with
  `No module named 'openai'`, install it into the pinned interpreter.
- `.graphifyignore` keeps the graph focused on the MCP server itself
  (`src/comfyui_mcp/` + docs); flip a line to `!` to re-include an excluded
  tree.
