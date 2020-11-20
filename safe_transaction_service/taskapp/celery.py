import logging
import os

from django.apps import AppConfig, apps
from django.conf import settings

from celery import Celery
from celery._state import get_current_task
from celery.app.log import TaskFormatter
from celery.signals import setup_logging
from celery.utils.log import ColorFormatter

logger = logging.getLogger(__name__)


if not settings.configured:
    # set the default Django settings module for the 'celery' program.
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')  # pragma: no cover


app = Celery('safe_transaction_service')


class CeleryConfig(AppConfig):
    name = 'safe_transaction_service.taskapp'
    verbose_name = 'Celery Config'

    # Use Django logging instead of celery logger
    @setup_logging.connect
    def on_celery_setup_logging(**kwargs):
        pass

    # @after_setup_logger.connect
    # def setup_loggers(logger, *args, **kwargs):
    #     formatter = TaskFormatter('%(asctime)s [%(levelname)s] [%(processName)s] %(message)s')
    #     handler = logger.handlers[0]
    #     # handler = logging.StreamHandler()
    #     handler.setFormatter(formatter)
    #     # print(logger.handlers)
    #     # logger.addHandler(handler)

    def ready(self):
        # Using a string here means the worker will not have to
        # pickle the object when using Windows.
        app.config_from_object('django.conf:settings')
        installed_apps = [app_config.name for app_config in apps.get_app_configs()]
        app.autodiscover_tasks(lambda: installed_apps, force=True)


class IgnoreSucceededNone(logging.Filter):
    """
    Ignore the messages of the style (usually emitted when redis lock is active)
    `Task safe_transaction_service.history.tasks.index_internal_txs_task[89ad3c46-aeb3-48a1-bd6f-2f3684323ca8]
    succeeded in 1.0970600529108196s: None`
    """
    def filter(self, rec: logging.LogRecord):
        message = rec.getMessage()
        return not ('Task' in message and 'succeeded' in message and 'None' in message)


class PatchedCeleryFormatterOriginal(TaskFormatter):
    """
    Patched to work as an standard logging formatter. Basic version
    """
    def __init__(self, fmt=None, datefmt=None, style='%'):
        super().__init__(fmt=fmt, use_color=True)


class PatchedCeleryFormatter(ColorFormatter):
    def __init__(self, fmt=None, datefmt=None, style='%'):
        super().__init__(fmt=fmt, use_color=True)

    def format(self, record):
        task = get_current_task()
        if task and task.request:
            # For gevent pool, task_id will be something like `7ab44cb4-aacf-444e-bc20-4cbaa2a7b082`. For logs
            # is better to get it short
            task_id = task.request.id[:8]
            # Task name usually has all the package, better cut the first part for logging
            task_name = task.name.split('.')[-1]

            record.__dict__.update(task_id=task_id,
                                   task_name=task_name)
        else:
            record.__dict__.setdefault('task_name', '???')
            record.__dict__.setdefault('task_id', '???')
        return ColorFormatter.format(self, record)
