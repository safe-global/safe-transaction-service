#!/bin/bash

set -euo pipefail

echo "==> Migrating Django models ... "
python manage.py migrate --noinput

echo "==> Setting up service... "
python manage.py setup_service &

echo "==> Collecting statics ... "
DOCKER_SHARED_DIR=/nginx
rm -rf $DOCKER_SHARED_DIR/*
STATIC_ROOT=$DOCKER_SHARED_DIR/staticfiles python manage.py collectstatic --noinput &

echo "==> Running Gunicorn ... "
exec gunicorn --worker-class gevent --pythonpath "$PWD" config.wsgi:application --log-file=- --error-logfile=- --access-logfile=- --log-level info --logger-class='safe_transaction_service.history.utils.CustomGunicornLogger' -b unix:$DOCKER_SHARED_DIR/gunicorn.socket -b 127.0.0.1:8888
