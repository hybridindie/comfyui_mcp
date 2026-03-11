import httpx
import pytest
import respx

from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.model_checker import ModelChecker


@pytest.fixture
def client():
    return ComfyUIClient(base_url="http://test:8188")


@pytest.fixture
def checker():
    return ModelChecker()


class TestModelChecker:
    @respx.mock
    async def test_no_warnings_when_models_present(self, checker, client):
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(
                200, json=["epicrealism_v5.safetensors", "sd_v15.safetensors"]
            )
        )
        workflow = {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "epicrealism_v5.safetensors"},
            }
        }
        warnings = await checker.check_models(workflow, client)
        assert warnings == []

    @respx.mock
    async def test_warns_missing_checkpoint(self, checker, client):
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["sd_v15.safetensors"])
        )
        workflow = {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "missing_model.safetensors"},
            }
        }
        warnings = await checker.check_models(workflow, client)
        assert len(warnings) == 1
        assert "missing_model.safetensors" in warnings[0]
        assert "search_models" in warnings[0]

    @respx.mock
    async def test_warns_missing_lora(self, checker, client):
        respx.get("http://test:8188/models/loras").mock(
            return_value=httpx.Response(200, json=["detail_v1.safetensors"])
        )
        workflow = {
            "10": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "missing_lora.safetensors", "model": ["4", 0]},
            }
        }
        warnings = await checker.check_models(workflow, client)
        assert len(warnings) == 1
        assert "missing_lora.safetensors" in warnings[0]

    @respx.mock
    async def test_multiple_missing_models(self, checker, client):
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("http://test:8188/models/loras").mock(return_value=httpx.Response(200, json=[]))
        workflow = {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "missing.safetensors"},
            },
            "10": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "missing_lora.safetensors", "model": ["4", 0]},
            },
        }
        warnings = await checker.check_models(workflow, client)
        assert len(warnings) == 2

    @respx.mock
    async def test_skips_unknown_node_types(self, checker, client):
        workflow = {
            "1": {
                "class_type": "SomeCustomNode",
                "inputs": {"value": "test"},
            }
        }
        warnings = await checker.check_models(workflow, client)
        assert warnings == []

    @respx.mock
    async def test_handles_api_error_gracefully(self, checker, client):
        respx.get("http://test:8188/models/checkpoints").mock(return_value=httpx.Response(500))
        workflow = {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"},
            }
        }
        warnings = await checker.check_models(workflow, client)
        assert warnings == []

    @respx.mock
    async def test_vae_loader(self, checker, client):
        respx.get("http://test:8188/models/vae").mock(
            return_value=httpx.Response(200, json=["vae-ft-mse.safetensors"])
        )
        workflow = {
            "5": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": "missing_vae.safetensors"},
            }
        }
        warnings = await checker.check_models(workflow, client)
        assert len(warnings) == 1
        assert "missing_vae.safetensors" in warnings[0]

    @respx.mock
    async def test_controlnet_loader(self, checker, client):
        respx.get("http://test:8188/models/controlnet").mock(
            return_value=httpx.Response(200, json=[])
        )
        workflow = {
            "6": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": "missing_cn.safetensors"},
            }
        }
        warnings = await checker.check_models(workflow, client)
        assert len(warnings) == 1

    @respx.mock
    async def test_upscale_model_loader(self, checker, client):
        respx.get("http://test:8188/models/upscale_models").mock(
            return_value=httpx.Response(200, json=[])
        )
        workflow = {
            "7": {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": "4x_ultrasharp.pt"},
            }
        }
        warnings = await checker.check_models(workflow, client)
        assert len(warnings) == 1

    @respx.mock
    async def test_input_is_reference_not_string(self, checker, client):
        """When input is a node reference like ['4', 0], skip it."""
        workflow = {
            "10": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "detail.safetensors", "model": ["4", 0]},
            }
        }
        respx.get("http://test:8188/models/loras").mock(
            return_value=httpx.Response(200, json=["detail.safetensors"])
        )
        warnings = await checker.check_models(workflow, client)
        assert warnings == []
