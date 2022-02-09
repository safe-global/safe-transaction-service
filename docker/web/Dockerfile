FROM python:3.10-slim

ARG APP_HOME=/app
WORKDIR ${APP_HOME}
ENV PYTHONUNBUFFERED 1

COPY requirements.txt ./
RUN set -ex \
	&& buildDeps=" \
		build-essential \
        git \
		libssl-dev \
        libpq-dev \
		" \
    && apt-get update \
    && apt-get install -y --no-install-recommends $buildDeps tmux postgresql-client \
    && pip install -U --no-cache-dir wheel setuptools pip \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove $buildDeps \
    && rm -rf /var/lib/apt/lists/* \
    && find /usr/local \
        \( -type d -a -name test -o -name tests \) \
        -o \( -type f -a -name '*.pyc' -o -name '*.pyo' \) \
        -exec rm -rf '{}' +

COPY . .
RUN DJANGO_SETTINGS_MODULE=config.settings.local DJANGO_DOT_ENV_FILE=.env.local python manage.py collectstatic --noinput
