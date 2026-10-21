# SPDX-License-Identifier: FSL-1.1-MIT
"""
Store gunicorn variables in this file, so they can be read by Django.

It must stay outside the ``config`` package, as ``gunicorn.conf.py`` imports it
(see the comment there).
"""

import os

gunicorn_request_timeout = int(os.environ.get("WEB_WORKER_TIMEOUT", 60))
gunicorn_worker_connections = int(os.environ.get("WEB_WORKER_CONNECTIONS", 100))
gunicorn_workers = int(os.environ.get("WEB_CONCURRENCY", 2))
