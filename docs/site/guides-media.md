---
type: guide
title: "Video and audio outputs"
description: "Find, fetch, and display the media ComfyUI produces that is not a raster image — URL, server path, or inline data URI."
created: 2026-11-27
updated: 2026-11-27
---

# Video and audio outputs

Image generation ends in a PNG, but a workflow can also return video (AnimateDiff,
SVD, VHS nodes) and audio. Those are not images, and `comfyui_get_image` will
refuse them. The tool for them is **`comfyui_get_output`**.

## Find the file

ComfyUI records every output in `/history`, keyed by prompt id. Two ways to see
them:

- **`comfyui_get_history`** — raw history entries. Each entry's `outputs` maps a
  node id to arrays keyed by kind (`images`, `gifs`, `videos`, `audio`, …).
- **the `comfyui://outputs` resource** — flattened, newest first, with `kind`,
  `filename`, `subfolder`, `prompt_id`, and `node_id` for each file.

> `comfyui_list_outputs` is **images-only**; it does not list video or audio.
> Use history or the resource when the output is not a PNG.

## Fetch it

```text
comfyui_get_output(filename="ComfyUI_00042_.mp4", subfolder="")
```

The default `response_format="url"` returns:

```json
{
  "status": "url",
  "filename": "ComfyUI_00042_.mp4",
  "subfolder": "",
  "url": "http://127.0.0.1:8188/view?filename=ComfyUI_00042_.mp4&type=output"
}
```

Three formats:

| `response_format` | Returns | Use when |
|---|---|---|
| `"url"` (default) | `{status, filename, subfolder, url}` | The client can open or render a URL — cheapest, no payload |
| `"path"` | `{status, filename, subfolder, path, note}` | Something on the server side needs the relative path. It is **relative to ComfyUI's output dir, not the MCP host** |
| `"inline"` | `{status, …, content_type, size_bytes, data_uri?}` | The client cannot fetch URLs and the file is small |

### Inline is capped at 8 MiB

`inline` inlines only when the content type is `image/*`, `video/*`, or
`audio/*` **and** the file is at most 8 MiB. Otherwise it returns metadata and
a URL instead of failing:

```json
{
  "status": "too_large",
  "filename": "ComfyUI_00042_.mp4",
  "content_type": "video/mp4",
  "size_bytes": 24117248,
  "url": "http://127.0.0.1:8188/view?...",
  "note": "Output is 24117248 bytes; the inline cap is 8388608 bytes. Use the URL instead."
}
```

`status: "not_inlined"` means the content type is not allow-listed (for
example `application/octet-stream` when ComfyUI cannot guess a type).

Do not retry `inline` for a bigger file — switch to the URL.

## `get_output` vs `get_image`

| | `comfyui_get_image` | `comfyui_get_output` |
|---|---|---|
| For | Raster images | Video, audio, GIF, or any output |
| Default return | A `data:image/...;base64,...` **string** | A dict with `url` (or `data_uri` when inline) |
| Thumbnails | `preview_format="webp"\|"jpeg"` via ComfyUI | Not supported — inline is the raw file |
| Refuses | Non-raster content types | Only over-cap/unknown types (returns a URL) |

Rule of thumb: if the filename does not end in `.png`, `.jpg`, `.jpeg`, or
`.webp`, use `comfyui_get_output`.

## Video/audio *inputs*

`comfyui_upload_image` uploads through ComfyUI's `/upload/image` endpoint with
an image MIME type and the image/JSON extension allow-list, so an `.mp4` is
rejected before it reaches ComfyUI. For video-to-video or audio-driven
workflows:

1. Put the file in ComfyUI's `input/` directory yourself (or use the ComfyUI
   UI's upload control).
2. Pass the **filename** to the tool or workflow exactly as it appears —
   `comfyui_run_workflow` with a `LoadVideo`-style node, or
   `comfyui_validate_workflow` first if you are unsure of the graph.

The same rule applies to any non-image input: the MCP upload path is for
images and masks.

## Notes

- `tools.profile: "core"` hides both `comfyui_get_output` and
  `comfyui_get_history`. The read-only `comfyui://outputs` resource still
  lists the files; for the tool calls, use the default `full` profile.
- Outputs live under ComfyUI's output directory; `subfolder` comes from
  history and must be passed back unchanged.
- The URL is built from `comfyui.url`, or `comfyui.external_url` when the
  browser reaches ComfyUI by a different address. `base_url_override` wins
  for a single call.
