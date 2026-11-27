---
type: reference
title: "Skills"
description: "The installable recipes that teach an AI assistant the common ComfyUI flows — generation, editing, batches, security review, and client setup."
created: 2026-11-27
updated: 2026-11-27
---

# Skills

Beyond tools, prompts, and resources, this repo ships **skills** under
[`skills/`](https://github.com/hybridindie/comfyui_mcp/tree/main/skills): plain
Markdown recipes an agent loads when it recognises the task. Tools tell the
model what it *can* do; skills tell it how to do it *well*.

They are optional — the tools work without them — but a client that installs
them inherits the parameter judgment, the upload order, the batch limits, and
the security-review sequence without you re-explaining them each session.

## Skills vs prompts

| | Skills (`skills/*/SKILL.md`) | MCP prompts (`txt2img_prompt`, …) |
|---|---|---|
| Invoked by | The **agent**, when the task matches | The **user**, as a slash command or prompt picker |
| Shape | Steps + decision rules + notes | A short recipe the client requests by name |
| Lives | On disk, in the client's skills directory | In the server |
| Use for | "Know how to do this flow" | "Give me this specific recipe" |

They compose: a skill teaches the flow and points at the tools; a prompt is a
one-shot recipe the server hands back.

## The twelve skills

| Skill | Use when | What it does |
|---|---|---|
| `gen` | "generate an image" | Picks a model, calls `comfyui_generate_image(wait=True)`, fetches a preview |
| `edit` | "edit / restyle / remove / enlarge" | Routes img2img vs inpaint vs upscale, handles uploads and masks, chooses strength |
| `batch` | "four variations", "seed sweep" | Builds a prompt/seed matrix, submits in waves around the 8-variant cap |
| `workflow` | "build a workflow from a template" | Creates, validates, then offers to run or modify |
| `workflows` | "how do nodes connect?" | Knowledge: workflow JSON format, common chains, node reference |
| `security-review` | "lock this down", "what can run?" | Audits nodes, derives an allowlist, chooses a warning policy, switches to enforce |
| `connect` | "add this to Claude/Cursor" | stdio vs authenticated HTTP, per-client env interpolation, read-only verification |
| `status` | "what is the queue doing?" | Running and pending job counts |
| `progress` | "how is my job going?" | Per-prompt progress, current node, steps, outputs |
| `history` | "what did I make recently?" | Recent completions with prompt ids and filenames |
| `models` | "what models do I have?" | Lists checkpoints/loras/vae, optionally by folder |
| `troubleshooting` | any error | Connection, missing model, workflow failure, stuck queue, plugin setup |

## Install

Clone the repo and copy the folders into your client's skills directory:

```bash
git clone --depth 1 https://github.com/hybridindie/comfyui_mcp /tmp/comfyui-mcp
mkdir -p ~/.config/opencode/skills
cp -r /tmp/comfyui-mcp/skills/* ~/.config/opencode/skills/
```

- **Claude Code / Claude Desktop:** `~/.claude/skills/`
- **OpenCode:** `~/.config/opencode/skills/`
- **Clients without a skills directory:** open the relevant `SKILL.md` and paste
  it into your always-on rules (`AGENTS.md`, a Cursor rule, or the client's
  instructions field).

Restart the client after copying. Skills activate automatically when their
description matches the task; they are not tools and do not appear in the tool
list.

Copy rather than symlink: some clients do not list files under a symlinked
skill directory.

## The four MCP prompts

These live in the server and work in any client, skills or not:

| Prompt | Returns |
|---|---|
| `txt2img_prompt(prompt, style)` | Guidance for `comfyui_generate_image` |
| `img2img_prompt(image, prompt, style)` | Guidance for `comfyui_transform_image` |
| `inpaint_prompt(image, mask, prompt, style)` | Guidance for `comfyui_inpaint_image` |
| `upscale_prompt(image, upscale_model)` | Guidance for `comfyui_upscale_image` |

## Keeping them honest

The skills are prose, not generated code, so a tool change can leave a step
stale. If a skill names a call that no longer exists, the authoritative list is
the [Tools reference](./reference-tools.md); treat the skill as guidance and the
tool schema as the contract. Issues and PRs that bring a skill back in line are
welcome.

The long-form versions of the same flows are
[Generate images](./guides-generate.md), [Edit images](./guides-edit.md), and
[Batch generation](./guides-batch.md).
