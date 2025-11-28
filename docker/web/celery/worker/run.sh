#!/bin/bash

set -euo pipefail

TASK_CONCURRENCY=${CELERYD_CONCURRENCY:-5000}
PREFETCH_MULTIPLIER=${CELERYD_PREFETCH_MULTIPLIER:-2}  # Default is 4

# DEBUG set in .env_docker_compose
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi

if [ ${RUN_MIGRATIONS:-0} = 1 ]; then
  echo "==> $(date +%H:%M:%S) ==> Migrating Django models... "
  # DB_STATEMENT_TIMEOUT=0 python manage.py migrate --noinput
  # Check migration 0097 is not applied, so we don't rollback to 0096
  if python manage.py showmigrations history | grep -q '\[ \] 0097'; then
    DB_STATEMENT_TIMEOUT=0 python manage.py migrate --noinput history 0096
  fi
  SECONDS=0
  (
    echo "Starting migration 0097 for denormalization" &&
    DB_STATEMENT_TIMEOUT=0 python manage.py migrate --noinput
    echo "Migration 0097 for denormalization was successful in ${SECONDS} seconds" &&
  ) &

  echo "==> $(date +%H:%M:%S) ==> Setting up service... "
  python manage.py setup_service
fi

if [ ${ENABLE_SAFE_SETUP_CONTRACTS:-0} = 1 ]; then
  echo "==> $(date +%H:%M:%S) ==> Setting contracts... "
  python manage.py setup_safe_contracts --force-update-contracts
fi

echo "==> $(date +%H:%M:%S) ==> Check RPC connected matches previously used RPC... "
python manage.py check_chainid_matches

echo "==> $(date +%H:%M:%S) ==> Running Celery worker for queues $WORKER_QUEUES with concurrency $TASK_CONCURRENCY <=="
exec celery --no-color -A config.celery_app worker \
     --pool=gevent \
     --loglevel $log_level \
     --concurrency="${TASK_CONCURRENCY}" \
     --prefetch-multiplier="${PREFETCH_MULTIPLIER}" \
     --without-heartbeat \
     --without-gossip \
     --without-mingle -E -Q "$WORKER_QUEUES"
