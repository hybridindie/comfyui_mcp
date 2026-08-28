"""Per-tool result TypedDicts for functions that build known-shape dicts.

These document the fixed return shapes of tools that construct their response
locally (as opposed to pass-through from the ComfyUI API, which stays
``dict[str, Any]`` because the upstream shape is not under our control).
"""

from __future__ import annotations

from typing import Any, TypedDict

# --- jobs.py ---


class CancelJobsResult(TypedDict):
    cancelled: int
    job_ids: list[str]
    result: Any


# --- models.py ---


class DownloadTasksResult(TypedDict):
    tasks: list[dict[str, Any]]


class CancelDownloadResult(TypedDict):
    success: bool
    task_id: str
    result: Any


# --- discovery.py ---


class ListModelsDetailedResult(TypedDict):
    folder: str
    models: list[dict[str, Any]]
    count: int


class ModelPreviewResult(TypedDict, total=False):
    available: bool
    folder: str
    filename: str
    mime_type: str
    size_bytes: int
    data_base64: str


# "class" is a reserved keyword in Python — use the call-form TypedDict
# so the field can be named "class" (matches the ComfyUI API key).
NodeAuditEntry = TypedDict("NodeAuditEntry", {"class": str, "reason": str})


class NodeAuditCategory(TypedDict):
    count: int
    nodes: list[NodeAuditEntry]


class NodeAuditResult(TypedDict):
    total_nodes: int
    dangerous: NodeAuditCategory
    suspicious: NodeAuditCategory


class SubgraphListResult(TypedDict):
    subgraphs: dict[str, Any]
    count: int


class SubgraphDetailResult(TypedDict, total=False):
    available: bool
    subgraph_id: str


# --- files.py ---


class WorkflowFromImageResult(TypedDict):
    workflow: dict[str, Any] | None
    prompt: dict[str, Any] | None
    message: str
