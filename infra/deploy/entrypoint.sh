#!/bin/sh
# proofstand orchestrator container entrypoint (T-070).
#   serve    (default) run migrations, then the API
#   migrate  run `alembic upgrade head` and exit
#   <other>  exec it verbatim (debug shell etc.)
set -e

PORT="${PORT:-${ORCHESTRATOR_PORT:-8088}}"

case "${1:-serve}" in
  migrate)
    exec alembic upgrade head
    ;;
  serve)
    echo "[entrypoint] alembic upgrade head"
    alembic upgrade head
    echo "[entrypoint] uvicorn on 0.0.0.0:${PORT}"
    exec uvicorn orchestrator.main:app --host 0.0.0.0 --port "${PORT}"
    ;;
  *)
    exec "$@"
    ;;
esac
