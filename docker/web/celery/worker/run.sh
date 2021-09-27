#!/bin/bash

set -euo pipefail

# DEBUG set in .env_docker_compose
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi

sleep 10  # Wait for migrations
echo "==> $(date +%H:%M:%S) ==> Running Celery worker <=="
exec celery -A config.celery_app worker --loglevel $log_level --pool=gevent --concurrency=120
