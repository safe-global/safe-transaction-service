# SPDX-License-Identifier: FSL-1.1-MIT
from config.gunicorn import (
    gunicorn_request_timeout,
    gunicorn_worker_connections,
    gunicorn_workers,
)

max_requests = 20_000  # Restart a worker after it has processed a given number of requests (for memory leaks)
max_requests_jitter = (
    10_000  # Randomize max_requests to prevent all workers restarting at the same time
)
# graceful_timeout = 90  # https://stackoverflow.com/a/24305939
loglevel = "info"
preload_app = False  # Load application code before the worker processes are forked (problems with gevent patching)
# For timeout to work with gevent, a custom GeventWorker needs to be used
timeout = gunicorn_request_timeout

worker_class = "gunicorn_custom_workers.MyGeventWorker"  # "gevent"
worker_connections = gunicorn_worker_connections
workers = gunicorn_workers
