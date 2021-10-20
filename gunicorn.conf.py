access_logfile = "-"
error_logfile = "-"
# max_requests = 500000  # Restart a worker after it has processed a given number of requests (for memory leaks)
# graceful_timeout = 90  # https://stackoverflow.com/a/24305939
keep_alive = 2
log_file = "-"
log_level = "info"
logger_class = "safe_transaction_service.utils.loggers.CustomGunicornLogger"
preload_app = False  # Load application code before the worker processes are forked (problems with gevent patching)
timeout = 60
worker_class = "gevent"
worker_connections = 2000


def post_fork(server, worker):
    try:
        from psycogreen.gevent import patch_psycopg

        patch_psycopg()
        worker.log.info("Made Psycopg2 Green")
    except ImportError:
        worker.log.info("Psycopg2 not patched")
