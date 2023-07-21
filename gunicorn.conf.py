import os

access_logfile = "-"
error_logfile = "-"
max_requests = 20_000  # Restart a worker after it has processed a given number of requests (for memory leaks)
max_requests_jitter = (
    10_000  # Randomize max_requests to prevent all workers restarting at the same time
)
# graceful_timeout = 90  # https://stackoverflow.com/a/24305939
keep_alive = 2
log_file = "-"
log_level = "info"
logger_class = "safe_transaction_service.utils.loggers.CustomGunicornLogger"
preload_app = False  # Load application code before the worker processes are forked (problems with gevent patching)
# For timeout to work with gevent, a custom GeventWorker needs to be used
timeout = os.environ("WEB_WORKER_TIMEOUT", 60)

worker_class = "gunicorn_custom_workers.MyGeventWorker"  # "gevent"
worker_connections = os.environ.get("WEB_WORKER_CONNECTIONS", 1000)
workers = os.environ.get("WEB_CONCURRENCY", 2)


def post_fork(server, worker):
    try:
        from psycogreen.gevent import patch_psycopg

        worker.log.info("Making Psycopg2 Green")
        patch_psycopg()
        worker.log.info("Made Psycopg2 Green")
    except ImportError:
        worker.log.info("Psycopg2 not patched")
