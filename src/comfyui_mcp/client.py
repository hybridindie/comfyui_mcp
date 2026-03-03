"""Async HTTP client for ComfyUI API."""

from __future__ import annotations

import httpx


class ComfyUIClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        timeout_connect: int = 30,
        timeout_read: int = 300,
        tls_verify: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=timeout_connect, read=timeout_read, write=30, pool=30
        )
        self._tls_verify = tls_verify
        self._client: httpx.AsyncClient | None = None

    def _get_headers(self) -> dict[str, str]:
        return {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._get_headers(),
                timeout=self._timeout,
                verify=self._tls_verify,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "ComfyUIClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def get_queue(self) -> dict:
        c = await self._get_client()
        r = await c.get("/queue")
        r.raise_for_status()
        return r.json()

    async def post_prompt(self, workflow: dict) -> dict:
        c = await self._get_client()
        r = await c.post("/prompt", json={"prompt": workflow})
        r.raise_for_status()
        return r.json()

    async def get_models(self, folder: str) -> list:
        c = await self._get_client()
        r = await c.get(f"/models/{folder}")
        r.raise_for_status()
        return r.json()

    async def get_object_info(self, node_class: str | None = None) -> dict:
        path = f"/object_info/{node_class}" if node_class else "/object_info"
        c = await self._get_client()
        r = await c.get(path)
        r.raise_for_status()
        return r.json()

    async def get_history(self) -> dict:
        c = await self._get_client()
        r = await c.get("/history")
        r.raise_for_status()
        return r.json()

    async def get_history_item(self, prompt_id: str) -> dict:
        c = await self._get_client()
        r = await c.get(f"/history/{prompt_id}")
        r.raise_for_status()
        return r.json()

    async def interrupt(self) -> None:
        c = await self._get_client()
        r = await c.post("/interrupt")
        r.raise_for_status()

    async def delete_queue_item(self, prompt_id: str) -> None:
        c = await self._get_client()
        r = await c.post("/queue", json={"delete": [prompt_id]})
        r.raise_for_status()

    async def upload_image(
        self, data: bytes, filename: str, subfolder: str = ""
    ) -> dict:
        c = await self._get_client()
        files = {"image": (filename, data, "image/png")}
        form_data = {}
        if subfolder:
            form_data["subfolder"] = subfolder
        r = await c.post("/upload/image", files=files, data=form_data)
        r.raise_for_status()
        return r.json()

    async def get_image(
        self, filename: str, subfolder: str = "output"
    ) -> tuple[bytes, str]:
        c = await self._get_client()
        r = await c.get("/view", params={"filename": filename, "subfolder": subfolder})
        r.raise_for_status()
        content_type = r.headers.get("content-type", "image/png")
        return r.content, content_type

    async def get_embeddings(self) -> list:
        c = await self._get_client()
        r = await c.get("/embeddings")
        r.raise_for_status()
        return r.json()

    async def get_workflow_templates(self) -> list:
        c = await self._get_client()
        r = await c.get("/workflow_templates")
        r.raise_for_status()
        return r.json()

    async def get_extensions(self) -> list:
        c = await self._get_client()
        r = await c.get("/extensions")
        r.raise_for_status()
        return r.json()

    async def get_features(self) -> dict:
        c = await self._get_client()
        r = await c.get("/features")
        r.raise_for_status()
        return r.json()

    async def get_model_types(self) -> list:
        c = await self._get_client()
        r = await c.get("/models")
        r.raise_for_status()
        return r.json()

    async def get_view_metadata(self, folder: str, filename: str) -> dict:
        c = await self._get_client()
        r = await c.get(f"/view_metadata/{folder}", params={"filename": filename})
        r.raise_for_status()
        return r.json()

    async def get_prompt_status(self) -> dict:
        c = await self._get_client()
        r = await c.get("/prompt")
        r.raise_for_status()
        return r.json()

    async def clear_queue(
        self, clear_running: bool = False, clear_pending: bool = False
    ) -> None:
        c = await self._get_client()
        data: dict[str, list[str]] = {"clear": []}
        if clear_running:
            data["clear"].append("running")
        if clear_pending:
            data["clear"].append("pending")
        r = await c.post("/queue", json=data)
        r.raise_for_status()

    async def upload_mask(
        self, data: bytes, filename: str, subfolder: str = ""
    ) -> dict:
        c = await self._get_client()
        files = {"mask": (filename, data, "image/png")}
        form_data: dict[str, str] = {}
        if subfolder:
            form_data["subfolder"] = subfolder
        r = await c.post("/upload/mask", files=files, data=form_data)
        r.raise_for_status()
        return r.json()
