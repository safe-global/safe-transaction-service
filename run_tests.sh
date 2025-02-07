#!/bin/bash

set -euo pipefail

export DJANGO_SETTINGS_MODULE=config.settings.test
export DJANGO_DOT_ENV_FILE=.env.test
export COMPOSE_PROFILES=develop
docker compose build --force-rm db redis ganache rabbitmq
docker compose up --no-start --force-recreate db redis ganache rabbitmq
docker compose start db redis ganache rabbitmq

python manage.py check
pytest -rxXs
