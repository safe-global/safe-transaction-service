from config.gunicorn import (
    gunicorn_request_timeout,
    gunicorn_worker_connections,
    gunicorn_workers,
)

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
logger_class = "safe_transaction_service.loggers.custom_logger.CustomGunicornLogger"
preload_app = False  # Load application code before the worker processes are forked (problems with gevent patching)
# For timeout to work with gevent, a custom GeventWorker needs to be used
timeout = gunicorn_request_timeout

worker_class = "gunicorn_custom_workers.MyGeventWorker"  # "gevent"
worker_connections = gunicorn_worker_connections
workers = gunicorn_workers
