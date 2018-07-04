#!/bin/bash

set -euo pipefail

docker-compose build --force-rm
docker-compose create
docker restart safe-transaction-history_db_1 safe-transaction-history_redis_1 safe-transaction-history_ganache_1
DJANGO_DOT_ENV_FILE=.env_local pytest
