#!/bin/bash

set -euo pipefail

docker-compose -f docker-compose.yml -f docker-compose.dev.yml build --force-rm db redis ganache
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --no-start db redis ganache
docker restart safe-transaction-service_db_1 safe-transaction-service_redis_1 safe-transaction-service_ganache_1
sleep 10
DJANGO_SETTINGS_MODULE=config.settings.test DJANGO_DOT_ENV_FILE=.env.test python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.test DJANGO_DOT_ENV_FILE=.env.test pytest -rxXs
