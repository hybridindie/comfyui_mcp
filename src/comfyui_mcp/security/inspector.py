"""Workflow inspection for detecting dangerous node types and suspicious inputs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_SUSPICIOUS_PATTERNS = [
    re.compile(r"__import__\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\bos\.system\s*\("),
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bopen\s*\(.+,\s*['\"]w"),
    re.compile(r"\bimportlib\b"),
    re.compile(r"\bpickle\.loads?\b"),
    re.compile(r"\bos\.(popen|execv|spawn)"),
    re.compile(r"\bctypes\b"),
]

# Keys that may hold a nested node map inside a subgraph node's inputs.
_SUBGRAPH_KEYS = ("subgraph", "nodes", "graph")


class WorkflowBlockedError(Exception):
    """Raised when a workflow is blocked in enforce mode."""


@dataclass
class InspectionResult:
    nodes_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_subgraph_class(class_type: str) -> bool:
    """True if the class_type looks like a subgraph wrapper node."""
    return "subgraph" in class_type.lower()


def _extract_subgraph_nodes(value: Any) -> dict[str, Any] | None:
    """Extract a nested node map from a value, if it looks like one.

    A node map is a dict whose values are dicts containing a ``class_type`` key.
    """
    if not isinstance(value, dict):
        return None
    if not value:
        return None
    for v in value.values():
        if isinstance(v, dict) and "class_type" in v:
            return value
    return None


def _find_subgraph_node_map(node_data: dict) -> dict[str, Any] | None:
    """Find a nested node map inside a subgraph node's inputs.

    Checks common keys (``subgraph``, ``nodes``, ``graph``) and falls back to
    scanning all input values for anything that looks like a node map.
    """
    inputs = node_data.get("inputs", {})
    if not isinstance(inputs, dict):
        return None
    for key in _SUBGRAPH_KEYS:
        nodes = _extract_subgraph_nodes(inputs.get(key))
        if nodes is not None:
            return nodes
    for value in inputs.values():
        nodes = _extract_subgraph_nodes(value)
        if nodes is not None:
            return nodes
    return None


def _check_value_for_suspicious(value: Any, node_id: str, class_type: str, key: str) -> list[str]:
    """Recursively check a value for suspicious patterns."""
    warnings = []
    if isinstance(value, str):
        for pattern in _SUSPICIOUS_PATTERNS:
            if pattern.search(value):
                warnings.append(f"Suspicious input in node {node_id} ({class_type}), field '{key}'")
                break
    elif isinstance(value, dict):
        for k, v in value.items():
            warnings.extend(_check_value_for_suspicious(v, node_id, class_type, f"{key}.{k}"))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            warnings.extend(_check_value_for_suspicious(v, node_id, class_type, f"{key}[{i}]"))
    return warnings


class WorkflowInspector:
    def __init__(
        self,
        mode: str = "audit",
        dangerous_nodes: list[str] | None = None,
        allowed_nodes: list[str] | None = None,
    ) -> None:
        self._mode = mode
        self._dangerous_nodes = set(dangerous_nodes or [])
        self._allowed_nodes = set(allowed_nodes or [])

    @property
    def mode(self) -> str:
        """Return the current inspection mode ('audit' or 'enforce')."""
        return self._mode

    def inspect(self, workflow: dict, _depth: int = 0) -> InspectionResult:
        """Inspect a ComfyUI workflow and return findings.

        Recurses into subgraph nodes (class_type containing ``subgraph``) when
        the nested node map is embedded inline. If a subgraph reference has no
        inline node map, a warning is emitted so callers know inspection is
        incomplete.
        """
        nodes_used: list[str] = []
        warnings: list[str] = []

        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue
            class_type = node_data.get("class_type", "")
            if class_type:
                nodes_used.append(class_type)

            for key, value in node_data.get("inputs", {}).items():
                warnings.extend(_check_value_for_suspicious(value, node_id, class_type, key))

            # Subgraph recursion (#110): if this node is a subgraph wrapper,
            # recurse into its embedded node map (if present).
            if class_type and _is_subgraph_class(class_type):
                sub_nodes = _find_subgraph_node_map(node_data)
                if sub_nodes is not None:
                    sub_result = self.inspect(sub_nodes, _depth=_depth + 1)
                    nodes_used.extend(sub_result.nodes_used)
                    warnings.extend(sub_result.warnings)
                else:
                    warnings.append(
                        f"Node {node_id} ({class_type}) contains unexpanded subgraph "
                        f"— cannot fully inspect"
                    )

        # Check for dangerous nodes
        for node_type in nodes_used:
            if node_type in self._dangerous_nodes:
                warnings.append(f"Dangerous node type: {node_type}")

        # Enforce mode: block unapproved nodes
        if self._mode == "enforce" and self._allowed_nodes:
            unapproved = [n for n in nodes_used if n not in self._allowed_nodes]
            if unapproved:
                raise WorkflowBlockedError(
                    f"Workflow blocked — unapproved node types: {unapproved}"
                )

        return InspectionResult(
            nodes_used=nodes_used,
            warnings=warnings,
        )
