---
type: reference
title: "Environment variables"
description: "Every env override, with what it maps to."
created: 2026-10-06
updated: 2026-10-06
---

# Environment variables

Environment variables override `config.yaml` values. Useful in Docker and
CI where files are awkward.

| Variable | Overrides |
|----------|-----------|
| `COMFYUI_URL` | `comfyui.url` |
| `COMFYUI_EXTERNAL_URL` | `comfyui.external_url` |
| `COMFYUI_TLS_VERIFY` | `comfyui.tls_verify` |
| `COMFYUI_TIMEOUT_CONNECT` | `comfyui.timeout_connect` |
| `COMFYUI_TIMEOUT_READ` | `comfyui.timeout_read` |
| `COMFYUI_SECURITY_MODE` | `security.mode` |
| `COMFYUI_AUDIT_FILE` | `logging.audit_file` |
| `COMFYUI_HUGGINGFACE_TOKEN` | `model_search.huggingface_token` |
| `COMFYUI_CIVITAI_API_KEY` | `model_search.civitai_api_key` |
| `COMFYUI_MAX_SEARCH_RESULTS` | `model_search.max_search_results` |
| `COMFYUI_ALLOWED_DOWNLOAD_DOMAINS` | `security.allowed_download_domains` |
| `COMFYUI_TASKS_ENABLED` | `tasks.enabled` |
| `COMFYUI_TASKS_BACKEND_URL` | `tasks.backend_url` (`memory://` or `redis://...`) |

## Secrets

Prefer environment variables over config files for tokens so secrets don't
sit in files that might get committed or mounted read-only into images:

```bash
export COMFYUI_HUGGINGFACE_TOKEN="hf_xxx"
export COMFYUI_CIVITAI_API_KEY="xxx"
```

The audit log redacts `token`, `password`, `secret`, `api_key`,
`authorization` fields — but avoid echoing secrets in shell history
regardless.

## Model-search keys

`comfyui_search_models` and `comfyui_download_model` work without keys for
many public models. Add keys for gated/private resources or higher provider
limits — details under [config](reference-config.md).