FROM python:3.6-slim-stretch

ENV PYTHONUNBUFFERED 1
WORKDIR /app

# Signal handling for PID1 https://github.com/krallin/tini
ENV TINI_VERSION v0.18.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

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

ENTRYPOINT ["/tini", "--"]
