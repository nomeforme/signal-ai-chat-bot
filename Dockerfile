# Signal AI Chat Bot - Python Bot Container
FROM python:3.12-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./
COPY uv.lock* ./
COPY README.md ./

# Install dependencies
RUN uv sync --no-dev

# Copy source code (will be overridden by volume mount in dev)
COPY src/ ./src/

# Set Python to run in unbuffered mode for real-time logs
ENV PYTHONUNBUFFERED=1

# Default command (can be overridden in docker-compose)
CMD ["uv", "run", "python", "src/main.py"]
