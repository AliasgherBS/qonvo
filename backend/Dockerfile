# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# uv for dependency management (copied from the official distroless image).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (cached layer), without the project itself.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now the application code.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

EXPOSE 8000

# Default: API server. Compose overrides `command` for worker/scheduler.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
