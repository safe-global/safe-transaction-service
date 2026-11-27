# Dependabot only updates image versions in FROM lines
FROM ghcr.io/astral-sh/uv:0.13.10 AS uv

FROM python:3.15.1-slim AS prod-deps
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
RUN --mount=type=cache,id=uv,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project --compile-bytecode --link-mode=copy --no-python-downloads

FROM python:3.15.1-slim AS production

# The python image ships the stdlib without bytecode, and the app user cannot write
# __pycache__ in /usr/local. pip in the base site-packages is not used.
RUN python -m compileall -q -j0 -x '/site-packages/' /usr/local/lib

# /nginx is shared with the nginx container (static files and the app socket)
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends postgresql-client tmux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 999 python \
    && useradd -u 999 -r -g python python \
    && mkdir /nginx \
    && chown python:python /nginx

ENV PYTHONUNBUFFERED=1 \
    GUNICORN_CMD_ARGS=--no-control-socket \
    PATH="/app/.venv/bin:${PATH}"
WORKDIR /app

COPY --from=prod-deps /app/.venv ./.venv
COPY . .
RUN DJANGO_SETTINGS_MODULE=config.settings.production DJANGO_DOT_ENV_FILE=.env.tracing.sample python manage.py collectstatic --noinput && install -d -o python -g python safe_transaction_service/media
# The app user cannot write __pycache__ in /app
RUN python -m compileall -q -x '/\.venv/' .

# Use numeric ids so kubernetes identifies the user correctly
USER 999:999
EXPOSE 8888

# Declared last so a new commit does not invalidate the cached layers above
ARG BUILD_COMMIT
ENV BUILD_COMMIT=${BUILD_COMMIT}
