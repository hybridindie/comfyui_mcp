---
read_when: "Changing packaging, entry points, versions, or the Python floor"
---

# Python Packaging: One Command, One Version Source

## MUST

- `uv` owns the environment; `uv.lock` is committed and used in CI.
- `pyproject.toml` declares the runtime floor (`requires-python`), dependency
  floors, and console entry points.
- `src/` layout; the package is importable without the repository root on
  `sys.path`.
- One source of truth for the version (`pyproject.toml`); everything else
  derives from it (release steps are in `enforcement.md`).

## SHOULD

- `uv run <tool>` in docs and CI, never bare `python`.
- Optional extras for heavy/optional features (`[project.optional-dependencies]`).
- Build a wheel in CI and install it into a clean environment for a smoke test.
- Keep dev tools (ruff, mypy, pytest) in a `dev` group.

## ANTI-PATTERNS

- `pip install -e .` as the documented path.
- Duplicate version strings in code, docs, and packaging.
- Unpinned `*` dependencies.
- Shipping tests and caches in the wheel.
- A package name that differs from the import name without documentation.
