#!/bin/bash

set -euo pipefail

sleep 10  # Wait for migrations
echo "==> $(date +%H:%M:%S) ==> Setting up service... "
python manage.py setup_service &

echo "==> $(date +%H:%M:%S) ==> Collecting statics... "
DOCKER_SHARED_DIR=/nginx
rm -rf $DOCKER_SHARED_DIR/*
# STATIC_ROOT=$DOCKER_SHARED_DIR/staticfiles python manage.py collectstatic --noinput &
cp -r staticfiles/ $DOCKER_SHARED_DIR/

echo "==> $(date +%H:%M:%S) ==> Send via Slack info about service version and network"
python manage.py send_slack_notification

echo "==> $(date +%H:%M:%S) ==> Running Gunicorn... "
exec gunicorn --worker-class gevent --pythonpath "$PWD" config.wsgi:application --timeout 60 --graceful-timeout 60 --log-file=- --error-logfile=- --access-logfile=- --log-level info --logger-class='safe_transaction_service.history.utils.CustomGunicornLogger' -b unix:$DOCKER_SHARED_DIR/gunicorn.socket -b 0.0.0.0:8888
