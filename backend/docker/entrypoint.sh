#!/bin/sh
# ORBIT backend entrypoint.
#   api     wait for Postgres, run migrations, start uvicorn (REST + MCP + /metrics)
#   worker  wait for Postgres, start the ingestion worker
#   all     api + worker in one container (single-service hosts such as Railway, sharing the object store volume)
#   migrate wait for Postgres, run migrations and exit
#   *       exec the given command (e.g. "python -m app.seed")
set -eu

wait_for_postgres() {
  python - <<'PY'
import asyncio, os, sys, time

import asyncpg

url = os.environ.get("ORBIT_DATABASE_URL", "postgresql+asyncpg://orbit:orbit@postgres:5432/orbit")
dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
deadline = time.monotonic() + float(os.environ.get("ORBIT_DB_WAIT_SECONDS", "90"))


async def main() -> int:
    attempt = 0
    while True:
        attempt += 1
        try:
            conn = await asyncpg.connect(dsn, timeout=5)
            await conn.execute("SELECT 1")
            await conn.close()
            print(f"[entrypoint] postgres ready (attempt {attempt})", flush=True)
            return 0
        except Exception as exc:  # noqa: BLE001
            if time.monotonic() > deadline:
                print(f"[entrypoint] postgres unavailable: {exc}", file=sys.stderr, flush=True)
                return 1
            await asyncio.sleep(min(5, attempt))


sys.exit(asyncio.run(main()))
PY
}

run_migrations() {
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
}

command="${1:-api}"
case "$command" in
  api)
    shift || true
    wait_for_postgres
    run_migrations
    exec uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "${ORBIT_API_PORT:-8000}" \
      --proxy-headers \
      --forwarded-allow-ips "${ORBIT_FORWARDED_ALLOW_IPS:-*}" \
      --timeout-graceful-shutdown 20 \
      "$@"
    ;;
  all)
    shift || true
    wait_for_postgres
    run_migrations
    python -m app.worker &
    worker_pid=$!
    uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "${PORT:-${ORBIT_API_PORT:-8000}}" \
      --proxy-headers \
      --forwarded-allow-ips "${ORBIT_FORWARDED_ALLOW_IPS:-127.0.0.1}" \
      --timeout-graceful-shutdown 20 \
      "$@" &
    api_pid=$!
    trap 'kill -TERM "$api_pid" "$worker_pid" 2>/dev/null' TERM INT
    # Exit (and let the platform restart us) as soon as either process stops.
    while kill -0 "$api_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null; do sleep 2; done
    kill -TERM "$api_pid" "$worker_pid" 2>/dev/null || true
    wait || true
    exit 1
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
  *)
    exec "$@"
    ;;
esac
