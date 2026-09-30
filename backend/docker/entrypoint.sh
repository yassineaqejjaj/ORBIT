#!/bin/sh
# ORBIT backend entrypoint.
#   api      wait for Postgres, [migrate if ORBIT_MIGRATE_ON_START=true], start uvicorn (REST + MCP)
#   worker   wait for Postgres, start the ingestion worker (metrics + /healthz on ORBIT_METRICS_PORT)
#   migrate  wait for Postgres, run `alembic upgrade head` and exit (compose one-shot / Helm hook Job)
#   seed     load the demo dataset (demo image only; refused unless ORBIT_DEMO_MODE=true)
#   *        exec the given command (e.g. "python -m app.admin status")
#
# Secrets can be injected as files (Docker/Kubernetes secrets): every ORBIT_<NAME>_FILE variable is
# read into ORBIT_<NAME> when the latter is not already set. ORBIT_ENCRYPTION_KEY_FILE is handled
# natively by the application and is left untouched.
set -eu

log() { printf '[entrypoint] %s\n' "$*" >&2; }

load_file_secrets() {
  for pair in $(env | grep -E '^ORBIT_[A-Z0-9_]+_FILE=' | cut -d= -f1); do
    [ "$pair" = "ORBIT_ENCRYPTION_KEY_FILE" ] && continue
    target="${pair%_FILE}"
    eval "current=\${$target:-}"
    eval "path=\${$pair}"
    if [ -n "$current" ]; then
      log "$target already set, $pair ignored"
      continue
    fi
    if [ ! -r "$path" ]; then
      log "secret file for $target is not readable: $path"
      exit 64
    fi
    value="$(cat "$path")"
    export "$target=$value"
    unset "$pair"
  done
}

normalize_database_url() {
  # Accept libpq-style URLs (e.g. CloudNativePG "<cluster>-app" secret `uri`) and add the asyncpg driver.
  url="${ORBIT_DATABASE_URL:-}"
  case "$url" in
    postgres://*) export ORBIT_DATABASE_URL="postgresql+asyncpg://${url#postgres://}" ;;
    postgresql://*) export ORBIT_DATABASE_URL="postgresql+asyncpg://${url#postgresql://}" ;;
  esac
}

wait_for_postgres() {
  python - <<'PY'
import asyncio
import os
import ssl
import sys
import time
from urllib.parse import urlsplit, urlunsplit

import asyncpg

url = os.environ.get("ORBIT_DATABASE_URL", "")
if not url:
    print("[entrypoint] ORBIT_DATABASE_URL is not set", file=sys.stderr, flush=True)
    sys.exit(64)
parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://", 1))
dsn = urlunsplit(parts._replace(query=""))
mode = os.environ.get("ORBIT_DATABASE_SSLMODE", "prefer")
ca_file = os.environ.get("ORBIT_DATABASE_CA_CERTS", "")
ssl_arg: object = mode
if mode in {"verify-ca", "verify-full"}:
    context = ssl.create_default_context(cafile=ca_file or None)
    context.check_hostname = mode == "verify-full"
    ssl_arg = context
deadline = time.monotonic() + float(os.environ.get("ORBIT_DB_WAIT_SECONDS", "120"))


async def main() -> int:
    attempt = 0
    while True:
        attempt += 1
        try:
            conn = await asyncpg.connect(dsn, timeout=5, ssl=ssl_arg)
            await conn.execute("SELECT 1")
            await conn.close()
            print(f"[entrypoint] postgres ready (attempt {attempt}, sslmode={mode})", file=sys.stderr, flush=True)
            return 0
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready yet"
            if time.monotonic() > deadline:
                print(f"[entrypoint] postgres unavailable: {type(exc).__name__}", file=sys.stderr, flush=True)
                return 1
            await asyncio.sleep(min(5, attempt))


sys.exit(asyncio.run(main()))
PY
}

run_migrations() {
  log "alembic upgrade head"
  alembic upgrade head
}

truthy() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1 | true | yes | on) return 0 ;;
    *) return 1 ;;
  esac
}

load_file_secrets
normalize_database_url

command="${1:-api}"
case "$command" in
  api)
    shift || true
    wait_for_postgres
    if truthy "${ORBIT_MIGRATE_ON_START:-false}"; then
      run_migrations
    fi
    exec uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "${ORBIT_API_PORT:-8000}" \
      --workers "${ORBIT_API_WORKERS:-2}" \
      --proxy-headers \
      --forwarded-allow-ips "${ORBIT_TRUSTED_PROXIES:-127.0.0.1}" \
      --no-server-header \
      --timeout-keep-alive "${ORBIT_API_KEEPALIVE_SECONDS:-15}" \
      --timeout-graceful-shutdown "${ORBIT_API_GRACEFUL_SECONDS:-20}" \
      "$@"
    ;;
  worker)
    shift || true
    wait_for_postgres
    exec python -m app.worker "$@"
    ;;
  migrate)
    wait_for_postgres
    run_migrations
    ;;
  seed)
    shift || true
    if ! truthy "${ORBIT_DEMO_MODE:-false}"; then
      log "seed refused: ORBIT_DEMO_MODE must be true (demo environments only)"
      exit 64
    fi
    if [ ! -d /app/app/seed/data ]; then
      log "seed refused: this is a runtime image without demo data (build the 'demo' target)"
      exit 64
    fi
    exec python -m app.seed "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
