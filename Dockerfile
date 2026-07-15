# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Faster, quieter Python in a container
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=/data/reading.db

WORKDIR /app

# Install deps first so they cache across code changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# App code (see .dockerignore — real reader_config.py / db / venv are excluded,
# so the image ships the sample reader_config_example.py only)
COPY . .

# SQLite lives here; mount a volume to persist it across rebuilds
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8602

# Simple healthcheck against the app's /health endpoint
HEALTHCHECK --interval=30s --timeout=4s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8602/health',timeout=3).status==200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8602"]
