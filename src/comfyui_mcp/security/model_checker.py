"""Proactive model availability checker for workflow submission."""

from typing import Any

import httpx

from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.model_registry import MODEL_LOADER_FIELDS as _MODEL_LOADER_FIELDS


class ModelChecker:
    """Checks workflow loader nodes against installed models."""

    async def check_models(self, workflow: dict[str, Any], client: ComfyUIClient) -> list[str]:
        """Check all model loader nodes in a workflow for missing models.

        Returns a list of warning strings for any missing models.
        Silently returns empty list on API errors (best-effort check).
        """
        to_check: list[tuple[str, str]] = []

        for node_data in workflow.values():
            if not isinstance(node_data, dict):
                continue
            class_type = node_data.get("class_type", "")
            if class_type not in _MODEL_LOADER_FIELDS:
                continue

            fields = _MODEL_LOADER_FIELDS[class_type]
            inputs = node_data.get("inputs", {})

            for field_name, folder in fields:
                model_name = inputs.get(field_name)
                if not isinstance(model_name, str) or not model_name:
                    continue
                to_check.append((model_name, folder))

        if not to_check:
            return []

        folder_models: dict[str, set[str]] = {}
        failed_folders: set[str] = set()
        warnings: list[str] = []

        for model_name, folder in to_check:
            if folder in failed_folders:
                continue
            if folder not in folder_models:
                try:
                    models = await client.get_models(folder)
                    folder_models[folder] = set(models)
                except (httpx.HTTPError, OSError):
                    failed_folders.add(folder)
                    continue

            if model_name not in folder_models[folder]:
                warnings.append(
                    f"Missing model: '{model_name}' not found in {folder}. "
                    f"Use search_models to find and download_model to install it."
                )

        return warnings
