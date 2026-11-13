#!/bin/bash

set -euo pipefail

source "$(dirname "$0")/../../datadog_tracer.sh"

echo "==> $(date +%H:%M:%S) ==> Running Celery flower <=="
exec "${DDTRACE_RUN[@]}" celery -C -A config.celery_app flower
