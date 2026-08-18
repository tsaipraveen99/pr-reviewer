#!/bin/sh
set -e

if [ "$SERVICE_ROLE" = "worker" ]; then
    exec uv run --no-sync celery -A prcrew.worker.celery_app.app worker --loglevel=info --concurrency="${CELERY_CONCURRENCY:-2}"
fi

exec uv run --no-sync uvicorn 'prcrew.api.app:create_app' --factory --host 0.0.0.0 --port "${PORT:-8000}"
