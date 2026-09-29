# AmbiSense API. Build from the repository root:  docker build -f backend/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# libgl1/libglib2.0-0: OpenCV runtime. ffmpeg is only needed for the OPTIONAL audio analysis
# (AUDIO_ANALYTICS_ENABLED=true); build with --build-arg INSTALL_FFMPEG=true to include it.
ARG INSTALL_FFMPEG=false
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && if [ "$INSTALL_FFMPEG" = "true" ]; then apt-get install -y --no-install-recommends ffmpeg; fi \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

# Copy only what the API needs (see .dockerignore: databases, uploads and secrets never enter the image).
COPY backend /app/backend
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY scripts/init_database.py /app/scripts/init_database.py
COPY yolov8n.pt /app/yolov8n.pt

# Run as an unprivileged user; artifact directories are volumes owned by it.
RUN useradd --create-home --uid 10001 ambisense \
    && mkdir -p /app/videos /app/reports /app/logs /app/models \
    && chown -R ambisense:ambisense /app
USER ambisense

EXPOSE 8000
# Lightweight liveness probe (no database or model access).
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

# Initialise the schema idempotently (fresh DB: create + stamp; existing: upgrade), then serve.
CMD ["sh", "-c", "python scripts/init_database.py && exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
