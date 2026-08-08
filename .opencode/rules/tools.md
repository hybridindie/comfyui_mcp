---
paths:
  - "src/comfyui_mcp/tools/**/*.py"
  - "src/comfyui_mcp/server.py"
---

# Tool Contract & Adding New Tools

Every `@mcp.tool()` MUST:

- Call `limiter.check("tool_name")` first (see [[security]] rule 3).
- Call `audit.log(tool="tool_name", action="...")` (see [[security]] rule 4).
- If it handles files: validate filenames/subfolders through `sanitizer`
  (see [[security]] rule 2).
- If it submits workflows: inspect through `inspector` before
  `client.post_prompt()` (see [[security]] rule 5).
- Use `Annotated[type, Field(...)]` for parameters with constraints (3+ params)
  (see [[architecture]] rule 13).
- Return `dict[str, Any]` if all code paths return structured data; use `-> str`
  only for mixed return paths (see [[architecture]] rule 12).
- Have a docstring written for an agent: what it does, when to use it, what it
  returns. This is the client-facing description.

## Adding a new tool (checklist)

1. Add the tool function in the appropriate `tools/*.py`.
2. Use `@mcp.tool()` decorator with a clear docstring.
3. Call `limiter.check("tool_name")` first.
4. Call `audit.log(tool="tool_name", action="...")`.
5. If it handles files: validate through `sanitizer`.
6. If it submits workflows: inspect through `inspector`.
7. Use `Annotated[type, Field(...)]` for parameters with constraints (3+ params).
8. Return `dict[str, Any]` if all code paths return structured data; use
   `-> str` only for mixed return paths.
9. Add the function to the `tool_fns` dict and return it.
10. Wire it in `server.py` `_register_all_tools()` if it needs new dependencies.
11. Add tests in `tests/test_tools_*.py` that call the function directly.
12. Update the Tools table in `README.md`.

## Anti-patterns

- Two tools calling the same client method (duplicate tool — see
  [[architecture]] rule 7).
- A tool that returns `json.dumps(...)` when every code path is structured
  (breaks `outputSchema` generation and forces `json.loads` in tests).
- A `@mcp.tool()` body that reaches into `client.py` transport details instead
  of calling a `ComfyUIClient` method.
