"""Tests for ComfyUI HTTP client."""

import asyncio
import json

import httpx
import pytest
import respx

from comfyui_mcp.client import ComfyUIClient


@pytest.fixture
def client():
    return ComfyUIClient(
        base_url="http://test-comfyui:8188",
        timeout_connect=5,
        timeout_read=10,
        tls_verify=False,
    )


class TestComfyUIClient:
    @respx.mock
    async def test_get_queue(self, client):
        respx.get("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        )
        result = await client.get_queue()
        assert "queue_running" in result

    @respx.mock
    async def test_post_prompt(self, client):
        respx.post("http://test-comfyui:8188/prompt").mock(
            return_value=httpx.Response(
                200, json={"prompt_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
            )
        )
        result = await client.post_prompt({"1": {"class_type": "KSampler", "inputs": {}}})
        assert result["prompt_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    @respx.mock
    async def test_get_models(self, client):
        respx.get("http://test-comfyui:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["model_v1.safetensors", "model_v2.safetensors"])
        )
        result = await client.get_models("checkpoints")
        assert len(result) == 2

    @respx.mock
    async def test_get_history(self, client):
        respx.get("http://test-comfyui:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}})
        )
        result = await client.get_history()
        assert "abc" in result

    @respx.mock
    async def test_get_job_returns_job_object(self, client):
        job_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        respx.get(f"http://test-comfyui:8188/api/jobs/{job_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "prompt_id": job_id,
                    "status": "in_progress",
                    "outputs": {},
                },
            )
        )
        result = await client.get_job(job_id)
        assert result["prompt_id"] == job_id
        assert result["status"] == "in_progress"

    async def test_get_job_rejects_non_uuid(self, client):
        with pytest.raises(ValueError, match="Invalid prompt_id"):
            await client.get_job("not-a-uuid")

    @respx.mock
    async def test_get_jobs_no_params(self, client):
        respx.get("http://test-comfyui:8188/api/jobs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [],
                    "pagination": {"offset": 0, "limit": None, "total": 0, "has_more": False},
                },
            )
        )
        result = await client.get_jobs()
        assert "jobs" in result
        assert "pagination" in result

    @respx.mock
    async def test_get_jobs_passes_filters(self, client):
        route = respx.get("http://test-comfyui:8188/api/jobs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [],
                    "pagination": {"offset": 5, "limit": 10, "total": 0, "has_more": False},
                },
            )
        )
        await client.get_jobs(
            status=["pending", "in_progress"],
            workflow_id="wf-123",
            sort_by="execution_duration",
            sort_order="asc",
            limit=10,
            offset=5,
        )
        request = route.calls.last.request
        params = dict(request.url.params.multi_items())
        assert params["status"] == "pending,in_progress"
        assert params["workflow_id"] == "wf-123"
        assert params["sort_by"] == "execution_duration"
        assert params["sort_order"] == "asc"
        assert params["limit"] == "10"
        assert params["offset"] == "5"

    async def test_get_jobs_rejects_invalid_status(self, client):
        with pytest.raises(ValueError, match="Invalid status"):
            await client.get_jobs(status=["bogus"])

    async def test_get_jobs_rejects_invalid_sort_by(self, client):
        with pytest.raises(ValueError, match="sort_by"):
            await client.get_jobs(sort_by="random")

    async def test_get_jobs_rejects_invalid_sort_order(self, client):
        with pytest.raises(ValueError, match="sort_order"):
            await client.get_jobs(sort_order="sideways")

    async def test_get_jobs_rejects_non_positive_limit(self, client):
        with pytest.raises(ValueError, match="limit"):
            await client.get_jobs(limit=0)
        with pytest.raises(ValueError, match="limit"):
            await client.get_jobs(limit=-1)

    async def test_get_jobs_rejects_negative_offset(self, client):
        with pytest.raises(ValueError, match="offset"):
            await client.get_jobs(offset=-1)

    @respx.mock
    async def test_get_object_info(self, client):
        respx.get("http://test-comfyui:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {"input": {}}})
        )
        result = await client.get_object_info()
        assert "KSampler" in result

    @respx.mock
    async def test_interrupt(self, client):
        respx.post("http://test-comfyui:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.interrupt()

    @respx.mock
    async def test_interrupt_with_prompt_id_sends_body(self, client):
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        route = respx.post("http://test-comfyui:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.interrupt(prompt_id=prompt_id)
        request = route.calls.last.request
        body = json.loads(request.content)
        assert body == {"prompt_id": prompt_id}

    @respx.mock
    async def test_interrupt_without_prompt_id_sends_no_body(self, client):
        route = respx.post("http://test-comfyui:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.interrupt()
        request = route.calls.last.request
        # Either no body or empty body — definitely no prompt_id
        assert request.content in (b"", b"{}", None)

    async def test_interrupt_rejects_non_uuid_prompt_id(self, client):
        with pytest.raises(ValueError, match="Invalid prompt_id"):
            await client.interrupt(prompt_id="not-a-uuid")

    @respx.mock
    async def test_upload_image(self, client):
        respx.post("http://test-comfyui:8188/upload/image").mock(
            return_value=httpx.Response(
                200, json={"name": "uploaded.png", "subfolder": "", "type": "input"}
            )
        )
        result = await client.upload_image(b"fake-png-data", "test.png")
        assert result["name"] == "uploaded.png"

    @respx.mock
    async def test_upload_image_default_type(self, client):
        # Default behavior: form does not include 'type' or 'overwrite' fields
        route = respx.post("http://test-comfyui:8188/upload/image").mock(
            return_value=httpx.Response(
                200, json={"name": "x.png", "subfolder": "", "type": "input"}
            )
        )
        await client.upload_image(b"data", "x.png")
        body = route.calls.last.request.content
        # multipart form encoded — check that type/overwrite are NOT present
        assert b'name="type"' not in body
        assert b'name="overwrite"' not in body

    @respx.mock
    async def test_upload_image_with_type_and_overwrite(self, client):
        route = respx.post("http://test-comfyui:8188/upload/image").mock(
            return_value=httpx.Response(
                200, json={"name": "x.png", "subfolder": "", "type": "output"}
            )
        )
        await client.upload_image(
            b"data",
            "x.png",
            destination="output",
            overwrite=True,
        )
        body = route.calls.last.request.content
        assert b'name="type"' in body
        assert b"output" in body
        assert b'name="overwrite"' in body
        assert b"true" in body

    async def test_upload_image_rejects_invalid_destination(self, client):
        with pytest.raises(ValueError, match="destination"):
            await client.upload_image(b"data", "x.png", destination="garbage")

    @respx.mock
    async def test_get_image(self, client):
        route = respx.get("http://test-comfyui:8188/view").mock(
            return_value=httpx.Response(
                200, content=b"fake-image-bytes", headers={"content-type": "image/png"}
            )
        )
        data, content_type = await client.get_image("output.png", "output")
        assert data == b"fake-image-bytes"
        assert content_type == "image/png"
        assert route.calls
        request = route.calls[0].request
        assert request.url.params["type"] == "output"

    @respx.mock
    async def test_get_image_preview_webp(self, client):
        route = respx.get("http://test-comfyui:8188/view").mock(
            return_value=httpx.Response(
                200,
                content=b"fake-webp-bytes",
                headers={"content-type": "image/webp"},
            )
        )
        data, content_type = await client.get_image("out.png", preview="webp;90")
        assert data == b"fake-webp-bytes"
        assert content_type == "image/webp"
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["filename"] == "out.png"
        assert params["preview"] == "webp;90"
        assert params["type"] == "output"

    @respx.mock
    async def test_get_image_preview_jpeg(self, client):
        route = respx.get("http://test-comfyui:8188/view").mock(
            return_value=httpx.Response(
                200,
                content=b"fake-jpeg-bytes",
                headers={"content-type": "image/jpeg"},
            )
        )
        await client.get_image("out.png", preview="jpeg;75")
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["preview"] == "jpeg;75"

    @respx.mock
    async def test_get_image_without_preview_omits_param(self, client):
        route = respx.get("http://test-comfyui:8188/view").mock(
            return_value=httpx.Response(
                200,
                content=b"png-bytes",
                headers={"content-type": "image/png"},
            )
        )
        await client.get_image("out.png")
        params = dict(route.calls.last.request.url.params.multi_items())
        assert "preview" not in params

    @respx.mock
    async def test_delete_queue_item(self, client):
        respx.post("http://test-comfyui:8188/queue").mock(return_value=httpx.Response(200, json={}))
        await client.delete_queue_item("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    @respx.mock
    async def test_get_history_item(self, client):
        respx.get("http://test-comfyui:8188/history/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").mock(
            return_value=httpx.Response(
                200, json={"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": {"outputs": {}}}
            )
        )
        result = await client.get_history_item("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in result

    @respx.mock
    async def test_get_embeddings(self, client):
        respx.get("http://test-comfyui:8188/embeddings").mock(
            return_value=httpx.Response(200, json=["embedding1.pt", "embedding2.pt"])
        )
        result = await client.get_embeddings()
        assert len(result) == 2

    @respx.mock
    async def test_get_extensions(self, client):
        respx.get("http://test-comfyui:8188/extensions").mock(
            return_value=httpx.Response(200, json=["ext1", "ext2"])
        )
        result = await client.get_extensions()
        assert len(result) == 2

    @respx.mock
    async def test_get_features(self, client):
        respx.get("http://test-comfyui:8188/features").mock(
            return_value=httpx.Response(200, json={"supports_preview_metadata": True})
        )
        result = await client.get_features()
        assert result["supports_preview_metadata"] is True

    @respx.mock
    async def test_get_model_types(self, client):
        respx.get("http://test-comfyui:8188/models").mock(
            return_value=httpx.Response(200, json=["checkpoints", "loras", "vae"])
        )
        result = await client.get_model_types()
        assert len(result) == 3
        assert "checkpoints" in result

    @respx.mock
    async def test_get_view_metadata(self, client):
        respx.get("http://test-comfyui:8188/view_metadata/checkpoints").mock(
            return_value=httpx.Response(200, json={"filename": "model.safetensors", "size": 123456})
        )
        result = await client.get_view_metadata("checkpoints", "model.safetensors")
        assert result["filename"] == "model.safetensors"

    @respx.mock
    async def test_get_prompt_status(self, client):
        respx.get("http://test-comfyui:8188/prompt").mock(
            return_value=httpx.Response(200, json={"exec_info": {"queue_remaining": 0}})
        )
        result = await client.get_prompt_status()
        assert "exec_info" in result

    @respx.mock
    async def test_get_system_stats(self, client):
        payload = {"system": {"comfyui_version": "0.3.10"}, "devices": []}
        respx.get("http://test-comfyui:8188/system_stats").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.get_system_stats()
        assert result["system"]["comfyui_version"] == "0.3.10"

    @respx.mock
    async def test_clear_queue_pending(self, client):
        route = respx.post("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.clear_queue(clear_pending=True)
        assert json.loads(route.calls[0].request.content) == {"clear": ["pending"]}

    @respx.mock
    async def test_clear_queue_running(self, client):
        route = respx.post("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.clear_queue(clear_running=True)
        assert json.loads(route.calls[0].request.content) == {"clear": ["running"]}

    @respx.mock
    async def test_clear_queue_both(self, client):
        route = respx.post("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.clear_queue(clear_running=True, clear_pending=True)
        payload = json.loads(route.calls[0].request.content)
        assert "running" in payload["clear"]
        assert "pending" in payload["clear"]

    @respx.mock
    async def test_upload_mask(self, client):
        respx.post("http://test-comfyui:8188/upload/mask").mock(
            return_value=httpx.Response(
                200, json={"name": "mask.png", "subfolder": "", "type": "input"}
            )
        )
        result = await client.upload_mask(
            b"fake-mask-data",
            "mask.png",
            {"filename": "original.png", "type": "input"},
        )
        assert result["name"] == "mask.png"

    @respx.mock
    async def test_retry_on_connection_error(self, client):
        route = respx.get("http://test-comfyui:8188/queue")
        route.side_effect = [
            httpx.ConnectError("Connection refused"),
            httpx.Response(200, json={"queue_running": [], "queue_pending": []}),
        ]
        result = await client.get_queue()
        assert "queue_running" in result
        assert route.call_count == 2

    @respx.mock
    async def test_no_retry_on_4xx(self, client):
        """4xx errors are not retried — they indicate client-side issues."""
        route = respx.get("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(404, json={"error": "Not Found"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_queue()
        assert route.call_count == 1

    @respx.mock
    async def test_retry_on_502_then_succeed(self, client):
        """502 is retried; second attempt succeeds."""
        route = respx.get("http://test-comfyui:8188/queue")
        route.side_effect = [
            httpx.Response(502, json={"error": "Bad Gateway"}),
            httpx.Response(200, json={"queue_running": [], "queue_pending": []}),
        ]
        result = await client.get_queue()
        assert "queue_running" in result
        assert route.call_count == 2

    @respx.mock
    async def test_concurrent_get_client_returns_same_instance(self, client):
        """Concurrent _get_client() calls should return the same AsyncClient instance."""
        results = await asyncio.gather(
            client._get_client(),
            client._get_client(),
            client._get_client(),
        )
        assert results[0] is results[1]
        assert results[1] is results[2]

    async def test_get_models_validates_path_segment(self, client):
        with pytest.raises(ValueError, match="invalid characters"):
            await client.get_models("../etc")

    async def test_get_view_metadata_validates_path_segment(self, client):
        with pytest.raises(ValueError, match="invalid characters"):
            await client.get_view_metadata("../etc", "file.safetensors")

    @respx.mock
    async def test_get_history_with_max_items(self, client):
        route = respx.get("http://test-comfyui:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}})
        )
        result = await client.get_history(max_items=50)
        assert "abc" in result
        request = route.calls[0].request
        assert request.url.params["max_items"] == "50"

    @respx.mock
    async def test_get_history_with_offset(self, client):
        route = respx.get("http://test-comfyui:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}})
        )
        await client.get_history(max_items=100, offset=50)
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["offset"] == "50"
        assert params["max_items"] == "100"

    @respx.mock
    async def test_get_history_without_offset_omits_param(self, client):
        route = respx.get("http://test-comfyui:8188/history").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.get_history(max_items=100)
        params = dict(route.calls.last.request.url.params.multi_items())
        assert "offset" not in params

    async def test_get_history_rejects_negative_offset(self, client):
        with pytest.raises(ValueError, match="offset"):
            await client.get_history(max_items=100, offset=-1)

    @respx.mock
    async def test_get_object_info_cache_returns_cached(self, client):
        route = respx.get("http://test-comfyui:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {"input": {}}})
        )
        result1 = await client.get_object_info()
        result2 = await client.get_object_info()
        assert result1 == result2
        assert route.call_count == 1

    def test_build_image_url_rejects_javascript_scheme(self, client):
        with pytest.raises(ValueError, match="http or https"):
            client.build_image_url("test.png", base_url="javascript:alert(1)")


class TestModelManagerClient:
    @respx.mock
    async def test_get_model_manager_folders(self, client):
        respx.get("http://test-comfyui:8188/model-manager/models").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "vae": ["/models/vae"],
                        "loras": ["/models/loras"],
                        "checkpoints": ["/models/checkpoints"],
                    },
                },
            )
        )
        result = await client.get_model_manager_folders()
        assert result == ["checkpoints", "loras", "vae"]

    @respx.mock
    async def test_create_download_task(self, client):
        route = respx.post("http://test-comfyui:8188/model-manager/model").mock(
            return_value=httpx.Response(200, json={"success": True, "data": {"taskId": "task-1"}})
        )
        result = await client.create_download_task(
            model_type="checkpoints",
            path_index=0,
            fullname="model.safetensors",
            download_platform="huggingface",
            download_url="https://huggingface.co/org/repo/resolve/main/model.safetensors",
            size_bytes=1000000,
        )
        assert result["taskId"] == "task-1"
        body = route.calls[0].request.content.decode()
        assert "previewFile=" in body

    @respx.mock
    async def test_get_download_tasks(self, client):
        respx.get("http://test-comfyui:8188/model-manager/download/task").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [{"taskId": "t1", "status": "doing", "progress": 50}],
                },
            )
        )
        result = await client.get_download_tasks()
        assert len(result) == 1
        assert result[0]["taskId"] == "t1"

    @respx.mock
    async def test_delete_download_task(self, client):
        respx.delete("http://test-comfyui:8188/model-manager/download/task-1").mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "data": {"taskId": "task-1", "removed": True}},
            )
        )
        result = await client.delete_download_task("task-1")
        assert result == {"taskId": "task-1", "removed": True}


