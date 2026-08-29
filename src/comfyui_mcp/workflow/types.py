"""Shared workflow graph types used across templates, operations, and validation."""

from __future__ import annotations

from typing import Any, TypedDict

# A node input value is either a scalar (str/int/float/bool), a connection
# reference [source_node_id, output_index], or a nested dict (e.g. subgraph
# node maps embedded under the "subgraph" key).
NodeInputValue = str | int | float | bool | list[str | int] | dict[str, Any]


class WorkflowNode(TypedDict, total=False):
    """A single node in a ComfyUI workflow graph.

    ComfyUI's native API JSON format: each node is keyed by its string ID and
    contains a ``class_type`` (the node type name) and ``inputs`` (a dict of
    input name -> value, where value is either a scalar or a ``[node_id, output_index]``
    connection reference).
    """

    class_type: str
    inputs: dict[str, NodeInputValue]


# A ComfyUI workflow is a dict of node_id -> node data.
Workflow = dict[str, WorkflowNode]
