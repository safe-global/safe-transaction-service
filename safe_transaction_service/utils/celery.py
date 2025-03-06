from functools import wraps
from typing import Optional

from celery.utils.log import get_task_logger
from gevent import Timeout


class TaskTimeoutException(Exception):
    pass


def task_timeout(timeout_seconds: int, raise_exception: Optional[bool] = False):
    """
    Catches Timeout exceptions and logs a clear, task-specific message.
    Ensures better tracking of hard limit errors and maintains consistent log formatting,
    improving visibility beyond Celery's generic error output.

    :param timeout_seconds:
    :param raise_exception: if True, raise TaskTimeoutException
    :return:
    """

    def decorator(func):
        @wraps(func)  # keep the name of the wrapped function
        def wrapper(*args, **kwargs):
            try:
                with Timeout(timeout_seconds):
                    return func(*args, **kwargs)
            except Timeout:
                logger = get_task_logger(func.__name__)
                logger.error("Task timeout exceeded: %i seconds", timeout_seconds)
                if raise_exception:
                    raise TaskTimeoutException()
                return None

        return wrapper

    return decorator
