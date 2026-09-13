#!/usr/bin/env bash
set -euo pipefail

wait_for_db() {
  echo "[entrypoint] waiting for postgres at ${IS_POSTGRES_HOST:-localhost}:${IS_POSTGRES_PORT:-5432}..."
  for i in $(seq 1 60); do
    if python -c "
import socket,os
s=socket.socket(); s.settimeout(2)
s.connect((os.environ.get('IS_POSTGRES_HOST','localhost'), int(os.environ.get('IS_POSTGRES_PORT','5432'))))
s.close()
" 2>/dev/null; then
      echo "[entrypoint] postgres is reachable."
      return 0
    fi
    sleep 2
  done
  echo "[entrypoint] ERROR: postgres not reachable in time." >&2
  exit 1
}

run_migrations() {
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
}

run_bootstrap() {
  echo "[entrypoint] seeding RBAC + admin"
  python -m app.modules.iam.bootstrap
}

case "${1:-serve}" in
  serve)
    wait_for_db
    run_migrations
    run_bootstrap
    echo "[entrypoint] starting API on port ${PORT:-8000}"
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
    ;;
  migrate)
    wait_for_db
    run_migrations
    ;;
  bootstrap)
    wait_for_db
    run_bootstrap
    ;;
  worker)
    wait_for_db
    exec celery -A app.worker.celery_app.celery worker -l info --concurrency 2
    ;;
  scheduler)
    wait_for_db
    exec celery -A app.worker.celery_app.celery beat -l info
    ;;
  *)
    exec "$@"
    ;;
esac