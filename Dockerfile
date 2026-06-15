# Use standard python:3.14-slim and copy the uv binary into it
FROM python:3.14-slim AS builder

# Copy uv binaries from the official uv image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of fetching if possible
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install the project's dependencies using the lockfile and pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Build the final run image
FROM python:3.14-slim

# Force stdin, stdout and stderr to be totally unbuffered
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv

# Place executable symlinks in the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy the application source code
COPY iot-home-manager.py /app/
COPY iot_home_manager /app/iot_home_manager

# Make sure logs directory exists
RUN mkdir -p /app/logs

# Expose the API server port
EXPOSE 8000

# Execute python command
CMD ["python", "iot-home-manager.py"]
