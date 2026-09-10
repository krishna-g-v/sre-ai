#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting uvicorn on ${HOST:-0.0.0.0}:${PORT:-8000}..."
exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
