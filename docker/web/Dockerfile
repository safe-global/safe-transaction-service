FROM python:3.7-slim-stretch

ENV PYTHONUNBUFFERED 1
WORKDIR /app

COPY requirements.txt ./
RUN set -ex \
	&& buildDeps=" \
		build-essential \
		libssl-dev \
		" \
    && apt-get update \
    && apt-get install -y --no-install-recommends $buildDeps \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove $buildDeps \
    && rm -rf /var/lib/apt/lists/* \
    && find /usr/local \
        \( -type d -a -name test -o -name tests \) \
        -o \( -type f -a -name '*.pyc' -o -name '*.pyo' \) \
        -exec rm -rf '{}' +

COPY . .
