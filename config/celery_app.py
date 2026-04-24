# SPDX-License-Identifier: FSL-1.1-MIT
import os

from django.db import close_old_connections

from celery import Celery
from celery.signals import setup_logging, task_postrun


@setup_logging.connect
def on_celery_setup_logging(**kwargs):
    """
    Use Django logging instead of celery logger
    :param kwargs:
    :return:
    """
    from logging.config import dictConfig

    from django.conf import settings

    # Patch all the code to use Celery logger (if not just logs inside tasks.py are displayed with the
    # task_id and task_name). This way every log will have the context information
    if not settings.CELERY_ALWAYS_EAGER:
        for _, logger in settings.LOGGING["loggers"].items():
            key = "handlers"
            if key in logger:
                logger[key] = ["celery_console"]
        dictConfig(settings.LOGGING)


@task_postrun.connect
def close_db_connections(**kwargs):
    # Django's close_old_connections() is called automatically at the end of each web request
    # via middleware signals, but Celery tasks have no equivalent lifecycle hook.
    #
    # Without this, connections acquired via pool.getconn() during a task are never returned
    # to the psycopg3 pool via pool.putconn() — the pool exhausts its max_size slots and new
    # tasks block until max_lifetime/max_idle timers recycle them.
    #
    # NOTE: Celery 5.x has built-in pool handling for Django 5.1+ (close_pool on worker
    # process init — see https://docs.celeryq.dev/en/main/django/first-steps-with-django.html#django-connection-pool),
    # but that only covers the fork/process-start path. With --pool=gevent there is no forking:
    # all tasks run as greenlets inside a single process, so close_pool never fires and
    # per-task connection cleanup must be handled explicitly here.
    #
    # CONN_MAX_AGE=0 means close_old_connections() treats every connection as expired,
    # triggering close() → putconn() and returning the slot to the pool immediately.
    close_old_connections()


# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("safe_transaction_service")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings")
# app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
