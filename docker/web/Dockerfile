FROM python:3.13-slim

ARG APP_HOME=/app
WORKDIR ${APP_HOME}
ENV PYTHONUNBUFFERED=1

# https://eth-hash.readthedocs.io/en/latest/quickstart.html#specify-backend-by-environment-variable
# `pysha3` is way faster than `pycryptodome` for CPython
ENV ETH_HASH_BACKEND=pysha3

# Install uv — copy binary from official image, no pip bootstrap needed
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV VIRTUAL_ENV=${APP_HOME}/.venv
ENV PATH="${APP_HOME}/.venv/bin:${PATH}"

COPY pyproject.toml uv.lock ./
RUN set -ex \
	&& buildDeps=" \
		build-essential \
        git \
		libssl-dev \
        libpq-dev \
		" \
    && apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends $buildDeps tmux postgresql-client \
    && uv sync --no-dev --frozen --no-install-project \
    && apt-get purge -y --auto-remove $buildDeps \
    && rm -rf /var/lib/apt/lists/*

# /nginx mount point must be created before so it doesn't have root permissions
# ${APP_HOME} root folder will not be updated by COPY --chown, so permissions need to be adjusted
RUN groupadd -g 999 python && \
    useradd -u 999 -r -g python python && \
    mkdir -p /nginx && \
    chown -R python:python /nginx ${APP_HOME}
COPY --chown=python:python . .

# Use numeric ids so kubernetes identifies the user correctly
USER 999:999

RUN DJANGO_SETTINGS_MODULE=config.settings.production DJANGO_DOT_ENV_FILE=.env.tracing.sample python manage.py collectstatic --noinput
