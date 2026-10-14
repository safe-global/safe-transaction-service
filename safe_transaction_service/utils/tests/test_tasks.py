# SPDX-License-Identifier: FSL-1.1-MIT
from unittest import mock

from django.test import TestCase

from celery.app.task import Task as CeleryTask
from redis.exceptions import LockError

from ..tasks import (
    ACTIVE_LOCKS,
    WORKER_STOPPED,
    only_one_running_task,
    worker_shutdown_handler,
    worker_shutting_down_handler,
)


class TestTasks(TestCase):
    def test_worker_shutting_down_handler(self):
        worker_shutting_down_handler(None, None, None)

    @mock.patch("safe_transaction_service.utils.tasks.close_queue_service")
    def test_worker_shutdown_handler(self, close_queue_service_mock):
        worker_shutdown_handler()
        close_queue_service_mock.assert_called_once_with()

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

    def test_only_one_running_task_removes_active_lock_on_error(self):
        celery_task = CeleryTask()
        celery_task.name = "Test Name"
        with self.assertRaises(ValueError):
            with only_one_running_task(celery_task):
                self.assertEqual(len(ACTIVE_LOCKS), 1)
                raise ValueError
        self.assertEqual(ACTIVE_LOCKS, set())
