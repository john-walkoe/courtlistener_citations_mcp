FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN groupadd --gid 1000 mcpuser && \
    useradd --uid 1000 --gid 1000 --create-home mcpuser

# Install build dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy project definition and install dependencies (non-editable)
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir . && \
    chown -R mcpuser:mcpuser /app

USER mcpuser

ENV LOG_LEVEL=INFO

# Port 8000 used when running in HTTP mode (TRANSPORT=http)
EXPOSE 8000

# Default: STDIO transport (for Docker MCP Gateway / MCP Toolkit)
# HTTP mode: docker run -e TRANSPORT=http -e PORT=8000 -p 8000:8000 <image>
CMD ["courtlistener-mcp"]
