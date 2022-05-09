#!/bin/bash

set -euo pipefail

# DEBUG set in .env
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi


echo "==> $(date +%H:%M:%S) ==> Installing flower for monitoring <=="
pip install 'celery[flower]'
sleep 5
echo "==> $(date +%H:%M:%S) ==> Running Celery beat <=="
exec celery -C -A config.celery_app beat -S django_celery_beat.schedulers:DatabaseScheduler --loglevel $log_level
