# SPDX-License-Identifier: FSL-1.1-MIT
"""
Store gunicorn variables in this file, so they can be read by Django
"""

import os

gunicorn_request_timeout = int(os.environ.get("WEB_WORKER_TIMEOUT", 60))
gunicorn_worker_connections = int(os.environ.get("WEB_WORKER_CONNECTIONS", 200))
gunicorn_workers = int(os.environ.get("WEB_CONCURRENCY", 2))
