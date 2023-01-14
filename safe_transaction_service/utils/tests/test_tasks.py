from unittest import mock

from django.test import TestCase

from celery.app.task import Task as CeleryTask
from redis.exceptions import LockError

from ..tasks import (
    WORKER_STOPPED,
    configure_workers,
    only_one_running_task,
    worker_shutting_down_handler,
)


class TestTasks(TestCase):
    def test_configure_workers(self):
        configure_workers()

    def test_worker_shutting_down_handler(self):
        worker_shutting_down_handler(None, None, None)

    def test_only_one_running_task(self):
        celery_task = CeleryTask()
        celery_task.name = "Test Name"
        with only_one_running_task(celery_task):
            with self.assertRaises(LockError):
                with only_one_running_task(celery_task):
                    pass

        with mock.patch.dict(WORKER_STOPPED, {True: True}):
            with self.assertRaisesMessage(LockError, "Worker is stopping"):
                with only_one_running_task(celery_task):
                    pass
