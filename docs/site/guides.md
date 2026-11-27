---
type: index
title: "Guides"
description: "Task-oriented recipes — generating and editing images, batches, custom workflows, models, and production deployment."
created: 2026-10-06
updated: 2026-11-27
---

# Guides

Task-oriented walks that compose the reference pages. Each shows the
`comfyui_*` calls the **agent** makes on your behalf — you prompt in plain
language and the calls are listed so you can follow along and spot where
the agent stalled. New here? Start with
[your first session](getting-started-first-session.md).

## Create

- [Generate images](guides-generate.md) — the generate loop: model discovery, params, thumbnails
- [Edit images](guides-edit.md) — img2img, inpaint, upscale
- [Batch generation](guides-batch.md) — prompt/seed matrices, the 8-variant cap, collecting results
- [Video and audio outputs](guides-media.md) — find media in history, fetch by URL/path/inline, the 8 MiB cap
- [Custom workflows](guides-custom-workflows.md) — templates → modify → validate → run, including partial re-execution
- [Manage models](guides-manage-models.md) — search, download, presets, prompting guidance, and the download lifecycle quirks
- [Skills](reference-skills.md) — the installable recipes behind these flows

## Operate

- [Which interface?](guides-which-tool.md) — MCP vs CLI vs the official server vs the UI
- [Run securely in production](guides-production.md) — enforce mode, allowlists, reverse proxy, audit hygiene
- [Docker deployment](guides-docker.md) — the GHCR image, config mounting, compose
