"""Proactive model availability checker for workflow submission."""

from __future__ import annotations

from typing import Any

import httpx

from comfyui_mcp.client import ComfyUIClient

# Maps node class_type -> list of (input field name, model folder) pairs.
# Most loaders have one model field, but some (DualCLIPLoader, TripleCLIPLoader)
# load multiple models from the same folder.
_MODEL_LOADER_FIELDS: dict[str, list[tuple[str, str]]] = {
    "CheckpointLoaderSimple": [("ckpt_name", "checkpoints")],
    "CheckpointLoader": [("ckpt_name", "checkpoints")],
    "unCLIPCheckpointLoader": [("ckpt_name", "checkpoints")],
    "LoraLoader": [("lora_name", "loras")],
    "LoraLoaderModelOnly": [("lora_name", "loras")],
    "VAELoader": [("vae_name", "vae")],
    "ControlNetLoader": [("control_net_name", "controlnet")],
    "UpscaleModelLoader": [("model_name", "upscale_models")],
    "CLIPLoader": [("clip_name", "clip")],
    "CLIPVisionLoader": [("clip_name", "clip_vision")],
    "StyleModelLoader": [("style_model_name", "style_models")],
    "GLIGENLoader": [("gligen_name", "gligen")],
    "DiffusersLoader": [("model_path", "diffusers")],
    "UNETLoader": [("unet_name", "diffusion_models")],
    "DualCLIPLoader": [("clip_name1", "clip"), ("clip_name2", "clip")],
    "TripleCLIPLoader": [("clip_name1", "clip"), ("clip_name2", "clip"), ("clip_name3", "clip")],
    "PhotoMakerLoader": [("photomaker_model_name", "photomaker")],
    "IPAdapterModelLoader": [("ipadapter_file", "ipadapter")],
}


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
        warnings: list[str] = []

        for model_name, folder in to_check:
            if folder not in folder_models:
                try:
                    models = await client.get_models(folder)
                    folder_models[folder] = set(models)
                except (httpx.HTTPError, OSError):
                    folder_models[folder] = set()
                    continue

            if model_name not in folder_models[folder]:
                warnings.append(
                    f"Missing model: '{model_name}' not found in {folder}. "
                    f"Use search_models to find and download_model to install it."
                )

        return warnings
