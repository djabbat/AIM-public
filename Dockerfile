FROM python:3.11-slim

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr poppler-utils inotify-tools rlwrap \
        sqlite3 gnupg ca-certificates curl \
        espeak-ng \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir \
        prometheus-client circuitbreaker tqdm prompt-toolkit \
        fastapi uvicorn websockets \
        tenacity \
        sentence-transformers lancedb networkx httpx pyyaml

COPY . .

# Make CLI wrappers available
RUN mkdir -p /usr/local/bin && \
    for cmd in agents/graph.py agents/embed_daemon.py agents/memory_index.py \
               scripts/backup_system.py scripts/disk_monitor.py \
               agents/memory_cli.py agents/memory_health.py agents/profile.py \
               agents/pi_agent.py agents/voice.py; do \
        true; \
    done

ENV PYTHONUNBUFFERED=1 \
    AIM_LLM_TIMEOUT=60 \
    AIM_METRICS_PORT=9090 \
    AIM_HEALTH_PORT=9091 \
    AIM_WEB_PORT=8080 \
    AIM_PROFILE=default

EXPOSE 8080 9090 9091

# Persistent state should be mounted as volumes:
#   /root/.claude          - memory + indexes + checkpoints
#   /app/Patients          - patient data
#   /root/.aim_env         - API keys (read-only)
VOLUME ["/root/.claude", "/app/Patients"]

# Healthcheck against /healthz
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:9091/healthz || exit 1

CMD ["python", "-m", "web.api", "--host", "0.0.0.0", "--port", "8080", "--metrics"]
