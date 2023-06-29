import contextlib
from typing import Optional, Set

import gevent
from celery.app.task import Task as CeleryTask
from celery.signals import celeryd_init, worker_shutting_down
from celery.utils.log import get_task_logger
from redis.exceptions import LockError

from .redis import get_redis
from .utils import close_gevent_db_connection

logger = get_task_logger(__name__)

LOCK_TIMEOUT = 60 * 15  # 15 minutes
SOFT_TIMEOUT = 60 * 10  # 10 minutes
ACTIVE_LOCKS: Set[str] = set()  # Active redis locks, release them when worker stops
WORKER_STOPPED = set()  # Worker status


@celeryd_init.connect
def configure_workers(sender=None, conf=None, **kwargs):
    def worker_patch_psycopg():
        """
        Patch postgresql to be friendly with gevent
        """
        try:
            from psycogreen.gevent import patch_psycopg

            logger.info("Patching Celery psycopg for gevent")
            patch_psycopg()
            logger.info("Patched Celery psycopg for gevent")
        except ImportError:
            pass

    worker_patch_psycopg()


@worker_shutting_down.connect
def worker_shutting_down_handler(sig, how, exitcode, **kwargs):
    logger.warning("Worker shutting down")
    gevent.spawn(shutdown_worker)  # If not raises a `BlockingSwitchOutError`


def shutdown_worker():
    WORKER_STOPPED.add(True)
    if ACTIVE_LOCKS:
        logger.warning("Force releasing of redis locks %s", ACTIVE_LOCKS)
        get_redis().delete(*ACTIVE_LOCKS)
        logger.warning("Released redis locks")
    else:
        logger.warning("No redis locks to release")


@contextlib.contextmanager
def only_one_running_task(
    task: CeleryTask,
    lock_name_suffix: Optional[str] = None,
    blocking_timeout: int = 1,
    lock_timeout: Optional[int] = LOCK_TIMEOUT,
    gevent: bool = True,
):
    """
    Ensures one running task at the same, using `task` name as a unique key

    :param task: CeleryTask
    :param lock_name_suffix: A suffix for the lock name, in the case that the same task can be run at the same time
    when it has different arguments
    :param blocking_timeout: Waiting blocking timeout, it should be as small as possible to the worker can release
    the task
    :param lock_timeout: How long the lock will be stored, in case worker is halted so key is not stored forever
    in Redis
    :param gevent: If `True`, `close_gevent_db_connection` will be called at the end
    :return: Instance of redis `Lock`
    :raises: LockError if lock cannot be acquired
    """
    if WORKER_STOPPED:
        raise LockError("Worker is stopping")
    redis = get_redis()
    lock_name = f"locks:tasks:{task.name}"
    if lock_name_suffix:
        lock_name += f":{lock_name_suffix}"
    with redis.lock(
        lock_name, blocking_timeout=blocking_timeout, timeout=lock_timeout
    ) as lock:
        try:
            ACTIVE_LOCKS.add(lock_name)
            yield lock
            ACTIVE_LOCKS.remove(lock_name)
        finally:
            if gevent:
                # Needed for django-db-geventpool
                close_gevent_db_connection()
