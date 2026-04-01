# Review Scope

## Target

Full review of `src/comfyui_mcp/` — a secure MCP (Model Context Protocol) server for ComfyUI built with FastMCP and Python 3.12.

## Files

### Core
- `src/comfyui_mcp/server.py` — MCP server entry, wires all components
- `src/comfyui_mcp/config.py` — Pydantic settings, YAML loading, env overrides
- `src/comfyui_mcp/client.py` — Async HTTP client for ComfyUI API
- `src/comfyui_mcp/audit.py` — Structured JSON audit logger
- `src/comfyui_mcp/model_manager.py` — Lazy Model Manager detection and folder caching
- `src/comfyui_mcp/model_registry.py` — Model registry
- `src/comfyui_mcp/node_manager.py` — Node manager
- `src/comfyui_mcp/progress.py` — WebSocket progress tracking with HTTP polling fallback
- `src/comfyui_mcp/__init__.py`

### Security
- `src/comfyui_mcp/security/inspector.py` — Workflow node inspection (audit/enforce)
- `src/comfyui_mcp/security/node_auditor.py` — Scans installed nodes for dangerous patterns
- `src/comfyui_mcp/security/sanitizer.py` — File path validation
- `src/comfyui_mcp/security/rate_limit.py` — Token-bucket rate limiter
- `src/comfyui_mcp/security/download_validator.py` — URL domain/path and extension validation
- `src/comfyui_mcp/security/model_checker.py` — Proactive model availability checking
- `src/comfyui_mcp/security/__init__.py`

### Workflow
- `src/comfyui_mcp/workflow/templates.py` — Built-in workflow templates
- `src/comfyui_mcp/workflow/operations.py` — Workflow graph operations
- `src/comfyui_mcp/workflow/validation.py` — Workflow analysis and validation
- `src/comfyui_mcp/workflow/__init__.py`

### Tools
- `src/comfyui_mcp/tools/generation.py` — generate_image, run_workflow, summarize_workflow
- `src/comfyui_mcp/tools/workflow.py` — create_workflow, modify_workflow, validate_workflow
- `src/comfyui_mcp/tools/jobs.py` — get_queue, get_job, cancel_job, interrupt, get_progress
- `src/comfyui_mcp/tools/discovery.py` — list_models, list_nodes, audit_dangerous_nodes, etc.
- `src/comfyui_mcp/tools/history.py` — get_history
- `src/comfyui_mcp/tools/files.py` — upload_image, get_image, list_outputs, upload_mask
- `src/comfyui_mcp/tools/models.py` — search_models, download_model, get_download_tasks, cancel_download
- `src/comfyui_mcp/tools/nodes.py` — Node-related tools
- `src/comfyui_mcp/tools/__init__.py`

## Flags

- Security Focus: no
- Performance Critical: no
- Strict Mode: no
- Framework: FastMCP (Python)

## Review Phases

1. Code Quality & Architecture
2. Security & Performance
3. Testing & Documentation
4. Best Practices & Standards
5. Consolidated Report
