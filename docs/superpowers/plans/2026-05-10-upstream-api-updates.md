# Upstream API Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt three deferred ComfyUI upstream-API capabilities in a single PR. (1) `/view?preview=webp;90` server-side thumbnails — significant bandwidth/context-window win when LLMs fetch images. (2) `/upload/image` `type` and `overwrite` params — gives callers explicit control over destination and replacement. (3) `/history?offset=N` server-side offset paging — adds a client-API capability for paging beyond the 1000-entry window.

**Architecture:** All three are passthrough extensions: client method signatures gain optional parameters, tools expose them via `Annotated[..., Field(...)]`, security primitives (sanitizer, rate limiter, audit logger) stay intact and apply at the same enforcement points. For (2) `upload_image` `type`, restrict the accepted values to a `Literal["input", "output", "temp"]` so callers cannot pass arbitrary destinations. For (3) the tool layer stays unchanged in this PR — the client API addition is the deliverable; refactoring `comfyui_get_history` to use server-side offset is deferred.

**Tech Stack:** Python 3.12, httpx (async), respx (HTTP mocking), pytest with `asyncio_mode = auto`, FastMCP, Pydantic `Field`/`Literal`/`Annotated`.

---

## File Structure

**Modify:**
- `src/comfyui_mcp/client.py` — extend `get_image`, `upload_image`, `get_history` method signatures.
- `src/comfyui_mcp/tools/files.py` — extend `comfyui_get_image` (preview) and `comfyui_upload_image` (type/overwrite) tools.
- `tests/test_client.py` — tests for the three new client capabilities.
- `tests/test_tools_files.py` — tests for the two new tool parameter sets.
- `README.md` — note the new tool params in the Tools section.

No new files.

---

## Task 1: Add `preview` support to `client.get_image`

ComfyUI `/view` accepts `preview=webp;<quality>` or `preview=jpeg;<quality>` to return a server-rendered thumbnail in the requested format. The response's `Content-Type` reflects the chosen format. Use case: large generated PNGs become small webp thumbnails for LLM context.

**Files:**
- Modify: `src/comfyui_mcp/client.py:248-260` (the `get_image` method)
- Test: `tests/test_client.py` (add to `TestComfyUIClient`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client.py` inside `class TestComfyUIClient:`:

```python
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
            return_value=httpx.Response(200, content=b"png-bytes", headers={"content-type": "image/png"})
        )
        await client.get_image("out.png")
        params = dict(route.calls.last.request.url.params.multi_items())
        assert "preview" not in params
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v -k "test_get_image_preview or test_get_image_without_preview"`
Expected: 2 of 3 fail (the no-preview test passes since current behavior already omits `preview`); the two preview tests fail because `get_image` doesn't accept the kwarg yet.

- [ ] **Step 3: Update `client.get_image`**

In `src/comfyui_mcp/client.py`, replace the existing `get_image` method:

```python
    async def get_image(
        self,
        filename: str,
        subfolder: str = "",
        *,
        preview: str | None = None,
    ) -> tuple[bytes, str]:
        """GET /view — download an output image by filename and subfolder.

        Args:
            filename: Image filename in ComfyUI's output dir.
            subfolder: Subfolder within ComfyUI's output dir.
            preview: Optional thumbnail spec passed to ComfyUI as ``preview=<spec>``.
                Format ``<format>;<quality>`` where format is ``webp`` or ``jpeg``
                and quality is 1-100. ComfyUI re-encodes the image server-side.
        """
        params: dict[str, str] = {
            "filename": filename,
            "subfolder": subfolder,
            "type": "output",
        }
        if preview is not None:
            params["preview"] = preview
        r = await self._request("get", "/view", params=params)
        content_type = r.headers.get("content-type", "image/png")
        return r.content, content_type
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v -k "test_get_image"`
Expected: all PASS (including pre-existing get_image tests).

- [ ] **Step 5: Commit**

```bash
git add src/comfyui_mcp/client.py tests/test_client.py
git commit -m "Add preview kwarg to client.get_image for server-rendered thumbnails"
```

---

## Task 2: Expose preview thumbnail support in `comfyui_get_image` tool

The tool gains two new optional parameters: `preview_format` (Literal `"webp"` / `"jpeg"`) and `preview_quality` (int 1-100). When both are provided, they're combined into the `preview=<fmt>;<q>` spec passed to the client.

**Files:**
- Modify: `src/comfyui_mcp/tools/files.py` (the `comfyui_get_image` function)
- Test: `tests/test_tools_files.py`

- [ ] **Step 1: Read the test file to learn the components fixture and existing tests**

Run: `grep -n "TestGetImage\|def components\|class Test" tests/test_tools_files.py | head -15`

Note the fixture name and the existing TestGetImage class location so the new tests slot in cleanly.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_tools_files.py` inside the existing test class for get_image (or as a new sibling class `TestGetImagePreview`):

