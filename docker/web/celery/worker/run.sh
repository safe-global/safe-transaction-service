#!/bin/bash

set -euo pipefail

# DEBUG set in .env_docker_compose
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi

if [ ${DJANGO_SETTINGS_MODULE} = "config.settings.production" ]; then
  export DJANGO_SETTINGS_MODULE="config.settings.production_celery"
fi

sleep 10  # Wait for migrations
echo "==> $(date +%H:%M:%S) ==> Running Celery worker <=="
exec celery -A safe_transaction_service.taskapp worker --loglevel $log_level --pool=gevent --autoscale=120,80
