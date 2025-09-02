import contextlib
from typing import Optional, Set

from django.conf import settings

import gevent
from celery.app.task import Task as CeleryTask
from celery.signals import worker_shutting_down
from celery.utils.log import get_task_logger
from redis.exceptions import LockError

from .redis import get_redis

logger = get_task_logger(__name__)

LOCK_TIMEOUT = settings.CELERY_TASK_LOCK_TIMEOUT
ACTIVE_LOCKS: Set[str] = set()  # Active redis locks, release them when worker stops
WORKER_STOPPED = set()  # Worker status


@worker_shutting_down.connect
def worker_shutting_down_handler(sig, how, exitcode, **kwargs):
    logger.warning("Worker shutting down")
    gevent.spawn(
        release_locks_on_worker_shutdown
    )  # If not raises a `BlockingSwitchOutError`


def release_locks_on_worker_shutdown():
    WORKER_STOPPED.add(True)
    if ACTIVE_LOCKS:
        logger.warning("Force releasing of redis locks %s", ACTIVE_LOCKS)
        get_redis().delete(*ACTIVE_LOCKS)
        logger.warning("Released redis locks")
    else:
        logger.warning("No redis locks to release")


def get_task_lock_name(task_name: str, lock_name_suffix: Optional[str] = None) -> str:
    lock_name = f"locks:tasks:{task_name}"
    if lock_name_suffix:
        lock_name += f":{lock_name_suffix}"
    return lock_name


@contextlib.contextmanager
def only_one_running_task(
    task: CeleryTask,
    lock_name_suffix: Optional[str] = None,
    lock_timeout: Optional[int] = LOCK_TIMEOUT,
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
    if WORKER_STOPPED:
        raise LockError("Worker is stopping")
    redis = get_redis()
    lock_name = get_task_lock_name(task.name, lock_name_suffix=lock_name_suffix)
    with redis.lock(lock_name, blocking=False, timeout=lock_timeout) as lock:
        ACTIVE_LOCKS.add(lock_name)
        yield lock
        ACTIVE_LOCKS.remove(lock_name)
