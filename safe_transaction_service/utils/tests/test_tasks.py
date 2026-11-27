# SPDX-License-Identifier: FSL-1.1-MIT
from unittest import mock

from django.test import TestCase

from celery.app.task import Task as CeleryTask
from redis.exceptions import LockError

from ..redis import get_redis
from ..tasks import (
    WORKER_STOPPED,
    get_task_lock_name,
    is_worker_stopping,
    only_one_running_task,
    worker_shutdown_handler,
    worker_shutting_down_handler,
)


class TestTasks(TestCase):
    def setUp(self):
        self.celery_task = CeleryTask()
        self.celery_task.name = "Test Name"

    def tearDown(self):
        WORKER_STOPPED.discard(True)

    def test_worker_shutting_down_handler(self):
        """
        Shutdown start blocks new task locks and keeps the locks of running tasks
        until they end
        """
        lock_name = get_task_lock_name(self.celery_task.name)
        with only_one_running_task(self.celery_task):
            worker_shutting_down_handler(None, None, None)
            self.assertTrue(is_worker_stopping())
            self.assertTrue(get_redis().exists(lock_name))
            with self.assertRaisesMessage(LockError, "Worker is stopping"):
                with only_one_running_task(self.celery_task, lock_name_suffix="2"):
                    pass
            self.assertTrue(get_redis().exists(lock_name))
        self.assertFalse(get_redis().exists(lock_name))

    @mock.patch("safe_transaction_service.utils.tasks.close_queue_service")
    def test_worker_shutdown_handler(self, close_queue_service_mock):
        worker_shutdown_handler()
        close_queue_service_mock.assert_called_once_with()

    def test_only_one_running_task(self):
        with only_one_running_task(self.celery_task):
            with self.assertRaises(LockError):
                with only_one_running_task(self.celery_task):
                    pass
