---
name: security-review
description: Audit installed ComfyUI nodes and move to enforce mode with an allowlist
---

# Security review

The user wants to harden their ComfyUI MCP setup. Request: "$ARGUMENTS".

## Steps

1. **Inventory the risk.** Call `comfyui_audit_dangerous_nodes`. Summarize the `dangerous` and `suspicious` counts and the top reasons; do not dump every node.

2. **Learn what this install actually runs.** The MCP server cannot read the audit file for you. Ask the user to run:

   ```bash
   uv run python scripts/policy_init.py            # review the suggestion
   uv run python scripts/policy_init.py --apply    # write security.allowed_nodes
   ```

   The script counts `nodes_used` per inspected workflow, excludes dangerous and policy-denied classes, and flags allowlist entries that were never observed. If the user cannot run it, ask for its output.

3. **Review the allowlist.** Show the suggested `security.allowed_nodes` and explain which classes were excluded as dangerous. Flag any entry the user does not recognize; do not let a one-off experimental node become permanent by accident.

4. **Choose the warning policy.** Under `security.policy`:
   - `on_warning: "elicit"` for interactive use (the tool asks before submission);
   - `on_warning: "block"` for headless/CI (warnings refuse without a prompt);
   - `on_warning: "allow"` only when the warnings are understood and accepted.
   Add `deny_nodes` for classes the user never wants to run, plus `max_nodes` or `allowed_model_folders` if the extra guardrails are useful.

5. **Switch to enforce.** Set `security.mode: "enforce"` and re-run one known-good workflow. Report the warnings, the decision, and the resulting audit action.

## Notes

- You cannot edit the config through MCP; give the user the YAML to paste.
- `scripts/policy_init.py` keeps a `.bak` and loses YAML comments when it rewrites the file.
- A dangerous node is only safe to allow if the user has reviewed its source and accepts the risk; say so explicitly.
- See `docs/site/security-enforce-mode.md` for the gate semantics and `docs/site/security-audit-log.md` for the log.
