# comfyui-mcp-secure

A secure MCP (Model Context Protocol) server for [ComfyUI](https://github.com/comfyanonymous/ComfyUI). Enables AI assistants to generate images, run workflows, and manage jobs through ComfyUI — with built-in security controls that existing ComfyUI MCP servers lack.

> **Using OpenCode?** This repo ships agent configuration under `.opencode/` — grounding rules (`.opencode/rules/`), a read-only `review` subagent, a `/preflight` command, and a graphify plugin — all pre-wired to the MCP server. See [AGENTS.md](./AGENTS.md) for the entry point. The server itself works with **any** MCP client over stdio or Streamable HTTP.

## Why this exists

Every existing ComfyUI MCP server is a thin passthrough to ComfyUI's API with no security guardrails. They allow arbitrary workflow execution (including malicious custom nodes that run `eval`/`exec`), have no input validation, no file path sanitization, no rate limiting, and no audit trail.

This server adds five security layers between the AI assistant and ComfyUI:

| Layer | What it does |
|-------|-------------|
| **Workflow Inspector** | Parses every workflow before execution, extracts node types, flags dangerous patterns (`eval`, `exec`, `__import__`, `subprocess`). Configurable audit-only or enforcement mode. In enforce mode, dangerous-node and suspicious-input warnings **elicit the user** for confirmation before submission. |
| **Path Sanitizer** | Validates all filenames, subfolders, and URL path segments — blocks path traversal (`../`), null bytes, percent-encoded attacks, absolute paths, and disallowed file extensions. Templated resources (`comfyui://models/{folder}`) also inherit FastMCP 4's built-in path-traversal screening. |
| **SecurityMiddleware** | Centralized rate-limit checks + entry audit logging across every tool call via the FastMCP 4 `on_call_tool` hook. Sensitive tool arguments (`token`, `password`, `api_key`) are redacted before the audit record is written. |
| **Audit Logger** | Structured JSON logging of every operation with automatic redaction of sensitive fields (tokens, passwords). |
| **Selective API Surface** | Only exposes safe ComfyUI endpoints. Dangerous endpoints (`/userdata`, `/free`, `/users`) are never proxied. `/system_stats` is called internally by `comfyui_get_system_info` but only a strict whitelist (GPU VRAM, queue counts, version) is returned. |

### Resources & Prompts (FastMCP 4)

The server exposes read-only ComfyUI state as **resources** the LLM can browse by URI without a tool call, and **prompts** as reusable workflow-template recipes:

- **Resources**: `comfyui://models/{folder}`, `comfyui://nodes/installed`, `comfyui://queue`, `comfyui://system`, `comfyui://settings`
- **Prompts**: `txt2img_prompt`, `img2img_prompt`, `inpaint_prompt`, `upscale_prompt`

### Dependency injection & background tasks (FastMCP 4)

- **Depends() DI** — tool modules may declare their dependencies (`client`, `audit`, `inspector`, `limiter`) via `Depends()` providers (auto-excluded from the MCP schema) instead of receiving them through `register_*_tools()` factories. `history_di.py` is the canonical DI module; the remaining tools migrate incrementally.
- **Background tasks** (optional) — long-running workflows can run as background tasks via `TasksExtension` (Docket-backed) instead of holding the request open. Disabled by default; see [Background tasks](#background-tasks-optional-phase-6).

### Real-time progress tracking

When `wait=True` is passed to `comfyui_generate_image` or `comfyui_run_workflow`, the server connects to ComfyUI's WebSocket to track execution in real time — reporting step progress, current node, and output files when complete. If the WebSocket connection fails, it automatically falls back to HTTP polling. Use `comfyui_get_progress` to check status of any job at any time.

For workflow streaming, use the mode that matches your use case:

- `comfyui_run_workflow(..., wait=True)` returns a summarized, tool-friendly completion response.
- `comfyui_run_workflow_stream(...)` returns raw WebSocket event flow (`progress`, `executing`, `executed`, etc.) plus final status and outputs.

### Structured output & rich schemas

Tools expose Pydantic `Field` constraints on input parameters (ranges, lengths, descriptions) and `outputSchema` for structured responses. MCP clients get:

- **Input validation**: Parameter constraints like `steps: 1-100`, `cfg: 1.0-30.0`, `width: 64-4096` appear in the tool's JSON schema
- **Output schemas**: 26 tools return structured data with auto-generated `outputSchema`, enabling clients to parse responses without guessing the shape
- **Streamable HTTP transport**: Optional remote transport via `transport.remote.enabled` using the MCP spec's recommended Streamable HTTP protocol

## Recent Breaking Changes (2026-05)

> **2.1.0 (2026-05-12) is additive — no breaking changes since 2.0.0.** Adds
> `comfyui_analyze_workflow`, replaces the bespoke Ollama eval runner with an
> Inspect AI Task module, and introduces a Phase 5 live-execution eval. See
> the [CHANGELOG](CHANGELOG.md) for the full per-PR breakdown. The breaking
> changes below all shipped in 2.0.0.

**Parameter renames** — update keyword arguments (positional calls are unaffected):

- `comfyui_install_custom_node`, `comfyui_uninstall_custom_node`, `comfyui_update_custom_node`: `id` → `node_id`.
- `comfyui_summarize_workflow`: `format` → `output_format`, restricted to `text` or `mermaid` via a Pydantic `Literal`.

**Response-shape changes** — these tools now return the standard pagination envelope `{items, total, offset, limit, has_more}` instead of bare lists or raw dicts:

- `comfyui_list_extensions` (was: `list[str]`)
- `comfyui_list_model_folders` (was: `list[str]`)
- `comfyui_list_workflows` (was: `dict[package_name, list[template]]`; now flattened to `items: [{package, templates}]`)

Callers must update to read `result["items"]` instead of indexing the response directly. The new envelope also exposes `limit` and `offset` parameters for pagination.

**Unified return envelope for workflow-submitting tools** — `comfyui_run_workflow`, `comfyui_run_workflow_stream`, `comfyui_generate_image`, `comfyui_transform_image`, `comfyui_inpaint_image`, `comfyui_upscale_image` now all return a uniform `dict[str, Any]` regardless of `wait`/`stream` mode:

```
{
  "status": "submitted" | "completed" | "interrupted" | "error" | "timeout",
  "prompt_id": "<uuid>",
  "warnings": [...]             # only when the workflow inspector produced warnings
  # When wait=True or stream:
  "outputs": [...],
  "elapsed_seconds": float,
  "step" / "total_steps" / "current_node" / "queue_position": ...,
  # When stream:
  "events": [...]
}
```

Previously these tools returned either a free-form sentence (`wait=False`) or a JSON-serialized string (`wait=True`/stream), forcing callers to try both shapes. Callers that previously parsed the response as text — or via `json.loads()` for `wait=True` — must update to read fields directly off the dict.

## Quick start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- A running ComfyUI instance (local or remote)

### Install

#### Option A: From PyPI

```bash
pip install comfyui-mcp-secure
```

For an isolated CLI install, use one of:

```bash
uv tool install comfyui-mcp-secure
pipx install comfyui-mcp-secure
```

For a one-shot run without installing first:

```bash
uvx comfyui-mcp-secure --help
```

#### Option B: From source (recommended for development)

```bash
git clone https://github.com/hybridindie/comfyui_mcp.git
cd comfyui_mcp
uv sync
```

#### Option C: Docker (no clone required)

```bash
docker pull ghcr.io/hybridindie/comfyui_mcp:latest
```

Or build locally from the repo:

```bash
docker build -t comfyui-mcp-secure .
```

### Configure

Create a minimal config for your ComfyUI instance:

```bash
mkdir -p ~/.comfyui-mcp
cat > ~/.comfyui-mcp/config.yaml << 'EOF'
comfyui:
  url: "http://127.0.0.1:8188"
EOF
```

For a remote server:

```bash
cat > ~/.comfyui-mcp/config.yaml << 'EOF'
comfyui:
  url: "https://your-gpu-server:8188"
EOF
```

### Add to your MCP client

The MCP server communicates over stdio. Add one of the following configurations to your MCP client (OpenCode, Claude Desktop, Cursor, or any stdio MCP client) depending on how you installed.

**From source (uv):**

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "uv",
      "args": ["--directory", "/path/to/comfyui_mcp", "run", "comfyui-mcp-secure"]
    }
  }
}
```

**From PyPI / pipx / uv tool install:**

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "comfyui-mcp-secure"
    }
  }
}
```

