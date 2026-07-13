#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set. Attach a Render Postgres database or set DATABASE_URL to the internal connection string." >&2
  exit 1
fi

alembic upgrade head
uvicorn nevo.main:app --host 0.0.0.0 --port "${PORT:-8000}"
