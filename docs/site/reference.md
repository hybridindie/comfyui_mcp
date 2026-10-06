---
type: index
title: "Reference"
description: "The surface in detail — every tool, resource, config knob, env var, and error."
created: 2026-10-06
updated: 2026-10-06
---

# Reference

Authoritative tables for the surface. The source of truth is the code +
`README.md` in the repo — these pages are the readable map.

- [Tools](reference-tools.md) — all 53, grouped by module
- [Resources & prompts](reference-resources-prompts.md) — the `comfyui://` URIs and the 4 recipes
- [Configuration](reference-config.md) — every config field with defaults
- [Environment variables](reference-env-vars.md) — every override
- [Server capability flags](reference-server-features.md) — the `/features` keys worth reasoning about
- [Errors & recovery](reference-errors.md) — the failure shapes and how to recover
- [Changelog](changelog.md) — what shipped in each release

!!! note "For LLM agents"
    The site serves [`llms.txt`](https://hybridindie.github.io/comfyui_mcp/llms.txt)
    (page index) and
    [`llms-full.txt`](https://hybridindie.github.io/comfyui_mcp/llms-full.txt)
    (everything as one markdown document) — point agents at those instead of
    crawling HTML.