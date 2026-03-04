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

# Default to HTTP transport in Docker
ENV TRANSPORT=http HOST=0.0.0.0 PORT=8000 LOG_LEVEL=INFO

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/health'); r.raise_for_status()" || exit 1

# Run with uvicorn for production
CMD ["uvicorn", "courtlistener_mcp.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
