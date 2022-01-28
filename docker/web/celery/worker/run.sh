#!/bin/bash

set -euo pipefail

# DEBUG set in .env_docker_compose
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi

echo "==> $(date +%H:%M:%S) ==> Migrating Django models... "
python manage.py migrate --noinput

echo "==> $(date +%H:%M:%S) ==> Setting up service... "
python manage.py setup_service

MAX_MEMORY_PER_CHILD="${WORKER_MAX_MEMORY_PER_CHILD:-2097152}"
echo "==> $(date +%H:%M:%S) ==> Running Celery worker with a max_memory_per_child of ${MAX_MEMORY_PER_CHILD} <=="
exec celery -C -A config.celery_app worker --loglevel $log_level --pool=gevent \
     --concurrency=${CELERYD_CONCURRENCY:-500} --max-memory-per-child=${MAX_MEMORY_PER_CHILD}
