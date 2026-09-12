#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8000}"

wait_for_db() {
  echo "[entrypoint] waiting for postgres at ${IS_POSTGRES_HOST}:${IS_POSTGRES_PORT}..."
  until python - <<'PY'
import os
import socket

host = os.environ["IS_POSTGRES_HOST"]
port = int(os.environ["IS_POSTGRES_PORT"])

try:
    with socket.create_connection((host, port), timeout=3):
        pass
except OSError:
    raise SystemExit(1)
PY
  do
    sleep 2
  done
  echo "[entrypoint] postgres is reachable."
}

run_migrations() {
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
}

seed_rbac() {
  echo "[entrypoint] seeding RBAC + admin"
  python -m app.db.seed
}

serve() {
  wait_for_db
  run_migrations
  seed_rbac

  echo "[entrypoint] starting API on port ${PORT}"
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
}

case "${1:-serve}" in
  serve)
    serve
    ;;
  *)
    exec "$@"
    ;;
esac