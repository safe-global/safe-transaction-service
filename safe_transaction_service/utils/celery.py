from celery._state import get_current_task
from celery.app.log import TaskFormatter
from celery.utils.log import ColorFormatter


class PatchedCeleryFormatterOriginal(TaskFormatter):  # pragma: no cover
    """
    Patched to work as an standard logging formatter. Basic version
    """

    def __init__(self, fmt=None, datefmt=None, style="%"):
        super().__init__(fmt=fmt, use_color=True)


class PatchedCeleryFormatter(ColorFormatter):  # pragma: no cover
    def __init__(self, fmt=None, datefmt=None, style="%", use_color=False):
        super().__init__(fmt=fmt, use_color=use_color)

    def format(self, record):
        task = get_current_task()
        if task and task.request:
            # For gevent pool, task_id will be something like `7ab44cb4-aacf-444e-bc20-4cbaa2a7b082`. For logs
            # is better to get it short
            task_id = task.request.id[:8] if task.request.id else task.request.id
            # Task name usually has all the package, better cut the first part for logging
            task_name = task.name.split(".")[-1] if task.name else task.name

            record.__dict__.update(task_id=task_id, task_name=task_name)
        else:
            record.__dict__.setdefault("task_name", "???")
            record.__dict__.setdefault("task_id", "???")
        return super().format(record)
