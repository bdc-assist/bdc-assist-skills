# One image recipe for bdc-assist, bdc-doc-mcp and bdc-doc-builder (docker-compose.yml sets each one's
# command). Built with each clone as the context; Dockerfile.dockerignore keeps .env files out of the image.
FROM python:3.12-slim

# git: the builder clones git sources
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY . .
# the classic builder ignores Dockerfile.dockerignore: stop rather than build an image holding the clone's API keys
RUN test ! -e .env || (echo "a .env file reached the image: build with BuildKit (docker buildx)" >&2; exit 1)
RUN uv sync --frozen --no-dev

# run from the synced venv: "uv run" would sync again (dev group included) at every start
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
