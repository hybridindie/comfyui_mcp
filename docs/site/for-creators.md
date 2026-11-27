---
type: index
title: "For creators"
description: "Make images, edit them, and run batches by talking to your AI assistant. Set up ComfyUI MCP once, then work in plain language."
created: 2026-11-27
updated: 2026-11-27
---

# For creators

**You make images. You want an AI assistant to drive ComfyUI for you.**
This track gets you there without learning MCP or typing tool names.

ComfyUI MCP connects your assistant to the ComfyUI you already run. The
assistant can list your models, generate and edit images, run a batch, and
fetch the results — while the server inspects every workflow, sanitizes file
paths, and keeps an audit trail.

## What you need

- A running **ComfyUI** — local (`127.0.0.1:8188`) or a URL you can reach.
- An AI client that can call MCP servers — OpenCode, Claude Code,
  Claude Desktop, Cursor, or any MCP client.
- That's it. The server is a single `pip`/`uvx` install, or a Docker image.

## Start here

1. **[Set up with your AI agent](getting-started-with-an-agent.md)** — one
   copy-paste prompt, or four short manual steps.
2. **[Your first session](getting-started-first-session.md)** — ask for an
   image and follow what happens.
3. **Describe what you want** — *"a yellow apple on a wooden table"*,
   *"make this photo look like an oil painting"*, *"give me four seeds of the
   same prompt"*.

## Then make things

- **[Generate images](guides-generate.md)** — prompt → image, model choice,
  thumbnails.
- **[Edit images](guides-edit.md)** — img2img, inpaint a region, or upscale.
- **[Batch generation](guides-batch.md)** — a prompt/seed matrix without
  flooding the queue.
- **[Video and audio outputs](guides-media.md)** — find, fetch, and display
  media that is not an image.
- **[Work with custom workflows](guides-custom-workflows.md)** — bring a graph
  from the ComfyUI UI.
- **[Manage models](guides-manage-models.md)** — see what is installed, search
  HuggingFace/CivitAI, download through Model Manager.
- **[Skills](reference-skills.md)** — the recipes that teach the assistant the
  common flows.

## What the assistant can do

| You say… | What happens |
|---|---|
| "generate a …" | Picks a checkpoint, runs txt2img, fetches a preview |
| "turn this into …" | Img2img with a strength you can tune |
| "remove the … from this photo" | Inpaint with a mask (white = regenerate) |
| "make it bigger" | Model-based upscale |
| "four variations of this prompt" | Bounded batch, one prompt id per variant |
| "what models do I have?" | Lists checkpoints/loras/vae from the live server |
| "show me the last video" | Fetches a video/audio output by URL or inline if small |

## What to expect

- **Audit mode is the default.** Every workflow is inspected and logged;
  dangerous nodes produce warnings but do not block. In **enforce mode**
  (opt-in), a flagged workflow pauses for your OK, and a decline never reaches
  ComfyUI. Enforce mode only hard-blocks nodes outside `allowed_nodes` when
  that list is non-empty; otherwise the warning/elicitation gate is the
  control.
- **Previews are a choice.** The `gen` skill fetches a ~90 KB webp thumbnail,
  but a direct `comfyui_get_image` call returns the full image unless
  `preview_format="webp"` is passed.
- **The checkpoint is checked on generation.** `comfyui_generate_image`
  verifies a named checkpoint before touching the queue; the edit tools fail
  at submission if the name is wrong.
- **Big media comes back as a link.** `comfyui_get_output` returns a `/view`
  URL by default. If you ask for `inline`, anything over 8 MiB still comes
  back as a link.
- **The `core` tool profile trims the surface.** With `tools.profile: "core"`,
  `comfyui_generate_batch` and `comfyui_get_output` are hidden. The default
  `full` profile has them.
- **It cannot see your screen.** Answer its questions about the image or the
  result; a vision-capable client can look at what it fetched.

## If something is off

| What you see | What to do |
|---|---|
| "Connection refused" / ComfyUI unreachable | Start ComfyUI, or point `COMFYUI_URL` at the right host. Run `comfyui-mcp-doctor` (ships with the package). |
| "Model not found" | Ask it to list your checkpoints; the name must match the file exactly. |
| Checkpoint list is empty | A fresh ComfyUI has no models. Put a checkpoint in `models/checkpoints/`, or install/download one (Model Manager is optional). |
| "Workflow has warnings" | Read them; approve only if you trust the node. |
| "Upload too large" | The server's `max_upload_size` wins — downscale or compress. |
| Video/audio upload rejected | MCP uploads accept images and JSON only. Put the file in ComfyUI's `input/` folder and pass its filename. |
| Download tools say Model Manager is missing | Install the ComfyUI-Model-Manager plugin, or download models another way. |
| Batch or video tool missing | `tools.profile: "core"` hides them; switch to the default `full` profile. |
| Video won't display inline | You asked for `inline` and it is over 8 MiB — use the returned `/view` link. `url` is the default. |

---

**Technical reader?** The [developer track](getting-started.md) covers
installation details, configuration, the security model, the tool contract,
and how to extend or contribute.
