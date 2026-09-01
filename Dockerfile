FROM python:3.13-slim

# curl is used by the container healthcheck below.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so application edits do not bust the layer cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/

# Defaults for the container; override in compose or a .env file.
ENV STORAGE_DIR=/storage/fitness_tracker \
    DB_PATH=/storage/fitness_tracker/tracker.db \
    PYTHONUNBUFFERED=1

# Run as a non-root user. The storage volume must be writable by this uid --
# on the host: chown -R 1000:1000 /path/to/storage
RUN useradd -u 1000 -m tracker && mkdir -p /storage/fitness_tracker \
    && chown -R tracker:tracker /storage
USER tracker

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
