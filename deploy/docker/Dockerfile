FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /bin/

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY --chown=app:app pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev

COPY --chown=app:app src/ ./src/

USER app

ENV PYTHONPATH=/app

ENTRYPOINT ["uv", "run", "comfyui-mcp-secure"]
