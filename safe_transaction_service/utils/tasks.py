# SPDX-License-Identifier: FSL-1.1-MIT
import contextlib
from typing import Any

from django.conf import settings

from celery.app.task import Task as CeleryTask
from celery.signals import worker_shutdown, worker_shutting_down
from celery.utils.log import get_task_logger
from redis.exceptions import LockError

from ..events.services.queue_service import close_queue_service
from .redis import get_redis

logger = get_task_logger(__name__)

LOCK_TIMEOUT = settings.CELERY_TASK_LOCK_TIMEOUT
WORKER_STOPPED = set()  # Worker status


def is_worker_stopping() -> bool:
    return bool(WORKER_STOPPED)


@worker_shutting_down.connect
def worker_shutting_down_handler(sig, how, exitcode, **kwargs):
    logger.warning("Worker shutting down")
    WORKER_STOPPED.add(True)


@worker_shutdown.connect
def worker_shutdown_handler(**kwargs: Any) -> None:
    close_queue_service()


def get_task_lock_name(task_name: str, lock_name_suffix: str | None = None) -> str:
    lock_name = f"locks:tasks:{task_name}"
    if lock_name_suffix:
        lock_name += f":{lock_name_suffix}"
    return lock_name


@contextlib.contextmanager
def only_one_running_task(
    task: CeleryTask,
    lock_name_suffix: str | None = None,
    lock_timeout: int | None = LOCK_TIMEOUT,
):
    """
    Ensures one running task at the same, using `task` name as a unique key

    :param task: CeleryTask
    :param lock_name_suffix: A suffix for the lock name, in the case that the same task can be run at the same time
    when it has different arguments
    :param lock_timeout: How long the lock will be stored, in case worker is halted so key is not stored forever
    in Redis
    :return: Instance of redis `Lock`
    :raises: LockError if lock cannot be acquired
    """
    if is_worker_stopping():
        raise LockError("Worker is stopping")
    redis = get_redis()
    lock_name = get_task_lock_name(task.name, lock_name_suffix=lock_name_suffix)
    with redis.lock(lock_name, blocking=False, timeout=lock_timeout) as lock:
        yield lock
