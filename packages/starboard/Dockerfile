# Starboard Server Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy workspace files
COPY pyproject.toml uv.lock ./
COPY packages/starboard-core packages/starboard-core
COPY packages/starboard-server packages/starboard-server

# Install uv
RUN pip install --no-cache-dir uv

# Install workspace dependencies
RUN uv sync --no-dev

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Run server
CMD ["uv", "run", "starboard-server"]

