# SPDX-License-Identifier: FSL-1.1-MIT
# Import the Celery app with the `config` package (Django settings, wsgi), so
# shared_task uses it.
from .celery_app import app as celery_app

__all__ = ("celery_app",)
