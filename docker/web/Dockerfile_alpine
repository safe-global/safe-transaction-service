# Less size than Debian, slowest to build
FROM python:3-alpine3.7

ENV PYTHONUNBUFFERED 1
WORKDIR /app

COPY requirements.txt ./

# Signal handling for PID1 https://github.com/krallin/tini
RUN apk add --update --no-cache tini postgresql-client && \
    apk add --no-cache --virtual .build-dependencies postgresql-dev alpine-sdk libffi-dev autoconf automake libtool gmp-dev linux-headers && \
    pip install --no-cache-dir -r requirements.txt && \
    apk del .build-dependencies && \
    find /usr/local \
        \( -type d -a -name test -o -name tests \) \
        -o \( -type f -a -name '*.pyc' -o -name '*.pyo' \) \
        -exec rm -rf '{}' +

COPY . .

ENTRYPOINT ["/sbin/tini", "--"]
