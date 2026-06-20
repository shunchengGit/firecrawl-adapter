FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir requests beautifulsoup4 html2text lxml

# Copy application code
COPY adapter/ ./adapter/

EXPOSE 3672

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3672/healthz', timeout=3)" || exit 1

CMD ["python", "-m", "adapter"]
