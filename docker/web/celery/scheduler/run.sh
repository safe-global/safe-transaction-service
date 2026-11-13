#!/bin/bash

set -euo pipefail

source "$(dirname "$0")/../../datadog_tracer.sh"

# DEBUG set in .env
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi

# Wait for migrations
sleep 10

echo "==> $(date +%H:%M:%S) ==> Running Celery beat <=="
exec "${DDTRACE_RUN[@]}" celery -C -A config.celery_app beat \
     -S django_celery_beat.schedulers:DatabaseScheduler \
     --loglevel $log_level
