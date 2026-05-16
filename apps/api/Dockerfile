# syntax=docker/dockerfile:1.7
# ─── Multi-stage build for the K-12 AI Tutor API ────────────────────────────

# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Build tools needed for some wheels (grpcio, cryptography, etc).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc \
 && rm -rf /var/lib/apt/lists/*

# Pre-create a venv we'll copy to the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python deps via requirements.txt (deterministic, no Poetry needed).
COPY requirements.txt ./
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# Minimal runtime deps + a non-root user.
#
# LibreOffice headless is the teacher-pipeline ingest layer
# (`teacher-authoring.md` §6 "Normalize -> PDF", task 2.1): it converts
# uploaded `.docx`/`.pptx`/`.txt` files to PDF via `soffice --headless`.
# We install only the Writer + Impress components (Word + PowerPoint) plus
# common fonts — not the full LibreOffice suite — to keep the image lean.
#
# Sandboxing note: `app.pipeline.ingest.convert_to_pdf` already runs
# `soffice` with a hard timeout, an isolated per-call profile dir, and a
# scrubbed environment. The remaining sandbox guarantees come from THIS
# container — the conversion subprocess inherits the container's network
# and resource limits. For a hardened deploy run the API container with
# `--network=none`-equivalent egress restrictions and CPU/memory caps
# (Fly.io machine limits / a restricted Docker network) so a crafted
# upload cannot reach the network or exhaust the host.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl \
      libreoffice-writer libreoffice-impress \
      fonts-liberation fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY pyproject.toml requirements.txt ./

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
