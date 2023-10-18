#!/bin/bash

set -euo pipefail

MAX_MEMORY_PER_CHILD="${WORKER_MAX_MEMORY_PER_CHILD:-2097152}"
MAX_TASKS_PER_CHILD="${MAX_TASKS_PER_CHILD:-1000000}"
TASK_CONCURRENCY="${CELERYD_CONCURRENCY:-1000}"

# DEBUG set in .env_docker_compose
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi

if [ ${RUN_MIGRATIONS:-0} = 1 ]; then
  echo "==> $(date +%H:%M:%S) ==> Migrating Django models... "
  python manage.py migrate --noinput

  echo "==> $(date +%H:%M:%S) ==> Setting up service... "
  python manage.py setup_service

  echo "==> $(date +%H:%M:%S) ==> Setting contracts... "
  python manage.py update_safe_contracts_logo
fi

echo "==> $(date +%H:%M:%S) ==> Check RPC connected matches previously used RPC... "
python manage.py check_chainid_matches

# Run Celery as root
export C_FORCE_ROOT=true

echo "==> $(date +%H:%M:%S) ==> Running Celery worker with a max_memory_per_child of ${MAX_MEMORY_PER_CHILD} <=="
exec celery -C -A config.celery_app worker \
     --loglevel $log_level --pool=gevent \
     --concurrency=${TASK_CONCURRENCY} \
     --max-memory-per-child=${MAX_MEMORY_PER_CHILD} \
     --max-tasks-per-child=${MAX_TASKS_PER_CHILD} \
     --without-heartbeat --without-gossip \
     --without-mingle -Q "$WORKER_QUEUES"
