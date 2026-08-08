---
paths:
  - "tests/**/*.py"
---

# Testing Rules

## Authoring

- Uses `pytest-asyncio` with `asyncio_mode = auto` (set in `pyproject.toml`).
- Mock ComfyUI API responses with `respx` — use `@respx.mock` decorator and
  `respx.get/post().mock()` to simulate ComfyUI API responses. Never make real
  HTTP calls in tests.
- Tests mirror `src/comfyui_mcp/` structure.

14. **Tests must call actual tool functions.** Test tools by calling the
    functions returned from `register_*_tools()`, or by using the tool
    registration dict. Never access `_tool_manager` or other private SDK
    attributes.
15. **Tests must test this project, not libraries.** Don't test that pydantic
    validates types, that respx mocks work, or that FastMCP registers tools.
    Test that *our* code does the right thing: security checks block bad input,
    audit logs are written, correct API calls are made.
16. **No `@pytest.mark.asyncio` decorators.** `asyncio_mode = auto` is set in
    `pyproject.toml`. The markers are redundant noise.
17. **No duplicate test method names.** Python silently shadows the first
    definition. Each test method in a class must have a unique name.
18. **Mock ComfyUI responses with `respx`.** Use `@respx.mock` decorator and
    `respx.get/post().mock()` to simulate ComfyUI API responses. Never make
    real HTTP calls in tests.

## Model Manager mocks

All `respx` mocks for ComfyUI-Model-Manager endpoints must use the
`{"success": bool, "data": <payload>}` envelope shape (see
[[architecture]] "ComfyUI-Model-Manager API notes"). The client normalizes it
at the boundary; mocks that return a bare payload will not match real
behavior.

## Anti-patterns

- `@pytest.mark.asyncio` on a test (redundant under `asyncio_mode = auto`).
- A test that imports `_tool_manager` or another private SDK attribute.
- A test that makes a real HTTP call to a ComfyUI instance.
- Two test methods on the same class with the same name (the first is silently
  shadowed).
