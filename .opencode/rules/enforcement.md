---
paths:
  - "**/*"
---

# Enforcement, Lint, Format & Release

These rules are the project's grounding contract. A change that violates one is
not "done."

## Gates

| Gate | Blocks on |
|------|-----------|
| Workflow ([[workflow]]) | A skipped step — no issue, test-after-code, bundled drive-by fix, unaddressed review comment |
| Suite health ([[testing]]) | Any failing/erroring test |
| Type check | New `mypy` / type errors in changed Python |
| Lint | `ruff check` errors |
| Format | `ruff format --check` drift |
| Security ([[security]]) | A blocked endpoint proxied, a file tool skipping the sanitizer, a tool skipping the limiter/audit, a workflow submit skipping the inspector |

## Lint and format rules

19. **All code must pass `ruff check` and `ruff format --check`.** Run
    `uv run ruff check src/ tests/` and `uv run ruff format --check src/ tests/`
    before committing. Ruff auto-fix (`--fix`) is safe to use.
20. **All source code must pass `mypy`.** Run `uv run mypy src/comfyui_mcp/`
    before committing. Add type annotations to new code. Use
    `# type: ignore[code]` only when the type stub is wrong, and always include
    the specific error code.
21. **Pre-commit hooks must pass.** Run `uv run pre-commit run --all-files` to
    verify. Hooks are installed via `uv run pre-commit install`.

## PR acceptance checklist

- [ ] **Workflow**: issue referenced (`closes #N`); test was red before the
      fix; preflight clean; comments resolved
- [ ] **Security** ([[security]]): no blocked endpoints; file tools sanitized;
      every tool limiter+audit; workflow submits inspected
- [ ] **Tools** ([[tools]]): typed I/O, `dict[str, Any]` for structured
      returns, `Field` annotations on 3+ params
- [ ] **Tests** ([[testing]]): `respx` mocks, no `@pytest.mark.asyncio`, unique
      method names, calling real tool functions
- [ ] **Docs** updated when a tool/contract or structure changes (`README.md`
      Tools table, `CHANGELOG.md`)

## Release & PR workflow

26. **Squash-merge convention.** Every PR is squash-merged with title in the
    form `Imperative summary (#N)` (gh's default). Squash-merge produces one
    commit per PR on `main`; never use merge commits or rebase-merges.
27. **Conventional commit body.** Commit message body explains *why*. End
    every commit with `Co-Authored-By: <model identifier> <noreply@...>` when
    authored with an AI assistant (use the active model's identifier).
28. **CHANGELOG-driven releases.** Cutting a release requires three coordinated
    edits:
    1. Bump `pyproject.toml` `[project].version`
    2. Promote `CHANGELOG.md`'s `[Unreleased]` section to
       `[X.Y.Z] — YYYY-MM-DD` with a summary paragraph and `### Added` /
       `### Changed` / `### Fixed` / `### Removed` sub-sections
    3. Add the
       `[X.Y.Z]: https://github.com/hybridindie/comfyui_mcp/releases/tag/vX.Y.Z`
       link reference at the bottom
29. **Tag → PyPI → GitHub Release.** The PyPI workflow auto-publishes on
    `git push origin vX.Y.Z`, but the GitHub Release is NOT auto-created — run
    `gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."` manually after
    the PyPI publish succeeds (we hit this gotcha for 2.0.0 and 2.1.0).
30. **No force-push to `main`.** Never force-push to `main`. Use
    `--force-with-lease` on feature branches only.

## Anti-patterns

- Unexplained deviation from a rule above (deviate only with a stated reason in
  the PR).
- Code changes that leave `README.md` or `CHANGELOG.md` stale.
- Forgetting the manual `gh release create` after the PyPI workflow publishes.
