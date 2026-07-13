#!/usr/bin/env bash
set -euo pipefail

alembic upgrade head
uvicorn nevo.main:app --host 0.0.0.0 --port "${PORT:-8000}"

