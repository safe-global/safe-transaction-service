# SPDX-License-Identifier: FSL-1.1-MIT
from celery import Celery
from celery.signals import setup_logging, task_postrun

from safe_transaction_service.utils.database import (
    close_unusable_or_obsolete_connections,
)


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
    if not settings.CELERY_TASK_ALWAYS_EAGER:
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
    close_unusable_or_obsolete_connections()


app = Celery("safe_transaction_service")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix and use Celery's modern lowercase
#   setting names (uppercased), e.g. `CELERY_TASK_ALWAYS_EAGER` for
#   `task_always_eager`. Pre-4.0 aliases like `CELERY_ALWAYS_EAGER`
#   are silently ignored.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
