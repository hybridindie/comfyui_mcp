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

Use **`comfyui_upload_media`**. It accepts base64 video/audio, writes to
ComfyUI's input directory by default, and sends the real media content type:

```text
comfyui_upload_media(filename="clip.mp4", media_data="<base64>",
                     destination="input")
```

Then pass the filename to the workflow — a `LoadVideo`/VHS-style node — and run
it with `comfyui_run_workflow`.

- The extension must be in `security.allowed_media_extensions`: by default
  `.mp4 .webm .mov .mkv .avi .m4v .mpg .mpeg .mp3 .wav .flac .ogg .m4a .aac
  .opus`. An empty list disables the tool; it does **not** fall back to the
  image allowlist.
- The file is not transcoded or inspected. Pass a container the workflow's
  loader can read; a mislabeled extension fails inside ComfyUI, not at upload.
- The same `max_upload_size` / `max_upload_size_mb` limits apply.

`comfyui_upload_image` remains image/mask/JSON-only. If media uploads are
disabled or unavailable, copy the file into ComfyUI's `input/` directory
yourself and pass the filename instead.

## Notes

- `tools.profile: "core"` hides both `comfyui_get_output` and
  `comfyui_get_history`. The read-only `comfyui://outputs` resource still
  lists the files; for the tool calls, use the default `full` profile.
- Outputs live under ComfyUI's output directory; `subfolder` comes from
  history and must be passed back unchanged.
- The URL is built from `comfyui.url`, or `comfyui.external_url` when the
  browser reaches ComfyUI by a different address. `base_url_override` wins
  for a single call.
