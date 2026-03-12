FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY src/ ./src/

RUN groupadd --system app && useradd --system --gid app app
USER app

ENV PYTHONPATH=/app

ENTRYPOINT ["uv", "run", "comfyui-mcp"]
