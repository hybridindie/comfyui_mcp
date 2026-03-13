# Plugin Packaging and Multi-App Configuration

**Issue:** #16
**Date:** 2026-03-13
**Status:** Approved

## Goal

Package the MCP server as a Claude Code plugin with slash commands, skills, and a security hook. Document configuration snippets for 8 client environments (Claude Code, Claude Desktop, VS Code/Copilot, Cursor, Windsurf, Continue.dev, OpenCode, Open WebUI) with both `uvx` and Docker variants.

## Background

The MCP server ships as a Python package (`comfyui-mcp`) installable via `uvx` and as a Docker image at `ghcr.io/hybridindie/comfyui_mcp`. It exposes 30+ tools via stdio transport (primary) and optional SSE.

Claude Code plugins add slash commands, contextual skills, and hooks on top of MCP tools. Other apps (VS Code, Cursor, etc.) discover MCP tools natively from config files — they don't need plugin infrastructure, just a config snippet.

### References

- [Claude Code Plugins](https://code.claude.com/docs/en/plugins)
- [Claude Code Hooks](https://code.claude.com/docs/en/hooks)
- [VS Code MCP Configuration](https://code.visualstudio.com/docs/copilot/reference/mcp-configuration)
- [Cursor MCP](https://docs.cursor.com/context/model-context-protocol)
- [Windsurf MCP](https://docs.windsurf.com/windsurf/cascade/mcp)
- [Continue.dev MCP](https://docs.continue.dev/customize/deep-dives/mcp)
- [OpenCode MCP](https://opencode.ai/docs/mcp-servers/)
- [Open WebUI MCP](https://docs.openwebui.com/features/extensibility/mcp/)

## Architecture

### Claude Code plugin structure

All plugin files live at the repo root. No changes to the MCP server source code.

```
.claude-plugin/
  plugin.json                        # Plugin manifest
.mcp.json                           # MCP server definition
hooks.json                          # PostToolUse hook definitions
hooks/
  security-warning.sh               # Security warning hook script
skills/
  comfyui-gen/SKILL.md              # /comfy:gen (orchestrating)
  comfyui-workflow/SKILL.md         # /comfy:workflow (orchestrating)
  comfyui-status/SKILL.md           # /comfy:status (simple)
  comfyui-models/SKILL.md           # /comfy:models (simple)
  comfyui-history/SKILL.md          # /comfy:history (simple)
  comfyui-progress/SKILL.md         # /comfy:progress (simple)
  comfyui-workflows/SKILL.md        # Skill: workflow building guide
  comfyui-troubleshooting/SKILL.md  # Skill: debugging guide
```

### plugin.json

```json
{
  "name": "comfyui-mcp",
  "version": "1.0.0",
  "description": "ComfyUI image generation via MCP with slash commands and skills"
}
```

**Note:** The manifest shown is the minimum required fields. During implementation, verify against the [Claude Code plugin docs](https://code.claude.com/docs/en/plugins) whether additional fields are needed for skills discovery, hooks file location, or slash command registration. Claude Code may auto-discover `skills/`, `hooks.json`, and `.mcp.json` by convention, or may require explicit declarations in the manifest.

### .mcp.json

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "uvx",
      "args": ["comfyui-mcp"],
      "env": {
        "COMFYUI_URL": "http://localhost:8188"
      }
    }
  }
}
```

## Slash commands

Six slash commands split into two categories: orchestrating (chain multiple tools) and simple (thin wrappers).

### Orchestrating commands

#### `/comfy:gen <prompt>`

Guides the user through image generation by chaining multiple tools:

1. Parse user prompt; use sensible defaults (512x512, 20 steps, cfg 7) unless overridden
2. If no model specified, call `list_models` for checkpoints and suggest one
3. Call `generate_image` with `wait=True`
4. On completion, call `get_image` to fetch the result
5. Present the image with a generation parameters summary

SKILL.md frontmatter:
```yaml
---
description: Generate an image with ComfyUI from a text prompt
---
```

#### `/comfy:workflow <template>`

Guided workflow creation from templates:

1. If no template specified, call `list_workflows` and present options
2. Call `create_workflow` with the chosen template
3. Call `validate_workflow` on the result
4. Present the workflow summary and offer to run it or modify it

SKILL.md frontmatter:
```yaml
---
description: Create a ComfyUI workflow from a template
---
```

### Simple wrapper commands

Each wraps one or two tools with formatting guidance.

| Command | Tools called | Behavior |
|---------|-------------|----------|
| `/comfy:status` | `get_queue` | Show running/pending jobs with counts. `get_queue` returns the full queue state (running and pending lists). |
| `/comfy:models [type]` | `list_models` | List models, optionally filtered by folder type argument |
| `/comfy:history` | `get_history` | Show recent completions with prompt IDs |
| `/comfy:progress <prompt_id>` | `get_progress` | Show execution progress for a specific job |

Each SKILL.md has a `description` in frontmatter and a body instructing Claude which tool(s) to call and how to format the response.

## Skills

Two contextual knowledge skills loaded when relevant to the user's question. These are pure markdown — no tool calls, just knowledge that helps Claude use the tools effectively.

### `comfyui-workflows`

Loaded when users ask about building or modifying workflows. Covers:

- API format explained (node IDs as keys, `class_type` + `inputs`)
- Connection syntax (`["node_id", output_index]`)
- Common node chains (txt2img, img2img, ControlNet, LoRA stacking)
- How to use `create_workflow`, `modify_workflow`, and `validate_workflow` together
- Tips for using `summarize_workflow` to understand existing workflows

### `comfyui-troubleshooting`

Loaded when users hit issues. Covers:

- Connection failures (ComfyUI not running, wrong URL, firewall)
- Model not found errors (wrong folder, need to download)
- Workflow execution failures (missing nodes, incompatible connections)
- Queue stuck / job not completing (interrupt, clear queue)
- Security warnings (what they mean, audit vs enforce mode)
- ComfyUI Manager / Model Manager not detected (install instructions)

## Security warning hook

A `PostToolUse` hook that fires after tool calls returning security audit findings. Surfaces a prominent warning so dangerous node detections aren't buried in tool output.

The matcher covers:
- `audit_dangerous_nodes` — explicit node scanning
- `install_custom_node`, `update_custom_node` — post-install/update audit results (from custom node management, PR #33)
- `run_workflow`, `generate_image` — workflow inspection warnings from `WorkflowInspector`

### hooks.json

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__comfyui__audit_dangerous_nodes|mcp__comfyui__install_custom_node|mcp__comfyui__update_custom_node|mcp__comfyui__run_workflow|mcp__comfyui__generate_image",
        "hooks": [
          {
            "type": "command",
            "command": "hooks/security-warning.sh"
          }
        ]
      }
    ]
  }
}
```

**Note:** The exact MCP tool name format in the matcher (e.g., `mcp__comfyui__audit_dangerous_nodes` vs `audit_dangerous_nodes`) depends on how Claude Code names MCP-provided tools. Verify during implementation and adjust the matcher pattern.

**Note:** The `hooks.json` file location shown here is at the repo root. During implementation, verify against the [Claude Code hooks docs](https://code.claude.com/docs/en/hooks) whether plugin hooks should live inside `.claude-plugin/` or at the root. Adjust the file map accordingly.

### hooks/security-warning.sh

```bash
#!/usr/bin/env bash
# Post-tool hook: surface security warnings from node audit results.
# Reads tool output JSON from stdin. Exits 0 always (non-blocking).

input=$(cat)
if echo "$input" | grep -qi "DANGEROUS"; then
  echo "SECURITY: Dangerous node patterns detected. Review the audit results above before proceeding."
fi
```

## Multi-app configuration documentation

A new "Setup" section in README.md with copy-paste config snippets. Each environment gets both `uvx` (recommended) and Docker variants where applicable.

### Claude Code

Plugin install (includes slash commands, skills, and hook):
```bash
claude plugin install github:hybridindie/comfyui_mcp
```

### Claude Desktop

Config file locations:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

uvx:
```json
{
  "mcpServers": {
    "comfyui": {
      "command": "uvx",
      "args": ["comfyui-mcp"],
      "env": { "COMFYUI_URL": "http://localhost:8188" }
    }
  }
}
```

Docker:
```json
{
  "mcpServers": {
    "comfyui": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "COMFYUI_URL=http://host.docker.internal:8188", "ghcr.io/hybridindie/comfyui_mcp"],
      "env": {}
    }
  }
}
```

### VS Code / GitHub Copilot

Config: `.vscode/mcp.json` (workspace) or via `MCP: Open User Configuration` command.

uvx:
```json
{
  "servers": {
    "comfyui": {
      "type": "stdio",
      "command": "uvx",
      "args": ["comfyui-mcp"],
      "env": { "COMFYUI_URL": "http://localhost:8188" }
    }
  }
}
```

Docker:
```json
{
  "servers": {
    "comfyui": {
      "type": "stdio",
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "COMFYUI_URL=http://host.docker.internal:8188", "ghcr.io/hybridindie/comfyui_mcp"],
      "env": {}
    }
  }
}
```

### Cursor

Config: `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global).

uvx:
```json
{
  "mcpServers": {
    "comfyui": {
      "command": "uvx",
      "args": ["comfyui-mcp"],
      "env": { "COMFYUI_URL": "http://localhost:8188" }
    }
  }
}
```

Docker:
```json
{
  "mcpServers": {
    "comfyui": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "COMFYUI_URL=http://host.docker.internal:8188", "ghcr.io/hybridindie/comfyui_mcp"],
      "env": {}
    }
  }
}
```

### Windsurf

Config: `~/.codeium/windsurf/mcp_config.json`.

uvx:
```json
{
  "mcpServers": {
    "comfyui": {
      "command": "uvx",
      "args": ["comfyui-mcp"],
      "env": { "COMFYUI_URL": "http://localhost:8188" }
    }
  }
}
```

Docker:
```json
{
  "mcpServers": {
    "comfyui": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "COMFYUI_URL=http://host.docker.internal:8188", "ghcr.io/hybridindie/comfyui_mcp"],
      "env": {}
    }
  }
}
```

### Continue.dev

Config: `.continue/config.yaml` (project) or global config.

uvx:
```yaml
mcpServers:
  - name: ComfyUI
    command: uvx
    args:
      - comfyui-mcp
    env:
      COMFYUI_URL: "http://localhost:8188"
```

Docker:
```yaml
mcpServers:
  - name: ComfyUI
    command: docker
    args:
      - run
      - "-i"
      - "--rm"
      - "-e"
      - "COMFYUI_URL=http://host.docker.internal:8188"
      - "ghcr.io/hybridindie/comfyui_mcp"
```

### OpenCode

Config: `~/.config/opencode/opencode.json` (global) or `opencode.json` (project root).

uvx:
```json
{
  "mcp": {
    "comfyui": {
      "type": "local",
      "command": "uvx",
      "args": ["comfyui-mcp"],
      "env": { "COMFYUI_URL": "http://localhost:8188" }
    }
  }
}
```

Docker:
```json
{
  "mcp": {
    "comfyui": {
      "type": "local",
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "COMFYUI_URL=http://host.docker.internal:8188", "ghcr.io/hybridindie/comfyui_mcp"],
      "env": {}
    }
  }
}
```

### Open WebUI

Open WebUI supports MCP via Streamable HTTP only — not stdio. SSE and Streamable HTTP are different protocols; our server's SSE mode may not be directly compatible.

**Recommended: MCPO proxy**

Use [MCPO](https://github.com/open-webui/mcpo) to bridge stdio to Streamable HTTP:
```bash
uvx mcpo -- uvx comfyui-mcp
```

In Open WebUI, add the MCPO endpoint (default `http://localhost:8000`) as an MCP server with type "MCP (Streamable HTTP)".

**Alternative: SSE mode (unverified)**

Our server supports SSE transport natively. Enable it in `~/.comfyui-mcp/config.yaml`:
```yaml
transport:
  sse:
    enabled: true
    host: "0.0.0.0"
    port: 8080
```

Open WebUI may accept this at `http://<host>:8080/sse`, but SSE and Streamable HTTP are different transports. Test before relying on this path. If it doesn't work, use MCPO above.

### Docker notes

All Docker snippets use:
- `-i` flag: required for stdio transport (keeps stdin open)
- `--rm`: auto-remove container on exit
- `host.docker.internal`: reaches the host machine from inside the container (macOS/Windows). On Linux, replace `-e COMFYUI_URL=http://host.docker.internal:8188` with `--network host -e COMFYUI_URL=http://localhost:8188`.
- `ghcr.io/hybridindie/comfyui_mcp`: published on every push to main. Use `ghcr.io/hybridindie/comfyui_mcp:main` for latest, or pin to a semver tag.

## File map

| File | Action | Purpose |
|------|--------|---------|
| `.claude-plugin/plugin.json` | Create | Plugin manifest |
| `.mcp.json` | Create | MCP server definition for Claude Code |
| `hooks.json` | Create | PostToolUse hook definitions |
| `hooks/security-warning.sh` | Create | Security warning hook script |
| `skills/comfyui-gen/SKILL.md` | Create | `/comfy:gen` orchestrating slash command |
| `skills/comfyui-workflow/SKILL.md` | Create | `/comfy:workflow` orchestrating slash command |
| `skills/comfyui-status/SKILL.md` | Create | `/comfy:status` simple slash command |
| `skills/comfyui-models/SKILL.md` | Create | `/comfy:models` simple slash command |
| `skills/comfyui-history/SKILL.md` | Create | `/comfy:history` simple slash command |
| `skills/comfyui-progress/SKILL.md` | Create | `/comfy:progress` simple slash command |
| `skills/comfyui-workflows/SKILL.md` | Create | Workflow building guide skill |
| `skills/comfyui-troubleshooting/SKILL.md` | Create | Troubleshooting guide skill |
| `README.md` | Modify | Add Setup section with multi-app config snippets |
| `.gitignore` | Modify | Ensure plugin/skill files are tracked (not ignored) |

## Testing

Plugin files are markdown and JSON — no unit tests needed. Verification is manual:

1. `claude plugin install .` from repo root — verify slash commands appear
2. Type `/comfy:gen "a sunset"` — verify orchestration flow
3. Type `/comfy:status` — verify tool is called and output formatted
4. Trigger a security warning (install a node with dangerous patterns) — verify hook fires
5. Verify all config snippets are syntactically valid JSON/YAML

## Out of scope

- VS Code marketplace extension (config snippets in README are sufficient)
- Prompt engineering skill (model-specific tips change too frequently)
- Job completion hook (redundant with `wait=True`)
- Agents (skills + slash commands cover the use cases)
- Publishing to a Claude Code plugin marketplace (can be added later)
- Changes to the MCP server source code (all plugin files are additive)
- Ollama Desktop (no native MCP support yet)
