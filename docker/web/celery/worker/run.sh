#!/bin/bash

set -euo pipefail

# DEBUG set in .env_docker_compose
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi

echo "==> Migrating Django models ... "
python manage.py migrate --noinput

echo "==> Running Celery worker <=="
exec celery -A safe_transaction_service.taskapp worker --loglevel $log_level -c 4
