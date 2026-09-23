# syntax=docker/dockerfile:1.7
# ORBIT backend image (API, worker, MCP). Build context: ./backend
#   docker build -t orbit-backend .
# The embedding model is downloaded at build time so the runtime works offline.

ARG PYTHON_VERSION=3.12

FROM ghcr.io/astral-sh/uv:0.12.17 AS uv

FROM python:${PYTHON_VERSION}-slim AS runtime

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

# 2. Embedding model (and optionally the cross-encoder reranker) baked into the image
ARG ORBIT_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ARG PRELOAD_RERANKER=false
ARG ORBIT_RERANKER_MODEL=jinaai/jina-reranker-v2-base-multilingual
ENV ORBIT_EMBEDDING_MODEL=${ORBIT_EMBEDDING_MODEL}
COPY docker/preload_models.py /tmp/preload_models.py
RUN python /tmp/preload_models.py \
    && rm /tmp/preload_models.py \
    && chmod -R a+rX /opt/models

# 3. Application code
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker/entrypoint.sh /usr/local/bin/orbit-entrypoint
RUN chmod 0755 /usr/local/bin/orbit-entrypoint \
    && python -m compileall -q app \
    && mkdir -p /data/objects \
    && chown -R orbit:orbit /data /app

# Runtime is offline-capable: models are loaded from the baked cache.
ENV HF_HUB_OFFLINE=1 \
    ORBIT_OBJECT_STORE_PATH=/data/objects

USER orbit
VOLUME ["/data/objects"]
EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/orbit-entrypoint"]
CMD ["api"]
