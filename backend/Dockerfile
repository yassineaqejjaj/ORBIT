# syntax=docker/dockerfile:1.7
# ORBIT backend image (API, worker, MCP, migrations). Build context: ./backend
#
# Targets:
#   runtime (default) production image: application code WITHOUT the demo dataset (app/seed/data)
#   demo              runtime + the fictitious demo dataset used by `python -m app.seed`
#
#   docker build --target runtime -t orbit-backend:dev .
#   docker build --target demo    -t orbit-backend:dev-demo .
#
# Base images are pinned by digest (refresh: `docker buildx imagetools inspect <image>`; Dependabot
# opens PRs for them). The embedding model is downloaded at build time at a pinned Hugging Face
# revision so the runtime works offline and the build is reproducible.

ARG PYTHON_IMAGE=python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    FASTEMBED_CACHE_PATH=/opt/models \
    ORBIT_MODEL_CACHE_DIR=/opt/models \
    HF_HOME=/opt/models/hf

COPY --from=uv /uv /uvx /usr/local/bin/

RUN groupadd --system --gid 10001 orbit \
    && useradd --system --uid 10001 --gid orbit --home-dir /app --shell /usr/sbin/nologin orbit

WORKDIR /app

# 1. Dependencies (cached layer: only invalidated when pyproject/uv.lock change)
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --python "$(which python3)"

# 2. Embedding model (and optionally the cross-encoder reranker) baked into the image at pinned revisions.
#    The default reranker model is MIT-licensed; models under a non-commercial licence are refused
#    unless ALLOW_NONCOMMERCIAL_MODELS=true (see THIRD_PARTY_NOTICES.md).
ARG ORBIT_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ARG ORBIT_EMBEDDING_MODEL_REVISION=faf4aa4225822f3bc6376869cb1164e8e3feedd0
ARG PRELOAD_RERANKER=false
ARG ORBIT_RERANKER_MODEL=BAAI/bge-reranker-base
ARG ORBIT_RERANKER_MODEL_REVISION=2cfc18c9415c912f9d8155881c133215df768a70
ARG ALLOW_NONCOMMERCIAL_MODELS=false
ENV ORBIT_EMBEDDING_MODEL=${ORBIT_EMBEDDING_MODEL} \
    ORBIT_RERANKER_MODEL=${ORBIT_RERANKER_MODEL}
COPY docker/preload_models.py /tmp/preload_models.py
RUN ORBIT_EMBEDDING_MODEL_REVISION="${ORBIT_EMBEDDING_MODEL_REVISION}" \
    ORBIT_RERANKER_MODEL_REVISION="${ORBIT_RERANKER_MODEL_REVISION}" \
    PRELOAD_RERANKER="${PRELOAD_RERANKER}" \
    ALLOW_NONCOMMERCIAL_MODELS="${ALLOW_NONCOMMERCIAL_MODELS}" \
    python /tmp/preload_models.py \
    && rm /tmp/preload_models.py \
    && chmod -R a+rX,go-w /opt/models

# ---------------------------------------------------------------------------------------------------
# Application sources, pruned of the demo dataset in a throw-away stage so that the data never
# lands in a layer of the runtime image.
FROM base AS app-src
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN rm -rf app/seed/data \
    && find app alembic -name '__pycache__' -prune -exec rm -rf {} +

# ---------------------------------------------------------------------------------------------------
FROM base AS app

ARG VERSION=0.0.0-dev
ARG REVISION=unknown
ARG CREATED=1970-01-01T00:00:00Z

LABEL org.opencontainers.image.title="orbit-backend" \
      org.opencontainers.image.description="ORBIT — plateforme de contexte et de mémoire gouvernée pour agents IA (API, worker, MCP)" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Devoteam"

COPY --from=app-src --chown=root:root /app/alembic.ini ./alembic.ini
COPY --from=app-src --chown=root:root /app/alembic ./alembic
COPY --from=app-src --chown=root:root /app/app ./app
COPY --chown=root:root docker/entrypoint.sh /usr/local/bin/orbit-entrypoint
COPY --chown=root:root docker/healthcheck.py /usr/local/bin/orbit-healthcheck
RUN chmod 0755 /usr/local/bin/orbit-entrypoint /usr/local/bin/orbit-healthcheck \
    && python -m compileall -q app alembic \
    && chmod -R a+rX,go-w /app \
    && mkdir -p /data/objects \
    && chown orbit:orbit /data /data/objects

# Code is owned by root and read-only for the service user; the root filesystem can be mounted
# read-only (only /tmp and /data/objects need to be writable).
ENV HF_HUB_OFFLINE=1 \
    ORBIT_OBJECT_STORE_PATH=/data/objects \
    ORBIT_APP_VERSION=${VERSION} \
    ORBIT_BUILD_REVISION=${REVISION}

USER 10001:10001
VOLUME ["/data/objects"]
EXPOSE 8000 9464

ENTRYPOINT ["/usr/local/bin/orbit-entrypoint"]
CMD ["api"]

# ---------------------------------------------------------------------------------------------------
# Demo image: adds the fictitious demo dataset (it contains C2/C3-labelled sample documents).
# Never deploy this target on a production environment; the seed also refuses to run unless
# ORBIT_DEMO_MODE=true.
FROM app AS demo
LABEL org.opencontainers.image.title="orbit-backend-demo"
COPY --chown=root:root app/seed/data ./app/seed/data
ENV ORBIT_IMAGE_FLAVOR=demo

# ---------------------------------------------------------------------------------------------------
# Default target (last stage): production runtime without demo data.
FROM app AS runtime
ENV ORBIT_IMAGE_FLAVOR=runtime
