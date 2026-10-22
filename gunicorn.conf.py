# SPDX-License-Identifier: FSL-1.1-MIT
import os

from gunicorn.arbiter import Arbiter
from gunicorn.workers.base import Worker

# Do not import the `config` package here: it imports Celery, and this file runs
# in the gunicorn master, before the gevent worker applies monkey patching

max_requests = 100_000  # Restart a worker after it has processed a given number of requests (for memory leaks)
max_requests_jitter = (
    50_000  # Randomize max_requests to prevent all workers restarting at the same time
)
# graceful_timeout = 90  # https://stackoverflow.com/a/24305939
loglevel = "info"
preload_app = False  # Load application code before the worker processes are forked (problems with gevent patching)
# For timeout to work with gevent, a custom GeventWorker needs to be used
timeout = int(os.environ.get("WEB_WORKER_TIMEOUT", 60))

worker_class = "gunicorn_custom_workers.MyGeventWorker"  # "gevent"
worker_connections = int(os.environ.get("WEB_WORKER_CONNECTIONS", 100))
workers = int(os.environ.get("WEB_CONCURRENCY", 2))


def worker_exit(server: Arbiter, worker: Worker) -> None:
    # Django is only loaded in the worker (`preload_app = False`)
    from safe_transaction_service.events.services.queue_service import (
        close_queue_service,
    )

    close_queue_service()
