---
name: connect
description: Add the ComfyUI MCP server to Claude, Cursor, OpenCode, or another MCP client
---

# Connect a client

The user wants to wire this server into an MCP client. Request: "$ARGUMENTS".

## Steps

1. **Ask two things.** Which client, and where ComfyUI runs. Same machine with a local install → stdio. A shared/remote ComfyUI → Streamable HTTP.

2. **stdio (local ComfyUI).** The client launches the server:
   - installed: `comfyui-mcp-secure`
   - no persistent install: `uvx comfyui-mcp-secure`
   - Docker: `docker run --rm -i ... ghcr.io/hybridindie/comfyui_mcp:latest`
   Set `COMFYUI_URL` if the instance is not at `127.0.0.1:8188`.

3. **HTTP (remote/shared).** The server must run with `transport.remote.enabled: true` and `auth.enabled: true`. Export `COMFYUI_MCP_HTTP_TOKEN` on the server host, then give the client:

   ```json
   {
     "url": "http://<host>:8080/mcp",
     "headers": { "Authorization": "Bearer <token>" }
   }
   ```

   Use the client's environment interpolation — `${env:COMFYUI_MCP_HTTP_TOKEN}` in Cursor, `{env:COMFYUI_MCP_HTTP_TOKEN}` in OpenCode. Claude Desktop does not expand env vars in every version; keep its config `chmod 600` if the token is pasted.

4. **Verify with a read-only call.** `comfyui_get_server_features` (or `comfyui_get_queue`). If it fails: check the URL and transport, the token variable, and the bind (a non-loopback host requires auth).

5. **Report** the transport, where the config lives, and the verification result.

## Notes

- Never paste a token into a file you might commit; use the client's env interpolation.
- Do not install packages or edit client config without the user's go-ahead.
- Full per-client snippets: `docs/site/getting-started-clients.md`; the HTTP compose example lives in `deploy/docker/docker-compose.http.yml`.
