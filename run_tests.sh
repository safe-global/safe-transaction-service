#!/bin/bash

set -euo pipefail

export DJANGO_SETTINGS_MODULE=config.settings.test
export DJANGO_DOT_ENV_FILE=.env.test
export COMPOSE_PROFILES=develop
docker compose up --detach --force-recreate --wait db redis anvil rabbitmq

python manage.py check
pytest -rxXs