```python
class TestGetImagePreview:
    @respx.mock
    async def test_data_uri_with_webp_preview(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/view").mock(
            return_value=httpx.Response(
                200,
                content=b"webp-bytes",
                headers={"content-type": "image/webp"},
            )
        )
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        result = await tools["comfyui_get_image"](
            filename="out.png",
            preview_format="webp",
            preview_quality=85,
        )
        assert result.startswith("data:image/webp;base64,")

    @respx.mock
    async def test_data_uri_with_jpeg_preview(self, components):
        client, audit, limiter, sanitizer = components
        route = respx.get("http://test:8188/view").mock(
            return_value=httpx.Response(
                200,
                content=b"jpeg-bytes",
                headers={"content-type": "image/jpeg"},
            )
        )
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        await tools["comfyui_get_image"](
            filename="out.png",
            preview_format="jpeg",
            preview_quality=50,
        )
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["preview"] == "jpeg;50"

    async def test_quality_without_format_rejected(self, components):
        client, audit, limiter, sanitizer = components
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        with pytest.raises(ValueError, match="preview_format"):
            await tools["comfyui_get_image"](
                filename="out.png",
                preview_quality=85,
            )

    async def test_url_format_ignores_preview(self, components):
        client, audit, limiter, sanitizer = components
        mcp = FastMCP("test")
        tools = register_file_tools(
            mcp, client, audit, limiter, sanitizer,
        )
        # When response_format='url', preview params should be ignored
        # (the returned /view URL is unchanged; LLMs that want a thumbnail
        # should use response_format='data_uri').
        result = await tools["comfyui_get_image"](
            filename="out.png",
            response_format="url",
            preview_format="webp",
            preview_quality=80,
        )
        assert "/view?" in result
        assert "preview" not in result
```

Make sure `pytest` is imported at the top of the test file (it should already be).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_files.py::TestGetImagePreview -v`
Expected: all 4 FAIL — the tool doesn't accept the new params.

- [ ] **Step 4: Update the tool**

In `src/comfyui_mcp/tools/files.py`, replace the existing `comfyui_get_image` signature and body. The current header was:

```python
    async def comfyui_get_image(
        filename: Annotated[str, Field(description="Name of the image file to retrieve")],
        subfolder: Annotated[
            str,
            Field(
                description="Subfolder within ComfyUI's output directory. "
                "Use the subfolder value from comfyui_list_outputs or generation results."
            ),
        ] = "",
        response_format: Annotated[
            Literal["data_uri", "url"],
            Field(description="'data_uri' to inline the image, or 'url' to return a /view URL"),
        ] = "data_uri",
        base_url_override: Annotated[
            str | None,
            Field(
                description="Optional override for URL responses; falls back to configured base URL"
            ),
        ] = None,
    ) -> str:
        """Download a generated image from ComfyUI or return a direct view URL.

        Returns:
            Base64-encoded image data with content type prefix, or a direct image URL
        """
        limiter.check("get_image")
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        await audit.async_log(
            tool="get_image",
            action="downloading",
            extra={"filename": clean_name, "response_format": response_format},
        )

        resolved_base_url = base_url_override or image_view_base_url

        if response_format == "url":
            return client.build_image_url(
                clean_name,
                clean_subfolder,
                base_url=resolved_base_url,
            )

        if response_format != "data_uri":
            raise ValueError("response_format must be 'data_uri' or 'url'")

        data, content_type = await client.get_image(
            clean_name,
            clean_subfolder,
        )
        b64 = base64.b64encode(data).decode()
        return f"data:{content_type};base64,{b64}"
