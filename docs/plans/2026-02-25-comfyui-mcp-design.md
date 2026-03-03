# ComfyUI MCP Server — Secure Design

## Context

Existing ComfyUI MCP servers are thin wrappers that pass everything to ComfyUI's API with no security guardrails: arbitrary workflow execution, file system access via path traversal, no input validation, no authentication, no rate limiting. This project builds a security-aware MCP server from scratch.

## Requirements

- **Use case**: Development/prototyping with AI assistance
- **Capabilities**: Image generation, arbitrary workflow execution, queue/job management, model/node discovery, history browsing, file upload/download
- **Security priority**: Prevent code execution via malicious nodes
- **Validation model**: Audit-only by default, with configurable enforcement mode
- **Deployment**: MCP server runs locally, ComfyUI on a remote GPU server
- **Transports**: stdio (primary for Claude Code) + optional SSE for web clients
- **Real-time updates**: WebSocket connection to ComfyUI for progress streaming

## Architecture

```
LLM Client  <--MCP (stdio/SSE)-->  ComfyUI MCP Server  <--HTTPS/WSS-->  ComfyUI (Remote)
                                    ├── Audit Logger
                                    ├── Workflow Inspector
                                    ├── Path Sanitizer
                                    ├── Rate Limiter
                                    └── ComfyUI Client (HTTP + WebSocket)
```

**Tech stack**: Python 3.12, `mcp` SDK (FastMCP), `httpx` (async HTTP), `websockets` (WS client), `pydantic` (config/validation), `structlog` (structured logging), `pyyaml` (config)

## MCP Tools

### Generation & Workflows

| Tool | Description | Risk |
|------|-------------|------|
| `generate_image` | Text-to-image using default workflow with configurable params (prompt, dimensions, model, steps, cfg) | Medium |
| `run_workflow` | Submit arbitrary workflow JSON with optional parameter overrides | High |

### Job Management

| Tool | Description | Risk |
|------|-------------|------|
| `get_queue` | Get current queue state | Low |
| `get_job` | Check status of a specific job by prompt_id | Low |
| `cancel_job` | Cancel a running/queued job | Medium |
| `interrupt` | Interrupt current execution | Medium |

### Discovery

| Tool | Description | Risk |
|------|-------------|------|
| `list_models` | List available models by type (checkpoints, loras, etc.) | Low |
| `list_nodes` | List available node types | Low |
| `get_node_info` | Get detailed info about a specific node type | Low |
| `list_workflows` | List saved workflow templates | Low |

### History

| Tool | Description | Risk |
|------|-------------|------|
| `get_history` | Browse execution history (read-only) | Low |
| `get_history_item` | Get details of a specific history entry | Low |

### File Operations

| Tool | Description | Risk |
|------|-------------|------|
| `upload_image` | Upload an image to ComfyUI's input directory | Medium |
| `get_image` | Download a generated image by filename | Medium |
| `list_outputs` | List files in ComfyUI's output directory | Low |

### Deliberately NOT Exposed

- `/userdata` endpoints (arbitrary file read/write)
- `/free` (unload models — DoS vector)
- `/users` (user management)
- `/history` POST (delete history)
- `/system_stats` (unnecessary info disclosure)

## Security Layers

### 1. Workflow Inspector

Every workflow submitted through `run_workflow` is parsed before forwarding:

- Extract all node types used in the workflow
- Check against `dangerous_nodes` list — flag in audit log
- In `enforce` mode: block workflows with unapproved node types
- In `audit` mode (default): log warnings but allow through
- Scan node inputs for suspicious patterns (code-like strings)

### 2. Path Sanitization

All file operations pass through a path sanitizer:

- Resolve to absolute path, verify under allowed base directory
- Block `..` traversal, symlink following, null bytes
- Validate file extensions against allowlist (`.png`, `.jpg`, `.jpeg`, `.webp`, `.json`)
- Enforce configurable max file size (default 50MB)

### 3. Transport Security (MCP to ComfyUI)

- Bearer token auth on every request to ComfyUI
- HTTPS with TLS verification (configurable for self-signed certs)
- Configurable timeouts (30s connect, 300s read)
- Auth tokens never appear in logs

### 4. Rate Limiting

Token-bucket rate limiter per tool category:

- Workflow/generation: 10 req/min
- File operations: 30 req/min
- Read-only: 60 req/min

### 5. Structured Audit Log

Every tool invocation produces a JSON log entry:

```json
{
  "timestamp": "2026-02-25T14:30:00Z",
  "tool": "run_workflow",
  "action": "workflow_submitted",
  "prompt_id": "abc-123",
  "nodes_used": ["KSampler", "CLIPTextEncode", "VAEDecode", "SaveImage"],
  "warnings": [],
  "duration_ms": 45,
  "status": "accepted"
}
```

Logs to file (`~/.comfyui-mcp/audit.log`) and stderr.

## Configuration

Single YAML file at `~/.comfyui-mcp/config.yaml` with env var overrides:

```yaml
comfyui:
  url: "https://my-gpu-server:8188"
  token: "${COMFYUI_API_TOKEN}"
  tls_verify: true
  timeout_connect: 30
  timeout_read: 300

security:
  mode: "audit"  # "audit" or "enforce"
  allowed_nodes: []  # enforce mode only; empty = block all
  dangerous_nodes:
    - "ExecuteAnything"
    - "EvalNode"
  max_upload_size_mb: 50
  allowed_extensions: [".png", ".jpg", ".jpeg", ".webp", ".json"]

rate_limits:
  workflow: 10
  generation: 10
  file_ops: 30
  read_only: 60

logging:
  level: "INFO"
  audit_file: "~/.comfyui-mcp/audit.log"

transport:
  stdio: true
  sse:
    enabled: false
    host: "127.0.0.1"
    port: 8080
```

Env var overrides: `COMFYUI_URL`, `COMFYUI_TOKEN`, `COMFYUI_SECURITY_MODE`, etc.

## Project Structure

```
comfyui_mcp/
├── src/
│   └── comfyui_mcp/
│       ├── __init__.py
│       ├── server.py          # MCP server setup, tool registration
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── generation.py  # generate_image, run_workflow
│       │   ├── jobs.py        # get_queue, get_job, cancel_job, interrupt
│       │   ├── discovery.py   # list_models, list_nodes, get_node_info, list_workflows
│       │   ├── history.py     # get_history, get_history_item
│       │   └── files.py       # upload_image, get_image, list_outputs
│       ├── client.py          # Async ComfyUI HTTP + WebSocket client
│       ├── security/
│       │   ├── __init__.py
│       │   ├── inspector.py   # Workflow inspector
│       │   ├── sanitizer.py   # Path sanitizer
│       │   └── rate_limit.py  # Rate limiter
│       ├── audit.py           # Structured audit logger
│       └── config.py          # Pydantic config model, YAML loading
├── tests/
├── docs/
│   └── plans/
├── pyproject.toml
└── README.md
```