**From PyPI without a persistent install (`uvx`):**

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "uvx",
      "args": ["comfyui-mcp-secure"]
    }
  }
}
```

**Docker (GitHub Container Registry):**

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "COMFYUI_URL=http://host.docker.internal:8188",
        "-v", "~/.comfyui-mcp:/home/app/.comfyui-mcp:ro",
        "ghcr.io/hybridindie/comfyui_mcp:latest"
      ]
    }
  }
}
```

> **Note:** `host.docker.internal` routes to your host machine from inside Docker. If ComfyUI runs on a remote server, replace with that server's URL. On Linux, you may need to add `--add-host=host.docker.internal:host-gateway`.

### Agent configuration (OpenCode)

This repository ships agent configuration under `.opencode/` for [OpenCode](https://opencode.ai) (and any harness that reads `AGENTS.md`). The server itself is harness-agnostic — it works with any MCP client over stdio or Streamable HTTP.

Agent-related files in this repo:

- `AGENTS.md` — harness-agnostic entry point; index of the grounding rules
- `.opencode/opencode.json` — wires `context7` (MCP/FastMCP/Pydantic/httpx docs), a `review` subagent, a `/preflight` command, the graphify plugin, and a `watcher.ignore`
- `.opencode/rules/` — path-scoped constitutional rules (security, architecture, tools, testing, workflow, enforcement, graphify); loaded as `instructions` in `opencode.json`
- `.opencode/agents/review.md` — read-only pre-PR reviewer subagent
- `.opencode/commands/preflight.md` — `/preflight` command (lint/format/type/tests gate)
- `.opencode/hooks/check-no-skipped-tests.sh` — zero-skip suite-health gate
- `.opencode/plugins/graphify.js` — knowledge-graph reminder plugin
- `skills/` — convenience recipes that wrap common multi-tool flows (`gen`, `workflow`, `status`, `progress`, `history`, `models`, `troubleshooting`, `workflows`)

#### Skills

The `skills/` directory contains pre-authored recipes that wrap common multi-tool flows so a user doesn't have to choreograph the calls themselves. They are harness-agnostic markdown and work with any agent that loads them. The two "knowledge" skills (`workflows`, `troubleshooting`) are auto-applied when the conversation matches their topic.

| Skill | What it does |
|---|---|
| `gen <prompt>` | Generate an image. Picks a model via `comfyui_list_models`, calls `comfyui_generate_image(wait=True)`, fetches the result via `comfyui_get_image`. |
| `workflow <description>` | Build a workflow from a built-in template, validate it, then offer to run or modify. |
| `workflows` | Knowledge skill — auto-applied when the conversation involves building/modifying workflows. Covers workflow JSON format, common node chains (txt2img/img2img/ControlNet/LoRA), and the key node reference. |
| `status` | Show queue state (running + pending jobs). |
| `progress <prompt_id>` | Per-job execution progress (current node, step X of Y, status). |
| `history` | Recent completions with prompt IDs and output filenames. |
| `models [folder]` | List models in a folder type (defaults to `checkpoints`). |
| `troubleshooting` | Knowledge skill — auto-applied when users report connection, model, workflow, or security errors. Covers connection failures, model-not-found, workflow execution failures, queue-stuck, security warnings, and the two upstream-plugin (ComfyUI-Manager, ComfyUI-Model-Manager) setup issues. |

#### Security warnings in the tool response

The workflow inspector and node auditor surface warnings directly in the tool response envelope. When `comfyui_run_workflow`, `comfyui_generate_image`, `comfyui_audit_dangerous_nodes`, `comfyui_install_custom_node`, or `comfyui_update_custom_node` detect dangerous node patterns (`"Dangerous node type"`, `"Suspicious input"`, or `dangerous.count > 0`), the response includes a `warnings` array. The agent reads this from the tool output and asks the user to confirm before proceeding — exactly the audit-mode-default behavior the project ships with.

#### End-to-end example

A user asks to generate "a yellow apple, photorealistic, 4k". The layers cooperate:

1. The `gen` skill parses the prompt and applies defaults (512×512, 20 steps, cfg 7.0).
2. It calls `comfyui_list_models(folder="checkpoints")`, picks an available model from the paginated `items` list, and confirms with the user if ambiguous.
3. It calls `comfyui_generate_image(prompt=..., model=..., wait=True)`.
4. Server-side, the MCP tool runs `WorkflowInspector.inspect()` on the workflow before submitting it to ComfyUI. With a clean built-in workflow there are no warnings.
5. ComfyUI executes; the tool blocks until the unified envelope comes back with `status="completed"`.
6. The skill reads `result["outputs"][0]` (a `{node_id, filename, subfolder}` dict), calls `comfyui_get_image(filename=..., subfolder="output", preview_format="webp", preview_quality=80)` for a cheap thumbnail, and presents the image inline.

Contrast that with running a user-supplied custom workflow that contains an `Exec`-class node: step 4's inspector emits `warnings: ["Dangerous node type: Exec..."]`, and the response envelope carries:

```
SECURITY: Dangerous node patterns detected. Review the audit results above before proceeding.
```

The agent sees this in the tool output and asks the user to confirm before continuing — exactly the audit-mode-default behavior the project ships with.

### Verify

```bash
# From source
uv run python -c "from comfyui_mcp.server import mcp; print(f'Server {mcp.name!r} ready')"

# Docker
docker run --rm ghcr.io/hybridindie/comfyui_mcp:latest --help
```

## Tools

### Generation & Workflows

| Tool | Description |
|------|-------------|
| `comfyui_generate_image` | Text-to-image using a built-in workflow. Params: prompt, negative_prompt, width, height, steps, cfg, model. Set `wait=True` to block until complete and return outputs. |
| `comfyui_transform_image` | Image-to-image transformation. Params: image (filename), prompt, negative_prompt, strength (0.0-1.0), steps, cfg, model. Input must be uploaded via `comfyui_upload_image` first. |
| `comfyui_inpaint_image` | Inpaint masked regions of an image. Params: image, mask (filenames), prompt, negative_prompt, strength, steps, cfg, model. Both files must be uploaded first. |
| `comfyui_upscale_image` | Upscale an image using a model-based upscaler. Params: image (filename), upscale_model (default: RealESRGAN_x4plus.pth). |
| `comfyui_run_workflow` | Submit arbitrary ComfyUI workflow JSON. Inspected for dangerous nodes before execution. Set `wait=True` to block until complete and return outputs. |
| `comfyui_run_workflow_stream` | Submit workflow JSON and capture ComfyUI websocket stream events (`progress`, `executing`, `executed`, etc.) until terminal status, returning events plus final outputs/status. |
| `comfyui_summarize_workflow` | Summarize a workflow's structure, data flow, models, and parameters. Supports `output_format="text"` (default) or `output_format="mermaid"` for diagram markup. |
| `comfyui_create_workflow` | Create a workflow from templates including txt2img/img2img/upscale/inpaint, txt2vid_animatediff/txt2vid_wan, controlnet_canny/controlnet_depth/controlnet_openpose, ip_adapter, lora_stack, face_restore, flux_txt2img, and sdxl_txt2img. |
| `comfyui_modify_workflow` | Apply batch operations (add_node, remove_node, set_input, connect, disconnect) to a workflow. |
| `comfyui_analyze_workflow` | Return a structured analysis of a workflow as a dict (`node_count`, `class_types`, `flow`, `models`, `parameters`, `pipeline`, `prompt_nodes`, `negative_nodes`). Use this when you want to read fields like `pipeline` programmatically; use `comfyui_summarize_workflow` for a human-readable text or Mermaid rendering. |
| `comfyui_validate_workflow` | Validate workflow structure, server compatibility, and security. |

### Job Management

| Tool | Description |
|------|-------------|
| `comfyui_get_queue` | Get current execution queue state. |
| `comfyui_list_jobs` | List jobs across queue + history with status filter, sorting, and pagination. |
| `comfyui_get_job` | Look up a single job (queued/running/finished) by prompt_id. |
| `comfyui_cancel_job` | Cancel a running or queued job. Uses the native `/api/jobs/{id}/cancel` endpoint and falls back to the legacy `/queue` delete on 404 (older ComfyUI builds). |
| `comfyui_cancel_jobs` | Batch-cancel one or more jobs by prompt_id via `/api/jobs/cancel`. |
| `comfyui_interrupt` | Interrupt the running workflow (global, or targeted via optional prompt_id). |
| `comfyui_get_queue_status` | Get detailed queue status including running and pending prompts. |
| `comfyui_clear_queue` | Clear pending and/or running items from the queue. |
| `comfyui_get_progress` | Get execution progress for a workflow by prompt_id. Returns status, queue position, and outputs. |

### Discovery

| Tool | Description |
|------|-------------|
| `comfyui_list_models` | List available models by folder (checkpoints, loras, vae, etc.). |
| `comfyui_list_models_detailed` | List models in a folder with file metadata (name, `pathIndex`, `modified`, `created`, `size`) from `/experiment/models/{folder}`. Use this when you need the `pathIndex` for preview lookups. |
| `comfyui_get_model_preview` | Fetch a model's preview image via `/experiment/models/preview/{folder}/{path_index}/{filename}`. Returns base64-encoded image data + mime type, or `{"available": false}` on 404. |
| `comfyui_list_nodes` | List all available node types. |
| `comfyui_get_node_info` | Get detailed info about a specific node type. |
| `comfyui_list_workflows` | List saved workflow templates. |
| `comfyui_list_extensions` | List available ComfyUI extensions. |
| `comfyui_get_server_features` | Get ComfyUI server features and capabilities. |
| `comfyui_list_model_folders` | List available model folder types. |
| `comfyui_get_model_metadata` | Get metadata for a specific model file. |
| `comfyui_audit_dangerous_nodes` | Scan all installed nodes to identify potentially dangerous ones. |
| `comfyui_get_system_info` | Sanitized GPU VRAM, queue depth, and ComfyUI version (whitelist-filtered from `/system_stats`). |
| `comfyui_get_settings` | Read ComfyUI server settings (sampler defaults, UI prefs, feature flags) from `GET /settings`. |
| `comfyui_update_settings` | Merge new settings into the ComfyUI server config via `POST /settings` (audit-logged; mutating). |

### Custom Node Management

| Tool | Description |
|------|-------------|
| `comfyui_search_custom_nodes` | Search ComfyUI Manager registry custom node packs by name/description/author. |
| `comfyui_install_custom_node` | Queue install for a custom node pack by `node_id`; optional restart and post-install security audit. |
| `comfyui_uninstall_custom_node` | Queue uninstall for a custom node pack by `node_id`; optional restart. |
| `comfyui_update_custom_node` | Queue update for a custom node pack by `node_id`; optional restart and post-update security audit. |
| `comfyui_get_custom_node_status` | Get custom node queue status (pending/running/completed). |

> **Requires:** ComfyUI-Manager available on the target ComfyUI server. If unavailable, node-management tools return a helpful error.

### History

| Tool | Description |
|------|-------------|
| `comfyui_get_history` | Browse execution history (read-only). Server-side paging via `limit` (1-100, default 25) and `offset` (no upper bound). Returns `{items, count, offset, limit, has_more, total}`; `total` is only set on the last page (the upstream endpoint does not expose a count). |

### Model Search & Download

| Tool | Description |
|------|-------------|
| `comfyui_search_models` | Search HuggingFace or CivitAI for models. Returns name, download URL, size, and stats. |
| `comfyui_download_model` | Download a model via [ComfyUI-Model-Manager](https://github.com/hayden-fr/ComfyUI-Model-Manager). URL and extension validated. |
| `comfyui_get_download_tasks` | Check status of active model downloads (progress, speed, status). |
| `comfyui_cancel_download` | Cancel or clean up a model download task. |
| `comfyui_get_model_presets` | Return recommended sampler/scheduler/steps/CFG defaults for a model family. |
| `comfyui_get_prompting_guide` | Return model-family prompt engineering tips and negative prompt guidance. |

> **Requires:** [ComfyUI-Model-Manager](https://github.com/hayden-fr/ComfyUI-Model-Manager) installed in your ComfyUI instance. Download tools are gated behind lazy detection — if Model Manager is not installed, these tools return a helpful error message. `comfyui_search_models` works without it.

#### Model Manager download lifecycle

Model Manager tracks downloads as tasks. After a download completes, the task remains in the list with `status: "pause"` and `progress: 100` — this is upstream Model Manager behavior. Call `comfyui_cancel_download` to remove it:

```
comfyui_download_model(url="...", folder="checkpoints", filename="model.safetensors")
→ { "taskId": "abc123", ... }

comfyui_get_download_tasks()
→ { "tasks": [{ "taskId": "abc123", "status": "pause", "progress": 100, ... }] }

comfyui_cancel_download(task_id="abc123")
→ { "success": true, ... }
```

The `comfyui_download_model` tool always sends a `previewFile` field (required by Model Manager even when empty). Omitting it causes the server to silently fail and delete the task.

### File Operations

| Tool | Description |
|------|-------------|
| `comfyui_upload_image` | Upload a base64-encoded image to ComfyUI. Path-sanitized. Params: filename, image_data, subfolder, `destination="input"\|"output"\|"temp"` (default `input`), `overwrite` (default False — ComfyUI auto-renames duplicates). |
| `comfyui_get_image` | Download a generated image. `response_format="data_uri"` (default) returns inline base64; `response_format="url"` returns a direct `/view` URL. With `data_uri`, optional `preview_format="webp"\|"jpeg"` + `preview_quality=1-100` request a server-rendered thumbnail (smaller payload, lossy). Optional `base_url_override` can override URL host per call. Path-sanitized. |
| `comfyui_list_outputs` | List generated output filenames from history. |
| `comfyui_upload_mask` | Upload a mask image to ComfyUI. Path-sanitized. Params: filename, mask_data, original_image, subfolder, original_subfolder, `destination="input"\|"output"\|"temp"` (default `input`), `overwrite` (default False — ComfyUI auto-renames duplicates). |
| `comfyui_get_workflow_from_image` | Extract embedded workflow and prompt metadata from a ComfyUI-generated PNG. |

### Resources

Read-only state the LLM can browse by URI without a tool call. Templated
resources inherit FastMCP 4's built-in path-traversal screening.

| URI | Description |
|-----|-------------|
| `comfyui://models/{folder}` | List models in a folder (checkpoints, loras, vae, etc.). Path-traversal in `{folder}` is screened. |
| `comfyui://nodes/installed` | Sorted list of all available ComfyUI node class types from `/object_info`. |
| `comfyui://queue` | Current queue state — running and pending job counts. |
| `comfyui://system` | Whitelisted system info: ComfyUI version, GPU VRAM, queue counts. Sensitive fields (hostname, OS, CPU, paths) excluded. |
| `comfyui://settings` | ComfyUI server settings (sampler defaults, UI prefs, feature flags) from `GET /settings`. |

### Prompts

Reusable, parameterized prompt recipes for the built-in workflow templates.
Return a plain string the LLM can use as guidance.

| Prompt | Description |
|--------|-------------|
| `txt2img_prompt` | Text-to-image recipe. Params: `prompt`, `style="photorealistic"`. |
| `img2img_prompt` | Image-to-image recipe. Params: `image`, `prompt`, `style="photorealistic"`. |
| `inpaint_prompt` | Inpaint recipe. Params: `image`, `mask`, `prompt`, `style="photorealistic"`. |
| `upscale_prompt` | Upscale recipe. Params: `image`, `upscale_model="RealESRGAN_x4plus.pth"`. |

### Deliberately not exposed

These ComfyUI endpoints are **never** proxied due to security risks:

- `/userdata` — arbitrary file read/write
- `/free` — unload models (DoS vector)
- `/users` — user management
- `/history` POST — delete history

`/system_stats` is called internally **only** by `comfyui_get_system_info`, which applies a strict whitelist and never forwards the raw response.

## Configuration

Config file: `~/.comfyui-mcp/config.yaml`

```yaml
comfyui:
  url: "http://127.0.0.1:8188"   # ComfyUI server URL
  external_url: null               # Optional public URL for get_image URL responses
                                   # If unset, URL responses use comfyui.url
  tls_verify: true                 # TLS certificate verification
  timeout_connect: 30              # Connection timeout (seconds)
  timeout_read: 300                # Read timeout (seconds)

security:
  mode: "audit"                    # "audit" (log only) or "enforce" (block unapproved)
  allowed_nodes: []                # Enforce mode: only these nodes can run
  dangerous_nodes:                 # Always flagged in audit log (showing subset)
    - "Terminal"                   # comfyui-colab: shell via subprocess
    - "interpreter_tool"           # comfyui_LLM_party: exec/eval
    - "KY_Eval_Python"             # ComfyUI-KYNode: exec Python
    - "Image Send HTTP"            # was-node-suite: arbitrary HTTP
    - "Load Text File"             # was-node-suite: reads arbitrary files
    - "Save Text File"             # was-node-suite: writes arbitrary files
    # ... see config.py _DEFAULT_DANGEROUS_NODES for the full list
  max_upload_size_mb: 50
  allowed_extensions:
    - ".png"
    - ".jpg"
    - ".jpeg"
    - ".webp"
    - ".gif"
    - ".json"

rate_limits:                       # Requests per minute
  workflow: 10
  generation: 10
  file_ops: 30
  read_only: 60

model_search:
  huggingface_token: ""            # Optional; needed for gated/private HF models
  civitai_api_key: ""              # Optional; needed for auth-only CivitAI access
  max_search_results: 10

logging:
  audit_file: "~/.comfyui-mcp/audit.log"

transport:
  remote:
    enabled: false
    host: "127.0.0.1"
    port: 8080
```

When `transport.remote.enabled` is `true`, the server starts in Streamable HTTP mode and binds to `transport.remote.host` and `transport.remote.port`.
Keep this bound to localhost unless you are running behind authenticated TLS reverse proxy infrastructure.

### Environment variables

Environment variables override config file values:

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
| `COMFYUI_TASKS_ENABLED` | `tasks.enabled` (optional background tasks) |
| `COMFYUI_TASKS_BACKEND_URL` | `tasks.backend_url` (`memory://` or `redis://...`) |

### HuggingFace and CivitAI API keys

`comfyui_search_models` and `comfyui_download_model` work without API keys for many public models. Add keys when you need access to gated/private resources or higher provider limits.

Set them in config:

```yaml
model_search:
  huggingface_token: "hf_xxx"
  civitai_api_key: "xxx"
```

Or via environment variables:

```bash
export COMFYUI_HUGGINGFACE_TOKEN="hf_xxx"
export COMFYUI_CIVITAI_API_KEY="xxx"
```

Security notes:
- Prefer environment variables in production so secrets do not live in files committed to git.
- Audit logs redact sensitive fields (`token`, `api_key`, etc.), but avoid printing secrets in shell history when possible.

## Security modes

### Audit mode (default)

Every workflow is inspected and logged, but nothing is blocked. Use this during development to understand what nodes your workflows use.

```yaml
security:
  mode: "audit"
```

Audit log entries look like:

```json
{
  "timestamp": "2026-02-25T14:30:00+00:00",
  "tool": "run_workflow",
  "action": "inspected",
  "nodes_used": ["KSampler", "CLIPTextEncode", "VAEDecode", "SaveImage"],
  "warnings": []
}
```

When a dangerous node is detected, warnings are included in the tool response:

```
Workflow submitted. prompt_id: abc123

⚠️ Warnings detected:
  - Dangerous node type: ExecutePython
  - Suspicious input in node 5 (ExecutePython), field 'code'
```

The MCP instructions tell the LLM to inform users and ask for confirmation before proceeding when warnings are present.

### Building your dangerous node list

Use the `comfyui_audit_dangerous_nodes` tool to scan your ComfyUI installation for potentially dangerous nodes:

| Tool | Description |
|------|-------------|
| `comfyui_audit_dangerous_nodes` | Scans all installed nodes and returns dangerous/suspicious ones with reasons |

Run this once to see what dangerous nodes are installed:

```
comfyui_audit_dangerous_nodes() → {
  "total_nodes": 456,
  "dangerous": {
    "count": 12,
    "nodes": [
      {"class": "ExecutePython", "reason": "Name matches pattern: \\bexec\\b"},
      {"class": "RunPython", "reason": "Name matches pattern: \\brunpython\\b"},
      {"class": "ShellCommand", "reason": "Name matches pattern: \\bshell\\b"}
    ]
  },
  "suspicious": {...}
}
```

Add these to your config:

```yaml
security:
  mode: "audit"
  dangerous_nodes:
    - "ExecutePython"      # from audit_dangerous_nodes
    - "RunPython"
    - "ShellCommand"
    # ... other nodes found by audit
```

### Enforce mode

Only explicitly approved nodes can run. Any workflow containing an unapproved node is rejected.

```yaml
security:
  mode: "enforce"
  allowed_nodes:
    - "KSampler"
    - "CheckpointLoaderSimple"
    - "CLIPTextEncode"
    - "VAEDecode"
    - "EmptyLatentImage"
    - "SaveImage"
    - "LoadImage"
    - "LoraLoader"
```

**Tip:** Use `comfyui_audit_dangerous_nodes` to identify dangerous nodes, run workflows in audit mode to see which nodes you use, then switch to enforce mode with that allowlist.

**Elicitation gate (Phase 5):** when enforce mode is on and the inspector produces warnings (dangerous-node types, suspicious inputs like `eval()`/`exec()`, or missing models), the generation tools (`comfyui_run_workflow`, `comfyui_generate_image`, `comfyui_transform_image`, `comfyui_inpaint_image`, `comfyui_upscale_image`) ask the user to confirm before submitting — `ctx.elicit(..., response_type=bool)`. A decline or cancel raises `WorkflowBlockedError` without calling `post_prompt`. Unapproved-node enforcement (the `allowed_nodes` allowlist) still blocks hard inside the inspector before elicitation; the gate fires on the warning path. Programmatic callers without a live MCP context keep the pre-existing behavior (immediate `WorkflowBlockedError` in enforce mode with warnings).

## Audit log

All tool invocations are logged as JSON lines to `~/.comfyui-mcp/audit.log`:

```bash
# Watch the audit log in real time
tail -f ~/.comfyui-mcp/audit.log | python -m json.tool

# Find all workflows that used dangerous nodes
grep '"warnings":\[' ~/.comfyui-mcp/audit.log | grep -v '"warnings":\[\]'
```

Sensitive fields (`token`, `password`, `secret`, `api_key`, `authorization`) are automatically redacted from log entries.

## Security

### Threat model

| Threat | Impact | Mitigation |
|--------|--------|------------|
| Arbitrary code execution via workflow nodes | Critical | Workflow inspector (audit/enforce mode) |
| Path traversal via file operations | High | Path sanitizer blocks `..`, null bytes, encoded attacks, absolute paths |
| Denial of service via request flooding | Medium | Token-bucket rate limiter per tool category |
| Credential leakage in logs | Medium | Automatic redaction of `token`, `password`, `secret`, `api_key`, `authorization` |
| Information disclosure via API | Low | Dangerous endpoints (`/userdata`, `/free`) never proxied; `/system_stats` whitelist-filtered by `comfyui_get_system_info` |
| MITM on ComfyUI connection | Medium | Configurable TLS verification |

### Security controls by component

**Workflow Inspector** (`security/inspector.py`)
- Parses workflow JSON, extracts node types, checks against configurable blocklist
- Recursive pattern matching for `__import__()`, `eval()`, `exec()`, `os.system()`, `subprocess` in all input values (including nested dicts/lists)
- Audit mode: logs warnings, allows execution. Enforce mode: blocks unapproved nodes
- Limitation: static blocklist can be bypassed with obfuscation or unknown custom nodes

**Path Sanitizer** (`security/sanitizer.py`)
- Validates filenames, subfolders, and URL path segments: blocks path traversal, null bytes, absolute paths, control characters
- URL path segment validation on discovery tools (`comfyui_list_models`, `comfyui_get_model_metadata`) prevents folder/filename injection
- Allowlist-based extension filtering (default: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.json`)
- Handles percent-encoded inputs (URL decoding before validation)
- Enforces max upload size (default 50MB), max filename length (255 chars)

**Rate Limiter** (`security/rate_limit.py`) + **SecurityMiddleware** (`middleware.py`)
- Token-bucket per tool category: workflow (10/min), generation (10/min), file_ops (30/min), read_only (60/min)
- In-memory only (resets on restart, no distributed support)
- `SecurityMiddleware` centralizes rate-limit checks + entry audit logging across every tool call (FastMCP 4 `on_call_tool` hook), so the per-tool `limiter.check()` / `audit.async_log(action="called")` boilerplate can be dropped. Tools keep their domain-specific lifecycle audit logs (`submitted`, `completed`, etc.)
- Sensitive tool arguments (`token`, `password`, `api_key`, ...) are redacted by the middleware before the entry audit record is written
- `mask_error_details=True` on the server constructor masks internal exception tracebacks from clients — only `ToolError` messages (which we control) include details
- Built-in FastMCP 4 middleware wired alongside `SecurityMiddleware` (see `build_middleware_stack()`): `ResponseCachingMiddleware` (caches read-only tools + the 4 `comfyui://` resources, 30s TTL), `ResponseLimitingMiddleware` (caps `list_nodes`/`list_models`/`get_history` payloads at 500KB), `PingMiddleware` (keeps long-lived HTTP connections alive), `StructuredLoggingMiddleware` (ops/observability, `include_payloads=False` — the AuditLogger already redacts).

**HTTP Client** (`client.py`)
- Configurable TLS verification, connect/read timeouts
- Retries on connection errors with backoff (3 retries default). HTTP 4xx/5xx errors raised immediately (no retry)

**WebSocket Progress** (`progress.py`)
- On-demand WebSocket connections for real-time execution tracking (step progress, current node, outputs)
- Automatic HTTP polling fallback if WebSocket connection fails
- TLS/SSL passthrough for secure ComfyUI connections
- Per-prompt event filtering (ignores events from other concurrent jobs)

**Configuration** (`config.py`)
- `yaml.safe_load` only, env var overrides limited to specific keys, Pydantic type validation

### Production deployment

For production, run behind a reverse proxy (nginx, Traefik) to add TLS termination, authentication, and CSP headers. No PII is collected. No external telemetry.

### Background tasks (optional, Phase 6)

Long-running workflows (`comfyui_run_workflow(wait=True)`, image generation) can run as background tasks instead of holding the MCP request open. Disabled by default — most useful for the HTTP/remote transport where a long generation can return a task handle immediately and the client polls for progress.

```yaml
tasks:
  enabled: true
  backend_url: "memory://"   # in-memory (default, single-process)
  # backend_url: "redis://localhost:6379/0"  # persistent, horizontally scalable
```

Env overrides: `COMFYUI_TASKS_ENABLED`, `COMFYUI_TASKS_BACKEND_URL`. When enabled, the server registers `TasksExtension` (backed by [Docket](https://github.com/chrisguidry/docket)) and async tools become task-capable — a client that opts in to the tasks capability gets a handle and polls; a client that does not gets synchronous execution as before. Use the Redis backend for deployments where tasks must survive restarts or run across workers. `ctx.elicit()` is not supported inside a background task — use the guard pattern (`InputRequiredResult`) for mid-task user input when serving 2026-07-28 connections.

## Architecture

```mermaid
flowchart TB
    subgraph Client["LLM Client"]
        MC[AI Assistant / MCP Client]
    end

    subgraph MCP["ComfyUI MCP Server (FastMCP 4)"]
        CONFIG[Config<br/>YAML/env]
        AL[Audit Logger<br/>JSON logs]

        subgraph Security["Security Layers"]
            WI[Workflow Inspector<br/>Dangerous nodes<br/>Suspicious input<br/>+ Elicitation gate]
            PS[Path Sanitizer<br/>Traversal block<br/>Extension filter]
            RL[Rate Limiter<br/>Token-bucket]
        end

        MW[SecurityMiddleware<br/>rate limit + entry audit<br/>on_call_tool hook]
        DI[Dependencies<br/>Depends() providers]

        subgraph Tools["Tool Groups"]
            TG[generation.py<br/>jobs.py<br/>discovery.py<br/>history_di.py<br/>files.py]
        end

        RES[Resources<br/>comfyui://models, nodes, queue, system]
        PR[Prompts<br/>txt2img, img2img, inpaint, upscale]
        TASKS[TasksExtension<br/>optional, Docket-backed]

        API[ComfyUI Client<br/>httpx]
        WS[WebSocket Progress<br/>websockets]
    end

    subgraph ComfyUI["ComfyUI Server"]
        CS[REST API<br/>port 8188]
        CWS[WebSocket<br/>/ws]
    end

    MC <--MCP--> MCP
    CONFIG --> MCP
    AL --> MCP

    MCP --> MW
    MW --> Security
    MW --> Tools
    DI --> Tools
    Security --> Tools
    Tools --> API
    Tools --> WS
    API --httpx--> CS
    WS --websockets--> CWS
```

### Components

| Component | File | Responsibility |
|-----------|------|----------------|
| Server | `server.py` | Entry point, wires components, registers tools/resources/prompts/middleware |
| Config | `config.py` | Pydantic settings, YAML loading, env overrides (incl. `tasks.*`) |
| Client | `client.py` | Async HTTP client for ComfyUI REST API |
| SecurityMiddleware | `middleware.py` | Centralized rate-limit + entry-audit via FastMCP 4 `on_call_tool` hook |
| Dependencies | `dependencies.py` | `Depends()` providers for client/audit/inspector/limiter singletons |
| Resources | `resources.py` | `@mcp.resource` URIs — models, nodes, queue, system (read-only browsing) |
| Prompts | `prompts.py` | `@mcp.prompt` workflow-template recipes (txt2img, img2img, inpaint, upscale) |
| Progress | `progress.py` | WebSocket progress tracking with HTTP polling fallback |
| Audit | `audit.py` | Structured JSON logging with redaction |
| Workflow Inspector | `security/inspector.py` | Node type detection, dangerous pattern matching, elicitation gate |
| Node Auditor | `security/node_auditor.py` | Scans installed nodes for dangerous patterns |
| Path Sanitizer | `security/sanitizer.py` | Path traversal, extension filtering |
| Rate Limiter | `security/rate_limit.py` | Token-bucket per tool category (enforced by `SecurityMiddleware`) |
| Download Validator | `security/download_validator.py` | URL domain/path and extension validation for downloads |
| Model Checker | `security/model_checker.py` | Proactive missing model detection in workflows |
| Model Manager | `model_manager.py` | Lazy detection of ComfyUI-Model-Manager availability |

## Development

### Project structure

```text
src/comfyui_mcp/
├── server.py              # MCP server entry point, wires all components + middleware
├── config.py              # Pydantic settings, YAML loading, env overrides
├── client.py              # Async HTTP client for ComfyUI API
├── middleware.py          # SecurityMiddleware (rate limit + entry audit, on_call_tool)
├── dependencies.py        # Depends() providers (client/audit/inspector/limiter singletons)
├── resources.py           # @mcp.resource URIs (models, nodes, queue, system)
├── prompts.py             # @mcp.prompt workflow-template recipes
├── progress.py            # WebSocket progress tracking with HTTP polling fallback
├── pagination.py          # Offset-based pagination helper for list tools
├── audit.py               # Structured JSON audit logger
├── model_manager.py       # Lazy Model Manager detection and validation
├── security/
│   ├── inspector.py       # Workflow node inspection (audit/enforce)
│   ├── node_auditor.py    # Scans installed nodes for dangerous patterns
│   ├── sanitizer.py       # File path validation
│   ├── rate_limit.py      # Token-bucket rate limiter
│   ├── download_validator.py  # URL/extension validation for model downloads
│   └── model_checker.py   # Proactive model availability checking
├── workflow/
│   ├── templates.py       # Built-in workflow templates (txt2img, img2img, upscale, etc.)
│   ├── operations.py      # Workflow graph operations (add/remove nodes, connect, etc.)
│   └── validation.py      # Workflow analysis and validation
└── tools/
    ├── generation.py      # generate_image, run_workflow, summarize_workflow (elicitation-gated)
    ├── workflow.py        # create_workflow, modify_workflow, validate_workflow, analyze_workflow
    ├── jobs.py            # get_queue, get_job, cancel_job, interrupt, get_progress
    ├── discovery.py       # list_models, list_nodes, audit_dangerous_nodes, etc.
    ├── history_di.py      # get_history (DI version — Depends())
    ├── files.py           # upload_image, get_image, list_outputs, upload_mask, get_workflow_from_image
    ├── models.py          # search_models, download_model, get_download_tasks, cancel_download
    └── nodes.py           # search/install/uninstall/update custom nodes

scripts/
├── smoke_test.py             # Operator smoke-test against a live ComfyUI instance
├── compare_evals.py          # Diff two Inspect AI eval runs (PASS/FAIL + per-tag breakdown)
└── run_multimodel_eval.py    # Run one Task against N models in a single invocation

evals/
├── comfyui_mcp_task.py                       # Inspect AI Task definitions (Phase 4, Phase 5)
├── 2026-05-11-comfyui-mcp-v1.jsonl           # Phase 4 dataset (10 static questions, tagged)
└── 2026-05-12-comfyui-mcp-phase5.jsonl       # Phase 5 dataset (5 live-execution questions, tagged)
```

### Run tests

```bash
uv sync
uv run pytest -v
```

### Evaluation

The MCP ships with an [Inspect AI](https://inspect.aisi.org.uk/)-based eval
harness for measuring how well an LLM uses the tools end-to-end. Two task
suites are defined:

- **Phase 4** — 10 static questions exercising templates, presets, the
  prompting guide, and the workflow validator/summarizer. ~1-6 min per run
  for cloud-tier models.
- **Phase 5** — 5 live-execution questions exercising multi-step tool
  chains, state passing, recovery from intentionally broken workflows, and
  reading structured outputs. Generation questions actually submit work to
  the connected ComfyUI server (so you need one reachable at
  `$COMFYUI_URL`).

Every question is tagged with what it tests (e.g. `template`, `recovery`,
`state-passing`, `output-reading`) so results can be sliced per category.

Run a single model against one suite:

```bash
COMFYUI_URL=https://comfyui.example.net uv run inspect eval \
    evals/comfyui_mcp_task.py@comfyui_mcp_phase5 \
    --model ollama/gpt-oss:120b-cloud \
    --log-dir ./logs/phase5
uv run inspect view --log-dir ./logs/phase5
```

Run one suite against N models in a single invocation (wraps the
`eval_set()` Python API because the CLI's `--model` flag is single-value
by Click's default):

```bash
uv run python scripts/run_multimodel_eval.py \
    evals/comfyui_mcp_task.py@comfyui_mcp_phase4 \
    --models ollama/gpt-oss:120b-cloud,ollama/qwen3-coder:480b-cloud,anthropic/claude-sonnet-4-6 \
    --log-dir ./logs/phase4-cross-model
```

Compare two runs (per-sample PASS/FAIL diff plus a per-tag breakdown when
either log has tagged samples):

```bash
uv run python scripts/compare_evals.py logs/phase4-before logs/phase4-after
```

Each path can be either a specific `.eval` file or a directory (uses the
most recent `.eval` by mtime).

### Build and publish

Build the distributable artifacts locally:

```bash
uv build
uvx twine check dist/*
```

Publish a release to PyPI:

```bash
# After bumping pyproject.toml [project].version and updating CHANGELOG.md
git tag v2.1.0
git push origin v2.1.0
```

The GitHub Actions workflow in `.github/workflows/pypi.yml` builds the sdist and wheel, verifies the metadata, and publishes to PyPI using GitHub Trusted Publishing on tag push. The GitHub Release is created manually after the workflow succeeds (`gh release create v<x.y.z>`). Before the first release, create the `comfyui-mcp-secure` project on PyPI, configure a trusted publisher for this repository in the PyPI project settings, and use the `pypi` GitHub environment.

### Smoke test against a live instance

Verify connectivity, Model Manager availability, and download lifecycle against a running ComfyUI server:

```bash
# Full test (connectivity + folder listing + download task lifecycle)
uv run python scripts/smoke_test.py

# Quick connectivity + folder check only
uv run python scripts/smoke_test.py --no-download

# Target a different server
uv run python scripts/smoke_test.py --url http://localhost:8188
```

The download probe uses a tiny (~520 KB) safetensors file from `hf-internal-testing/tiny-random-bert`. The file is created with a timestamped name and cleaned up automatically on every run.

## Docker

A pre-built Docker image is published to the GitHub Container Registry. No need to clone the repo.

```bash
docker pull ghcr.io/hybridindie/comfyui_mcp:latest
```

### How it works

The container runs as a non-root `app` user with `uv run comfyui-mcp-secure` as its entrypoint, communicating over stdin/stdout (stdio). This makes it compatible with OpenCode, Claude Desktop, Cursor, and any MCP client. Config is read from `/home/app/.comfyui-mcp/config.yaml` inside the container — mount your local config directory to provide it, or use environment variables.

### Running standalone

```bash
# Using the hosted image
docker run --rm -i \
  -e COMFYUI_URL=http://host.docker.internal:8188 \
  -v ~/.comfyui-mcp:/home/app/.comfyui-mcp:ro \
  ghcr.io/hybridindie/comfyui_mcp:latest

# Or build and run locally
docker build -t comfyui-mcp-secure .
docker run --rm -i \
  -e COMFYUI_URL=http://host.docker.internal:8188 \
  -v ~/.comfyui-mcp:/home/app/.comfyui-mcp:ro \
  comfyui-mcp-secure
```

> **Linux users:** Add `--add-host=host.docker.internal:host-gateway` if using `host.docker.internal`.

### Docker Compose

A `docker-compose.yml` is included for persistent deployments:

```bash
# Start
COMFYUI_URL=http://your-comfyui:8188 docker compose up -d

# View logs
docker compose logs -f comfyui-mcp-secure
```

The compose file mounts `./config.yaml` and persists audit logs to a named volume:

```yaml
services:
  comfyui-mcp-secure:
    build: .
    image: comfyui-mcp-secure:latest
    container_name: comfyui-mcp-secure
    environment:
      - COMFYUI_URL=${COMFYUI_URL:-http://comfyui:8188}
      - COMFYUI_SECURITY_MODE=${COMFYUI_SECURITY_MODE:-audit}
    volumes:
      - ./config.yaml:/home/app/.comfyui-mcp/config.yaml:ro
      - comfyui-mcp-secure-data:/home/app/.comfyui-mcp/logs
    restart: unless-stopped

volumes:
  comfyui-mcp-secure-data:
```

### Connecting via Docker

See the [Docker configuration](#add-to-your-mcp-client) in Quick Start above. The key points:

- Use `docker run --rm -i` (interactive, no detach) so stdio works
- Mount your config: `-v ~/.comfyui-mcp:/home/app/.comfyui-mcp:ro`
- Set `COMFYUI_URL` to reach your ComfyUI instance from inside the container
- Use `host.docker.internal` to reach ComfyUI running on your host machine
- The GHCR image (`ghcr.io/hybridindie/comfyui_mcp:latest`) means no local build needed

## License

MIT