```

Replace it with:

```python
    async def comfyui_get_image(
        filename: Annotated[str, Field(description="Name of the image file to retrieve")],
        subfolder: Annotated[
            str,
            Field(
                description="Subfolder within ComfyUI's output directory. "
                "Use the subfolder value from comfyui_list_outputs or generation results."
            ),
        ] = "",
        response_format: Annotated[
            Literal["data_uri", "url"],
            Field(description="'data_uri' to inline the image, or 'url' to return a /view URL"),
        ] = "data_uri",
        base_url_override: Annotated[
            str | None,
            Field(
                description="Optional override for URL responses; falls back to configured base URL"
            ),
        ] = None,
        preview_format: Annotated[
            Literal["webp", "jpeg"] | None,
            Field(
                default=None,
                description="If set with response_format='data_uri', request a server-rendered "
                "thumbnail in this format instead of the original (smaller payload, lossy).",
            ),
        ] = None,
        preview_quality: Annotated[
            int | None,
            Field(
                default=None,
                ge=1,
                le=100,
                description="Encoder quality (1-100) for preview_format. Default: 90 when "
                "preview_format is set.",
            ),
        ] = None,
    ) -> str:
        """Download a generated image from ComfyUI or return a direct view URL.

        Returns:
            Base64-encoded image data with content type prefix, or a direct image URL.
            When response_format='data_uri' and preview_format is set, ComfyUI re-encodes
            the image server-side as a smaller webp or jpeg thumbnail.
        """
        if preview_quality is not None and preview_format is None:
            raise ValueError(
                "preview_quality is only meaningful when preview_format is also set"
            )

        limiter.check("get_image")
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        await audit.async_log(
            tool="get_image",
            action="downloading",
            extra={
                "filename": clean_name,
                "response_format": response_format,
                "preview_format": preview_format,
            },
        )

        resolved_base_url = base_url_override or image_view_base_url

        if response_format == "url":
            # Preview params don't apply to URL responses — the returned URL
            # is a direct /view link; callers wanting a thumbnail should
            # request response_format='data_uri'.
            return client.build_image_url(
                clean_name,
                clean_subfolder,
                base_url=resolved_base_url,
            )

        if response_format != "data_uri":
            raise ValueError("response_format must be 'data_uri' or 'url'")

        preview_spec: str | None = None
        if preview_format is not None:
            quality = preview_quality if preview_quality is not None else 90
            preview_spec = f"{preview_format};{quality}"

        data, content_type = await client.get_image(
            clean_name,
            clean_subfolder,
            preview=preview_spec,
        )
        b64 = base64.b64encode(data).decode()
        return f"data:{content_type};base64,{b64}"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_files.py -v -k "GetImage"`
Expected: all pass (existing TestGetImage tests + the 4 new TestGetImagePreview tests).

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src/comfyui_mcp/tools/files.py && uv run ruff format src/comfyui_mcp/tools/files.py && uv run mypy src/comfyui_mcp/tools/files.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/comfyui_mcp/tools/files.py tests/test_tools_files.py
git commit -m "Expose preview thumbnail params on comfyui_get_image"
```

---

## Task 3: Add `type` and `overwrite` support to `client.upload_image`

