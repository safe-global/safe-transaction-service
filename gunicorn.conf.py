access_logfile = '-'
error_logfile = '-'
graceful_timeout = 60
log_file = '-'
log_level = 'info'
logger_class = 'safe_transaction_service.history.utils.CustomGunicornLogger'
# max_requests = 2000  # Restart a worker after it has processed a given number of requests (for memory leaks)
preload_app = False  # Load application code before the worker processes are forked (problems with gevent patching)
timeout = 60
worker_class = 'gevent'
worker_connections = 2000


def post_fork(server, worker):
    try:
        from psycogreen.gevent import patch_psycopg
        patch_psycopg()
        worker.log.info("Made Psycopg2 Green")
    except ImportError:
        worker.log.info("Psycopg2 not patched")
