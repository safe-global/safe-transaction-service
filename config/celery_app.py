import os

from celery import Celery
from celery.signals import setup_logging


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