ComfyUI `/upload/image` accepts `type` (input/output/temp) and `overwrite` ("true"/"1") as form fields. Default behavior preserved: type=input, no overwrite (server auto-renames `name (1).png`).

**Files:**
- Modify: `src/comfyui_mcp/client.py:240-246`
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client.py` inside `class TestComfyUIClient:`:

```python
    @respx.mock
    async def test_upload_image_default_type(self, client):
        # Default behavior: form does not include 'type' or 'overwrite' fields
        route = respx.post("http://test-comfyui:8188/upload/image").mock(
            return_value=httpx.Response(200, json={"name": "x.png", "subfolder": "", "type": "input"})
        )
        await client.upload_image(b"data", "x.png")
        body = route.calls.last.request.content
        # multipart form encoded — check that type/overwrite are NOT present
        assert b'name="type"' not in body
        assert b'name="overwrite"' not in body

    @respx.mock
    async def test_upload_image_with_type_and_overwrite(self, client):
        route = respx.post("http://test-comfyui:8188/upload/image").mock(
            return_value=httpx.Response(200, json={"name": "x.png", "subfolder": "", "type": "output"})
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v -k "test_upload_image"`
Expected: the two new tests with `destination` kwarg fail (TypeError: unexpected keyword argument). The default-type test passes against current code since the form is empty by default — but pre-existing `test_upload_image` should still pass.

- [ ] **Step 3: Update `client.upload_image`**

In `src/comfyui_mcp/client.py`, replace lines 240-246:

```python
    async def upload_image(self, data: bytes, filename: str, subfolder: str = "") -> dict:
        files = {"image": (filename, data, "image/png")}
        form_data: dict[str, str] = {}
        if subfolder:
            form_data["subfolder"] = subfolder
        r = await self._request("post", "/upload/image", files=files, data=form_data)
        return r.json()
```

with:

```python
    async def upload_image(
        self,
        data: bytes,
        filename: str,
        subfolder: str = "",
        *,
        destination: str = "input",
        overwrite: bool = False,
    ) -> dict:
        """POST /upload/image — upload an image to ComfyUI.

        Args:
            data: Raw image bytes.
            filename: Target filename in ComfyUI's storage.
            subfolder: Optional subfolder within the destination.
            destination: Destination type. One of "input" (default), "output", "temp".
                The wire field name is ``type`` — renamed here to avoid shadowing the
                Python builtin.
            overwrite: If True, replace an existing file with the same name. If False
                (default), ComfyUI auto-renames by suffixing ``(N)`` when a duplicate
                exists.
        """
        if destination not in {"input", "output", "temp"}:
            raise ValueError(
                f"destination must be one of 'input', 'output', 'temp'; got {destination!r}"
            )
        files = {"image": (filename, data, "image/png")}
        form_data: dict[str, str] = {}
        if subfolder:
            form_data["subfolder"] = subfolder
        # Only include 'type'/'overwrite' when the caller deviates from defaults —
        # keeps the request body identical to historical behavior in the common case.
        if destination != "input":
            form_data["type"] = destination
        if overwrite:
            form_data["overwrite"] = "true"
        r = await self._request("post", "/upload/image", files=files, data=form_data)
        return r.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v -k "test_upload_image"`
Expected: all PASS, including the pre-existing `test_upload_image`.

- [ ] **Step 5: Commit**

```bash
git add src/comfyui_mcp/client.py tests/test_client.py
git commit -m "Add destination/overwrite kwargs to client.upload_image"
```

---

## Task 4: Expose `destination` and `overwrite` on `comfyui_upload_image` tool

**Security note:** this is a deliberate widening of the tool surface. The default stays `destination="input"` so existing callers see no behavior change. The tool restricts `destination` to a `Literal` so callers cannot pass arbitrary directory names; `overwrite` is a bool. The path sanitizer's filename validation still applies to all destinations. Upstream ComfyUI also enforces `os.path.commonpath` against traversal regardless of which destination we choose.

**Files:**
- Modify: `src/comfyui_mcp/tools/files.py` (the `comfyui_upload_image` function)
- Test: `tests/test_tools_files.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools_files.py`:

```python
class TestUploadImageDestination:
    @respx.mock
    async def test_upload_to_output_dir(self, components):
        client, audit, limiter, sanitizer = components
        route = respx.post("http://test:8188/upload/image").mock(
            return_value=httpx.Response(
                200, json={"name": "x.png", "subfolder": "", "type": "output"}
            )
        )
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        result = await tools["comfyui_upload_image"](
            filename="x.png",
            image_data="ZGF0YQ==",  # base64 "data"
            destination="output",
        )
        body = route.calls.last.request.content
        assert b'name="type"' in body
        assert b"output" in body
        assert "Uploaded" in result

    @respx.mock
    async def test_upload_with_overwrite(self, components):
        client, audit, limiter, sanitizer = components
        route = respx.post("http://test:8188/upload/image").mock(
            return_value=httpx.Response(
                200, json={"name": "x.png", "subfolder": "", "type": "input"}
            )
        )
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        await tools["comfyui_upload_image"](
            filename="x.png",
            image_data="ZGF0YQ==",
            overwrite=True,
        )
        body = route.calls.last.request.content
        assert b'name="overwrite"' in body
        assert b"true" in body

    @respx.mock
    async def test_upload_default_unchanged(self, components):
        # Verify existing default-call behavior is byte-identical to before:
        # no 'type' or 'overwrite' fields in the multipart body.
        client, audit, limiter, sanitizer = components
        route = respx.post("http://test:8188/upload/image").mock(
            return_value=httpx.Response(
                200, json={"name": "x.png", "subfolder": "", "type": "input"}
            )
        )
        mcp = FastMCP("test")
        tools = register_file_tools(mcp, client, audit, limiter, sanitizer)
        await tools["comfyui_upload_image"](
            filename="x.png",
            image_data="ZGF0YQ==",
        )
        body = route.calls.last.request.content
        assert b'name="type"' not in body
        assert b'name="overwrite"' not in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tools_files.py::TestUploadImageDestination -v`
Expected: the two parametrized tests fail (tool doesn't accept `destination`/`overwrite` kwargs).

- [ ] **Step 3: Update the tool**

In `src/comfyui_mcp/tools/files.py`, replace the existing `comfyui_upload_image`:

```python
    async def comfyui_upload_image(filename: str, image_data: str, subfolder: str = "") -> str:
        """Upload an image to ComfyUI's input directory.

        Args:
            filename: Name for the uploaded file (e.g. 'reference.png')
            image_data: Base64-encoded image data
            subfolder: Optional subfolder within ComfyUI's input directory
        """
        limiter.check("upload_image")
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        raw = base64.b64decode(image_data)
        sanitizer.validate_size(len(raw))
        await audit.async_log(
            tool="upload_image",
            action="uploading",
            extra={"filename": clean_name, "size_bytes": len(raw)},
        )
        result = await client.upload_image(raw, clean_name, clean_subfolder)
        await audit.async_log(tool="upload_image", action="uploaded", extra={"result": result})
        return f"Uploaded {result.get('name', clean_name)} to ComfyUI input directory"
```

with:

```python
    async def comfyui_upload_image(
        filename: Annotated[
            str,
            Field(description="Name for the uploaded file (e.g. 'reference.png')"),
        ],
        image_data: Annotated[
            str,
            Field(description="Base64-encoded image data"),
        ],
        subfolder: Annotated[
            str,
            Field(default="", description="Optional subfolder within the destination directory"),
        ] = "",
        destination: Annotated[
            Literal["input", "output", "temp"],
            Field(
                default="input",
                description="Destination directory. 'input' (default) is where workflows "
                "read user-supplied images from; 'output' and 'temp' are usually only "
                "useful for testing or scripted setups.",
            ),
        ] = "input",
        overwrite: Annotated[
            bool,
            Field(
                default=False,
                description="If True, replace any existing file with the same name. If False "
                "(default), ComfyUI auto-renames by suffixing ' (N)'.",
            ),
        ] = False,
    ) -> str:
        """Upload an image to ComfyUI.

        Defaults to ComfyUI's input directory (the destination workflows read from).
        Set destination='output' or 'temp' only if you have a specific reason.
        """
        limiter.check("upload_image")
        clean_name = sanitizer.validate_filename(filename)
        clean_subfolder = sanitizer.validate_subfolder(subfolder)
        raw = base64.b64decode(image_data)
        sanitizer.validate_size(len(raw))
        await audit.async_log(
            tool="upload_image",
            action="uploading",
            extra={
                "filename": clean_name,
                "size_bytes": len(raw),
                "destination": destination,
                "overwrite": overwrite,
            },
        )
        result = await client.upload_image(
            raw,
            clean_name,
            clean_subfolder,
            destination=destination,
            overwrite=overwrite,
        )
        await audit.async_log(tool="upload_image", action="uploaded", extra={"result": result})
        return f"Uploaded {result.get('name', clean_name)} to ComfyUI {destination} directory"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_files.py -v -k "UploadImage"`
Expected: all pass — existing UploadImage tests plus the new TestUploadImageDestination tests.

- [ ] **Step 5: Run the security invariants to confirm the tool still has sanitizer in its closure**

Run: `uv run pytest tests/test_security_invariants.py -v`
Expected: all PASS. `comfyui_upload_image` is in the `FILE_HANDLING_TOOLS` allowlist and uses `sanitizer.validate_filename` / `validate_subfolder` — these checks still happen up front.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src/comfyui_mcp/tools/files.py && uv run ruff format src/comfyui_mcp/tools/files.py && uv run mypy src/comfyui_mcp/tools/files.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/comfyui_mcp/tools/files.py tests/test_tools_files.py
git commit -m "Expose destination/overwrite on comfyui_upload_image

Restricts destination to Literal['input', 'output', 'temp'] so callers
can't pass arbitrary directory names. Sanitizer validation still applies
to filename and subfolder. Default stays 'input' — existing callers see
no behavior change."
```

---

## Task 5: Add `offset` support to `client.get_history`

Upstream `/history` accepts `offset` (default -1, meaning no offset). This task adds the client capability. The `comfyui_get_history` tool is unchanged in this PR — the tool layer's full conversion to server-side offset is deferred (the response-shape `total` becomes ambiguous; needs separate design).

**Files:**
- Modify: `src/comfyui_mcp/client.py:158-165` (the `get_history` method)
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client.py` inside `class TestComfyUIClient:`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v -k "test_get_history"`
Expected: the new tests fail (the method doesn't accept `offset`).

- [ ] **Step 3: Update the method**

In `src/comfyui_mcp/client.py`, replace lines 158-165:

```python
    async def get_history(self, max_items: int | None = None) -> dict:
        params: dict[str, int] = {}
        if max_items is not None:
            if max_items <= 0:
                raise ValueError("max_items must be a positive integer")
            params["max_items"] = min(max_items, 1000)
        r = await self._request("get", "/history", params=params or None)
        return r.json()
```

with:

```python
    async def get_history(
        self,
        max_items: int | None = None,
        *,
        offset: int | None = None,
    ) -> dict:
        """GET /history — fetch execution history with optional pagination.

        Args:
            max_items: Maximum number of history entries to return. Capped at 1000
                server-side regardless of the value passed.
            offset: Zero-based starting index. None (default) sends no offset, which
                ComfyUI treats as "no offset" (newest entries first).
        """
        params: dict[str, int] = {}
        if max_items is not None:
            if max_items <= 0:
                raise ValueError("max_items must be a positive integer")
            params["max_items"] = min(max_items, 1000)
        if offset is not None:
            if offset < 0:
                raise ValueError("offset must be >= 0")
            params["offset"] = offset
        r = await self._request("get", "/history", params=params or None)
        return r.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v -k "test_get_history"`
Expected: all PASS, including the pre-existing `test_get_history`.

- [ ] **Step 5: Commit**

```bash
git add src/comfyui_mcp/client.py tests/test_client.py
git commit -m "Add optional offset to client.get_history

Threads upstream /history?offset=N support through the client. The
comfyui_get_history tool is unchanged in this PR — converting it to
server-side paging would change the meaning of the 'total' field in
the pagination envelope and needs separate design."
```

---

## Task 6: README updates

Document the new tool parameters.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Find the existing get_image and upload_image entries in the Tools table**

Run: `grep -n "comfyui_get_image\|comfyui_upload_image" README.md`

The current row for `comfyui_get_image` is something like:
```
| `comfyui_get_image` | Download a generated image as base64 data URI, or get a direct /view URL. Params: filename, subfolder, response_format. |
```

The current row for `comfyui_upload_image` is something like:
```
| `comfyui_upload_image` | Upload an image to ComfyUI's input directory. Params: filename, image_data (base64), subfolder. |
```

- [ ] **Step 2: Update both rows**

Locate the `comfyui_get_image` row and replace its description with:

```
| `comfyui_get_image` | Download a generated image as base64 data URI, or get a direct /view URL. Optional server-rendered thumbnail via `preview_format="webp"|"jpeg"` + `preview_quality=1-100` (only applies with `response_format="data_uri"`). |
```

Locate the `comfyui_upload_image` row and replace its description with:

```
| `comfyui_upload_image` | Upload an image to ComfyUI. Params: filename, image_data (base64), subfolder, `destination="input"|"output"|"temp"` (default input), `overwrite` (default False — ComfyUI auto-renames duplicates). |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document new params on comfyui_get_image and comfyui_upload_image"
```

---

## Task 7: Final verification sweep

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v 2>&1 | tail -10`
Expected: ALL PASS, no skipped, no errors. The count should be > 496 (the baseline before this PR) — roughly +10-12 new tests across this work.

- [ ] **Step 2: Lint, format, type-check**

Run: `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/comfyui_mcp/`
Expected: clean.

- [ ] **Step 3: Pre-commit on touched files**

Run: `uv run pre-commit run --files $(git diff --name-only main...HEAD)`
Expected: all hooks pass.

- [ ] **Step 4: Verify the tool surface is unchanged in count**

Run: `grep -rn "@mcp.tool" src/comfyui_mcp/tools/ | wc -l`
Expected: same count as before this PR — this work only adds optional parameters to existing tools, no new tools.

- [ ] **Step 5: Confirm no other tests reference the old `client.upload_image` or `client.get_image` signatures**

Run: `grep -rn "client.upload_image\|client.get_image" src/ tests/ | head`
Expected: usages match the new signatures (positional args still work — `data`, `filename`, optionally `subfolder` — and the new kwargs are keyword-only via `*`).

If any verification step fails, fix and amend the appropriate commit (or add a fixup commit) before declaring the plan complete.

---

## Out of scope (deliberately not in this plan)

- **Wire `comfyui_get_history` to use server-side offset.** Doing this changes the meaning of the pagination envelope's `total` field (it would become only the size of the returned page). Needs a separate design discussion — should `total` go away, become approximate, or be computed via an extra round-trip? Deferred.
- **`POST /upload/mask` `type`/`overwrite` params.** The mask upload tool has the same upstream support; could extend symmetrically. Deferred for a follow-up since masks are a less common use case.
- **`GET /view?channel=rgb|a` for mask debugging.** Niche; defer.
- **Surfacing new `object_info` fields (`deprecated`, `experimental`, etc.) in `list_nodes`.** Audit recommendation; deferred — needs broader UX thinking about how to filter.
