"""Workflow inspection for detecting dangerous node types and suspicious inputs."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from comfyui_mcp.model_registry import MODEL_LOADER_FIELDS

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

# Maximum subgraph nesting depth. Prevents RecursionError from a malicious or
# malformed workflow with self-referencing or deeply nested subgraphs.
_MAX_SUBGRAPH_DEPTH = 10


class WorkflowBlockedError(Exception):
    """Raised when a workflow is blocked in enforce mode."""


@dataclass(frozen=True)
class WorkflowPolicy:
    """Declarative inspection policy (issue #211).

    An empty policy is the historical behavior: warnings are logged, the
    allowlist blocks unapproved nodes in enforce mode, and the caller elicits
    on warnings.
    """

    deny_nodes: frozenset[str] = frozenset()
    warn_nodes: frozenset[str] = frozenset()
    on_warning: str = "elicit"
    max_nodes: int = 0
    allowed_model_folders: frozenset[str] = frozenset()

    @property
    def is_configured(self) -> bool:
        """True when anything differs from the historical defaults."""
        return bool(
            self.deny_nodes
            or self.warn_nodes
            or self.max_nodes
            or self.allowed_model_folders
            or self.on_warning != "elicit"
        )

    def describe(self) -> dict[str, object]:
        """A JSON-safe snapshot for the audit trail."""
        return {
            "deny_nodes": sorted(self.deny_nodes),
            "warn_nodes": sorted(self.warn_nodes),
            "on_warning": self.on_warning,
            "max_nodes": self.max_nodes,
            "allowed_model_folders": sorted(self.allowed_model_folders),
        }


@dataclass
class InspectionResult:
    nodes_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_subgraph_class(class_type: str) -> bool:
    """True if the class_type looks like a subgraph wrapper node."""
    return "subgraph" in class_type.lower()


def _extract_subgraph_nodes(value: object) -> dict[str, Any] | None:
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


def _check_value_for_suspicious(
    value: object, node_id: str, class_type: str, key: str
) -> list[str]:
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


def _remap_replacement_inputs(
    submitted: dict[str, Any], replacement: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Build the inputs the replacement node will actually receive.

    Upstream's ``input_mapping`` describes how the old node's inputs map onto
    the new node; ``set_value`` entries are constants the server injects.
    Starting from an empty dict (rather than the submitted inputs) keeps the
    scan faithful: an input the replacement does not consume is not something
    the replacement can execute.
    """
    mapping = replacement.get("input_mapping")
    if not isinstance(mapping, list) or not mapping:
        return dict(submitted), [
            "replacement has no input mapping — inspecting the submitted inputs as-is"
        ]

    inputs: dict[str, Any] = {}
    notes: list[str] = []
    for entry in mapping:
        if not isinstance(entry, dict):
            continue
        new_id = entry.get("new_id")
        if not isinstance(new_id, str) or not new_id:
            continue
        if "set_value" in entry:
            inputs[new_id] = entry["set_value"]
        elif "old_id" in entry:
            old_id = entry["old_id"]
            if isinstance(old_id, str) and old_id in submitted:
                inputs[new_id] = submitted[old_id]
            else:
                notes.append(
                    f"mapped input '{old_id}' is absent from the submitted node — "
                    "the replacement may fail or behave differently"
                )
    return inputs, notes


def _iter_nodes(workflow: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield every node, including nodes inside inline subgraph maps."""
    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        yield node_id, node_data
        if _is_subgraph_class(node_data.get("class_type", "")):
            sub_nodes = _find_subgraph_node_map(node_data)
            if sub_nodes is not None:
                yield from _iter_nodes(sub_nodes)


def uses_server_replacement(
    workflow: dict[str, Any], node_replacements: dict[str, Any] | None
) -> bool:
    """True if any node (including inline subgraphs) has a server replacement."""
    if not node_replacements:
        return False
    for _node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        if node_data.get("class_type") in node_replacements:
            return True
        if _is_subgraph_class(node_data.get("class_type", "")):
            sub_nodes = _find_subgraph_node_map(node_data)
            if sub_nodes is not None and uses_server_replacement(sub_nodes, node_replacements):
                return True
    return False


class WorkflowInspector:
    def __init__(
        self,
        mode: str = "audit",
        dangerous_nodes: list[str] | None = None,
        allowed_nodes: list[str] | None = None,
        policy: WorkflowPolicy | None = None,
    ) -> None:
        self._mode = mode
        self._dangerous_nodes = set(dangerous_nodes or [])
        self._allowed_nodes = set(allowed_nodes or [])
        self._policy = policy or WorkflowPolicy()

    @property
    def mode(self) -> str:
        """Return the current inspection mode ('audit' or 'enforce')."""
        return self._mode

    @property
    def policy(self) -> WorkflowPolicy:
        """Return the declarative policy in effect."""
        return self._policy

    @property
    def on_warning(self) -> str:
        """What an enforce-mode warning means: elicit, block, or allow."""
        return self._policy.on_warning

    def _check_policy(self, workflow: dict[str, Any], nodes_used: list[str]) -> list[str]:
        """Apply the declarative policy; raise on hard violations in enforce mode."""
        policy = self._policy
        if not policy.is_configured:
            return []

        warnings: list[str] = []
        for node_type in sorted(set(nodes_used) & policy.warn_nodes):
            warnings.append(f"Policy warning node: {node_type}")

        denied = sorted(set(nodes_used) & policy.deny_nodes)
        if denied:
            message = f"policy denied node type(s): {', '.join(denied)}"
            if self._mode == "enforce":
                raise WorkflowBlockedError(f"Workflow blocked — {message}")
            warnings.append(f"Workflow would be blocked — {message} (audit mode)")

        if policy.max_nodes and len(nodes_used) > policy.max_nodes:
            message = (
                f"workflow has {len(nodes_used)} nodes; policy max_nodes is {policy.max_nodes}"
            )
            if self._mode == "enforce":
                raise WorkflowBlockedError(f"Workflow blocked — {message}")
            warnings.append(f"Workflow would be blocked — {message} (audit mode)")

        if policy.allowed_model_folders:
            violations: set[str] = set()
            for _node_id, node in _iter_nodes(workflow):
                inputs = node.get("inputs")
                if not isinstance(inputs, dict):
                    continue
                for field, folder in MODEL_LOADER_FIELDS.get(node.get("class_type", ""), ()):
                    value = inputs.get(field)
                    if (
                        isinstance(value, str)
                        and value
                        and folder not in policy.allowed_model_folders
                    ):
                        violations.add(f"{node.get('class_type')}.{field} loads from '{folder}'")
            if violations:
                message = (
                    "policy allows model folders "
                    f"{sorted(policy.allowed_model_folders)}; violations: {sorted(violations)}"
                )
                if self._mode == "enforce":
                    raise WorkflowBlockedError(f"Workflow blocked — {message}")
                warnings.append(f"Workflow would be blocked — {message} (audit mode)")

        return warnings

    def inspect(
        self,
        workflow: dict,
        _depth: int = 0,
        node_replacements: dict[str, Any] | None = None,
        known_node_types: set[str] | None = None,
    ) -> InspectionResult:
        """Inspect a ComfyUI workflow and return findings.

        Recurses into subgraph nodes (class_type containing ``subgraph``) when
        the nested node map is embedded inline. If a subgraph reference has no
        inline node map, a warning is emitted so callers know inspection is
        incomplete.

        When ``node_replacements`` is provided (from ``GET /node_replacements``),
        warns for any submitted ``class_type`` that the server will silently
        rewrite and re-inspects the effective node — class and remapped inputs
        — so what executes is vetted too (#111, #206). ``known_node_types`` (the
        keys of ``/object_info``) lets the inspector flag a replacement target
        that is not installed.
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
                    if _depth >= _MAX_SUBGRAPH_DEPTH:
                        warnings.append(
                            f"Node {node_id} ({class_type}) exceeds max subgraph depth "
                            f"({_MAX_SUBGRAPH_DEPTH}) — deeper nesting not inspected"
                        )
                    else:
                        sub_result = self.inspect(
                            sub_nodes,
                            _depth=_depth + 1,
                            node_replacements=node_replacements,
                            known_node_types=known_node_types,
                        )
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

        # Check for server-side node replacements (#111, #206). Upstream rewrites
        # class_types after submission, so inspect the effective node too: a
        # benign class can become a dangerous one, or a replacement can remap a
        # suspicious value into an input.
        if node_replacements:
            for node_id, node_data in workflow.items():
                if not isinstance(node_data, dict):
                    continue
                node_type = node_data.get("class_type", "")
                replacements = node_replacements.get(node_type)
                if not isinstance(replacements, list) or not replacements:
                    continue

                new_ids = [
                    str(r.get("new_node_id", "?")) for r in replacements if isinstance(r, dict)
                ]
                if new_ids:
                    warnings.append(
                        f"Node type '{node_type}' has server-side "
                        f"replacement(s) -> [{', '.join(new_ids)}] — what "
                        f"executes may differ from what was vetted"
                    )

                submitted_inputs = node_data.get("inputs", {})
                if not isinstance(submitted_inputs, dict):
                    submitted_inputs = {}
                for replacement in replacements:
                    if not isinstance(replacement, dict):
                        continue
                    new_type = replacement.get("new_node_id")
                    if not isinstance(new_type, str) or not new_type:
                        warnings.append(
                            f"Node {node_id} ({node_type}) has a malformed "
                            "server-side replacement — cannot verify what executes"
                        )
                        continue

                    if new_type in self._dangerous_nodes:
                        warnings.append(
                            "Dangerous node type after server-side replacement: "
                            f"{new_type} (submitted {node_type}, node {node_id})"
                        )
                    if known_node_types is not None and new_type not in known_node_types:
                        warnings.append(
                            f"Replacement target '{new_type}' for '{node_type}' is not "
                            "installed — cannot fully inspect what executes"
                        )

                    effective_inputs, notes = _remap_replacement_inputs(
                        submitted_inputs, replacement
                    )
                    warnings.extend(
                        f"Node {node_id} ({node_type} -> {new_type}): {note}" for note in notes
                    )
                    for input_key, value in effective_inputs.items():
                        warnings.extend(
                            _check_value_for_suspicious(value, node_id, new_type, input_key)
                        )

        # Declarative policy (#211): checked once for the whole graph, including
        # nodes nested in inline subgraphs. Hard violations raise in enforce mode
        # and downgrade to warnings in audit mode.
        if _depth == 0:
            warnings.extend(self._check_policy(workflow, nodes_used))

        # Enforce mode: block unapproved nodes
        if self._mode == "enforce" and self._allowed_nodes:
            unapproved = [n for n in nodes_used if n not in self._allowed_nodes]
            if unapproved:
                raise WorkflowBlockedError(
                    f"Workflow blocked — unapproved node types: {unapproved}"
                )

        return InspectionResult(
            nodes_used=nodes_used,
            warnings=list(dict.fromkeys(warnings)),
        )
