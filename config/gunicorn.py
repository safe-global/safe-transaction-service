"""
Store gunicorn variables in this file, so they can be read by Django
"""

import os

gunicorn_request_timeout = os.environ.get("WEB_WORKER_TIMEOUT", 60)
gunicorn_worker_connections = os.environ.get("WEB_WORKER_CONNECTIONS", 1000)
gunicorn_workers = os.environ.get("WEB_CONCURRENCY", 2)
