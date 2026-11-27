---
type: walkthrough
title: "Set up with your AI agent"
description: "One prompt — or four manual steps — to install ComfyUI MCP, connect it to your client, and make the first image."
created: 2026-11-27
updated: 2026-11-27
---

# Set up with your AI agent

You do not need to learn MCP. Hand this to your assistant, or follow the four
manual steps below.

## The one-prompt version

Paste this into your AI client and answer its questions:

```text
Install the comfyui-mcp-secure MCP server on this machine.
Use `uv tool install comfyui-mcp-secure` (or `pipx install comfyui-mcp-secure`).
Confirm ComfyUI is running at http://127.0.0.1:8188; if it is somewhere else,
ask me for the URL. Then add `comfyui-mcp-secure` as a stdio MCP server to this
client and restart/reload so the tools appear. Finally, call
comfyui_list_models for the checkpoints folder and tell me what is installed.
```

If the client cannot edit its own config, it will print the JSON for you to
paste — the manual steps below are that JSON.

## Manual setup

1. **Install the server.**

   ```bash
   uv tool install comfyui-mcp-secure
   # or: pipx install comfyui-mcp-secure
   # or: pip install comfyui-mcp-secure
   ```

2. **Make sure ComfyUI is running.** The default is
   `http://127.0.0.1:8188`; if yours is elsewhere:

   ```bash
   export COMFYUI_URL=http://your-comfyui:8188
   ```

3. **Add it to your client.** Most clients take a `mcpServers` block:

   ```json
   {
     "mcpServers": {
       "comfyui": {
         "command": "comfyui-mcp-secure",
         "env": {
           "COMFYUI_URL": "http://127.0.0.1:8188"
         }
       }
     }
   }
   ```

   Client-specific locations and remote/HTTP setup:
   [Add to your MCP client](./getting-started-clients.md).

4. **Restart or reload the client**, then ask:

   > List my checkpoints, then generate a yellow apple on a wooden table.

## What you should see

- `comfyui_list_models(folder="checkpoints")` returns your installed files.
- `comfyui_generate_image(..., wait=True)` returns `status: "completed"` and an
  output filename.
- `comfyui_get_image(..., preview_format="webp")` shows a thumbnail inline.

If nothing appears, the assistant will usually say the server is not connected
or ComfyUI is unreachable. The troubleshooting table on
[For creators](./for-creators.md#if-something-is-off) covers the common cases.

## Optional, but worth it

- **Skills** teach the assistant the generation, edit, batch, and
  security-review flows. See [Skills](./reference-skills.md) for the copy
  command.
- **Enforce mode** asks you before a workflow with dangerous nodes runs. The
  default is audit mode (log only); see
  [enforce mode](./security-enforce-mode.md).
- **Model downloads** need the
  [ComfyUI-Model-Manager](https://github.com/hayden-cn/ComfyUI-Model-Manager)
  plugin. Browsing installed models and generating do not.
