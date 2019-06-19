#!/bin/bash

set -euo pipefail

docker-compose build --force-rm
docker-compose create
docker restart safe-transaction-service_db_1 safe-transaction-service_redis_1 safe-transaction-service_ganache_1
DJANGO_DOT_ENV_FILE=.env_local pytest
