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

- **It asks before a risky graph runs.** In enforce mode, a workflow with
  dangerous nodes pauses for your OK; a decline never reaches ComfyUI.
- **It previews instead of dumping megabytes.** Images come back as a webp
  thumbnail by default; full-size is a choice.
- **It checks the model first.** A wrong checkpoint name fails before the
  queue is touched.
- **It tells you when media is too big to inline.** Video/audio over 8 MiB
  comes back as a `/view` link instead.
- **It cannot see your screen.** Answer its questions about the image or the
  result; a vision-capable client can look at what it fetched.

## If something is off

| What you see | What to do |
|---|---|
| "Connection refused" / ComfyUI unreachable | Start ComfyUI, or point `COMFYUI_URL` at the right host. Run `scripts/doctor.py` if you have the repo. |
| "Model not found" | Ask it to list your checkpoints; the name must match the file exactly. |
| "Workflow has warnings" | Read them; approve only if you trust the node. |
| "Upload too large" | The server's `max_upload_size` wins — downscale or compress. |
| Download tools say Model Manager is missing | Install the ComfyUI-Model-Manager plugin, or download models another way. |
| Video won't display inline | It is over 8 MiB; use the returned `/view` link. |

---

**Technical reader?** The [developer track](getting-started.md) covers
installation details, configuration, the security model, the tool contract,
and how to extend or contribute.