class TestPathInjectionValidation:
    """Verify that prompt_id and path segment validators block injection attempts."""

    async def test_get_history_item_rejects_path_traversal(self, client):
        with pytest.raises(ValueError, match="Invalid prompt_id"):
            await client.get_history_item("../../../free")

    async def test_get_history_item_rejects_empty(self, client):
        with pytest.raises(ValueError, match="Invalid prompt_id"):
            await client.get_history_item("")

    async def test_get_history_item_rejects_non_uuid(self, client):
        with pytest.raises(ValueError, match="Invalid prompt_id"):
            await client.get_history_item("not-a-valid-uuid-format")

    async def test_delete_queue_item_rejects_path_traversal(self, client):
        with pytest.raises(ValueError, match="Invalid prompt_id"):
            await client.delete_queue_item("../../userdata")

    async def test_get_object_info_rejects_path_traversal(self, client):
        with pytest.raises(ValueError, match="invalid characters"):
            await client.get_object_info("../../userdata")

    async def test_get_object_info_rejects_slash(self, client):
        with pytest.raises(ValueError, match="invalid characters"):
            await client.get_object_info("node/traversal")

    async def test_get_object_info_rejects_empty(self, client):
        with pytest.raises(ValueError, match="must not be empty"):
            await client.get_object_info("")

    async def test_delete_download_task_rejects_path_traversal(self, client):
        with pytest.raises(ValueError, match="invalid characters"):
            await client.delete_download_task("../../free")

    async def test_delete_download_task_rejects_empty(self, client):
        with pytest.raises(ValueError, match="must not be empty"):
            await client.delete_download_task("")

    @respx.mock
    async def test_valid_uuid_passes_through(self, client):
        """Sanity check: valid UUID is accepted."""
        respx.get("http://test-comfyui:8188/history/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").mock(
            return_value=httpx.Response(200, json={})
        )
        result = await client.get_history_item("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert isinstance(result, dict)

    @respx.mock
    async def test_valid_node_class_passes_through(self, client):
        """Sanity check: valid node class name is accepted."""
        respx.get("http://test-comfyui:8188/object_info/KSampler").mock(
            return_value=httpx.Response(200, json={"KSampler": {}})
        )
        result = await client.get_object_info("KSampler")
        assert "KSampler" in result


class TestComfyUIManagerClient:
    @respx.mock
    async def test_get_manager_version(self, client):
        respx.get("http://test-comfyui:8188/v2/manager/version").mock(
            return_value=httpx.Response(200, text="V4.1")
        )
        result = await client.get_manager_version()
        assert result == "V4.1"

    @respx.mock
    async def test_get_installed_custom_nodes(self, client):
        payload = {
            "comfyui-impact-pack": {
                "name": "Impact Pack",
                "ver": "1.0.0",
            }
        }
        respx.get("http://test-comfyui:8188/v2/customnode/installed").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.get_installed_custom_nodes()
        assert "comfyui-impact-pack" in result

    @respx.mock
    async def test_queue_manager_task_install(self, client):
        route = respx.post("http://test-comfyui:8188/v2/manager/queue/task").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.queue_manager_task(
            kind="install",
            params={
                "id": "comfyui-impact-pack",
                "version": "latest",
                "selected_version": "latest",
                "mode": "remote",
                "channel": "default",
            },
        )
        body = json.loads(route.calls[0].request.content)
        assert body["kind"] == "install"
        assert body["params"]["id"] == "comfyui-impact-pack"
        assert body["client_id"] == "comfyui-mcp"
        assert "ui_id" in body

    @respx.mock
    async def test_queue_manager_task_uninstall(self, client):
        route = respx.post("http://test-comfyui:8188/v2/manager/queue/task").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.queue_manager_task(
            kind="uninstall",
            params={"node_name": "comfyui-impact-pack", "is_unknown": False},
        )
        body = json.loads(route.calls[0].request.content)
        assert body["kind"] == "uninstall"
        assert body["params"]["node_name"] == "comfyui-impact-pack"

    @respx.mock
    async def test_queue_manager_task_update(self, client):
        route = respx.post("http://test-comfyui:8188/v2/manager/queue/task").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.queue_manager_task(
            kind="update",
            params={"node_name": "comfyui-impact-pack", "node_ver": None},
        )
        body = json.loads(route.calls[0].request.content)
        assert body["kind"] == "update"
        assert body["params"]["node_name"] == "comfyui-impact-pack"

    @respx.mock
    async def test_start_custom_node_queue(self, client):
        respx.get("http://test-comfyui:8188/v2/manager/queue/start").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.start_custom_node_queue()

    @respx.mock
    async def test_get_custom_node_queue_status(self, client):
        payload = {
            "is_processing": True,
            "total_count": 3,
            "processed_count": 1,
            "current_action": "installing comfyui-impact-pack",
        }
        respx.get("http://test-comfyui:8188/v2/manager/queue/status").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.get_custom_node_queue_status()
        assert result["is_processing"] is True
        assert result["total_count"] == 3
        assert result["processed_count"] == 1

    @respx.mock
    async def test_reset_custom_node_queue(self, client):
        respx.get("http://test-comfyui:8188/v2/manager/queue/reset").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.reset_custom_node_queue()

    @respx.mock
    async def test_reboot_comfyui(self, client):
        respx.get("http://test-comfyui:8188/v2/manager/reboot").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.reboot_comfyui()
