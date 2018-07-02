#!/bin/bash

set -euo pipefail

docker-compose build --force-rm
docker-compose create
docker restart safe-relay-service_db_1 safe-relay-service_redis_1 safe-relay-service_ganache_1
DJANGO_DOT_ENV_FILE=.env_local pytest
